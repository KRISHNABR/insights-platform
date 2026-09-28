# ADR-004 — Enforcement: each rule at the earliest layer that makes it impossible to get wrong

**Status:** Accepted · **Date:** 2026-09-26
**Drivers from the brief:** *"the platform team is 2–3 engineers"* · *"teams vary"* · *"every
tenant is a team of employees… organisational recourse when a team misbehaves."*

---

## Context

A platform is a set of rules about how apps behave. The rules are the easy part; **choosing where
each one is enforced** is the design.

Put everything in review and a two-to-three person team becomes the bottleneck for twenty-five
tenants. Put everything in runtime and you fail in production what you could have failed in CI.
Put it in documentation and it is not a rule at all.

The diagnostic question is: **what does the platform's day-one guide have to warn people about?**

A guide that has to say "remember to set this variable or calls hang forever", "keep this line
above every import or it fails silently", "pick your own port because apps collide", or "install
this separately, the normal command misses it" is not documenting a platform — it is enumerating
that platform's defects and asking tenants to compensate for them. Each of those warnings is a
rule that could have been a default, a generated file, or a startup assertion.

That observation produced the rule below.

## Decision

**A rule is enforced at the earliest layer that can make it impossible to get wrong.**

| Layer | What lives here | Why there |
|---|---|---|
| **Generator / template** | repo layout, the four CI callers, `pyproject.toml`, `.gitignore`, `RUNBOOK.md`, **the Dockerfile** | If it is generated, it starts right. The Dockerfile is the one generated file the tenant then *owns* outright — see below, including what that costs |
| **SDK (runtime)** | credential custody, identity trust, telemetry redaction, and the rule that a connection comes from the manifest or not at all | Must hold even if CI is bypassed, and the failure mode is an accident rather than a policy breach |
| **CI (central reusable workflow)** | manifest schema, the connection-engine check, SDK support window, no secrets, no tracked `.env`, no `:latest`, no root `USER`, tests pass | Must never *ship*. The platform owns the pipeline even though it does not own the code |
| **Human review** | only manifest changes that cross a boundary: a new connection, a change to `access.manage` | The judgement calls — and there are few enough that three people can actually do them. What data an app may read is **not** on this list: that is the data owner's grant in their own system, not something we review |
| **Documentation** | explanation, rationale, worked examples | **Enforcement of last resort.** If a rule only exists in a doc, assume it is not enforced |

Two consequences of that ordering are worth stating explicitly:

**The platform owns the pipeline, not the code.** Tenant repositories call a central reusable
workflow with a four-line caller. That is how the platform retains real control without owning
tenant code — *you own your code, we own the road it travels on.*

**Most rules end up in the generator or the SDK, and that is the goal.** Every rule that has to
live in CI is one a tenant can trip over during development; every rule in documentation is one
they will trip over in production.

### The image is the tenant's, and we publish no base

**This reverses the original decision twice, and the second reversal fixed the first.**

The first design refused a tenant Dockerfile entirely: the platform rendered the image
from a declared `runtime.base`. Three properties were then *constructed* rather than
checked — built on a supported base, runs as non-root, SDK matches the manifest — and
nothing in a tenant repo could take them back, because there was no file to edit.

Teams asked for the image, and the argument was good: a platform that owns the image
owns every `apt-get` line anyone will ever need, and "file a ticket and wait" is not an
answer to a team with a deadline and an unusual native dependency. So `insights new-app`
began generating a Dockerfile the team owns.

That left us in the worst position of the three. We had handed over the file but kept
publishing base images — so the platform still implicitly promised to patch something,
and *could not deliver*, because a fix in a base image reaches an app only when that
app bumps its own `FROM`. A promise we could not keep is worse than no promise.

**So we publish nothing.** A generated Dockerfile is `FROM python:3.12-slim` with uv
copied from its official image. There is no platform base image to be behind.

CI checks exactly two things:

| Rule | Why |
|---|---|
| The base is pinned, not `:latest` | an image you cannot name is one you cannot roll back to, and `latest` means the build is not reproducible |
| The final `USER` is not root | a container breakout should land on a user that owns nothing, and nothing at runtime undoes it |

Everything else in that file is a suggestion. Add build stages, system packages, a
different distro — CI will not stop you.

**What this costs, stated plainly.** Nobody patches tenant base images. A CVE in
`python:3.12-slim` reaches an app when that team rebuilds, and we can tell them but not
do it for them. With platform-rendered images that was one central rebuild.

We accept it because the alternative was *pretending* otherwise. Scanning is where this
gets closed, not ownership: image scanning on every build, and a fleet view of base
image age, are both on the list in
[ADR-005](0005-deliberate-omissions-and-triggers.md).

**It also answers the Python-version question properly.** "We need 3.10 and you support
3.12" is one line: `FROM python:3.10-slim`. Nothing in the platform pins a tenant's
interpreter. The remaining constraint is the SDK's own `requires-python`, which is a
real conversation and not an image problem — see
[ARCHITECTURE §10](../ARCHITECTURE.md#10--upgrades-how-a-platform-change-reaches-a-running-app).

## The tension

**Enforcement strength versus tenant autonomy and platform-team load.**

Stronger enforcement lower in the stack means less tenant freedom. A tenant who needs an
engine the SDK does not ship is blocked by design, and will be annoyed.

**Be precise about what is actually closed here, because it is narrower than it sounds.**
The SDK has no escape hatch: `connect()` takes a *name*, never a host or a credential, so
what an app can reach is declared in `app.yaml` and reviewable in git. The *process* has
one — nothing stops a tenant importing a driver directly and connecting with their own
credential. That is not a leak in this decision; it is the residual risk stated plainly in
[ADR-003](0003-operator-access-and-tenant-data.md), and it is what an in-process library
means. A platform that claimed otherwise would be claiming containment it cannot enforce.

So the control is not "they cannot", it is "they would have to leave the paved road to do
it, visibly, in their own repo." The mitigation is a **response-time commitment**: if
`connect()` cannot do something a tenant needs, that is a platform gap and we treat it as a
bug, not a request to work around. *Tell us rather than working around it — that is a bug on
our side, not a limitation on yours.*

## Alternatives considered

### A. Lint-only — a shared ruleset tenants run locally and in CI

Cheap, familiar, and tenants keep full freedom.

**Why not.** Lint is advisory and bypassable, and it cannot see runtime. It can tell you that a
line *looks* like it logs a dataframe; it cannot stop one being logged. Every control this design
depends on — credential custody, identity trust, redaction — is a runtime property. Lint is a fine
supplement and a poor foundation.

### B. A policy engine such as OPA, with rules as data

Rules become declarative, auditable and independently versioned, and non-developers can in
principle read them.

**Why not, yet.** It introduces a second language, a second toolchain and a second thing to debug
during an incident, in exchange for expressing a ruleset that currently fits on one page. For two
to three engineers that trade is bad today.

*Trigger to revisit, from ADR-005:* rules that must be authored or audited by people who do not
write Python — most likely a security or compliance function wanting to own policy directly.

### C. Mandatory human review of every change

The strongest enforcement, and how many regulated environments actually work.

**Why not.** Two to three engineers reviewing every change from twenty-five tenants is the
definition of a bottleneck, and it makes the platform team the reason things are slow — the exact
complaint the brief opens with. Review also catches only what the reviewer remembers to look for,
which is a weaker guarantee than a check that runs every time. We keep review for the small set
of decisions that genuinely need judgement: manifest changes that cross a boundary.

### D. Convention and documentation only

**Why not.** This is the status quo the brief describes, and the Context section above shows
where it leads: sharp edges written down as warnings because nothing prevented them.
Documentation is where enforcement goes to be ignored.

## Consequences

**What a tenant cannot do**

* Open a connection that is not in `app.yaml` — `connect()` takes a name, and an undeclared
  name fails. They cannot pass a host, a DSN or a credential at the call site.
* Put a credential in the manifest, or name their own service identity.
* Log a record-shaped object.

They *can* import a driver and connect directly with a credential of their own. We do not
pretend otherwise: see the tension above, and ADR-003's residual risk.

**What we now owe them in return**

A **response-time commitment**. If `connect()` cannot do something a tenant legitimately needs,
that is a platform gap and we treat it as a bug, not as a request to work around. Without that
commitment, a strict boundary becomes an obstruction and teams will route around the platform
entirely — which is worse than a weaker boundary.

**What gets harder for us**

* The reusable CI workflow is now on the critical path for every tenant deploy. It must be simple,
  well-tested and fast, and a bug in it blocks everyone. That is a deliberate concentration of
  risk in exchange for a single point of control.
* The generator becomes a maintained product, because anything it emits is something we have
  implicitly promised to keep working — hence `insights upgrade-scaffold` in ADR-001.

**Where this becomes insufficient**

At roughly twenty-five tenants this holds. Past that, two things break first: the manifest-review
queue stops being small enough for three people, and per-tenant exceptions start accumulating in
CI as special cases. Both are signals to move policy into data (alternative B), not to add
reviewers.

**What to watch**

**Rules accumulating in documentation.** Every time we write "remember to…" in a doc instead of
enforcing it, we have lost a little. That count is the health metric for this ADR.

## Revisit when

* **"Remember to…" appears in a document instead of a control.** That count is the health metric
  for this ADR: every instance is a rule that belongs one layer earlier.
* **The manifest-review queue stops fitting three people**, at roughly twenty-five tenants. The
  answer is to move policy into data — alternative B — not to add reviewers.
* **Per-tenant exceptions start accumulating in CI as special cases.** Same signal, arriving from
  the other direction.
