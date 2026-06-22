---
schema_version: "striatum.handoff.v1"
artifact_kind: "handoff"
---

# CLAIM_LEDGER — RFC 0001 build (exclusive slot leases)

author: author-claude-opus-4.8-001

Build of `docs/rfc/0001-exclusive-slot-leases.md` per `COMMITTED_PLAN.md`, with BC1
discharged to the achievable, testable scope in `PRIOR_FINDINGS_AND_BC1_SCOPE.md`
(which supersedes BC1's literal wording). The default suite stays green and hermetic;
no live infra was touched.

## Verbatim test result

```
51 passed, 1 skipped in 1.23s
```

- **51 passed** = 26 pre-existing hermetic tests (unchanged) + 25 new hermetic tests.
- **1 skipped** = `tests/test_leases_pg.py` (its 4 ephemeral-Postgres tests) — guarded
  OFF; runs only when `GPU_FLEET_TEST_DB` points at a throwaway cluster.
- Runner: `python3 -m pytest tests/ -q`. Run here with an interpreter that has both
  `pytest` and `psycopg` installed (`/tmp/praxis-s3-venv/bin/python`); the repo's
  pre-existing `heartbeat*` tests `import psycopg` at module top, so collection
  requires the driver present regardless of this change. The reviewer should re-run
  with any interpreter that has pytest + psycopg.

## Files changed (all inside the build write scope)

| File | Slice | What |
|---|---|---|
| `migrations/007_exclusive_slot_leases.sql` (new) | A | Additive expand: `capacity` + nullable `lease_id/lease_holder/lease_expires`, backfill, partial `gpu_slots_lease_pick_idx`. `free_slots`/`gpu_slots_claim_idx` untouched. Reversible; deploy-order + contract-migration notes in header. |
| `pick_slot.py` (mod) | B | Lease-free predicate in WHERE; warm-pref + NULL-safe stable jitter `hashtext(COALESCE(%(job)s::text,'')||node||slot_id::text)`; selects `lease_id/lease_expires/slot_id`; **keeps `free_slots` output key aliased from `capacity`** (BC2); `psycopg` import made lazy so the picker is importable for hermetic tests. |
| `di_fleet.py` (mod) | C+D | Lease lifecycle (claim/renew/release/`failover_transfer`, SQL constants, `TTL_SECONDS=45`/`RENEW_SECONDS=15`) folded in (see deviation 1); `run_leased_shard` = `Popen` child + per-shard renew monitor that aborts the child in the renew path (BC1-A); failover frees the dead lease immediately (BC4); `dispatch` shard_fn now required; `main()` claims/renews/releases around every picked slot. |
| `tests/test_pick_slot.py` (new) | B | BC2, BC3, lease-free predicate. |
| `tests/test_leases.py` (new) | C | Hermetic claim/renew/release/transfer over `FakeSlotDB`. |
| `tests/test_leases_pg.py` (new) | C | Guarded ephemeral-Postgres: true concurrency, self-expiry, fencing, transfer atomicity. |
| `tests/test_di_fleet.py` (mod) | D | BC1, K-fan-out distinct leases, BC4 failover wiring (existing 11 tests unchanged + green). |
| `tests/test_lease_no_consumer_clock.py` (new) | E | Source/AST inspection: lease SQL uses `now()`; lease functions read no Python clock. |
| `tests/lease_fakes.py` (new) | — | `FakeSlotDB` (models the real lease SQL with a controllable clock) + `FakeChild`. Non-`test_` module, not collected. |

## Migration

`migrations/007_exclusive_slot_leases.sql` — **007** because `006_peecee_dense_27b.sql`
already exists on master (per the task). Purely additive (ADD COLUMN / one backfill
UPDATE / one partial index); renames and drops nothing; reversible before any consumer
claims (DROP statements in the header). The out-of-scope contract migration (future
008) that drops `free_slots`/`gpu_slots_claim_idx` is documented but **not built**.
Not applied to any database by this build.

## Falsifiable gate → test map

| RFC / BC gate item | Test | Kind |
|---|---|---|
| Two concurrent consumers on a capacity-1 slot → **exactly one** holds | `test_leases_pg.py::test_two_concurrent_claims_exactly_one_wins` (+ hermetic companion `test_leases.py::test_claim_returns_none_when_predicate_unmet`) | ephemeral PG + hermetic |
| **BC1 — in-flight abort:** a lost lease terminates the running `di --json` child **in the renew path** (DB-only test necessary but not sufficient) | `test_di_fleet.py::test_lost_lease_aborts_di_child_in_renew_path` (+ focused `::test_failed_renew_aborts_shard`) | **hermetic — the BC1 gate the verifier confirms** |
| Consumer stops renewing → slot free within ≤ TTL, no reaper | `test_leases_pg.py::test_unrenewed_lease_self_expires` (+ `test_leases.py::test_renew_false_after_autonomous_expiry`) | ephemeral PG + hermetic |
| Zombie renew after re-claim → zero rows (fenced) | `test_leases_pg.py::test_zombie_renew_after_reclaim_is_fenced` (+ `test_leases.py::test_zombie_renew_after_reclaim_is_fenced`) | ephemeral PG + hermetic |
| K-fan-out across N slots holds **N distinct** leases | `test_di_fleet.py::test_kfanout_claims_n_distinct_leases` | hermetic |
| Failover releases dead lease + claims survivor **atomically** | `test_di_fleet.py::test_failover_transfer_releases_dead_and_claims_survivor`, `test_leases.py::test_failover_transfer_releases_dead_and_claims_survivor`, atomicity by `test_leases_pg.py::test_failover_transfer_is_atomic` | hermetic + ephemeral PG |
| **BC4 — no-survivor failover** frees the slot immediately (not after TTL) | `test_di_fleet.py::test_no_survivor_failover_releases_dead_lease` (+ `test_leases.py::test_failover_transfer_no_survivor_releases_dead_lease_immediately`) | hermetic |
| **No consumer wall-clock** in claim/renew/release | `test_lease_no_consumer_clock.py` (2 tests) | hermetic (inspection) |
| **BC2 — pick_slot backward-compat** (`free_slots` key preserved) | `test_pick_slot.py::test_output_still_contains_free_slots` | hermetic |
| **BC3 — NULL-safe jitter** for `job=''` and `job=None` | `test_pick_slot.py::test_jitter_active_for_empty_and_none_job` | hermetic |

## BC1 — exactly how it is discharged (per the operator scope)

- **BC1-A (responsive abort, code, REQUIRED).** `di_fleet.run_leased_shard` replaces the
  old blocking `subprocess.run` with `subprocess.Popen` (stdout/stderr to temp files so
  a chatty child can't deadlock the monitor). A single per-shard loop OWNS the child
  handle: every `RENEW_SECONDS` (TTL/3 = 15s) it renews; **when `renew` returns zero
  rows it terminates the child synchronously, right there in the renew-observing path**
  — not on a later independent poll, not via a flag. It acts only on the `Popen` handle
  (`terminate()`/`kill()`); it never imports the Node engine.
- **BC1-test (honest falsifier, hermetic, REQUIRED).**
  `test_lost_lease_aborts_di_child_in_renew_path` drives the **production** path: the
  loss is a real autonomous-expiry event in `FakeSlotDB` and the successor claims via
  the **real** `claim`/`LEASE_CLAIM_SQL` seam — there is **no test-only
  `gpu_busy`/sleep handshake** (the specific cheat the prior attempt was rejected for).
  It asserts the predecessor's child is terminated **as a consequence of** the lost
  renew; it does **not** assert a happens-before the code cannot enforce.
- **BC1-residual (documented, accepted for v1).** This is a client-side deadman. A
  *fully frozen* consumer (its renew loop itself stalled) or a zombie-reclaim race can
  let a child physically outlive its lease until the OS/monitor reaps it, bounded by the
  renew interval / TTL — the exact case the RFC's own failure table accepts. The build
  does **NOT** eliminate all physical overlap; the hard guarantee needs a server-side /
  OS-level fence (GPU cgroup kill, or a claim handshake that waits for the predecessor's
  confirmed termination) and is **explicitly out of scope for v1**. Stated in the
  `run_leased_shard` docstring and here; the final report must restate it plainly.

## Deviations from the committed plan (called out, not silently widened)

1. **`leases.py` folded into `di_fleet.py`.** The plan's Slice C placed the lease
   lifecycle in a new top-level `leases.py`, but the frozen build **write scope** lists
   root files `di_fleet.py`/`pick_slot.py`/`heartbeat.py`/`heartbeat_all.py`/`conftest.py`
   and dirs `migrations/`/`bin/`/`tests/` — **not** a new `leases.py`. Per the envelope
   rule (don't assume the frozen scope widens), the lifecycle lives in `di_fleet.py`
   (its only consumer) as a clearly-delineated "slot-lease lifecycle" section with the
   same pure-functions-over-injected-`conn` discipline. All claim/renew/release/transfer
   behavior, SQL, and tests are unchanged in substance.
2. **README deploy note → migration header instead.** Slice E mentioned a `README.md`
   deploy-ordering note; `README.md` is **outside the write scope**, so the operator
   deploy ordering is recorded in the `007_*.sql` header and in §"Operator deploy" below
   rather than in the README.
3. **Single-slot path now leases (buffers instead of `exec`).** The old `main()` `exec`'d
   `di` for a single picked slot. An `exec`'d process can't run the in-process renew
   monitor + release that exclusivity (and BC1-A) require, so the single-slot case now
   runs through the leased dispatch path and buffers di's output like the N>1 fan-out.
   The **no-fleet fallback still `exec`s** (nothing to lease there). UX cost: the
   single-slot run no longer streams di output live.

`failover_transfer` (the RFC's atomic release+claim primitive) is implemented and tested
(hermetic + PG atomicity). di-fleet's *runtime* failover frees the dead shard's lease
immediately (release in `run_leased_shard`'s `finally`) and re-pins the dead frames to a
freed survivor; `failover_transfer` is the atomic single-transaction primitive backing
the RFC's herd-avoidance guarantee and the capacity>1 evolution.

## Live-infra safety

No migration applied; no connection to the live `gpu_fleet` DB; `gpu-fleet-heartbeat`
untouched and unrestarted; no peecee/GPU/`marker` access. The `di --json` shell-out
boundary is intact (abort operates on the `Popen` handle; the Node engine is never
imported). The ephemeral-PG tests refuse to run against `dbname=gpu_fleet` and default
OFF. `bin/di-fleet` is unchanged.

## Operator deploy (post-integration — the build performs NONE of these)

1. **DB:** apply `migrations/007_exclusive_slot_leases.sql` (additive ⇒ safe with the
   heartbeat running; stop→migrate→start optional and equally safe).
2. **Readers:** deploy the new `pick_slot.py` (picks lease-free slots; still emits
   `free_slots`).
3. **Writers/consumers:** deploy the new `di_fleet.py`; re-deploy the wrapper with
   `cp bin/di-fleet ~/.local/bin/` — begins claiming/renewing/releasing with the BC1-A
   in-flight abort active.

No heartbeat change in v1. The contract migration 008 (drops `free_slots`) is out of
scope and happens only after the heartbeat stops writing it.

## For the verifier

The accept gate is **BC1-A**: confirm `run_leased_shard` aborts the child in the renew
path (production code) and that `test_lost_lease_aborts_di_child_in_renew_path` is honest
(no synthetic wait) and green. The DB-only two-transaction concurrency test remains
necessary but not sufficient. Re-run `python3 -m pytest tests/ -q` with a pytest+psycopg
interpreter; optionally set `GPU_FLEET_TEST_DB` to a throwaway cluster to exercise the 4
ephemeral-PG tests.
