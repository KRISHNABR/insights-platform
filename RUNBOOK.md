# Runbook

For the platform team. How to operate this, and how to change it without breaking
twenty-five apps.

There are two or three of us. Everything here is written on the assumption that the
person reading it is on call, tired, and did not write the code.

---

## 1 · Daily operations

### Is everything alright?

```bash
uv run insights status                                    # every app: team, kind, SDK version, last seen
uv run insights compliance-report
```

In production, the per-app CloudWatch dashboard is the first stop. Four alarms page us:

| Alarm | Means | First move |
|---|---|---|
| 5xx rate > 2% over 5 min | one app is broken | Check that app's logs. It is almost never the platform |
| Job failed after its last retry | a scheduled run gave up | Read the `job_failed` record; the `reason` field names the exception type |
| Job overran its `timeout` | it was killed mid-run | Check `concurrency` — if `allow`, runs may be piling up |
| **One connection failing across many apps** | **a shared system, a rotated credential, or us** | **See §5** |

The last one is the only alarm that is about the platform rather than an app: a single
app failing to connect is that app's problem, but the *same* connection failing for
everyone at once is a shared system, a credential that rotated, or something we did.

### Where things are

| What | Local | Production |
|---|---|---|
| App logs | `runtime/sinks/events.jsonl` | CloudWatch, `/insights/apps/<name>` |
| Data audit | **not ours** — we hold only the correlation record in `events.jsonl` | Unity Catalog `system.access.audit`, authoritative and theirs |
| What is deployed | `control/registry/apps.json` | same, written by CI |
| Who may read what | not ours — each team's own data platform | Unity Catalog grants (authoritative) |

---

## 2 · Common requests

### "We need access to a dataset"

You cannot grant it, and there is no command that pretends otherwise. Route them to the
**data owner**, and give them the exact request to send:

```bash
# the requesting team runs this; it prints who to ask and what to ask for
uv run insights connections --probe
```

The owner grants it **in the data platform** — a Unity Catalog grant, a role, whatever that
source uses. Nothing is recorded here; `insights doctor` reads their state and goes green.

Two cases, and they are different:

* **Interactive apps** — nothing to do. The signed-in user's identity reaches the data platform,
  so it applies their grants. If they can read it in a notebook, they can read it in the app.
* **Scheduled jobs** — no user to inherit from, so the job acts as `sp-<app>`. Someone must
  grant *that identity*. This is the case people forget until 06:00.

If someone argues this is slow: it is meant to be proportional to sensitivity. Standard datasets
need no grant at all.

### "We need to connect to a system we have not used before"

Not our approval to give. They already have access, or they do not — that is a
conversation with whoever owns that system.

What we do owe them:

1. **Is the engine supported?** `insights connections` refuses an unsupported one at
   load time with the list. Adding an engine is about ten minutes — see
   [ARCHITECTURE §6](docs/ARCHITECTURE.md).
2. **A secret slot.** We bind their app's identity to `insights/<app>/<name>`; their
   group writes the value and we cannot read it.
3. **A `${VAR}` per environment**, if the host differs — `control/registry/environments.yaml`.

### "We need a library the base image doesn't have"

In order, cheapest first:

1. **It is a Python dependency** → it goes in *their* `pyproject.toml`. The image installs it
   from their lockfile. No platform change at all.
2. **It is a system package** (`libgeos`, `unixodbc`) → `runtime.system_packages` in their
   manifest. The rendered image adds an apt layer. Still no platform change.
3. **Two or more teams need the same heavy thing** → that is no longer a long tail. Add a base
   image family member (§4). We are agreeing to patch it forever, so it gets a discussion.

### "Can we use Go / Node / Rust?"

Not today, and be straight about why: the SDK is an in-process Python library, so a
non-Python app gets no identity, no secret binding, no telemetry and no connectors. See
[ADR-005 omission 10](docs/adr/0005-deliberate-omissions-and-triggers.md).
The path is a sidecar, or the HTTP data service in
[ADR-002 alternative D](docs/adr/0002-tenant-isolation-and-data-access.md) — and note that
either one also closes the credential-isolation residual risk in ADR-003, because the
credential stops living in the tenant's process. If someone genuinely needs this, it is a
real project, not a favour.

### "The platform is making something hard that should be easy"

Treat it as a bug in the platform, not as a request to work around. That commitment is the other
half of having no escape hatch ([ADR-004](docs/adr/0004-enforcement-and-platform-rules.md)). If
we stop honouring it, teams route around the platform entirely, which is worse than a weaker
boundary.

---

## 3 · Onboarding a new team

About thirty minutes, most of it waiting for a data owner.

1. Point them at [`ONBOARDING.md`](ONBOARDING.md). Do not walk them through it — if they get
   stuck, that is a bug in the doc and we should fix the doc.
2. Create their repo from `insights new-app`.
3. Confirm `access.manage.owners` is a **corporate group**, not a person. The manifest loader
   rejects anything containing `@`, but check the group actually exists.
4. Their first `uv run insights up` should work with no help. If it does not, that is the highest-priority
   bug we have that week.

---

## 4 · Changing the platform

### Working on the platform and the SDK together

Every repo resolves the SDK from its published `v1` tag, so each one clones and builds
on its own. When you need the platform to run against an SDK change you have not tagged
yet, opt in explicitly:

```bash
cd insights-platform
uv run --with-editable ../insights-sdk insights status
```

That overlays your checkout for **one command**, with no state to forget to undo.

Note that `uv pip install -e ../insights-sdk` on its own does **not** work: `uv run`
re-syncs the project before every command and silently reverts it, so you get the tagged
SDK while believing you are testing your change. If you want the override to stick for a
whole session, add `--no-sync` or export `UV_NO_SYNC=1`.

**Do not commit a path dependency to get this.** It resolves on your machine and nowhere
else, and CI now fails if any repo stops resolving standalone. That check exists because
a path source shipped once and only broke for people who cloned a single repo — which is
everyone except us.

### Releasing a new SDK version

Tenants declare a **floor** (`>=0.1,<1`), so a minor or patch reaches every app on its next
build without anyone doing anything. That is the deal, and it puts the burden on us.

```bash
# in insights-sdk
# 1. make the change, with tests
uv run --with pytest --with pyyaml --with fastapi python -m pytest -q

# 2. update CHANGELOG.md — what a team needs to DO, not what we did
# 3. bump the version in pyproject.toml and __init__.py
# 4. tag
git tag -a v0.2.0 -m "0.2.0" && git push origin v0.2.0
```

**Rules that are not negotiable:**

- **Never break a minor.** New behaviour arrives *alongside* old behaviour. If you cannot do
  that, it is a major.
- **Deprecate before removing.** Mark it, ship it, and let the telemetry tell you who is
  affected:

  ```python
  @deprecated(since="0.2", removed_in="1.0", instead="query()")
  def run_sql(...): ...
  ```

- **Do not cut a major on a date.** Cut it when `sdk_deprecated_use` stops appearing for the
  path you are removing. If it never stops, the migration is too hard and that is our problem
  to fix, not theirs to absorb.
- **Keep the support window at N-2.** `SUPPORTED_VERSIONS` in `insights_sdk/__init__.py` is what
  CI checks a tenant's floor against.

### Changing a generated file

Files listed in `scaffold.PLATFORM_OWNED` live in tenant repos but belong to us.

1. Change the template in `insights_sdk/cli/scaffold.py`.
2. Ship an SDK release.
3. Tell teams to run `insights upgrade-scaffold`. `--check` reports drift without writing, so it
   can go in their CI.

If you add a new generated file, **add it to `PLATFORM_OWNED`** or it will silently rot — there
is a test that asserts every rendered file is listed.

### A team needs a system package, or a different Python version

Nothing to do. They own their Dockerfile (ADR-004) — they add the `apt-get` line or
change the `FROM`, and CI checks only that the base is pinned and the final `USER` is
not root.

We publish no base image, so there is nothing here for anyone to wait on us for. The
cost, stated in ADR-004: nobody patches a tenant's base but the tenant.

### Adding a data connection type

1. Write a connector class in `insights_sdk/connectors.py`, subclassing `_Base`, with
   `query()` and a real `probe()`. `_Base.probe()` raises `NotImplementedError` on
   purpose — a connector that cannot prove a round trip must not claim one.
2. Register it in `_ENGINES`.
3. Add its driver signatures to `_SIGNATURES` so its errors translate to a kind that
   names who fixes it.

It inherits the trusted-caller check, secret binding, `${VAR}` expansion, the `local:`
override and the telemetry shape for free, because those live in `connect()` and not in
the connector. **If you find yourself adding an identity or secret check inside a
connector, stop** — it belongs one level up, where it applies to every engine.

### Changing a CI rule

The reusable workflows in `.github/workflows/` are on the critical path for every tenant deploy.

- A rule that must **never ship** → `control/cli/gates.py`.
- A rule that must hold **even if CI is bypassed** → the SDK runtime. Most data rules are here,
  and the ones in CI are *also* in the runtime, deliberately.
- A rule you are tempted to put in documentation → read
  [ADR-004](docs/adr/0004-enforcement-and-platform-rules.md) first. Documentation is enforcement
  of last resort.

Test workflow changes against a real tenant repo before merging. A broken `deploy.yml` blocks
everyone at once, which is the cost of the thin-caller pattern.

---

## 5 · Incidents

### Where to look first

```
insights up                       # the console registers itself at /apps/console/
```

Four views, all read-only, all telemetry and never rows: **Apps** (what exists, last
seen, recent problems), **Connections** (queries, failures, failure kind, and whether
it is likely ours or the team's), **Runs** (from the scheduler's own state, so a run
that died before emitting anything still appears), **Telemetry** (the raw records).

It is a tenant of this platform, not a privileged tool: it sits behind the edge, gets
the same session cookie and the same group check, and reads `X-Auth-*` exactly as a
tenant app does. If the edge is broken the console is broken too — which is a better
bug to have than a console that works when nothing else does.

### Everything says "did not become healthy", but the apps are fine

A corporate `HTTP_PROXY` whose bypass list has `localhost` but not `127.0.0.1`. The
platform talks to itself over `127.0.0.1` — health checks, the edge's hop to each app,
the REST connector reaching the local stub — so all of it gets handed to a proxy that
correctly refuses to route loopback.

Every local HTTP call now bypasses the proxy (`trust_env=False` for httpx, a
`ProxyHandler({})` opener for urllib), scoped to loopback so a tenant's real REST
connection can still use the proxy when it needs to.

The tell: the edge's own root page works — it makes no upstream call — while every
app route fails.

### An app is down

Almost always the app, not the platform. Two different questions, two different logs:

```bash
insights logs --app headcount-dashboard --startup   # did it boot? tracebacks live here
insights logs --app headcount-dashboard             # it booted - what did it do?
```

`--startup` is the process log: uvicorn's output and any import error or traceback. Without it
an app that dies on import leaves nothing in telemetry, because it never got far enough to
emit any — so the structured view is empty and looks like "no traffic" rather than "crashed".

Then `/healthz`, which opens every connection the app declared and checks its credential
arrived, so it distinguishes "the app is broken" from "the app cannot reach its data".

Platform-wide symptoms: every app failing at once, or the edge not responding. Check the edge
first — nothing works without it.

### Reading the telemetry stream

```bash
insights logs                                   # everything, newest last
insights logs --app comp-report                 # one app
insights logs --event connection_failed --json | jq 'select(.kind=="auth")'
```

Each record carries caller, app, connection, engine, duration and row count — and
nothing else. There is no payload in it by construction, so this stream can be read by
anyone operating the platform without that being access to tenant *data*. That
distinction is the whole of
[ADR-003](docs/adr/0003-operator-access-and-tenant-data.md): we see **that** a query
happened, never **what** it returned.

> **There is no separate `audit` stream.** There was one while the platform brokered
> every read — it carried the dataset, its classification and its owner. It went with
> the broker (ADR-002): the platform is not in the data path, so it has nothing to put
> in those fields. `insights logs --stream` refuses the name rather than returning an
> empty result, because an empty result reads as *"no reads happened"* when the truth
> is *"nothing records this"* — and the difference matters most during an incident,
> which is exactly when someone would run it.

### An app read data and we have no record of it

The residual risk named in
[ADR-003](docs/adr/0003-operator-access-and-tenant-data.md): the SDK runs inside the
tenant's process, so a team *can* open their own connection with their own credential
and read their own data without the platform seeing it. Treat a report of this as a
question about our records, not as an accusation.

1. Confirm the gap: compare the data platform's own audit (Unity Catalog, the database's
   log) for that app's principal against our `connection_opened` / `query_executed`
   correlation records for the same window.
2. If reads there have no matching record here, the app is connecting outside the SDK.
   That is not a control failure — it is the correct description of a platform that does
   not own its tenants' data, and it is stated as such in ADR-003.
3. The recourse is organisational, and it is the team's data either way. What we owe is
   an accurate statement of what our records do and do not cover.

> **What would change this** is the sidecar in §2 ("Can we use Go / Node / Rust?"): a
> credential the tenant's process never holds. That is the only version of this where
> the platform's records are complete, and it costs a service to be paged for.

### We need to see tenant data

We have no standing access, and that is deliberate.

1. Request a **Unity Catalog grant from the dataset owner**, time-boxed. We cannot self-approve.
2. It is recorded in UC's audit, which we cannot edit, and the tenant is notified.
3. Afterwards, ask why telemetry was insufficient. **If asking a data owner for rows is becoming routine, either
   the telemetry is inadequate or the control is theatre.** Either way it means a redesign, not
   tolerance.

### A tenant's manifest was rejected and they are blocked

Read the error — they name the rule and the ADR. The common ones:

| Error | Cause |
|---|---|
| `'classification' may not appear in a tenant manifest` | They tried to mark their own data's sensitivity. That is the data owner's, in the data platform |
| `runtime.sdk is pinned` | They wrote `==`. Floors only |
| `access.manage.owners is required` | No owner group, or they used an individual |
| `kind=not_declared` | The connection is not in `app.yaml` — add it under `connections:` |


None of these should be worked around. If one is wrong, fix the rule.

---

## 6 · Things that will bite you

- **`control/registry/environments.yaml` is a control surface.** Changing a value
  repoints every app that reads it. Review it like code, because it is.
- **The reusable `deploy.yml` blocks everyone when broken.** That is the deliberate cost of one
  pipeline. Keep it simple and fast.
- **`insights doctor` and CI must never disagree.** They share a code path on purpose. If you
  add a check to CI that `doctor` does not run, tenants learn the rules from CI failures — the
  slowest feedback loop there is, and the reason people resent platforms.
- **Two isolation tiers is the maximum.** If someone proposes a third, the model is wrong, not
  the tier count.
- **The local loop finds sibling repos by directory name.** Rename a repo and `uv run insights up` stops
  working, with an unhelpful error. Worth fixing if it ever bites twice.
