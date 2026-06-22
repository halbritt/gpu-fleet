# FALSIFIER - RFC 0001 build plan challenge (Falsifier 2)

author: falsifier-antigravity-gemini-001

## Claims challenged

We challenge the build plan on the following claims:
1. **Claim C2 & C4 (Correctness & Design of Shard Failover):** The proposed `failover_transfer` mechanism is logically redundant if dead leases are released on error, and leaks leases if they are not.
2. **Claim C1 (Backward Compatibility of Readers):** Slice B's proposal to drop the `free_slots` column from `pick_slot.py` breaks un-upgraded consumers in the fleet.
3. **Claim C1 & C7 (Slice-Decomposition of `capacity` Column):** Adding the `capacity` column in Slice A creates immediate data drift and is redundant/unused in v1.
4. **Claim C3 & C5 (Correctness of Stable Jitter SQL):** The proposed stable jitter SQL expression propagates `NULL` when the `job` parameter is not provided, breaking herd dispersal.

---

## 1. Concurrency, Atomicity, and Leakage Dilemma in `failover_transfer`

### Claim Challenged
Claim C4 asserts that "failover transfers release dead lease and claim survivor atomically (no double-hold, no leak)" via `leases.failover_transfer(conn, dead_lease_id, candidate_slots, ...)`.

### Refuting Counterexample
This design introduces a logical contradiction regarding when a failed shard's lease is released:
- **Scenario A (Worker releases lease on error):** If the worker thread (running `run_shard`) immediately releases its lease on error/exception to keep the database tidy, then the dead lease is already `NULL` before the failover phase begins. Consequently, `failover_transfer`'s attempt to release it is a no-op, and no atomic transfer is necessary or achieved.
- **Scenario B (Worker does not release lease on error):** If the worker thread does *not* release the lease on error, relying instead on `failover_transfer` to do it, then if there are *no survivors* available (a total fleet wipe or no slots have completed), `failover_transfer` is never called. As a result, the dead shard's lease is leaked and remains locked in the database for up to 45 seconds (the TTL), preventing any other concurrent client/run from reusing that slot until it autonomously expires.

### Required Gap to Close
The build plan must clarify the lifecycle boundary: either enforce immediate lease release on error inside the worker thread (removing the redundant release logic from `failover_transfer`), or implement a fallback release mechanism for failed shards when no survivors are available for failover.

---

## 2. Backward-Compatibility Violation in `pick_slot.py`

### Claim Challenged
Claim C1 asserts that the plan is "backward-compatible: until consumers use the new columns/state, fleet behavior equals today's."

### Refuting Counterexample
Slice B proposes: *"Drop the `free_slots` reference from `SELECT`/`ORDER BY`"* in `pick_slot.py`.
However, because the heartbeat writer is left untouched in v1, the `free_slots` column still exists in the database and is written to by the heartbeat. If an un-upgraded consumer (e.g., running an older version of `di_fleet.py` or another tool in the fleet) calls the updated `pick_slot.pick` or runs `pick_slot.py --json` and attempts to access the `"free_slots"` key from the returned slot dictionary, it will raise a `KeyError` or encounter a parsing failure, breaking backward compatibility before the rollout is complete.

### Required Gap to Close
To maintain true backward-compatibility, `pick_slot.py` must continue to return the `"free_slots"` column (or map `capacity` as an alias to `"free_slots"`) in the returned dictionary until all un-upgraded readers are decommissioned.

---

## 3. Redundancy and Drift of the `capacity` Column in v1

### Claim Challenged
Claim C1 and the slice-decomposition structure claim that Slice A is a clean, additive expand/contract step.

### Refuting Counterexample
Slice A adds `capacity` and backfills it from `free_slots`. However:
1. Because the heartbeat service is completely untouched in v1, new slots registered in the fleet will be inserted into `gpu_slots` using the default value (`capacity = 1`). If a slot is configured with `free_slots = 2` in `fleet_nodes`, the heartbeat will write `free_slots = 2` but `capacity` will remain `1`, leading to immediate data drift between the two columns.
2. In Slice B, the pick query is updated to check `(lease_id IS NULL OR now() >= lease_expires)` but completely ignores the `capacity` column. Thus, `capacity` is never read or used to determine slot availability in v1.
Adding a write-only, read-never schema change that immediately drifts from the active source of truth (`free_slots`) violates the principles of clean slice-decomposition and YAGNI.

### Required Gap to Close
The plan should either update the heartbeat service in v1 to correctly write to `capacity`, or defer adding the `capacity` column until the `capacity > 1` evolution is actually implemented.

---

## 4. Propagation of NULL in Stable Jitter SQL

### Claim Challenged
Claim C3 and C5 assert that the stable jitter SQL query correctly disperses the herd when a job is provided or when no job is specified (the fallback no-arg call).

### Refuting Counterexample
Slice B proposes the stable jitter tie-breaker in `ORDER BY`:
`hashtext(%(job)s || node || slot_id::text)`
In PostgreSQL, string concatenation (`||`) propagates `NULL` (i.e., any string concatenated with `NULL` returns `NULL`). If a caller passes `job` as `None` or if the parameter is omitted/NULL, the entire concatenation evaluates to `NULL`. Consequently, `hashtext(NULL)` returns `NULL` for every row, completely disabling the stable jitter ordering and defeating herd dispersal.

### Required Gap to Close
The SQL query must be updated to avoid `NULL` propagation, either by using `CONCAT(%(job)s, node, slot_id::text)` or by using `COALESCE(%(job)s, '') || node || slot_id::text`.
