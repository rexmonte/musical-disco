# CLAUDE.md — Context for Claude Code Sessions

## What This Repo Is

OpenClaw personal AI infrastructure config. Multi-agent system running on Mac Mini M4 (32GB) with Ollama local models + Anthropic/Google cloud fallbacks. Discord is the primary user interface.

## Key Files

- `openclaw.json` — Master config. All API keys are `${VAR}` references, real values are set at runtime.
- `agents/*/agent/models.json` — Per-agent model definitions (all agents share the same Ollama/Anthropic/Google provider setup).
- `workspace/ops/route.py` — Intelligent prompt router (3-tier: regex → heuristic → LLM). Pure Python, no dependencies.
- `workspace/ops/purge.sh` — Config cleanup script (removes dead providers via jq).
- `cron/jobs.json` — Three daily intel pipeline jobs (collect → analyze → briefing).

## Architecture Rules

1. **Privacy first**: Prompts matching privacy patterns MUST route to local Ollama models. Never to cloud.
2. **Local-first**: Default to `ollama/qwen3.5:35b`. Cloud is fallback only.
3. **8K context ceiling**: All local models are capped at 8192 tokens (32GB RAM constraint). Long-context goes to `google/gemini-2.5-flash` (1M context).
4. **No OpenRouter**: Previously used, fully purged. All routing goes direct to Anthropic/Google APIs.
5. **Secrets**: API keys use `${VAR}` interpolation. Identity files contain REDACTED placeholders. Never commit real secrets.

## Common Tasks

- **Adding a new model**: Add to `openclaw.json` → `models.providers` and update `agents.defaults.models` aliases. Also update `agents/*/agent/models.json` for per-agent availability.
- **Changing routing logic**: Edit `workspace/ops/route.py`. Test with `python3 route.py --prompt "test" --verbose --json`.
- **Adding a cron job**: Edit `cron/jobs.json`. Follow the existing `intel:collect` pattern.
- **Security audit**: Check for leaked secrets with `grep -r "sk-ant\|AIza\|MTQ\|BEGIN PRIVATE" --include="*.json" --include="*.md" --include="*.env*"`.
