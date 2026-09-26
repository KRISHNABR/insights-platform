# ADR-003 — Operator access to tenant data: none standing, and redaction that raises at the emit point

**Status:** Accepted · **Date:** 2026-09-26
**Drivers from the brief:** *"their compliance partner will review your design before they
onboard"* · *"you have observability into what runs"* · *"the platform team is 2–3 engineers, who
also maintain, upgrade, and support everything they build."*

---

## Context

Three engineers have to operate everything: diagnose a failing scheduled job, explain a slow
dashboard, answer "did it run?". That needs real telemetry.

The same three engineers must not be able to casually read compensation rows — and, crucially,
must be able to **demonstrate** that they cannot, to a compliance partner who will not accept
"we wouldn't do that."

The naive failure mode is well known and almost universal: an engineer debugging a data problem
logs the dataframe. Now sensitive rows are in the log sink, which has looser access than the
warehouse, longer retention than anyone intended, and is searchable by everyone on the platform
team. **The data leaked through the observability system, not through the data system.**

## Decision

**Three controls, in descending order of how much they matter.**

### 1. Telemetry is structurally incapable of carrying tenant payloads

The SDK logger accepts identifiers, counts, durations and status — and **raises** if handed a
`DataFrame`, a `dict` that looks like a record, or a list of records. Not a lint warning, not a
convention: an exception, at the emit point, at runtime.

This is deliberately placed in the SDK rather than in CI, because it must hold even when CI is
bypassed, and because the failure it prevents is an accident by a well-meaning engineer at 2am.

For datasets classified `restricted`, the SDK additionally asserts that no field name from that
dataset's schema appears in any log record.

### 2. No standing access to tenant data

The platform team has **standing read access to platform telemetry** — logs, metrics, run
history, the registry — and **no standing access to the rows inside any tenant dataset.**

They are different systems with different grants, and that separation is the whole point: the
thing needed daily is available, the thing needed rarely is not.

### 3. Break-glass, with evidence

When an operator genuinely needs to see tenant data, the path is:

| Property | How |
|---|---|
| **Granted** | Explicit request naming the dataset and the reason |
| **Approved** | By the **dataset owner** (not the platform team) — for restricted data, a second approver |
| **Constrained** | Time-boxed and auto-expiring; scoped to one dataset; read-only |
| **Evidenced** | An immutable audit record, and the tenant is **notified**, not merely logged |

The tenant notification is the part that makes it real. An audit log nobody reads is not
evidence; a message that arrives in the owning team's channel is.

## The tension

**Operability versus assurance, again — but sharper, because here the platform team is the
subject.**

Every control above makes the platform team's job harder. Not being able to log a dataframe
makes debugging a data-shape bug genuinely slower. Break-glass adds minutes to an incident.

We accepted that, for one reason: **the compliance partner reviews this design before People
Analytics onboards.** A platform that cannot answer "what can your engineers see?" with something
better than a policy statement does not get that tenant — and a platform that never gets its
most sensitive tenant has not proven anything.

The honest caveat, which belongs in front of the compliance partner rather than buried: an
operator with break-glass and an operator with standing access can see the same rows. The
difference is **friction, expiry and evidence**, not capability. We are not claiming otherwise.

## Alternatives considered

### A. Redact in the log sink rather than at the emit point

Filter sensitive fields centrally as records arrive, so tenants need no discipline at all.

**Why not.** By the time the sink sees it, the data has already left the process, crossed the
network and been written somewhere. More importantly, sink-side filtering **fails open**: it can
only redact patterns it recognises, so an unexpected field name, a nested structure or a
free-text blob passes straight through. Emit-time type checking **fails closed** — the SDK does
not need to know what the fields mean, only that a record-shaped object is not a log message.

*We would add sink-side redaction as well*, as defence in depth — never instead.

### B. Full standing access, with after-the-fact audit

The operationally easiest option, and very common.

**Why not.** An audit log that nobody reads is not a control, it is a record of what already
happened. And it fails the specific test this design has to pass: a compliance partner reviewing
before People Analytics onboards will ask what prevents access, not what records it.

### C. No operator access to tenant data under any circumstances

Superficially the strongest position.

**Why not.** Three engineers cannot operate a platform blind. It pushes every data-shaped
incident back onto the tenant, which defeats the purpose of having a platform, and in practice it
gets circumvented — someone gets a warehouse credential by another route and now the access is
real but invisible. A break-glass path that is used and recorded is safer than a prohibition that
is quietly worked around.

### D. Synthetic or sampled data for debugging

Give operators a scrubbed copy so real access is rarely needed. Genuinely good, and the right
long-term answer.

**Why not now.** It is a pipeline to build, validate and keep in sync with schema changes —
meaningful engineering for a team this size. Deferred with a trigger in ADR-005 rather than
dismissed.

## Consequences

**What we now have to do**

* Build break-glass properly: request, dataset-owner approval, expiry, audit record, and tenant
  notification. The notification is what makes it a control rather than paperwork.
* Maintain per-dataset schema knowledge in the SDK so the restricted-tier field-name assertion
  can work.
* Define what happens when an approver is unavailable — see below.

**What gets harder**

* Debugging a data-shape bug is genuinely slower. An engineer who would have logged the
  dataframe now has to reason from schema, counts and a sample they cannot see.
* The logger is on the hot path and now does a type check on every call.
* Incident response gains minutes at exactly the moment they are expensive.

**The gap we are accepting, explicitly**

If the dataset owner is unreachable during an incident, break-glass stalls. We chose **not** to
build an emergency override, because an override that exists will be used routinely and the
control becomes decorative. The fallback is organisational: escalate to the owning team's
management chain. That is slower, and it is a deliberate choice rather than an oversight.

**What to watch**

* **Break-glass frequency.** If it becomes routine, one of two things is true: the telemetry is
  inadequate for operating the platform, or the control is theatre. Either way it means redesign,
  not tolerance.
* Attempts to log payloads, caught by the SDK. A rising count means the documentation or the
  ergonomics are wrong.

## What is actually built, and what is not

`insights compliance-report` renders break-glass events, which could reasonably be read as
"break-glass works". Being precise, because the difference matters to a reviewer:

| | Status |
|---|---|
| Redaction raising at the emit point | **built** — `telemetry.py`, and `tests/test_telemetry_boundary.py` |
| Per-dataset sensitive-field assertion, armed when the broker resolves a restricted dataset | **built** — the field list comes from the catalog, so a tenant cannot shorten it |
| Every read audited with caller, sensitivity and masked-field count | **built** — `telemetry.audit_read`, written to `runtime/sinks/audit.jsonl`. In production this is the *correlation* record; Unity Catalog's `system.access.audit` is the authoritative one |
| Zero standing operator access | **built, structurally** — the platform team holds no grants, and the broker's only path to data requires one |
| The break-glass **data model** — expiry, second approver, tenant notification, usage count | **built** — `control/registry/grants.yaml`, and the report reads it |
| A break-glass **workflow** | **not built.** With the broker gone the platform holds no grant to break; operator access to a tenant's data is now a request to that team's data owner, in their own system |

The workflow was the first thing cut when time ran short, and it was the right cut: a fake
implementation would have looked more finished and been worth less than an honest schema plus
this paragraph. What it costs today is that an operator needing emergency access has to have an
owner hand-edit `grants.yaml` — which is auditable, and slow, and exactly the friction the
control is supposed to create. It is the first thing to build after the items in the README's
"what I'd do next".

## Revisit when

* **Break-glass becomes routine.** One of two things is then true: the telemetry is inadequate
  for operating the platform, or the control is theatre. Either way it means redesign, not
  tolerance.
* **Misuse of a platform-held credential would be a reportable event rather than an internal
  one.** That is the trigger to move the broker into a sidecar, so the tenant process stops
  holding the credential at all.
* **Attempts to log payloads stop declining.** The SDK catches them, so they are never incidents
  — but a flat or rising count means the ergonomics or the documentation are wrong, not that
  people are careless.
* An approver being unreachable stalls a real incident more than once. The accepted gap has then
  stopped being theoretical, and the answer is more approvers, not an override.
