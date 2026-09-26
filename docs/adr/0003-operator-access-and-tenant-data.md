# ADR-003 — What the platform team can see, and what it cannot

**Status:** accepted · rewritten when the data broker was removed ([ADR-002](0002-tenant-isolation-and-data-access.md))
**Decision owner:** platform team

---

## Context

The brief asks it directly: *what can the platform team itself see and do — in
telemetry and in tenant data — and how is that access granted, constrained and
evidenced?*

It is the right question to ask a platform team, and the honest answer got **smaller**
when the broker was removed. An earlier version of this ADR described a break-glass
workflow: time-boxed operator grants on a dataset, approved by the data owner,
recorded in `grants.yaml`. That machinery existed because the platform sat in the data
path and held grants of its own.

It does not any more. The platform ships connectors; teams connect to systems they
already have access to. So the platform holds no dataset grants, and there is nothing
for an operator to break glass *on*.

Three people still have to operate the thing, though. They need to answer "is it
broken, and whose fault is it" at 3am without that being a licence to read anybody's
data.

---

## Decision

### 1. Standing access to telemetry. None to tenant data.

The split works because of what a telemetry record **contains**:

```json
{"event": "query_executed", "app": "comp-report", "caller": "sp-comp-report",
 "connection": "hr-warehouse", "engine": "sqlite", "ms": 2, "rows": 4}
```

Caller, app, connection, engine, duration, row count. **No payload, by construction** —
the logger raises at the point of writing on anything that is not a scalar, and on any
string long enough to be a payload in disguise.

So the whole telemetry stream can be readable by anyone operating the platform without
that being access to tenant data. **We see that a query happened. We never see what it
returned.** Not the SQL either: SQL names tables and columns and often carries a
literal in a `WHERE`, so a platform-wide log of tenant SQL is a data inventory nobody
consented to.

### 2. The platform team cannot read a tenant's credential

This is the one that would otherwise undo everything above — a credential is a key to
all the data behind it.

```
secret store        insights/<app>/<secret>
writes the value    the app's owning group
reads the value     sp-<app>, on its own prefix only
CANNOT read it      the platform team — an explicit IAM Deny on insights/*
sees every read     CloudTrail, including ours
```

**Custody is a property of the thing issuing credentials, not of us choosing not to
call `GetSecretValue`.** An explicit `Deny` cannot be overridden by any `Allow`, so it
survives somebody later granting the platform role broad access by accident — which is
how this kind of control usually fails.

Locally the same rule holds in a smaller way: secrets are in each tenant's own `.env`,
gitignored, in their repo. Not in a directory inside ours.

### 3. Operators are not members of tenant groups

`suraj@corp.example` is `MG-PLATFORM` and nothing else. The edge refuses him at an app
he is not listed on, exactly as it refuses anyone:

```
suraj@corp.example is not a member of any group that may use 'headcount-dashboard'
```

The platform team is not special-cased into tenant apps. If an operator needs to see
an app's *behaviour*, that is telemetry and they already have it. If they need to see
its *data*, see below.

### 4. Reading tenant rows is a conversation with the data owner, not a platform feature

There is no `insights access breakglass` command, and that is the decision.

The platform holds no grant on any dataset, so it has nothing to grant itself
temporarily. An operator who genuinely needs to see rows asks **that team's data
owner**, in the data owner's own system — a Unity Catalog grant, a database role. It
is recorded there, in an audit we cannot edit, and it expires there.

That is a smaller claim than a break-glass workflow, and it has the advantage of being
true. A workflow in *our* repo would have implied we could grant it, and we cannot.

> **If this becomes routine, something is wrong.** An operator repeatedly needing raw
> rows to debug means the telemetry is inadequate. The fix is better telemetry, not a
> smoother path to other people's data.

### 5. The console shows telemetry, never rows

The platform's own portal is the obvious place for this control to leak, so it is
stated as a property and pinned by a test: the console may not import `insights_sdk`,
`connectors` or the broker, and the only database it opens is the scheduler's own run
state, read-only.

It cannot leak what the platform never collected.

---

## The tension

**Operability versus assurance.**

Three people supporting three hundred apps need enough signal to diagnose a problem
they cannot reproduce, on an app whose code they have never read. Every increase in
that signal is a step toward "the platform team can see everything".

We resolved it by making the *shape* of the signal the control, rather than a policy
about who may look. A record that structurally cannot contain a payload needs no
access rules — and a rule that is enforced by the data model does not decay when
somebody is in a hurry at 3am.

The cost is real: sometimes the telemetry genuinely is not enough, and the answer is
"ask the team", which is slower than looking. We think that is the right trade at this
size, and §4's revisit note is where we would notice if it is not.

---

## Alternatives considered

### A. Break-glass with time-boxed operator grants *(what this ADR used to describe)*
Coherent while the platform brokered data. Removed with the broker: the platform holds
no grants, so a break-glass flow here would have been theatre — a form to fill in that
grants nothing.

### B. Standing read access for the platform team, with audit
Simplest to operate and the most common thing internal platforms actually do. Rejected:
"we log our own access" is a deterrent, not a control, and it makes the platform team
the largest standing exposure of every tenant's data.

### C. No telemetry access either
Maximally defensible and unoperable. Three people cannot support three hundred apps
they can see nothing about, and the result would be worse — debugging by asking teams
to paste logs, which contain more than our records do.

---

## Consequences

**Good.** The platform team's access is bounded by what the telemetry *can contain*,
not by a policy. Credential custody is enforced by IAM rather than by us. There is
nothing to grant ourselves, so there is nothing to abuse.

**Bad.** Some incidents will need a conversation with the tenant that a standing grant
would have skipped. We will be slower on those.

**The residual risk, stated plainly.** The SDK runs inside the tenant's process, so a
team *could* open their own connection and read their own data without the platform
seeing it. Detection is comparing the data platform's audit against our correlation
records; the recourse is organisational. This is not a gap being worked on — it is a
correct description of a platform that does not own its tenants' data.

---

## Revisit when

- **An operator asks for raw rows more than about twice a quarter.** That is the
  telemetry failing, and the fix is in the telemetry.
- **A tenant asks us to hold a connection on their behalf.** That is the broker
  arriving through the front door, and it should be a deliberate decision rather than
  a slow accretion of special cases.
- **Anyone proposes a console feature that shows data rather than shape.** The test in
  `tests/test_console.py` will fail, and that failure is the conversation.
