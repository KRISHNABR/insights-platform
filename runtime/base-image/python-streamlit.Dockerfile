# Base image: python-streamlit
#
# For web.type: streamlit. Streamlit runs its own server and has no middleware, so
# this image carries two things the other web images do not need:
#
#   1. an identity shim - the SDK reads the edge's headers from st.context.headers
#      and builds the same Caller every other shape gets, so require_role() is
#      unchanged
#   2. a health sidecar - Streamlit's own /_stcore/health only proves the process
#      is alive. Ours resolves every declared dataset and checks its credential
#      arrived, which is the contract every app on this platform owes
#
# A data scientist writes app.py and gets the same entitlement, masking and audit
# guarantees as a FastAPI app, because those live in the SDK rather than in the
# web framework.
FROM python:3.12-slim AS base

RUN useradd --create-home --uid 10001 insights
WORKDIR /app

COPY --from=ghcr.io/astral-sh/uv:0.5.11 /uv /usr/local/bin/uv

RUN uv pip install --system --no-cache \
      "insights-sdk[streamlit]==0.1.0" \
      "streamlit==1.41.1" \
      "pandas==2.2.3"

ENV PYTHONUNBUFFERED=1 PYTHONDONTWRITEBYTECODE=1 \
    STREAMLIT_SERVER_HEADLESS=true \
    STREAMLIT_BROWSER_GATHER_USAGE_STATS=false \
    STREAMLIT_SERVER_ENABLE_XSRF_PROTECTION=true \
    STREAMLIT_SERVER_ENABLE_CORS=false

COPY entrypoint.sh /usr/local/bin/entrypoint.sh
RUN chmod +x /usr/local/bin/entrypoint.sh

USER insights
EXPOSE 8000 8001

# The sidecar serves /healthz on 8001; the platform probes that, not Streamlit's.
HEALTHCHECK --interval=30s --timeout=3s --start-period=10s \
  CMD python -c "import urllib.request,sys; sys.exit(0 if urllib.request.urlopen('http://127.0.0.1:8001/healthz').status==200 else 1)"

ENTRYPOINT ["/usr/local/bin/entrypoint.sh"]
