# Insights Hub

[![verify](https://github.com/KRISHNABR/insights-platform/actions/workflows/verify.yml/badge.svg)](https://github.com/KRISHNABR/insights-platform/actions/workflows/verify.yml)
[![Open in Codespaces](https://img.shields.io/badge/Open%20in-Codespaces-24292e?logo=github)](https://codespaces.new/KRISHNABR/insights-platform)

An internal platform for small analytics apps — dashboards, scheduled reports, data explorers.
A team writes their app and one config file, and gets login, permissions, data access,
deployment, logging and monitoring without writing any of it.

**This repo is the platform.** It is the root of a four-repo submission.

| Repo | Who touches it |
|---|---|
| **insights-platform** *(here)* | platform team only — runtime, control plane, docs |
| [insights-sdk](https://github.com/KRISHNABR/insights-sdk) | tenants, as a dependency |
| [insights-headcount-dashboard](https://github.com/KRISHNABR/insights-headcount-dashboard) | example tenant — web app |
| [insights-comp-report](https://github.com/KRISHNABR/insights-comp-report) | example tenant — scheduled job |

---

## Where to start

| You want | Go to |
|---|---|
| How it works | [`docs/ARCHITECTURE.md`](docs/ARCHITECTURE.md) |
| Why it works that way | [`docs/adr/`](docs/adr/) — five decision records |
| To join the platform as a team | [`ONBOARDING.md`](ONBOARDING.md) |
| **To operate or change the platform** | **[`RUNBOOK.md`](RUNBOOK.md)** |
| To review it as a compliance partner | [`COMPLIANCE.md`](COMPLIANCE.md) |

---

## Run it

```bash
mkdir insights-hub && cd insights-hub
git clone https://github.com/KRISHNABR/insights-platform.git
git clone https://github.com/KRISHNABR/insights-sdk.git
git clone https://github.com/KRISHNABR/insights-headcount-dashboard.git
git clone https://github.com/KRISHNABR/insights-comp-report.git

cd insights-platform && ./dev up
```

Needs Python 3.12 and [uv](https://docs.astral.sh/uv/). No Docker, no cloud account, no
credentials. Directory names matter — the local loop finds the sibling repos by name. Use
`./dev up --port 9100` if 8080 is taken.

```bash
open "http://localhost:8080/a/headcount-dashboard/?as=krishna@corp.example"
```

Appending `?as=` is the whole local login.

**Or install nothing:** the [verify badge](https://github.com/KRISHNABR/insights-platform/actions/workflows/verify.yml)
runs this entire stack on every push and publishes the results — including the two checks that
must *fail* — to the job summary. [Codespaces](https://codespaces.new/KRISHNABR/insights-platform)
gives you a working environment in a browser.

### Four things worth trying

```bash
# 1 · a client cannot assert its own identity — still krishna
curl -b cookies.txt -H "X-Auth-Groups: comp-analyst" \
     http://localhost:8080/a/headcount-dashboard/api/me

# 2 · a tenant cannot mark its own data non-sensitive
#     add `classification: internal` to a dataset in any app.yaml → rejected, at runtime and in CI

# 3 · knowing a dataset name is not access
#     query `sales.pipeline` from the dashboard → EntitlementError. It exists, and has rows

# 4 · the evidence a reviewer gets
./dev compliance-report --dataset hr.compensation
```

---

## What is in this repo

```
insights-platform/
├── docs/
│   ├── ARCHITECTURE.md              the system, end to end
│   └── adr/                         five decision records
├── ONBOARDING.md                    day one for a new team
├── RUNBOOK.md                       how the platform team operates and changes this
├── COMPLIANCE.md                    the control catalogue, for a reviewer
├── dev                              local entrypoint — wraps the insights CLI
│
├── control/                         the CONTROL PLANE — decides what is allowed
│   ├── registry/
│   │   ├── catalog.yaml             connections and datasets. A projection, not a source of truth
│   │   ├── grants.yaml              the second key for restricted data
│   │   └── apps.json                what is deployed (CI writes it)
│   └── cli/gates.py                 rules that must never ship
│
├── runtime/                         the DATA PLANE — what actually runs
│   ├── edge/                        identity. The most important 120 lines here
│   ├── scheduler/                   what makes `kind: job` mean something
│   ├── base-image/                  the published image family every app builds on
│   ├── fakes/                       stub warehouse (SQLite) + stub REST API
│   └── sinks/                       events.jsonl + audit.jsonl
│
├── infra/                           target architecture, described. No deployable IaC
└── .github/workflows/
    ├── ci.yml                       reusable — every tenant's PR calls this
    ├── deploy.yml                   reusable — every tenant's deploy calls this
    └── verify.yml                   proof this repo works, on every push
```

**control vs runtime** is the split worth knowing: `control/` decides what is allowed and is
reviewed like code; `runtime/` is what serves traffic.

---

## The design in five lines

1. **Tenants declare intent; the platform resolves mechanism.** A team names a dataset, a role,
   a schedule. The platform picks the engine, the credential, the group, the cron.
2. **The platform brokers data; it never hands out a connection.** Sharing a connection means
   sharing a credential, and then nothing stops the headcount dashboard reading salaries.
3. **Identity is only believed when the edge asserts it.** Client-supplied identity headers are
   stripped, and an app's `Caller.groups` is empty without a valid edge assertion.
4. **Every rule sits at the earliest layer that makes it impossible to get wrong.** Generator →
   SDK runtime → CI → human review → documentation last.
5. **Governance belongs to the data platform, not to us.** In production, Unity Catalog owns
   ownership, sensitivity, grants and column masks. We own the application platform and the
   bridge between them.

---

## The brief's five questions

| Question | Answer | Detail |
|---|---|---|
| **Reuse and upgrade** with 12 dependants | A versioned SDK, floor not pin, scaffolds generated not cloned. **Deprecation telemetry** turns "please migrate" into a list of four teams | [ADR-001](docs/adr/0001-platform-shape-and-reuse-strategy.md) |
| **Isolation** — shared vs not | Everything is shared except the data path. The tier follows the **data's** sensitivity, not the tenant's identity | [ADR-002](docs/adr/0002-tenant-isolation-and-data-access.md) |
| **Operator access** | Redaction raises at emit; no standing access to rows; break-glass approved by the **dataset owner**, time-boxed, audited, tenant notified | [ADR-003](docs/adr/0003-operator-access-and-tenant-data.md) |
| **Enforcement** | Earliest layer that makes a rule impossible to get wrong. The diagnostic: *what does the day-one guide have to warn people about?* | [ADR-004](docs/adr/0004-enforcement-and-platform-rules.md) |
| **Deliberate omissions** | Fifteen, each with the trigger that reverses it | [ADR-005](docs/adr/0005-deliberate-omissions-and-triggers.md) |

A fuller mapping, including the brief's context constraints, is in
[`docs/BRIEF-COVERAGE.md`](docs/BRIEF-COVERAGE.md).

---

## What I'd do next

1. **Real IaC and a second environment.** `infra/` describes the target and deploys nothing.
   This is what most weakens "production grade". CDK in Python — it produces CloudFormation,
   it is the same language as the platform, and it unit-tests without an AWS account.
2. **The identity bridge, for real.** Interactive apps should exchange the user's session for a
   short-lived Databricks token so Unity Catalog sees the actual person. Structural, not wired.
3. **Periodic access review.** The compliance partner will ask. All the inputs exist.
4. **Make `insights status` answer "is it broken?"** rather than "did it run?"
5. **A second engine adapter, chosen by a real tenant** — "adding an engine inherits every
   control for free" is true in the code and unproven in practice.
6. **Machine-to-machine exposure.** The first agent or system calling an app as a tool needs
   API Gateway, and more interestingly a decision about what a non-human caller's identity means.

**The call most likely to be wrong:** the data API is narrow on purpose — two verbs, no escape
hatch. The signal to watch is the rate of "can the platform add X" tickets. A trickle means it
is well judged; a stream means the platform team has become a queue, and the answer then is a
data service other languages can reach, not an escape hatch.

---

## Notes on scope

Time budget was 10–12 hours, and the brief scores prioritisation.

| Where it went | Why |
|---|---|
| ADRs and docs (~45%) | The brief says ADRs first, code second, and means it |
| The broker and its tests (~30%) | It is the decision everything rests on, so it had to be real |
| Runtime, CLI, CI, examples (~25%) | Enough to prove the model runs end to end |

Not polished on purpose: no web UI for status (the CLI has the same data), no retries or
backfill in the scheduler, no real IaC. Each would have looked more finished and taught a reader
less.

**Three things found by building rather than designing** — the reason the code was worth writing:

- A scheduled job has no human caller, so "may this caller see salaries?" has no answer from
  corporate groups. The obvious fix — read `access.roles` from the manifest — lets a team unmask
  compensation by editing its own repo. Roles now come from the **grant**.
- An undeclared dataset and a nonexistent one return the **same** error, because a differentiated
  error lets any tenant enumerate the registry by guessing. A test asserts they stay identical.
- The rendered image never installed the tenant's own dependencies. Everything passed until it
  ran. Found by the verify workflow, not by reading the code.
