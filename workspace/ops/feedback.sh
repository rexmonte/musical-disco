#!/bin/zsh
# ops/feedback.sh - Capture Rex's feedback
# Use this script to record what works/doesn't for future briefings.
# It simply appends the feedback to reports/briefing_context.md

export PATH="/opt/homebrew/bin:$HOME/.npm-global/bin:$PATH:/usr/local/bin:/usr/bin:/bin"
FEEDBACK="$1"
CONTEXT_FILE="$HOME/.openclaw/workspace/reports/briefing_context.md"

if [ -z "$FEEDBACK" ]; then
  echo "Usage: ./ops/feedback.sh 'Your feedback here'"
  exit 1
fi

TIMESTAMP=$(date +"%Y-%m-%d")
echo "- $TIMESTAMP: $FEEDBACK" >> "$CONTEXT_FILE"

echo "Feedback recorded: $FEEDBACK"
