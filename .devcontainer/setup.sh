#!/usr/bin/env bash
# Clone the sibling repositories so the local dev loop can find them.
set -euo pipefail

OWNER="${GITHUB_REPOSITORY_OWNER:-KRISHNABR}"
WORKSPACE="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
cd "$WORKSPACE"

for repo in insights-sdk insights-headcount-dashboard insights-comp-report; do
  [ -d "$repo" ] || git clone --depth 1 "https://github.com/$OWNER/$repo.git"
done

cat <<'MSG'

  Insights Hub is ready.

    cd insights-platform && uv run insights up

  Then open the forwarded port 8080 and append ?as=krishna@corp.example to any app URL.
  That is the whole local login.

MSG
