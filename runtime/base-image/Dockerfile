# The platform base image. Every tenant app is three lines on top of this.
#
# What lives here instead of in 25 repos:
#   * the Python runtime and its patch level
#   * the SDK, so the runtime version and the library version are one decision
#   * a non-root user, because 25 teams will not each remember
#   * the entrypoint, so `kind: web` and `kind: job` start the same way everywhere
#   * the health/liveness contract
#
# A CVE in any of these is one rebuild here plus a redeploy, rather than a pull request
# against 25 repositories and a month of chasing. That property is most of the argument
# for a paved road (ADR-001).
FROM python:3.12-slim

RUN useradd --create-home --uid 10001 insights
WORKDIR /app

# Pinned deliberately. The base image is where the platform takes responsibility for the
# version, so it may not float - and CI rejects an app whose FROM is :latest.
RUN pip install --no-cache-dir "insights-sdk==0.1.0"

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    INSIGHTS_ENV=prod

COPY entrypoint.sh /usr/local/bin/entrypoint.sh
RUN chmod +x /usr/local/bin/entrypoint.sh

USER insights
EXPOSE 8000

# The health contract lives here, not in tenant code: the SDK's /healthz resolves every
# declared dataset and checks its credential was injected, so a deploy that would fail on
# first use fails at the probe instead.
HEALTHCHECK --interval=30s --timeout=3s --start-period=5s \
  CMD python -c "import urllib.request,sys; sys.exit(0 if urllib.request.urlopen('http://127.0.0.1:8000/healthz').status==200 else 1)"

ENTRYPOINT ["/usr/local/bin/entrypoint.sh"]
