# ADR-005 — Deliberate omissions, and the triggers that would reverse them

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

### 5. No containers locally — a single-host process supervisor

`./dev up` is a Python process supervisor: it seeds a SQLite file, starts two stub services
and the tenant apps as plain processes, and puts the edge in front of them. There is no
`compose.yaml`, no local container runtime, and no local registry.

The payoff is the setup instruction: *Python and uv, one command*. A reviewer with fifteen
minutes runs it; a reviewer who first has to install a container runtime does not.

> **Trigger:** the first tenant whose app needs a native dependency the host cannot provide,
> or the first time a local-versus-production difference costs a real debugging session. At
> that point local becomes containers, and the rendered Dockerfile (`insights build`) already
> exists to make that a small change.

### 6. Three environments as a contract; one backed by infrastructure

`dev`, `uat` and `prod` are real in the *contract*: the manifest declares them with their
approvers, the generated workflows promote an artefact by ref between them, and the platform
refuses a production deploy to anyone outside `access.manage.owners`.

What does not exist is three environments' worth of infrastructure. Locally there is one.

This is a deliberate ordering, not an oversight: the promotion *shape* is the part that is
hard to retrofit — once teams have deployed straight to production for a year, adding a gate
is a political problem rather than a technical one. Standing up a second environment behind an
existing contract is a week of infrastructure work.

> **Trigger:** the first sign-off requirement that needs somewhere other than production to
> sign off in. That is People Analytics, i.e. now — which is why this is first on the
> README's "what I'd do next".

### 7. No agents, chat, or LLM features

Out of scope for a platform substrate.

> **Trigger:** a tenant use case that genuinely needs it, at which point it is a *tenant*
> capability first and a platform one only once two or more tenants want the same thing.

### 8. Single-region, no DR, no SLOs

No failover, no formal availability target, no on-call rotation defined.

> **Trigger:** the first tenant whose app is in a business-critical path. Before that, an SLO
> would be a number nobody is accountable for.

### 9. No data discovery in the app platform

No dataset search, no schema browser, no lineage, no sample rows. `insights datasets` tells a
team what it already has, plus the name and owner of what it could request.

The reasoning changed once governance moved to Unity Catalog, and it got stronger. Discovery is
not missing from the *organisation* — UC has search, lineage and column-level metadata, governed
by the same grants that control the data. Building a second discovery surface in the application
platform would mean **storing a description of compensation data's shape for teams that cannot
read it**, in a system with weaker controls than the one that already does this properly.

> **Trigger:** none that leads back to us. If discovery is inadequate, the fix belongs in Unity
> Catalog. The only thing that would change here is `insights datasets` linking out to the UC
> entry for a dataset a team is already entitled to — a convenience, not a catalog.

### 10. No HTTP data service — the broker is an in-process library

The broker only works for tenants on our language stack. A team wanting to build in Go or
TypeScript cannot consume the platform's data path at all.

*(An earlier version of this ADR also listed per-user credential passthrough here. It is no
longer an omission: delegating governance to Unity Catalog means an interactive app exchanges
the signed-in user's session for a short-lived token, so UC sees the actual person. That was
listed as a future trigger and is now the design — see ADR-002 §3.)*

> **Trigger:** the first tenant that is not on our language stack. The answer is alternative D
> in ADR-002 — a data service behind HTTP — and it costs a network hop, a service to be paged
> for, and a second identity problem.

### 11. No machine-to-machine exposure — no API Gateway

Apps are reachable by **people in browsers**, authenticated by the corporate IdP. Nothing here
lets another system, a scheduled process in a different platform, or an agent call an app as a
tool: no API keys, no per-consumer throttling, no usage plans, no mTLS.

This is why the front door is an ALB rather than API Gateway. ALB does browser SSO natively
and carries the websockets Streamlit needs; API Gateway does neither, and its real strengths —
throttling, usage plans, consumer keys — are exactly the things we have no use for **yet**.

> **Trigger:** the first machine-to-machine consumer. API Gateway would then sit in front of
> the same Fargate services rather than replacing the ALB, and the interesting work is not the
> gateway — it is deciding what a non-human caller's identity means for `require_role()` and
> for the Unity Catalog grant it reads under.

### 12. Not on Kubernetes

Apps run on ECS Fargate. No cluster, no node pools, no add-on lifecycle, no CNI, and none of
the Kubernetes policy ecosystem — no OPA/Gatekeeper, no NetworkPolicy, no per-namespace
ResourceQuota.

The honest version of this decision: for two or three engineers who also run support, a
Kubernetes upgrade path is a second job. Fargate has no servers to patch.

> **Trigger, and it has two halves.** Technically: needing workload-level policy-as-data, a
> service mesh, or per-tenant network policy. Organisationally — and this is the one more
> likely to fire — **if the company already operates EKS as a shared service**, the control
> plane is already someone else's job, the cost argument mostly evaporates, and namespaces plus
> NetworkPolicy plus ResourceQuota give real per-tenant isolation primitives we currently
> hand-roll with IAM and security groups. That would be a reason to reopen this, not a reason
> to have started here.

### 13. No real infrastructure as code

`infra/` describes the target architecture; it contains no CloudFormation, CDK or Terraform.
Nothing in this submission can actually be deployed to an AWS account.

This is a time-budget decision rather than a design one, and it is the omission that most
weakens the phrase "production grade". What is *not* missing is the shape: every local fake
has a named production counterpart and a stated seam (ARCHITECTURE §11), so the work is
bounded rather than open.

> **Trigger:** the first real environment. I would write it as CDK in Python — it produces
> CloudFormation, so it fits an organisation whose standard is CloudFormation, it is the same
> language as the platform, and it synthesises and unit-tests locally without an AWS account.

### 14. No CSRF protection

Authentication is cookie-based and same-origin, which is what keeps any token out of the
browser. The trade-off is cross-site request forgery, and the mitigation is currently only
`SameSite=Lax` on the session cookie — there is no CSRF token and no middleware enforcing one.

Nothing here is exposed: both example apps are read-only. The first tenant with a `POST` is.

> **Trigger:** the first state-changing endpoint on the platform. The fix belongs in the SDK's
> web middleware so that no team writes CSRF code and no team can forget to — the same
> argument as redaction and identity.

### 15. No Streamlit shape, though it is the one most wanted

`web.type: streamlit` is **refused** by the manifest loader. Data teams want it, and it is the
natural shape for an exploratory dashboard.

Two things have to exist first, and neither is trivial: Streamlit has no middleware, so
identity needs a shim that reads the edge's headers out of `st.context.headers`; and its own
`/_stcore/health` only proves the process is alive, so the platform's health contract needs a
sidecar. It also holds session state over a websocket, which means sticky sessions and a
replica cap.

Accepting the shape without those would move the failure from `insights doctor` on a laptop to
a deploy in an environment — the wrong layer (ADR-004). Refusing early is the same rule the
platform applies to tenants, applied to itself.

> **Trigger:** the first team that actually asks. It is roughly a day of work, and it is the
> omission most likely to be worth closing first.

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
and the identity bridge in ADR-002, and the operator-access model in ADR-003 — are exactly the
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
