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
    Refreshes quotes every QUOTE_REFRESH_SEC seconds.
    """

    def __init__(
        self,
        market: dict,
        engine: ASQuoteEngine,
        inventory: InventoryTracker,
        order_mgr: OrderManager,
        size_usd: float,
    ):
        self.market = market
        self.engine = engine
        self.inventory = inventory
        self.order_mgr = order_mgr
        self.size_usd = size_usd
        self.token_yes = market["token_yes"]
        self.token_no = market["token_no"]
        self.cycles = 0

    async def run_cycle(self) -> None:
        """Single quote refresh cycle."""
        self.cycles += 1
        token = self.token_yes
        question_short = self.market["question"][:50]

        # Get current mid price
        try:
            mid_data = self.order_mgr.client.get_midpoint(token)
            mid = float(mid_data.get("mid", self.market.get("mid", 0.5)))
        except Exception as e:
            logger.warning(f"[{question_short}] midpoint fetch failed: {e}")
            return

        # Get inventory
        inv = self.inventory.get(token)

        # Time remaining fraction (rough estimate based on days)
        days = self.market.get("days_to_close", 30.0)
        T = min(1.0, max(0.01, days / 30.0))

        # Generate quote
        quote = self.engine.quote(mid=mid, inventory_usd=inv, time_remaining_fraction=T)

        if quote is None:
            vpin_status = self.engine.vpin.status()
            if vpin_status["toxic"]:
                logger.warning(
                    f"[{question_short}] VPIN={vpin_status['vpin']:.3f} TOXIC — skipping"
                )
            else:
                logger.info(f"[{question_short}] No quote (inventory limit or VPIN)")
            # Cancel existing orders on both tokens
            self.order_mgr.cancel_market_orders(token)
            self.order_mgr.cancel_market_orders(self.token_no)
            return

        logger.info(
            f"[{question_short}] "
            f"mid={mid:.3f} res={quote.reservation:.3f} "
            f"bid={quote.bid:.3f} ask={quote.ask:.3f} "
            f"spread={quote.spread:.3f} inv=${inv:.1f}"
        )

        # Cancel stale orders before requoting (both YES and NO tokens)
        self.order_mgr.cancel_market_orders(token)
        self.order_mgr.cancel_market_orders(self.token_no)

        # Place bid: BUY YES token
        self.order_mgr.place_limit_post_only(
            token_id=token,
            side=BUY,
            price=quote.bid,
            size_usd=self.size_usd,
            tick_size=self.market.get("tick_size", 0.01),
            min_size=self.market.get("min_order_size", 1.0),
        )
        # Place ask: BUY NO token at (1 - ask_price)
        # Equivalent to SELL YES but doesn't require holding YES tokens
        self.order_mgr.place_limit_post_only(
            token_id=self.token_no,
            side=BUY,
            price=round(1.0 - quote.ask, 4),
            size_usd=self.size_usd,
            tick_size=self.market.get("tick_size", 0.01),
            min_size=self.market.get("min_order_size", 1.0),
        )

        # Check for fills on both tokens, update inventory, and feed VPIN
        fills = self.order_mgr.check_fills(token, self.inventory)
        fills_no = self.order_mgr.check_fills(self.token_no, self.inventory)
        all_fills = fills + fills_no
        for f in all_fills:
            self.engine.vpin.add_trade(f["price"], f["size"], f["side"] == "BUY")
        if all_fills:
            vpin_status = self.engine.vpin.status()
            logger.info(
                f"[{question_short}] VPIN={vpin_status['vpin']:.3f} "
                f"trades={vpin_status['trades_in_window']} toxic={vpin_status['toxic']}"
            )

        # Periodic P&L summary (every 10 cycles ~5 min)
        if self.cycles % 10 == 0:
            pnl = self.inventory.summary()
            fills = self.inventory.total_fills
            if pnl or fills:
                logger.info(
                    f"[{question_short}] === P&L Summary (cycle {self.cycles}) === "
                    f"fills={fills} positions={pnl}"
                )


# ── Main Bot ──────────────────────────────────────────────────────────────────

class PolyMakerBot:
    """
    Production market maker bot.
    Discovers markets, runs parallel quote loops, handles shutdown.
    """

    def __init__(self, dry_run: bool = False, num_markets: int = NUM_MARKETS):
        self.dry_run = dry_run
        self.num_markets = num_markets
        self._running = False
        self._loops: list[MarketLoop] = []

    def _setup(self):
        logger.info("=" * 60)
        logger.info("PolyMaker Bot starting up")
        logger.info(f"  dry_run={self.dry_run}  markets={self.num_markets}  size=${ORDER_SIZE_USD}/side")
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

        # Shared objects
        inventory = InventoryTracker()
        order_mgr = OrderManager(client, dry_run=self.dry_run)

        # Build per-market loops (each gets its own engine for independent state)
        self._loops = [
            MarketLoop(
                market=m,
                engine=ASQuoteEngine(),
                inventory=inventory,
                order_mgr=order_mgr,
                size_usd=ORDER_SIZE_USD,
            )
            for m in selected
        ]

    async def _run_loop(self, loop: MarketLoop):
        """Continuously run a single market's quote cycle."""
        while self._running:
            try:
                await loop.run_cycle()
            except Exception as e:
                logger.error(f"Loop error for {loop.market['question'][:40]}: {e}")
            await asyncio.sleep(QUOTE_REFRESH_SEC)

    async def run(self):
        self._setup()
        self._running = True

        # Handle SIGTERM/SIGINT for clean shutdown
        loop = asyncio.get_event_loop()
        for sig in (signal.SIGINT, signal.SIGTERM):
            loop.add_signal_handler(sig, self._shutdown)

        logger.info(f"Bot running — refresh every {QUOTE_REFRESH_SEC}s")
        if self.dry_run:
            logger.info("*** DRY RUN MODE — no real orders ***")

        tasks = [asyncio.create_task(self._run_loop(ml)) for ml in self._loops]
        await asyncio.gather(*tasks, return_exceptions=True)

    def _shutdown(self):
        logger.info("Shutdown signal received — cancelling all orders...")
        self._running = False
        # Cancel all resting orders (both YES and NO tokens)
        for ml in self._loops:
            try:
                ml.order_mgr.cancel_market_orders(ml.token_yes)
                ml.order_mgr.cancel_market_orders(ml.token_no)
            except Exception as e:
                logger.warning(f"Shutdown cancel error: {e}")
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
