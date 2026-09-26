# What is in these repos, and why

Two repos, two audiences. If you remember one thing:

> **`insights-sdk` is what a tenant imports and runs.**
> **`insights-platform` is what runs beside their app.**

---

## Why the CLI lives in the SDK, and what `control/cli` is doing here

The most common confusion, so it goes first. They are not the same thing.

| | `insights-sdk/src/insights_sdk/cli/` | `insights-platform/control/cli/` |
|---|---|---|
| What | the `insights` command | scripts the **pipeline** runs |
| Who runs it | a person, at a terminal | GitHub Actions, in a workflow |
| Examples | `doctor`, `serve`, `run`, `new-app` | `gates.py`, `deploy.py`, `register.py` |
| Installed? | yes — it is a console script | no — invoked as `python control/cli/gates.py` |

**Why `insights` ships in the SDK:** `insights doctor` has to validate a manifest with
*exactly the code the app will run*. If the CLI were its own package it would either
depend on the SDK anyway — two version numbers, nothing gained — or reimplement the
validation and drift. Then CI says fine and the runtime says no, which is the worst
failure a platform can have.

**Why `control/cli` is not in the SDK:** these are the platform's side of the deploy
contract. A tenant never runs them and should not be able to — `gates.py` is the thing
that can *refuse their deploy*. Shipping it in the library they install would put the
gate inside the thing being gated.

`insights --help` groups the commands by audience for the same reason.

---

## `insights-platform` — what runs beside an app

```
insights-platform/
│
├── README.md              start here
├── ONBOARDING.md          day one, for a team joining the platform
├── RUNBOOK.md             day two, for us — incidents and procedures
├── COMPLIANCE.md          the control list, for a reviewer
│
├── docs/
│   ├── ARCHITECTURE.md    how it works and why each line is where it is
│   ├── APP-YAML.md        every manifest field, what it means, what it costs
│   ├── WALKTHROUGH.md     run everything, step by step
│   ├── REPO-GUIDE.md      this file
│   ├── BRIEF-COVERAGE.md  how the submission maps to the original brief
│   └── adr/               the five decisions, with alternatives and triggers
│
├── control/               THE CONTROL PLANE — what decides, not what serves
│   ├── cli/
│   │   ├── gates.py           the CI gates. Rules that must never ship
│   │   ├── reconcile.py       manifest → GitHub reviewers, IAM, edge table
│   │   ├── deploy.py          roll the image out          ┐ interface stubs:
│   │   ├── register.py        record what is deployed      │ they print what
│   │   ├── verify.py          prove it works               │ they would do
│   │   └── _contract.py       shared helper for those      ┘ and exit 2
│   └── registry/
│       ├── apps.json          which apps exist, and which groups may use them
│       ├── apps.local.json    the same, written by `insights up` / `serve`
│       └── environments.yaml  values for ${VAR} in tenant connections, per env
│
├── runtime/               THE DATA PLANE — what actually serves traffic
│   ├── edge/              the front door: sign-in, group check, header injection
│   │   ├── main.py        ~150 lines, and the most important ones here
│   │   └── users.yaml     the stub corporate directory. Add a person here
│   ├── scheduler/
│   │   ├── main.py        cron matching, timeouts, retries
│   │   └── state.py       run state in SQLite, so `concurrency: forbid` survives
│   │                      a restart
│   ├── console/           the portal. A tenant OF this platform, not a privileged
│   │   ├── main.py        tool — it sits behind the edge like any app
│   │   └── index.html
│   ├── fakes/             local stand-ins, so `up` needs no cloud account
│   │   ├── warehouse/     a seeded SQLite database
│   │   └── directory/     a tiny REST API
│   ├── sinks/             telemetry written locally (gitignored)
│   ├── state/             scheduler run state (gitignored)
│   └── outputs/           what jobs produce (gitignored)
│
├── tests/                 the scheduler's run state, and the console
├── infra/                 what the AWS layer would be. Stubs, and honest about it
├── .devcontainer/         so Codespaces gives a reviewer a working env in a browser
└── .github/workflows/
    ├── ci.yml             the reusable CI every tenant calls
    ├── deploy.yml         the reusable deploy every tenant calls
    └── verify.yml         proves the whole stack on every push to this repo
```

### The split that matters: `control/` vs `runtime/`

**`control/` decides. `runtime/` serves.**

Nothing in `control/` is in the request path — it runs in a pipeline, at deploy time,
and its output is configuration. Nothing in `runtime/` makes a policy decision it did
not read from the control plane.

That is why the edge does not parse tenant manifests: `reconcile.py` turns
`access.manage` into the edge's authorization table at deploy time, and the edge reads
only that table. A running app cannot change who may reach it by editing a file.

---

## `insights-sdk` — what a tenant imports

```
insights-sdk/
├── src/insights_sdk/
│   ├── __init__.py        the entire tenant-facing surface. If it is not exported
│   │                      here it is internals and may change in a minor
│   ├── entrypoints.py     web_app() and run_job() — what an app is built on
│   ├── identity.py        Caller, require_role, and the trust rules
│   ├── connectors.py      connect(), the engines, and the error translation
│   ├── secrets.py         resolving a secret without ever printing one
│   ├── config.py          loading and validating app.yaml
│   ├── telemetry.py       the logger that refuses to carry a payload
│   ├── outputs.py         output()
│   ├── deprecation.py     @deprecated — the keystone of the upgrade story
│   └── cli/
│       ├── main.py        the `insights` command
│       └── scaffold.py    every file `insights new-app` generates
└── tests/                 89 tests
```

### What a tenant repo looks like

```
insights-your-app/
├── app.yaml               YOURS. The only configuration this app has
├── src/main.py            YOURS
├── static/                YOURS (web apps) — we serve it, we do not build it
├── Dockerfile             YOURS, generated once. CI checks two things about it
├── pyproject.toml         YOURS
├── .env                   YOURS, and gitignored. Local secret values
├── .env.example           committed, so a colleague knows what to fill in
├── .github/workflows/     PLATFORM-OWNED. Four lines each, calling ours
└── RUNBOOK.md             PLATFORM-OWNED. Refreshed by `insights upgrade-scaffold`
```

The platform-owned files are re-rendered by `insights upgrade-scaffold`; everything
else is yours and never touched. That is only possible because they were **generated**
rather than cloned from a template — the SDK knows which files it owns, so it can
rewrite exactly those.

---

## The tags, and why there are two

Both repos carry a **moving `v1`**, and they mean different things.

| Tag | What points at it | Moves when |
|---|---|---|
| `insights-sdk@v1` | tenants' `pyproject.toml` | every SDK release |
| `insights-platform@v1` | tenants' `.github/workflows/*.yml` | every platform release |

A tenant's pipeline is four lines: `uses: .../ci.yml@v1`. So a stale **platform** tag
means every tenant runs stale CI — with the old gate rules — and nothing says so.
Ours was 28 commits behind before anyone noticed, because moving it was a manual step
nobody had written down. It is now a job in `verify.yml` that runs when main is green.

Same argument as the SDK's floor-not-pin ([ADR-001](adr/0001-platform-shape-and-reuse-strategy.md)):
the tag **moves** within the major line, and a breaking change means cutting `v2`.

> **`uv.lock` pins the resolved commit, not the tag.** Moving `insights-sdk@v1` changes
> nothing for a tenant until they re-lock. That is the point — a release cannot alter
> a running app underneath it — but it does mean a moved tag alone is not a rollout.

---

## Where to look when

| Question | File |
|---|---|
| How do I run all this? | [WALKTHROUGH.md](WALKTHROUGH.md) |
| What can I put in `app.yaml`? | [APP-YAML.md](APP-YAML.md) |
| Why is it built this way? | [ARCHITECTURE.md](ARCHITECTURE.md) |
| What were the alternatives? | [adr/](adr/) |
| What does CI enforce? | [ARCHITECTURE.md §9](ARCHITECTURE.md), `control/cli/gates.py` |
| Who can see my data? | [COMPLIANCE.md](../COMPLIANCE.md), [ADR-003](adr/0003-operator-access-and-tenant-data.md) |
| Something is broken | [RUNBOOK.md](../RUNBOOK.md) |
| Day two for my own app | `RUNBOOK.md`, in your own repo |
