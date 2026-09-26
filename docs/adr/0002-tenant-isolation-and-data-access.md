# ADR-002 — Tenant isolation and data access: broker the reads, delegate the governance

**Status:** Accepted · **Date:** 2026-09-26
**Drivers from the brief:** *"access to shared data connections (e.g., a warehouse, an internal
REST API)"* · *"every tenant is a team of employees… you have observability into what runs, and
organisational recourse"* · *"their compensation data will be the most sensitive thing the
platform holds, and their compliance partner will review your design before they onboard."*

> The longest ADR in the set, because it is where three of the brief's constraints collide.
> Everything else in the design is downstream of the first decision below.

---

## Context

The brief asks for shared data connections by name, and today every team hand-rolls one: a
connection string in each team's secret store, a copy of a credential per app, and no way to
answer *"who read compensation last month?"* without asking five teams and trusting the answers.

Three facts pull on the replacement, and they do not agree.

| Fact | What it demands |
|---|---|
| The platform team is **2–3 engineers** who also run support | One data path, not one per tenant. Whatever we build, we are paged for |
| Tenants are **teams of employees**, with observability and organisational recourse | Threat model is **accident and casual over-access, not attack** — share aggressively |
| **People Analytics**' compensation data is the most sensitive thing here, and **their compliance partner reviews the design before they onboard** | For that data: least privilege, and **evidence** a sceptical reviewer can read |

Two questions follow, and this ADR answers both:

1. **When a tenant needs data, does the platform give them a connection — or perform the read?**
2. **Who owns the governance model** — who may read which columns, and how that is enforced?

## Decision

### 1. The platform brokers reads. It never hands out a connection.

A tenant declares intent in its manifest and reads through one function:

```yaml
data:
  - dataset: hr.headcount        # a logical name. NOT a table, NOT a connection
    access: read
```

```python
rows = query("hr.headcount", "SELECT dept, headcount FROM hr.headcount WHERE month = :m", m="2026-09")
```

There is no `connect()`, no cursor, no DSN and **no exported way to obtain one** — a test
asserts the shape of the SDK so that adding one fails CI.

Between the call and the rows the broker runs a fixed sequence: load the manifest, check the
dataset is **declared**, check the caller is **trusted**, **resolve** the nickname to a physical
location for this environment, **acquire a short-lived credential**, execute, and **audit**.

**Why this is the hinge:** entitlement, audit and correlation are enforceable only because there
is exactly one code path to data. Hand out a connection and all of them become advisory.

### 2. Unity Catalog owns governance. We do not reimplement it.

**This reverses the obvious instinct**, which is for the platform to own its own classification
and masking rules. An earlier version of this design did exactly that.

| Governance question | Owner |
|---|---|
| Who owns this table? | Unity Catalog object owner (a group) |
| How sensitive is it? | UC tag, e.g. `sensitivity=restricted` |
| Who may read it? | `GRANT SELECT ON TABLE … TO <group>` |
| Which **columns** may this person see? | UC **column mask** |
| Which **rows**? | UC **row filter** |
| Who read what, when? | UC `system.access.audit` |

**Why we gave it up.** A governance model maintained by three engineers *beside* the one the
data platform already enforces is a second source of truth, and second sources of truth drift
silently. Ours would have been enforced only for apps that came through our broker; Unity
Catalog's is enforced for every path to the data, including a notebook. Our masking rules would
have been one more thing a compliance partner has to audit *separately*.

**What we keep** — five things UC does not do, and the reason the platform is not redundant:

| # | Ours | Why UC cannot |
|---|---|---|
| 1 | **The app contract**: `app.yaml` declares which datasets an app uses | UC knows principals, not "apps". We map app → service principal → grant request |
| 2 | **Failing early and legibly**: undeclared dataset errors in CI and at startup | UC fails at query time, in production, with `PERMISSION_DENIED on table x` |
| 3 | **Alias indirection**: `hr.headcount` → `hr_dev.people.headcount` \| `hr_prod.people.headcount` | UC's three-level name *contains* the environment, so portable tenant SQL needs a layer above it |
| 4 | **Identity bridging**: carrying the end user from a browser session into Databricks | The gap between a web session and a warehouse principal is exactly what nobody supplies |
| 5 | **Correlation**: joining "request R by user U in app A" to "Databricks query Q" | UC's audit knows the query and the principal. Only we know the app and the request |

**In one line:** *Unity Catalog owns the data. We own the application platform, and the bridge.*

### 3. The credential story, stated per environment

The sharpest objection to any platform like this is: *if the platform team manages the
credentials, the platform team can read the data.* The answer differs by environment, and
conflating the two is how a design document starts contradicting its own compliance page.

**Locally — a credential exists and the process can read it.** The stub warehouse is a file
whose path is in the app's environment. There is nothing secret in it, but the seam is real:
a local process can read the whole file regardless of what the broker would have allowed.
This is a property of the *stub*, not of the design, and `COMPLIANCE.md` says so in the same
words.

**On the Databricks target — the broker holds no long-lived data credential.** That is the
design below, and it is what a compliance partner is being asked to review.

| | Interactive app | Scheduled job |
|---|---|---|
| Who does UC see? | **the actual person** | the app's service principal |
| How the token is obtained | OAuth token exchange from their session — Databricks federates to the same Entra | **Workload identity federation** from the ECS task role (OIDC) |
| Secret stored anywhere? | **No** | **No** — federation, not a client secret |
| What a platform engineer can read | **nothing — there is nothing to read** | **nothing** |
| Who enforces column and row access | Unity Catalog, per person | Unity Catalog, per principal |

Per-user tokens are the part that matters. Unity Catalog applies *Krishna's* masks to Krishna's
query, so the platform cannot see compensation by impersonating an app — the app holds no
standing credential to impersonate. A platform engineer who genuinely needs tenant rows must
obtain a **UC grant from the data owner**, recorded in UC's audit, which we cannot edit.

The residual, stated plainly: AWS Secrets Manager still holds genuinely external secrets, such
as a third-party API key. Those carry a resource policy granting only the app's task role, and
a KMS key policy that **explicitly denies the platform role**, so we cannot self-serve even
holding admin.

### 4. Two keys for sensitive data

The tenant declares the dataset in its repo (intent). The **data owner** grants it in Unity
Catalog (approval). Neither alone is sufficient: declaring a dataset you have not been granted
fails in CI, where we check UC, and again at query time, where UC refuses.

### 5. There is no data discovery, and that is deliberate

Our registry is an **access registry, not a data catalog**: a nickname, its environment
mapping, and an owner to route a request to. No search, no schema browser, no lineage.

Discovery, when it is wanted, belongs in **Unity Catalog**, which already has search, lineage
and column-level metadata governed by the same grants. Building a second discovery surface in
the app platform would mean storing a description of compensation data's shape for teams that
cannot read it — new exposure, no benefit, and the first thing a compliance partner would ask
us to justify.

### 6. What this draws: the isolation line

Isolation here is almost entirely a question about **data**. Runtime, ALB, CI, base images and
log sink are shared by every tenant and nobody finds that controversial. So the tier follows
the **data's classification, not the tenant's identity** — and the classification lives in a UC
tag, which a tenant cannot edit.

| | Standard | Restricted (UC tag `sensitivity=restricted`) |
|---|---|---|
| Process | own container per app | own container per app |
| Data path | brokered, per-user token | brokered, per-user token **+ dataset-owner grant in UC** |
| Column/row access | UC grants | **+ UC column masks and row filters** |
| Telemetry | redaction enforced at emit | **+ emit-time assertion that no restricted field name appears** |
| Operator access | standing read on platform telemetry | **none to rows** — a UC grant from the owner, audited by UC |

> **Why not tier by tenant:** sensitivity travels with the data, not the team reading it. If
> People Ops gained compensation access tomorrow, tenant-based tiering would give that access
> standard-tier treatment — exactly backwards.

**Shared by everyone:** the VPC, the cluster, the ALB, the broker, the base images, the CI
pipeline, the Databricks workspace.
**Shared by nobody:** their process, their task role, their UC grants, their log group and
dashboard — and their credentials, because they have none.

## The tension

**Operability versus assurance**, and it cuts twice.

This is **soft isolation** and we say so. Apps share a kernel, a cluster and a control plane. If
the threat model were a hostile tenant this design would be wrong, and the answer would be
per-tenant infrastructure — which two to three engineers cannot run for twenty-five tenants. The
brief's sentence about employees and organisational recourse is the licence. **The restricted
tier buys least privilege and evidence, not a stronger wall**, and telling a compliance partner
otherwise would be the real failure.

The second cut is the one that changed our mind: **owning a governance model is a liability, not
an asset.** Writing masking rules in our own YAML was faster, entirely under our control, and
wrong — because it would have been enforced only on our path, drifted from the data platform's
model, and doubled the surface a reviewer has to check. Delegating to Unity Catalog costs us
control and couples us to Databricks. We took that trade deliberately.

## Alternatives considered

### A. Hand out connections — a shared connection factory *(the strongest rejected alternative)*

`get_connection("warehouse")` returns a configured client; the tenant writes whatever SQL it
likes. This is what most people mean by "shared data connections", it is the cheapest thing to
build, and it is what a tenant would *prefer*.

**Why not.** It shares the **credential**, so every app that can reach the warehouse can read
compensation. Entitlement degrades to documentation. The audit answers "an app read something",
not "which app read what, for whom". And the compliance partner's first question — *"what stops
the headcount dashboard from selecting salaries?"* — has no answer except "they wouldn't."

### B. Own the governance model ourselves *(what we built first, and removed)*

Classification, masking rules and grants in our own registry, enforced by our broker. This was
the previous version of this ADR.

**Why not.** Three failures, in increasing order of seriousness. It is enforced **only on our
path** — a notebook against the same table obeys none of it. It is a **second source of truth**
beside Unity Catalog, and it will drift without anyone noticing which is right. And it gives a
compliance reviewer **two models to audit** instead of one, while being the less authoritative
of the two. Fast to build, and a liability by the second year.

### C. Service principal per app, no per-user identity

Every app authenticates to Databricks as itself. Much simpler: no token exchange.

**Why not.** Unity Catalog then sees the app, never the person, so per-user column masks and
row filters cannot apply and the audit answers "comp-report read this" rather than "Krishna did".
For a scheduled job that is correct and it is what we do. For an interactive app it throws away
the main reason to have a governed data platform at all.

### D. A data API service instead of an in-process broker

Same enforcement, behind HTTP: apps call a platform data service rather than importing a library.

**Why not.** It buys one real thing — language independence — at the cost of a network hop, a
service to run and be paged for, and a *second* identity problem (the app authenticating to the
data service). We already control the runtime, so we get the same guarantee in-process.
**Trigger:** the first tenant that is not on our language stack (ADR-005).

### E. Per-tenant infrastructure — separate compute, network and data path per team

The strongest isolation available, and what we would build if tenants were untrusted.

**Why not.** Twenty-five tenants times the cost of a dedicated stack, against a team of two to
three. It would consume the platform team entirely and leave nothing for onboarding, which is
the platform's actual job.

### F. A separate deployment for People Analytics only

Cheap in the short run: one tenant is special, so give that tenant its own everything.

**Why not.** It solves one instance, not the class. The second sensitive dataset — and on an
HR-adjacent platform there will be one — restarts the argument from scratch, and by then there
is a precedent for bespoke arrangements.

### G. No tiering at all

**Why not.** One uniform level is wrong in both directions: set it low and compensation is
under-protected; set it high and every dashboard inherits owner approval, which makes the
platform unusable for the other twenty-four tenants.

## Consequences

**What we now have to do**

* Operate the **bridge**: token exchange for interactive apps, workload identity federation for
  jobs. This is the part with real engineering in it, and the part that breaks in interesting ways.
* Keep the registry a **projection** of Unity Catalog and prove it stays one — a drifted
  projection is worse than no projection, because people trust it.
* Own every engine adapter. A tenant needing a data source we do not support is **blocked on us**,
  and that queue is the platform team's main scaling risk.

**What gets harder**

* We are now **coupled to Databricks** for governance. If the organisation moved data platforms,
  this ADR is void — not adjustable.
* Debugging a permissions problem now spans two systems. "It worked yesterday" can mean a UC
  grant changed, and we don't own that. The error path has to name which system said no.
* The narrow API will not fit something eventually. The escalation is a platform ticket, **not a
  tenant escape hatch**, and the frequency of those tickets is the signal the API is wrong.

**What to watch — and what invalidates this ADR**

* **A tenant that is not a team of employees** — contractors, a joint venture, an acquired
  company. This removes the organisational-recourse premise and the ADR must be reopened rather
  than stretched.
* A broker bug: because the data platform trusts our token exchange, a defect here is a data
  incident, not a 500.
* Honest limitation kept in view: apps share a kernel and a control plane, so a container escape
  is a cross-tenant event. We state that rather than implying otherwise.

**What the compliance partner will ask, and our answer**

*"Who enforces column-level access?"* — Unity Catalog, per person, on every path to the data
including notebooks; not our code. *"Can the platform team read compensation?"* — there is no
standing credential to use; access requires a UC grant from the data owner, recorded in UC's
audit, which we cannot edit. *"Evidence of periodic access review?"* — **not built.** A correct
ask, and it sits in ADR-005's trigger list rather than being quietly omitted.

## Revisit when

* **A tenant is not a team of employees** — the organisational-recourse premise is gone, and
  this ADR must be reopened rather than stretched.
* **The organisation moves off Databricks**, or stands up a second governed data platform. The
  delegation in §2 is the whole design; it does not survive two governance models.
* **"Can the platform add X" becomes a stream rather than a trickle.** The narrow API is then
  wrong, and the answer is alternative D — a data service other languages can reach — not an
  escape hatch.
* **Token exchange becomes the top source of incidents.** The bridge is the riskiest thing we
  own; if it is fragile, per-app service principals (alternative C) plus UC row filters keyed on
  a passed-through user attribute is the fallback, and it is worse but simpler.
* **Someone proposes a third tier.** Two is the maximum this model should carry; a third means
  the tiering dimension itself is wrong.
