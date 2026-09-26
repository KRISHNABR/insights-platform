# Base image: python-data
#
# For kind: job. Data libraries, no web server - a job that cannot serve traffic
# cannot quietly become an unmonitored API.
FROM python:3.12-slim AS base

RUN useradd --create-home --uid 10001 insights
WORKDIR /app

COPY --from=ghcr.io/astral-sh/uv:0.5.11 /uv /usr/local/bin/uv

# Pinned deliberately. The base image is where the platform takes responsibility
# for the version, so it may not float - and CI rejects an app whose FROM is :latest.
RUN uv pip install --system --no-cache \
      "insights-sdk==0.1.0" \
      "pandas==2.2.3" \
      "pyarrow==18.1.0"

ENV PYTHONUNBUFFERED=1 PYTHONDONTWRITEBYTECODE=1

COPY entrypoint.sh /usr/local/bin/entrypoint.sh
RUN chmod +x /usr/local/bin/entrypoint.sh

USER insights
ENTRYPOINT ["/usr/local/bin/entrypoint.sh"]
