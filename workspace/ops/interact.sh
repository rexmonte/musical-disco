#!/bin/bash
# ops/interact.sh
# Logic for per-channel interaction
# Requires: jq, openclaw CLI

CHANNEL_ID=$1
USER_MSG=$2
AGENT_NAME=""
MODEL=""
SYSTEM=""

# Load config
CONFIG=$(cat /Users/clawdrex/.openclaw/workspace/ops/agents.json)

# Check which agent owns this channel
if echo "$CONFIG" | jq -e ".scout | select(.channelId == \"$CHANNEL_ID\")" >/dev/null; then
  AGENT_NAME="scout"
elif echo "$CONFIG" | jq -e ".pulse | select(.channelId == \"$CHANNEL_ID\")" >/dev/null; then
  AGENT_NAME="pulse"
elif echo "$CONFIG" | jq -e ".forge | select(.channelId == \"$CHANNEL_ID\")" >/dev/null; then
  AGENT_NAME="forge"
else
  # Not a managed channel
  exit 0
fi

# Extract settings
MODEL=$(echo "$CONFIG" | jq -r ".$AGENT_NAME.model")
SYSTEM=$(echo "$CONFIG" | jq -r ".$AGENT_NAME.system")

# Spawn the reply
# Note: We use "run" mode for a single reply, or "session" if we want state.
# "run" is safer for simple Q&A.
openclaw sessions spawn \
  --task "$SYSTEM\n\nUser asked: $USER_MSG\n\nReply directly to them in channel $CHANNEL_ID." \
  --model "$MODEL" \
  --label "ops:$AGENT_NAME:reply" \
  --cleanup delete
