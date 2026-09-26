# Base image: python-web
#
# For web.type: api and spa. Carries the web server; an `spa` app's own frontend is
# copied in by the rendered Dockerfile. The platform serves a bundle; it never builds one.
FROM python:3.12-slim AS base

RUN useradd --create-home --uid 10001 insights
WORKDIR /app

# uv, because tenants manage their projects with it and the image should resolve
# dependencies the same way their laptop does.
COPY --from=ghcr.io/astral-sh/uv:0.5.11 /uv /usr/local/bin/uv

# Pinned deliberately. The base image is where the platform takes responsibility
# for the version, so it may not float - and CI rejects an app whose FROM is :latest.
RUN uv pip install --system --no-cache \
      "insights-sdk==0.1.0" \
      "uvicorn[standard]==0.34.0"

ENV PYTHONUNBUFFERED=1 PYTHONDONTWRITEBYTECODE=1

COPY entrypoint.sh /usr/local/bin/entrypoint.sh
RUN chmod +x /usr/local/bin/entrypoint.sh

USER insights
EXPOSE 8000

HEALTHCHECK --interval=30s --timeout=3s --start-period=5s \
  CMD python -c "import urllib.request,sys; sys.exit(0 if urllib.request.urlopen('http://127.0.0.1:8000/healthz').status==200 else 1)"

ENTRYPOINT ["/usr/local/bin/entrypoint.sh"]
