#!/usr/bin/env python3
"""
Polymarket BTC Cross-Market Arbitrage Scanner

Scans BTC-related markets on Polymarket for mispriced odds across correlated markets.

Arbitrage types detected:
1. THRESHOLD INVERSION: P(BTC > $120K) > P(BTC > $100K) — logically impossible
2. MONOTONICITY VIOLATION: "reach" thresholds not strictly decreasing as price rises
3. DIP MONOTONICITY: "dip to" thresholds not strictly increasing as price drops
4. TIMELINE INVERSION: P(event by sooner date) > P(event by later date)
5. CROSS-EVENT: Inconsistencies between related events (reach vs ATH, etc.)
6. SPREAD COMPRESSION: Adjacent thresholds with suspiciously narrow spreads

Usage:
    python3 scan_arbs.py [path_to_markets.json]
    
If no path given, fetches live from Polymarket API.
"""

import json
import re
import sys
import os
from datetime import datetime, date
from typing import Optional
from dataclasses import dataclass, field


@dataclass
class Market:
    question: str
    yes_price: float
    no_price: float
    event_title: str
    market_id: str = ""
    slug: str = ""
    volume: float = 0.0
    liquidity: float = 0.0
    end_date: str = ""
    # Parsed fields
    threshold: Optional[float] = None
    direction: str = ""  # "reach" or "dip"
    deadline: str = ""
    active: bool = True


@dataclass
class ArbOpportunity:
    arb_type: str
    market_a: Market
    market_b: Market
    margin: float  # profit margin in percentage points
    description: str
    risk_note: str = ""
    confidence: str = "HIGH"  # HIGH, MEDIUM, LOW


def fetch_live_markets() -> list[dict]:
    """Fetch BTC markets from Polymarket API."""
    import urllib.request
    
    all_events = []
    for offset in range(0, 2000, 50):
        url = f'https://gamma-api.polymarket.com/events?closed=false&limit=50&offset={offset}'
        req = urllib.request.Request(url, headers={'User-Agent': 'Mozilla/5.0'})
        try:
            resp = urllib.request.urlopen(req, timeout=15)
            data = json.loads(resp.read())
            if not data:
                break
            all_events.extend(data)
        except Exception as e:
            print(f"Warning: API error at offset {offset}: {e}")
            break
    
    btc_markets = []
    for e in all_events:
        blob = json.dumps(e).lower()
        if 'bitcoin' in blob or 'btc' in blob:
            for m in e.get('markets', []):
                m['_event_title'] = e.get('title', '')
                m['_event_id'] = e.get('id', '')
                btc_markets.append(m)
    
    return btc_markets


def parse_market(raw: dict) -> Optional[Market]:
    """Parse a raw market dict into a Market object."""
    try:
        question = raw.get('question', '')
        prices_str = raw.get('outcomePrices', '[]')
        
        if isinstance(prices_str, str):
            prices = json.loads(prices_str)
        else:
            prices = prices_str
        
        if not prices or len(prices) < 2:
            return None
        
        yes_price = float(prices[0])
        no_price = float(prices[1])
        
        # Skip resolved/dead markets
        if (yes_price == 0 and no_price == 1) or (yes_price == 1 and no_price == 0):
            return None
        
        m = Market(
            question=question,
            yes_price=yes_price,
            no_price=no_price,
            event_title=raw.get('_event_title', ''),
            market_id=raw.get('id', ''),
            slug=raw.get('slug', ''),
            volume=float(raw.get('volume', 0) or 0),
            liquidity=float(raw.get('liquidity', 0) or 0),
            end_date=raw.get('endDate', ''),
            active=raw.get('active', True),
        )
        
        # Parse threshold from question
        # "Will Bitcoin reach $120,000 by December 31, 2026?"
        # "Will Bitcoin dip to $45,000 by December 31, 2026?"
        # "Will Bitcoin hit $150k by March 31, 2026?"
        
        reach_match = re.search(r'(?:reach|hit)\s+\$?([\d,]+(?:k)?)', question, re.I)
        dip_match = re.search(r'dip\s+to\s+\$?([\d,]+(?:k)?)', question, re.I)
        
        if reach_match:
            m.direction = "reach"
            m.threshold = parse_price(reach_match.group(1))
        elif dip_match:
            m.direction = "dip"
            m.threshold = parse_price(dip_match.group(1))
        
        # Parse deadline
        date_match = re.search(r'by\s+([\w\s,]+\d{4})', question, re.I)
        if date_match:
            m.deadline = date_match.group(1).strip()
        
        return m
    except Exception as e:
        return None


def parse_price(s: str) -> float:
    """Parse price string like '120,000' or '150k' into float."""
    s = s.replace(',', '').lower()
    if s.endswith('k'):
        return float(s[:-1]) * 1000
    return float(s)


def find_threshold_arbs(markets: list[Market]) -> list[ArbOpportunity]:
    """Find monotonicity violations in threshold markets."""
    arbs = []
    
    # Group by (direction, deadline)
    groups: dict[tuple, list[Market]] = {}
    for m in markets:
        if m.threshold and m.direction and m.deadline:
            key = (m.direction, m.deadline)
            groups.setdefault(key, []).append(m)
    
    for (direction, deadline), group in groups.items():
        if direction == "reach":
            # Sort by threshold ascending — yes_price should be DECREASING
            group.sort(key=lambda m: m.threshold)
            for i in range(len(group) - 1):
                lower = group[i]  # lower threshold (easier to reach)
                higher = group[i + 1]  # higher threshold (harder)
                
                if higher.yes_price > lower.yes_price:
                    # INVERSION: higher target priced more likely than lower
                    margin = (higher.yes_price - lower.yes_price) * 100
                    arbs.append(ArbOpportunity(
                        arb_type="THRESHOLD_INVERSION",
                        market_a=lower,
                        market_b=higher,
                        margin=margin,
                        description=(
                            f"P(BTC reach ${higher.threshold:,.0f}) = {higher.yes_price:.1%} > "
                            f"P(BTC reach ${lower.threshold:,.0f}) = {lower.yes_price:.1%} "
                            f"by {deadline}"
                        ),
                        risk_note="True logical arbitrage — higher threshold can't be more likely than lower",
                        confidence="HIGH"
                    ))
                elif higher.yes_price == lower.yes_price and lower.threshold != higher.threshold:
                    # Flat pricing — potential arb if spread is tight
                    arbs.append(ArbOpportunity(
                        arb_type="FLAT_PRICING",
                        market_a=lower,
                        market_b=higher,
                        margin=0.5,  # minimal but noteworthy
                        description=(
                            f"P(BTC reach ${higher.threshold:,.0f}) = P(BTC reach ${lower.threshold:,.0f}) "
                            f"= {lower.yes_price:.1%} by {deadline}"
                        ),
                        risk_note="Same price for different thresholds — likely low liquidity/stale",
                        confidence="LOW"
                    ))
                
                # Check for suspiciously narrow spreads
                spread = lower.yes_price - higher.yes_price
                threshold_gap = higher.threshold - lower.threshold
                if 0 < spread < 0.01 and threshold_gap >= 10000:
                    arbs.append(ArbOpportunity(
                        arb_type="SPREAD_COMPRESSION",
                        market_a=lower,
                        market_b=higher,
                        margin=spread * 100,
                        description=(
                            f"${threshold_gap:,.0f} gap but only {spread:.1%} spread: "
                            f"${lower.threshold:,.0f} ({lower.yes_price:.1%}) vs "
                            f"${higher.threshold:,.0f} ({higher.yes_price:.1%})"
                        ),
                        risk_note="Compressed spread suggests one side is mispriced or illiquid",
                        confidence="MEDIUM"
                    ))
        
        elif direction == "dip":
            # Sort by threshold descending — yes_price should be DECREASING (easier to dip to higher)
            group.sort(key=lambda m: m.threshold, reverse=True)
            for i in range(len(group) - 1):
                higher_dip = group[i]  # dip to higher price (easier)
                lower_dip = group[i + 1]  # dip to lower price (harder)
                
                if lower_dip.yes_price > higher_dip.yes_price:
                    margin = (lower_dip.yes_price - higher_dip.yes_price) * 100
                    arbs.append(ArbOpportunity(
                        arb_type="DIP_INVERSION",
                        market_a=higher_dip,
                        market_b=lower_dip,
                        margin=margin,
                        description=(
                            f"P(BTC dip to ${lower_dip.threshold:,.0f}) = {lower_dip.yes_price:.1%} > "
                            f"P(BTC dip to ${higher_dip.threshold:,.0f}) = {higher_dip.yes_price:.1%}"
                        ),
                        risk_note="True logical arbitrage — dipping to lower price implies dipping to higher",
                        confidence="HIGH"
                    ))
    
    return arbs


def find_timeline_arbs(markets: list[Market]) -> list[ArbOpportunity]:
    """Find timeline inversions: earlier deadline priced higher than later."""
    arbs = []
    
    # Group by (direction, threshold)
    groups: dict[tuple, list[Market]] = {}
    for m in markets:
        if m.threshold and m.direction:
            key = (m.direction, m.threshold)
            groups.setdefault(key, []).append(m)
    
    # Also group by event_title for timeline markets like "hit $150k by X"
    event_groups: dict[str, list[Market]] = {}
    for m in markets:
        if m.event_title and m.deadline:
            event_groups.setdefault(m.event_title, []).append(m)
    
    for title, group in event_groups.items():
        if len(group) < 2:
            continue
        # Sub-group by (direction, threshold) so we only compare same-question-different-date
        sub_groups: dict[tuple, list[Market]] = {}
        for m in group:
            if m.threshold and m.direction:
                key = (m.direction, m.threshold)
                sub_groups.setdefault(key, []).append(m)
        
        for (direction, threshold), sub in sub_groups.items():
            dated = []
            for m in sub:
                d = parse_deadline(m.deadline)
                if d:
                    dated.append((d, m))
            
            dated.sort(key=lambda x: x[0])
            
            for i in range(len(dated) - 1):
                earlier_date, earlier_m = dated[i]
                later_date, later_m = dated[i + 1]
                
                if earlier_date == later_date:
                    continue
                
                # Later deadline should have >= probability
                if earlier_m.yes_price > later_m.yes_price and earlier_m.yes_price > 0:
                    margin = (earlier_m.yes_price - later_m.yes_price) * 100
                    arbs.append(ArbOpportunity(
                        arb_type="TIMELINE_INVERSION",
                        market_a=earlier_m,
                        market_b=later_m,
                        margin=margin,
                        description=(
                            f"'{earlier_m.question[:60]}' ({earlier_m.yes_price:.1%}) > "
                            f"'{later_m.question[:60]}' ({later_m.yes_price:.1%})"
                        ),
                        risk_note="Earlier deadline can't be more likely than later — true arb if same underlying",
                        confidence="HIGH"
                    ))
    
    return arbs


def parse_deadline(deadline_str: str) -> Optional[date]:
    """Try to parse a deadline string into a date."""
    for fmt in ['%B %d, %Y', '%B %d %Y', '%b %d, %Y']:
        try:
            return datetime.strptime(deadline_str.strip(), fmt).date()
        except ValueError:
            continue
    # Try partial: "December 31, 2026"
    match = re.search(r'(\w+)\s+(\d+),?\s+(\d{4})', deadline_str)
    if match:
        try:
            return datetime.strptime(f"{match.group(1)} {match.group(2)}, {match.group(3)}", "%B %d, %Y").date()
        except ValueError:
            pass
    return None


def find_cross_event_arbs(markets: list[Market]) -> list[ArbOpportunity]:
    """Find inconsistencies across related events."""
    arbs = []
    
    # BTC ATH vs reach markets
    # If ATH is at ~$109K, then "reach $110K" ≈ "new ATH"
    ath_markets = [m for m in markets if 'all time high' in m.question.lower()]
    reach_markets = [m for m in markets if m.direction == 'reach']
    
    for ath in ath_markets:
        ath_deadline = parse_deadline(ath.deadline) if ath.deadline else None
        # ATH ~= reach ~$110K (approximate)
        for reach in reach_markets:
            reach_deadline = parse_deadline(reach.deadline) if reach.deadline else None
            if not reach.threshold or not ath_deadline or not reach_deadline:
                continue
            # If same deadline and threshold near ATH (~$109K)
            if (ath_deadline == reach_deadline and 
                105000 <= reach.threshold <= 115000):
                diff = abs(ath.yes_price - reach.yes_price)
                if diff > 0.02:
                    arbs.append(ArbOpportunity(
                        arb_type="CROSS_EVENT",
                        market_a=ath,
                        market_b=reach,
                        margin=diff * 100,
                        description=(
                            f"ATH ({ath.yes_price:.1%}) vs reach ${reach.threshold:,.0f} "
                            f"({reach.yes_price:.1%}) by same deadline — should be ~equal"
                        ),
                        risk_note="Depends on exact ATH value assumption; ~$109K as of late 2024",
                        confidence="MEDIUM"
                    ))
    
    return arbs


def analyze_reach_distribution(markets: list[Market]) -> str:
    """Generate a price distribution analysis of reach markets."""
    reach = [m for m in markets if m.direction == 'reach' and m.threshold and 'December 31, 2026' in m.deadline]
    if not reach:
        return ""
    
    reach.sort(key=lambda m: m.threshold)
    
    lines = ["### BTC Price Distribution (Reach by Dec 31, 2026)\n"]
    lines.append("| Threshold | Yes Price | Implied Prob | Δ from prev |")
    lines.append("|-----------|-----------|-------------|-------------|")
    
    prev = None
    for m in reach:
        delta = f"{(prev - m.yes_price)*100:+.1f}pp" if prev is not None else "—"
        lines.append(f"| ${m.threshold:>10,.0f} | {m.yes_price:>9.1%} | {m.yes_price:>11.1%} | {delta:>11} |")
        prev = m.yes_price
    
    return "\n".join(lines)


def analyze_dip_distribution(markets: list[Market]) -> str:
    """Generate distribution of dip markets."""
    dip = [m for m in markets if m.direction == 'dip' and m.threshold and 'December 31, 2026' in m.deadline]
    if not dip:
        return ""
    
    dip.sort(key=lambda m: m.threshold, reverse=True)
    
    lines = ["### BTC Dip Distribution (Dip to X by Dec 31, 2026)\n"]
    lines.append("| Threshold | Yes Price | Implied Prob | Δ from prev |")
    lines.append("|-----------|-----------|-------------|-------------|")
    
    prev = None
    for m in dip:
        delta = f"{(prev - m.yes_price)*100:+.1f}pp" if prev is not None else "—"
        lines.append(f"| ${m.threshold:>10,.0f} | {m.yes_price:>9.1%} | {m.yes_price:>11.1%} | {delta:>11} |")
        prev = m.yes_price
    
    return "\n".join(lines)


def generate_report(arbs: list[ArbOpportunity], markets: list[Market], today: str) -> str:
    """Generate the markdown report."""
    arbs.sort(key=lambda a: a.margin, reverse=True)
    
    high_confidence = [a for a in arbs if a.confidence == "HIGH"]
    medium_confidence = [a for a in arbs if a.confidence == "MEDIUM"]
    low_confidence = [a for a in arbs if a.confidence == "LOW"]
    
    total_margin = sum(a.margin for a in arbs)
    
    lines = [
        f"# Polymarket BTC Arbitrage Scan — {today}",
        f"\n**Scan time:** {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}",
        f"**Markets analyzed:** {len(markets)}",
        f"**Arbitrage opportunities found:** {len(arbs)}",
        f"  - HIGH confidence: {len(high_confidence)}",
        f"  - MEDIUM confidence: {len(medium_confidence)}",
        f"  - LOW confidence: {len(low_confidence)}",
        f"**Total arb margin (sum):** {total_margin:.1f} percentage points",
        "",
        "---",
        "",
    ]
    
    if arbs:
        lines.append("## Top Arbitrage Opportunities\n")
        for i, arb in enumerate(arbs[:10], 1):
            lines.append(f"### #{i} — {arb.arb_type} [{arb.confidence}]")
            lines.append(f"**Margin:** {arb.margin:.1f}pp")
            lines.append(f"**Description:** {arb.description}")
            lines.append(f"")
            lines.append(f"- **Market A:** {arb.market_a.question}")
            lines.append(f"  - Yes: {arb.market_a.yes_price:.1%} | Vol: ${arb.market_a.volume:,.0f} | Liq: ${arb.market_a.liquidity:,.0f}")
            lines.append(f"- **Market B:** {arb.market_b.question}")
            lines.append(f"  - Yes: {arb.market_b.yes_price:.1%} | Vol: ${arb.market_b.volume:,.0f} | Liq: ${arb.market_b.liquidity:,.0f}")
            lines.append(f"")
            lines.append(f"⚠️ **Risk:** {arb.risk_note}")
            lines.append("")
    else:
        lines.append("## No Arbitrage Opportunities Found\n")
        lines.append("All BTC threshold markets appear correctly ordered. The market is efficient today.\n")
    
    # Distribution tables
    reach_dist = analyze_reach_distribution(markets)
    dip_dist = analyze_dip_distribution(markets)
    
    if reach_dist or dip_dist:
        lines.append("---\n")
        lines.append("## Market Distribution Analysis\n")
        if reach_dist:
            lines.append(reach_dist)
            lines.append("")
        if dip_dist:
            lines.append(dip_dist)
            lines.append("")
    
    # Additional arbs beyond top 10
    if len(arbs) > 10:
        lines.append("---\n")
        lines.append(f"## Additional Opportunities ({len(arbs) - 10} more)\n")
        for arb in arbs[10:]:
            lines.append(f"- **{arb.arb_type}** [{arb.confidence}] {arb.margin:.1f}pp: {arb.description}")
    
    lines.append("\n---\n")
    lines.append("## Methodology\n")
    lines.append("- **Threshold Inversion:** P(BTC > higher target) > P(BTC > lower target) — logically impossible")
    lines.append("- **Dip Inversion:** P(BTC dips to lower price) > P(BTC dips to higher price) — logically impossible")
    lines.append("- **Timeline Inversion:** P(event by earlier date) > P(event by later date)")
    lines.append("- **Flat Pricing:** Same odds for different thresholds (likely stale/illiquid)")
    lines.append("- **Spread Compression:** Large threshold gap with tiny price difference")
    lines.append("- **Cross-Event:** Related events with inconsistent pricing")
    lines.append("\n**Disclaimer:** Markets may have different resolution criteria, liquidity conditions, ")
    lines.append("or be pricing in information not captured by simple threshold comparison. ")
    lines.append("Always verify resolution sources before trading.")
    
    return "\n".join(lines)


def main():
    today = date.today().isoformat()
    
    # Load data
    if len(sys.argv) > 1:
        path = sys.argv[1]
        print(f"Loading markets from {path}...")
        with open(path) as f:
            raw_markets = json.load(f)
    else:
        print("Fetching live markets from Polymarket API...")
        raw_markets = fetch_live_markets()
    
    print(f"Raw markets: {len(raw_markets)}")
    
    # Parse
    markets = []
    for raw in raw_markets:
        m = parse_market(raw)
        if m:
            markets.append(m)
    
    print(f"Parsed active markets: {len(markets)}")
    print(f"  - With thresholds: {len([m for m in markets if m.threshold])}")
    print(f"  - Reach markets: {len([m for m in markets if m.direction == 'reach'])}")
    print(f"  - Dip markets: {len([m for m in markets if m.direction == 'dip'])}")
    
    # Find arbs
    arbs = []
    arbs.extend(find_threshold_arbs(markets))
    arbs.extend(find_timeline_arbs(markets))
    arbs.extend(find_cross_event_arbs(markets))
    
    print(f"\nArbitrage opportunities found: {len(arbs)}")
    for a in sorted(arbs, key=lambda x: x.margin, reverse=True)[:5]:
        print(f"  [{a.confidence}] {a.arb_type}: {a.margin:.1f}pp — {a.description[:80]}")
    
    # Generate report
    report = generate_report(arbs, markets, today)
    
    # Write output
    output_dir = os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', '..', 'intel', 'analysis')
    os.makedirs(output_dir, exist_ok=True)
    output_path = os.path.join(output_dir, f"market_arbs_{today}.md")
    
    with open(output_path, 'w') as f:
        f.write(report)
    
    print(f"\nReport written to {output_path}")
    return arbs


if __name__ == '__main__':
    main()
