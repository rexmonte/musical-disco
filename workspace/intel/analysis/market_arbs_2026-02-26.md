# Polymarket BTC Arbitrage Scan — 2026-02-26

**Scan time:** 2026-02-26 22:32:21
**Markets analyzed:** 111
**Arbitrage opportunities found:** 8
  - HIGH confidence: 0
  - MEDIUM confidence: 5
  - LOW confidence: 3
**Total arb margin (sum):** 11.8 percentage points

---

## Top Arbitrage Opportunities

### #1 — CROSS_EVENT [MEDIUM]
**Margin:** 8.5pp
**Description:** ATH (18.0%) vs reach $110,000 (26.5%) by same deadline — should be ~equal

- **Market A:** Bitcoin all time high by December 31, 2026?
  - Yes: 18.0% | Vol: $401,682 | Liq: $41,044
- **Market B:** Will Bitcoin reach $110,000 by December 31, 2026?
  - Yes: 26.5% | Vol: $471,796 | Liq: $36,165

⚠️ **Risk:** Depends on exact ATH value assumption; ~$109K as of late 2024

### #2 — SPREAD_COMPRESSION [MEDIUM]
**Margin:** 1.0pp
**Description:** $10,000 gap but only 1.0% spread: $160,000 (7.5%) vs $170,000 (6.5%)

- **Market A:** Will Bitcoin reach $160,000 by December 31, 2026?
  - Yes: 7.5% | Vol: $298,466 | Liq: $55,840
- **Market B:** Will Bitcoin reach $170,000 by December 31, 2026?
  - Yes: 6.5% | Vol: $194,970 | Liq: $30,816

⚠️ **Risk:** Compressed spread suggests one side is mispriced or illiquid

### #3 — FLAT_PRICING [LOW]
**Margin:** 0.5pp
**Description:** P(BTC reach $160,000) = P(BTC reach $150,000) = 7.5% by December 31, 2026

- **Market A:** Will Bitcoin reach $150,000 by December 31, 2026?
  - Yes: 7.5% | Vol: $599,748 | Liq: $59,607
- **Market B:** Will Bitcoin reach $160,000 by December 31, 2026?
  - Yes: 7.5% | Vol: $298,466 | Liq: $55,840

⚠️ **Risk:** Same price for different thresholds — likely low liquidity/stale

### #4 — FLAT_PRICING [LOW]
**Margin:** 0.5pp
**Description:** P(BTC reach $180,000) = P(BTC reach $170,000) = 6.5% by December 31, 2026

- **Market A:** Will Bitcoin reach $170,000 by December 31, 2026?
  - Yes: 6.5% | Vol: $194,970 | Liq: $30,816
- **Market B:** Will Bitcoin reach $180,000 by December 31, 2026?
  - Yes: 6.5% | Vol: $313,933 | Liq: $48,107

⚠️ **Risk:** Same price for different thresholds — likely low liquidity/stale

### #5 — FLAT_PRICING [LOW]
**Margin:** 0.5pp
**Description:** P(BTC reach $190,000) = P(BTC reach $180,000) = 6.5% by December 31, 2026

- **Market A:** Will Bitcoin reach $180,000 by December 31, 2026?
  - Yes: 6.5% | Vol: $313,933 | Liq: $48,107
- **Market B:** Will Bitcoin reach $190,000 by December 31, 2026?
  - Yes: 6.5% | Vol: $335,514 | Liq: $43,656

⚠️ **Risk:** Same price for different thresholds — likely low liquidity/stale

### #6 — SPREAD_COMPRESSION [MEDIUM]
**Margin:** 0.5pp
**Description:** $10,000 gap but only 0.5% spread: $130,000 (12.0%) vs $140,000 (11.5%)

- **Market A:** Will Bitcoin reach $130,000 by December 31, 2026?
  - Yes: 12.0% | Vol: $547,274 | Liq: $68,499
- **Market B:** Will Bitcoin reach $140,000 by December 31, 2026?
  - Yes: 11.5% | Vol: $551,625 | Liq: $65,983

⚠️ **Risk:** Compressed spread suggests one side is mispriced or illiquid

### #7 — SPREAD_COMPRESSION [MEDIUM]
**Margin:** 0.2pp
**Description:** $500,000 gap but only 0.2% spread: $500,000 (1.5%) vs $1,000,000 (1.3%)

- **Market A:** Will Bitcoin reach $500,000 by December 31, 2026?
  - Yes: 1.5% | Vol: $26,677 | Liq: $62,791
- **Market B:** Will Bitcoin reach $1,000,000 by December 31, 2026?
  - Yes: 1.3% | Vol: $31,826 | Liq: $129,302

⚠️ **Risk:** Compressed spread suggests one side is mispriced or illiquid

### #8 — SPREAD_COMPRESSION [MEDIUM]
**Margin:** 0.1pp
**Description:** $50,000 gap but only 0.1% spread: $200,000 (5.5%) vs $250,000 (5.4%)

- **Market A:** Will Bitcoin reach $200,000 by December 31, 2026?
  - Yes: 5.5% | Vol: $649,972 | Liq: $53,475
- **Market B:** Will Bitcoin reach $250,000 by December 31, 2026?
  - Yes: 5.4% | Vol: $3,265,179 | Liq: $67,814

⚠️ **Risk:** Compressed spread suggests one side is mispriced or illiquid

---

## Market Distribution Analysis

### BTC Price Distribution (Reach by Dec 31, 2026)

| Threshold | Yes Price | Implied Prob | Δ from prev |
|-----------|-----------|-------------|-------------|
| $    75,000 |     85.5% |       85.5% |           — |
| $    80,000 |     71.0% |       71.0% |     +14.5pp |
| $    90,000 |     49.5% |       49.5% |     +21.5pp |
| $   100,000 |     38.5% |       38.5% |     +11.0pp |
| $   110,000 |     26.5% |       26.5% |     +12.0pp |
| $   120,000 |     19.5% |       19.5% |      +7.0pp |
| $   130,000 |     12.0% |       12.0% |      +7.5pp |
| $   140,000 |     11.5% |       11.5% |      +0.5pp |
| $   150,000 |     10.5% |       10.5% |      +1.0pp |
| $   150,000 |      7.5% |        7.5% |      +3.0pp |
| $   160,000 |      7.5% |        7.5% |      +0.0pp |
| $   170,000 |      6.5% |        6.5% |      +1.0pp |
| $   180,000 |      6.5% |        6.5% |      +0.0pp |
| $   190,000 |      6.5% |        6.5% |      +0.0pp |
| $   200,000 |      5.5% |        5.5% |      +1.0pp |
| $   250,000 |      5.4% |        5.4% |      +0.1pp |
| $   500,000 |      1.5% |        1.5% |      +3.9pp |
| $ 1,000,000 |      1.3% |        1.3% |      +0.2pp |

### BTC Dip Distribution (Dip to X by Dec 31, 2026)

| Threshold | Yes Price | Implied Prob | Δ from prev |
|-----------|-----------|-------------|-------------|
| $    55,000 |     75.5% |       75.5% |           — |
| $    50,000 |     62.5% |       62.5% |     +13.0pp |
| $    45,000 |     50.0% |       50.0% |     +12.5pp |
| $    40,000 |     41.0% |       41.0% |      +9.0pp |
| $    35,000 |     30.0% |       30.0% |     +11.0pp |
| $    30,000 |     18.0% |       18.0% |     +12.0pp |
| $    25,000 |     14.0% |       14.0% |      +4.0pp |
| $    20,000 |     10.5% |       10.5% |      +3.5pp |
| $    15,000 |      7.6% |        7.6% |      +2.9pp |
| $    10,000 |      5.9% |        5.9% |      +1.7pp |
| $     5,000 |      3.9% |        3.9% |      +2.0pp |


---

## Methodology

- **Threshold Inversion:** P(BTC > higher target) > P(BTC > lower target) — logically impossible
- **Dip Inversion:** P(BTC dips to lower price) > P(BTC dips to higher price) — logically impossible
- **Timeline Inversion:** P(event by earlier date) > P(event by later date)
- **Flat Pricing:** Same odds for different thresholds (likely stale/illiquid)
- **Spread Compression:** Large threshold gap with tiny price difference
- **Cross-Event:** Related events with inconsistent pricing

**Disclaimer:** Markets may have different resolution criteria, liquidity conditions, 
or be pricing in information not captured by simple threshold comparison. 
Always verify resolution sources before trading.