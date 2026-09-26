# Walkthrough — run everything, step by step

Follow top to bottom. Each step says **what to run** and **what you should see**.

The platform and the apps are **independent**. You start the platform once, in its own
terminal. Each app then runs in its own repo, in its own terminal, and can be started
and stopped without touching anything else.

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

---

## Step 2 — Start the platform · terminal 1

```bash
cd ~/insights-hub/insights-platform
uv run insights up
```

**You should see:**

```
THE PLATFORM IS UP

  edge      http://localhost:8080
  console   http://localhost:8080/apps/console/?as=suraj@corp.example

No tenant apps are running yet - that is deliberate, they are independent.
To run one, open another terminal, go to its repo and:

    uv run insights serve        (a web app)
    uv run insights run          (a scheduled job)

ctrl-c to stop the platform
```

That started the edge (the front door), the console, and two local stubs standing in
for a warehouse and an internal REST API. **No tenant apps** — that is the point.

**Leave this running.**

> **Port busy?** `uv run insights up --port 9000`. It refuses up front and names what
> is holding the port.

> **On a corporate network:** if an app later fails to connect, your proxy is probably
> intercepting `127.0.0.1`. The platform bypasses the proxy for loopback itself; on an
> older SDK, `export NO_PROXY=127.0.0.1,localhost,::1`.

---

## Step 3 — Open the portal

```
http://localhost:8080/apps/console/?as=suraj@corp.example
```

`?as=` is the local stand-in for corporate SSO. You type it **once** — after that a
session cookie carries you.

**You should see** a greeting and a sidebar: Home · Connections · Runs · Telemetry.
No app cards yet, because nothing is running.

Sign in as someone else and watch the page change:

```
http://localhost:8080/apps/console/?as=krishna@corp.example
```

---

## Step 4 — Run a web app · terminal 2

```bash
cd ~/insights-hub/insights-headcount-dashboard
cp .env.example .env          # your local secrets. gitignored.
uv run insights serve
```

**You should see:**

```
headcount-dashboard on :8101

  open    http://localhost:8080/apps/headcount-dashboard/?as=krishna@corp.example
          (anyone in MG-FINANCE-BI, MG-PEOPLE-OPS, MG-PEOPLE-OPS-ENG)
  logs    appear below. ctrl-c to stop and deregister.
```

Open that URL. Then **refresh the console** — the app is there as a card, with no
restart. The edge re-reads its registry on every request.

> **If it warns a secret is not set**, open `.env` and fill the value in. Any string
> works locally. See Step 7 for what that file is.

Check it from the command line too:

```bash
B=http://localhost:8080/apps/headcount-dashboard
J=/tmp/jar

curl -s -c $J -o /dev/null "$B/api/me?as=krishna@corp.example"   # sign in once
curl -s -b $J "$B/api/me"
curl -s -b $J "$B/api/headcount?month=2026-09"                    # warehouse
curl -s -b $J "$B/api/team?dept=Engineering"                      # REST API
```

Press **Ctrl-C** in terminal 2, refresh the console — the card is gone. Start it
again and it is back.

---

## Step 5 — Run a job · terminal 3

```bash
cd ~/insights-hub/insights-comp-report
cp .env.example .env
uv run insights doctor
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

Connection, engine, duration, row count. **Not the SQL, not a row.** The platform
never sees your data.

Output lands in `~/insights-hub/insights-platform/runtime/outputs/comp-report/`.

Now open the console → **Runs** and **Connections**. Your run is there.

---

## Step 6 — Run the job from the portal

In the console, click the **comp-report** card, then **Run now**.

- As `vidya@corp.example` (an owner) it runs, and you see every step.
- As `krishna@corp.example` the button is **disabled** — he is a reader on that app,
  and running a job is an action, not a view.

That button is the console's only write endpoint, authorized exactly like everything
else: the edge says who you are, the app's `access.manage` says whether you may.

The same view has tabs for **Connections**, **app.yaml** and **Telemetry**.

---

## Step 7 — How auth and secrets work

Three things happen, in this order. That is the whole model.

```
1. WHO ARE YOU?          the edge      ?as= locally · corporate SSO in production
                                        → sets a session cookie

2. MAY YOU USE THIS APP? the edge      are you in a group listed in the app's
                                        access.manage? → 403 before any of your
                                        code runs

3. MAY YOU DO THIS?      your code     require_role("reader")
```

**Your app never authenticates anybody.** By the time your code runs, the edge has
established who the caller is and put it in headers your app trusts. `current_user()`
just reads them.

### Where users and groups live

```
insights-platform/runtime/edge/users.yaml
```

That file is the entire stub IdP. To add a person:

```yaml
  priya@corp.example:
    name: Priya Raman
    groups: [MG-PEOPLE-OPS]
```

Restart the platform, then `?as=priya@corp.example`. In production this file does not
exist — the edge learns the same facts from corporate SSO, and **nothing downstream
changes**, because everything downstream consumes the edge's assertion, not the IdP.

### Who may use an app

The app's own `app.yaml`, and there are exactly three tiers:

```yaml
access:
  manage:
    owners:       [MG-PEOPLE-OPS]       # approve prod · change access
    contributors: [MG-PEOPLE-OPS-ENG]   # deploy dev/uat · read logs
    readers:      [MG-FINANCE-BI]       # use the app, see its telemetry
```

They **nest** — an owner passes `require_role("reader")` without being listed as one.

### Where secrets live

**Locally: `.env`, in the app's own repo.** Your credential, your repo, next to the
code that uses it.

```bash
cp .env.example .env
# hr-warehouse-token=any-local-value
```

`.env` is gitignored, and CI **refuses a committed one** — a credential in git is a
credential in the history forever, and removing it in the next commit is not a
remediation.

**In dev and prod `.env` is not read at all.** The SDK refuses it outside local, so a
stray `.env` in an image cannot quietly become the source of a production credential.
There, the platform injects each value from:

```
insights/<app>/<secret-name>
```

| | |
|---|---|
| writes the value | **your group** |
| reads the value | `sp-<app>` — your app's identity, on its own prefix |
| **cannot** read it | the platform team, by an explicit IAM `Deny` |
| sees every read | CloudTrail, including ours |

`app.yaml` only ever holds the **name**. The manifest loader refuses `password`,
`token`, `api_key` and friends outright.

### See it hold

```bash
B=http://localhost:8080/apps/headcount-dashboard

# 1. no identity
curl -s -o /dev/null -w "%{http_code}\n" "$B/api/headcount?month=2026-09"      # 401

# 2. forge your groups — you stay yourself
curl -s -b /tmp/jar -H "X-Auth-Groups: admin,superuser" "$B/api/me"

# 3. a user in no group of this app
curl -s -c /tmp/j2 -o /dev/null "$B/api/me?as=lokesh@corp.example"
curl -s -b /tmp/j2 "$B/api/headcount?month=2026-09"                            # 403

# 4. bypass the edge entirely (app port from Step 4)
curl -s http://localhost:8101/api/me
```

**You should see:** `401` · your **real** groups, not the forged ones · `403` ·
`{"subject":"anonymous","groups":[],"trusted":false}`.

That last one is the design: outside the edge every check returns no — including
`connect()`, which refuses to open a connection on behalf of nobody.

---

## Step 8 — Build a new app · terminal 4

Install the CLI once, globally — there is no project yet, so it cannot come from one:

```bash
uv tool install git+https://github.com/KRISHNABR/insights-sdk.git@v1
```

> If `insights` is not on your PATH, uv prints the directory to add. Or skip the
> install and prefix with
> `uvx --from git+https://github.com/KRISHNABR/insights-sdk.git@v1`.

```bash
cd ~/insights-hub
insights new-app attrition-api --kind web --team people-analytics --owner MG-PEOPLE-ANALYTICS
cd insights-attrition-api
uv sync
uv run insights doctor            # green already
uv run insights serve             # and it already has a UI
```

**You should see** a working page. A generated web app ships `static/index.html` that
calls its own API — no build step, no bundler, and no auth code in it.

### Give it a connection

In `app.yaml`, replace `connections: []`:

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

```bash
uv run insights connections
```
```
  hr-warehouse
    engine    sqlite
    path      ${INSIGHTS_WAREHOUSE_PATH}   ->  /Users/you/insights-hub/.../warehouse.db
```

The same file, as production:

```bash
INSIGHTS_ENV=prod uv run insights connections
```
```
    engine    databricks-sql
    host      ${HR_WAREHOUSE_HOST}   ->  adb-9876543210.1.azuredatabricks.net
```

**One manifest, both environments.** Those values come from
`insights-platform/control/registry/environments.yaml` — you say *which* variable, the
platform says *what it is*.

### Use it

In `src/main.py`, replace the body of `/api/hello`:

```python
@app.get("/api/hello")
def hello() -> list[dict]:
    require_role("reader")
    return connect("hr-warehouse").query(
        "SELECT dept, headcount FROM hr_headcount WHERE month = '2026-09'"
    )
```

Restart `serve` (Ctrl-C, up-arrow, Enter) and refresh. The table is your data.

---

## Step 9 — Break things on purpose

**A credential in the manifest** — add `password: hunter2` to any connection:

```bash
uv run insights doctor
```
```
FAIL  manifest: connection '...' contains password. app.yaml is in git —
      a credential here is a credential in the history forever.
```

**A connection that cannot be reached:**

```bash
uv run insights connections --probe
```

It does a real round trip — `SELECT 1`, or a request to `base_url`. The error says
**who fixes it**: `auth` and `not_found` are yours, `tls` and `network` are usually
the platform's.

**An app that will not boot** — break an import, then:

```bash
uv run insights logs --app attrition-api --startup
```

`doctor` will not help here: it checks your manifest, and a manifest can be perfect
while the process fails to start.

---

## When something goes wrong

| Symptom | Run this |
|---|---|
| App will not start | `uv run insights logs --app X --startup` |
| Started, behaving oddly | `uv run insights logs --app X` |
| A query failing | `uv run insights connections --probe` |
| What is registered? | `uv run insights status` |
| Anything else | the console |

Stop everything:

```bash
lsof -ti tcp:8080 -ti tcp:8081 -ti tcp:8082 | xargs kill -9
```

---

## The whole thing, minimal

```bash
# once
git clone .../insights-platform && git clone .../insights-sdk
uv tool install git+https://github.com/KRISHNABR/insights-sdk.git@v1

# every time
cd insights-platform            && uv run insights up       # terminal 1
cd insights-headcount-dashboard && uv run insights serve    # terminal 2
cd insights-comp-report         && uv run insights run      # terminal 3

# a new app
insights new-app my-app --kind web --team my-team --owner MG-MY-TEAM
cd insights-my-app && uv sync && cp .env.example .env && uv run insights serve
```

---

## Where to go next

| | |
|---|---|
| Every `app.yaml` field | [APP-YAML.md](APP-YAML.md) |
| How it works and why | [ARCHITECTURE.md](ARCHITECTURE.md) |
| The decisions | [adr/](adr/) |
| Day two for your app | `RUNBOOK.md`, in your own repo |
