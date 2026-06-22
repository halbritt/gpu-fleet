# Task — Verify the implementation against the RFC's falsifiable gate

You are the verifier. Read the committed build plan, the RFC's "Falsifiable gate"
section, **`PRIOR_FINDINGS_AND_BC1_SCOPE.md`**, the author's claim ledger, and the
**actual diff** on disk. For BC1, verify against the *scoped* criterion in
`PRIOR_FINDINGS_AND_BC1_SCOPE.md` (BC1-A responsive abort wired into the production
claim/dispatch/run_shard path; an honest test with **no synthetic `gpu_busy`/sleep
handshake**; the irreducible residual documented), not BC1's literal wording. Accept
only if BC1-A is in the production path and its test is honest and green.

## Verify (do the work yourself — do not take the ledger's word)

1. Re-run `python3 -m pytest tests/ -q` yourself. Record the verbatim result and
   count. If it is not green, the verdict is `needs_revision` (or `reject`).
2. For EACH bullet in the RFC's falsifiable gate, confirm a test **exists** and
   **actually proves it**. Inspect the test bodies:
   - Exclusivity proven by a genuine two-transaction concurrency test (loser's
     CLAIM returns zero rows), not a bare assertion.
   - Deadman expiry frees the slot within ≤ TTL with **no reaper process** running.
   - A zombie renew after re-claim returns **zero rows** (fenced).
   - K-fan-out holds N distinct leases; failover releases + reclaims atomically.
   - **No consumer wall-clock** is read anywhere in claim/renew/release (inspection).
   (Use the RFC's own gate list — these are the 0001 examples.)
3. Confirm the migration is backward-compatible and numbered `006`, the `di --json`
   boundary is intact, and **no live infra** (the `gpu_fleet` DB, the
   `gpu-fleet-heartbeat` service, peecee) is touched by the diff.
4. Confirm **every binding constraint** from the committed plan's ledger is
   discharged.

## Deliverable — the finding (at the declared artifact path)

Record a single finding with a verdict: `accept`, `accept_with_findings`,
`needs_revision`, or `reject`. Cite the specific gate items and what proved or
refuted each, and the pytest result you observed. Do NOT edit code — write only your
review artifact.
