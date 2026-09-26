# Compliance — the controls, and the evidence for each

What a reviewer is handed. Every row names the control, where it is enforced, and the
**test or command that demonstrates it** — so nothing here has to be taken on trust.

Run `uv run insights compliance-report` for the live version of the last section.

---

## What this platform does, and does not, do with your data

Stating this first, because it changes which controls are even relevant.

**The platform does not broker data access.** Teams already have access to their own
systems — their Unity Catalog grants, their database roles, their API keys say so, and
that is true whether or not this platform exists. The platform ships the **connector**,
holds the **credential** somewhere only the app can read it, and translates the
**error**. It does not sit between an app and its warehouse, and it never sees a row.

An earlier design did broker every read, with a dataset catalog and an entitlement
check. It was removed ([ADR-002](docs/adr/0002-tenant-isolation-and-data-access.md)):
it maintained a second copy of the data platform's governance model, and it implied a
containment guarantee that an in-process library cannot make.

**So the controls below are about identity, credential custody, and evidence.** Data
governance is the data platform's, enforced on every path including a notebook.

---

## The controls

| # | Control | How it is enforced | Where | Evidence |
|---|---|---|---|---|
| 1 | A caller's identity cannot be forged | The edge **strips** every `X-Auth-*` a client sent, then injects values it validated itself plus a token only it and the app hold | the edge, a separate process | `verify.yml` → "Forged identity headers are stripped" |
| 2 | An app outside the platform can do nothing | `Caller.groups` is a property returning `()` unless `trusted`. `require_role()` and `connect()` both refuse | SDK runtime | `test_an_app_run_outside_the_edge_can_read_nothing`, `test_no_connection_without_a_caller_the_platform_vouched_for` |
| 3 | Someone with no business in an app never reaches its code | The edge checks group membership against the app's `access.manage` before proxying | the edge | `verify.yml` → "A user outside the app is refused" |
| 4 | An app cannot claim another app's identity | Unattended work runs as `sp-<app>`, **derived** from the registered app name. There is no manifest field for it, and unknown keys are rejected | manifest loader + deploy | `test_a_tenant_cannot_declare_its_own_service_identity` |
| 5 | A credential never enters source control | The manifest loader refuses `password`, `token`, `api_key`, `client_secret`, `dsn`. `.env` is gitignored and CI refuses a tracked one. A repo-wide pattern scan runs on every build | loader + CI | `test_a_credential_in_the_manifest_is_refused` · `verify.yml` → "A committed .env is refused" |
| 6 | The platform team cannot read a tenant's credential | Values live at `insights/<app>/<secret>`, written by the owning group and readable by `sp-<app>` only. The platform role carries an explicit IAM **Deny** on `insights/*`, which no Allow overrides | IAM, not code | [ADR-003](docs/adr/0003-operator-access-and-tenant-data.md) |
| 7 | A secret cannot leak through a log line or a traceback | `Secret.reveal()` is the only path to the value; `str`, `repr`, f-strings and `format` all give `REDACTED` | SDK runtime | `test_a_secret_never_stringifies_to_its_value` |
| 8 | A local secret cannot become a production one | `.env` is read **only** when `INSIGHTS_ENV=local`. Outside local the SDK refuses it and names the variable the platform should have injected | SDK runtime | `test_dotenv_is_refused_outside_local` |
| 9 | Tenant data cannot reach platform telemetry | The logger **raises** at the point of writing on any non-scalar field, and on any string long enough to be a payload. Not scrubbed at the sink — scrubbing fails open | SDK runtime | `test_a_log_record_cannot_carry_rows`, `test_a_log_record_cannot_carry_a_payload_disguised_as_a_string` |
| 10 | A query's contents are never recorded | A `query_executed` record carries connection, engine, duration and row count. Never the SQL, which would name tables and columns and often a literal | SDK runtime | `test_a_connector_records_shape_and_never_content` · `verify.yml` asserts no SQL in the record |
| 11 | A container does not run as root | CI refuses a Dockerfile whose final `USER` is root, or that sets none | CI gate | `verify.yml` → "a final USER of root" |
| 12 | A build is reproducible and rollback-able | CI refuses an unpinned or `:latest` base. `uv sync --frozen` fails if the lockfile is not current | CI gate | `verify.yml` → "an unpinned :latest base" |
| 13 | An app cannot run an unsupported SDK | The deploy gate resolves the declared range against the supported window (current major plus two) and refuses a pin | CI gate | `test_the_sdk_floor_gate_can_actually_fail` |
| 14 | Deploy approval cannot be self-granted | The approval gate is a GitHub environment whose reviewers the platform reconciles from `access.manage`. A tenant's pipeline is a four-line caller onto a central reusable workflow | CI + GitHub | `.github/workflows/deploy.yml` |
| 15 | Evidence cannot be quietly edited | Telemetry and audit sinks are append-only. Scheduler run state records every run, including ones that died before emitting anything | sink writer, scheduler | `runtime/sinks/*.jsonl` · `tests/test_scheduler_state.py` |

---

## What the platform team can see

**Telemetry: standing access. Tenant data: none.**

That works because of what a record *contains*: caller, app, connection, engine,
duration, row count — and no payload, by construction. So the telemetry stream is
readable by anyone operating the platform without that being access to tenant data.

**We see that a query happened. We never see what it returned.**

For a tenant's actual data there is no platform mechanism at all. An operator who
needs to see rows asks that team's data owner, in the data owner's own system, and the
grant is recorded there. The platform holds no dataset grants to break glass on —
which is a smaller and more honest claim than the break-glass workflow an earlier
version of this document described.

See [ADR-003](docs/adr/0003-operator-access-and-tenant-data.md).

---

## Running the evidence

```bash
uv run insights compliance-report
```

Reports which apps hold which connections, whose credential each uses, every
connection failure by kind, and the redaction assertion status. Everything in it is
read from the registry, the manifests and the audit sink — **nothing is asserted by
the command itself**, because a report the platform team writes by hand is a claim.

```bash
cd insights-sdk && uv run --no-project --with pytest ... python -m pytest -q
```

88 tests. The ones cited above are named so a reviewer can run exactly the one that
backs a given row.

---

## Known limits, stated rather than discovered

- **This is soft isolation.** Apps share a cluster, a kernel and a control plane. The
  boundary is the credential and the identity, not the hypervisor.
- **A team can connect to their own data without going through us, and we would not
  know.** The SDK runs in their process. That is a correct description of a platform
  that does not own its tenants' data, not a gap being worked on.
- **The AWS deployment is an interface stub.** There is no cloud account behind this
  submission; the deploy steps print what they would do and exit 2. Everything above
  that is *not* AWS-specific runs and is tested.
