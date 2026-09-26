# ADR-005 — What we deliberately did not build, and what would trigger building it

**Status:** Accepted · **Date:** 2026-09-26
**Drivers from the brief:** *"the platform team is 2–3 engineers, who also maintain, upgrade, and
support everything they build"* · *"we score prioritization, not endurance."*

---

## Context

The binding constraint on this platform is not technology. It is that **two to three engineers
must build, operate, upgrade and support everything here, while onboarding up to twenty-five
tenants.** Every component added is a component to patch, debug and be paged for.

So the omissions below are not a backlog of things we ran out of time for. They are positions,
each with a stated trigger, so that a future engineer can tell whether the situation that
justified the decision still holds.

## Decision

### 1. No self-service web portal

The obvious shape of a platform like this is a portal: create an app, see your apps, manage
access, view runs. We built a **read-only status view** and a CLI instead.

A portal is a frontend, an API behind it, auth on it, its own deployment, its own upgrades and
its own on-call. Every mature internal platform has one — and **every one of them is run by far
more than three engineers.** The portal is not the hard part; operating it for years while also
onboarding tenants is.

> **Trigger:** non-engineer tenants need to self-serve app creation, **or** onboarding volume
> exceeds roughly one team per fortnight, **or** access-request handling becomes a meaningful
> share of the platform team's week.

### 2. No micro-frontend shell

The destination for a platform hosting many interactive apps is a shell that loads tenant UIs at
runtime — Module Federation or equivalent — so tenants ship panels rather than whole
applications, rather than whole front-ends.

It is also a frontend build-and-release system, with version-skew failure modes that appear at
runtime rather than build time.

> **Trigger:** more than about five interactive tenants, **and** a demand for a single navigable
> surface rather than separate URLs.

### 3. No policy engine

Enforcement is Python in the SDK and steps in the CI workflow (ADR-004), not OPA or similar.

At this rule count, a policy engine is a second language, a second toolchain and a second thing
to debug at 2am — for rules that fit on one page.

> **Trigger:** rules that must be authored or audited by people who do not write Python — most
> likely a security or compliance function wanting to own policy directly.

### 4. No per-tenant infrastructure

Every tenant shares the runtime, the broker and the control plane (ADR-002).

> **Trigger:** a tenant that is **not** a team of employees — a contractor, a joint venture, an
> acquired company — which invalidates the "organisational recourse" premise the whole isolation
> model rests on. Also: a regulatory obligation naming physical separation.

### 5. No real cloud infrastructure — stubs and fakes throughout

Sanctioned by the brief. `infra/` describes the target state (ECS Fargate behind a shared ALB,
EventBridge for schedules, an identity edge) without provisioning it. Local runtime is
`compose.yaml`.

> **Trigger:** n/a for this exercise. In reality the first production tenant.

### 6. No multi-environment promotion

One environment. No dev → UAT → prod path, no promotion gates.

> **Trigger:** the first tenant whose app affects a decision someone is accountable for — which,
> notably, is People Analytics. **This is the omission most likely to be challenged**, and the
> honest answer is that it is next, not never.

### 7. No agents, chat, or LLM features

Out of scope for a platform substrate.

> **Trigger:** a tenant use case that genuinely needs it, at which point it is a *tenant*
> capability first and a platform one only once two or more tenants want the same thing.

### 8. Single-region, no DR, no SLOs

No failover, no formal availability target, no on-call rotation defined.

> **Trigger:** the first tenant whose app is in a business-critical path. Before that, an SLO
> would be a number nobody is accountable for.

### 9. No data discovery — the catalog is an access registry, not a data catalog

No dataset search, no schema browser, no lineage, no sample rows, no column descriptions.
`insights datasets` tells a team what it already has, plus the name and owner of what it could
request. Finding out what data exists is a conversation with a data owner.

This one is omitted on principle as much as on budget: a discovery surface would mean the platform
storing a description of compensation data's shape **for the benefit of teams that cannot read
it** — new exposure, no benefit, and the first thing the compliance partner would ask us to
justify. It also removes the governance moment where an owner learns who wants their data and why.

> **Trigger:** the dataset count exceeds what an owner can hold in their head — call it ~50 — or
> onboarding is repeatedly blocked on *"who do I even ask?"*. Either is a real signal; neither has
> happened at five teams.

### 10. No per-user credential passthrough to the data engine, and no data API over HTTP

Two related things the broker does not do, both argued in ADR-002 §3 and alternative C.

The end user's identity reaches the **audit record**, not the warehouse; row-level policy is
enforced by the platform's masking rules rather than by the engine. And the broker is an
in-process library, not an HTTP service, so it only works for tenants on our language stack.

> **Trigger (passthrough):** the first dataset where two users of the *same* app must see
> different rows for a reason we cannot express as a masking rule — or a compliance requirement
> that row-level policy be enforced by the data platform itself rather than by us.
> **Trigger (data service):** the first tenant that is not on our language stack. Note these two
> triggers point at the same rebuild, so if both look likely, do them together.

### 11. No federation to an enterprise data catalog — but the seam is cut for it

Our registry is authoritative today. In the end state it should not be: classification, ownership
and grants belong to whatever governed data platform the organisation runs, and a three-person
team maintaining a second, divergent source of truth for who owns compensation data is a
liability, not a feature.

This is the omission we are *least* attached to. `catalog.yaml` deliberately holds only the subset
such a platform would publish, and every lookup goes through one function, so the change is
`resolve()` and nothing else (ADR-002 §6).

Not built here because the brief gives us a stubbed warehouse and a stubbed REST API and no
catalog — building a fake one to defer to would be plumbing with no decision in it, and would
dodge the question actually asked.

> **Trigger:** the organisation stands up a governed data platform with its own identity and grant
> model. When that happens, do this **first** — before per-user passthrough (omission 10), because
> it is what makes passthrough cheap rather than a programme.

## The tension

**Completeness versus honesty about who operates this.**

Every omission above would make the platform better on paper and worse in practice, because the
team that has to run it is three people. The failure mode we designed against is not a missing
feature — it is a platform with twelve components, three engineers, and no time left to onboard
anyone.

The one that would most change the shape of the system is **multi-environment promotion**, and
if the budget were fourteen hours rather than twelve, it is what we would have built next.

## Alternatives considered

### A. Build the portal, cut the SDK

Invert the priorities: give tenants a polished self-service surface and let them write their own
auth, data and logging against documented APIs.

**Why not.** It optimises for the demo rather than the problem. The brief's complaint is that
*"every team currently hand-rolls the same things"* — a portal that creates a repo does not stop
that; a library that already contains the behaviour does. It would also make every control in
ADR-003 and ADR-004 unenforceable, because there would be no shared code path to enforce them in.

### B. Buy rather than build

Use an existing internal developer platform — Backstage, or a managed PaaS — instead of writing
one.

**Why not, here.** Genuinely the right question to ask in reality, and for a real organisation
this deserves a serious evaluation before writing any code. We build in this exercise because the
brief asks us to design a substrate, and because the distinctive requirements — the data-broker
and classification model in ADR-002, and the operator-access model in ADR-003 — are exactly the
parts an off-the-shelf platform would not give us. A realistic hybrid is worth naming: buy the
scaffolding and catalogue, build the data and access layer.

### C. A thinner substrate with more tenant freedom

Ship utilities rather than an opinionated framework; let teams assemble what they need.

**Why not.** Flexibility is what makes governance impossible. With a compliance partner reviewing
before the most sensitive tenant onboards, "each team does it their own way" is not a position we
can defend. The cost is real — some tenant will want something the substrate does not offer —
and ADR-004's response-time commitment is how we pay it.

## Consequences

**What a tenant lives with today**

* A CLI and a read-only status view, no graphical self-service.
* One environment. No promotion path, so "test in production" is the literal situation.
* No chat, no agents, no bring-your-own-widget.
* Access requests go through the app owner and, for restricted data, the dataset owner —
  by hand.

**What the compliance partner will push back on, and where each is handled**

| Their likely challenge | Where it lands |
|---|---|
| "No separate production environment?" | Omission 6 — acknowledged as next, not never |
| "Row-level security in the warehouse?" | ADR-002 consequences — not built, correct ask |
| "Evidence of periodic access review?" | Not built. Would be the first thing added alongside promotion |
| "Shared kernel across tenants?" | ADR-002 — stated plainly, licensed by the employee/recourse premise |

**The order we would build these in, and why**

1. **Multi-environment promotion** — the trigger has arguably already fired, and everything else
   is harder to justify while "deploy" and "production" are the same word.
2. **Periodic access review + evidence export** — cheap, and it is what converts ADR-003 from a
   design into something auditable.
3. **The portal** — only once onboarding volume or non-engineer tenants make it pay for itself.
4. Everything else, on its stated trigger.

**The risk in this ADR**

Omissions justified by team size age badly. If the platform team grows to six and these are still
absent, the reason will have quietly become inertia rather than judgement. Each trigger above is
written to be checkable for exactly that reason — they are falsifiable claims, not preferences.

## Revisit when

Each omission above carries its own trigger. This ADR **as a whole** should be reopened when:

* **The platform team grows past three people.** Almost every omission here is justified by who
  has to operate it. That justification ages badly and quietly, and nobody is assigned to notice.
* **Tenant count passes roughly twelve.** Several of these decisions were sized for five teams
  and argued as safe up to twenty-five. Twelve is where the assumption should be re-tested rather
  than assumed to still hold.
* **Two or more triggers fire in the same quarter.** That is a signal the environment has moved,
  not that individual omissions were wrong — and the right response is to re-argue the set, not
  to work through them one at a time.
