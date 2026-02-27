#!/usr/bin/env python3
"""
Fetch active BTC-related Polymarket markets and save to intel/raw/.

Usage:
    python scripts/fetch_markets.py                    # basic fetch
    python scripts/fetch_markets.py --clob-prices      # also pull CLOB midpoints
    python scripts/fetch_markets.py --verbose           # debug logging

Output:
    intel/raw/polymarket_markets_YYYY-MM-DD.json
"""

import argparse
import json
import logging
import sys
from datetime import datetime, timezone
from pathlib import Path

# Add project root to path
PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from polymarket_api import PolymarketClient, load_api_key


def main():
    parser = argparse.ArgumentParser(description="Fetch BTC markets from Polymarket")
    parser.add_argument("--clob-prices", action="store_true", help="Enrich with CLOB midpoint prices (slower)")
    parser.add_argument("--verbose", "-v", action="store_true", help="Debug logging")
    parser.add_argument("--output-dir", default=str(PROJECT_ROOT / "intel" / "raw"), help="Output directory")
    args = parser.parse_args()

    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
        datefmt="%H:%M:%S",
    )

    # Load API key (optional for read-only ops)
    api_key = load_api_key()
    if api_key:
        logging.info("API key loaded")
    else:
        logging.info("No API key found — using public endpoints only (fine for market data)")

    client = PolymarketClient(api_key=api_key)

    # Fetch
    logging.info("Fetching BTC-related markets from Polymarket...")
    markets = client.find_btc_markets(include_clob_prices=args.clob_prices)

    if not markets:
        logging.warning("No BTC markets found!")
        sys.exit(1)

    # Sort by 24h volume descending
    markets.sort(key=lambda m: m.get("volume_24h", 0) or 0, reverse=True)

    # Build output
    now = datetime.now(timezone.utc)
    output = {
        "fetched_at": now.isoformat(),
        "total_markets": len(markets),
        "filters": {
            "tag_slugs": ["bitcoin", "crypto"],
            "keywords": ["bitcoin", "btc", "satoshi", "sats", "microstrategy", "mstr"],
            "active_only": True,
            "include_clob_prices": args.clob_prices,
        },
        "markets": markets,
    }

    # Save
    out_dir = Path(args.output_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    date_str = now.strftime("%Y-%m-%d")
    out_file = out_dir / f"polymarket_markets_{date_str}.json"
    with open(out_file, "w") as f:
        json.dump(output, f, indent=2, default=str)

    logging.info(f"Saved {len(markets)} markets → {out_file}")

    # Print summary
    print(f"\n{'='*70}")
    print(f"  Polymarket BTC Markets — {date_str}")
    print(f"  Total: {len(markets)} active markets")
    print(f"{'='*70}\n")

    for i, m in enumerate(markets[:20], 1):
        odds_str = " | ".join(f"{k}: {v:.1%}" for k, v in m["odds"].items() if v is not None)
        vol = m.get("volume_24h", 0) or 0
        liq = m.get("liquidity", 0) or 0
        print(f"  {i:>2}. {m['question']}")
        print(f"      Odds: {odds_str}")
        print(f"      24h Vol: ${vol:,.0f}  |  Liquidity: ${liq:,.0f}")
        if m.get("group_item_title"):
            print(f"      Group: {m['group_item_title']}")
        print()

    if len(markets) > 20:
        print(f"  ... and {len(markets) - 20} more (see {out_file})\n")


if __name__ == "__main__":
    main()
