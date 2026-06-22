---
schema_version: "striatum.synthesis.v1"
artifact_kind: "synthesis"
---

# FINAL REPORT — RFC 0001 build (exclusive slot leases)

author: author-claude-opus-4.8-004

Final report for the build of `docs/rfc/0001-exclusive-slot-leases.md` on branch
`striatum/rfc-0001-build-2`, per `striatum/campaign/rfc-0001/design/COMMITTED_PLAN.md`
with BC1 discharged to the achievable scope in
`striatum/campaign/rfc-0001/build/PRIOR_FINDINGS_AND_BC1_SCOPE.md` (which supersedes
BC1's literal wording).

## Disposition

The independent verifier (`reviewer-openai-codex-gpt-5.5-003`,
`review/VERIFICATION_REVIEW.md`) recorded **`accept_with_findings`** at revision
`a1739d1d…`: *"I found no blocking implementation issue that requires another
revision."* The prior cycle's one blocking finding — runtime failover bypassing the
atomic release-plus-claim path — is **fixed** in this revision (production `main()`
wires `dispatch(..., failover_fn=leased_failover)`; the dead lease is disposed only
through the single-transaction `failover_transfer`). No source change was required by
this apply step. The verifier's "findings" are informational: the migration is
correctly numbered **007** (not the plan's notional 006, because `006_peecee_dense_27b.sql`
already exists on master), and the 4 guarded ephemeral-Postgres tests were *skipped* in
the verifier's environment because no throwaway DB was configured.

**This step:** confirmed the tree is green, additionally exercised the 4 skipped
real-Postgres gate tests against a disposable `initdb` cluster (then tore it down — the
live `gpu_fleet` DB and the `:5432` cluster were never touched), and wrote this report.

## Final files changed + the migration

All inside the build write scope; no live infra touched.

| File | Status | Slice | What |
|---|---|---|---|
| `migrations/007_exclusive_slot_leases.sql` | **new** | A | Additive **expand** half of the `free_slots → capacity` rename: `ADD COLUMN capacity` (const default, `CHECK >= 1`) + nullable `lease_id`/`lease_holder`/`lease_expires`, one backfill `UPDATE`, one partial `gpu_slots_lease_pick_idx`. `free_slots` and `gpu_slots_claim_idx` left **untouched**. Reversible; deploy-order + contract-migration (008) notes in the header. |
| `pick_slot.py` | mod | B | Lease-free predicate `AND (lease_id IS NULL OR now() >= lease_expires)`; warm-pref ordering + **NULL-safe** stable jitter `hashtext(COALESCE(%(job)s::text,'') || node || slot_id::text)`; selects `lease_id`/`lease_expires`; **keeps the `free_slots` output key aliased from `capacity`** (BC2); `psycopg` import made lazy. |
| `di_fleet.py` | mod | C+D | Slot-lease lifecycle (`claim`/`renew`/`release`/`failover_transfer`, SQL constants, `TTL_SECONDS=45`/`RENEW_SECONDS=15`) folded in; `run_leased_shard` = `subprocess.Popen` child + per-shard renew monitor (`_monitor`) that aborts the child **in the renew-observing path** (BC1-A); on child death raises `ShardDied` carrying the **still-held** lease; `run_failover_shard` runs failover as a single-transaction `failover_transfer` (BC4); `dispatch` gained a `failover_fn` seam; `main()` wires it via a dedicated non-autocommit transfer-conn factory. |
| `tests/test_pick_slot.py` | new | B | BC2, BC3, lease-free predicate. |
| `tests/test_leases.py` | new | C | Hermetic claim/renew/release/transfer over `FakeSlotDB`. |
| `tests/test_leases_pg.py` | new | C | **Guarded** ephemeral-Postgres: true concurrency, self-expiry, fencing, transfer atomicity. |
| `tests/test_di_fleet.py` | mod | D | BC1 abort, K-fan-out distinct leases, BC4 failover, and the production-path guard `test_dispatch_failover_routes_through_atomic_transfer_not_release_then_claim`. |
| `tests/test_lease_no_consumer_clock.py` | new | E | Source/AST inspection: lease SQL uses `now()`; lease functions read no Python clock. |
| `tests/lease_fakes.py` | new | — | `FakeSlotDB` (models the real lease SQL with a controllable clock) + `FakeChild`. Not a `test_` module; not collected. |
| `striatum/campaign/rfc-0001/build/CLAIM_LEDGER.md` | new | — | Build handoff ledger (provenance). |

**Note on `leases.py`:** the committed plan's Slice C placed the lease lifecycle in a
new top-level `leases.py`. That path is **not** in the frozen build write scope, so the
lifecycle lives inside `di_fleet.py` (its only consumer) as a delineated "slot-lease
lifecycle" section with the same pure-functions-over-injected-`conn` discipline. The
tests import it as `import di_fleet as leases`. Substance is unchanged; this deviation
is recorded in `CLAIM_LEDGER.md`.

## Falsifiable-gate → test map (FINAL verbatim pytest)

The default suite is **hermetic** — it needs no DB, HTTP, or subprocess. The four
real-Postgres gate rows are **guarded**: they `importorskip("psycopg")` and skip unless
`GPU_FLEET_TEST_DB` points at an ephemeral throwaway cluster (and refuse to run against
`dbname=gpu_fleet`).

| Falsifiable gate | Concrete test(s) | Kind |
|---|---|---|
| Two concurrent consumers on a capacity-1 slot → **exactly one** holds (loser's CLAIM returns 0 rows) | `test_leases_pg.py::test_two_concurrent_claims_exactly_one_wins` (+ hermetic companion `test_leases.py::test_claim_returns_none_when_predicate_unmet`) | ephemeral PG + hermetic |
| **BC1 — in-flight abort:** a lost lease terminates the running `di --json` child **in the renew path** (DB-only test necessary but NOT sufficient) | `test_di_fleet.py::test_lost_lease_aborts_di_child_in_renew_path` (+ `::test_failed_renew_aborts_shard`) | **hermetic — the BC1 gate the verifier confirmed** |
| Consumer stops renewing → slot free within ≤ TTL, **no reaper** | `test_leases_pg.py::test_unrenewed_lease_self_expires` (+ `test_leases.py::test_renew_false_after_autonomous_expiry`) | ephemeral PG + hermetic |
| Zombie renew after re-claim → **zero rows** (fenced) | `test_leases_pg.py::test_zombie_renew_after_reclaim_is_fenced` (+ `test_leases.py::test_zombie_renew_after_reclaim_is_fenced`) | ephemeral PG + hermetic |
| K-fan-out across N slots holds **N distinct** leases | `test_di_fleet.py::test_kfanout_claims_n_distinct_leases` | hermetic |
| Failover releases dead lease + claims survivor **atomically**, and the **production `dispatch()` path routes through it** | `test_di_fleet.py::test_dispatch_failover_routes_through_atomic_transfer_not_release_then_claim`, `::test_failover_transfer_releases_dead_and_claims_survivor`, `test_leases.py::test_failover_transfer_releases_dead_and_claims_survivor`; atomicity by `test_leases_pg.py::test_failover_transfer_is_atomic` | hermetic + ephemeral PG |
| **BC4 — no-survivor failover** frees the slot immediately (not after TTL) | `test_di_fleet.py::test_no_survivor_failover_releases_dead_lease` (+ `test_leases.py::test_failover_transfer_no_survivor_releases_dead_lease_immediately`) | hermetic |
| **No consumer wall-clock** in claim/renew/release (inspection) | `test_lease_no_consumer_clock.py` (2 tests) | hermetic (AST/source) |
| **BC2 — pick_slot backward-compat** (`free_slots` key preserved) | `test_pick_slot.py::test_output_still_contains_free_slots` | hermetic |
| **BC3 — NULL-safe jitter** for `job=''` and `job=None` | `test_pick_slot.py::test_jitter_active_for_empty_and_none_job` | hermetic |

**FINAL verbatim pytest result lines** (run with an interpreter that has `pytest` +
`psycopg`; the repo's pre-existing `heartbeat*` tests import `psycopg` at module top, so
collection requires the driver regardless of this change):

Default — the operator's literal command, hermetic (DB tests guarded OFF):

```text
$ python3 -m pytest tests/ -q
....................................................                     [100%]
52 passed, 1 skipped in 1.22s
```

The `1 skipped` is the `test_leases_pg.py` module (4 ephemeral-Postgres tests), guarded
OFF. With a disposable cluster provided, all four run and pass (this report's extra
verification, against a `/tmp` `initdb` cluster — torn down afterward; the live
`gpu_fleet` DB was never touched):

```text
$ GPU_FLEET_TEST_DB='dbname=gpu_fleet_test host=/tmp/<ephemeral>' python3 -m pytest tests/ -q
........................................................                 [100%]
56 passed in 3.75s
```

```text
$ ... python3 -m pytest tests/test_leases_pg.py -v
tests/test_leases_pg.py::test_two_concurrent_claims_exactly_one_wins PASSED [ 25%]
tests/test_leases_pg.py::test_unrenewed_lease_self_expires PASSED        [ 50%]
tests/test_leases_pg.py::test_zombie_renew_after_reclaim_is_fenced PASSED [ 75%]
tests/test_leases_pg.py::test_failover_transfer_is_atomic PASSED         [100%]
4 passed in 2.69s
```

The RFC's primary falsifiable gate (two concurrent consumers, exactly one wins) — which
the verifier had to skip — is therefore confirmed against real Postgres.

## Binding constraints — all discharged

| Constraint | Status | Where |
|---|---|---|
| **BC1 — physical-exclusivity gate (CRITICAL, the verifier's accept gate)**, scoped per `PRIOR_FINDINGS_AND_BC1_SCOPE.md` | **discharged** | **BC1-A (responsive abort):** `di_fleet._monitor` renews every TTL/3 and, when `renew` returns zero rows, terminates the `Popen` child **synchronously in the same control path that observed the loss** (`di_fleet.py:408`–`414`) — never on a later independent poll, acting only on the process handle. **BC1-test (honest falsifier):** `test_lost_lease_aborts_di_child_in_renew_path` drives the **production** claim/renew seam via `FakeSlotDB`, the successor claims through the real `claim`/`LEASE_CLAIM_SQL` — **no synthetic `gpu_busy`/sleep handshake** (the prior cheat). **BC1-residual:** documented below. |
| **BC2 — migration backward-compat** | **discharged** | `pick_slot.pick` still returns `free_slots` (aliased from `capacity`), so the readers-before-writers window never `KeyError`s an un-upgraded reader (`pick_slot.py:68`). Pinned by `test_output_still_contains_free_slots`. |
| **BC3 — NULL-safe stable jitter** | **discharged** | `hashtext(COALESCE(%(job)s::text,'') || node || slot_id::text)` (`pick_slot.py:39`); `job=None` degrades to `''`. Pinned by `test_jitter_active_for_empty_and_none_job`. |
| **BC4 — failover lifecycle** | **discharged** | Survivor path: `failover_transfer` releases the dead lease and claims a survivor in **one** committed transaction (`di_fleet.py:160`–`182`, `run_failover_shard`). No-survivor path: the dead lease is still released in that same transaction, freeing the slot immediately rather than at the TTL. Pinned by `test_no_survivor_failover_releases_dead_lease`, the production-path guard, and `test_failover_transfer_is_atomic`. |

**The sound spine kept through the build:** DB-side lease lifecycle (single Postgres
`now()` clock; `lease_id` fencing); additive expand/contract migration (`free_slots` /
`gpu_slots_claim_idx` untouched, reversible); slice ordering DB → readers → writers;
hermetic-default + env-guarded real-Postgres split; the `di --json` subprocess boundary
(BC1 acts on the `Popen` handle, never imports the Node engine).

## BC1 residual (stated plainly — the build does NOT eliminate all physical overlap)

BC1's literal phrasing ("terminate the child before **any** second consumer can use the
GPU") is **not fully achievable client-side** under the RFC's autonomous-deadman design:
deadman recovery *requires* that a second consumer can claim the instant a lease expires
(a frozen consumer cannot release its own lease). So a **fully frozen** consumer (its
renew loop itself stalled) or a zombie-reclaim race can let a `di --json` child
physically outlive its lease until the OS / monitor reaps it, bounded by the renew
interval / TTL. This is the **irreducible client-side deadman residual the RFC already
accepts** (its failure table: a "frozen-but-TCP-alive consumer ... reaped by autonomous
expiry"). The hard guarantee against frozen-consumer overlap needs a **server-side /
OS-level fence** — a GPU cgroup kill, or a claim handshake that waits for the
predecessor's confirmed termination — which is **explicitly OUT OF SCOPE for v1** and
recorded as the follow-up. BC1-A delivers the achievable guarantee: a *healthy* consumer
that loses its lease aborts its child within one renew interval (TTL/3 = 15s), well
inside the TTL margin. The DB-only two-transaction concurrency test remains necessary
but **not sufficient** for the exactly-one-holder-at-any-instant invariant; BC1-A's
in-flight-abort test is the one that gates accept.

## EXACT operator deployment steps

**The build performs NONE of these.** No migration was applied; no connection to the
live `gpu_fleet` DB was made; `gpu-fleet-heartbeat` was not restarted; peecee / the GPU /
`marker` were not touched. The operator performs the rollout **after** integration, in
the RFC's mandated order (DB → readers → writers):

1. **Confirm green on the integrated tree:**
   `python3 -m pytest tests/ -q` is green (expect `52 passed, 1 skipped` hermetically;
   the 1 skip is the guarded ephemeral-Postgres module). Run with an interpreter that has
   `pytest` + `psycopg`.

2. **DB — apply migration 007:** apply `migrations/007_exclusive_slot_leases.sql` to the
   live `gpu_fleet` DB. It is purely additive, so it is **safe with `gpu-fleet-heartbeat`
   running**; `stop → migrate → start` is optional and equally safe. Use the
   **stop → migrate → start** sequence for `gpu-fleet-heartbeat` only if the change
   alters `probe_model` / sentinels — **migration 007 does not** (it only adds `capacity`
   + lease columns and an index), so migrate-before-restart is sufficient here.

3. **Re-deploy the wrapper if it changed:** `cp bin/di-fleet ~/.local/bin/` **only if
   `bin/di-fleet` changed** — in this build `bin/di-fleet` is **unchanged**, so this step
   is a no-op this time. (Listed because the prompt's checklist includes it; deploy the
   new `pick_slot.py` and `di_fleet.py` to wherever they are run from.)

4. **Restart the service:** `systemctl --user restart gpu-fleet-heartbeat`.

**Rollout order recap:** DB (apply 007) → readers (new `pick_slot.py`; still emits
`free_slots`) → writers/consumers (new `di_fleet.py`; begins claiming / renewing /
releasing with the BC1-A in-flight abort active). The heartbeat writer needs **no
change** in v1. The contract migration **008** (drops `free_slots` / `gpu_slots_claim_idx`)
is out of scope and happens only after the heartbeat stops writing `free_slots`.

**Reversibility (before any consumer has claimed):**

```sql
DROP INDEX IF EXISTS gpu_slots_lease_pick_idx;
ALTER TABLE gpu_slots
  DROP COLUMN IF EXISTS lease_id,
  DROP COLUMN IF EXISTS lease_holder,
  DROP COLUMN IF EXISTS lease_expires,
  DROP COLUMN IF EXISTS capacity;
```

`free_slots` was never touched, so rollback restores the exact prior schema and behavior.
