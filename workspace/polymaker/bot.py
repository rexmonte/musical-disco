"""
bot.py — Production Polymarket Market Maker Bot
================================================
Strategy: Post-only maker orders (zero fees + USDC rebates)
Model: Avellaneda-Stoikov with VPIN kill switch
Deployment: Run directly or via launchd (see com.rex.polymaker.plist)

Usage:
    python bot.py [--dry-run] [--markets N] [--size USD]

--dry-run: Quote without placing orders (safe testing mode)
--markets: How many markets to trade simultaneously (default: 5)
--size: USD per order side (default: from .env)
"""

import argparse
import asyncio
import logging
import os
import signal
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

from dotenv import load_dotenv

# Load config
load_dotenv(Path(__file__).parent / ".env")
_secrets = Path(__file__).parent / "../.secrets/wallet.env"
if _secrets.exists():
    load_dotenv(_secrets, override=True)

from auth import get_client
from markets import find_maker_markets
from strategy import ASQuoteEngine
from ws_feed import MarketFeed, FillUpdate

from py_clob_client.clob_types import OrderArgs, OrderType, TradeParams
from py_clob_client.order_builder.constants import BUY, SELL

# ── Logging ───────────────────────────────────────────────────────────────────

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    handlers=[
        logging.StreamHandler(sys.stdout),
        logging.FileHandler(Path(__file__).parent / "bot.log", mode="a"),
    ],
)
logger = logging.getLogger("polymaker")


# ── Config ────────────────────────────────────────────────────────────────────

MAX_POSITION_USD = float(os.getenv("MAX_POSITION_USD", "50.0"))
ORDER_SIZE_USD = float(os.getenv("ORDER_SIZE_USD", "5.0"))
QUOTE_REFRESH_SEC = int(os.getenv("QUOTE_REFRESH_SEC", "30"))
NUM_MARKETS = int(os.getenv("NUM_MARKETS", "5"))
MIN_REQUOTE_SEC = float(os.getenv("MIN_REQUOTE_SEC", "2.0"))
MID_THRESHOLD = float(os.getenv("MID_THRESHOLD", "0.005"))


# ── Inventory Tracker ─────────────────────────────────────────────────────────

class InventoryTracker:
    """Tracks net USD position per market token and fill P&L."""

    def __init__(self):
        self._positions: dict[str, float] = {}  # token_id -> net USD
        self._fill_count: int = 0
        self._buy_usd: float = 0.0
        self._sell_usd: float = 0.0

    def get(self, token_id: str) -> float:
        return self._positions.get(token_id, 0.0)

    def update(self, token_id: str, delta_usd: float) -> None:
        self._positions[token_id] = self._positions.get(token_id, 0.0) + delta_usd

    def record_fill(self, side: str, usd: float) -> None:
        self._fill_count += 1
        if side == "BUY":
            self._buy_usd += usd
        else:
            self._sell_usd += usd

    @property
    def total_fills(self) -> int:
        return self._fill_count

    def summary(self) -> dict:
        return {
            "positions": {k: round(v, 2) for k, v in self._positions.items() if abs(v) > 0.01},
            "fills": self._fill_count,
            "bought_usd": round(self._buy_usd, 2),
            "sold_usd": round(self._sell_usd, 2),
            "net_pnl": round(self._sell_usd - self._buy_usd, 2),
        }


# ── Order Manager ─────────────────────────────────────────────────────────────

class OrderManager:
    """Wraps py-clob-client for order placement and cancellation."""

    def __init__(self, client, dry_run: bool = False):
        self.client = client
        self.dry_run = dry_run
        self._active_orders: dict[str, list[str]] = {}  # token_id -> [order_ids]
        self._seen_fills: set[str] = set()  # fill/trade IDs already processed

    def cancel_market_orders(self, token_id: str) -> None:
        """Cancel all resting orders for a token (batch + server-side fallback)."""
        order_ids = self._active_orders.get(token_id, [])
        if not order_ids:
            return

        if self.dry_run:
            logger.info(f"[DRY-RUN] Would cancel {len(order_ids)} orders for {token_id[:16]}...")
            self._active_orders[token_id] = []
            return

        try:
            # Batch cancel by order IDs
            self.client.cancel_orders(order_ids)
            logger.debug(f"Batch-cancelled {len(order_ids)} orders for {token_id[:16]}...")
        except Exception as e:
            logger.warning(f"Batch cancel failed for {token_id[:16]}...: {e}")

        try:
            # Belt-and-suspenders: server-side cancel all for this asset
            self.client.cancel_market_orders(asset_id=token_id)
        except Exception as e:
            logger.warning(f"Server-side cancel failed for {token_id[:16]}...: {e}")

        # Only clear tracking after both attempts
        self._active_orders[token_id] = []

    def check_fills(self, token_id: str, inventory: 'InventoryTracker') -> list[dict]:
        """Check for new fills on a token and update inventory."""
        if self.dry_run:
            return []
        try:
            trades = self.client.get_trades(params=TradeParams(asset_id=token_id))
            if not trades:
                return []
            new_fills = []
            for t in trades:
                tid = t.get("id") or t.get("tradeID") or ""
                if not tid or tid in self._seen_fills:
                    continue
                self._seen_fills.add(tid)
                side = t.get("side", "").upper()
                price = float(t.get("price", 0))
                size = float(t.get("size", 0))
                usd = price * size
                # BUY = we acquired shares (spent USD), SELL = we sold shares (received USD)
                delta = -usd if side == "BUY" else usd
                inventory.update(token_id, delta)
                inventory.record_fill(side, usd)
                new_fills.append({"side": side, "price": price, "size": size, "usd": usd})
                logger.info(f"Fill: {side} {size:.1f}@{price:.3f} (${usd:.2f}) token={token_id[:16]}...")
            return new_fills
        except Exception as e:
            logger.warning(f"Fill check failed for {token_id[:16]}...: {e}")
            return []

    def place_limit_post_only(
        self,
        token_id: str,
        side: str,  # BUY or SELL
        price: float,
        size_usd: float,
        tick_size: float = 0.01,
        min_size: float = 1.0,
    ) -> Optional[str]:
        """
        Place a post-only GTC limit order.
        Returns order_id or None on failure.
        """
        # Round price to tick
        price = round(round(price / tick_size) * tick_size, 4)

        # Size in shares = USD / price (for BUY YES) or USD / (1-price) (for SELL YES)
        if side == BUY:
            size_shares = size_usd / price if price > 0 else 0
        else:
            size_shares = size_usd / (1.0 - price) if price < 1.0 else 0

        # Cap shares to prevent explosion at extreme prices (e.g. 5.0/0.01 = 500)
        max_shares = size_usd * 10
        size_shares = min(size_shares, max_shares)
        size_shares = max(min_size, round(size_shares, 1))

        if self.dry_run:
            logger.info(
                f"[DRY-RUN] {side} {size_shares:.1f} shares @ {price:.3f} "
                f"token={token_id[:16]}..."
            )
            return f"dry-{token_id[:8]}-{side}-{int(time.time())}"

        try:
            order_args = OrderArgs(
                price=price,
                size=size_shares,
                side=side,
                token_id=token_id,
            )
            signed = self.client.create_order(order_args)
            resp = self.client.post_order(signed, OrderType.GTC, post_only=True)

            order_id = resp.get("orderID") or resp.get("order_id")
            if order_id:
                self._active_orders.setdefault(token_id, []).append(order_id)
                logger.info(
                    f"Order placed: {side} {size_shares:.1f}@{price:.3f} "
                    f"id={order_id[:12]} token={token_id[:16]}..."
                )
                return order_id
            else:
                logger.warning(f"Order response missing ID: {resp}")
                return None
        except Exception as e:
            logger.error(f"Order placement failed ({side} @ {price:.3f}): {e}")
            return None


# ── Market Loop ───────────────────────────────────────────────────────────────

class MarketLoop:
    """
    Manages quoting for a single market.
    Event-driven: requotes on WS midpoint changes, falls back to REST polling.
    """

    def __init__(
        self,
        market: dict,
        engine: ASQuoteEngine,
        inventory: InventoryTracker,
        order_mgr: OrderManager,
        size_usd: float,
        feed: Optional['MarketFeed'] = None,
    ):
        self.market = market
        self.engine = engine
        self.inventory = inventory
        self.order_mgr = order_mgr
        self.size_usd = size_usd
        self.feed = feed
        self.token_yes = market["token_yes"]
        self.token_no = market["token_no"]
        self.cycles = 0
        self._last_requote: float = 0.0
        self._running = False

    async def run(self) -> None:
        """Event-driven loop: wait for WS mid update or REST fallback on timeout."""
        self._running = True
        question_short = self.market["question"][:50]

        while self._running:
            try:
                # Wait for WS mid update, or fall back to REST after timeout
                ws_update = False
                if self.feed:
                    ws_update = await self.feed.wait_for_update(
                        self.token_yes, timeout=QUOTE_REFRESH_SEC
                    )

                    # Process WS fills before requoting
                    await self._process_ws_fills()
                else:
                    await asyncio.sleep(QUOTE_REFRESH_SEC)

                # Rate-limit requotes
                now = time.time()
                elapsed = now - self._last_requote
                if elapsed < MIN_REQUOTE_SEC:
                    await asyncio.sleep(MIN_REQUOTE_SEC - elapsed)

                # Get midpoint: prefer WS cached, fall back to REST
                mid = None
                if self.feed:
                    mid = self.feed.get_mid(self.token_yes)
                    if mid is not None:
                        source = "WS" if ws_update else "WS-cached"

                if mid is None:
                    # REST fallback
                    try:
                        mid_data = self.order_mgr.client.get_midpoint(self.token_yes)
                        mid = float(mid_data.get("mid", self.market.get("mid", 0.5)))
                        source = "REST"
                    except Exception as e:
                        logger.warning(f"[{question_short}] midpoint fetch failed: {e}")
                        continue

                await self._requote(mid, source)

                # REST fill reconciliation every 5th cycle
                if self.cycles % 5 == 0:
                    self._reconcile_fills_rest()

            except asyncio.CancelledError:
                return
            except Exception as e:
                logger.error(f"Loop error for {question_short}: {e}")
                await asyncio.sleep(QUOTE_REFRESH_SEC)

    def stop(self):
        self._running = False

    async def _requote(self, mid: float, source: str = "REST") -> None:
        """Generate and place quotes for given midpoint."""
        self.cycles += 1
        self._last_requote = time.time()
        token = self.token_yes
        question_short = self.market["question"][:50]

        inv = self.inventory.get(token)
        days = self.market.get("days_to_close", 30.0)
        T = min(1.0, max(0.01, days / 30.0))

        quote = self.engine.quote(mid=mid, inventory_usd=inv, time_remaining_fraction=T)

        if quote is None:
            vpin_status = self.engine.vpin.status()
            if vpin_status["toxic"]:
                logger.warning(
                    f"[{question_short}] VPIN={vpin_status['vpin']:.3f} TOXIC — skipping"
                )
            else:
                logger.info(f"[{question_short}] No quote (inventory limit or VPIN)")
            self.order_mgr.cancel_market_orders(token)
            self.order_mgr.cancel_market_orders(self.token_no)
            return

        logger.info(
            f"[{question_short}] "
            f"mid={mid:.3f}({source}) res={quote.reservation:.3f} "
            f"bid={quote.bid:.3f} ask={quote.ask:.3f} "
            f"spread={quote.spread:.3f} inv=${inv:.1f}"
        )

        self.order_mgr.cancel_market_orders(token)
        self.order_mgr.cancel_market_orders(self.token_no)

        self.order_mgr.place_limit_post_only(
            token_id=token,
            side=BUY,
            price=quote.bid,
            size_usd=self.size_usd,
            tick_size=self.market.get("tick_size", 0.01),
            min_size=self.market.get("min_order_size", 1.0),
        )
        self.order_mgr.place_limit_post_only(
            token_id=self.token_no,
            side=BUY,
            price=round(1.0 - quote.ask, 4),
            size_usd=self.size_usd,
            tick_size=self.market.get("tick_size", 0.01),
            min_size=self.market.get("min_order_size", 1.0),
        )

        # Periodic P&L summary (every 10 cycles)
        if self.cycles % 10 == 0:
            pnl = self.inventory.summary()
            total_fills = self.inventory.total_fills
            if pnl or total_fills:
                logger.info(
                    f"[{question_short}] === P&L Summary (cycle {self.cycles}) === "
                    f"fills={total_fills} positions={pnl}"
                )

    async def _process_ws_fills(self) -> None:
        """Drain WS fill queues for both tokens and update inventory/VPIN."""
        if not self.feed:
            return

        all_fills: list[FillUpdate] = []
        for tid in (self.token_yes, self.token_no):
            all_fills.extend(await self.feed.get_fills(tid))

        for f in all_fills:
            usd = f.price * f.size
            delta = -usd if f.side == "BUY" else usd
            self.inventory.update(f.token_id, delta)
            self.inventory.record_fill(f.side, usd)
            self.engine.vpin.add_trade(f.price, f.size, f.side == "BUY")
            # Mark as seen for REST dedup
            self.order_mgr._seen_fills.add(f.trade_id)

        if all_fills:
            question_short = self.market["question"][:50]
            vpin_status = self.engine.vpin.status()
            logger.info(
                f"[{question_short}] VPIN={vpin_status['vpin']:.3f} "
                f"trades={vpin_status['trades_in_window']} toxic={vpin_status['toxic']}"
            )

    def _reconcile_fills_rest(self) -> None:
        """REST fill check for reconciliation (catches any WS misses)."""
        fills = self.order_mgr.check_fills(self.token_yes, self.inventory)
        fills_no = self.order_mgr.check_fills(self.token_no, self.inventory)
        all_fills = fills + fills_no
        for f in all_fills:
            self.engine.vpin.add_trade(f["price"], f["size"], f["side"] == "BUY")
        if all_fills:
            question_short = self.market["question"][:50]
            vpin_status = self.engine.vpin.status()
            logger.info(
                f"[{question_short}] REST reconciliation: {len(all_fills)} new fills, "
                f"VPIN={vpin_status['vpin']:.3f}"
            )


# ── Main Bot ──────────────────────────────────────────────────────────────────

class PolyMakerBot:
    """
    Production market maker bot.
    Discovers markets, starts WebSocket feed, runs event-driven quote loops.
    """

    def __init__(self, dry_run: bool = False, num_markets: int = NUM_MARKETS):
        self.dry_run = dry_run
        self.num_markets = num_markets
        self._running = False
        self._loops: list[MarketLoop] = []
        self._feed: Optional[MarketFeed] = None

    def _setup(self):
        logger.info("=" * 60)
        logger.info("PolyMaker Bot starting up")
        logger.info(f"  dry_run={self.dry_run}  markets={self.num_markets}  size=${ORDER_SIZE_USD}/side")
        logger.info(f"  min_requote={MIN_REQUOTE_SEC}s  mid_threshold={MID_THRESHOLD}")
        logger.info("=" * 60)

        # Auth
        client = get_client()
        logger.info("CLOB client authenticated")

        # Discover markets
        markets = find_maker_markets(limit=self.num_markets * 3)
        if not markets:
            raise RuntimeError("No suitable markets found — check connectivity")

        selected = markets[:self.num_markets]
        logger.info(f"Selected {len(selected)} markets:")
        for m in selected:
            logger.info(f"  [{m['days_to_close']:.0f}d] ${m['volume_24h']:,.0f}/24h  {m['question'][:60]}")

        # Collect token/condition IDs for WebSocket subscriptions
        token_ids = []
        condition_ids = []
        for m in selected:
            token_ids.append(m["token_yes"])
            if m.get("token_no"):
                token_ids.append(m["token_no"])
            if m.get("condition_id"):
                condition_ids.append(m["condition_id"])

        # Create WebSocket feed
        api_creds = {
            "api_key": client.creds.api_key,
            "api_secret": client.creds.api_secret,
            "api_passphrase": client.creds.api_passphrase,
        }
        self._feed = MarketFeed(
            api_creds=api_creds,
            token_ids=token_ids,
            condition_ids=condition_ids,
            mid_threshold=MID_THRESHOLD,
        )

        # Shared objects
        inventory = InventoryTracker()
        order_mgr = OrderManager(client, dry_run=self.dry_run)

        # Build per-market loops with feed reference
        self._loops = [
            MarketLoop(
                market=m,
                engine=ASQuoteEngine(),
                inventory=inventory,
                order_mgr=order_mgr,
                size_usd=ORDER_SIZE_USD,
                feed=self._feed,
            )
            for m in selected
        ]

    async def run(self):
        self._setup()
        self._running = True

        loop = asyncio.get_event_loop()
        for sig in (signal.SIGINT, signal.SIGTERM):
            loop.add_signal_handler(sig, lambda: asyncio.create_task(self._shutdown()))

        logger.info(f"Bot running — WS-driven requoting (fallback every {QUOTE_REFRESH_SEC}s)")
        if self.dry_run:
            logger.info("*** DRY RUN MODE — no real orders ***")

        # Start WS feed + all market loops
        tasks = [asyncio.create_task(self._feed.run(), name="ws_feed")]
        tasks += [asyncio.create_task(ml.run(), name=f"loop_{i}") for i, ml in enumerate(self._loops)]

        try:
            await asyncio.gather(*tasks, return_exceptions=True)
        finally:
            await self._shutdown()

    async def _shutdown(self):
        if not self._running:
            return
        logger.info("Shutdown signal received — cancelling all orders...")
        self._running = False

        # Stop market loops
        for ml in self._loops:
            ml.stop()
            try:
                ml.order_mgr.cancel_market_orders(ml.token_yes)
                ml.order_mgr.cancel_market_orders(ml.token_no)
            except Exception as e:
                logger.warning(f"Shutdown cancel error: {e}")

        # Stop WS feed
        if self._feed:
            await self._feed.stop()

        logger.info("Shutdown complete")


# ── Entry Point ───────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(description="PolyMaker — Polymarket Market Maker Bot")
    parser.add_argument("--dry-run", action="store_true", help="Quote without placing orders")
    parser.add_argument("--markets", type=int, default=NUM_MARKETS, help="Number of markets to trade")
    parser.add_argument("--size", type=float, default=ORDER_SIZE_USD, help="USD per order side")
    args = parser.parse_args()

    # Override env config from CLI
    if args.size != ORDER_SIZE_USD:
        os.environ["ORDER_SIZE_USD"] = str(args.size)

    bot = PolyMakerBot(dry_run=args.dry_run, num_markets=args.markets)
    asyncio.run(bot.run())


if __name__ == "__main__":
    main()
