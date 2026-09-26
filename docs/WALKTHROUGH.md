# Walkthrough — build two apps from scratch and run everything

A step-by-step you can follow start to finish. Every command here was run exactly as
written. Roughly 30 minutes.

By the end you will have: the platform running locally, the console, two example apps
you built yourself (one web, one scheduled job), both talking to real connections, and
you will have watched the auth, the secrets, the logs and the failure modes.

**Two commands you will type a lot, and the difference:**

| | When | Why |
|---|---|---|
| `insights ...` | `new-app` only | There is no project yet — it must come from a global install |
| `uv run insights ...` | everything else, inside a repo | Uses **your** pinned SDK, so `doctor` cannot disagree with your app |

They are the same program.

---

## 0 · Prerequisites

```bash
python3 --version     # need 3.12+
uv --version          # https://docs.astral.sh/uv/  — curl -LsSf https://astral.sh/uv/install.sh | sh
```

No Docker. No cloud account. No credentials.

---

## 1 · Get the platform running (5 min)

```bash
mkdir ~/insights-hub && cd ~/insights-hub

for r in insights-platform insights-sdk insights-headcount-dashboard insights-comp-report; do
  git clone "https://github.com/KRISHNABR/$r.git"
done

cd insights-platform
uv run insights up
```

**Directory names matter** — the local loop finds the sibling repos by name.

You should see:

```
registered 3 app(s) -> apps.local.json
  headcount-dashboard on :8101
  console on :8102

edge on http://localhost:8080
  the console     http://localhost:8080/a/console/?as=suraj@corp.example
  the dashboard   http://localhost:8080/a/headcount-dashboard/?as=krishna@corp.example
  ...
logs     uv run insights logs --app headcount-dashboard --startup
```

> Port 8080 busy? `uv run insights up --port 9000` and add 920 to the app ports.

**✅ Check:** open the console URL. Four tabs: Apps, Connections, Runs, Telemetry.
The header shows `suraj@corp.example · MG-PLATFORM` — that came from the edge, not
from the console.

Leave this running. **Open a second terminal for everything below.**

---

## 2 · Prove the auth before you trust it (5 min)

All of these are against the running stack. Second terminal, from `~/insights-hub`.

```bash
B=http://localhost:8080/a/headcount-dashboard
```

**a. No identity → refused**

```bash
curl -s -o /dev/null -w "%{http_code}\n" "$B/api/headcount?month=2026-09"
```
```
401
```

**b. Sign in — the `?as=` stub stands in for the IdP redirect**

```bash
curl -s -c /tmp/jar -o /dev/null "$B/api/me?as=krishna@corp.example"
curl -s -b /tmp/jar "$B/api/me"
```
```json
{"subject":"krishna@corp.example","groups":["MG-PEOPLE-OPS","headcount-viewer"],"trusted":true}
```

The app **never authenticated anybody**. It read headers the edge injected.

**c. Forge the headers → the forgery is discarded**

```bash
curl -s -b /tmp/jar -H "X-Auth-Groups: admin,superuser" "$B/api/me"
```
```json
{"subject":"krishna@corp.example","groups":["MG-PEOPLE-OPS","headcount-viewer"],"trusted":true}
```

Your real groups, not the ones you sent. The edge strips every `X-Auth-*` before
injecting its own.

**d. Someone outside the app → refused before any app code runs**

```bash
curl -s -c /tmp/jar2 -o /dev/null "$B/api/me?as=lokesh@corp.example"
curl -s -b /tmp/jar2 "$B/api/headcount?month=2026-09"
```
```json
{"error":"lokesh@corp.example is not a member of any group that may use 'headcount-dashboard'", ...}
```

**e. Bypass the edge entirely**

```bash
curl -s http://localhost:8101/api/me
```
```json
{"subject":"anonymous","groups":[],"trusted":false}
```

Running outside the edge is not "an app with no user" — it is an app where every check
returns no. Try to read data that way and `connect()` raises `IdentityError`.

---

## 3 · Build a web app from scratch (10 min)

Install the CLI globally — there is no project yet, so it cannot come from one:

```bash
uv tool install git+https://github.com/KRISHNABR/insights-sdk.git@v1
```

> If `insights` is not on your PATH afterwards, uv prints the directory to add. Or skip
> the install and prefix with
> `uvx --from git+https://github.com/KRISHNABR/insights-sdk.git@v1` instead.

```bash
cd ~/insights-hub
insights new-app attrition-api --kind web --team people-analytics --owner MG-PEOPLE-ANALYTICS
cd insights-attrition-api
```

**✅ Check:** ten files — `app.yaml`, `Dockerfile`, `pyproject.toml`, `src/main.py`,
`README.md`, `RUNBOOK.md`, `.gitignore`, and four workflows. You will edit two.

```bash
uv sync
uv run insights doctor
```
```
  ok    manifest app.yaml: attrition-api (web, team people-analytics)
  ok    Dockerfile on python:3.12-slim, runs as app
  ok    sdk 0.2.0 (supported: 0.2.0, 0.1.0)

no problems
```

### 3a. Declare a connection

Open `app.yaml` and replace `connections: []` with:

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

Also add contributors and readers under `access.manage` so there is something to test:

```yaml
    contributors: [MG-PEOPLE-ANALYTICS-ENG]
    readers:      [MG-FINANCE-BI]
```

**✅ Check — this is the `${VAR}` question, answered:**

```bash
uv run insights connections
```
```
  hr-warehouse
    engine    sqlite
    path      ${INSIGHTS_WAREHOUSE_PATH}   ->  /Users/you/insights-hub/insights-platform/runtime/fakes/warehouse/warehouse.db
```

Now the same file, as production:

```bash
INSIGHTS_ENV=prod uv run insights connections
```
```
  hr-warehouse
    engine    databricks-sql
    host      ${HR_WAREHOUSE_HOST}   ->  adb-9876543210.1.azuredatabricks.net
    http_path ${HR_WAREHOUSE_HTTP_PATH}   ->  /sql/1.0/warehouses/prd00warehouse
```

One manifest, two environments, no environment handling in your code. **§7 below
explains where those values come from.**

### 3b. Write the handler

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

**✅ Check:** `ok connection hr-warehouse (sqlite)`.

### 3c. Run it

Go to the terminal running `insights up`, press **Ctrl-C**, and start it again — it
picks up new apps at startup:

```bash
cd ~/insights-hub/insights-platform && uv run insights up
```

**✅ Check:** `attrition-api on :81xx` in the output, and it appears in the console's
Apps tab.

```bash
curl -s -c /tmp/v -o /dev/null "http://localhost:8080/a/attrition-api/api/me?as=vidya@corp.example"
curl -s -b /tmp/v "http://localhost:8080/a/attrition-api/api/attrition?month=2026-09"
```
```json
{"month":"2026-09","departments":[{"dept":"Engineering","headcount":184,"attrition_pct":1.09}, ...]}
```

**✅ Check isolation** — krishna owns the *other* app, not this one:

```bash
curl -s -c /tmp/k -o /dev/null "http://localhost:8080/a/attrition-api/api/me?as=krishna@corp.example"
curl -s -b /tmp/k "http://localhost:8080/a/attrition-api/api/attrition"
```
```json
{"error":"krishna@corp.example is not a member of any group that may use 'attrition-api'", ...}
```

---

## 4 · Build a scheduled job from scratch (8 min)

```bash
cd ~/insights-hub
insights new-app directory-sync --kind job --team people-ops --owner MG-PEOPLE-OPS
cd insights-directory-sync
uv sync
```

This one uses a **different engine** — a REST API — and needs a **credential**.

`app.yaml`, replacing `connections: []`:

```yaml
connections:
  - name: people-directory
    engine: rest
    base_url: ${INSIGHTS_DIRECTORY_URL}
    secret: directory-api-token
    timeout: 10
```

And add a schedule (jobs require one):

```yaml
job:
  schedule: "0 2 * * *"
  timezone: Europe/Dublin
  timeout: 30m
  retries: 2
  concurrency: forbid
  catchup: false
```

**✅ Check the secret is missing, and that the message tells you whose job it is:**

```bash
uv run insights connections
```
```
    secret    directory-api-token  ->  insights/directory-sync/directory-api-token  [MISSING]
              your team sets this. The platform cannot read it.
```

Create it. In production your group writes this into Secrets Manager; locally it is a
file with the same path shape:

```bash
mkdir -p ~/insights-hub/insights-platform/runtime/fakes/secret-store/directory-sync
echo "local-fake-directory-token" > \
  ~/insights-hub/insights-platform/runtime/fakes/secret-store/directory-sync/directory-api-token

uv run insights connections
```
```
    secret    directory-api-token  ->  insights/directory-sync/directory-api-token  [present]
```

`src/main.py`:

```python
from insights_sdk import connect, get_logger, output, run_job

log = get_logger()


def main() -> None:
    directory = connect("people-directory")
    people = directory.query("/people")          # a PATH, not SQL — same contract

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

**✅ Check** — six records, and note what they contain:

```
job_start · connection_opened · query_executed · output_written · snapshot_complete · job_complete
```

```json
{"event":"query_executed","connection":"people-directory","engine":"rest","ms":12,"rows":4}
```

Connection, engine, duration, row count. **Not the path, not a row.** The platform
never sees your data.

Your CSV: `~/insights-hub/insights-platform/runtime/outputs/directory-sync/`

---

## 5 · Break things on purpose (5 min)

The failure modes are the interesting part.

**a. A credential in the manifest** — add `password: hunter2` to any connection:

```bash
uv run insights doctor
```
```
FAIL  manifest: connection 'people-directory' contains password. app.yaml is in git —
      a credential here is a credential in the history forever.
```

Remove it.

**b. A connection that cannot be reached** — point `base_url` at something dead:

```bash
uv run insights connections --probe
```
```
    probe     FAILED (network)
              connection 'people-directory' (rest): could not reach the host.
```

The message says **who fixes it**: `auth` and `not_found` are yours, `tls` and
`network` are usually the platform's.

**c. An app that will not boot** — break an import in `src/main.py`, restart `up`:

```bash
uv run insights logs --app attrition-api --startup
```
```
ModuleNotFoundError: No module named 'insights_sdk_typo'
```

That is why startup logs are separate from telemetry: an app that dies on import emits
**no** telemetry, so the structured view would read as "no traffic" rather than
"crashed".

**d. A container that would run as root** — add `USER root` at the end of your
`Dockerfile`, then run the deploy gate:

```bash
cd ~/insights-hub/insights-attrition-api
INSIGHTS_REGISTRY_DIR=../insights-platform/control/registry \
  uv run python ../insights-platform/control/cli/gates.py --app attrition-api --manifest app.yaml
```
```
::error::Dockerfile's last USER is root...
platform gates: 1 failure(s)
```

---

## 6 · The console (3 min)

```
http://localhost:8080/a/console/?as=suraj@corp.example
```

| Tab | What to look for |
|---|---|
| **Apps** | all four apps, last seen, declared connections, recent warn/error |
| **Connections** | queries, failures, failure **kind**, and `likely_owner` — platform or tenant |
| **Runs** | your `directory-sync` run, from the scheduler's own state |
| **Telemetry** | raw records — every one has an app and a caller, none has a payload |

**Two things worth noticing.**

It is a **tenant of the platform**, not a privileged tool — it registers like any app,
sits behind the edge, and gets the same session cookie and group check. If the edge
breaks, the tool you would use to diagnose it breaks the same way.

It shows **telemetry, never rows**. It cannot leak what the platform never collected.
That is what stops a fleet-wide console becoming the largest data-exfiltration surface
here, and it is why it needs no access model of its own.

**✅ Check:** sign in as a tenant instead — `?as=krishna@corp.example` — and you still
get in. A team should not have to ask the platform team to see their own app's health.

---

## 7 · How `${HR_WAREHOUSE_HOST}` is actually passed

The question this file exists to answer properly.

**A tenant says which variable they need. The platform says what it is.**

```yaml
# YOUR app.yaml — in your repo, in git
host: ${HR_WAREHOUSE_HOST}
```

```yaml
# insights-platform/control/registry/environments.yaml — platform-owned
dev:
  HR_WAREHOUSE_HOST: "adb-1234567890.7.azuredatabricks.net"
prod:
  HR_WAREHOUSE_HOST: "adb-9876543210.1.azuredatabricks.net"
```

| | Local | Production |
|---|---|---|
| Who reads that file | `insights up` / `insights run` | the deploy pipeline |
| How it reaches the process | exported before your app starts | rendered into the task definition / pod spec |
| When it is substituted | `connect()` | `connect()` |

Substitution happens when the connection is **opened**, not when the manifest is read —
which is why `insights doctor`, the deploy gate and the console can all read your
manifest without being the environment your app runs in. An unset variable fails at
`connect()` with `kind=config_missing`, naming the variable.

See it both ways:

```bash
uv run insights connections                  # local
INSIGHTS_ENV=prod uv run insights connections   # production
```

**Credentials never travel this way.** A `${VAR}` becomes an environment variable,
readable by anything that can see the process. Credentials go through `secret:`,
are fetched from the secret store at the point of use, and are never held in a
variable — see §4.

> **Honest scope:** the local half is fully implemented and you just ran it. The
> production half — the deploy step rendering this into a task definition — is an
> interface stub in this submission, like the rest of the AWS deployment. The
> mechanism and the file are real; the thing that would apply them in AWS is not.

---

## 8 · Ship a platform change and take it (5 min)

The upgrade story, end to end.

```bash
cd ~/insights-hub/insights-comp-report
uv run insights doctor | grep sdk          # what you are on
```

A new SDK release does **not** reach you automatically — `uv.lock` pins the exact
version, so nothing changes under a running app. You take it:

```bash
uv lock --upgrade-package insights-sdk
uv sync
uv run insights doctor
uv run insights run
git diff --stat                            # only uv.lock changed
```

Generated files are a separate, reviewable upgrade:

```bash
uv run insights upgrade-scaffold --check   # are my pipelines and RUNBOOK current?
uv run insights upgrade-scaffold           # update them
git diff                                   # review before committing
```

**✅ Check the guardrails.** In `pyproject.toml`, change the dependency to
`insights-sdk==0.2.0` and run the deploy gate (§5d) — it refuses a pin. Try
`>=9.9,<10` — it refuses a version outside the N-2 support window.

---

## What you have now

- Four apps: two you cloned, two you built
- Both web shapes (`api`, `spa`), both kinds (`web`, `job`), three engines
- Auth proven from four angles including two that must fail
- A credential you created that the platform team cannot read
- Startup logs, telemetry, a console, a deploy gate that refuses four things

## Where to go next

| | |
|---|---|
| Why it is built this way | [ARCHITECTURE.md](ARCHITECTURE.md) |
| Every `app.yaml` field | [APP-YAML.md](APP-YAML.md) |
| The decisions and their alternatives | [adr/](adr/) |
| Day two for your app | `RUNBOOK.md`, in your own repo |
