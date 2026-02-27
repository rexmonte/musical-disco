#!/bin/zsh
# ops/vision.sh - Meta Ray-Ban Analysis Agent
# Role: Process images from #sight channel
# Model: gemini-2.0-flash (Fast Vision)
# Schedule: */30 * * * * (Every 30 mins)

export PATH="/opt/homebrew/bin:$HOME/.npm-global/bin:$PATH:/usr/local/bin:/usr/bin:/bin"
export OPENCLAW_BIN="$HOME/.npm-global/bin/openclaw"
export OPENCLAW_CONFIG="$HOME/.openclaw/openclaw.json"

# Directories
INBOX="$HOME/.openclaw/workspace/reports/inbox"
MEDIA_DIR="$HOME/.openclaw/workspace/media/vision"
SEEN_FILE="$HOME/.openclaw/workspace/reports/seen_vision.txt"
TIMESTAMP=$(date +"%Y-%m-%d_%H%M")
REPORT_FILE="$INBOX/vision_${TIMESTAMP}.json"

mkdir -p "$MEDIA_DIR"
touch "$SEEN_FILE"

# 1. Fetch latest message from #sight (Channel ID: 1476493414341148768)
LATEST_MSG_JSON=$("$OPENCLAW_BIN" message read --target "1476493414341148768" --limit 1 --json)

if [ -z "$LATEST_MSG_JSON" ] || [ "$LATEST_MSG_JSON" = "[]" ]; then
  echo "No messages found in #sight."
  exit 0
fi

# Extract Message ID and Attachment URL
MSG_ID=$(echo "$LATEST_MSG_JSON" | jq -r '.[0].id')
IMG_URL=$(echo "$LATEST_MSG_JSON" | jq -r '.[0].attachments[0].url // empty')
IMG_NAME=$(echo "$LATEST_MSG_JSON" | jq -r '.[0].attachments[0].filename // empty')

# Check if already processed
if grep -q "$MSG_ID" "$SEEN_FILE"; then
  echo "Message $MSG_ID already processed."
  exit 0
fi

# Check if there is an image
if [ -z "$IMG_URL" ]; then
  echo "Message $MSG_ID has no image. Ignoring."
  echo "$MSG_ID" >> "$SEEN_FILE"
  exit 0
fi

echo "Processing image from message $MSG_ID..."

# 2. Download Image Locally
LOCAL_IMG_PATH="$MEDIA_DIR/${TIMESTAMP}_${IMG_NAME}"
curl -s -L "$IMG_URL" -o "$LOCAL_IMG_PATH"

# 3. Analyze Image with Vision Model
# We use 'agent' run with the image attached.
ANALYSIS=$("$OPENCLAW_BIN" agent \
  --agent "commander" \
  --message "Analyze this image from Rex's smart glasses: $IMG_URL.
  
  **Directives:**
  1. If text (whiteboard, document): Transcribe it fully.
  2. If chart/graph: Summarize the trend and key data points.
  3. If object/scene: Describe it and identify any actionable opportunities (e.g. 'For Sale sign', 'Brand logo').
  
  Output ONLY a JSON object:
  {
    \"summary\": \"Brief description\",
    \"text_content\": \"Full transcription if any\",
    \"insight\": \"Actionable takeaway for Rex\",
    \"local_path\": \"$LOCAL_IMG_PATH\"
  }" \
  --thinking "off")

# 4. Save Report
echo "$ANALYSIS" > "$REPORT_FILE"

# 5. Update Seen List
echo "$MSG_ID" >> "$SEEN_FILE"

# Audit Log
AUDIT_FILE="/Users/clawdrex/.openclaw/workspace/reports/usage_audit.csv"
echo "$(date),vision,gemini-2.0-flash,1_image,API" >> "$AUDIT_FILE"

echo "Vision analysis saved to $REPORT_FILE"
