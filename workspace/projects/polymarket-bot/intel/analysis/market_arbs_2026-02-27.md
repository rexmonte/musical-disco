# Polymarket Cross-Market Arbitrage Scan

**Generated:** 2026-02-27 06:28 UTC
**Data source:** 2026-02-27T05:53:47.176791+00:00
**Markets analyzed:** 3613

## Summary

| Severity | Count |
|----------|-------|
| 🔴 HIGH | 0 |
| 🟡 MEDIUM | 1 |
| 🟢 LOW | 2 |
| ℹ️ INFO | 22 |
| **Total** | **25** |

## 🎯 Actionable Opportunities

### 🟡 MEDIUM — Range Sum Violation

**Event:** Bitcoin price on March 5?
**Finding:** Range buckets sum to 106.7% (expected ~100%) across 10 buckets

**Trade:**
- **Strategy:** sell all YES
- **Edge:** 6.65%

**Risk notes:**
- Range buckets are mutually exclusive → sum should be 100%
- Current sum: 106.7%
- Overshoot of 6.65% → sell overpriced buckets

---

## 📊 Minor Inconsistencies

- **What price will Bitcoin hit February 23-March 1?**: P(dip to $56,000) = 0.4% < P(dip to $54,000) = 0.9% (edge: 0.40%)
- **What price will Bitcoin hit in February?**: P(dip to $45,000) = 0.1% < P(dip to $40,000) = 0.1% (edge: 0.10%)

## 📅 Cross-Date Divergences

These aren't necessarily arb — later dates *should* have different odds. But large spreads are worth monitoring.

- $75,000 strike: February @ 2.8% vs What price will Bitcoin hit in 2026? @ 86.0% (Δ83.2%)
- $80,000 strike: February @ 0.5% vs What price will Bitcoin hit in 2026? @ 71.0% (Δ70.5%)
- $80,000 strike: February 23-March 1 @ 0.6% vs What price will Bitcoin hit in 2026? @ 71.0% (Δ70.4%)
- $90,000 strike: February @ 0.1% vs What price will Bitcoin hit in 2026? @ 49.5% (Δ49.5%)
- $100,000 strike: February @ 0.1% vs What price will Bitcoin hit in 2026? @ 38.5% (Δ38.5%)
- $70,000 strike: February 23-March 1 @ 37.0% vs February 27 @ 4.8% (Δ32.2%)
- $110,000 strike: February @ 0.1% vs What price will Bitcoin hit in 2026? @ 27.5% (Δ27.5%)
- $70,000 strike: February 23-March 1 @ 37.0% vs February 28 @ 11.5% (Δ25.5%)
- $66,000 strike: February 27 @ 92.5% vs March 5 @ 67.5% (Δ25.0%)
- $70,000 strike: February 27 @ 4.8% vs March 5 @ 29.5% (Δ24.7%)
- $70,000 strike: February 27 @ 4.8% vs March 4 @ 28.0% (Δ23.2%)
- $66,000 strike: February 27 @ 92.5% vs March 4 @ 69.5% (Δ23.0%)
- $70,000 strike: February 23-March 1 @ 37.0% vs March 1 @ 16.3% (Δ20.7%)
- $66,000 strike: February 27 @ 92.5% vs March 3 @ 72.0% (Δ20.5%)
- $70,000 strike: February 27 @ 4.8% vs March 3 @ 24.5% (Δ19.7%)
- $120,000 strike: February @ 0.1% vs What price will Bitcoin hit in 2026? @ 19.5% (Δ19.4%)
- $70,000 strike: February 28 @ 11.5% vs March 5 @ 29.5% (Δ18.0%)
- $66,000 strike: February 28 @ 84.5% vs March 5 @ 67.5% (Δ17.0%)
- $70,000 strike: February 28 @ 11.5% vs March 4 @ 28.0% (Δ16.5%)
- $64,000 strike: February 27 @ 98.7% vs March 5 @ 82.5% (Δ16.2%)
- $72,000 strike: February 27 @ 0.7% vs March 5 @ 16.0% (Δ15.3%)
- $66,000 strike: February 28 @ 84.5% vs March 4 @ 69.5% (Δ15.0%)

## Notes

- **Fees:** Polymarket charges ~2% on profits. Spreads under 2% are likely not profitable.
- **Slippage:** Check CLOB order book depth. Thin books mean your order moves the price.
- **Settlement risk:** Ensure paired markets use the same oracle and settlement time.
- **This scan is a snapshot.** Odds change by the second. Re-run before trading.
