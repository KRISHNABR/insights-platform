# Insights Hub — architecture

*The whole system in one document: what it is, how a request and a deploy flow through it, and
where every decision behind it is written down. This records no decision of its own — the five
[ADRs](adr/) do that, each one severable so it can be superseded on its own. Read this first, then
go argue with whichever ADR you disagree with.*

---

## Everything traces back to three sentences in the brief

Almost every decision in this design is downstream of three facts we were given. Where they
conflict, the ADRs say which one won and why.

| The fact | What it licenses | Mostly drives |
|---|---|---|
| *"The platform team is **2–3 engineers**, who also maintain, upgrade, and support everything they build."* | Ruthless restraint. Every component is something to patch and be paged for | ADR-001, ADR-004, ADR-005 |
| *"Every tenant is a **team of employees**… you have observability and **organisational recourse**."* | Threat model is **accident, not attack** — so share infrastructure aggressively | ADR-002 |
| *"**People Analytics**… compensation data… their **compliance partner will review** your design."* | The counterweight. Forces least privilege and **evidence** for one dataset | ADR-002, ADR-003 |

The first two point at *share everything and keep it small*. The third pulls the other way. The
interesting parts of this design are where that collision gets resolved.

## The system in one page

**The tenant contract:** *you write your app logic and an `app.yaml`. Everything else is
inherited.*

```text
DEPLOY PATH  -- how a tenant ships
────────────────────────────────────────────────────────────────────────────────
  tenant repo ──push──▶ .github/ci.yml ──calls──▶ insights-platform
   src/                 (4 lines)                  .github/workflows/deploy.yml
   app.yaml                                              │
   .github/ci.yml                                        ├─ validate app.yaml vs schema
                                                         ├─ check datasets vs catalog
                                                         │    (entitlement: declared?)
                                                         ├─ check SDK floor is supported
                                                         ├─ build on platform base image
                                                         └─ register ──▶ control/registry
                                                                              │
                                                                     insights status
                                                                     + status view


RUNTIME PATH  -- how a request is served
────────────────────────────────────────────────────────────────────────────────
  user ──▶ runtime/edge ────────▶ tenant app ──▶ insights_sdk.data.query("hr.headcount")
            strips client          (container)            │
            X-User-* headers                              ├─ catalog:     alias → engine,
            injects validated                             │               env, credentials
            identity                                      ├─ entitlement: declared in app.yaml?
                                                          ├─ scope:       per calling user
                                                          └─ audit ──────▶ runtime/sinks
                                                                                │
  cron ──▶ runtime/scheduler ───▶ tenant job ──▶ (same SDK path) ───────────────┘


  The tenant writes:  src/  +  app.yaml  +  a 4-line CI caller.
  Everything else in both diagrams is inherited.
```

**Four repositories:**

| Repo | Who touches it |
|---|---|
| `insights-sdk` | **Tenants**, as a dependency. Ships the library, the `insights` CLI and the scaffold templates together |
| `insights-platform` | **Platform team only.** `runtime/` · `control/` · `infra/` · the reusable CI workflow · these ADRs · ONBOARDING |
| `insights-headcount-dashboard` | Tenant — interactive web app |
| `insights-comp-report` | Tenant — scheduled job, restricted data |

**Two organising ideas, which most of the design falls out of:**

1. **Declare, don't wire.** The tenant declares *intent* — a dataset alias, a role, a schedule —
   and the platform resolves it to an engine, a credential, an access group, a cron. The tenant
   never writes a connection string or a deployment.
2. **Enforce at the earliest layer that makes a rule impossible to get wrong.** Generator, then
   SDK, then CI, then review, and documentation only as a last resort.

And the ownership line that follows from them: **you own your code, we own the road it travels
on.**

## Decision map — the brief's five questions

*The ADRs are written as decisions, not as answers to these five questions — each one cites the
constraints that forced it, the way an ADR would if there had been no brief. This table and the
one below it are the traceability surface, so nothing is dodged and nothing has to be hunted for.
One ADR does not map to one question: ADR-002 answers isolation **and** the shared-data-connection
requirement, and ADR-001 and ADR-004 together answer deployment.*

| The question | ADR | The call, in one line | The tension resolved |
|---|---|---|---|
| **Reuse mechanism** and the upgrade story with 12 apps depending on it | [ADR-001](adr/ADR-001-reuse-and-upgrade.md) | Versioned SDK in its own repo, floor-not-pin, scaffolds **generated not cloned**; seven upgrade mechanisms with deprecation telemetry as the keystone | Tenant autonomy vs platform upgrade cost — we took the harder upgrade path to keep ownership where it belongs |
| **Isolation** — what's shared, what isn't, and what drew the line | [ADR-002](adr/ADR-002-shared-data-and-isolation.md) | The platform **brokers reads rather than handing out connections**, so the only real boundary is the data path — and the tier follows the *data's* classification, not the tenant. Classification lives in the platform catalog, never the tenant's manifest | Operability vs assurance — "employees + recourse" licenses sharing; compensation data buys back least privilege and evidence |
| **Operator access** — what the platform team can see and do | [ADR-003](adr/ADR-003-operator-access.md) | Telemetry **structurally cannot carry payloads** (raises at emit); zero standing access to rows; break-glass that is time-boxed, dataset-owner-approved, audited and **tenant-notified** | Same tension, with the platform team as the subject — every control makes our own job harder |
| **Enforcement** — where the rules live and how we decided | [ADR-004](adr/ADR-004-enforcement-placement.md) | Earliest layer that makes it impossible to get wrong: generator → SDK → CI → review → docs last | Enforcement strength vs tenant freedom — no escape hatch round the broker, but platform gaps are treated as bugs |
| **Deliberate omissions** and their triggers | [ADR-005](adr/ADR-005-deliberate-omissions.md) | Eleven things not built — portal, micro-frontend shell, policy engine, per-tenant infra, real cloud, multi-env promotion, agents, DR/SLOs, **data discovery**, **per-user passthrough / an HTTP data service**, and **federation to an enterprise data catalog** — each with a written trigger | Completeness vs honesty about who operates this |

## The two flows worth understanding in detail

Everything else in this document is context for these two.

### Identity — why an app outside the edge can read nothing

```text
  browser ──▶ runtime/edge ─────────────────────▶ tenant app
              │                                   │
              │ 1. STRIP every inbound            │ insights_sdk.identity.from_headers()
              │    X-Auth-* header                │   • is the edge token present and correct?
              │    (a client cannot assert        │        no  ──▶ Caller.anonymous()
              │     its own identity)             │                 trusted = False
              │ 2. resolve the session            │        yes ──▶ Caller(subject, groups,
              │ 3. RE-INJECT validated            │                        trusted=True)
              │    X-Auth-User                    │
              │    X-Auth-Groups                  │  Caller.groups is a PROPERTY that returns
              │    X-Auth-Request-Id              │  () unless trusted — so every authorization
              │    X-Auth-Edge-Token              │  check fails closed structurally, with no
              └───────────────────────────────────┘  code anywhere having to remember a flag.
```

A scheduled job has no interactive caller, so the scheduler constructs
`Caller.service("svc:comp-report", groups=<manifest owners>)` — trusted, because the platform and
not a network client built it. Naming that explicitly matters; otherwise "who is the caller at
06:00?" gets answered by accident.

### Data — the connection is shared by being operated for you

The registry has two levels, and the distinction carries most of the design:

| | What it is | Named by tenant code? | Granted to anyone? |
|---|---|---|---|
| **connection** | a shared source the platform operates — one warehouse, one internal REST API | never | **no** |
| **dataset** | a named thing *inside* a connection, with an owner and a classification | yes, in `app.yaml` | yes — the unit of entitlement |

```text
  query("hr.headcount", "SELECT dept, headcount FROM hr.headcount WHERE month = :month", ...)
    │
    1  manifest            this app's app.yaml, cached at startup
    2  ENTITLEMENT         declared in app.yaml?            no ─▶ EntitlementError
    3  IDENTITY            trusted caller?                  no ─▶ IdentityError
    4  RESOLVE             alias ─▶ connection · engine · location(env) · classification · owner
    5  GRANT               restricted? active grant?        no ─▶ EntitlementError
                           …and register its sensitive field names with the logger
    6  REWRITE + SCOPE     alias ─▶ physical table, and reject SQL that reaches for
                           any dataset this app did not declare
    7  EXECUTE             engine adapter, platform-held credential
    8  MASK                fields this caller's roles may not see
    9  AUDIT               who · app · dataset · classification · rows · ms · masked count
    │
    └─▶ list[dict]         never a connection, a cursor or a credential
```

Steps 2, 5, 6, 8 and 9 are only enforceable because there is exactly **one** code path to data.
That is the reason the platform brokers reads instead of handing out connections, and it is the
single decision the rest of the design rests on ([ADR-002](adr/ADR-002-shared-data-and-isolation.md)).

## Where the brief's four shared needs are answered

The brief names four things apps share. None of them is answered only by code.

| Shared need | Mechanism | Decided in |
|---|---|---|
| **authN / authZ** (stub SSO) | Trusted edge strips client-supplied identity headers and re-injects authorizer-validated ones; the SDK's `Caller` is **untrusted** without them and every group check then returns empty, so authorization fails closed. Two layers: platform membership, then `<app>-admin` / `<app>-user` groups derived from the manifest | ADR-004 (placement), ADR-002 (what identity reaches the data) |
| **Shared data connections** — a warehouse and an internal REST API | The platform **brokers the read**; it never hands out a connection. Tenants name a logical dataset, the platform resolves engine, location, credential, classification and owner. Two engines, one enforcement path | **ADR-002** |
| **Deployment** | Four-line CI caller in the tenant repo → one central reusable workflow that validates, checks entitlement, builds on the platform base image and registers the app. Jobs are registered and run by the platform scheduler, not deployed as services | ADR-001, ADR-004 |
| **Observability** | SDK logger auto-stamps app/team/env/request-id/caller/SDK version; **redaction raises at the emit point** rather than being scrubbed in the sink; a separate audit stream records every read | ADR-003 |

## The three calls most worth arguing with

If you have limited time, these are where the design is most exposed and most deliberate.

**1. We broker data instead of sharing connections — and that is the expensive choice.** A shared
connection factory is cheaper to build, and it is what a tenant would prefer. We rejected it
because sharing a connection means sharing a credential, and then nothing stops the headcount
dashboard from selecting salaries. The cost is that the platform team owns every engine adapter
and becomes the queue a blocked tenant waits in. ADR-002 names that as our main scaling risk
rather than hiding it.

**2. Soft isolation is soft, and we say so.** ADR-002 states plainly that apps share a kernel, a
broker and a control plane, and that if the threat model were a hostile tenant this design would
be wrong. We took the brief's "employees and organisational recourse" sentence as the licence.
The restricted tier buys **least privilege and evidence, not a stronger wall** — and pretending
otherwise to a compliance partner would be the real failure.

**3. Multi-repo made our hardest problem harder, on purpose.** A monorepo would make upgrades
trivial. It would also put a 2–3 person platform team in the path of every tenant's code. ADR-001
takes the harder upgrade story and spends the design effort on making it survivable.

*Runner-up: no multi-environment promotion — and ADR-005 admits the trigger has arguably already
fired, because it is "the first tenant whose app affects a decision someone is accountable for",
which is People Analytics, i.e. now. It is next, not never.*

## Reading order

1. This page
2. [ADR-002 Shared data and isolation](adr/ADR-002-shared-data-and-isolation.md) — the central tension, and the decision everything else rests on
3. [ADR-003 Operator access](adr/ADR-003-operator-access.md) — the same tension with us as the subject
4. [ADR-001 Reuse and upgrade](adr/ADR-001-reuse-and-upgrade.md) — the mechanism everything rests on
5. [ADR-004 Enforcement](adr/ADR-004-enforcement-placement.md) · [ADR-005 Omissions](adr/ADR-005-deliberate-omissions.md)

Then [`ONBOARDING.md`](../../ONBOARDING.md) for what all of this looks like to team #6 on day one.
