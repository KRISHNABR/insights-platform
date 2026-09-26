# Walkthrough — run everything, step by step

Follow top to bottom. Each step says **what to run** and **what you should see**.

You will start the platform, check the console, check an existing dashboard, run an
existing job, then build one new app of each kind.

**Two forms of the same command:**

| | When |
|---|---|
| `insights ...` | `new-app` only — there is no project yet |
| `uv run insights ...` | everything else, from inside a repo — uses *your* pinned SDK |

---

## Step 0 — Prerequisites

```bash
python3 --version     # need 3.12+
uv --version          # curl -LsSf https://astral.sh/uv/install.sh | sh
```

No Docker. No cloud account. No credentials.

---

## Step 1 — Clone

```bash
mkdir ~/insights-hub && cd ~/insights-hub

for r in insights-platform insights-sdk insights-headcount-dashboard insights-comp-report; do
  git clone "https://github.com/KRISHNABR/$r.git"
done
```

**Directory names matter** — the local loop finds sibling repos by name.

---

## Step 2 — Start the platform

```bash
cd ~/insights-hub/insights-platform
uv run insights up
```

**You should see:**

```
seeded .../runtime/fakes/warehouse/warehouse.db
registered 3 app(s) -> apps.local.json
  headcount-dashboard on :8101
  console on :8102

edge on http://localhost:8080
  the console     http://localhost:8080/apps/console/?as=suraj@corp.example
  the dashboard   http://localhost:8080/apps/headcount-dashboard/?as=krishna@corp.example
  ...
ctrl-c to stop
```

**Leave this running. Open a second terminal for every step below.**

What just started: a fake warehouse, a fake internal REST API, one web server per app,
the console, and the edge (the front door) on `:8080`.

> **Ports:** the edge is `--port`, the stub is `+1`, apps start at `+21` and are
> assigned **alphabetically** — so they shift as you add apps. Always read them from
> this output rather than assuming.

> **If a port is busy:** `uv run insights up --port 9000`. It refuses up front and
> names what is holding the port.

---

> **On a corporate network:** the platform talks to itself over `127.0.0.1`, and a
> corporate proxy bypass list often contains `localhost` but **not** `127.0.0.1` — so
> the proxy is handed loopback traffic it correctly refuses to route, and every app
> reports "did not become healthy" while serving perfectly. The platform now bypasses
> the proxy for loopback itself. If you are on an older SDK, this unblocks it:
>
> ```bash
> export NO_PROXY=127.0.0.1,localhost,::1 no_proxy=127.0.0.1,localhost,::1
> ```

---

## Step 2b — Set the local secrets

On a fresh clone `up` will also print this:

```
  3 local secret(s) not set — these apps will fail to connect:
    comp-report: hr-warehouse-token
    headcount-dashboard: directory-api-token
  set them with (a fake value is fine locally):
    mkdir -p .../secret-store/comp-report && echo local-fake > .../comp-report/hr-warehouse-token
    ...
```

**Copy those `mkdir` lines and run them**, then Ctrl-C and `uv run insights up` again.

The fake secret store is gitignored — the platform does not commit credentials, even
obviously fake ones — so a fresh clone has none. This is also the first thing the
platform teaches you: **a secret is yours to set.** The platform creates the slot and
reports that it is empty; it never writes the value, locally or in production.

---

## Step 3 — The platform console

The platform team's own tool, hosted *on* the platform.

```
http://localhost:8080/apps/console/?as=suraj@corp.example
```

**You should see** a dark page, header `suraj@corp.example · MG-PLATFORM`, four tabs:

| Tab | Shows |
|---|---|
| **Apps** | every app, last seen, its connections, recent errors |
| **Connections** | queries, failures, failure kind, and whether it is likely ours or the team's |
| **Runs** | scheduled job history, from the scheduler's own state |
| **Telemetry** | raw records |

**Check:** it never shows a row of anybody's data — only counts and timings. It cannot
leak what the platform never collected.

**Check:** sign in as a tenant instead and you still get in:

```
http://localhost:8080/apps/console/?as=krishna@corp.example
```

A team should not have to ask the platform team to see their own app's health.

---

## Step 4 — The dashboard (an existing web app)

```
http://localhost:8080/apps/headcount-dashboard/?as=krishna@corp.example
```

**You should see** a headcount table. Now check it from the command line:

```bash
B=http://localhost:8080/apps/headcount-dashboard
J=/tmp/jar

# sign in once — ?as= stands in for the corporate SSO redirect
curl -s -c $J -o /dev/null "$B/api/me?as=krishna@corp.example"

# who does the app think you are?
curl -s -b $J "$B/api/me"
```
```json
{"subject":"krishna@corp.example","groups":["MG-PEOPLE-OPS","headcount-viewer"],"trusted":true}
```

```bash
# the warehouse connector
curl -s -b $J "$B/api/headcount?month=2026-09"
```
```json
{"month":"2026-09","departments":[{"dept":"Engineering","headcount":184}, ...]}
```

```bash
# the REST connector — same app, different engine
# (needs the secret from Step 2b)
curl -s -b $J "$B/api/team?dept=Engineering"
```
```json
{"dept":"Engineering","people":[{"email":"kishore@corp.example", ...}]}
```

### Check the auth actually holds

```bash
# 1. no identity
curl -s -o /dev/null -w "%{http_code}\n" "$B/api/headcount?month=2026-09"      # 401

# 2. forge your groups — you stay krishna
curl -s -b $J -H "X-Auth-Groups: admin,superuser" "$B/api/me"

# 3. someone not listed on the app
curl -s -c /tmp/j2 -o /dev/null "$B/api/me?as=lokesh@corp.example"
curl -s -b /tmp/j2 "$B/api/headcount?month=2026-09"                            # 403

# 4. bypass the edge entirely (use the app port from Step 2)
curl -s http://localhost:8101/api/me
```

**You should see:** `401` · your **real** groups, not the forged ones · `403` ·
`{"subject":"anonymous","groups":[],"trusted":false}`.

That last one is the design: outside the edge, every check returns no.

---

## Step 5 — The job (an existing scheduled app)

```bash
cd ~/insights-hub/insights-comp-report
uv run insights doctor
```
```
  ok    manifest app.yaml: comp-report (job, team people-analytics)
  ok    connection hr-warehouse (sqlite, secret 'hr-warehouse-token' present)
  ok    Dockerfile on python:3.12-slim, runs as app
  ok    sdk 0.2.0 (supported: 0.2.0, 0.1.0)

no problems
```

```bash
uv run insights run
```

**You should see** six events:

```
job_start · connection_opened · query_executed · output_written · report_complete · job_complete
```

Look at the query record:

```json
{"event":"query_executed","connection":"hr-warehouse","engine":"sqlite","ms":2,"rows":4}
```

Connection, engine, duration, row count. **Not the SQL, not a row.**

Your output: `~/insights-hub/insights-platform/runtime/outputs/comp-report/`

Now refresh the console's **Runs** and **Connections** tabs — your run is there.

---

## Step 6 — Build a new web app

Install the CLI globally. There is no project yet, so it cannot come from one:

```bash
uv tool install git+https://github.com/KRISHNABR/insights-sdk.git@v1
```

> If `insights` is not on your PATH afterwards, uv prints the directory to add. Or use
> `uvx --from git+https://github.com/KRISHNABR/insights-sdk.git@v1 insights ...` instead.

```bash
cd ~/insights-hub
insights new-app attrition-api --kind web --team people-analytics --owner MG-PEOPLE-ANALYTICS
cd insights-attrition-api
uv sync
uv run insights doctor        # green already
```

### 6a. Declare a connection

In `app.yaml`, replace `connections: []` with:

```yaml
connections:
  - name: hr-warehouse
    engine: databricks-sql
    host: ${HR_WAREHOUSE_HOST}
    http_path: ${HR_WAREHOUSE_HTTP_PATH}
    local:
      engine: sqlite
      path: ${INSIGHTS_WAREHOUSE_PATH}
```

and add groups under `access.manage` so there is something to test:

```yaml
    contributors: [MG-PEOPLE-ANALYTICS-ENG]
    readers:      [MG-FINANCE-BI]
```

```bash
uv run insights connections
```
```
  hr-warehouse
    engine    sqlite
    path      ${INSIGHTS_WAREHOUSE_PATH}   ->  /Users/you/insights-hub/.../warehouse.db
```

Same file, as production:

```bash
INSIGHTS_ENV=prod uv run insights connections
```
```
    engine    databricks-sql
    host      ${HR_WAREHOUSE_HOST}   ->  adb-9876543210.1.azuredatabricks.net
```

**One manifest, both environments.** The values come from
`insights-platform/control/registry/environments.yaml` — the tenant says *which*
variable, the platform says *what it is*.

### 6b. Write the handler

Replace `src/main.py`:

```python
from insights_sdk import connect, get_logger, require_role, web_app

app = web_app()
log = get_logger()


@app.get("/api/attrition")
def attrition(month: str = "2026-09"):
    require_role("reader")

    rows = connect("hr-warehouse").query(
        "SELECT dept, headcount FROM hr_headcount WHERE month = :month ORDER BY dept",
        month=month,
    )
    summary = [
        {"dept": r["dept"], "headcount": r["headcount"],
         "attrition_pct": round((r["headcount"] % 7) / max(r["headcount"], 1) * 100, 2)}
        for r in rows
    ]
    log.info("attrition_computed", month=month, departments=len(summary))
    return {"month": month, "departments": summary}
```

```bash
uv run insights doctor
```

### 6c. Host it

Go to the terminal running `up`, press **Ctrl-C**, and start it again — apps are
registered at startup:

```bash
cd ~/insights-hub/insights-platform && uv run insights up
```

**You should see** `attrition-api` in the list, with a new port. **Note the ports have
shifted** — `attrition-api` sorts first alphabetically.

```bash
E=http://localhost:8080
curl -s -c /tmp/v -o /dev/null "$E/apps/attrition-api/healthz?as=vidya@corp.example"
curl -s -b /tmp/v "$E/apps/attrition-api/api/attrition?month=2026-09"
```
```json
{"month":"2026-09","departments":[{"dept":"Engineering","headcount":184,"attrition_pct":1.09}, ...]}
```

**Check isolation** — krishna owns the *other* app:

```bash
curl -s -b $J "$E/apps/attrition-api/api/attrition"
```
```json
{"error":"krishna@corp.example is not a member of any group that may use 'attrition-api'", ...}
```

It also appears in the console's Apps tab.

---

## Step 7 — Build a new job

```bash
cd ~/insights-hub
insights new-app directory-sync --kind job --team people-ops --owner MG-PEOPLE-OPS
cd insights-directory-sync
uv sync
```

This one uses the **REST** engine and needs a **credential**.

`app.yaml` — replace `connections: []`:

```yaml
connections:
  - name: people-directory
    engine: rest
    base_url: ${INSIGHTS_DIRECTORY_URL}
    secret: directory-api-token
    timeout: 10
```

and add a schedule (jobs require one):

```yaml
job:
  schedule: "0 2 * * *"
  timezone: Europe/Dublin
  timeout: 30m
  retries: 2
  concurrency: forbid
  catchup: false
```

```bash
uv run insights connections
```
```
    secret    directory-api-token  ->  insights/directory-sync/directory-api-token  [MISSING]
              your team sets this. The platform cannot read it.
```

Create it. In production your group writes this into Secrets Manager; locally it is a
file at the same path:

```bash
mkdir -p ~/insights-hub/insights-platform/runtime/fakes/secret-store/directory-sync
echo "local-fake-directory-token" > \
  ~/insights-hub/insights-platform/runtime/fakes/secret-store/directory-sync/directory-api-token

uv run insights connections          # now [present]
uv run insights connections --probe  # actually opens it
```

`src/main.py`:

```python
from insights_sdk import connect, get_logger, output, run_job

log = get_logger()


def main() -> None:
    people = connect("people-directory").query("/people")   # a PATH, not SQL

    by_dept: dict[str, int] = {}
    for person in people:
        by_dept[person["dept"]] = by_dept.get(person["dept"], 0) + 1

    snapshot = [{"dept": d, "headcount": c} for d, c in sorted(by_dept.items())]
    output("nightly-headcount", snapshot)
    log.info("snapshot_complete", departments=len(snapshot), people=len(people))


if __name__ == "__main__":
    run_job(main)
```

```bash
uv run insights run
```

**You should see** six events again, with `"connection":"people-directory"`.

Output: `~/insights-hub/insights-platform/runtime/outputs/directory-sync/`

---

## Step 8 — Break things on purpose

**A credential in the manifest** — add `password: hunter2` to any connection:

```bash
uv run insights doctor
```
```
FAIL  manifest: connection 'people-directory' contains password. app.yaml is in git —
      a credential here is a credential in the history forever.
```

**A connection that cannot be reached:**

```bash
INSIGHTS_DIRECTORY_URL=http://127.0.0.1:1 uv run insights connections --probe
```
```
    probe     FAILED (network)
```

The message says **who fixes it** — `auth` and `not_found` are yours, `tls` and
`network` are usually the platform's.

**An app that will not boot** — break an import in `src/main.py`, restart `up`:

```bash
uv run insights logs --app attrition-api --startup
```

**A container that would run as root** — add `USER root` to the end of your
`Dockerfile`:

```bash
INSIGHTS_REGISTRY_DIR=../insights-platform/control/registry \
  uv run python ../insights-platform/control/cli/gates.py --app attrition-api --manifest app.yaml
```
```
::error::Dockerfile's last USER is root...
```

---

## When something goes wrong

| Symptom | Run this |
|---|---|
| "X did not become healthy" | `uv run insights logs --app X --startup` |
| App started, behaving oddly | `uv run insights logs --app X` |
| A query failing | `uv run insights connections --probe` |
| Is it registered? | `uv run insights status` |
| Anything else | the console, `/apps/console/` |

**`doctor` will not help with a startup failure** — it checks your manifest, and a
manifest can be perfect while the process fails to bind a port.

Stop a stuck stack:

```bash
lsof -ti tcp:8080 -ti tcp:8081 -ti tcp:8101 -ti tcp:8102 | xargs kill -9
```

---

## Where to go next

| | |
|---|---|
| Every `app.yaml` field | [APP-YAML.md](APP-YAML.md) |
| How it works and why | [ARCHITECTURE.md](ARCHITECTURE.md) |
| The decisions | [adr/](adr/) |
| Day two for your app | `RUNBOOK.md`, in your own repo |
