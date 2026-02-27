# Projects Directory

## Active Projects

### Polymarket Arbitrage Bot
**Status:** Building - in active iteration

**What:** High-frequency Polymarket bot that exploits mispriced odds, particularly on BTC 5m/15m charts. Focus on arbitrage opportunities:
- Cross-market arbitrage (correlated markets with inconsistent pricing)
- Temporal arbitrage (buy low, wait for odds to adjust, sell)
- Funding rate arb (when market odds diverge from probability)

**Current State:** Initial research phase - analyzing market structures, identifying alpha sources.

**Files:**
- `projects/polymarket-bot/` - Active development directory
- `projects/polymarket-bot/alpha-research/` - Market analysis

**Next Steps:** [Update this as you work]

---

### Intel Pipeline
**Status:** Active - runs daily 6:00 AM - 7:30 AM PST

**What:** Automated market intelligence system
- 6:00 AM: Collect BTC/Polymarket data (haiku API)
- 6:45 AM: Analyze data (Qwen3.5 35B local)
- 7:30 AM: Deliver briefing to your DMs

**Status:** Operational. First run: 2026-02-27 06:00 AM

**Files:**
- `intel/` - Auto-generated data directory
- Cron jobs: `intel:collect`, `intel:analyze`, `daily:briefing`

---

### General Notes
- Always review `AGENTS.md` before starting coding session
- Always review `MEMORY.md` for context from previous sessions
- All significant decisions documented in `memory/YYYY-MM-DD.md`
- Workspace = source of truth. Not chat history.
