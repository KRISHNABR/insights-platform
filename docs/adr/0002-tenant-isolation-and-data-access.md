# ADR-002 — Tenant isolation, data access and secrets

**Status:** accepted · supersedes the brokered-access design described in the first
two revisions of this file
**Decision owner:** platform team

---

## Context

Apps on this platform read data: a warehouse, an internal REST API, occasionally
both. They run beside each other on shared infrastructure, operated by three people.
Two questions follow, and they are not the same question:

1. How does an app reach its data safely?
2. What stops one tenant reaching another tenant's?

The brief also asks how the platform team's own access is granted, constrained and
evidenced — answered in [ADR-003](0003-operator-access-and-tenant-data.md).

### What we built first, and why it was wrong

The first design brokered every read. The platform held a catalog of datasets, a
tenant declared `data: [{dataset: hr.compensation}]`, and `query()` resolved the
nickname to a physical table, checked an entitlement, applied column masking and
wrote an audit record. Connections were platform-operated and never handed out.

It was coherent, and it was over-reach on two counts.

**It answered a question nobody asked.** Teams on this platform *already have access
to their data.* People Analytics can read compensation data because their Unity
Catalog grants say so, and that is true whether or not this platform exists. Putting
ourselves in the middle meant maintaining a second governance model beside the data
platform's own — and a second model does not stay in sync, it drifts silently.

**It implied a guarantee an in-process library cannot make.** The broker ran inside
the tenant's process. A team could `import sqlite3`, or add a driver, and connect
directly. So "the platform controls data access" was true only for teams who chose to
let it be — which is not a control, it is a convention with a large amount of code
attached.

Deleting it removed 431 lines of SDK and 176 of registry, and made the honest claim
smaller and true.

---

## Decision

### 1. The platform ships connectors. It does not broker reads.

A team declares a connection; the SDK opens it.

```yaml
connections:
  - name: hr-warehouse
    engine: databricks-sql
    host: ${HR_WAREHOUSE_HOST}
    secret: hr-warehouse-token
```

```python
rows = connect("hr-warehouse").query("SELECT dept, headcount FROM hr_headcount")
```

| Ours | Theirs |
|---|---|
| the driver, pooling, timeouts, TLS | which system, which database |
| error translation | the query |
| the secret binding | every row that comes back |
| telemetry about the connection | — |

**What the platform records:** which connection, which engine, duration, row count.
**What it does not record:** the SQL, or any row. SQL carries table and column names
and frequently a literal in a `WHERE` clause; a platform-wide log of tenant SQL is a
data inventory nobody consented to.

### 2. A connection is declared, never improvised.

`connect()` takes a **name**. It has no parameter that could carry a host, a URL, a
DSN or a credential — a fact pinned by a test, because the signature *is* the control.
What an app can reach is therefore reviewable in `app.yaml`, in git, rather than
buried in a function three directories down.

An engine the platform has not shipped is refused at load time with the list of
supported ones, rather than failing at 06:00 on the first run.

### 3. `connect()` requires a caller the platform vouched for.

The credential belongs to the **app**, not to whoever is asking. Without this check an
app reachable outside the edge would use its own credential on behalf of an anonymous
caller.

- A web app gets its caller from the edge.
- A job gets a service identity from the scheduler.
- Anything else gets `IdentityError`.

This is what keeps *"running outside the edge is not an app with no user, it is an app
where every check returns no"* true of the data path and not only of `require_role()`.

### 4. Secrets: the platform holds the slot, never the value.

Somebody has to store the credential. If we do, three people can read every team's
database password, and "we promise not to look" is not a control.

```
app.yaml            secret: hr-warehouse-token       <- a REFERENCE
secret store        insights/<app>/<secret>
writes the value    the app's owning group
reads the value     sp-<app>, on its own prefix only
CANNOT read it      the platform team — explicit IAM Deny on insights/*
sees every read     CloudTrail, including ours
```

**Custody is a property of the thing issuing credentials, not of us choosing not to
call `GetSecretValue`.** An explicit `Deny` cannot be overridden by any `Allow`, so it
survives somebody later granting the platform role broad access by mistake.

Two supporting rules, both in code:

- The manifest loader **refuses** `password`, `token`, `api_key`, `client_secret`,
  `dsn` and friends. `app.yaml` is in git; a credential there is in the history
  forever, and "we removed it in the next commit" is not a remediation.
- `Secret.reveal()` is the only path to the value. `str`, `repr`, f-strings and
  `format` all give `<Secret name REDACTED>` — so the leak nobody wrote on purpose
  (a debug f-string, a traceback, `json.dumps(default=str)`) does not happen.

`${VAR}` in a connection option is expanded at **connect** time, not load time, so
`doctor`, the deploy gate and the console can all read a manifest without being the
environment the app runs in. Only ever a host, path or URL — never a credential, which
would make it an environment variable readable by anything that can see the process.

### 5. Service identity is derived, never declared.

Unattended work runs as `sp-<app>`, derived by the platform from the registered app
name. A team cannot name their own: if they could, they could claim another app's and
inherit whatever it can read. It is one string everywhere — the principal a data owner
grants to, the subject in the data platform's audit, and the caller in ours — so the
two audit trails join on a literal match rather than on somebody knowing a renaming
rule.

### 6. What isolation actually means here

Honesty first: this is **soft isolation**. Apps share a cluster, a control plane and a
kernel. The boundary is the credential and the identity, not the hypervisor.

| | Shared by everyone | Shared by nobody |
|---|---|---|
| | the VPC, the cluster, the edge, the CI pipeline | their process, their task role, their secret prefix, their log group, their connections |

The line that matters: **an app can only ever reach systems it has a credential for,
and that credential is scoped to its own identity.** A compromised app is a bad day
for one team's data. It is not a route into another team's, because there is no shared
credential to steal and no broker holding everyone's keys.

And there is no tiering by tenant. A team reading compensation data gets the same
mechanism as a team reading headcount — the sensitivity lives in the data platform's
own tags and grants, applied on every path including a notebook, and does not need a
second expression here.

---

## The tension

**Control versus honesty.**

The brokered design *looked* stronger. It could say "every read is entitled, masked
and audited by the platform", which is a better sentence to put in a compliance
document than "teams connect to systems they already have access to." Giving it up
means giving up that sentence.

We think the sentence was misleading. It described what happened when a tenant used
the SDK as intended, in a library running inside their own process, reading data they
were already entitled to. The control it implied — that the platform could *prevent*
an unauthorised read — was never real, because the entitlement it checked was a copy
of somebody else's, and the code it checked in was the tenant's own.

What we have instead is smaller and true: the platform controls **identity** (which
the tenant cannot forge, because the edge is a separate process) and **credential
custody** (which the tenant cannot widen, because IAM is not a library). Both hold
against a tenant who is trying.

The residual risk, stated plainly: **a team can connect to their own data without
going through us, and we would not know.** That is not a gap we are working to close.
It is a correct description of a platform that does not own its tenants' data.

---

## Alternatives considered

### A. Keep the broker *(what we built first)*
Rejected above. The decisive argument is that it implied containment an in-process
library cannot deliver, while costing a permanent second copy of somebody else's
governance model.

### B. A data API service — brokering, but in a separate process
This *would* deliver real containment: tenants get no credential, and every read is
genuinely mediated. Rejected for the reason in
[ADR-001](0001-platform-shape-and-reuse-strategy.md): it puts three people on the
critical path of every read in the company. It is also the most credible thing to
revisit — see the trigger below.

### C. Hand out raw connection strings, ship nothing
The honest minimum: teams manage their own credentials and connections, and the
platform does auth and deployment only. Rejected because the credential has to live
somewhere, and "somewhere" becomes a `.env` file in a repo. The secret custody model
is most of the value here, and it does not work without the platform in the loop for
*storage* — which it can do without being in the loop for *reads*.

### D. Per-tenant infrastructure — a cluster or account per team
Real isolation, and the cost is three people operating N clusters. Rejected on
operational capacity, not on principle. The trigger is regulatory rather than
technical: data that may not share a kernel.

---

## Consequences

**Good.** One way to read data, not two. No governance model to keep in sync with the
data platform's. A tenant's data access is a conversation with their data owner, which
is where it belonged. 431 lines of SDK deleted. Connection errors that say who has to
fix them.

**Bad.** We cannot answer "who read compensation data last month" from our own
records — only "which app queried which connection, how often". The real answer lives
in Unity Catalog's audit, which is authoritative anyway, but it is now two systems to
look in rather than one.

**Ugly.** Teams who liked `query("hr.headcount", ...)` and never thinking about a
connection now have a connection to think about. That is a genuine ergonomic loss, and
the counterweight is that `connect()` is three lines of YAML and the errors tell them
what to do.

---

## Revisit when

- **A tenant is compromised and the blast radius includes another team's data.** That
  would mean the credential scoping is not doing what this ADR claims, and alternative
  B becomes urgent.
- **More than a handful of teams ask us to hold a connection on their behalf** — e.g.
  a shared reference dataset everybody reads. That is alternative B arriving through
  the front door, and it should be a deliberate decision rather than a slow accretion
  of special cases.
- **Secret sprawl.** If apps routinely declare more than a couple of secrets each,
  something about the credential model is not matching how teams actually work.
