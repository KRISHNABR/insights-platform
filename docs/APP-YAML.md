# `app.yaml` — the complete schema

The only configuration file an app has. Everything in it is a **declaration**: what
you need and who owns it. Nothing in it is mechanism — no connection string, no IAM
role, no pipeline.

Unknown keys are **refused, not ignored**. A silently-dropped block is a team
believing a rule is in force when it is not.

---

## The whole file

```yaml
apiVersion: v1
app: comp-report
team: people-analytics
kind: job                        # web | job

access:
  manage:
    owners:       [MG-PEOPLE-ANALYTICS]
    contributors: [MG-PEOPLE-ANALYTICS-ENG]
    readers:      []

runtime:
  size: medium                   # small | medium | large

connections:
  - name: hr-warehouse
    engine: databricks-sql
    host: ${HR_WAREHOUSE_HOST}
    http_path: ${HR_WAREHOUSE_HTTP_PATH}
    secret: hr-warehouse-token
    local:
      engine: sqlite
      path: ${INSIGHTS_WAREHOUSE_PATH}

job:                             # only for kind: job
  schedule: "0 6 * * MON"
  timezone: Europe/Dublin
  timeout: 30m
  retries: 2
  concurrency: forbid
  catchup: false
  on_failure: notify-owners
```

---

## `access` — who may do what

```yaml
access:
  manage:
    owners:       [MG-PEOPLE-ANALYTICS]    # required
    contributors: [MG-PEOPLE-ANALYTICS-ENG]
    readers:      [MG-FINANCE-BI]
```

| Tier | Can |
|---|---|
| `owners` | approve a production deploy · change `access` itself · answer for the app |
| `contributors` | deploy dev and uat · read logs and telemetry · **not** prod |
| `readers` | use the running app · see it in `insights status` · nothing more |

**The tiers nest.** An owner satisfies `require_role("reader")` without being listed
as one. The alternative is listing owners in three places, and forgetting once is a
lockout that looks like a platform bug.

**Corporate groups, never individuals.** The loader refuses anything containing `@` —
individuals leave, and an app owned by someone who left is an orphan.

These do three jobs at once, which is why there is no second block:

1. The edge uses their **union** to decide who may reach the app at all — layer 1,
   before any of your code runs.
2. `require_role("owner" | "contributor" | "reader")` checks them inside your code —
   layer 2.
3. The deploy pipeline reconciles them into GitHub environment reviewers, so the right
   to own an app and the right to promote it cannot drift apart.

> **Removed:** `access.roles`, where an app defined its own named roles. Two
> authorization vocabularies in one file meant every reader had to work out which one
> a given check used, and in practice apps' roles restated these three. Refused now.

---

## `runtime` — how much machine

```yaml
runtime:
  size: small                    # small | medium | large
  system_packages: [libgeos-dev] # optional; apt packages your Dockerfile installs
```

`size` maps to cpu / memory / replicas per environment. That mapping is the platform's
and is not in your file.

> **Removed:** `runtime.sdk` — `pyproject.toml` declares it and `uv.lock` pins it, and
> uv enforces that on every build. **`runtime.base`** — your Dockerfile's `FROM` line
> names it, and you own that file. Both were second copies of something stated
> elsewhere, and a second copy drifts. Both are refused, with a message saying where
> the real one lives.

---

## `connections` — the systems you talk to

```yaml
connections:
  - name: hr-warehouse           # what you pass to connect("hr-warehouse")
    engine: databricks-sql
    host: ${HR_WAREHOUSE_HOST}
    http_path: ${HR_WAREHOUSE_HTTP_PATH}
    timeout: 30
    secret: hr-warehouse-token
```

```python
rows = connect("hr-warehouse").query("SELECT dept, headcount FROM hr_headcount")
```

**You already have access to these systems.** The platform is not in that loop: there
is no catalog here, no entitlement to request from us, no approval queue. What you get
is the driver, somewhere safe for the credential, and an error that says who has to fix
a failure.

### The engines

| `engine` | `query()` takes | Options | Driver |
|---|---|---|---|
| `databricks-sql` | SQL | `host`, `http_path` | your `pyproject.toml` |
| `redshift` | SQL | `host`, `port`, `database` | your `pyproject.toml` |
| `postgres` | SQL | `host`, `port`, `database` | your `pyproject.toml` |
| `rest` | a **path** | `base_url`, `timeout` | built in (httpx) |
| `sqlite` | SQL | `path` | built in |

Options are passed through to the driver, so there is no schema to extend when one
gains a parameter. An engine the platform has not shipped is refused **at load time**
with the list of supported ones — not at 06:00 on the first run.

Adding an engine is a platform change of about ten minutes:
[ARCHITECTURE §6](ARCHITECTURE.md#6--data-connectors-not-a-broker).

### `secret:` is a name, never a value

```yaml
    secret: hr-warehouse-token
```

resolves to `insights/<app>/hr-warehouse-token` in the secret store.

| | |
|---|---|
| writes the value | **your group** |
| reads the value | `sp-<app>` — your app's identity, on its own prefix only |
| **cannot** read it | the platform team, by explicit IAM `Deny` that no `Allow` overrides |
| sees every read | CloudTrail, including ours |

`app.yaml` is in git, so a password typed here is a password in the history forever.
The loader refuses `password`, `token`, `api_key`, `client_secret`, `dsn`,
`connection_string` and friends outright — in the `local:` block too.

### `${VAR}` — one manifest, every environment

Anything that differs per environment is a variable the platform injects at deploy:

```yaml
    host: ${HR_WAREHOUSE_HOST}
```

Expanded when the connection is **opened**, not when the manifest is read — so
`insights doctor`, the deploy gate and the console can all read your manifest without
being the environment your app runs in. An unset variable fails at `connect()` with
`kind=config_missing`.

Only ever a host, path or URL. Never a credential: that would make it an environment
variable, readable by anything that can see the process.

### `local:` — the stand-in for a laptop

```yaml
    local:
      engine: sqlite
      path: ${INSIGHTS_WAREHOUSE_PATH}
```

There is no Databricks on a laptop. Without this, a manifest either describes
production and cannot run locally, or describes the laptop and is a lie about
production.

- Applied **only** when `INSIGHTS_ENV=local`. It cannot make dev behave unlike prod,
  which is where "it worked in dev" comes from.
- It **merges**: fields it names override, everything else is inherited. Your secret
  still resolves locally, so a local run exercises the credential path — the half of a
  connection most likely to be wrong in production and least likely to be tested if
  local skips it.
- `insights up` and `insights run` set `INSIGHTS_WAREHOUSE_PATH` and
  `INSIGHTS_DIRECTORY_URL` for you.

---

## `web` — only for `kind: web`

```yaml
web:
  route: /headcount-dashboard    # where the edge publishes you
  type: spa                      # api | spa
  health: /healthz               # generated by the SDK
```

| `type` | What it is |
|---|---|
| `api` | JSON only. Something else calls you — another app, a notebook, an agent |
| `spa` | Your own built bundle in `static/`, served from the **same origin** as your API — which is what lets the browser hold nothing but a session cookie it cannot read. We serve it; we do not build it |

`health` is generated. It opens every connection you declared and confirms the
credential arrived, so a deploy that starts fine and fails on first use is caught here
rather than by a user. It does **not** run a query — a health check hitting the
warehouse every 30 seconds across three hundred apps is a load generator.

> **Refused:** `dashboard` (a Jinja type) and `streamlit`. Both meant the platform
> owning a UI framework for three hundred apps — Streamlit alone needed a header shim
> for identity, a health sidecar, sticky sessions with a replica cap, and a caching
> wrapper. The loader rejects them rather than accepting and failing at deploy.

---

## `job` — only for `kind: job`

```yaml
job:
  schedule: "0 6 * * MON"
  timezone: Europe/Dublin
  timeout: 30m
  retries: 2
  concurrency: forbid
  catchup: false
  on_failure: notify-owners
```

| Field | Default | What it means |
|---|---|---|
| `schedule` | *required* | Standard cron, in the timezone below |
| `timezone` | *required* | Explicit, always. "UTC vs local" causes one real incident per platform |
| `timeout` | `1h` | SIGTERM at the limit, SIGKILL 30 seconds later |
| `retries` | `0` | On a non-zero exit, with backoff |
| `concurrency` | `forbid` | `forbid` skips this run if the previous one is still going — what you want for anything that writes |
| `catchup` | `false` | If the platform was down at 06:00, do **not** fire a burst of missed runs on recovery |
| `on_failure` | `notify-owners` | After the last retry, page `access.manage.owners` |

`concurrency` and the fire-once-per-schedule guard live in the scheduler's own SQLite
state, so they survive a scheduler restart. They used to be a dict in the process,
which made them true only within one lifetime.

**Exit codes are a contract:** `0` succeeded · `1` the job broke · `2` the platform
refused it. The scheduler retries 1 and 2 differently, because a refusal will not fix
itself.

Outputs are not declared. `output("name", rows)` writes an artefact with the
platform's default retention; naming each one in the manifest bought a per-artefact
retention and cost a block of ceremony plus a failure mode where the job runs,
computes, and throws the result away because a name did not match.

---

## What is **not** in this file, and why

| Not here | Where it is | Why |
|---|---|---|
| Deploy approvals | GitHub environment protection, reviewers reconciled from `access.manage` | Stating it twice means two things that can disagree |
| `auto_deploy` | which of the three deploy workflows exists | Same |
| Python version | your `Dockerfile`'s `FROM` | You own your image |
| SDK version | your `pyproject.toml` + `uv.lock` | uv enforces it on every build |
| Credentials | the secret store | git remembers forever |
| Dataset entitlements | your data platform | You already have access; we are not in that loop |

> **Removed:** the whole `environments:` block —
> `{dev: {auto_deploy: true}, prod: {approvers: owners}}`. Nothing ever read it. The
> approval gate is a GitHub environment whose reviewers the platform reconciles from
> `access.manage`, and "automatic" is simply which workflow exists. It is refused now,
> with a message that says so.

---

## Checking it

```bash
uv run insights doctor               # the same code CI runs
uv run insights connections          # what you declared, and whether the secrets resolve
uv run insights connections --probe  # actually open each one
```
