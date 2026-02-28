#!/bin/zsh
# ops/pulse.sh - Trend Monitoring
# Model: ollama/qwen3:14b
# Schedule: :40 every 2 hours

export PATH="/opt/homebrew/bin:$HOME/.npm-global/bin:$PATH:/usr/local/bin:/usr/bin:/bin"
export OPENCLAW_BIN="$HOME/.npm-global/bin/openclaw"
export OPENCLAW_CONFIG="$HOME/.openclaw/openclaw.json"

export OLLAMA_HOST="http://127.0.0.1:11434"
export OLLAMA_API_KEY="ollama"
export NO_COLOR=1

# Audit Logging
AUDIT_FILE="/Users/clawdrex/.openclaw/workspace/reports/usage_audit.csv"
START_TIME=$(date +%s)
MODEL_USED="ollama/qwen3:14b"

TIMESTAMP=$(date +"%Y-%m-%d_%H%M")
REPORT_FILE="/Users/clawdrex/.openclaw/workspace/reports/inbox/pulse_${TIMESTAMP}.json"

cd /Users/clawdrex/.openclaw/workspace

"$OPENCLAW_BIN" agent \
  --agent "pulse" \
  --message "Scan for emerging trends in AI, crypto market structure, and biohacking/peptides. Look for signals relevant to Rex's interests (Polymarket, sovereign living). Post a bulleted summary of 3-5 key signals. Output ONLY a valid JSON object with keys: 'summary', 'signals' (array), 'polymarket_alerts' (array)." \
  --deliver \
  --local \
  --reply-channel "discord" \
  --reply-to "1475007798063534192" \
  --thinking "off" \
  --timeout 600 > "$REPORT_FILE" 2>&1
EXIT_CODE=$?

if [ ! -s "$REPORT_FILE" ] || [ $EXIT_CODE -ne 0 ]; then
  echo "{\"error\": \"pulse run failed\", \"exit_code\": $EXIT_CODE, \"timestamp\": \"$(date -u +%Y-%m-%dT%H:%M:%SZ)\"}" > "$REPORT_FILE"
fi

# Log execution stats
END_TIME=$(date +%s)
DURATION=$((END_TIME - START_TIME))
echo "$(date),pulse,$MODEL_USED,${DURATION}s,LOCAL_OLLAMA,exit=${EXIT_CODE}" >> "$AUDIT_FILE"
