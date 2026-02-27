"""
Polymarket API Client
=====================
Connects to Polymarket's three APIs:
  - Gamma API (gamma-api.polymarket.com): Markets, events, tags — public, no auth
  - Data API (data-api.polymarket.com): Positions, trades, leaderboards — public, no auth
  - CLOB API (clob.polymarket.com): Orderbook, pricing, trading — public reads, auth for orders

This client focuses on market discovery and price data for arbitrage detection.
"""

import os
import json
import time
import logging
from datetime import datetime, timezone
from typing import Optional
from pathlib import Path

import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

GAMMA_API = "https://gamma-api.polymarket.com"
DATA_API = "https://data-api.polymarket.com"
CLOB_API = "https://clob.polymarket.com"

DEFAULT_PAGE_SIZE = 100  # Gamma max per request
MAX_PAGES = 20           # Safety cap: 2000 markets max per query
RATE_LIMIT_SLEEP = 0.25  # seconds between paginated requests

# BTC-related keywords for filtering
BTC_KEYWORDS = [
    "bitcoin", "btc", "satoshi", "sats",
    "microstrategy", "mstr",  # highly BTC-correlated
]

# Tag slugs known to contain BTC markets
BTC_TAG_SLUGS = ["bitcoin", "crypto"]


# ---------------------------------------------------------------------------
# Session Factory
# ---------------------------------------------------------------------------

def _build_session(api_key: Optional[str] = None) -> requests.Session:
    """Build a requests session with retry logic and optional auth."""
    session = requests.Session()

    # Retry on 429 (rate limit), 500, 502, 503, 504
    retry = Retry(
        total=5,
        backoff_factor=1.0,
        status_forcelist=[429, 500, 502, 503, 504],
        allowed_methods=["GET"],
        raise_on_status=False,
    )
    adapter = HTTPAdapter(max_retries=retry)
    session.mount("https://", adapter)
    session.mount("http://", adapter)

    session.headers.update({
        "Accept": "application/json",
        "User-Agent": "polymarket-arb-bot/0.1",
    })

    if api_key:
        session.headers["Authorization"] = f"Bearer {api_key}"

    return session


# ---------------------------------------------------------------------------
# PolymarketClient
# ---------------------------------------------------------------------------

class PolymarketClient:
    """Client for Polymarket Gamma + CLOB APIs."""

    def __init__(self, api_key: Optional[str] = None):
        self.api_key = api_key
        self._gamma = _build_session()
        self._clob = _build_session(api_key)

    # -- Gamma API: Events --------------------------------------------------

    def list_events(
        self,
        active: bool = True,
        closed: bool = False,
        tag_slug: Optional[str] = None,
        limit: int = DEFAULT_PAGE_SIZE,
        offset: int = 0,
    ) -> list[dict]:
        """Fetch events from Gamma API (single page)."""
        params = {
            "limit": limit,
            "offset": offset,
            "active": str(active).lower(),
            "closed": str(closed).lower(),
        }
        if tag_slug:
            params["tag_slug"] = tag_slug

        resp = self._gamma.get(f"{GAMMA_API}/events", params=params)
        resp.raise_for_status()
        return resp.json()

    def list_all_events(
        self,
        active: bool = True,
        closed: bool = False,
        tag_slug: Optional[str] = None,
    ) -> list[dict]:
        """Paginate through all events matching filters."""
        all_events = []
        offset = 0
        for _ in range(MAX_PAGES):
            page = self.list_events(
                active=active, closed=closed, tag_slug=tag_slug,
                limit=DEFAULT_PAGE_SIZE, offset=offset,
            )
            if not page:
                break
            all_events.extend(page)
            if len(page) < DEFAULT_PAGE_SIZE:
                break
            offset += DEFAULT_PAGE_SIZE
            time.sleep(RATE_LIMIT_SLEEP)
        return all_events

    # -- Gamma API: Markets -------------------------------------------------

    def list_markets(
        self,
        closed: bool = False,
        limit: int = DEFAULT_PAGE_SIZE,
        offset: int = 0,
        tag_id: Optional[int] = None,
    ) -> list[dict]:
        """Fetch markets from Gamma API (single page)."""
        params = {
            "limit": limit,
            "offset": offset,
            "closed": str(closed).lower(),
        }
        if tag_id is not None:
            params["tag_id"] = tag_id

        resp = self._gamma.get(f"{GAMMA_API}/markets", params=params)
        resp.raise_for_status()
        return resp.json()

    def list_all_markets(self, closed: bool = False, tag_id: Optional[int] = None) -> list[dict]:
        """Paginate through all markets matching filters."""
        all_markets = []
        offset = 0
        for _ in range(MAX_PAGES):
            page = self.list_markets(
                closed=closed, limit=DEFAULT_PAGE_SIZE, offset=offset, tag_id=tag_id,
            )
            if not page:
                break
            all_markets.extend(page)
            if len(page) < DEFAULT_PAGE_SIZE:
                break
            offset += DEFAULT_PAGE_SIZE
            time.sleep(RATE_LIMIT_SLEEP)
        return all_markets

    def get_market(self, market_id: int) -> dict:
        """Fetch a single market by ID."""
        resp = self._gamma.get(f"{GAMMA_API}/markets/{market_id}")
        resp.raise_for_status()
        return resp.json()

    # -- CLOB API: Prices ---------------------------------------------------

    def get_midpoint(self, token_id: str) -> Optional[float]:
        """Get midpoint price for a CLOB token."""
        try:
            resp = self._clob.get(f"{CLOB_API}/midpoint", params={"token_id": token_id})
            resp.raise_for_status()
            data = resp.json()
            return float(data.get("mid", 0))
        except Exception as e:
            logger.warning(f"Failed to get midpoint for {token_id[:20]}...: {e}")
            return None

    def get_orderbook(self, token_id: str) -> Optional[dict]:
        """Get order book for a CLOB token."""
        try:
            resp = self._clob.get(f"{CLOB_API}/book", params={"token_id": token_id})
            resp.raise_for_status()
            return resp.json()
        except Exception as e:
            logger.warning(f"Failed to get orderbook for {token_id[:20]}...: {e}")
            return None

    def get_last_trade_price(self, token_id: str) -> Optional[dict]:
        """Get last trade price for a CLOB token."""
        try:
            resp = self._clob.get(f"{CLOB_API}/last-trade-price", params={"token_id": token_id})
            resp.raise_for_status()
            return resp.json()
        except Exception as e:
            logger.warning(f"Failed to get last trade price for {token_id[:20]}...: {e}")
            return None

    # -- BTC Market Discovery -----------------------------------------------

    def find_btc_markets(self, include_clob_prices: bool = False) -> list[dict]:
        """
        Find all active BTC-related markets.

        Strategy:
        1. Fetch events tagged 'bitcoin' and 'crypto' via Gamma tag_slug
        2. Also fetch a broad set of markets and keyword-filter
        3. Deduplicate by market ID
        4. Optionally enrich with CLOB midpoint prices

        Returns list of normalized market dicts.
        """
        seen_ids = set()
        btc_markets = []

        # Strategy 1: Tag-based discovery (most reliable)
        for tag_slug in BTC_TAG_SLUGS:
            logger.info(f"Fetching events with tag_slug={tag_slug}")
            events = self.list_all_events(active=True, closed=False, tag_slug=tag_slug)
            for event in events:
                for market in event.get("markets", []):
                    mid = market.get("id")
                    if mid and mid not in seen_ids:
                        seen_ids.add(mid)
                        market["_source_event"] = {
                            "id": event.get("id"),
                            "title": event.get("title"),
                            "slug": event.get("slug"),
                        }
                        btc_markets.append(market)

        # Strategy 2: Keyword scan on broad market list
        logger.info("Scanning broad market list for BTC keywords")
        broad_markets = self.list_all_markets(closed=False)
        for market in broad_markets:
            mid = market.get("id")
            if mid in seen_ids:
                continue
            question = (market.get("question") or "").lower()
            description = (market.get("description") or "").lower()
            text = question + " " + description
            if any(kw in text for kw in BTC_KEYWORDS):
                seen_ids.add(mid)
                btc_markets.append(market)

        logger.info(f"Found {len(btc_markets)} BTC-related markets")

        # Normalize
        normalized = []
        for m in btc_markets:
            normalized.append(self._normalize_market(m))

        # Optional: enrich with CLOB midpoints
        if include_clob_prices:
            logger.info("Enriching with CLOB midpoint prices...")
            for nm in normalized:
                for token in nm.get("clob_tokens", []):
                    tid = token.get("token_id")
                    if tid:
                        mid = self.get_midpoint(tid)
                        if mid is not None:
                            token["midpoint"] = mid
                        time.sleep(RATE_LIMIT_SLEEP)

        return normalized

    # -- Normalization ------------------------------------------------------

    @staticmethod
    def _normalize_market(raw: dict) -> dict:
        """Extract the fields we care about into a clean structure."""
        # Parse outcome prices
        outcome_prices_raw = raw.get("outcomePrices", "[]")
        if isinstance(outcome_prices_raw, str):
            try:
                outcome_prices = json.loads(outcome_prices_raw)
            except json.JSONDecodeError:
                outcome_prices = []
        else:
            outcome_prices = outcome_prices_raw

        outcomes_raw = raw.get("outcomes", "[]")
        if isinstance(outcomes_raw, str):
            try:
                outcomes = json.loads(outcomes_raw)
            except json.JSONDecodeError:
                outcomes = []
        else:
            outcomes = outcomes_raw

        # Parse CLOB token IDs
        clob_ids_raw = raw.get("clobTokenIds", "[]")
        if isinstance(clob_ids_raw, str):
            try:
                clob_ids = json.loads(clob_ids_raw)
            except json.JSONDecodeError:
                clob_ids = []
        else:
            clob_ids = clob_ids_raw

        # Build odds dict
        odds = {}
        for i, outcome in enumerate(outcomes):
            price = float(outcome_prices[i]) if i < len(outcome_prices) else None
            odds[outcome] = price

        # Build clob tokens list
        clob_tokens = []
        for i, tid in enumerate(clob_ids):
            label = outcomes[i] if i < len(outcomes) else f"token_{i}"
            clob_tokens.append({"label": label, "token_id": tid})

        source_event = raw.get("_source_event", {})

        return {
            "market_id": raw.get("id"),
            "question": raw.get("question"),
            "slug": raw.get("slug"),
            "condition_id": raw.get("conditionId"),
            "status": "active" if raw.get("active") else ("closed" if raw.get("closed") else "unknown"),
            "accepting_orders": raw.get("acceptingOrders", False),
            "neg_risk": raw.get("negRisk", False),
            "outcomes": outcomes,
            "odds": odds,
            "clob_tokens": clob_tokens,
            "volume_total": raw.get("volumeNum", 0),
            "volume_24h": raw.get("volume24hr", 0),
            "volume_1wk": raw.get("volume1wk", 0),
            "liquidity": raw.get("liquidityNum", 0),
            "end_date": raw.get("endDate"),
            "created_at": raw.get("createdAt"),
            "updated_at": raw.get("updatedAt"),
            "group_item_title": raw.get("groupItemTitle"),
            "event": source_event if source_event else None,
            "tick_size": raw.get("orderPriceMinTickSize"),
            "min_order_size": raw.get("orderMinSize"),
        }


# ---------------------------------------------------------------------------
# Convenience: load API key from .secrets/polymarket.env
# ---------------------------------------------------------------------------

def load_api_key(env_path: Optional[str] = None) -> Optional[str]:
    """Load POLYMARKET_API_KEY from env file or environment."""
    # Check environment first
    key = os.environ.get("POLYMARKET_API_KEY")
    if key and key != "your_key_here":
        return key

    # Try .env file
    if env_path is None:
        env_path = str(Path(__file__).parent / ".secrets" / "polymarket.env")

    if os.path.exists(env_path):
        with open(env_path) as f:
            for line in f:
                line = line.strip()
                if line.startswith("#") or "=" not in line:
                    continue
                k, v = line.split("=", 1)
                if k.strip() == "POLYMARKET_API_KEY":
                    val = v.strip()
                    if val and val != "your_key_here":
                        return val
    return None
