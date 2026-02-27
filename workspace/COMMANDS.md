# Command Cheatsheet (Tip #11 & #31)

## Model Switching
- `/q8` — Qwen3 8B Fast (fastest, subagents)
- `/q14` — Qwen3 14B Fast (balanced)
- `/moe` — Qwen3 30B MoE Fast (default, best quality+speed)
- `/coder` — Qwen3 Coder 30B Fast (code tasks)
- `/sonnet` — Claude Sonnet (API fallback)
- `/haiku` — Claude Haiku (API fallback, cheapest)
- `/opus` — Claude Opus (API fallback, strongest)

## Common Commands
- `/status` — Session status, model, usage
- `/reasoning` — Toggle reasoning/thinking mode
- `/model <alias>` — Switch model mid-conversation
- `/reset` — Reset conversation context

## Workflow Shortcuts
- "Farm this" — Trigger SMG receipt survey skill
- "Morning brief" — Get summary of emails, calendar, weather
- "End session" — Summary + git commit check

## OpenClaw CLI
- `openclaw status` — System overview
- `openclaw security audit --deep` — Security check
- `openclaw update` — Update to latest version
- `openclaw doctor` — Diagnose issues
- `openclaw gateway restart` — Restart service
