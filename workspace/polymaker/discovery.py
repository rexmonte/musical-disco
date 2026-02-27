import httpx
from datetime import datetime, timezone

GAMMA_API = "https://gamma-api.polymarket.com"
COINS = ["btc", "eth"] # Starting safe with BTC/ETH
INTERVALS = ["15m"]    # Sticking to 15m for Phase 1

class MarketDiscovery:
    """Finds active 15-min crypto markets via the Gamma API."""
    def __init__(self):
        self.client = httpx.Client(timeout=10)
    
    def find_active_markets(self) -> list[dict]:
        markets = []
        for interval in INTERVALS:
            for coin in COINS:
                slug_prefix = f"{coin}-updown-{interval}"
                try:
                    resp = self.client.get(
                        f"{GAMMA_API}/markets",
                        params={
                            "slug_prefix": slug_prefix,
                            "active": "true",
                            "closed": "false",
                            "limit": 5,
                        }
                    )
                    if resp.status_code == 200:
                        for m in resp.json():
                            if m.get("active") and not m.get("closed"):
                                markets.append({
                                    "slug": m["slug"],
                                    "question": m.get("question", ""),
                                    "condition_id": m["condition_id"],
                                    "token_yes": m["clobTokenIds"][0] if m.get("clobTokenIds") else None,
                                    "token_no": m["clobTokenIds"][1] if m.get("clobTokenIds") and len(m["clobTokenIds"]) > 1 else None,
                                    "end_date": m.get("end_date_iso"),
                                    "coin": coin,
                                    "interval": interval,
                                })
                except Exception as e:
                    print(f"Error fetching markets for {slug_prefix}: {e}")
        return markets

if __name__ == "__main__":
    # Quick test when running the file directly
    discovery = MarketDiscovery()
    active = discovery.find_active_markets()
    print(f"Found {len(active)} active markets.")
    for m in active:
        print(f"- {m['slug']}")
