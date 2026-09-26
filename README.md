# Insights Hub

An internal platform for small analytics apps — dashboards, scheduled reports, data
explorers — built for teams who currently hand-roll auth, data access, deployment and
logging for every one of them.

**This is the root of the submission.** It's four repositories; this one is the platform,
and everything is indexed from here.

---

## Read this in ten minutes

| If you have | Read |
|---|---|
| **2 minutes** | this page, down to *"The shape of it"* |
| **10 minutes** | [`docs/ARCHITECTURE.md`](docs/ARCHITECTURE.md) — the whole system in one document |
| **30 minutes** | [ADR-002](docs/adr/ADR-002-shared-data-and-isolation.md) and [ADR-003](docs/adr/ADR-003-operator-access.md) — the two decisions most worth arguing with |
| **an hour** | all five [ADRs](docs/adr/), then [`ONBOARDING.md`](ONBOARDING.md) to see what it feels like to a tenant |

**If you only read one thing:** [`docs/ARCHITECTURE.md`](docs/ARCHITECTURE.md).

---

## Run it

Four repositories, side by side in one directory:

```bash
git clone <this-repo>            insights-platform
git clone <sdk-repo>             insights-sdk
git clone <web-app-repo>         insights-headcount-dashboard
git clone <job-app-repo>         insights-comp-report
```

Then, from `insights-platform/`:

```bash
./dev up
```

That seeds a stub warehouse, starts a stub internal REST API, starts every registered
app, and puts the platform edge on `localhost:8080`. Requires Python 3.11+ and
[`uv`](https://docs.astral.sh/uv/); nothing else, and no cloud account.

(If something already has port 8080, `./dev up --port 9100` moves the whole stack. It
checks before starting anything rather than failing on the third process.)

```bash
# sign in — appending ?as= is the whole local login
open "http://localhost:8080/a/headcount-dashboard/?as=dana@corp.example"

# read the warehouse, through the broker
curl "http://localhost:8080/a/headcount-dashboard/headcount?month=2026-09"

# read the internal REST API — different connection, same broker
curl "http://localhost:8080/a/headcount-dashboard/team?dept=Engineering"
```

In another shell:

```bash
./dev status                                          # every app, four facts each
./dev compliance-report --dataset hr.compensation     # what a reviewer gets handed
python runtime/scheduler/main.py --all                # run the scheduled job now
```

And the test suite, from `insights-sdk/`:

```bash
uv run --with pytest --with pyyaml --with fastapi python -m pytest -q      # 31 tests
```

### Three things worth trying, because they're the design

```bash
# 1. Knowing a dataset's name is not access.
#    sales.pipeline is real and has rows. This app didn't declare it.
curl "http://localhost:8080/a/headcount-dashboard/headcount"   # works
# ...then add sales.pipeline to a query in src/main.py → EntitlementError

# 2. A client cannot assert its own identity.
#    Signed in as Dana, who is not a comp-analyst:
curl -b cookies.txt \
     -H "X-Auth-User: ceo@corp.example" \
     -H "X-Auth-Groups: comp-analyst" \
     "http://localhost:8080/a/headcount-dashboard/"
# → still Dana. The edge strips those headers before the app ever sees them.

# 3. A tenant cannot declare its own data sensitive-or-not.
#    Add `classification: internal` to a dataset in any app.yaml → the manifest is rejected,
#    at runtime AND in CI.
```

---

## The shape of it

**The tenant contract:** *you write your app logic and an `app.yaml`. Everything else is
inherited.*

| Repository | Who touches it | What's in it |
|---|---|---|
| [`insights-sdk`](../insights-sdk) | **tenants**, as a dependency | the library, the `insights` CLI, the scaffold templates |
| `insights-platform` *(here)* | **platform team only** | `runtime/` · `control/` · the reusable CI workflow · docs and ADRs |
| [`insights-headcount-dashboard`](../insights-headcount-dashboard) | tenant | example: interactive web app |
| [`insights-comp-report`](../insights-comp-report) | tenant | example: scheduled job, restricted data |

```
insights-platform/
├── docs/
│   ├── ARCHITECTURE.md          ← the system, end to end
│   └── adr/                     ← five decision records
├── ONBOARDING.md                ← day one for team #6
├── COMPLIANCE.md                ← the control catalogue, for a reviewer
├── control/
│   ├── registry/
│   │   ├── catalog.yaml         connections + datasets. The access registry
│   │   ├── grants.yaml          the second key for restricted data
│   │   └── apps.json            what is deployed (written by CI; by `up` locally)
│   └── cli/gates.py             the CI-layer rules
├── runtime/
│   ├── edge/                    identity. The most important 120 lines here
│   ├── scheduler/               what makes `kind: job` mean something
│   ├── base-image/              what 25 apps build FROM
│   ├── fakes/                   stub warehouse + stub internal REST API
│   └── sinks/                   events.jsonl + audit.jsonl
└── .github/workflows/deploy.yml the one pipeline every tenant calls
```

**Two ideas most of the design falls out of:**

1. **Declare, don't wire.** A tenant declares intent — a dataset name, a role, a
   schedule. The platform resolves it to an engine, a credential, a group, a cron slot.
2. **Enforce at the earliest layer that makes a rule impossible to get wrong.**
   Generator → SDK runtime → CI → human review → documentation last.

And the ownership line that follows: **you own your code, we own the road it travels on.**

---

## The questions the brief asked

Each is answered properly in an ADR; these are the one-line versions.

**Reuse and upgrade** — a versioned SDK, installed as a dependency, with the CLI and
scaffolds inside it. Tenants declare a floor (`>=0.1,<1`), never a pin, so patches and
minors flow automatically. The upgrade story with twelve dependants rests on
**deprecation telemetry**: a deprecated call emits an event naming the app, version and
symbol, so migration is a list of four teams rather than a broadcast email. Majors are
cut when that list empties, not on a date.
→ [ADR-001](docs/adr/ADR-001-reuse-and-upgrade.md)

**Isolation, and shared data connections** — the platform **brokers reads; it never hands
out a connection.** Sharing a connection means sharing a credential, and then nothing
stops the headcount dashboard selecting salaries. Tenants name a logical dataset; the
platform resolves connection, engine, location, credential and classification. Isolation
is soft by default with a restricted tier triggered by the **data's classification, not
the tenant's identity** — and classification lives in the platform registry, so no team
can downgrade its own.
→ [ADR-002](docs/adr/ADR-002-shared-data-and-isolation.md)

**Operator access** — telemetry structurally cannot carry payloads: the logger *raises*
at the emit point rather than scrubbing at the sink, because scrubbing fails open. The
platform team has no standing access to tenant rows; break-glass is time-boxed,
approved by the **dataset owner** rather than by us, audited, and the tenant is notified.
We also write down the hole we can't close: the broker is in-process, so the credential
sits in the tenant's container.
→ [ADR-003](docs/adr/ADR-003-operator-access.md)

**Enforcement** — each rule goes to the earliest layer that makes it impossible to get
wrong. The diagnostic: *what does the day-one guide have to warn people about?* Every
warning is a control sitting one layer too late.
→ [ADR-004](docs/adr/ADR-004-enforcement-placement.md)

**Deliberate omissions** — eleven of them, each with the trigger that reverses it. No
portal, no policy engine, no per-tenant infrastructure, no multi-environment promotion,
**no data discovery**, no per-user credential passthrough, no federation to an
enterprise data catalog.
→ [ADR-005](docs/adr/ADR-005-deliberate-omissions.md)

---

## What I'd do next

In order, with the reason — not a backlog, a sequence.

**1. A staging environment and promotion. *(the trigger has already fired)***
This is the omission I'm least comfortable with. ADR-005 says the trigger is "the first
tenant whose app affects a decision someone is accountable for" — which is People
Analytics, i.e. now. Everything is already environment-aware (the registry resolves
locations per environment), so this is a second registry environment and a promotion
gate rather than a redesign. I left it because a fake second environment would have
proved nothing; a real one is the first thing I'd build.

**2. Periodic access review.** The compliance partner will ask for it and we don't have
it. All the data exists — grants, audit records, owners — so this is a report and a
cadence, not new machinery. It pairs naturally with (1) because both are about evidence
over time rather than evidence at a point.

**3. Move the broker into a sidecar.** Today the credential sits in the tenant's own
process, which I've written down rather than glossed (ADR-002 §3). A sidecar in the same
pod gives process isolation without the cost of a platform-wide data service. I'd do
this before onboarding any tenant that isn't a team of employees.

**4. Make `insights status` answer "is it broken?" rather than "did it run?"**
Right now it reports last-seen and version — enough to operate five apps, thin for
twenty-five. The next increment is error rates and last-failure per app, from telemetry
we already emit. Cheap, and it's the difference between operating and watching.

**5. Federate the registry to a real data catalog.** Our registry is authoritative today
and shouldn't be forever: classification, ownership and grants belong to whatever
governed data platform the organisation runs. I shaped `catalog.yaml` as a projection of
exactly that, and every lookup goes through one function, so this is `resolve()` and
nothing else (ADR-002 §6). Do it *before* per-user credential passthrough — it's what
makes passthrough an integration instead of a programme.

**6. A second engine adapter, chosen by an actual tenant.** The broker's value claim is
"adding an engine inherits every control for free." That's true in the code and
unproven in practice. The first real request tests it, and I'd rather find out on
someone's object store than assume.

### And the thing I'd change about what's here

The data API is narrow on purpose — two verbs, no escape hatch — and I think that's
right, but it's the decision most likely to be wrong. The signal to watch is the rate of
"can the platform add X" tickets. A slow trickle means the API is well-judged. A steady
stream means the platform team has become a queue, and the honest response then isn't to
add an escape hatch — it's alternative C in ADR-002, a data service that other languages
and other shapes of query can reach.

---

## Notes on scope

Time budget was 10–12 hours, and the brief says it scores prioritisation rather than
endurance. Where I spent it:

| | Why |
|---|---|
| **ADRs and docs (~45%)** | the brief says ADRs first, code second, and means it |
| **The data broker and its tests (~30%)** | it's the decision everything else rests on, so it needed to be real rather than described |
| **Runtime, CLI, CI, examples (~25%)** | enough to prove the model runs end to end |

What I deliberately didn't polish: no web UI for status (the CLI has the same data), no
Docker Compose (the CLI orchestrates the local stack in one command), no retries or
backfill in the scheduler. Each of those would have looked more finished and taught a
reader less.

**Two things surfaced by building rather than designing**, both of which changed the
design and are the reason the code was worth writing:

- A scheduled job has no human caller, so "may this caller see salaries?" has no answer
  from corporate groups. The tempting fix — read `access.roles` from the manifest — lets
  a team unmask compensation by editing its own repo. The roles now come from the
  **grant**, which only the dataset owner can write.
- An undeclared dataset and a nonexistent one now return the *same* error, because a
  differentiated error would let any tenant enumerate the registry by guessing names.
  That's a discovery oracle, and there's a test asserting the two errors stay identical.
