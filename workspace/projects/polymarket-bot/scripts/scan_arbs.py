#!/usr/bin/env python3
"""
Cross-Market Inconsistency Scanner
====================================
Reads Polymarket market data and detects:

1. **Monotonicity violations** in "BTC above $X" series
   - P(BTC > 60K) should always be >= P(BTC > 70K)
   - If inverted → arbitrage: buy the underpriced, sell the overpriced

2. **Range sum violations** in "BTC between $X-$Y" bucket series
   - All buckets should sum to ~100% (they're mutually exclusive)
   - If sum > 100% or < 95% → mispricing exists

3. **Cross-date arbitrage**
   - P(BTC > 70K on March 4) should be influenced by P(BTC > 70K on March 1)
   - Large divergences at same strike across dates → potential arb

Output: intel/analysis/market_arbs_YYYY-MM-DD.md

Usage:
    python scripts/scan_arbs.py
    python scripts/scan_arbs.py --input intel/raw/polymarket_markets_2026-02-27.json
    python scripts/scan_arbs.py --min-liquidity 5000  # skip illiquid markets
"""

import argparse
import json
import re
import sys
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))


# ---------------------------------------------------------------------------
# Parsing helpers
# ---------------------------------------------------------------------------

def extract_strike(group_title: str, question: str) -> tuple:
    """
    Extract strike price and direction from group_item_title or question.
    Returns (direction, strike_price) where direction is 'above', 'below', 'reach', 'dip', 'range'.
    """
    if not group_title and not question:
        return ("unknown", None)

    text = (group_title or "").strip()

    # "↑ 75,000" or "↓ 60,000"
    m = re.match(r'[↑↓]\s*([\d,]+)', text)
    if m:
        direction = "above" if "↑" in text else "below"
        return (direction, float(m.group(1).replace(",", "")))

    # "58,000" or "76,000" (plain number = "above X" in daily series)
    m = re.match(r'^([\d,]+)$', text)
    if m:
        return ("above", float(m.group(1).replace(",", "")))

    # ">76,000"
    m = re.match(r'>([\d,]+)', text)
    if m:
        return ("above", float(m.group(1).replace(",", "")))

    # "60,000-62,000" (range bucket)
    m = re.match(r'([\d,]+)-([\d,]+)', text)
    if m:
        low = float(m.group(1).replace(",", ""))
        high = float(m.group(2).replace(",", ""))
        return ("range", (low, high))

    # Fallback: parse from question
    q = (question or "").lower()
    m = re.search(r'above\s*\$?([\d,]+)', q)
    if m:
        return ("above", float(m.group(1).replace(",", "")))
    m = re.search(r'reach\s*\$?([\d,]+)', q)
    if m:
        return ("above", float(m.group(1).replace(",", "")))
    m = re.search(r'dip\s+to\s*\$?([\d,]+)', q)
    if m:
        return ("below", float(m.group(1).replace(",", "")))

    return ("unknown", None)


def extract_date_from_event(event_title: str) -> str:
    """Extract target date string from event title like 'Bitcoin above ___ on February 27?'"""
    if not event_title:
        return None
    # "on February 27" or "on March 4"
    m = re.search(r'on\s+((?:January|February|March|April|May|June|July|August|September|October|November|December)\s+\d+)', event_title, re.I)
    if m:
        return m.group(1)
    # "in February" or "in 2026"
    m = re.search(r'in\s+((?:January|February|March|April|May|June|July|August|September|October|November|December)(?:\s+\d{4})?)', event_title, re.I)
    if m:
        return m.group(1)
    # "February 23-March 1"
    m = re.search(r'((?:January|February|March|April|May|June|July|August|September|October|November|December)\s+\d+-\w+\s+\d+)', event_title, re.I)
    if m:
        return m.group(1)
    return event_title


# ---------------------------------------------------------------------------
# Scanners
# ---------------------------------------------------------------------------

def scan_monotonicity(event_markets: list[dict], event_title: str, min_liquidity: float) -> list[dict]:
    """
    Check that 'above $X' probabilities decrease as X increases.
    P(BTC > 60K) >= P(BTC > 70K) >= P(BTC > 80K) ...

    Also check 'below/dip' series: P(dip to 60K) >= P(dip to 50K) ...
    """
    findings = []

    above_markets = []
    below_markets = []

    for m in event_markets:
        direction, strike = extract_strike(m.get("group_item_title"), m.get("question"))
        if strike is None or isinstance(strike, tuple):
            continue

        yes_odds = m["odds"].get("Yes")
        if yes_odds is None:
            continue

        liq = m.get("liquidity", 0) or 0
        if liq < min_liquidity:
            continue

        entry = {
            "strike": strike,
            "yes_odds": yes_odds,
            "market_id": m["market_id"],
            "question": m["question"],
            "liquidity": liq,
            "volume_24h": m.get("volume_24h", 0) or 0,
            "clob_tokens": m.get("clob_tokens", []),
        }

        if direction == "above":
            above_markets.append(entry)
        elif direction == "below":
            below_markets.append(entry)

    # Check above series: sorted by strike ascending, odds should be descending
    above_markets.sort(key=lambda x: x["strike"])
    for i in range(len(above_markets) - 1):
        a = above_markets[i]      # lower strike
        b = above_markets[i + 1]  # higher strike

        # P(above lower) should be >= P(above higher)
        if a["yes_odds"] < b["yes_odds"]:
            spread = b["yes_odds"] - a["yes_odds"]
            findings.append({
                "type": "monotonicity_violation",
                "subtype": "above",
                "severity": "HIGH" if spread > 0.02 else "MEDIUM" if spread > 0.005 else "LOW",
                "event": event_title,
                "description": (
                    f"P(BTC > ${a['strike']:,.0f}) = {a['yes_odds']:.1%} < "
                    f"P(BTC > ${b['strike']:,.0f}) = {b['yes_odds']:.1%}"
                ),
                "spread": spread,
                "action": {
                    "buy": f"YES on 'above ${a['strike']:,.0f}' @ {a['yes_odds']:.1%}",
                    "sell": f"YES on 'above ${b['strike']:,.0f}' @ {b['yes_odds']:.1%}",
                    "edge": f"{spread:.2%}",
                },
                "market_a": a,
                "market_b": b,
            })

    # Check below/dip series: sorted by strike descending, odds should be descending
    # P(dip to 60K) >= P(dip to 50K) since dipping to 50K implies dipping to 60K
    below_markets.sort(key=lambda x: x["strike"], reverse=True)
    for i in range(len(below_markets) - 1):
        a = below_markets[i]      # higher strike (easier to hit)
        b = below_markets[i + 1]  # lower strike (harder to hit)

        if a["yes_odds"] < b["yes_odds"]:
            spread = b["yes_odds"] - a["yes_odds"]
            findings.append({
                "type": "monotonicity_violation",
                "subtype": "below",
                "severity": "HIGH" if spread > 0.02 else "MEDIUM" if spread > 0.005 else "LOW",
                "event": event_title,
                "description": (
                    f"P(dip to ${a['strike']:,.0f}) = {a['yes_odds']:.1%} < "
                    f"P(dip to ${b['strike']:,.0f}) = {b['yes_odds']:.1%}"
                ),
                "spread": spread,
                "action": {
                    "buy": f"YES on 'dip to ${a['strike']:,.0f}' @ {a['yes_odds']:.1%}",
                    "sell": f"YES on 'dip to ${b['strike']:,.0f}' @ {b['yes_odds']:.1%}",
                    "edge": f"{spread:.2%}",
                },
                "market_a": a,
                "market_b": b,
            })

    return findings


def scan_range_sums(event_markets: list, event_title: str, min_liquidity: float) -> list:
    """
    Check that mutually exclusive range buckets sum to ~100%.
    ONLY applies to actual range buckets (60K-62K, 62K-64K, etc.) + a single ">X" overflow.
    NOT cumulative "above $X" markets (those are checked by monotonicity scanner).
    """
    findings = []
    range_markets = []
    overflow_market = None  # The ">76K" style catch-all bucket

    for m in event_markets:
        direction, strike = extract_strike(m.get("group_item_title"), m.get("question"))
        yes_odds = m["odds"].get("Yes")
        if yes_odds is None:
            continue
        liq = m.get("liquidity", 0) or 0
        if liq < min_liquidity:
            continue

        if direction == "range" and isinstance(strike, tuple):
            range_markets.append({
                "direction": direction,
                "strike": strike,
                "yes_odds": yes_odds,
                "question": m["question"],
                "market_id": m["market_id"],
                "liquidity": liq,
            })
        elif direction == "above" and isinstance(strike, (int, float)):
            # Check if this is a ">" overflow in a range-bucket event
            # (e.g. ">76,000" alongside "60K-62K" buckets)
            gt = m.get("group_item_title", "")
            if gt.startswith(">"):
                overflow_market = {
                    "direction": "overflow",
                    "strike": strike,
                    "yes_odds": yes_odds,
                    "question": m["question"],
                    "market_id": m["market_id"],
                    "liquidity": liq,
                }

    # Need actual range buckets (not just "above" markets)
    if len(range_markets) < 2:
        return findings

    all_buckets = range_markets[:]
    if overflow_market:
        all_buckets.append(overflow_market)

    total = sum(rm["yes_odds"] for rm in all_buckets)

    if abs(total - 1.0) > 0.05:  # More than 5% off from 100%
        severity = "HIGH" if abs(total - 1.0) > 0.10 else "MEDIUM"
        findings.append({
            "type": "range_sum_violation",
            "severity": severity,
            "event": event_title,
            "description": f"Range buckets sum to {total:.1%} (expected ~100%) across {len(all_buckets)} buckets",
            "total": total,
            "overshoot": total - 1.0,
            "buckets": all_buckets,
            "action": {
                "strategy": "sell all YES" if total > 1.0 else "buy all YES",
                "edge": f"{abs(total - 1.0):.2%}",
            },
        })

    return findings


def scan_cross_date(all_events: dict, min_liquidity: float) -> list[dict]:
    """
    Compare same-strike markets across different dates.
    Large divergences at the same strike = potential arb or insight.
    """
    findings = []

    # Build strike → [(date, odds, market)] mapping
    strike_map = defaultdict(list)

    for (eid, etitle), markets in all_events.items():
        date_str = extract_date_from_event(etitle)
        if not date_str:
            continue
        # Only look at daily "above" series
        if "above" not in etitle.lower() and "price" not in etitle.lower():
            continue

        for m in markets:
            direction, strike = extract_strike(m.get("group_item_title"), m.get("question"))
            if direction != "above" or strike is None or isinstance(strike, tuple):
                continue
            yes_odds = m["odds"].get("Yes")
            liq = m.get("liquidity", 0) or 0
            if yes_odds is None or liq < min_liquidity:
                continue

            strike_map[strike].append({
                "date": date_str,
                "event": etitle,
                "yes_odds": yes_odds,
                "market_id": m["market_id"],
                "question": m["question"],
                "liquidity": liq,
                "volume_24h": m.get("volume_24h", 0) or 0,
            })

    # Find same-strike, cross-date anomalies
    for strike, entries in strike_map.items():
        if len(entries) < 2:
            continue
        entries.sort(key=lambda x: x["date"])

        # Look for cases where a later date has higher odds than an earlier date
        # (not necessarily wrong, but worth flagging if the spread is large)
        for i in range(len(entries)):
            for j in range(i + 1, len(entries)):
                a, b = entries[i], entries[j]
                spread = abs(a["yes_odds"] - b["yes_odds"])
                if spread > 0.15:  # Only flag large divergences
                    findings.append({
                        "type": "cross_date_divergence",
                        "severity": "INFO",
                        "strike": strike,
                        "description": (
                            f"${strike:,.0f} strike: {a['date']} @ {a['yes_odds']:.1%} vs "
                            f"{b['date']} @ {b['yes_odds']:.1%} (Δ{spread:.1%})"
                        ),
                        "market_a": a,
                        "market_b": b,
                        "spread": spread,
                    })

    return findings


# ---------------------------------------------------------------------------
# Report generation
# ---------------------------------------------------------------------------

def generate_report(findings: list[dict], data_meta: dict) -> str:
    """Generate markdown report."""
    now = datetime.now(timezone.utc)

    high = [f for f in findings if f.get("severity") == "HIGH"]
    medium = [f for f in findings if f.get("severity") == "MEDIUM"]
    low = [f for f in findings if f.get("severity") == "LOW"]
    info = [f for f in findings if f.get("severity") == "INFO"]

    lines = [
        f"# Polymarket Cross-Market Arbitrage Scan",
        f"",
        f"**Generated:** {now.strftime('%Y-%m-%d %H:%M UTC')}",
        f"**Data source:** {data_meta.get('fetched_at', 'unknown')}",
        f"**Markets analyzed:** {data_meta.get('total_markets', 0)}",
        f"",
        f"## Summary",
        f"",
        f"| Severity | Count |",
        f"|----------|-------|",
        f"| 🔴 HIGH | {len(high)} |",
        f"| 🟡 MEDIUM | {len(medium)} |",
        f"| 🟢 LOW | {len(low)} |",
        f"| ℹ️ INFO | {len(info)} |",
        f"| **Total** | **{len(findings)}** |",
        f"",
    ]

    if not findings:
        lines.append("**No inconsistencies detected.** Markets appear correctly priced.")
        lines.append("")
        lines.append("This is actually useful info — it means the market is efficient at this snapshot.")
        return "\n".join(lines)

    # Actionable findings first
    if high or medium:
        lines.append("## 🎯 Actionable Opportunities")
        lines.append("")

        for f in high + medium:
            sev = "🔴 HIGH" if f["severity"] == "HIGH" else "🟡 MEDIUM"
            lines.append(f"### {sev} — {f['type'].replace('_', ' ').title()}")
            lines.append(f"")
            lines.append(f"**Event:** {f.get('event', 'N/A')}")
            lines.append(f"**Finding:** {f['description']}")
            lines.append(f"")

            action = f.get("action", {})
            if action:
                lines.append(f"**Trade:**")
                for k, v in action.items():
                    lines.append(f"- **{k.title()}:** {v}")
                lines.append(f"")

            # Risk notes
            lines.append(f"**Risk notes:**")
            if f["type"] == "monotonicity_violation":
                spread = f.get("spread", 0)
                if spread < 0.01:
                    lines.append(f"- Spread ({spread:.2%}) is thin — likely eaten by fees + slippage")
                else:
                    lines.append(f"- Spread ({spread:.2%}) may be tradeable after fees")
                lines.append(f"- Check CLOB orderbook depth before executing")
                lines.append(f"- Verify both markets settle on same oracle/timeframe")
                ma = f.get("market_a", {})
                mb = f.get("market_b", {})
                min_liq = min(ma.get("liquidity", 0), mb.get("liquidity", 0))
                lines.append(f"- Min liquidity in pair: ${min_liq:,.0f}")
            elif f["type"] == "range_sum_violation":
                lines.append(f"- Range buckets are mutually exclusive → sum should be 100%")
                lines.append(f"- Current sum: {f.get('total', 0):.1%}")
                if f.get("total", 0) > 1.0:
                    lines.append(f"- Overshoot of {f.get('overshoot', 0):.2%} → sell overpriced buckets")
                else:
                    lines.append(f"- Undershoot → buy underpriced buckets")
            lines.append(f"")
            lines.append(f"---")
            lines.append(f"")

    # Low severity
    if low:
        lines.append("## 📊 Minor Inconsistencies")
        lines.append("")
        for f in low:
            lines.append(f"- **{f.get('event', '')}**: {f['description']} (edge: {f.get('spread', 0):.2%})")
        lines.append("")

    # Cross-date info
    if info:
        lines.append("## 📅 Cross-Date Divergences")
        lines.append("")
        lines.append("These aren't necessarily arb — later dates *should* have different odds. But large spreads are worth monitoring.")
        lines.append("")
        for f in info:
            lines.append(f"- {f['description']}")
        lines.append("")

    # Market efficiency note
    lines.append("## Notes")
    lines.append("")
    lines.append("- **Fees:** Polymarket charges ~2% on profits. Spreads under 2% are likely not profitable.")
    lines.append("- **Slippage:** Check CLOB order book depth. Thin books mean your order moves the price.")
    lines.append("- **Settlement risk:** Ensure paired markets use the same oracle and settlement time.")
    lines.append("- **This scan is a snapshot.** Odds change by the second. Re-run before trading.")
    lines.append("")

    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main():
    parser = argparse.ArgumentParser(description="Scan for cross-market arbitrage")
    parser.add_argument("--input", help="Input JSON file (default: latest in intel/raw/)")
    parser.add_argument("--min-liquidity", type=float, default=1000, help="Min liquidity to consider (default: $1000)")
    parser.add_argument("--output-dir", default=str(PROJECT_ROOT / "intel" / "analysis"))
    args = parser.parse_args()

    # Find input file
    if args.input:
        input_path = Path(args.input)
    else:
        raw_dir = PROJECT_ROOT / "intel" / "raw"
        files = sorted(raw_dir.glob("polymarket_markets_*.json"))
        if not files:
            print("No market data found in intel/raw/. Run fetch_markets.py first.")
            sys.exit(1)
        input_path = files[-1]  # latest

    print(f"Reading: {input_path}")
    with open(input_path) as f:
        data = json.load(f)

    markets = data.get("markets", [])
    print(f"Loaded {len(markets)} markets")

    # Group by event
    events = defaultdict(list)
    for m in markets:
        if not m.get("question"):
            continue
        q = m["question"].lower()
        # Only analyze BTC markets
        if "bitcoin" not in q and "btc" not in q:
            continue

        eid = m.get("event", {}).get("id") if m.get("event") else m.get("market_id")
        etitle = m.get("event", {}).get("title") if m.get("event") else m.get("question")
        events[(eid, etitle)].append(m)

    print(f"Found {len(events)} BTC event groups")

    # Run scanners
    all_findings = []

    for (eid, etitle), event_markets in events.items():
        if len(event_markets) < 2:
            continue

        # Monotonicity check
        findings = scan_monotonicity(event_markets, etitle, args.min_liquidity)
        all_findings.extend(findings)

        # Range sum check
        findings = scan_range_sums(event_markets, etitle, args.min_liquidity)
        all_findings.extend(findings)

    # Cross-date check
    findings = scan_cross_date(events, args.min_liquidity)
    all_findings.extend(findings)

    # Sort: HIGH first, then by spread
    severity_order = {"HIGH": 0, "MEDIUM": 1, "LOW": 2, "INFO": 3}
    all_findings.sort(key=lambda f: (severity_order.get(f.get("severity", "INFO"), 9), -f.get("spread", 0)))

    print(f"\nFindings: {len(all_findings)}")
    for sev in ["HIGH", "MEDIUM", "LOW", "INFO"]:
        count = sum(1 for f in all_findings if f.get("severity") == sev)
        if count:
            print(f"  {sev}: {count}")

    # Generate report
    report = generate_report(all_findings, {
        "fetched_at": data.get("fetched_at"),
        "total_markets": data.get("total_markets"),
    })

    # Save
    out_dir = Path(args.output_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    date_str = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    out_file = out_dir / f"market_arbs_{date_str}.md"
    with open(out_file, "w") as f:
        f.write(report)

    print(f"\nReport saved: {out_file}")

    # Also save raw findings as JSON for downstream use
    json_file = out_dir / f"market_arbs_{date_str}.json"
    with open(json_file, "w") as f:
        json.dump({
            "generated_at": datetime.now(timezone.utc).isoformat(),
            "source": str(input_path),
            "total_findings": len(all_findings),
            "findings": all_findings,
        }, f, indent=2, default=str)

    print(f"Raw data saved: {json_file}")


if __name__ == "__main__":
    main()
