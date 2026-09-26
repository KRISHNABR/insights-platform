# Base image: python-min
#
# The SDK and nothing else. For small jobs where cold-start time matters more
# than convenience - roughly a third the size of python-data.
FROM python:3.12-slim AS base

RUN useradd --create-home --uid 10001 insights
WORKDIR /app

COPY --from=ghcr.io/astral-sh/uv:0.5.11 /uv /usr/local/bin/uv
RUN uv pip install --system --no-cache "insights-sdk==0.1.0"

ENV PYTHONUNBUFFERED=1 PYTHONDONTWRITEBYTECODE=1

COPY entrypoint.sh /usr/local/bin/entrypoint.sh
RUN chmod +x /usr/local/bin/entrypoint.sh

USER insights
ENTRYPOINT ["/usr/local/bin/entrypoint.sh"]
