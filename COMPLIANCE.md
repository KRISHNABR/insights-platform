# Control catalogue

*For the compliance partner reviewing this platform before People Analytics onboards.*

The brief for this platform said your review happens **before** that team onboards, not
after. So this document is written to be argued with rather than to reassure: every row
below ends in something you can run or read, and the last two sections are the things we
did **not** build and the gap we cannot close.

---

## What the platform is, in one paragraph

Teams build small internal apps — dashboards and scheduled reports — on a shared
substrate. They do not hold database credentials and cannot open a connection. They
declare which **datasets** they need; the platform resolves that to a connection, a
credential and a physical location, checks the request, performs the read, applies field
masking, and records what happened. There is exactly one code path from an app to data,
which is what makes everything below enforceable rather than aspirational.

---

## Controls

| # | Obligation | Control | Enforced in | Evidence you can check |
|---|---|---|---|---|
| 1 | Only entitled apps read compensation data | The **data owner** grants it to the app's service identity, in their own system. The platform grants nothing — it verifies the grant exists and refuses early if it does not | data platform; verified in CI and at runtime | `insights access` · `insights compliance-report --dataset hr.compensation` |
| 2 | Teams cannot decide how sensitive their own data is | Sensitivity is a **Unity Catalog tag** set by the data owner. A manifest containing the word `classification` — at any depth — is rejected outright | manifest loader **and** CI gate | `tests/test_manifest_contract.py` · try adding it to any `app.yaml` |
| 3 | Apps cannot reach data they did not declare | Entitlement is checked on every read. SQL is additionally scanned and refused if it references another dataset's table | SDK runtime | `test_an_undeclared_dataset_is_refused`, `test_sql_cannot_reach_past_the_declared_dataset` |
| 4 | Users see only the rows and fields they may see | **Unity Catalog column masks and row filters**, applied by the data platform per person — on every path to the data, including a notebook, not only through this platform | Unity Catalog | UC mask definitions; locally approximated and covered by `test_a_caller_without_the_role_gets_masked_fields` |
| 5 | An app cannot claim another app's access | Its service identity is **derived from the registered app name**. There is no manifest field for it and the loader rejects unknown keys — which matters because access is granted to identities | manifest loader + deploy | `test_a_tenant_cannot_choose_its_own_service_identity` |
| 6 | Compensation data never reaches logs | The logger **raises** on any non-scalar field, and additionally on any field *name* belonging to a restricted dataset the app has read | SDK runtime | `tests/test_telemetry_boundary.py` · `runtime/sinks/events.jsonl` |
| 7 | Identity cannot be forged | The edge strips every identity header a client sends and re-injects its own. An app with no edge in front of it has a caller with no groups, so every check fails | edge + SDK runtime | `test_a_client_cannot_assert_its_own_identity` · the curl example in the [README](README.md) |
| 8 | The platform team has no standing access to tenant data | Platform engineers hold no dataset grants. Reading tenant rows requires break-glass: time-boxed, approved by the **dataset owner**, audited, and the tenant is notified | access model | the `break_glass` section of `grants.yaml` · the report's *Operator access* block |
| 9 | Access is reviewable | **Unity Catalog `system.access.audit`** is authoritative for every read. We additionally write a correlation record — which app, which HTTP request, which user — because UC knows the query and only we know the app | UC + SDK runtime | UC system tables · `runtime/sinks/audit.jsonl` |
| 10 | Evidence cannot be quietly edited | Audit and event sinks are append-only; grants are appended, never edited in place. A revocation is a new record | sink writer | `grants.yaml` structure |

---

## The one artefact to ask for

```bash
uv run insights compliance-report --dataset hr.compensation
```

```
DATASET  hr.compensation      sensitivity: restricted (UC tag)     owner: MG-PEOPLE-ANALYTICS

APPS WITH ACCESS
  comp-report                  granted 2026-09-20 by vidya@corp.example

ACCESS IN PERIOD                                      2 reads
  2026-09-26T06:00:02Z  comp-report            sp-comp-report          4 rows

OPERATOR ACCESS                                       0 standing · 1 break-glass
  2026-09-24  suraj@corp.example  approved by vidya@corp.example  [expired]
              used 1x · tenant notified: True

REDACTION ASSERTIONS                                  active, 0 violations
```

Nothing in that output is asserted by the command. Every line is read from the registry
and the audit sink, so it reports the system's actual state rather than its intent.

---

## What we did not build

Named here rather than left for you to find. Each has a written trigger in
[ADR-005](docs/adr/0005-deliberate-omissions-and-triggers.md).

| Not built | Why not, honestly | What would change it |
|---|---|---|
| **Periodic access review** | Not built. The data exists (grants, audit, owners); the report and the cadence do not | Your requirement. It is first on the "what next" list after a staging environment |
| **A separate production environment** | Everything runs in one environment today | Already triggered, by this onboarding. It is the next thing we build |
| **Per-tenant infrastructure** | Two to three engineers cannot operate twenty-five isolated stacks. Tenants are teams of employees, with organisational recourse | A tenant that is not a team of employees — a contractor, a joint venture, an acquired entity |
| **A browsable data catalog** | A discovery surface would mean storing a description of compensation data's shape for teams who cannot read it | We would build discovery *outside* this platform, in a governed catalog, not inside it |

---

## The gap, stated plainly — and which environment it applies to

This is the one place the design reads differently depending on where it runs, so it is worth
being exact rather than reassuring. The full argument is in
[ADR-002 §3](docs/adr/0002-tenant-isolation-and-data-access.md).

**On the Databricks target, there is no long-lived data credential to take.** An interactive
app exchanges the signed-in user's session for a short-lived token, so Unity Catalog sees the
actual person; a scheduled job federates its workload identity. Nothing is stored, so there is
nothing for a platform engineer — or a tenant — to read.

**What remains is narrower**, and it is this: the broker runs **in the tenant's own process**,
so whatever token that process holds for the duration of a query is reachable from that
process. A determined team member could use it directly and make a read the platform never
audits.

**Locally it is wider**, because the stub warehouse is a plain file and the path is in the
environment: a local process can read the whole file. That is a property of the stub, not of
the design.

We accept this, and we want you to accept it knowingly rather than not notice it:

- **Why we accept it.** Doing that is not an accident. It is a deliberate act by a named
  employee against a platform with observability and organisational recourse — a
  conversation with a manager, not a control failure.
- **Why it is not invisible.** Every legitimate read produces an audit record. A read
  through a side channel produces none while the app's own logs keep flowing, so an app
  that queries data it never audits is a detectable pattern. That is the alert we would
  write first.
- **How we would close it.** Move the broker into a sidecar process in the same pod: the
  credential lives with the sidecar, the app talks to it over localhost and never holds
  it. We would do this before onboarding any tenant that is not a team of employees, or
  if misuse of this credential would be a reportable event rather than an internal one.

We would rather tell you this now than have you find it.

---

## Questions we expect, and where they land

| Question | Answer |
|---|---|
| "Can the platform team read compensation data?" | Not without break-glass, which the **dataset owner** approves — not us — and which expires, is audited, and notifies the team. Control 8 |
| "What if a team writes salaries into a log line?" | It raises at the point of writing. Control 6 |
| "What if a team edits its own config to widen access?" | Classification and grants are not in tenant repositories. Controls 1, 2 and 5 |
| "How would you know if something went wrong?" | Every read is audited with caller and sensitivity, and four alarms are generated per app — including one for an app that queries data it never audits. See ARCHITECTURE §7a |
| "Who approves access?" | The dataset owner. The platform team cannot approve access to data it does not own, and the CLI has no command that would let it |
