#!/bin/zsh
# ops/briefing.sh - Ace's Executive Summary
# Role: Consolidator & Filter
# Model: gemini-3-pro-preview (Smartest available)
# Schedule: 7:00 AM & 7:00 PM (End of shift / Start of day)

export PATH="/opt/homebrew/bin:$HOME/.npm-global/bin:$PATH:/usr/local/bin:/usr/bin:/bin"
export OPENCLAW_BIN="$HOME/.npm-global/bin/openclaw"
export OPENCLAW_CONFIG="$HOME/.openclaw/openclaw.json"

# Directories
INBOX="$HOME/.openclaw/workspace/reports/inbox"
ARCHIVE="$HOME/.openclaw/workspace/reports/archive"
CONTEXT_FILE="$HOME/.openclaw/workspace/reports/briefing_context.md"

# Ensure directories exist
mkdir -p "$ARCHIVE"
touch "$CONTEXT_FILE"

# check if there are reports
if [ -z "$(ls -A $INBOX)" ]; then
  echo "No reports in inbox. Skipping briefing."
  exit 0
fi

# 1. Aggregate Reports
echo "Aggregating reports..."
COMBINED_REPORT=""
for f in $INBOX/*.json; do
  AGENT=$(basename "$f" | cut -d_ -f1)
  CONTENT=$(cat "$f")
  COMBINED_REPORT+="\n--- REPORT FROM $AGENT ---\n$CONTENT\n"
done

# 2. Read Historical Context (What works/doesn't)
# We limit context to last 50 lines to keep prompt clean but relevant
CONTEXT_SNIPPET=$(tail -n 50 "$CONTEXT_FILE")

# 3. Generate Briefing via Cortex (Ace)
# We use the Gateway/CLI to spawn this as a "run" to get the output.
# We explicitly tell Cortex to be the "Chief of Staff".

PROMPT="
You are Ace (Cortex), the Chief of Staff for Rex.
Your sub-agents (Scout, Pulse, Forge) have submitted raw reports.
Your job is to consolidate them into a SINGLE, high-signal executive summary.

**User Context:**
- Rex works 12h night shifts (7p-7a). He is busy.
- Focus: Passive income, Polymarket bot dev, Sovereign living.
- He hates fluff. He wants actionable intel.

**Historical Feedback (What works/doesn't):**
$CONTEXT_SNIPPET

**Raw Sub-Agent Reports:**
$COMBINED_REPORT

**Directives:**
1. Filter out noise. If Pulse says 'Bitcoin is moving' but gives no reason, ignore it.
2. Prioritize Forge's blockers (technical issues).
3. Highlight high-yield opportunities from Scout ONLY if they are concrete.
4. Format:
   - 🛑 **Blockers/Urgent** (If any)
   - 🔨 **Build Progress** (Forge)
   - 💰 **Opportunities** (Scout/Pulse)
   - 🧠 **Strategic Suggestion** (Your synthesis)

Output the briefing text only.
"

# Send to Discord via 'message' tool or agent run
# We use 'agent' with --deliver to send it to the main chat or a specific briefing channel.
# Using 'commander' identity or just default Cortex.
"$OPENCLAW_BIN" agent \
  --agent "commander" \
  --message "$PROMPT" \
  --deliver \
  --reply-channel "discord" \
  --reply-to "1472703302494978172" \
  --thinking "low"

# 4. Cleanup
# Move processed reports to archive
mv "$INBOX"/*.json "$ARCHIVE/"
