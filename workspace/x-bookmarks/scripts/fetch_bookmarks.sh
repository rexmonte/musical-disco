#!/usr/bin/env bash
# Fetch X bookmarks via bird CLI and output JSON
# Usage: fetch_bookmarks.sh [count] [--all] [--since-id <id>] [extra bird flags...]
#
# Examples:
#   ./fetch_bookmarks.sh 20
#   ./fetch_bookmarks.sh --all --max-pages 5
#   ./fetch_bookmarks.sh 50 --chrome-profile "Default"
#
# Environment:
#   AUTH_TOKEN, CT0 — manual auth (or use --chrome-profile flag)
#     NOTE: Credentials are passed via BIRD_AUTH_TOKEN/BIRD_CT0 env vars
#     to avoid exposing them in process listings (ps aux).
#   BOOKMARKS_STATE — path to state file for tracking last-seen ID

set -euo pipefail

COUNT="${1:-20}"
shift 2>/dev/null || true

# Build bird command
CMD=(bird bookmarks --json)

# If count is a number, add -n flag; otherwise treat as extra flag
if [[ "$COUNT" =~ ^[0-9]+$ ]]; then
  CMD+=(-n "$COUNT")
else
  CMD+=("$COUNT")
fi

# Pass auth via environment variables instead of CLI args to avoid
# exposing credentials in process listings (visible via `ps aux`).
if [[ -n "${AUTH_TOKEN:-}" ]] && [[ -n "${CT0:-}" ]]; then
  export BIRD_AUTH_TOKEN="$AUTH_TOKEN"
  export BIRD_CT0="$CT0"
fi

# Pass through any extra flags
CMD+=("$@")

# Run and output
exec "${CMD[@]}"
