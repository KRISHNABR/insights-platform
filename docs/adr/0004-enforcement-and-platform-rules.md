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
| **Generator / template** | repo layout, the four CI callers, `pyproject.toml`, `.gitignore`, **the Dockerfile** | If it is generated, it starts right. The Dockerfile is the one generated file the tenant then *owns* — see "The image is the tenant's" below, including what that costs |
| **SDK (runtime)** | credential handling, per-user data scoping, telemetry redaction, identity trust, dataset entitlement | Must hold even if CI is bypassed, and the failure mode is an accident rather than a policy breach |
| **CI (central reusable workflow)** | manifest schema, dataset entitlement vs catalog, SDK version floor, no secrets, no `:latest`, tests pass | Must never *ship*. The platform owns the pipeline even though it does not own the code |
| **Human review** | only manifest changes that cross a boundary: a new dataset, a new role, a change to `access.manage` | The judgement calls — and there are few enough that three people can actually do them. Sensitivity is **not** on this list: it is a Unity Catalog tag the data owner sets, not something we review |
| **Documentation** | explanation, rationale, worked examples | **Enforcement of last resort.** If a rule only exists in a doc, assume it is not enforced |

Two consequences of that ordering are worth stating explicitly:

**The platform owns the pipeline, not the code.** Tenant repositories call a central reusable
workflow with a four-line caller. That is how the platform retains real control without owning
tenant code — *you own your code, we own the road it travels on.*

**Most rules end up in the generator or the SDK, and that is the goal.** Every rule that has to
live in CI is one a tenant can trip over during development; every rule in documentation is one
they will trip over in production.

### The image is the tenant's — and what that costs

**This reverses the original decision, deliberately.** The first design refused a tenant
Dockerfile outright: `runtime.base` was declared in `app.yaml` and the platform rendered and
built the image. That put three properties in the strongest possible layer — *built on a
supported base*, *runs as non-root*, and *the SDK matches the manifest* were *constructed*, not
checked. Nothing in a tenant repo could take them back because there was no file to edit.

Teams asked for the image, and the argument for giving it to them is real: a platform that owns
the image owns every `apt-get` line anyone will ever need, and "file a ticket and wait" is not
an answer to a team with a deadline and an unusual native dependency. `uv` already owns the
Python dependency layer, so what is left in the base is thin — an OS, an interpreter, a user id
and an entrypoint.

So: **`insights new-app` generates a Dockerfile, and from that moment it belongs to the repo.**
`insights upgrade-scaffold` does not touch it, because re-rendering it would silently discard
the edits that were the whole point.

Four properties move from *constructed* to *checked*, in CI and in `insights doctor`:

| Rule | Why |
|---|---|
| Every `FROM` is a published `insights-hub/*` base | Those are the images we patch. A stage `FROM docker.io` is one nobody here is patching |
| No `:latest`, every base pinned | An image you cannot name is one you cannot roll back to |
| The final `USER` is not root | The base already sets `USER insights`, so a file with no `USER` line is correct. Install as root if you must; switch back |
| The pinned base version is current | See below |

**Be honest about the last one, because it is the price.** A check is weaker than a
construction: it has to be right, and it has to run. Three of the four above are genuinely
enforceable — a repo cannot ship past them. The fourth cannot be enforced *away*: when a CVE
lands in `python:3.12-slim`, the platform rebuilds the base, and that fix reaches an app **only
when that app bumps its own `FROM` line.** We can fail their pipeline; we cannot patch their
image. With platform-rendered images that was one central rebuild and zero tenant action.

We accept that, and we pay for it with noise rather than silence: `insights doctor` reports a
stale base locally, the deploy gate fails on it, and `insights status` will show fleet-wide base
drift. The failure mode we are guarding against is not a team refusing to upgrade — it is a team
**not knowing** they are behind.

> **Revisit if** base drift stops being a number someone looks at. The moment "how many apps are
> on a base older than N?" has no owner, this reversal has quietly cost us the thing it traded
> away, and platform-rendered images come back.

## The tension

**Enforcement strength versus tenant autonomy and platform-team load.**

Stronger enforcement lower in the stack means less tenant freedom. A tenant who needs a data
client the SDK does not provide is blocked by design, and will be annoyed. We accepted that,
because the alternative — an escape hatch around the broker — silently voids per-user scoping,
entitlement and audit, which are the three things the whole design rests on.

The mitigation is not an escape hatch but a **response-time commitment**: if `query()` cannot do
something a tenant needs, that is a platform gap and we treat it as a bug, not a request to work
around. The message to tenants is explicit: *if `query()` cannot do something you need, tell us
rather than working around it — that is a bug on our side, not a limitation on yours.*

## Alternatives considered

### A. Lint-only — a shared ruleset tenants run locally and in CI

Cheap, familiar, and tenants keep full freedom.

**Why not.** Lint is advisory and bypassable, and it cannot see runtime. It can tell you that a
line *looks* like it logs a dataframe; it cannot stop one being logged. Every control this design
depends on — per-user scoping, entitlement, redaction — is a runtime property. Lint is a fine
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

* Build their own database client, or reach a data source around `query()`. There is no escape
  hatch, by design — going around the broker voids per-user scoping, entitlement and audit in one
  step.
* Access a dataset they have not declared in `app.yaml`, even if they know its name.
* Log a record-shaped object.

**What we now owe them in return**

A **response-time commitment**. If `query()` cannot do something a tenant legitimately needs,
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
