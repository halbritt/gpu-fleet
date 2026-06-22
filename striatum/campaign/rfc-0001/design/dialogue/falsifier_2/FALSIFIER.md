# FALSIFIER - RFC 0001 build plan challenge

author: falsifier-antigravity-gemini-002

## Claim challenged

The build plan's Claim C4 asserts that "failover transfer is atomic and leak-free" via the transaction behavior of `leases.failover_transfer` ("release(dead_lease_id) then claim() the first claimable candidate; commit together or roll back together"). The plan also claims in Slice B that the readers/writers migration is "backward-compatible and reversible" (Claim C1) through independent committability of code slices.

These claims are flawed from the perspectives of correctness-of-the-falsifiable-gate, reversibility, and independent-committability.

## Refuting counterexamples & design flaws

### 1. Correctness-of-the-gate: "Atomic Transfer" causes temporary lease leaks (resource lockout)
By forcing the release of the dead slot's lease and the claim of the survivor slot's lease into the same database transaction, a failure in the claim phase rolls back the release phase.

1. A shard fails. `di_fleet` invokes `failover_transfer` to transition the execution to a survivor slot.
2. `failover_transfer` issues the `release` for the dead slot's lease, then attempts to `claim` one of the candidate slots in a single transaction.
3. If no candidate slot is claimable (e.g. all survivors are fully occupied by other concurrent jobs, or a transient database deadlock occurs), the transaction rolls back.
4. Consequently, the release of the dead slot is rolled back, leaving its lease active.
5. The dead slot remains locked (unusable by other consumers) for the rest of its TTL (up to 45s), despite the fact that its subprocess is dead and the job has abandoned the frames.

Because database rows for distinct slots represent independent physical resources, there is no integrity constraint linking their states. Forcing them into the same transaction does not prevent a "double-hold" (since a slot is released before claiming another anyway) but directly introduces a resource utilization degradation (temporary lease lockout) on failover failure.

### 2. Independent-Committability & Reversibility: Schema-dependency in Slice B
Slice B drops the `free_slots` column and assumes `lease_id` and `lease_expires` are present in `pick_slot.py`.
If the database migration `006` needs to be rolled back, or if Slice B is deployed in a canary context where database migrations are delayed, the picker query fails immediately with SQL errors:
```
column "lease_id" does not exist
```
The plan lacks a fallback strategy in `pick_slot.py` to handle the absence of lease columns. A truly reversible and independently committable slice would inspect the schema or gracefully degrade (e.g., fallback to the `free_slots` logic if lease columns are missing) to maintain operational safety across code rollbacks and rollout skews.

## Why the proposed tests would miss it

1. The proposed atomic transfer test (`test_leases_pg.py::test_failover_transfer_is_atomic`) only asserts that transaction rollback occurs. It does not check if the dead slot's lease is left in a locked state when a failover fails, nor does it test the system-level impact on cluster capacity.
2. The hermetic tests for `pick_slot.py` are mock-based and do not check compatibility against the baseline schema (pre-migration `005` or `006` layout). Hence, the schema dependency failure during rollbacks or canaries will go undetected by `pytest`.

## Required gap to close

To make the build plan acceptable:
1. **Uncouple Release and Claim in Failover**:
   - Release the dead slot's lease immediately in a separate transaction upon detecting failure to prevent capacity lockout.
   - Try to claim a survivor in a subsequent transaction.
2. **Defensive Schema Parsing in Picker**:
   - Update `pick_slot.py` to check if `lease_id` exists in the database. If not, fallback to using `free_slots` for picking, ensuring compatibility across migrations and rollbacks.
3. **Explicit Locked Lease Test**:
   - Add a test verifying that when failover fails to find any candidate, the dead slot is *not* left leased in the database after the cleanup routine completes.
