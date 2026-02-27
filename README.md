# OpenClaw Configuration Repository

Personal [OpenClaw](https://docs.openclaw.ai) infrastructure configuration — a local-first, multi-agent AI assistant platform.

## Architecture

```
Mac Mini M4 (32GB) → Ollama (local) + Anthropic/Google API fallbacks
                   → OpenClaw Gateway (localhost:18789)
                   → Discord bot interface
```

### Model Stack

| Tier | Model | Use Case | Cost |
|------|-------|----------|------|
| Local Primary | `ollama/qwen3.5:35b` | General reasoning (MoE, multimodal) | Free |
| Local Coder | `ollama/qwen3-coder:30b` | Code generation & debugging | Free |
| Local Fast | `ollama/qwen3:8b` | Trivial questions, classification | Free |
| Cloud Cheap | `anthropic/claude-haiku` | Web search, quick cloud tasks | ~$0.001/req |
| Cloud Smart | `anthropic/claude-sonnet-4` | Complex analysis | ~$0.01/req |
| Cloud Flash | `google/gemini-2.5-flash` | Long context (1M tokens) | ~$0.001/req |
| Cloud Pro | `google/gemini-2.5-pro` | Advanced reasoning | ~$0.01/req |

### Intelligent Router (`workspace/ops/route.py`)

Three-tier prompt classification:
- **Tier 0**: Regex pattern matching (0ms) — privacy, code, web, simple questions
- **Tier 1**: Heuristic scoring across 5 dimensions (<1ms)
- **Tier 2**: LLM classification via `qwen3:8b` (~1.5s, ambiguous cases only)

Privacy-sensitive prompts always stay local. Long-context tasks route to cloud. Saturation detection escalates to cloud when Ollama is busy.

### Agents

| Agent | Model | Role |
|-------|-------|------|
| **main** (Cortex) | qwen3.5:35b | Primary interactive agent |
| **scout** | qwen3:30b-a3b | Passive income research |
| **pulse** | qwen3:14b | Trend monitoring |
| **forge** | qwen3-coder:30b | Engineering & MVP building |
| **commander** | — | Orchestration |

### Automated Intel Pipeline (Cron)

| Time (PST) | Job | Model | Output |
|-------------|-----|-------|--------|
| 6:00 AM | `intel:collect` | Claude Haiku | `workspace/intel/raw/YYYY-MM-DD.json` |
| 6:45 AM | `intel:analyze` | qwen3.5:35b (local) | `workspace/intel/analysis/YYYY-MM-DD.md` |
| 7:30 AM | `daily:briefing` | Claude Haiku | Discord DM delivery |

## Setup

### Prerequisites

- [OpenClaw](https://docs.openclaw.ai) installed
- [Ollama](https://ollama.ai) with models pulled:
  ```bash
  ollama pull qwen3:8b
  ollama pull qwen3:14b
  ollama pull qwen3:30b-a3b
  ollama pull qwen3-coder:30b
  ollama pull qwen3.5:35b
  ```
- API keys for Anthropic and Google (optional, for cloud fallback)
- Discord bot token (optional, for Discord channel)

### Deploy

1. Clone this repo into your OpenClaw config directory:
   ```bash
   git clone https://github.com/rexmonte/musical-disco.git ~/.openclaw
   ```

2. Set real API keys in `openclaw.json` → `env` section:
   ```json
   {
     "env": {
       "ANTHROPIC_API_KEY": "sk-ant-...",
       "GEMINI_API_KEY": "AI...",
       "DISCORD_BOT_TOKEN": "MTQ..."
     }
   }
   ```

3. Regenerate device identity (first run will auto-generate, or manually):
   ```bash
   openclaw identity regenerate
   ```

4. Update `node.json` with your hostname:
   ```json
   { "displayName": "your-hostname" }
   ```

5. Start the gateway:
   ```bash
   openclaw start
   ```

6. Verify:
   ```bash
   openclaw status
   ```

## Directory Structure

```
.
├── openclaw.json           # Master config (models, auth, channels, failover)
├── node.json               # Node identity & gateway connection
├── agents/                 # Per-agent auth profiles and model configs
│   ├── main/
│   ├── commander/
│   ├── forge/
│   ├── pulse/
│   └── scout/
├── workspace/              # Primary workspace (memory, ops, intel, projects)
│   ├── ops/                # Operational scripts (route.py, purge.sh, agent launchers)
│   ├── intel/              # Automated market intelligence pipeline
│   ├── memory/             # Daily memory files
│   ├── projects/           # Active projects (polymarket-bot)
│   └── reports/            # Agent reports and audit trails
├── sandboxes/              # Agent sandbox environments with skills
├── workspace-*/            # Per-agent workspace instances
├── cron/                   # Scheduled job definitions
├── identity/               # Device keypair and auth (REDACTED in repo)
├── devices/                # Paired device registry (REDACTED in repo)
├── delivery-queue/         # Pending message deliveries
├── media/                  # Inbound media storage
├── backup/                 # Session backups
└── completions/            # Shell autocomplete scripts
```

## Security Notes

- All API keys use `${VAR}` references resolved at runtime — never hardcoded
- Identity keypairs and device tokens are redacted in this repo; regenerated on deploy
- Twitter/X auth tokens and Discord webhooks are placeholder values
- The gateway binds to `127.0.0.1` only (localhost)
- Privacy-sensitive prompts are routed exclusively to local Ollama models
- See `openclaw security audit --deep` for runtime security checks

## Failover Policy

```
sequential → max 2 retries → exponential backoff
cooldown: 3 errors → 5min pause → 15min auto-reset
health checks: every 60s, 5s timeout
rate limits: respects Retry-After header, 10s-120s backoff range
```
