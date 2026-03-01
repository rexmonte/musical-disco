# Long-Term Memory - Cortex

## Identity
Name: Cortex. Sharp, helpful, occasional cheekiness. Emoji: 🔧

## System (Feb 2026)
- Mac Mini M4 32GB. Primary model: qwen3.5-m4-optimized (8K ctx, MoE, ~100% GPU)
- Fallbacks: qwen3.5:27b -> haiku -> sonnet -> gemini-flash
- Gateway: OpenClaw via LaunchAgent, Discord channel

## Active Pipelines
- Intel: collect 6:00 AM, analyze 6:45 AM, briefing 7:30 AM (Discord DM)
- Bookmarks: collect 5:00 AM (Haiku), analyze 5:15 AM (Haiku). Data in workspace/bookmarks/
- Ops channels: #scout (research), #pulse (trends), #forge (MVPs) — 2h staggered cron

## Key People
- Rex: Boss. 35, night shift RN UCLA, 7.1+ BTC, building geographic sovereignty. Direct, technical.

## Handoff
- Check workspace/CHANGELOG.md for recent changes made via Claude Code terminal sessions.

## Lessons
- 48K context with Q8_0 KV cache = sweet spot on M4 32GB (was 32K, now ~2.4x more history)
- Qwen 35B can't handle multi-step prompts with code gen — use Haiku for those
- Stop gateway before editing sessions.json or cron/jobs.json
- MoE models = sweet spot for M4: fast as small, smart as large
- Chat history is cache. Files survive. Write it down.
