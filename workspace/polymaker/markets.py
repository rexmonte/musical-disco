"""
markets.py — Market selection for the maker bot
================================================
Finds low-competition markets suitable for market making:
  - Active, accepting orders
  - NOT on the fee list (15m/5m crypto, NCAAB, Serie A)
  - Reasonable liquidity (> $1K) and volume (> $5K)
  - Binary (YES/NO) with valid CLOB token IDs
  - Time remaining > 1 day (avoid resolution risk)
"""

import os
import json
import time
import logging
from datetime import datetime, timezone
from typing import Optional
import httpx
from dotenv import load_dotenv
from pathlib import Path

load_dotenv(Path(__file__).parent / ".env")

logger = logging.getLogger(__name__)

GAMMA_API = "https://gamma-api.polymarket.com"

# Slugs/keywords in markets with taker fees — avoid these
FEE_SLUGS = [
    "updown-15m", "updown-5m",
    "ncaab", "ncaa-basketball",
    "serie-a",
]

# Minimum thresholds for market selection
MIN_LIQUIDITY = 1_000.0   # USD
MIN_VOLUME_24H = 500.0    # USD (some activity = orders will fill)
MIN_DAYS_TO_CLOSE = 1.0   # Avoid markets resolving today


def _is_fee_market(market: dict) -> bool:
    slug = (market.get("slug") or "").lower()
    question = (market.get("question") or "").lower()
    for kw in FEE_SLUGS:
        if kw in slug or kw in question:
            return True
    return False


def _days_to_close(market: dict) -> float:
    end_str = market.get("endDate") or market.get("end_date_iso")
    if not end_str:
        return 999.0
    try:
        # Handle both "2026-03-15T00:00:00Z" and "2026-03-15"
        end_str = end_str.replace("Z", "+00:00")
        if "T" not in end_str:
            end_str += "T00:00:00+00:00"
        end_dt = datetime.fromisoformat(end_str)
        now = datetime.now(timezone.utc)
        return (end_dt - now).total_seconds() / 86400.0
    except Exception:
        return 999.0


def _parse_clob_tokens(market: dict) -> list[dict]:
    raw = market.get("clobTokenIds") or "[]"
    if isinstance(raw, str):
        try:
            ids = json.loads(raw)
        except Exception:
            return []
    else:
        ids = raw

    outcomes_raw = market.get("outcomes") or '["Yes","No"]'
    if isinstance(outcomes_raw, str):
        try:
            outcomes = json.loads(outcomes_raw)
        except Exception:
            outcomes = ["Yes", "No"]
    else:
        outcomes = outcomes_raw

    tokens = []
    for i, tid in enumerate(ids):
        label = outcomes[i] if i < len(outcomes) else f"token_{i}"
        tokens.append({"label": label, "token_id": tid})
    return tokens


def find_maker_markets(limit: int = 20) -> list[dict]:
    """
    Return a list of markets suitable for market making.
    Sorted by 24h volume descending (more activity = more fills).
    """
    client = httpx.Client(timeout=15)
    results = []
    cursor = None

    # Paginate until we have enough candidates
    for page in range(10):
        params = {
            "active": "true",
            "closed": "false",
            "limit": 100,
            "order": "volume24hr",
            "ascending": "false",
        }
        if cursor:
            params["next_cursor"] = cursor

        try:
            resp = client.get(f"{GAMMA_API}/markets", params=params)
            resp.raise_for_status()
            data = resp.json()
        except Exception as e:
            logger.warning(f"Gamma API error: {e}")
            break

        markets = data if isinstance(data, list) else data.get("data", [])
        cursor = data.get("next_cursor") if isinstance(data, dict) else None

        for m in markets:
            # Must be accepting orders
            if not m.get("acceptingOrders", False):
                continue

            # Skip fee markets
            if _is_fee_market(m):
                continue

            # Liquidity check
            liq = float(m.get("liquidityNum") or m.get("liquidity") or 0)
            if liq < MIN_LIQUIDITY:
                continue

            # Volume check
            vol24 = float(m.get("volume24hr") or 0)
            if vol24 < MIN_VOLUME_24H:
                continue

            # Time check
            days = _days_to_close(m)
            if days < MIN_DAYS_TO_CLOSE:
                continue

            # Need valid CLOB tokens
            tokens = _parse_clob_tokens(m)
            if len(tokens) < 2:
                continue

            # Parse outcome prices
            prices_raw = m.get("outcomePrices", "[]")
            if isinstance(prices_raw, str):
                try:
                    prices = [float(p) for p in json.loads(prices_raw)]
                except Exception:
                    prices = []
            else:
                prices = [float(p) for p in prices_raw]

            mid = prices[0] if prices else 0.5

            # Skip extreme prices where A-S model is meaningless
            if mid < 0.15 or mid > 0.85:
                continue

            results.append({
                "market_id": m.get("id"),
                "question": m.get("question"),
                "slug": m.get("slug"),
                "condition_id": m.get("conditionId"),
                "token_yes": tokens[0]["token_id"],
                "token_no": tokens[1]["token_id"] if len(tokens) > 1 else None,
                "mid": mid,
                "liquidity": liq,
                "volume_24h": vol24,
                "days_to_close": round(days, 1),
                "tick_size": float(m.get("orderPriceMinTickSize") or 0.01),
                "min_order_size": float(m.get("orderMinSize") or 1.0),
            })

            if len(results) >= limit:
                break

        if len(results) >= limit or not cursor:
            break

        time.sleep(0.25)

    # Composite score: 60% mid-range preference (closer to 0.50 = better) + 40% volume
    max_vol = max((r["volume_24h"] for r in results), default=1.0)
    def _score(m):
        mid_score = 1.0 - 2.0 * abs(m["mid"] - 0.50)  # 1.0 at 0.50, 0.0 at extremes
        vol_score = m["volume_24h"] / max_vol if max_vol > 0 else 0
        return 0.6 * mid_score + 0.4 * vol_score
    results.sort(key=_score, reverse=True)
    logger.info(f"Found {len(results)} maker-suitable markets")
    return results[:limit]


if __name__ == "__main__":
    import logging
    logging.basicConfig(level=logging.INFO)
    markets = find_maker_markets(10)
    print(f"\nTop {len(markets)} maker markets:\n")
    for m in markets:
        print(
            f"  [{m['days_to_close']:.0f}d] "
            f"${m['volume_24h']:>8,.0f}/24h  "
            f"liq=${m['liquidity']:>8,.0f}  "
            f"mid={m['mid']:.2f}  "
            f"{m['question'][:70]}"
        )
