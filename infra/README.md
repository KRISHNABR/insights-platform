# infra/ — illustrative only

There is no Terraform here, and no cloud account. The brief encourages stubs and fakes
wherever real infrastructure would be, so this directory answers one question a reviewer
will ask — *where would the real thing go, and why isn't it a fifth repository?* — rather
than holding code nobody can run.

## Why platform infrastructure lives in this repo, not its own

The tempting split is `insights-platform` for control-plane code and `insights-infra` for
Terraform. We did not do that, for one reason: **the registry and the infrastructure
describe the same facts.**

A tenant's `app.yaml` names a connection and the NAME of a secret. The infrastructure
creates that secret's slot and grants the app's own identity permission to
read it. Split across two repositories, those drift — and the failure is silent until an
app deploys cleanly and then cannot read anything. Same repo, same pull request, same
review.

**The trigger to split them:** a separate team owning infrastructure with a different
change-approval path. An organisational boundary is a legitimate reason to split a
repository. Two engineers wanting tidier folders is not.

## What would actually be here

| | What it provisions | Why the platform owns it |
|---|---|---|
| `network/` | VPC, subnets, the ingress that fronts `runtime/edge` | The edge is the only thing that may assert identity, so its network position is a security control, not a deployment detail |
| `secrets/` | one slot per `secret:` a tenant declares, scoped so only that app's identity can read it — and an explicit Deny for the platform team | This is where credential custody becomes true rather than aspirational |
| `compute/` | the cluster, the app runtime, the scheduler | One shared runtime — per-tenant infrastructure is rejected in ADR-002 |
| `observability/` | log sink, retention, and the audit stream's separate retention | Audit retention is a compliance obligation, so it belongs in code with a review path |
| `identity/` | the `<app>-admin` / `<app>-user` groups derived from each manifest | Derived from `app.yaml` at deploy time, never created by hand |

## The one design note worth keeping

**Groups are derived, not authored.** When an app lists a group in `access.manage`,
the deploy pipeline reconciles the corresponding group — it is not a ticket someone files.
Anything a human creates by hand for twenty-five tenants will be wrong for at least one of
them, and nobody will know which.

The same principle explains the credential model: a manifest names a secret, the
infrastructure creates it under that name, and the runtime injects it. No human ever
copies a secret between two places.
