"""
ws_feed.py — WebSocket feed for Polymarket market data + user fills
====================================================================
Connects to two WebSocket channels:
  - Market (public): real-time best_bid/best_ask price changes
  - User (authenticated): our fill notifications

Provides event-driven midpoint updates to MarketLoop, with automatic
reconnection and REST fallback on disconnect.
"""

import asyncio
import logging
import time
from dataclasses import dataclass, field
from typing import Optional

import websockets
import json

logger = logging.getLogger("polymaker.ws")

WS_URL = "wss://ws-subscriptions-clob.polymarket.com/ws/market"
WS_USER_URL = "wss://ws-subscriptions-clob.polymarket.com/ws/user"

KEEPALIVE_SEC = 10
RECONNECT_BASE = 1.0
RECONNECT_MAX = 30.0


@dataclass
class MidpointUpdate:
    token_id: str
    mid: float
    timestamp: float = field(default_factory=time.time)


@dataclass
class FillUpdate:
    token_id: str
    trade_id: str
    side: str
    price: float
    size: float
    timestamp: float = field(default_factory=time.time)


class MarketFeed:
    """
    Manages market + user WebSocket connections.
    Dispatches midpoint updates and fill events to per-token queues.
    """

    def __init__(
        self,
        api_creds: dict,
        token_ids: list[str],
        condition_ids: list[str],
        mid_threshold: float = 0.005,
    ):
        self._api_creds = api_creds  # {api_key, api_secret, api_passphrase}
        self._token_ids = set(token_ids)
        self._condition_ids = list(set(condition_ids))
        self._mid_threshold = mid_threshold

        # State
        self._mids: dict[str, float] = {}  # token_id -> latest mid
        self._mid_events: dict[str, asyncio.Event] = {
            tid: asyncio.Event() for tid in token_ids
        }
        self._fill_queues: dict[str, asyncio.Queue] = {
            tid: asyncio.Queue() for tid in token_ids
        }
        self._running = False
        self._tasks: list[asyncio.Task] = []

    async def run(self):
        """Start market WS, user WS, and keepalive tasks."""
        self._running = True
        self._tasks = [
            asyncio.create_task(self._market_ws_loop(), name="market_ws"),
            asyncio.create_task(self._user_ws_loop(), name="user_ws"),
        ]
        logger.info(
            f"MarketFeed started: {len(self._token_ids)} tokens, "
            f"{len(self._condition_ids)} conditions"
        )

    async def stop(self):
        """Clean shutdown."""
        self._running = False
        for t in self._tasks:
            t.cancel()
        if self._tasks:
            await asyncio.gather(*self._tasks, return_exceptions=True)
        self._tasks = []
        logger.info("MarketFeed stopped")

    async def wait_for_update(self, token_id: str, timeout: float) -> bool:
        """
        Block until the midpoint for token_id changes meaningfully, or timeout.
        Returns True if an update arrived, False on timeout.
        """
        ev = self._mid_events.get(token_id)
        if ev is None:
            await asyncio.sleep(timeout)
            return False
        ev.clear()
        try:
            await asyncio.wait_for(ev.wait(), timeout=timeout)
            return True
        except asyncio.TimeoutError:
            return False

    def get_mid(self, token_id: str) -> Optional[float]:
        """Return latest cached midpoint, or None if never received."""
        return self._mids.get(token_id)

    async def get_fills(self, token_id: str) -> list[FillUpdate]:
        """Drain and return all queued fills for a token."""
        q = self._fill_queues.get(token_id)
        if q is None:
            return []
        fills = []
        while not q.empty():
            try:
                fills.append(q.get_nowait())
            except asyncio.QueueEmpty:
                break
        return fills

    # ── Market WebSocket ─────────────────────────────────────────────────────

    async def _market_ws_loop(self):
        """Connect to market WS with auto-reconnect."""
        backoff = RECONNECT_BASE
        while self._running:
            try:
                await self._run_market_ws()
            except asyncio.CancelledError:
                return
            except Exception as e:
                if not self._running:
                    return
                logger.warning(f"Market WS error: {e} — reconnecting in {backoff:.0f}s")
                await asyncio.sleep(backoff)
                backoff = min(backoff * 2, RECONNECT_MAX)

    async def _run_market_ws(self):
        async with websockets.connect(WS_URL, ping_interval=None) as ws:
            # Subscribe to all token IDs
            sub = {
                "assets_ids": list(self._token_ids),
                "type": "market",
                "custom_feature_enabled": True,
            }
            await ws.send(json.dumps(sub))
            logger.info(f"Market WS connected — subscribed to {len(self._token_ids)} assets")

            # Reset backoff on successful connect
            # (handled by outer loop resetting after yield)

            # Keepalive + message loop
            async def keepalive():
                while self._running:
                    await asyncio.sleep(KEEPALIVE_SEC)
                    try:
                        await ws.ping()
                    except Exception:
                        return

            ka_task = asyncio.create_task(keepalive())
            try:
                async for raw in ws:
                    self._handle_market_msg(raw)
            finally:
                ka_task.cancel()

    def _handle_market_msg(self, raw: str):
        try:
            msgs = json.loads(raw)
        except json.JSONDecodeError:
            return

        # Server sends a list of event objects
        if not isinstance(msgs, list):
            msgs = [msgs]

        for msg in msgs:
            event_type = msg.get("event_type", "")

            if event_type == "price_change":
                self._process_price_change(msg)
            elif event_type == "last_trade_price":
                self._process_last_trade(msg)

    def _process_price_change(self, msg: dict):
        """Extract best_bid/best_ask from price_change events."""
        changes = msg.get("price_changes") or msg.get("changes") or []
        if not isinstance(changes, list):
            changes = [changes]
        for change in changes:
            asset_id = change.get("asset_id") or msg.get("asset_id")
            if not asset_id or asset_id not in self._token_ids:
                continue
            best_bid = change.get("best_bid") or change.get("price")
            best_ask = change.get("best_ask")
            if best_bid is not None and best_ask is not None:
                try:
                    mid = (float(best_bid) + float(best_ask)) / 2.0
                except (ValueError, TypeError):
                    continue
                self._update_mid(asset_id, mid)
            elif best_bid is not None:
                # Fallback: use best_bid as approximation
                try:
                    self._update_mid(asset_id, float(best_bid))
                except (ValueError, TypeError):
                    pass

    def _process_last_trade(self, msg: dict):
        """Use last_trade_price as mid approximation."""
        asset_id = msg.get("asset_id")
        price = msg.get("price") or msg.get("last_trade_price")
        if not asset_id or asset_id not in self._token_ids or price is None:
            return
        try:
            self._update_mid(asset_id, float(price))
        except (ValueError, TypeError):
            pass

    def _update_mid(self, token_id: str, new_mid: float):
        """Update cached mid and signal waiters if change exceeds threshold."""
        old_mid = self._mids.get(token_id)
        self._mids[token_id] = new_mid

        if old_mid is None or abs(new_mid - old_mid) >= self._mid_threshold:
            ev = self._mid_events.get(token_id)
            if ev:
                ev.set()

    # ── User WebSocket (fills) ───────────────────────────────────────────────

    async def _user_ws_loop(self):
        """Connect to user WS with auto-reconnect."""
        backoff = RECONNECT_BASE
        while self._running:
            try:
                await self._run_user_ws()
            except asyncio.CancelledError:
                return
            except Exception as e:
                if not self._running:
                    return
                logger.warning(f"User WS error: {e} — reconnecting in {backoff:.0f}s")
                await asyncio.sleep(backoff)
                backoff = min(backoff * 2, RECONNECT_MAX)

    async def _run_user_ws(self):
        async with websockets.connect(WS_USER_URL, ping_interval=None) as ws:
            sub = {
                "auth": {
                    "apiKey": self._api_creds["api_key"],
                    "secret": self._api_creds["api_secret"],
                    "passphrase": self._api_creds["api_passphrase"],
                },
                "markets": self._condition_ids,
                "type": "user",
            }
            await ws.send(json.dumps(sub))
            logger.info(
                f"User WS connected — subscribed to {len(self._condition_ids)} conditions"
            )

            async def keepalive():
                while self._running:
                    await asyncio.sleep(KEEPALIVE_SEC)
                    try:
                        await ws.ping()
                    except Exception:
                        return

            ka_task = asyncio.create_task(keepalive())
            try:
                async for raw in ws:
                    self._handle_user_msg(raw)
            finally:
                ka_task.cancel()

    def _handle_user_msg(self, raw: str):
        try:
            msgs = json.loads(raw)
        except json.JSONDecodeError:
            return

        if not isinstance(msgs, list):
            msgs = [msgs]

        for msg in msgs:
            event_type = msg.get("event_type", "")
            if event_type == "trade":
                self._process_fill(msg)

    def _process_fill(self, msg: dict):
        """Extract fill info from user trade events."""
        # Only process confirmed fills
        status = (msg.get("status") or "").upper()
        if status not in ("MATCHED", "CONFIRMED", "MINED"):
            return

        asset_id = msg.get("asset_id")
        if not asset_id or asset_id not in self._token_ids:
            return

        trade_id = msg.get("id") or msg.get("tradeID") or ""
        if not trade_id:
            return

        try:
            fill = FillUpdate(
                token_id=asset_id,
                trade_id=trade_id,
                side=msg.get("side", "").upper(),
                price=float(msg.get("price", 0)),
                size=float(msg.get("size", 0)),
            )
        except (ValueError, TypeError):
            return

        q = self._fill_queues.get(asset_id)
        if q:
            q.put_nowait(fill)
            logger.info(
                f"Fill (WS): {fill.side} {fill.size:.1f}@{fill.price:.3f} "
                f"token={asset_id[:16]}..."
            )
