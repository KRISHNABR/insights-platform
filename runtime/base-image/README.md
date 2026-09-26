# Base images — a small published family

Tenants do not write a Dockerfile. They declare `runtime.base` in `app.yaml` and the
platform builds the image. This directory is what the platform publishes.

## Why a family rather than one image

One image is too few and "bring your own" is too many.

**One image** breaks the first time a team legitimately needs something the others don't —
pandas and pyarrow in a web app that only serves JSON is wasted size and CVE surface, and a
data team without them is blocked on us.

**Bring your own** destroys the property that makes the paved road worth paving: one CVE fix
becomes 25 pull requests against images we don't control, and the non-root user, the SDK
version and the entrypoint contract become things we *ask* for rather than things that are
true.

So: a **small, published family**. Three today, and adding one is a platform change with a
review — not a team's private decision.

| `runtime.base` | Contains | For |
|---|---|---|
| `python-web` | Python 3.12, SDK, uvicorn | `web.type: api` and `spa` — JSON backends, and serving a team's own frontend |
| `python-data` | Python 3.12, SDK, pandas, pyarrow, **no web server** | `kind: job` — batch and reporting. A job that cannot serve traffic cannot quietly become an unmonitored API |
| `python-min` | Python 3.12, SDK only | Small jobs where start-up time matters |
| `python-streamlit` | Python 3.12, SDK, Streamlit, pandas, the identity shim and health sidecar | `web.type: streamlit` — exploratory dashboards |

`insights runtimes` lists them with their current versions and patch dates.

## What every one of them carries, so no team has to remember

- The Python runtime and its patch level
- The SDK — runtime version and library version become **one** decision, not two
- A non-root user (uid 10001)
- The entrypoint: `kind` in `app.yaml` selects web or job, so the two archetypes cannot drift
- The health contract: `/healthz` resolves every declared dataset and checks its credential was injected

A CVE in any of these is **one rebuild here plus a redeploy**, rather than chasing 25 repos.

## "What if none of these fit?"

Three answers, in the order we try them:

1. **Declare extra packages.** `runtime.packages: [geopandas]` — we build `FROM` the family
   image and add them. Covers most of the long tail, and you still inherit every guarantee.
2. **Ask for a new family member.** If two teams need the same thing, it stops being a long
   tail and becomes a base image. That is a platform change with a review, which is correct —
   we are agreeing to patch it forever.
3. **Bring your own base** — *not supported today.* The trigger would be a tenant whose
   runtime genuinely cannot be expressed as ours plus packages: a different language, or a
   vendored binary with its own base OS requirements. At that point CI would have to verify
   what we currently guarantee by construction (non-root, SDK present, entrypoint, no
   `:latest`), and we would be checking instead of knowing. Worth it only when a real tenant
   needs it. See ADR-005.

## Files here

- `python-web.Dockerfile`, `python-data.Dockerfile`, `python-min.Dockerfile`, `python-streamlit.Dockerfile` — the family
- `entrypoint.sh` — shared by all of them; branches on `kind`
