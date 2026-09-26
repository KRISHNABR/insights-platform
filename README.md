# Insights Hub

[![verify](https://github.com/KRISHNABR/insights-platform/actions/workflows/verify.yml/badge.svg)](https://github.com/KRISHNABR/insights-platform/actions/workflows/verify.yml)

An internal platform for small analytics apps — dashboards, scheduled reports,
internal APIs — operated by a team of three.

A team writes two files. They inherit corporate sign-in, authorization, connectors for
the systems they already have access to, somewhere safe to keep the credential,
structured logging, a health check that checks something, and a deployment pipeline.

**Start here**, then [ONBOARDING.md](ONBOARDING.md) if you are a team joining, or
[docs/ARCHITECTURE.md](docs/ARCHITECTURE.md) if you want to know how it works.

---

## Run the whole thing locally

```bash
mkdir insights-hub && cd insights-hub
for r in insights-platform insights-sdk insights-headcount-dashboard \
         insights-comp-report insights-attrition-api insights-directory-sync; do
  git clone "https://github.com/KRISHNABR/$r.git"
done

cd insights-platform && uv run insights up
```

Needs Python 3.12 and [uv](https://docs.astral.sh/uv/). No Docker, no cloud account,
no credentials. Directory names matter — the local loop finds the sibling repos by
name. Use `uv run insights up --port 9100` if 8080 is taken.

```bash
open "http://localhost:8080/apps/console/?as=suraj@corp.example"
```

Appending `?as=` once is the whole local login; after that a session cookie carries it.

### Five things worth trying

```bash
# 1 · a client cannot assert its own identity — you stay krishna, not admin
curl -b cookies.txt -H "X-Auth-Groups: admin" \
     http://localhost:8080/apps/headcount-dashboard/api/me

# 2 · someone outside the app cannot probe its routes at all
#     krishna on attrition-api → 403, from the edge, before any app code runs

# 3 · a credential in app.yaml is refused, not ignored
#     add `password: hunter2` to any connection → the manifest fails to load

# 4 · bypass the edge entirely → anonymous, and anonymous can read nothing
curl http://localhost:8102/api/me

# 5 · the two logs, which answer two different questions
uv run insights logs --app headcount-dashboard --startup   # did it boot?
uv run insights logs --app headcount-dashboard             # what did it do?
```

---

## The four example apps

| App | Kind | Shows |
|---|---|---|
| [headcount-dashboard](https://github.com/KRISHNABR/insights-headcount-dashboard) | `web` / `spa` | a backend plus its own frontend; two engines in one app |
| [attrition-api](https://github.com/KRISHNABR/insights-attrition-api) | `web` / `api` | JSON only, no frontend |
| [comp-report](https://github.com/KRISHNABR/insights-comp-report) | `job` | a schedule, retries, concurrency, an output artefact |
| [directory-sync](https://github.com/KRISHNABR/insights-directory-sync) | `job` | the REST connector, and a credential from the secret store |

All four were created with `insights new-app` and then filled in — nothing in them was
hand-assembled.

---

## What is in this repo

```
insights-platform/
├── README.md                        this
├── ONBOARDING.md                    day one, for a team joining
├── RUNBOOK.md                       day two, for us
├── COMPLIANCE.md                    the control list, for a reviewer
├── docs/
│   ├── REPO-GUIDE.md                what every folder and file is for
│   ├── WALKTHROUGH.md               run everything, step by step
│   ├── APP-YAML.md                  every manifest field
│   ├── ARCHITECTURE.md              how it works, and why each line is where it is
│   └── adr/                         the decisions, with alternatives and triggers
├── control/
│   ├── cli/gates.py                 the CI gates — rules that must never ship
│   └── registry/apps.json           which apps exist, and which groups may use them
└── runtime/
    ├── edge/                        the front door: sign-in, group check, identity injection
    ├── scheduler/                   cron, retries, concurrency, run state in SQLite
    ├── console/                     a read-only fleet view, hosted as a tenant of itself
    └── fakes/                       a warehouse, a REST API and a secret store, for local
```

The SDK is [its own repository](https://github.com/KRISHNABR/insights-sdk).

---

## The shape of it

**An SDK, not a central service.** A three-person team cannot be on the critical path
of three hundred apps at 3am. There is no shared runtime to fail, no extra hop on every
read, and a team debugging gets a stack trace in their own process rather than "the
platform is slow". The cost is that upgrades are opt-in — see
[ADR-001](docs/adr/0001-platform-shape-and-reuse-strategy.md) for what stops that
becoming "never".

**Connectors, not a broker.** Teams already have access to their data. The platform
ships the driver, holds the credential and translates the error; it does not stand
between an app and its warehouse, and never sees a row.
[ADR-002](docs/adr/0002-tenant-isolation-and-data-access.md).

**The platform holds the secret slot, never the value.** A team writes it; the app's
own identity reads it; the platform team cannot, by explicit IAM `Deny`. Custody is a
property of the thing issuing credentials, not of us choosing not to look.

**Everything that protects other people runs outside the tenant's process.** The edge
is a separate service; identity, group membership and secret custody are not library
decisions. Everything *inside* the SDK protects a tenant from their own mistakes.

**Refuse, don't ignore.** A manifest key we removed, a shape we do not support, a
credential where a reference belongs — all fail the file. A silently-dropped block is
a team believing a rule is in force when it is not.

---

## The commands

| | |
|---|---|
| `insights new-app NAME --kind web\|job --team T --owner GROUP` | Generate an app: manifest, Dockerfile, source stub, runbook, four pipelines |
| `insights doctor` | Everything CI will check, checked locally first — **the same code**, so they cannot disagree |
| `insights connections [--probe]` | What this app talks to, whether its secrets resolve, whether it can connect |
| `insights up [--port N]` | The whole local platform: apps, the edge, the console |
| `insights run` | Run a job now, exactly as the scheduler would |
| `insights logs --app X [--startup]` | Telemetry, or the process log |
| `insights status` | Every registered app |
| `insights build --show \| --write` | The Dockerfile — print it, or write it into your repo |
| `insights upgrade-scaffold [--check]` | Re-render the platform-owned files in a tenant repo |
| `insights compliance-report` | The evidence a reviewer gets, read from the registry and the sink |

Install it once, globally — there is no project yet when you run `new-app`:

```bash
uv tool install git+https://github.com/KRISHNABR/insights-sdk.git@v1
```

Inside a repo, prefer `uv run insights`: it uses **your** pinned SDK, so `doctor`
cannot disagree with your app.

---

## What it deliberately does not do

Each with the trigger that would change our minds, in
[ADR-005](docs/adr/0005-deliberate-omissions-and-triggers.md).

No data catalog. No governance layer — Unity Catalog owns that, enforced on every path
including a notebook. No portal. No second language. No base images. Not hard
isolation, and we say so rather than implying more.

---

## Verification

The [verify workflow](https://github.com/KRISHNABR/insights-platform/actions/workflows/verify.yml)
clones every repo on each push, boots the whole stack, and runs the behaviour checks —
**including the ones that must fail**: a forged identity header, a credential in a
manifest, an unpinned base image, a container running as root, and a tenant repo that
cannot resolve without its siblings.
