#!/bin/zsh
# ops/structlog.sh — Structured JSON Logger for OpenClaw Agent Supervision
# Wraps agent execution and captures structured, machine-readable logs.
# Captures: what the LLM was asked, what it responded, what was executed, exit status.
#
# Usage:
#   ./structlog.sh --agent scout --model ollama/qwen3:30b-a3b --prompt "..." [--skill "..."]
#   ./structlog.sh --wrap "command to execute" --agent forge --label "skill:build"
#
# Logs to: ~/.openclaw/logs/structured/YYYY-MM-DD.jsonl (one JSON object per line)

export PATH="/opt/homebrew/bin:$HOME/.npm-global/bin:$PATH:/usr/local/bin:/usr/bin:/bin"
export OPENCLAW_BIN="$HOME/.npm-global/bin/openclaw"

# ── Config ──
LOG_DIR="$HOME/.openclaw/logs/structured"
CRASH_DIR="$HOME/.openclaw/logs/crashes"
MAX_LOG_DAYS=30

mkdir -p "$LOG_DIR" "$CRASH_DIR"

# ── Args ──
AGENT=""
MODEL=""
PROMPT=""
SKILL=""
LABEL=""
WRAP_CMD=""
VERBOSE=false

while [[ $# -gt 0 ]]; do
  case $1 in
    --agent)   AGENT="$2";    shift 2 ;;
    --model)   MODEL="$2";    shift 2 ;;
    --prompt)  PROMPT="$2";   shift 2 ;;
    --skill)   SKILL="$2";    shift 2 ;;
    --label)   LABEL="$2";    shift 2 ;;
    --wrap)    WRAP_CMD="$2"; shift 2 ;;
    --verbose) VERBOSE=true;  shift ;;
    *)         shift ;;
  esac
done

# ── Helpers ──
now_iso() { date -u +"%Y-%m-%dT%H:%M:%S.000Z"; }
now_ms()  { python3 -c "import time; print(int(time.time()*1000))"; }
today()   { date -u +"%Y-%m-%d"; }

LOG_FILE="$LOG_DIR/$(today).jsonl"

emit_log() {
  local level="$1"
  local event="$2"
  local payload="$3"  # Must be valid JSON

  local entry
  entry=$(jq -cn \
    --arg ts "$(now_iso)" \
    --arg level "$level" \
    --arg event "$event" \
    --arg agent "$AGENT" \
    --arg model "$MODEL" \
    --arg skill "$SKILL" \
    --arg label "$LABEL" \
    --argjson payload "$payload" \
    '{
      timestamp: $ts,
      level: $level,
      event: $event,
      agent: $agent,
      model: $model,
      skill: (if $skill == "" then null else $skill end),
      label: (if $label == "" then null else $label end),
      payload: $payload
    }')

  echo "$entry" >> "$LOG_FILE"

  if $VERBOSE; then
    echo "$entry" | jq . >&2
  fi
}

# ── Rotate old logs ──
find "$LOG_DIR" -name "*.jsonl" -mtime +$MAX_LOG_DAYS -delete 2>/dev/null
find "$CRASH_DIR" -name "*.json" -mtime +$MAX_LOG_DAYS -delete 2>/dev/null

# ── Main execution ──
START_MS=$(now_ms)

if [[ -n "$WRAP_CMD" ]]; then
  # Wrap mode: execute an arbitrary command and log the result
  emit_log "info" "exec.start" "$(jq -cn --arg cmd "$WRAP_CMD" '{command: $cmd}')"

  OUTPUT=$(eval "$WRAP_CMD" 2>&1)
  EXIT_CODE=$?
  END_MS=$(now_ms)
  DURATION_MS=$((END_MS - START_MS))

  # Truncate output for log (keep first 4000 chars)
  TRUNCATED="${OUTPUT:0:4000}"

  if [[ $EXIT_CODE -eq 0 ]]; then
    emit_log "info" "exec.success" "$(jq -cn \
      --arg output "$TRUNCATED" \
      --argjson exit_code "$EXIT_CODE" \
      --argjson duration_ms "$DURATION_MS" \
      '{exit_code: $exit_code, duration_ms: $duration_ms, output_preview: $output}')"
  else
    emit_log "error" "exec.failure" "$(jq -cn \
      --arg output "$TRUNCATED" \
      --argjson exit_code "$EXIT_CODE" \
      --argjson duration_ms "$DURATION_MS" \
      '{exit_code: $exit_code, duration_ms: $duration_ms, output_preview: $output}')"

    # Dump crash log
    CRASH_FILE="$CRASH_DIR/crash_$(date -u +%Y%m%dT%H%M%S)_${AGENT:-unknown}.json"
    jq -cn \
      --arg ts "$(now_iso)" \
      --arg agent "$AGENT" \
      --arg model "$MODEL" \
      --arg skill "$SKILL" \
      --arg cmd "$WRAP_CMD" \
      --arg output "$OUTPUT" \
      --argjson exit_code "$EXIT_CODE" \
      --argjson duration_ms "$DURATION_MS" \
      '{
        crash_timestamp: $ts,
        agent: $agent,
        model: $model,
        skill: $skill,
        command: $cmd,
        exit_code: $exit_code,
        duration_ms: $duration_ms,
        full_output: $output
      }' > "$CRASH_FILE"

    emit_log "warn" "crash.dumped" "$(jq -cn --arg path "$CRASH_FILE" '{crash_file: $path}')"
  fi

elif [[ -n "$PROMPT" ]]; then
  # Agent prompt mode: route and execute via openclaw, log LLM thought vs action
  emit_log "info" "prompt.received" "$(jq -cn \
    --arg prompt "${PROMPT:0:2000}" \
    --argjson token_est "$(echo -n "$PROMPT" | wc -c | awk '{print int($1/4)}')" \
    '{prompt_preview: $prompt, estimated_tokens: $token_est}')"

  # Route if no model specified
  if [[ -z "$MODEL" ]]; then
    MODEL=$(python3 "$HOME/.openclaw/workspace/ops/route.py" --prompt "$PROMPT" 2>/dev/null)
    emit_log "info" "prompt.routed" "$(jq -cn --arg model "$MODEL" '{routed_model: $model}')"
  fi

  # Execute via openclaw agent
  OUTPUT=$("$OPENCLAW_BIN" agent \
    --agent "${AGENT:-main}" \
    --message "$PROMPT" \
    --model "$MODEL" \
    --thinking "off" 2>&1)
  EXIT_CODE=$?
  END_MS=$(now_ms)
  DURATION_MS=$((END_MS - START_MS))

  TRUNCATED="${OUTPUT:0:4000}"

  if [[ $EXIT_CODE -eq 0 ]]; then
    emit_log "info" "prompt.completed" "$(jq -cn \
      --arg response "$TRUNCATED" \
      --argjson exit_code "$EXIT_CODE" \
      --argjson duration_ms "$DURATION_MS" \
      '{exit_code: $exit_code, duration_ms: $duration_ms, response_preview: $response}')"
  else
    emit_log "error" "prompt.failed" "$(jq -cn \
      --arg response "$TRUNCATED" \
      --argjson exit_code "$EXIT_CODE" \
      --argjson duration_ms "$DURATION_MS" \
      '{exit_code: $exit_code, duration_ms: $duration_ms, error_output: $response}')"

    # Dump crash context
    CRASH_FILE="$CRASH_DIR/crash_$(date -u +%Y%m%dT%H%M%S)_${AGENT:-unknown}.json"
    jq -cn \
      --arg ts "$(now_iso)" \
      --arg agent "$AGENT" \
      --arg model "$MODEL" \
      --arg skill "$SKILL" \
      --arg prompt "$PROMPT" \
      --arg output "$OUTPUT" \
      --argjson exit_code "$EXIT_CODE" \
      --argjson duration_ms "$DURATION_MS" \
      '{
        crash_timestamp: $ts,
        agent: $agent,
        model: $model,
        skill: $skill,
        prompt: $prompt,
        exit_code: $exit_code,
        duration_ms: $duration_ms,
        full_output: $output
      }' > "$CRASH_FILE"

    emit_log "warn" "crash.dumped" "$(jq -cn --arg path "$CRASH_FILE" '{crash_file: $path}')"
  fi
else
  echo "Usage: structlog.sh --agent NAME --prompt 'text' [--model MODEL]" >&2
  echo "       structlog.sh --wrap 'command' --agent NAME --label 'tag'" >&2
  exit 1
fi
