# Task — Author the build plan for the RFC in context_docs

You are the plan holder. A gpu-fleet RFC is attached as a context document
(`docs/rfc/<id>-*.md`). It is a **settled design** — prepared via `/adhd`, scored,
with rejected traps recorded. Do NOT re-open its design decisions or resurrect a
rejected alternative. Translate it into a **falsifiable build plan** that a separate
build run will execute.

## Deliverable — the build plan (write it at the declared artifact path)

It MUST contain:

1. **Scope & slices** — ordered, independently-committable slices (e.g. DB
   migration → pick query → consumer claim/renew/release → failover). Each slice
   names the exact files it touches (its blast radius). Source lives at the repo
   root: `di_fleet.py`, `pick_slot.py`, `heartbeat.py`, `heartbeat_all.py`,
   `bin/di-fleet`, `migrations/`, `tests/`.
2. **Migration plan** — exact schema changes. Use the next **UNUSED** migration
   number: inspect the `migrations/` directory and take the lowest unused `0NN`
   (001–005 are taken, and a prior RFC in this campaign may already have landed
   006/007); never reuse an existing number. It MUST be backward-compatible: until
   consumers use the new columns/state, fleet behavior equals today's. State the
   apply order (DB → readers → writers).
3. **Test plan mapped to the RFC's falsifiable gate** — for EACH bullet in the
   RFC's "Falsifiable gate" section, name the concrete test that proves it and say
   whether it is a hermetic unit test (inject fakes, mirrors
   `tests/test_probe_all.py`) or needs an ephemeral real Postgres. The default
   `python3 -m pytest tests/ -q` (26 tests today) MUST stay green and hermetic; any
   DB-backed test MUST be guarded so it does not break that hermetic default when no
   DB is present.
4. **Live-infra safety** — the build MUST NOT touch the live `gpu_fleet` Postgres
   DB, the running `gpu-fleet-heartbeat` service, or peecee's shared GPU. It only
   writes migration SQL files, code, and tests, and runs pytest. The operator
   applies migrations (stop→migrate→start) and restarts the service AFTER
   integration.
5. **Boundaries to preserve** — di-fleet consumers shell out to `di --json` and
   never import the Node engine (`~/git/divergent-ideation`); re-deploying
   `bin/di-fleet` is an operator step.
6. **Open questions** — answer each open question the RFC leaves with the choice the
   build will adopt, and why.

## If you are REVISING (a prior `needs_revision` verdict)

If a collaboration ledger from a prior cycle is in the dialogue, you are revising.
Read it, discharge **every binding constraint** it recorded (fold the fix into the
relevant slice and into the falsifiable-gate→test map), restate any claim the
adjudicator said you only conceded, and preserve everything the ledger said
survived falsification. Do not re-open the RFC's settled design.

## Claims to make falsifiable

State each load-bearing plan claim with the evidence that would support it and the
observation that would refute it. The falsifiers will attack these.

## Output contract

Write ONLY the declared artifact. Downstream challenge completion is not acceptance;
the collaboration ledger decides whether the gate clears.
