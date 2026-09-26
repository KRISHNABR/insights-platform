# Insights Hub — day one

Welcome. You're team #6.

This page gets you from nothing to a running app that reads real data, with auth,
logging and deployment already working. It takes about thirty minutes, and roughly
twenty of those are waiting for someone to approve a data request.

You will write two files. Everything else is generated or inherited.

---

## What you're getting, and what it costs you

**What you get.** Corporate sign-in, authorization, connectors for the systems you
already have access to, somewhere safe to keep the credential, a deployment pipeline,
structured logs, and a health check that actually checks something.

**What it costs you.** You give up choosing your own web framework and your own
logging, and you declare your connections in `app.yaml` rather than building them in
code.

**What it does *not* cost you: your data.** You already have access to your warehouse;
we are not in that loop and do not want to be. We ship the connector, hold the
credential in a store only your app's identity can read, and translate the driver's
error into something that says who has to fix it. We never see your SQL and never see
a row — the telemetry records that a query ran on `hr-warehouse`, took 12ms and
returned 4 rows, and that is all it can record.

**What we don't do.** There's no portal, no data catalog you can browse, and no staging
environment yet. Those are decisions rather than gaps —
[ADR-005](docs/adr/0005-deliberate-omissions-and-triggers.md) lists all fifteen of them with the
trigger that would change our mind. If you hit one, tell us: you're the trigger.

---

## Before you start

You need:

- **Your team's corporate group** (something like `MG-YOUR-TEAM`). Whoever administers
  your team's access has it.
- **Python 3.12+** and [`uv`](https://docs.astral.sh/uv/).
- To know which of the two shapes you're building:

|  | `kind: web` | `kind: job` |
|---|---|---|
| What it is | someone opens it in a browser | it runs on a schedule |
| You get | a routed URL, sign-in, per-request identity | a cron slot, retries, a run identity |
| You write | request handlers | a `main()` |

If you need both, that's two apps. They're cheap.

---

## 1 · Create the app (2 minutes)

Install the CLI once, globally. There is no project yet — that is the point of this
step — so it cannot come from a project's virtualenv:

```bash
uv tool install git+https://github.com/KRISHNABR/insights-sdk.git@v1
```

Or run it without installing anything at all:

```bash
uvx --from git+https://github.com/KRISHNABR/insights-sdk.git@v1 insights new-app ...
```

<details>
<summary>Why the CLI ships inside the SDK, and when to use which</summary>

`insights` is an entry point on the `insights-sdk` package rather than a separate
`insights-cli`, because `uv run insights doctor` has to validate your manifest with **exactly
the code your app will run**. Split them and `doctor` either depends on the SDK anyway
— two version numbers, nothing gained — or reimplements the validation, and then CI
says fine while the runtime says no. That is the worst failure a platform can have.

So there are two ways to run it, and both are correct:

| | Use it for | Why |
|---|---|---|
| `uv tool install` (global) | `new-app` | There is no project yet |
| `uv run insights` (in your repo) | `doctor`, `run`, `build` | Uses **your** pinned SDK, so doctor cannot disagree with your app |

Inside a repo, prefer `uv run insights`. If the global CLI is on 0.3 and your app pins
0.1, the global one would check rules your app does not follow.
</details>

> **Which form to type, in one line:** `insights new-app` (there is no project yet),
> `uv run insights <everything-else>` (from inside your repo, so it uses *your* pinned
> SDK). Both are the same program.

```bash
insights new-app forecast-dashboard \
  --kind web \
  --team demand-planning \
  --owner MG-DEMAND-PLANNING
```

That generates a repository:

```
insights-forecast-dashboard/
├── app.yaml                          ← yours
├── src/main.py                       ← yours
├── static/                           ← yours, if web.type is spa
├── pyproject.toml                    generated — uv, with the SDK floor
├── .github/workflows/ci.yml          generated — 4 lines
├── .github/workflows/deploy-dev.yml  generated — 4 lines
├── .github/workflows/deploy-uat.yml  generated — 4 lines
├── .github/workflows/deploy-prod.yml generated — 4 lines
└── README.md
```

**The Dockerfile is yours** — generated once by `insights new-app`, then your file to edit. CI
checks four things about it (published base, pinned version, non-root, base not stale); it does
not check the rest. You declare a runtime
image. The four workflow files are four lines each and call one platform pipeline. All of it is
**generated rather than copied from a template**, so when we improve it you get the improvement
by upgrading the SDK; you don't inherit a snapshot of what we thought was good eighteen months
ago. `uv run insights upgrade-scaffold` re-renders exactly the files we own and touches nothing else.

`app.yaml` is your whole contract with the platform:

```yaml
apiVersion: v1
app: forecast-dashboard
team: demand-planning
kind: web                      # web | job

access:
  # WHO MANAGES THE APP — deploys, approvals, data requests
  manage:
    owners:       [MG-DEMAND-PLANNING]      # approve prod; request data; answer for it
    contributors: [MG-DEMAND-PLANNING-ENG]  # deploy dev/uat, read logs. NOT prod
    readers:      []                        # see it in `uv run insights status`, nothing more

  # WHO MAY USE THE RUNNING APP — checked by require_role() in your code
  roles:
    - name: forecast-viewer
      groups: [MG-DEMAND-PLANNING]

runtime:
  size: small                  # small | medium | large -> cpu/memory/replicas

connections: []                # what you talk to. Filled in below

web:
  route: /forecast-dashboard
  type: spa                    # api | spa  (the loader refuses anything else)

environments:
  dev:  {auto_deploy: true}
  uat:  {auto_deploy: false, approvers: contributors}
  prod: {auto_deploy: false, approvers: owners}
```

**Three tiers, and there is no fourth.** They nest: an owner satisfies every check a
contributor does, and a contributor every check a reader does — so nobody is listed
twice, and nobody is locked out because somebody forgot to.

There used to be a second `access.roles` block where an app defined its own named
roles. It was removed: two authorization vocabularies in one file meant every reader
had to work out which one a given check used, and in practice apps' roles restated
these three. The loader now refuses it rather than ignoring it.

You will also notice there is no `runtime.sdk` and no `runtime.base`. Both were second
copies of something stated elsewhere — `pyproject.toml` pins the SDK, your Dockerfile's
`FROM` names the base — and a second copy drifts. Both are refused, with a message
saying where the real one lives.

---

## 2 · Get auth (0 minutes — you already have it)

There is nothing to wire up. Sign-in, session handling and group membership arrive from
the platform edge, and your code reads them:

```python
from insights_sdk import current_user, require_role, web_app

app = web_app()

@app.get("/api/me")
def me():
    return {"you": current_user().subject, "groups": list(current_user().groups)}

@app.get("/api/forecast")
def forecast():
    require_role("reader")      # raises → the caller gets a 403
    ...
```

**Two layers of authorization**, and the difference matters:

| Layer | Question | Where it is checked |
|---|---|---|
| Can they reach the app at all? | are they in **any** group this app lists? | the edge, before your code runs |
| Can they do *this*? | `require_role("owner" \| "contributor" \| "reader")` | your code, against `access.manage` |

The first layer is why someone with no business in your app never runs a line of it.

**One thing worth knowing**, because it will confuse you exactly once: if you run your
app directly with `python main.py`, every authorization check fails, and so does
`connect()`. That is not a bug. Identity is only believed when the platform edge
asserts it, so an app running without the edge has a caller with no groups —
deliberately, because the alternative is an app that behaves differently in production
than on your laptop, in the one area where that is dangerous. Use `uv run insights run` or
`uv run insights up`.

---

## 3 · Connect to your data (5 minutes)

**You already have access to your data.** The platform is not in that loop and does not
want to be — there is no catalog here, no entitlement to request from us, and no
approval queue. What we give you is the connector, somewhere safe for the credential,
and an error message that says who has to fix it.

Declare the connection:

```yaml
connections:
  - name: hr-warehouse
    engine: databricks-sql      # databricks-sql | redshift | postgres | rest | sqlite
    host: ${HR_WAREHOUSE_HOST}  # ${VAR} so one manifest works in every environment
    http_path: /sql/1.0/warehouses/abc123
    secret: hr-warehouse-token  # a NAME. Never a value
```

Put the value in the secret store, not in the file:

```
insights/forecast-dashboard/hr-warehouse-token
```

| | |
|---|---|
| writes the value | **your group** |
| reads the value | `sp-forecast-dashboard` — your app's identity, on its own prefix |
| **cannot** read it | the platform team, by an explicit IAM Deny that no Allow overrides |
| sees every read | CloudTrail, including ours |

`app.yaml` is in git, so a password typed there is a password in the history forever.
The manifest loader refuses `password`, `token`, `api_key`, `client_secret` and `dsn`
outright rather than letting you find out later.

Then use it:

```python
from insights_sdk import connect

rows = connect("hr-warehouse").query(
    "SELECT dept, headcount FROM hr_headcount WHERE month = :month", month="2026-09"
)
```

A REST connection is the same shape — `query()` takes a path instead of SQL, and the
connector adds the bearer token for you.

**Check it:**

```bash
uv run insights connections          # what you declared, and whether the secrets resolve
uv run insights connections --probe  # actually open each one
```

---

## 4 · Check it before you push

```bash
uv run insights doctor
```

```
uv run insights doctor  (sdk 0.1.0)

  ok    manifest app.yaml: forecast-dashboard (web, team demand-planning)
  ok    connection hr-warehouse (databricks-sql, secret 'hr-warehouse-token' present)
  ok    Dockerfile on python:3.12-slim, runs as app
  ok    sdk 0.1.0 (supported: 0.1.0)

no problems
```

This is the same code CI runs. Not a similar check — the same one. If it passes here it
passes there, and if it fails you found out in two seconds instead of two minutes.

Run it locally the way the platform runs it:

```bash
uv run insights run        # jobs
uv run insights up         # the whole local platform, including the edge
```

`uv run insights up` starts a stub warehouse, a stub directory API, a fake secret store, every
registered app, the console and the edge on `localhost:8080`. Sign in by adding
`?as=krishna@corp.example` to any URL once — that is the entire local login.

---

## 5 · Logging, and the one rule

```python
from insights_sdk import get_logger
log = get_logger()

log.info("forecast_generated", region="EMEA", rows=len(rows), ms=38)
```

Every record is automatically stamped with your app, team, environment, request id,
caller and SDK version. You don't configure anything.

**The rule: log fields are scalars.** Not rows, not dicts, not DataFrames.

```python
log.info("debug", rows=rows)      # RedactionError, immediately
```

This raises rather than being quietly stripped later, because stripping later fails
open — anything the stripper doesn't recognise has already left. Raising here means you
find out while you're writing the line.

If you want to record a result, record its shape: `rows=len(rows)`. In practice this is
the only platform rule people bump into, and it's usually once.

---

## 6 · Deploy

```bash
git push
```

That's it — to **dev**. Your generated workflows do the rest:

| Workflow | When | Who approves |
|---|---|---|
| `ci.yml` | every PR and branch | nobody — it deploys nothing |
| `deploy-dev.yml` | every merge to main | nobody. That's what dev is for |
| `deploy-uat.yml` | you click Run | your **contributors** |
| `deploy-prod.yml` | you click Run | your **owners** |

Three things worth knowing:

- **The image is built once, in dev.** uat and prod *promote that exact image* — they never
  rebuild. If prod rebuilt, prod would be running code nobody tested.
- **You cannot give yourself a production deploy.** The approver lists come from
  `access.manage` in your manifest, not from your workflow files — which are four lines and
  call ours.
- **In dev your schedule is disarmed.** A job deploys to dev but won't fire on its own; run it
  by hand with `uv run insights run`. Nobody wants a half-finished report emailing people at 06:00.

**Know it's healthy:**

```bash
uv run insights status
```

```
APP                     TEAM                KIND  SDK     LAST SEEN             STATUS
comp-report             people-analytics    job   0.1.0   2026-09-26T06:00:02Z  ok  restricted
forecast-dashboard      demand-planning     web   0.1.0   2026-09-26T14:02:11Z  ok
headcount-dashboard     people-ops          web   0.1.0   2026-09-26T13:58:40Z  ok
```

Your app also exposes `/healthz`, which opens every connection you declared and confirms
the credentials were injected — so the classic failure, a deploy that starts fine and
breaks on first use, shows up at the probe instead of in front of a user.

---

## Upgrades — what happens when we change something

Your `pyproject.toml` says `insights-sdk>=0.1,<1`. That is a **floor, not a pin**, and
it is the deal. `uv.lock` pins the exact version you run, so nothing changes underneath
you — a release reaches you when you re-lock:

```bash
uv lock --upgrade-package insights-sdk
uv run insights doctor
```


- **Patches and minors reach you automatically** on your next build. You get fixes and
  new capabilities without doing anything.
- **We never break you in a minor.** New behaviour arrives alongside old behaviour.
- **When something is going away**, it keeps working and starts telling us you're using
  it. We then come to you with the specific thing to change, not a broadcast email — we
  can see who's affected and what they actually call.
- **We support the current major and the two before it.** The deploy gate fails an app
  outside the window, so you find out at your desk rather than on the day you need to
  ship something urgent.
- **A major version is a migration we write with you**, and we don't cut one until the
  telemetry says nobody is still on the removed path.

If you pin an exact version with `==`, CI rejects it. A pinned app is an app we
eventually have to break.

Generated files — your pipelines and `RUNBOOK.md` — are refreshed separately:

```bash
uv run insights upgrade-scaffold --check     # are they current?
uv run insights upgrade-scaffold             # update, then review the diff
```

---

## Where things live

| Question | Answer |
|---|---|
| How does this work? | [`docs/ARCHITECTURE.md`](docs/ARCHITECTURE.md) |
| Why does it work that way? | [`docs/adr/`](docs/adr/) — five decision records |
| What's NOT built, and why? | [ADR-005](docs/adr/0005-deliberate-omissions-and-triggers.md) |
| What can the platform team see? | [ADR-003](docs/adr/0003-operator-access-and-tenant-data.md) — short version: not your data |
| I have a compliance reviewer | [`COMPLIANCE.md`](COMPLIANCE.md), and `insights compliance-report` |
| Day-two operations for my app | `RUNBOOK.md`, generated into your own repo |

## When you get stuck

We're two to three people, so here's an honest triage:

| Situation | Do this |
|---|---|
| `uv run insights doctor` fails | The message says what and usually how. Start there |
| A connection fails with `auth` | Your credential — check the secret's value and expiry |
| A connection fails with `tls` or `network` | Ours — tell us the host and paste the error |
| You need a data source we don't support | Talk to us early. It's a platform change, and it's a queue |
| The platform made something hard that should be easy | That's a bug in the platform, not a thing to work around. Tell us |

That last row is the one we mean most. The platform's job is to make the right thing the
easy thing. If you're fighting it, we got something wrong.
