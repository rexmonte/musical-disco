#!/bin/zsh
# ops/librarian.sh - Bookmark Scraper (Robust V2)
# Role: Fetch & Filter X Bookmarks
# Schedule: 6:30 AM daily

export PATH="/opt/homebrew/bin:$HOME/.npm-global/bin:$PATH:/usr/local/bin:/usr/bin:/bin"
# Source credentials
source "$HOME/.openclaw/workspace/.env.bird"

INBOX="$HOME/.openclaw/workspace/reports/inbox"
SEEN_FILE="$HOME/.openclaw/workspace/reports/seen_bookmarks.txt"
TIMESTAMP=$(date +"%Y-%m-%d_%H%M")
REPORT_FILE="$INBOX/librarian_${TIMESTAMP}.json"

touch "$SEEN_FILE"

# Fetch latest 20 bookmarks
echo "Fetching bookmarks..."
# Use python -m json.tool to validate/format if needed, but let's just grab raw first
bird bookmarks -n 20 --json > "$REPORT_FILE"

if [ ! -s "$REPORT_FILE" ]; then
  echo "No bookmarks fetched."
  rm "$REPORT_FILE"
  exit 0
fi

# Audit Log
COUNT=$(grep -o '"id":' "$REPORT_FILE" | wc -l | tr -d ' ')
AUDIT_FILE="/Users/clawdrex/.openclaw/workspace/reports/usage_audit.csv"
echo "$(date),librarian,bird-cli,${COUNT}_items,X_API" >> "$AUDIT_FILE"

echo "Saved $COUNT bookmarks to $REPORT_FILE"
