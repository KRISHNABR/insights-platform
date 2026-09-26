#!/usr/bin/env bash
# Shared by every base image.
#
# One entrypoint for both archetypes: `kind` in app.yaml decides which path runs.
# A team never writes a start command, and the two archetypes cannot drift apart
# because there is only one file that starts anything.
set -euo pipefail

KIND=$(python -c "from insights_sdk import config; print(config.manifest().kind)")

case "$KIND" in
  web)
    # api and spa both run the same ASGI app; they differ only in what the tenant
    # mounted on it. There is deliberately no other web shape - see ADR-005.
    exec python -m uvicorn main:app \
      --host 0.0.0.0 --port 8000 --app-dir /app/src \
      --no-access-log        # the SDK emits structured access logs itself
    ;;
  job)
    # Runs to completion. The SDK's run_job() owns the exit-code contract:
    #   0 = success   1 = the job broke   2 = the platform refused it
    exec python /app/src/main.py
    ;;
  *)
    echo "unknown kind: ${KIND}" >&2
    exit 2
    ;;
esac
