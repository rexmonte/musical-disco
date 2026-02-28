#!/bin/zsh
# ops/killswitch.sh — Human-in-the-Loop Destructive Action Interception
# Intercepts dangerous commands and requires Discord DM confirmation before execution.
#
# Usage:
#   ./killswitch.sh --action "git push --force" --agent forge --reason "Deploying hotfix"
#   ./killswitch.sh --action "rm -rf /tmp/build" --agent main
#   ./killswitch.sh --action "gh issue close 42" --agent scout --timeout 300
#
# Flow:
#   1. Checks if action matches destructive patterns
#   2. If destructive: sends Discord DM asking for YES/NO confirmation
#   3. Waits for reply (default 5 min timeout)
#   4. If approved: executes and logs. If denied/timeout: blocks and logs.
#   5. Safe actions execute immediately with logging.

export PATH="/opt/homebrew/bin:$HOME/.npm-global/bin:$PATH:/usr/local/bin:/usr/bin:/bin"
export OPENCLAW_BIN="$HOME/.npm-global/bin/openclaw"

# ── Config ──
OWNER_DISCORD_ID="964788836775366746"
CONFIRM_TIMEOUT=300  # 5 minutes default
LOG_DIR="$HOME/.openclaw/logs/structured"
KILLSWITCH_LOG="$HOME/.openclaw/logs/killswitch.jsonl"

mkdir -p "$LOG_DIR" "$(dirname "$KILLSWITCH_LOG")"

# ── Args ──
ACTION=""
AGENT=""
REASON=""
DRY_RUN=false
FORCE_ALLOW=false

while [[ $# -gt 0 ]]; do
  case $1 in
    --action)   ACTION="$2";         shift 2 ;;
    --agent)    AGENT="$2";          shift 2 ;;
    --reason)   REASON="$2";         shift 2 ;;
    --timeout)  CONFIRM_TIMEOUT="$2"; shift 2 ;;
    --dry-run)  DRY_RUN=true;        shift ;;
    --force)    FORCE_ALLOW=true;    shift ;;
    *)          shift ;;
  esac
done

if [[ -z "$ACTION" ]]; then
  echo "Usage: killswitch.sh --action 'command' --agent NAME [--reason 'why'] [--timeout 300]" >&2
  exit 1
fi

# ── Helpers ──
now_iso() { date -u +"%Y-%m-%dT%H:%M:%S.000Z"; }

emit_ks_log() {
  local level="$1" event="$2" payload="$3"
  local entry
  entry=$(jq -cn \
    --arg ts "$(now_iso)" \
    --arg level "$level" \
    --arg event "$event" \
    --arg agent "$AGENT" \
    --arg action "$ACTION" \
    --argjson payload "$payload" \
    '{timestamp: $ts, level: $level, event: $event, agent: $agent, action: $action, payload: $payload}')
  echo "$entry" >> "$KILLSWITCH_LOG"
}

# ── Destructive Pattern Detection ──
is_destructive() {
  local cmd="$1"
  local lower="${cmd:l}"  # zsh lowercase

  # File destruction
  [[ "$lower" =~ "rm -rf" ]]          && return 0
  [[ "$lower" =~ "rm -r " ]]          && return 0
  [[ "$lower" =~ "rmdir" ]]           && return 0
  [[ "$lower" =~ "unlink " ]]         && return 0

  # Git destructive
  [[ "$lower" =~ "git push --force" ]] && return 0
  [[ "$lower" =~ "git push -f" ]]     && return 0
  [[ "$lower" =~ "git reset --hard" ]] && return 0
  [[ "$lower" =~ "git clean -f" ]]    && return 0
  [[ "$lower" =~ "git branch -D" ]]   && return 0
  [[ "$lower" =~ "git checkout -- " ]] && return 0
  [[ "$lower" =~ "git rebase" ]]      && return 0

  # GitHub destructive (closing/deleting)
  [[ "$lower" =~ "gh issue close" ]]   && return 0
  [[ "$lower" =~ "gh pr close" ]]      && return 0
  [[ "$lower" =~ "gh repo delete" ]]   && return 0
  [[ "$lower" =~ "gh release delete" ]] && return 0

  # Process killing
  [[ "$lower" =~ "kill -9" ]]          && return 0
  [[ "$lower" =~ "killall" ]]          && return 0
  [[ "$lower" =~ "pkill" ]]            && return 0

  # Database destructive
  [[ "$lower" =~ "drop table" ]]       && return 0
  [[ "$lower" =~ "drop database" ]]    && return 0
  [[ "$lower" =~ "truncate " ]]        && return 0
  [[ "$lower" =~ "delete from" ]]      && return 0

  # System-level
  [[ "$lower" =~ "chmod -R 777" ]]     && return 0
  [[ "$lower" =~ "launchctl remove" ]] && return 0

  # Bulk operations
  [[ "$lower" =~ "xargs rm" ]]         && return 0

  return 1  # Not destructive
}

# ── Check action ──
if $FORCE_ALLOW; then
  emit_ks_log "warn" "killswitch.force_bypassed" '{"forced": true}'
  eval "$ACTION"
  exit $?
fi

if ! is_destructive "$ACTION"; then
  # Safe action — execute immediately
  emit_ks_log "info" "killswitch.safe_action" '{"destructive": false}'
  eval "$ACTION"
  exit $?
fi

# ── Destructive action detected ──
emit_ks_log "warn" "killswitch.destructive_detected" "$(jq -cn \
  --arg action "$ACTION" \
  --arg reason "$REASON" \
  '{action: $action, reason: $reason}')"

if $DRY_RUN; then
  echo "[KILLSWITCH DRY-RUN] Would block: $ACTION" >&2
  emit_ks_log "info" "killswitch.dry_run_blocked" '{"dry_run": true}'
  exit 0
fi

# ── Send Discord confirmation request ──
CONFIRM_MSG="⚠️ **KILLSWITCH — Destructive Action Intercepted**

**Agent:** \`${AGENT:-unknown}\`
**Action:** \`\`\`${ACTION}\`\`\`
**Reason:** ${REASON:-No reason provided}
**Timeout:** ${CONFIRM_TIMEOUT}s

Reply **YES** to approve or **NO** to block."

# Write confirmation request to a pending file that OpenClaw can poll
PENDING_DIR="$HOME/.openclaw/logs/killswitch-pending"
mkdir -p "$PENDING_DIR"
REQUEST_ID="ks_$(date -u +%Y%m%dT%H%M%S)_$$"
PENDING_FILE="$PENDING_DIR/$REQUEST_ID.json"
RESPONSE_FILE="$PENDING_DIR/${REQUEST_ID}_response"

jq -cn \
  --arg id "$REQUEST_ID" \
  --arg ts "$(now_iso)" \
  --arg agent "$AGENT" \
  --arg action "$ACTION" \
  --arg reason "$REASON" \
  --arg message "$CONFIRM_MSG" \
  --argjson timeout "$CONFIRM_TIMEOUT" \
  '{
    id: $id,
    timestamp: $ts,
    agent: $agent,
    action: $action,
    reason: $reason,
    confirm_message: $message,
    timeout_seconds: $timeout,
    status: "pending"
  }' > "$PENDING_FILE"

# Send via openclaw agent to owner's Discord DM
"$OPENCLAW_BIN" agent \
  --agent "main" \
  --message "$CONFIRM_MSG" \
  --deliver \
  --reply-channel "discord" \
  --reply-to "$OWNER_DISCORD_ID" \
  --thinking "off" 2>/dev/null &

echo "[KILLSWITCH] Awaiting confirmation for: $ACTION" >&2
echo "[KILLSWITCH] Request ID: $REQUEST_ID" >&2
echo "[KILLSWITCH] Timeout: ${CONFIRM_TIMEOUT}s" >&2

# ── Wait for response ──
# OpenClaw should write YES or NO to the response file when the user replies.
# The bot's message handler needs to watch for replies to killswitch DMs and
# write the response to $RESPONSE_FILE.
# Alternatively, the user can manually: echo "YES" > $RESPONSE_FILE

ELAPSED=0
POLL_INTERVAL=5

while [[ $ELAPSED -lt $CONFIRM_TIMEOUT ]]; do
  if [[ -f "$RESPONSE_FILE" ]]; then
    RESPONSE=$(cat "$RESPONSE_FILE" | tr '[:lower:]' '[:upper:]' | tr -d '[:space:]')
    break
  fi
  sleep $POLL_INTERVAL
  ELAPSED=$((ELAPSED + POLL_INTERVAL))
done

# ── Evaluate response ──
if [[ -z "$RESPONSE" ]]; then
  # Timeout
  emit_ks_log "warn" "killswitch.timeout" "$(jq -cn \
    --argjson timeout "$CONFIRM_TIMEOUT" \
    '{result: "timeout", timeout_seconds: $timeout}')"

  echo "[KILLSWITCH] TIMEOUT — Action blocked: $ACTION" >&2

  # Update pending file
  jq '.status = "timeout"' "$PENDING_FILE" > "${PENDING_FILE}.tmp" && mv "${PENDING_FILE}.tmp" "$PENDING_FILE"
  exit 1

elif [[ "$RESPONSE" == "YES" ]]; then
  emit_ks_log "info" "killswitch.approved" '{"result": "approved"}'
  echo "[KILLSWITCH] APPROVED — Executing: $ACTION" >&2

  jq '.status = "approved"' "$PENDING_FILE" > "${PENDING_FILE}.tmp" && mv "${PENDING_FILE}.tmp" "$PENDING_FILE"

  eval "$ACTION"
  EXIT_CODE=$?

  emit_ks_log "info" "killswitch.executed" "$(jq -cn --argjson exit "$EXIT_CODE" '{exit_code: $exit}')"
  exit $EXIT_CODE

else
  emit_ks_log "info" "killswitch.denied" "$(jq -cn --arg resp "$RESPONSE" '{result: "denied", response: $resp}')"
  echo "[KILLSWITCH] DENIED — Action blocked: $ACTION" >&2

  jq '.status = "denied"' "$PENDING_FILE" > "${PENDING_FILE}.tmp" && mv "${PENDING_FILE}.tmp" "$PENDING_FILE"
  exit 1
fi
