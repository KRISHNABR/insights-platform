# Local fake secret store

One file per secret, at `<app>/<secret-name>`. The path is the same shape as
production — `insights/<app>/<secret>` in AWS Secrets Manager — so the scoping rule is
identical and only the enforcer changes.

**What is different in production, and it is the whole point:** here, anyone who can
read this directory can read every app's secret. There:

| | |
|---|---|
| writes the value | the app's owning group — the team |
| reads the value | `sp-<app>`, the app's own identity, on its own prefix only |
| **cannot read it** | the platform team, by an explicit IAM `Deny` on `insights/*` that no `Allow` can override |
| sees every read | CloudTrail, including ours if we ever granted ourselves an exception |

Custody is a property of the thing issuing credentials, not of us choosing not to call
`GetSecretValue`.

Values here are obvious fakes and are gitignored. `insights run` and `insights up` point
`INSIGHTS_SECRET_DIR` here for you.
