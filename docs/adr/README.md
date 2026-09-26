# Architecture Decision Records

Five records, each one severable: it has its own status and date, and can be superseded on its own
without disturbing the others. That is the reason these are not one design document.

For the system as a whole — how a request flows, how a deploy flows, and a map of which record
answers which question — read [`../ARCHITECTURE.md`](../ARCHITECTURE.md) first.

| | Decision | Why it was hard |
|---|---|---|
| [ADR-001](ADR-001-reuse-and-upgrade.md) | A versioned SDK in its own repo, with generated scaffolds | Tenant autonomy vs. the cost of upgrading twelve dependants |
| [ADR-002](ADR-002-shared-data-and-isolation.md) | Shared data connections are **brokered, not handed out** — and the isolation line that draws | Operability for a team of three vs. what a compliance partner will accept |
| [ADR-003](ADR-003-operator-access.md) | Zero standing access to tenant data; redaction that raises at the emit point | Every control here makes the platform team's own job harder |
| [ADR-004](ADR-004-enforcement-placement.md) | Enforce each rule at the earliest layer that makes it impossible to get wrong | Enforcement strength vs. tenant freedom |
| [ADR-005](ADR-005-deliberate-omissions.md) | Eleven things deliberately not built, each with the trigger that reverses it | Completeness vs. honesty about who operates this |

**Suggested order:** ADR-002 → ADR-003 → ADR-001 → ADR-004 → ADR-005. Two and three are where the
design is most exposed and most deliberate.

## The shape each one follows

Every record has the same six sections, so they can be read in any order and compared against
each other:

| Section | What it is for |
|---|---|
| **Context** | the facts from the environment that forced a decision, quoted rather than paraphrased |
| **Decision** | what we did |
| **The tension** | the two legitimate goals that pulled against each other. If an ADR has no tension, it was not a decision — it was a preference, and it does not belong here |
| **Alternatives considered** | what we rejected and *why not*, including the one with the strongest case |
| **Consequences** | what we now have to do, what gets harder, and what we accept |
| **Revisit when** | the specific signals that would make this decision wrong. A decision without a written expiry condition quietly becomes a convention |

The last two are the ones worth arguing with. An ADR that only lists benefits has not been
thought through.
