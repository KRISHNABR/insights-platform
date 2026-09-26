# Insights Hub — day one

Welcome. You're team #6.

This page gets you from nothing to a running app that reads real data, with auth,
logging and deployment already working. It takes about thirty minutes, and roughly
twenty of those are waiting for someone to approve a data request.

You will write two files. Everything else is generated or inherited.

---

## What you're getting, and what it costs you

**What you get.** Corporate sign-in, authorization, access to shared data connections,
a deployment pipeline, structured logs, a health check that actually checks something,
and a base image somebody else patches.

**What it costs you.** You give up choosing your own web framework, your own logging,
and — the one people notice — **direct access to the warehouse**. You never get a
connection string. You name a dataset and we run the query.

That last one is the deliberate trade, so it's worth saying why up front: if we handed
every app a warehouse connection, every app could read compensation data, and we'd have
no way to tell you which app read what. Instead, access is per dataset, the owner of the
data approves it, and every read is recorded. If you only ever read your own team's
numbers, you'll never notice. If you're the team whose data everyone wants, you'll care
a lot.

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

```bash
pip install "insights-sdk>=0.1,<1"

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

**There is no Dockerfile**, and that is deliberate — you declare a runtime, you don't build an
image. The four workflow files are four lines each and call one platform pipeline. All of it is
**generated rather than copied from a template**, so when we improve it you get the improvement
by upgrading the SDK; you don't inherit a snapshot of what we thought was good eighteen months
ago. `insights upgrade-scaffold` re-renders exactly the files we own and touches nothing else.

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
    readers:      []                        # see it in `insights status`, nothing more

  # WHO MAY USE THE RUNNING APP — checked by require_role() in your code
  roles:
    - name: forecast-viewer
      groups: [MG-DEMAND-PLANNING]

runtime:
  sdk: ">=0.1,<1"              # a floor, not a pin
  base: python-web             # `insights runtimes` lists them. We patch these
  size: small

data: []                       # dataset names; `insights datasets` shows what you can ask for

web:
  route: /forecast-dashboard
  type: spa                    # api | spa  (the loader refuses anything else)

environments:
  dev:  {auto_deploy: true}
  uat:  {auto_deploy: false, approvers: contributors}
  prod: {auto_deploy: false, approvers: owners}
```

**The two `access` blocks answer different questions, and keeping them apart matters.**
`manage` is *who can deploy and govern this app*. `roles` is *who can use it*. An engineer who
can ship to uat is not thereby allowed to read what the app reads, and a person allowed to view
the dashboard cannot deploy it. Mixing those two is the most common way an internal platform
quietly leaks.

You declare *what you need*. We decide *how it's satisfied* — which engine, which
credential, which physical table in which environment. That's why there's nothing in
there resembling a connection string, and why the manifest loader will reject one if you
add it.

---

## 2 · Get auth (0 minutes — you already have it)

There is nothing to wire up. Sign-in, session handling and group membership arrive from
the platform edge, and your code reads them:

```python
from insights_sdk import current_user, require_role, web_app

app = web_app()

@app.get("/")
def index():
    return {"you": current_user().subject, "groups": list(current_user().groups)}

@app.get("/forecast")
def forecast():
    require_role("forecast-viewer")      # raises → the caller gets a 403
    ...
```

**Two layers of authorization**, and the difference matters:

| Layer | Question | Where it comes from |
|---|---|---|
| Can they reach the app at all? | is this person in **any** group this app declared? | checked at the edge, before your code runs |
| Can they do *this*? | `require_role("forecast-viewer")` | `access.roles` in your manifest |
| Can the **app** read this data? | is the dataset declared, and granted by its owner? | your manifest **and** the data owner |

Add a role to `access.roles` and the platform reconciles the corporate groups behind it at
deploy time. You don't create groups by hand and you don't check membership by hand.

The third row is worth reading twice: it is about the **app**, not the person. Someone with
every permission in the company still gets nothing from an app that never declared the
dataset.

**One thing worth knowing**, because it will confuse you exactly once: if you run your
app directly with `python main.py`, every authorization check fails. That's not a bug.
Identity is only believed when the platform edge asserts it, so an app running without
the edge in front of it has a caller with no groups — deliberately, because the
alternative is an app that behaves differently in production than on your laptop in the
one area where that's dangerous. Use `insights run`.

---

## 3 · Get data (2 minutes, plus approval)

**See what exists:**

```bash
insights datasets
```

```
datasets for forecast-dashboard

  ENTITLED
    (none yet)

  AVAILABLE TO REQUEST  (ask the owner — the platform does not decide this)
    hr.headcount           internal     MG-PEOPLE-OPS
                           Headcount by department and month. Aggregate, no individuals.
    sales.pipeline         internal     MG-SALES-OPS
                           Open opportunities by region.
```

A name, an owner, one line of description. That's on purpose — this is an access
registry, not a data catalog. If you want to know what's *in* a dataset, talk to the
owner. That conversation is where they find out who's using their data and why, and
it's worth more than a schema browser.

**Declare what you need:**

```yaml
data:
  - dataset: sales.pipeline
    access: read
```

**Then read it:**

```python
from insights_sdk import query

rows = query(
    "sales.pipeline",
    "SELECT region, SUM(value) AS total FROM sales.pipeline GROUP BY region",
)
```

Write SQL against the **dataset name**. We substitute the physical table for whatever
environment you're in, so the same query works everywhere and you never learn that the
production table is called something else. Bind values with `:named` parameters; never
format them into the string.

For REST-backed datasets the verb is `fetch()` — the resource path comes from the
registry, not from you:

```python
from insights_sdk import fetch
people = fetch("directory.people", params={"dept": "Engineering"})
```

If you call the wrong verb, the error tells you which one to use.

### Getting access — we are not in that loop

The platform does not own the data and cannot grant access to it. What it does is tell you
**exactly what to ask for, and who to ask**:

```bash
uv run insights access --reason "quarterly equity review"
```

```
  hr.compensation   owner: MG-PEOPLE-ANALYTICS   not granted

    Send to MG-PEOPLE-ANALYTICS:

      Please grant read access on hr.compensation
      to the service identity  sp-forecast-dashboard
      for the app              forecast-dashboard (demand-planning)
```

Two things are worth understanding here.

**Interactive requests run as you.** When someone opens your app, their own identity reaches
the data platform, so it applies *their* grants and *their* column masks. If they can read it
in a notebook, they can read it here; if they cannot, they cannot. You do not manage that.

**Unattended work runs as your app.** A 06:00 job has nobody to inherit access from, so it acts
as its own service identity — `sp-<your-app>`, derived from your app name. You do not declare
it and you cannot change it; that is deliberate, because access is granted *to identities*, and
a team that could name its own could claim another app's.

So for a scheduled job, someone has to grant `sp-<your-app>` in the data platform. `insights
doctor` checks whether that has happened and fails at your desk rather than at 06:00.

Restricted datasets come with two more things you will notice:

1. Some fields come back as `***`. In production that masking is applied by the data platform
   itself, per principal, on every path to the data — so a notebook sees the same thing.
2. Your logs are checked at write time for field names from that dataset, and the logger
   *raises* if one appears. See §5.

## 4 · Check it before you push

```bash
insights doctor
```

```
insights doctor  (sdk 0.1.0)

  ok    manifest app.yaml: forecast-dashboard (web, team demand-planning)
  ok    dataset sales.pipeline (internal)
  ok    sdk floor >=0.1,<1 (supported: 0.1.0)

no problems
```

This is the same code CI runs. Not a similar check — the same one. If it passes here it
passes there, and if it fails you found out in two seconds instead of two minutes.

Run it locally the way the platform runs it:

```bash
insights run        # jobs
insights up         # the whole local platform, including the edge
```

`insights up` starts a stub warehouse, a stub directory API, every registered app and
the edge on `localhost:8080`. Sign in by adding `?as=krishna@corp.example` to any URL —
that's the entire local login.

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
  by hand with `insights run`. Nobody wants a half-finished report emailing people at 06:00.

**Know it's healthy:**

```bash
insights status
```

```
APP                     TEAM                KIND  SDK     LAST SEEN             STATUS
comp-report             people-analytics    job   0.1.0   2026-09-26T06:00:02Z  ok  restricted
forecast-dashboard      demand-planning     web   0.1.0   2026-09-26T14:02:11Z  ok
headcount-dashboard     people-ops          web   0.1.0   2026-09-26T13:58:40Z  ok
```

Your app also exposes `/healthz`, which resolves every dataset you declared and confirms
the credentials were injected — so the classic failure, a deploy that starts fine and
breaks on first use, shows up at the probe instead of in front of a user.

---

## Upgrades — what happens when we change something

Your manifest says `sdk: ">=0.1,<1"`. That's a **floor, not a pin**, and it's the deal:

- **Patches and minors reach you automatically** on your next build. You get fixes and
  new capabilities without doing anything.
- **We never break you in a minor.** New behaviour arrives alongside old behaviour.
- **When something is going away**, it keeps working and starts telling us you're using
  it. We then come to you with the specific thing to change, not a broadcast email — we
  can see who's affected and what they actually call.
- **We support the current major and the two before it.** `insights doctor` warns before
  you fall out of the window.
- **A major version is a migration we write with you**, and we don't cut one until the
  telemetry says nobody is still on the removed path.

If you pin an exact version, the manifest loader rejects it. A pinned app is an app we
eventually have to break.

---

## Where things live

| Question | Answer |
|---|---|
| How does this work? | [`docs/ARCHITECTURE.md`](docs/ARCHITECTURE.md) |
| Why does it work that way? | [`docs/adr/`](docs/adr/) — five decision records |
| What's NOT built, and why? | [ADR-005](docs/adr/0005-deliberate-omissions-and-triggers.md) |
| What can the platform team see? | [ADR-003](docs/adr/0003-operator-access-and-tenant-data.md) — short version: not your data |
| I have a compliance reviewer | [`COMPLIANCE.md`](COMPLIANCE.md), and `insights compliance-report` |

## When you get stuck

We're two to three people, so here's an honest triage:

| Situation | Do this |
|---|---|
| `insights doctor` fails | The message says what and usually how. Start there |
| A dataset is `NOT GRANTED` | Chase the **dataset owner**, not us — we can't approve it |
| You need a data source we don't support | Talk to us early. It's a platform change, and it's a queue |
| The platform made something hard that should be easy | That's a bug in the platform, not a thing to work around. Tell us |

That last row is the one we mean most. The platform's job is to make the right thing the
easy thing. If you're fighting it, we got something wrong.
