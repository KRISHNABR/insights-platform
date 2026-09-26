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
uv run insights compliance-report --dataset hr.compensation
```

In production, the per-app CloudWatch dashboard is the first stop. Four alarms page us:

| Alarm | Means | First move |
|---|---|---|
| 5xx rate > 2% over 5 min | one app is broken | Check that app's logs. It is almost never the platform |
| Job failed after its last retry | a scheduled run gave up | Read the `job_failed` record; the `reason` field names the exception type |
| Job overran its `timeout` | it was killed mid-run | Check `concurrency` — if `allow`, runs may be piling up |
| **App queried data it never audited** | **possible bypass of the broker** | **Escalate. See §5** |

The last one is the only alarm that is about the platform rather than an app.

### Where things are

| What | Local | Production |
|---|---|---|
| App logs | `runtime/sinks/events.jsonl` | CloudWatch, `/insights/apps/<name>` |
| Data audit | `runtime/sinks/audit.jsonl` | Unity Catalog `system.access.audit` (authoritative) + our correlation record |
| What is deployed | `control/registry/apps.json` | same, written by CI |
| Who may read what | `control/registry/grants.yaml` | Unity Catalog grants (authoritative) |

---

## 2 · Common requests

### "We need access to a dataset"

You cannot grant it, and there is no command that pretends otherwise. Route them to the
**data owner**, and give them the exact request to send:

```bash
# the requesting team runs this; it prints who to ask and what to ask for
uv run insights access --reason "quarterly equity review"
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

### "We need a dataset that doesn't exist yet"

1. The data owner creates and owns it in the data platform.
2. Add it to [`control/registry/catalog.yaml`](control/registry/catalog.yaml): name, connection,
   owner, and its location per environment.
3. Open a PR. **This file gets a real review** — it is a control surface, not configuration.
4. The team declares it in their `app.yaml`. Restricted datasets also need the owner's grant.

### "We need a library the base image doesn't have"

In order, cheapest first:

1. **It is a Python dependency** → it goes in *their* `pyproject.toml`. The image installs it
   from their lockfile. No platform change at all.
2. **It is a system package** (`libgeos`, `unixodbc`) → `runtime.system_packages` in their
   manifest. The rendered image adds an apt layer. Still no platform change.
3. **Two or more teams need the same heavy thing** → that is no longer a long tail. Add a base
   image family member (§4). We are agreeing to patch it forever, so it gets a discussion.

### "Can we use Go / Node / Rust?"

Not today, and be straight about why: the broker is an in-process Python library, so there is no
way for a non-Python app to reach data. See [ADR-005 omission 10](docs/adr/0005-deliberate-omissions-and-triggers.md).
The path is a sidecar broker — and note it closes the credential-isolation gap in ADR-003 at the
same time. If someone genuinely needs this, it is a real project, not a favour.

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

### Changing a base image

```bash
# edit runtime/base-image/python-web.Dockerfile
# bump BASE_VERSIONS in insights_sdk/cli/scaffold.py
# rebuild and push; apps pick it up on their next build
```

A CVE in a base image is one rebuild plus a redeploy of affected apps — that property is most of
the argument for a paved road. Since ADR-004 tenants own their Dockerfile, so a base change is
not a silent rebuild any more: bump BASE_VERSIONS, and every app's `doctor` and deploy gate
starts reporting the stale pin until they bump their FROM. Announce it; do not assume they look.

### Adding a base image family member

Do this when **two or more** teams need the same thing, not on the first request. It is a
permanent maintenance commitment.

1. Add `runtime/base-image/python-<name>.Dockerfile`.
2. Add it to `VALID_BASES` in `insights_sdk/config.py` and `BASE_VERSIONS` in `scaffold.py`.
3. If it changes how the app starts, extend `runtime/base-image/entrypoint.sh`.
4. Document it in `runtime/base-image/README.md`.

### Adding a data connection type

1. Write an adapter class in `insights_sdk/adapters.py` with a `run()` method.
2. Register it in `_ENGINES`.
3. Add the connection to `control/registry/catalog.yaml`.

It inherits entitlement, grants, masking, audit and the redaction assertions for free, because
those live in the broker and not in the adapter. **That claim is the reason the broker is shaped
this way — if you find yourself adding an authorization check inside an adapter, stop.**

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
insights up                       # the console registers itself at /a/console/
```

Four views, all read-only, all telemetry and never rows: **Apps** (what exists, last
seen, recent problems), **Connections** (queries, failures, failure kind, and whether
it is likely ours or the team's), **Runs** (from the scheduler's own state, so a run
that died before emitting anything still appears), **Telemetry** (the raw records).

It is a tenant of this platform, not a privileged tool: it sits behind the edge, gets
the same session cookie and the same group check, and reads `X-Auth-*` exactly as a
tenant app does. If the edge is broken the console is broken too — which is a better
bug to have than a console that works when nothing else does.

### An app is down

Almost always the app, not the platform. Two different questions, two different logs:

```bash
insights logs --app headcount-dashboard --startup   # did it boot? tracebacks live here
insights logs --app headcount-dashboard             # it booted - what did it do?
```

`--startup` is the process log: uvicorn's output and any import error or traceback. Without it
an app that dies on import leaves nothing in telemetry, because it never got far enough to
emit any — so the structured view is empty and looks like "no traffic" rather than "crashed".

Then `/healthz`, which resolves every dataset the app declared and checks its credential
arrived, so it distinguishes "the app is broken" from "the app cannot reach its data".

Platform-wide symptoms: every app failing at once, or the edge not responding. Check the edge
first — nothing works without it.

### Reading the audit stream

```bash
insights logs --stream audit                        # every read of a governed dataset
insights logs --stream audit --event dataset_read --json | jq 'select(.masked_fields > 0)'
```

Each record carries caller, dataset, classification, owner, row count and masked-field count —
and nothing else. There is no payload in it by construction, so this stream can be read by
anyone operating the platform without that being access to tenant *data*. That distinction is
the whole of [ADR-003](docs/adr/0003-operator-access-and-tenant-data.md): we see **that** a
read happened, never **what** was read.

### "App queried data it never audited"

The one alarm that suggests the broker was bypassed. Treat as a potential data incident.

1. Confirm: compare the app's request volume with its audit records for the same window.
2. Check Unity Catalog's audit for reads by that app's principal that have no matching
   correlation record from us.
3. If confirmed, this is the residual risk named in
   [ADR-003](docs/adr/0003-operator-access-and-tenant-data.md) §"the gap we cannot close" — the
   credential lives in the tenant's process. Involve the team's management chain; the recourse
   here is organisational, which is the premise the whole isolation model rests on.

### We need to see tenant data

We have no standing access, and that is deliberate.

1. Request a **Unity Catalog grant from the dataset owner**, time-boxed. We cannot self-approve.
2. It is recorded in UC's audit, which we cannot edit, and the tenant is notified.
3. Afterwards, ask why telemetry was insufficient. **If break-glass is becoming routine, either
   the telemetry is inadequate or the control is theatre.** Either way it means a redesign, not
   tolerance.

### A tenant's manifest was rejected and they are blocked

Read the error — they name the rule and the ADR. The common ones:

| Error | Cause |
|---|---|
| `'classification' may not appear in a tenant manifest` | They tried to mark their own data's sensitivity. That is the data owner's, in the data platform |
| `runtime.sdk is pinned` | They wrote `==`. Floors only |
| `access.manage.owners is required` | No owner group, or they used an individual |
| `not entitled to X` | Declared in neither `app.yaml` nor granted |
| `runtime.base is not published` | They invented a base image |

None of these should be worked around. If one is wrong, fix the rule.

---

## 6 · Things that will bite you

- **`control/registry/catalog.yaml` is a control surface.** Changing a dataset's location
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
