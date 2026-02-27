#!/bin/zsh
# ops/purge.sh - Eradicate OpenRouter & Legacy Bloat
# WARNING: This modifies 11 config files. Stage 0 creates backups.
# Usage: zsh ops/purge.sh [--dry-run]

set -euo pipefail

DRY_RUN=false
[[ "${1:-}" == "--dry-run" ]] && DRY_RUN=true

TIMESTAMP=$(date +"%Y%m%d_%H%M%S")
BACKUP_DIR="$HOME/.openclaw/backup/purge-${TIMESTAMP}"
OPENCLAW_ROOT="$HOME/.openclaw"
REPO_ROOT="$(cd "$(dirname "$0")/../.." && pwd)"

# Colors
RED='\033[0;31m'; GREEN='\033[0;32m'; YELLOW='\033[1;33m'; NC='\033[0m'
info()  { echo "${GREEN}[PURGE]${NC} $1"; }
warn()  { echo "${YELLOW}[WARN]${NC} $1"; }
error() { echo "${RED}[ERROR]${NC} $1"; }

if ! command -v jq &> /dev/null; then
    error "jq is required. Install: brew install jq"
    exit 1
fi

# ═══════════════════════════════════════════════════════════════
# STAGE 0: SNAPSHOT — Back up everything before touching it
# ═══════════════════════════════════════════════════════════════
info "Stage 0: Creating backup at $BACKUP_DIR"
mkdir -p "$BACKUP_DIR"

FILES_TO_BACKUP=(
    "$REPO_ROOT/openclaw.json"
    "$REPO_ROOT/agents/main/agent/models.json"
    "$REPO_ROOT/agents/main/agent/auth-profiles.json"
    "$REPO_ROOT/agents/commander/agent/models.json"
    "$REPO_ROOT/agents/commander/agent/auth-profiles.json"
    "$REPO_ROOT/agents/forge/agent/models.json"
    "$REPO_ROOT/agents/forge/agent/auth-profiles.json"
    "$REPO_ROOT/agents/pulse/agent/models.json"
    "$REPO_ROOT/agents/pulse/agent/auth-profiles.json"
    "$REPO_ROOT/agents/scout/agent/models.json"
    "$REPO_ROOT/agents/scout/agent/auth-profiles.json"
)

for f in "${FILES_TO_BACKUP[@]}"; do
    if [ -f "$f" ]; then
        REL_PATH="${f#$REPO_ROOT/}"
        mkdir -p "$BACKUP_DIR/$(dirname "$REL_PATH")"
        cp "$f" "$BACKUP_DIR/$REL_PATH"
    fi
done
info "Backed up ${#FILES_TO_BACKUP[@]} files."

if $DRY_RUN; then
    warn "DRY RUN MODE — showing what would change, no files modified."
fi

# ═══════════════════════════════════════════════════════════════
# STAGE 1: CONFIG PURGE — Remove OpenRouter from all JSON configs
# ═══════════════════════════════════════════════════════════════
info "Stage 1: Purging OpenRouter from configuration files..."

apply_jq() {
    local file="$1"
    local filter="$2"
    local desc="$3"

    if [ ! -f "$file" ]; then
        warn "File not found: $file"
        return
    fi

    if $DRY_RUN; then
        info "  [DRY] $desc → $file"
        jq "$filter" "$file" > /dev/null 2>&1 || warn "  Filter would fail on $file"
    else
        local tmp="${file}.tmp"
        if jq "$filter" "$file" > "$tmp" 2>/dev/null; then
            mv "$tmp" "$file"
            info "  $desc → $file"
        else
            rm -f "$tmp"
            error "  jq filter failed on $file: $desc"
        fi
    fi
}

# --- openclaw.json ---
MAIN_CFG="$REPO_ROOT/openclaw.json"
info "  Processing openclaw.json..."
apply_jq "$MAIN_CFG" 'del(.env.OPENROUTER_API_KEY)' "Remove OPENROUTER_API_KEY env"
apply_jq "$MAIN_CFG" 'del(.auth.profiles["openrouter:api"])' "Remove openrouter:api auth profile"
apply_jq "$MAIN_CFG" 'del(.auth.order.openrouter)' "Remove openrouter auth order"
apply_jq "$MAIN_CFG" 'del(.models.providers.openrouter)' "Remove openrouter provider"
apply_jq "$MAIN_CFG" '.agents.defaults.model.fallbacks |= map(select(. != "openrouter"))' "Remove openrouter from fallbacks"
apply_jq "$MAIN_CFG" 'del(.agents.defaults.models.openrouter)' "Remove openrouter alias"
apply_jq "$MAIN_CFG" '.agents.defaults.subagents.model.fallbacks |= map(select(. != "openrouter/auto"))' "Remove openrouter from subagent fallbacks"

# --- Per-agent models.json (5 agents) ---
AGENTS=("main" "commander" "forge" "pulse" "scout")
for agent in "${AGENTS[@]}"; do
    MODELS_FILE="$REPO_ROOT/agents/$agent/agent/models.json"
    apply_jq "$MODELS_FILE" 'del(.providers.openrouter)' "Remove openrouter provider from $agent"
done

# --- Per-agent auth-profiles.json (5 agents) ---
for agent in "${AGENTS[@]}"; do
    AUTH_FILE="$REPO_ROOT/agents/$agent/agent/auth-profiles.json"
    apply_jq "$AUTH_FILE" 'del(.profiles["openrouter:default"])' "Remove openrouter profile from $agent"
    apply_jq "$AUTH_FILE" 'del(.lastGood.openrouter)' "Remove openrouter lastGood from $agent"
    apply_jq "$AUTH_FILE" 'del(.usageStats["openrouter:default"])' "Remove openrouter usageStats from $agent"
done

# ═══════════════════════════════════════════════════════════════
# STAGE 2: STALE CRON CLEANUP
# ═══════════════════════════════════════════════════════════════
info "Stage 2: Checking for stale cron entries..."

if command -v crontab &> /dev/null; then
    CRON_HITS=$(crontab -l 2>/dev/null | grep -c "openclaw\|openrouter\|workspace/ops" || true)
    if [ "$CRON_HITS" -gt 0 ]; then
        warn "Found $CRON_HITS stale cron entries referencing openclaw/ops:"
        crontab -l 2>/dev/null | grep "openclaw\|openrouter\|workspace/ops" || true
        warn "Review manually: crontab -e"
    else
        info "  No stale cron entries found."
    fi
else
    info "  crontab not available (expected in sandbox)."
fi

# ═══════════════════════════════════════════════════════════════
# STAGE 3: VERIFY
# ═══════════════════════════════════════════════════════════════
info "Stage 3: Verification..."

ERRORS=0

# Check all JSON files are valid
for f in "${FILES_TO_BACKUP[@]}"; do
    if [ -f "$f" ]; then
        if ! jq empty "$f" 2>/dev/null; then
            error "  Invalid JSON: $f"
            ERRORS=$((ERRORS + 1))
        fi
    fi
done

# Check for remaining openrouter references in config JSONs
REMAINING=$(grep -rl "openrouter" "$REPO_ROOT/openclaw.json" \
    "$REPO_ROOT"/agents/*/agent/models.json \
    "$REPO_ROOT"/agents/*/agent/auth-profiles.json 2>/dev/null | wc -l | tr -d ' ')

if [ "$REMAINING" -gt 0 ]; then
    error "  Found $REMAINING files still referencing openrouter:"
    grep -rl "openrouter" "$REPO_ROOT/openclaw.json" \
        "$REPO_ROOT"/agents/*/agent/models.json \
        "$REPO_ROOT"/agents/*/agent/auth-profiles.json 2>/dev/null
    ERRORS=$((ERRORS + 1))
else
    info "  Zero openrouter references in config files."
fi

if [ "$ERRORS" -eq 0 ]; then
    info "Purge complete. All checks passed."
    info "Backup at: $BACKUP_DIR"
else
    error "Purge completed with $ERRORS errors. Review output above."
    error "Restore from: $BACKUP_DIR"
fi
