#!/bin/zsh
# ops/crashwatch.sh — Automated Crash Watcher & Diagnostic Dump
# Monitors OpenClaw agent logs for fatal errors, captures full diagnostic context,
# and writes a ready-to-review crash report for Claude Code to analyze.
#
# Usage:
#   ./crashwatch.sh                  # Watch mode (runs continuously)
#   ./crashwatch.sh --scan           # One-shot scan of recent logs
#   ./crashwatch.sh --review FILE    # Pretty-print a crash file for review
#
# Designed for the "morning review" workflow:
#   1. OpenClaw agents run overnight, crashwatch catches failures
#   2. You wake up and run: claude "review crash logs" or read the summary
#   3. Claude Code reads the crash dump, finds the bug, generates a patch

export PATH="/opt/homebrew/bin:$HOME/.npm-global/bin:$PATH:/usr/local/bin:/usr/bin:/bin"

# ── Config ──
LOG_DIR="$HOME/.openclaw/logs/structured"
CRASH_DIR="$HOME/.openclaw/logs/crashes"
SUMMARY_DIR="$HOME/.openclaw/logs/crash-summaries"
CRON_LOG_DIR="/tmp"  # Where cron jobs write their raw logs

# Agent log files (from crontab.txt)
AGENT_LOGS=(
  "$CRON_LOG_DIR/scout.log"
  "$CRON_LOG_DIR/pulse.log"
  "$CRON_LOG_DIR/forge.log"
  "$CRON_LOG_DIR/briefing.log"
  "$CRON_LOG_DIR/librarian.log"
  "$CRON_LOG_DIR/vision.log"
)

# Error patterns to watch for
ERROR_PATTERNS=(
  "FATAL"
  "Error:"
  "error:"
  "Traceback"
  "panic:"
  "ECONNREFUSED"
  "ETIMEDOUT"
  "rate.limit"
  "429"
  "500 Internal"
  "503 Service"
  "model not found"
  "OOM"
  "killed"
  "segfault"
  "timeout expired"
  "ENOMEM"
)

mkdir -p "$CRASH_DIR" "$SUMMARY_DIR"

# ── Helpers ──
now_iso() { date -u +"%Y-%m-%dT%H:%M:%S.000Z"; }
today()   { date -u +"%Y-%m-%d"; }

# ── Build grep pattern from error list ──
build_error_regex() {
  local pattern=""
  for p in "${ERROR_PATTERNS[@]}"; do
    if [[ -n "$pattern" ]]; then
      pattern="$pattern|$p"
    else
      pattern="$p"
    fi
  done
  echo "$pattern"
}

# ── Extract diagnostic context around an error ──
extract_context() {
  local log_file="$1"
  local error_line="$2"
  local context_lines=30

  # Get line number of the error
  local line_num
  line_num=$(grep -n "$error_line" "$log_file" 2>/dev/null | tail -1 | cut -d: -f1)

  if [[ -n "$line_num" ]]; then
    local start=$((line_num - context_lines))
    [[ $start -lt 1 ]] && start=1
    local end=$((line_num + context_lines))
    sed -n "${start},${end}p" "$log_file"
  else
    tail -60 "$log_file"
  fi
}

# ── Scan a single log file for errors ──
scan_log() {
  local log_file="$1"
  local agent_name
  agent_name=$(basename "$log_file" .log)
  local error_regex
  error_regex=$(build_error_regex)

  if [[ ! -f "$log_file" ]]; then
    return 0
  fi

  # Only look at entries from the last 24 hours
  local recent_errors
  recent_errors=$(grep -iE "$error_regex" "$log_file" 2>/dev/null | tail -20)

  if [[ -z "$recent_errors" ]]; then
    return 0
  fi

  # Found errors — build crash report
  local crash_id="crash_$(date -u +%Y%m%dT%H%M%S)_${agent_name}"
  local crash_file="$CRASH_DIR/${crash_id}.json"

  # Get recent memory context if available
  local memory_file="$HOME/.openclaw/workspace/memory/$(today).md"
  local memory_context=""
  if [[ -f "$memory_file" ]]; then
    memory_context=$(tail -30 "$memory_file")
  fi

  # Get the last error line for context extraction
  local last_error_line
  last_error_line=$(echo "$recent_errors" | tail -1)
  local full_context
  full_context=$(extract_context "$log_file" "$last_error_line")

  # Get agent config
  local agent_config=""
  local agent_config_file="$HOME/.openclaw/agents/$agent_name/agent/models.json"
  if [[ -f "$agent_config_file" ]]; then
    agent_config=$(cat "$agent_config_file")
  fi

  # Build the crash report
  jq -cn \
    --arg id "$crash_id" \
    --arg ts "$(now_iso)" \
    --arg agent "$agent_name" \
    --arg log_file "$log_file" \
    --arg errors "$recent_errors" \
    --arg context "$full_context" \
    --arg memory "$memory_context" \
    --arg agent_cfg "$agent_config" \
    '{
      crash_id: $id,
      timestamp: $ts,
      agent: $agent,
      source_log: $log_file,
      error_lines: ($errors | split("\n") | map(select(. != ""))),
      surrounding_context: $context,
      recent_memory: (if $memory == "" then null else $memory end),
      agent_config: (if $agent_cfg == "" then null else ($agent_cfg | try fromjson catch $agent_cfg) end),
      diagnosis: null,
      patch: null
    }' > "$crash_file"

  echo "[CRASHWATCH] Error detected in $agent_name — dumped to $crash_file" >&2
  return 1
}

# ── Generate daily crash summary ──
generate_summary() {
  local crash_files=("$CRASH_DIR"/crash_$(today | tr -d '-')*.json(N))
  local crash_count=${#crash_files[@]}

  if [[ $crash_count -eq 0 ]]; then
    echo "[CRASHWATCH] No crashes today." >&2
    return 0
  fi

  local summary_file="$SUMMARY_DIR/summary_$(today).md"

  {
    echo "# OpenClaw Crash Summary — $(today)"
    echo ""
    echo "**Total crashes detected:** $crash_count"
    echo ""
    echo "---"
    echo ""

    for cf in "${crash_files[@]}"; do
      local agent ts errors
      agent=$(jq -r '.agent' "$cf")
      ts=$(jq -r '.timestamp' "$cf")
      errors=$(jq -r '.error_lines | join("\n")' "$cf")

      echo "## Agent: \`$agent\` — $ts"
      echo ""
      echo "**Errors:**"
      echo '```'
      echo "$errors"
      echo '```'
      echo ""
      echo "**Context:**"
      echo '```'
      jq -r '.surrounding_context' "$cf" | head -40
      echo '```'
      echo ""
      echo "**Crash file:** \`$cf\`"
      echo ""
      echo "---"
      echo ""
    done

    echo "## Quick Fix Commands"
    echo ""
    echo '```bash'
    echo "# Review full crash details:"
    echo "jq . $CRASH_DIR/crash_$(today | tr -d '-')*.json"
    echo ""
    echo "# Feed to Claude Code for automated diagnosis:"
    echo "# claude \"review crash logs in $SUMMARY_DIR/summary_$(today).md, identify failures, and generate patches\""
    echo '```'
  } > "$summary_file"

  echo "[CRASHWATCH] Summary written to $summary_file" >&2
  echo "$summary_file"
}

# ── Scan structured logs (JSONL) for errors ──
scan_structured_logs() {
  local today_log="$LOG_DIR/$(today).jsonl"
  if [[ ! -f "$today_log" ]]; then
    return 0
  fi

  local error_count
  error_count=$(grep -c '"level":"error"' "$today_log" 2>/dev/null || echo "0")

  if [[ "$error_count" -gt 0 ]]; then
    echo "[CRASHWATCH] Found $error_count errors in structured logs" >&2

    # Extract error entries
    grep '"level":"error"' "$today_log" | while IFS= read -r line; do
      local agent event
      agent=$(echo "$line" | jq -r '.agent // "unknown"')
      event=$(echo "$line" | jq -r '.event // "unknown"')
      echo "[CRASHWATCH]   $agent: $event" >&2
    done
  fi
}

# ── Review mode: pretty-print a crash file ──
review_crash() {
  local file="$1"
  if [[ ! -f "$file" ]]; then
    echo "File not found: $file" >&2
    exit 1
  fi

  echo "═══════════════════════════════════════════════════════════"
  echo "  CRASH REPORT: $(jq -r '.crash_id' "$file")"
  echo "═══════════════════════════════════════════════════════════"
  echo ""
  echo "Agent:     $(jq -r '.agent' "$file")"
  echo "Timestamp: $(jq -r '.timestamp' "$file")"
  echo "Log File:  $(jq -r '.source_log' "$file")"
  echo ""
  echo "── Error Lines ──"
  jq -r '.error_lines[]' "$file" 2>/dev/null
  echo ""
  echo "── Surrounding Context ──"
  jq -r '.surrounding_context' "$file" 2>/dev/null
  echo ""
  if jq -e '.recent_memory != null' "$file" >/dev/null 2>&1; then
    echo "── Recent Memory ──"
    jq -r '.recent_memory' "$file"
    echo ""
  fi
  echo "═══════════════════════════════════════════════════════════"
}

# ── Main ──
case "${1:-}" in
  --scan)
    echo "[CRASHWATCH] Scanning agent logs..." >&2
    FOUND_ERRORS=false

    for log in "${AGENT_LOGS[@]}"; do
      if ! scan_log "$log"; then
        FOUND_ERRORS=true
      fi
    done

    scan_structured_logs

    if $FOUND_ERRORS; then
      generate_summary
    else
      echo "[CRASHWATCH] All clear — no errors found." >&2
    fi
    ;;

  --review)
    if [[ -z "$2" ]]; then
      # Review most recent crash
      LATEST=$(ls -t "$CRASH_DIR"/*.json 2>/dev/null | head -1)
      if [[ -n "$LATEST" ]]; then
        review_crash "$LATEST"
      else
        echo "No crash files found in $CRASH_DIR" >&2
      fi
    else
      review_crash "$2"
    fi
    ;;

  --summary)
    generate_summary
    ;;

  "")
    # Watch mode — continuous monitoring
    echo "[CRASHWATCH] Starting continuous watch mode..." >&2
    echo "[CRASHWATCH] Scanning every 60 seconds. Ctrl-C to stop." >&2

    while true; do
      for log in "${AGENT_LOGS[@]}"; do
        scan_log "$log"
      done
      scan_structured_logs
      sleep 60
    done
    ;;

  *)
    echo "Usage: crashwatch.sh [--scan | --review [FILE] | --summary]" >&2
    echo ""
    echo "  (no args)    Continuous watch mode (every 60s)"
    echo "  --scan       One-shot scan of all agent logs"
    echo "  --review     Pretty-print latest (or specified) crash file"
    echo "  --summary    Generate daily crash summary markdown"
    exit 1
    ;;
esac
