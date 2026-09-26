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
    # web.type decides what actually serves HTTP. The tenant never picks a
    # command; they declared a shape and this resolves it.
    TYPE=$(python -c "from insights_sdk import config; print(config.manifest().web_type)")
    case "$TYPE" in
      streamlit)
        # Health sidecar first - it resolves every declared dataset, which
        # Streamlit's own /_stcore/health does not.
        python -m insights_sdk.runtime.health_sidecar --port 8001 &
        exec streamlit run /app/src/app.py \
          --server.port 8000 --server.address 0.0.0.0
        ;;
      *)
        # dashboard | api | spa all run the same ASGI app; they differ only in
        # what the tenant mounted on it.
        exec python -m uvicorn main:app \
          --host 0.0.0.0 --port 8000 --app-dir /app/src \
          --no-access-log        # the SDK emits structured access logs itself
        ;;
    esac
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
