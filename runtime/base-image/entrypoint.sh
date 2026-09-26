#!/usr/bin/env bash
# One entrypoint for both archetypes. `kind` in app.yaml decides which path runs, so a
# team never writes a start command and the two archetypes cannot drift apart.
set -euo pipefail

KIND=$(python -c "from insights_sdk import config; print(config.manifest().kind)")

case "$KIND" in
  web) exec python -m uvicorn main:app --host 0.0.0.0 --port 8000 --app-dir /app/src ;;
  job) exec python /app/src/main.py ;;
  *)   echo "unknown kind: $KIND" >&2; exit 2 ;;
esac
