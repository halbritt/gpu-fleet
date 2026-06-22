# Task — Implement the RFC per the committed build plan

Context docs: the **committed build plan**, the RFC, and
`PRIOR_FINDINGS_AND_BC1_SCOPE.md`. A prior build attempt was rejected by the verifier
on BC1 — **read `PRIOR_FINDINGS_AND_BC1_SCOPE.md` first**; it refines BC1 into the
achievable, testable scope (BC1-A responsive abort in the production path, an honest
no-synthetic-wait test, and a documented irreducible residual) and **supersedes BC1's
literal wording**. Implement the plan's ordered slices, honoring every binding
constraint, and discharge BC1 exactly per that scope.

## Do

- Write the migration SQL file as the **next unused** `migrations/0NN_*.sql` — note
  `006_peecee_dense_27b.sql` already exists on master, so use **`007_exclusive_slot_leases.sql`**.
- Implement the code changes (`pick_slot.py`, `di_fleet.py`, `bin/di-fleet`,
  `heartbeat*.py`, etc. — only what the plan's blast radius names).
- Write/extend tests that map to **EACH** bullet of the RFC's "Falsifiable gate".
  Mirror `tests/test_probe_all.py`: inject fakes; no real DB/HTTP/subprocess in unit
  tests. If a gate item genuinely needs an ephemeral real Postgres (e.g. a true
  two-transaction concurrency test), write that test but GUARD it (skip when no DB
  is reachable) so `python3 -m pytest tests/ -q` stays green and hermetic.
- Run `python3 -m pytest tests/ -q` and make **all** tests pass. Record the count.
- If you change `bin/di-fleet` or `di_fleet.py`, note (do not perform) the operator
  re-deploy step `cp bin/di-fleet ~/.local/bin/`.

## Do NOT

- Do NOT apply the migration to any live database, connect to the live `gpu_fleet`
  DB, run `systemctl`/restart `gpu-fleet-heartbeat`, or touch peecee or its GPU.
  Deployment is the operator's job, after integration.
- Do NOT import the Node di engine; the `di --json` shell-out boundary stays.
- Do NOT edit files outside your declared write scope (the RFC under `docs/rfc/` is
  frozen).

## Deliverable — the claim ledger (at the declared artifact path) + the code

Write the claim-ledger artifact listing: files changed, the migration, each
falsifiable-gate item mapped to the test that proves it, and the verbatim pytest
result line (e.g. `31 passed in 0.42s`). The code/migration/test changes live in the
repository within your write scope.

## Output contract

Stay inside the declared write scope. The reviewer will independently re-run the
tests and verify the falsifiable gate — do not treat your own pass as acceptance.
