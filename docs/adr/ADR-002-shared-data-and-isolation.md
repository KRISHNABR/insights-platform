# ADR-002 — Shared data connections: a broker, not a connection pool — and the isolation line it draws

**Status:** Accepted · **Date:** 2026-09-26
**Drivers from the brief:** *"access to shared data connections (e.g., a warehouse, an internal
REST API)"* · *"every tenant is a team of employees… you have observability into what runs, and
organisational recourse"* · *"their compensation data will be the most sensitive thing the
platform holds, and their compliance partner will review your design before they onboard."*

> This is the longest ADR in the set, because it is where three of the brief's constraints collide.
> Everything else in the design is downstream of the first decision below.

---

## Context

The brief asks for shared data connections by name:

> *"Apps share common needs. At minimum: … access to shared **data connections** (e.g., a
> warehouse, an internal REST API — stub these with fixtures or fakes)"*

Today each team hand-rolls this. In practice that means a connection string in every team's secret
store, a copy of a credential per app, and no way to answer *"who read compensation data last
month?"* without asking five teams and trusting the answers.

Three facts from the brief pull on the replacement, and they do not agree.

| Fact | What it demands |
|---|---|
| The platform team is **2–3 engineers** who also run support | One data path, not one per tenant. Whatever we build, we are paged for |
| Tenants are **teams of employees**, with observability and organisational recourse | The threat model is **accident and casual over-access, not attack** — share aggressively |
| **People Analytics**' compensation data is the most sensitive thing here, and **their compliance partner reviews the design before they onboard** | For that data: least privilege, and **evidence** a sceptical reviewer can read |

All of which reduces to one question, and this ADR is the answer to it:

**When a tenant needs data, does the platform give them a connection — or does the platform perform
the read on their behalf?**

## Decision

### 1. The platform brokers reads. It never hands out a connection.

This is the hinge. Everything else follows.

A tenant declares *intent* in its manifest:

```yaml
# app.yaml — in the tenant's own repo
data:
  - dataset: hr.headcount        # a logical name. NOT a connection string
    access: read
```

…and reads through one function:

```python
from insights_sdk.data import query

rows = query(
    "hr.headcount",
    "SELECT dept, headcount FROM hr.headcount WHERE month = :month",
    month="2026-09",
)
```

There is no `connect()`, no cursor, no DSN, no engine selection, and **no exported way to obtain
one**. `query()` returns `list[dict]`.

The platform resolves the *mechanism* in a registry the tenant cannot edit: which engine, which
physical location in this environment, which credential, what classification, which group owns it.

Between the call and the rows, the broker runs a fixed sequence:

```text
query("hr.headcount", sql, **params)
  │
  1 load this app's manifest                        (cached at startup)
  2 ENTITLEMENT  is the dataset declared in app.yaml?      else EntitlementError
  3 IDENTITY     is the caller trusted?                    else IdentityError
  4 RESOLVE      alias → engine · physical · classification · owner · credential
  5 GRANT        if restricted: is there an active grant?  else EntitlementError
  6 REWRITE      alias → physical name, so tenant SQL is environment-portable
  7 EXECUTE      via the engine adapter, platform-held credential
  8 SCOPE        apply masking rules for this caller's roles
  9 AUDIT        who · app · dataset · classification · rows · duration
  │
  └─▶ list[dict]      never a connection, a cursor or a credential
```

Steps 2, 5, 8 and 9 are only enforceable **because there is exactly one code path to the data.**
Hand out a connection and every one of them becomes advisory.

### 2. The registry has two levels: connections are shared, datasets are entitled

This distinction carries a lot of the design, so it is worth being precise about.

| | What it is | Who uses it | Granularity of access |
|---|---|---|---|
| **Connection** | A shared data source the platform operates — one warehouse, one internal REST API | The platform only. Tenant code never names one | n/a — nobody is granted a connection |
| **Dataset** | A named thing *inside* a connection, with an owner and a classification | Tenants declare these in `app.yaml` | The unit of entitlement |

So the connection genuinely is shared — that is what the brief asks for — but **it is shared by
being operated on your behalf, not by being handed to you.** Granting a connection would grant
everything reachable through it. Granting a dataset grants one named thing, with an owner who
can say no.

The brief names two kinds of connection. They get different verbs and the same broker:

| Engine | Stubbed as | Tenant API | Used by |
|---|---|---|---|
| `warehouse` | SQLite file + a seed script | `query(dataset, sql, **params)` | both example apps |
| `rest` | ~30-line HTTP service over fixture JSON | `fetch(dataset, resource, **params)` | the web app's directory lookup |

Different verbs because SQL and HTTP genuinely are different, and pretending otherwise produces a
lowest-common-denominator API that is bad at both. **Identical broker:** steps 1–6 and 8–9 are
shared code; only step 7 differs. A third engine is a platform change, not a tenant change, and it
inherits every control for free.

### 3. The credential is the platform's, per app — and the end user's identity does not reach the warehouse

Three models were available:

| | Model | Audit can answer |
|---|---|---|
| a | One shared platform credential for all apps | "something read this" |
| **b** | **Per-app credential, platform-held; caller identity carried in the audit record and in scoping rules** | **"app X read this, on behalf of user Y"** |
| c | Per-user credential exchange — the end user's own identity reaches the engine | "user Y read this", enforced by the engine |

**Chosen: (b).**

(a) collapses the audit trail at exactly the moment it matters. (c) is stronger, and is where a
mature platform ends up — but it requires the data engine to mirror corporate identity (every
employee, every group) and the platform to broker a token exchange per request. That is a
programme, not a feature, and it is the wrong first thing for a team of three.

**What (b) costs, stated plainly:** authorization *inside* a dataset is the platform's job — via
the entitlement check and masking rules — not the warehouse's. If the broker has a bug, the
warehouse will not catch it. That is a single point of failure, and it is why the broker is the
most heavily tested module in the SDK and why it fails closed on every ambiguity.

**Triggers for (c)**, in the order they are likely to fire:

1. **An enterprise data platform with its own identity and grant model arrives.** This is the big
   one, and it dissolves the objection above rather than outweighing it: the reason we rejected
   per-user passthrough is that the engine would have to mirror corporate identity — a governed
   data platform *already does*. At that point (c) stops being a programme and becomes an
   integration, and we should take it.
2. The first dataset where two users of the *same* app must see different rows for a reason we
   cannot express as a masking rule.
3. A compliance requirement that row-level policy be enforced by the data platform itself rather
   than by us.

#### Where the credential actually sits — and the hole that leaves

Worth stating before a reviewer finds it. The broker is an in-process library (alternative C
below), so the credential is injected into **the tenant's own container** and is reachable from
the tenant's own process. A determined tenant could read it out of the environment and open a
connection we never see.

We accept this, for one reason and with one mitigation:

* **The reason** is the threat model the brief handed us. Doing that is not a mistake anyone makes
  by accident — it is a deliberate act by an employee, against a platform with observability and
  organisational recourse. It is a conversation with a manager, not a control failure.
* **The mitigation** is that it is *loud*. Every legitimate read produces an audit record; a read
  through a side channel produces none, while the app's own logs keep flowing. An app that queries
  data it never audits is a detectable pattern, and it is the one alert worth writing early.

**The fix, when the threat model changes:** move the broker into a sidecar in the same pod. The
credential lives in the sidecar, the tenant process talks to it over localhost, and the tenant
never holds it. That buys process isolation without the cost of the platform-wide data service in
alternative C. **Trigger:** any tenant that is not a team of employees, or the first credential
whose misuse would be a reportable event rather than an internal one.

### 4. For restricted data, two keys

The tenant declares the dataset in its repo (intent). The **dataset owner** grants it in the
platform registry (approval). Neither alone is sufficient: declaring a restricted dataset you have
not been granted fails in CI, and fails again at runtime if CI is bypassed.

**Classification lives in the platform catalog and never in `app.yaml`.** A tenant cannot downgrade
the sensitivity of its own data by editing a file in its own repository. This is a ten-line
implementation detail and the single most defensible control in the design.

### 5. There is no data discovery, and that is deliberate

`catalog.yaml` is an **access registry, not a data catalog.** It records what connections exist,
what sits behind them, who owns them, and how sensitive they are — the minimum the broker needs in
order to enforce. It has no search, no schema browser, no lineage, no sample rows, and no
descriptions beyond a single line.

`insights datasets` shows a team what it already has, plus the name and owner of datasets it could
request. **Finding out what data exists is a conversation with a data owner, not a platform
feature.** At five teams — and at twenty-five — that conversation is cheap, and it is also where
the governance actually happens: the owner learns who wants their data and why.

Building discovery would mean the platform stores a description of compensation data's shape for
the benefit of teams that cannot read it. That is new exposure for no benefit, and it would be the
first thing the compliance partner asks us to justify.

**Trigger to revisit:** the dataset count exceeds what an owner can hold in their head (call it
~50), or onboarding is repeatedly blocked on *"who do I even ask?"*. Note that in both cases the
right answer is probably **not** for this platform to build discovery — see below.

### 6. This registry is a projection, and it is shaped to be replaced

`catalog.yaml` holds classification, owner, physical location, masking rules and sensitive field
names — and deliberately nothing else. That is not a minimal-viable-catalog; it is **exactly the
subset that a governed enterprise data platform would publish**, and no more.

We wrote it this way because the end state is not for Insights Hub to own a governance model.
Governance belongs in the data platform. A three-person team maintaining a second, divergent
source of truth for who owns compensation data is a liability, and the day the organisation has a
real catalog, ours should stop being authoritative and start being a cache.

**The migration is one function.** Everything in the broker goes through `catalog.resolve(alias,
env) -> Resolved`. Replacing the YAML with a client against a real catalog changes that call and
nothing else: entitlement, masking, audit, redaction assertions and the two-key grant model all
keep working against whatever `resolve` returns. Keeping that seam narrow is the point of the
design, not an accident of it.

**Why we did not just integrate one now:** the brief gives us a stubbed warehouse and a stubbed
REST API, and no catalog. Building a fake catalog to defer to would produce plumbing and no
decision — and it would dodge the question actually asked, which is where *we* draw the line.
Federating to a real one is in ADR-005's trigger list.

## What this draws: the isolation line

Isolation in this platform is almost entirely a question about **data**. Runtime, edge, CI, base
image, registry and log sink are shared by every tenant and nobody finds that controversial. The
broker is the only place a real boundary has to be drawn — so the tier follows the *data*, not the
tenant.

| | Standard tier (default) | Restricted tier |
|---|---|---|
| Triggered by | everything else | any dataset classified `restricted` in the catalog |
| Process | own container per app | own container per app |
| Data path | shared broker | shared broker **+ dataset-owner grant** |
| Telemetry | redaction enforced at emit | **+ emit-time assertion that no restricted field name appears** |
| Operator access | standing read on platform telemetry | **no standing access to rows** — break-glass only (ADR-003) |
| Approval | app owner | **dataset owner**, separately from the app owner |

**Shared by everyone:** the runtime, the edge, the broker, the registry, the log sink, the CI
pipeline, the base image.
**Shared by nobody:** their process, their data scope, their app's access groups — and their
credentials, because they have none.

## The tension

**Operability versus assurance**, and it cuts twice.

This is **soft isolation** and we say so. Apps share a kernel, a broker and a control plane. If the
threat model were a hostile tenant, this design would be wrong and the answer would be per-tenant
infrastructure — which two to three engineers cannot run for twenty-five tenants. The brief's
sentence about employees and organisational recourse is the licence. **The restricted tier buys
least privilege and evidence, not a stronger wall** — and telling a compliance partner otherwise
would be the real failure.

The second cut is newer and sharper: **the platform now holds every credential.** A platform
engineer with production deployment access can reach one. ADR-003's zero-standing-access model
constrains the *supported* path, not physics. What we can honestly claim is that there is exactly
one audited path to data and that reaching any other path requires actions that are themselves
visible. What we cannot claim is that it is impossible. We chose the claim we can defend.

## Alternatives considered

### A. Hand out connections — a shared connection factory *(the strongest rejected alternative)*

`get_connection("warehouse")` returns a configured client; the tenant writes whatever SQL it
likes. This is what most people mean by "shared data connections", it is the cheapest thing to
build, and it is what a tenant would *prefer*.

**Why not.** It shares the **credential**, so every app that can reach the warehouse can read
compensation data. Entitlement degrades to documentation. The audit answers "an app read
something", not "which app read what". Masking becomes impossible because there is no chokepoint
to apply it at. And the compliance partner's first question — *"what stops the headcount dashboard
from selecting salaries?"* — has no answer except "they wouldn't."

Rejecting this is the decision the rest of the design rests on, which is also why `ONBOARDING.md`
has to earn its keep: the narrow API must feel like a service, not a restriction.

### B. Per-user credential passthrough

The end user's identity reaches the data engine; the engine enforces row-level policy.

**Why not (yet).** Strongest model and the right end state. It needs the warehouse to mirror
corporate identity and a token exchange on every request — a programme, not a feature. Trigger
named in §3.

### C. A data API service instead of an in-process broker

Same enforcement, but behind HTTP: apps call a platform data service rather than importing a
library.

**Why not.** It buys one real thing — language independence — at the cost of a network hop, a
service to run and be paged for, and a *second* identity problem (the app authenticating to the
data service). We already control the runtime, so we get the same guarantee in-process for free.
**Trigger:** the first tenant that is not on our language stack. ADR-005 carries this.

### D. Per-tenant infrastructure — separate compute, network and data path per team

The strongest isolation available, and what we would build if tenants were untrusted.

**Why not.** Twenty-five tenants times the cost of a dedicated stack, against a team of two to
three. It would consume the platform team entirely and leave nothing for onboarding, which is the
platform's actual job.

### E. A separate deployment for People Analytics only

Cheap in the short run: one tenant is special, so give that tenant its own everything.

**Why not.** It solves one instance, not the class. The second sensitive dataset — and on an
HR-adjacent platform there will be one — restarts the argument from scratch, and by then there is
a precedent for bespoke arrangements. Tiering by classification generalises: the next restricted
dataset gets the right treatment with no negotiation.

### F. Tier by tenant rather than by dataset

**Why not.** Sensitivity travels with the data, not with the team reading it. If People Ops were
granted `hr.compensation` tomorrow, tenant-based tiering would give that access standard-tier
treatment — exactly backwards.

### G. No tiering at all

**Why not.** One uniform level is wrong in both directions: set it low and compensation is
under-protected; set it high and every dashboard inherits owner approval and break-glass, which
makes the platform unusable for the other twenty-four tenants.

## Consequences

**What we now have to do**

* Treat `catalog.yaml` as a **control surface**, not configuration: its own review path, because
  classification is a security decision expressed as YAML.
* Enforce in CI that a manifest can never declare or override classification.
* Build the dataset-owner grant path — a second approver is a workflow, not a flag.
* Own every engine adapter. A tenant that needs a data source we do not support is **blocked on
  us**, and that queue is the platform team's main scaling risk.

**What gets harder**

* The narrow API will not fit something, and the first time it does not, the tenant's options are
  a platform change or nothing. We keep that deliberate: the escalation path is a platform ticket,
  **not a tenant escape hatch**, and the frequency of those tickets is the signal that the API is
  wrong.
* Adding a restricted dataset now costs an approval path, redaction assertions and break-glass.
  That friction is the point, but it is friction.
* Two tiers is the maximum this design should carry. A third means the model is wrong.

**What to watch — and what invalidates this ADR**

* **A tenant that is not a team of employees** — contractors, a joint venture, an acquired company
  under a separate legal entity. Any of these removes the organisational-recourse premise, and
  this ADR must be reopened rather than stretched.
* A regulatory obligation naming physical or network separation.
* A broker bug: because the warehouse trusts us, a defect here is a data incident, not a 500.
* Honest limitation kept in view: apps share a kernel and a control plane, so a container escape
  is a cross-tenant event. We state that rather than implying otherwise.

**What the compliance partner will still ask for, and our answer**

Row-level access control enforced inside the warehouse (§3 alternative B), and evidence of
periodic access review. Neither is built. Both are correct asks, and both sit in ADR-005's trigger
list rather than being quietly omitted. What we *can* hand them today is
`insights compliance-report --dataset hr.compensation`: who is entitled, who granted it, every
read in the period, and every break-glass event.

## Revisit when

* **A tenant is not a team of employees** — a contractor team, a joint venture, an acquired
  company under a separate legal entity. This removes the organisational-recourse premise the
  whole ADR rests on, and it must be reopened rather than stretched.
* **A governed enterprise data platform arrives.** Our registry should stop being authoritative
  and become a cache (§6), and per-user passthrough stops being a programme (§3).
* **"Can the platform add X" becomes a stream rather than a trickle.** The narrow API is then
  wrong, and the answer is alternative C — a data service other languages can reach — not an
  escape hatch.
* **Someone proposes a third tier.** Two is the maximum this model should carry; a third means
  the tiering dimension itself is wrong.
* A regulatory obligation names physical or network separation.
