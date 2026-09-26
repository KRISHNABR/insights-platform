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
[ADR-005](docs/adr/0005-deliberate-omissions-and-triggers.md) lists all eleven of them with the
trigger that would change our mind. If you hit one, tell us: you're the trigger.

---

## Before you start

You need:

- **Your team's corporate group** (something like `MG-YOUR-TEAM`). Whoever administers
  your team's access has it.
- **Python 3.11+** and [`uv`](https://docs.astral.sh/uv/).
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
├── app.yaml                     ← yours
├── src/main.py                  ← yours
├── Dockerfile                   generated — three lines, don't edit
├── .github/workflows/ci.yml     generated — four lines, don't edit
└── README.md
```

**The two files that are yours are the only two files that are yours.** The Dockerfile
and the CI config are generated rather than copied from a template, so when we improve
them you get the improvement by upgrading the SDK — you don't inherit a snapshot of what
we thought was good eighteen months ago.

`app.yaml` is your whole contract with the platform:

```yaml
apiVersion: v1
app: forecast-dashboard
team: demand-planning
kind: web

owners:
  - MG-DEMAND-PLANNING      # becomes forecast-dashboard-admin

runtime:
  sdk: ">=0.1,<1"           # a floor, not a pin — see "Upgrades" below

data: []                    # datasets go here
access:
  roles: []                 # who may use this app
```

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
| Platform membership | can this person reach any app at all? | corporate SSO |
| App roles | can they use *this* app, or this part of it? | `access.roles` in your manifest |

Add a role to `access.roles` and the platform creates the group at deploy time. You
don't create groups by hand and you don't check them by hand.

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

### If the dataset is restricted

Some datasets — compensation is the obvious one — need a second approval. Declaring
them isn't enough:

```bash
insights access request --dataset hr.compensation --reason "quarterly equity review"
```

That prints a request for the **dataset owner**, not for us. We can't approve it, and
that's the point: the platform team doesn't decide who reads your colleagues' salaries.
While you wait, `insights doctor` will show the dataset as `NOT GRANTED` and your app
will refuse to read it — at your desk, not in production.

Restricted datasets come with three things you'll notice:

1. Some fields come back as `***` unless the owner granted your app the role that
   unmasks them.
2. Your logs are checked at write time for field names from that dataset, and the logger
   *raises* if one appears. See §5.
3. Every read is recorded with who, what and how many rows.

---

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
the edge on `localhost:8080`. Sign in by adding `?as=dana@corp.example` to any URL —
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

That's it. Your four-line CI file calls our pipeline, which validates your manifest,
checks your datasets against the registry, checks your SDK version is supported, builds
you on the platform base image, registers you, and rolls you out.

You don't maintain a pipeline. When we make deploys faster or safer, you get it on your
next push without changing anything.

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
