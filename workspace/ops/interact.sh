#!/bin/bash
# ops/interact.sh
# Logic for per-channel interaction
# Requires: jq, openclaw CLI

set -euo pipefail

CHANNEL_ID="${1:-}"
USER_MSG="${2:-}"
AGENT_NAME=""
MODEL=""
SYSTEM=""

# Validate inputs
if [ -z "$CHANNEL_ID" ] || [ -z "$USER_MSG" ]; then
  echo "Usage: interact.sh <channel_id> <user_message>" >&2
  exit 1
fi

# Sanitize: reject inputs with shell metacharacters or excessive length
if [ ${#USER_MSG} -gt 2000 ]; then
  echo "Message too long (max 2000 chars)" >&2
  exit 1
fi

# Load config
CONFIG_FILE="/Users/clawdrex/.openclaw/workspace/ops/agents.json"
if [ ! -f "$CONFIG_FILE" ]; then
  echo "agents.json not found" >&2
  exit 1
fi
CONFIG=$(cat "$CONFIG_FILE")

# Check which agent owns this channel (use --arg to prevent jq injection)
if echo "$CONFIG" | jq -e --arg cid "$CHANNEL_ID" '.scout | select(.channelId == $cid)' >/dev/null 2>&1; then
  AGENT_NAME="scout"
elif echo "$CONFIG" | jq -e --arg cid "$CHANNEL_ID" '.pulse | select(.channelId == $cid)' >/dev/null 2>&1; then
  AGENT_NAME="pulse"
elif echo "$CONFIG" | jq -e --arg cid "$CHANNEL_ID" '.forge | select(.channelId == $cid)' >/dev/null 2>&1; then
  AGENT_NAME="forge"
else
  # Not a managed channel
  exit 0
fi

# Extract settings using --arg to prevent injection
MODEL=$(echo "$CONFIG" | jq -r --arg a "$AGENT_NAME" '.[$a].model')
SYSTEM=$(echo "$CONFIG" | jq -r --arg a "$AGENT_NAME" '.[$a].system')

# Build task string safely using printf
TASK=$(printf '%s\n\nUser asked: %s\n\nReply directly to them in channel %s.' "$SYSTEM" "$USER_MSG" "$CHANNEL_ID")

# Spawn the reply
openclaw sessions spawn \
  --task "$TASK" \
  --model "$MODEL" \
  --label "ops:${AGENT_NAME}:reply" \
  --cleanup delete
