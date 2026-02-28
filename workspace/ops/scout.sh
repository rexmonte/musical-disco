#!/bin/zsh
# ops/scout.sh - Passive Income Research
# Model: ollama/qwen3:30b-a3b
# Schedule: :00 every 2 hours

export PATH="/opt/homebrew/bin:$HOME/.npm-global/bin:$PATH:/usr/local/bin:/usr/bin:/bin"
export OPENCLAW_BIN="$HOME/.npm-global/bin/openclaw"
export OPENCLAW_CONFIG="$HOME/.openclaw/openclaw.json"

# FORCE local configuration
export OLLAMA_HOST="http://127.0.0.1:11434"
export OLLAMA_API_KEY="ollama" 
export NO_COLOR=1

# Audit Logging
AUDIT_FILE="/Users/clawdrex/.openclaw/workspace/reports/usage_audit.csv"
START_TIME=$(date +%s)
MODEL_USED="ollama/qwen3:30b-a3b"

# Timestamp for report file
TIMESTAMP=$(date +"%Y-%m-%d_%H%M")
REPORT_FILE="/Users/clawdrex/.openclaw/workspace/reports/inbox/scout_${TIMESTAMP}.json"

cd /Users/clawdrex/.openclaw/workspace

# Check for priority task
PRIORITY_FILE="$HOME/.openclaw/workspace/reports/priority_scout.txt"
if [ -f "$PRIORITY_FILE" ]; then
  TASK=$(cat "$PRIORITY_FILE")
  rm "$PRIORITY_FILE"
  echo "Running priority task: $TASK"
else
  TASK="Research high-yield passive income opportunities compatible with a $95k income + 12h night shift schedule. Focus on: Defi yields, dividends, automated businesses, or crypto strategies. Output ONLY a valid JSON object with keys: 'summary', 'opportunities' (array), and 'risk_assessment'."
fi

# Run agent and capture output
"$OPENCLAW_BIN" agent \
  --agent "scout" \
  --message "$TASK" \
  --deliver \
  --local \
  --reply-channel "discord" \
  --reply-to "1475007773816131635" \
  --thinking "off" \
  --timeout 600 > "$REPORT_FILE" 2>&1
EXIT_CODE=$?

# If the output is empty or exit code non-zero, write an error sentinel so
# downstream parsers don't crash on empty files.
if [ ! -s "$REPORT_FILE" ] || [ $EXIT_CODE -ne 0 ]; then
  echo "{\"error\": \"scout run failed\", \"exit_code\": $EXIT_CODE, \"timestamp\": \"$(date -u +%Y-%m-%dT%H:%M:%SZ)\"}" > "$REPORT_FILE"
fi

# Log execution stats
END_TIME=$(date +%s)
DURATION=$((END_TIME - START_TIME))
echo "$(date),scout,$MODEL_USED,${DURATION}s,LOCAL_OLLAMA,exit=${EXIT_CODE}" >> "$AUDIT_FILE"
