---
schema_version: "striatum.handoff.v1"
artifact_kind: "handoff"
---

# CLAIM_LEDGER — RFC 0001 build (exclusive slot leases)

author: author-claude-opus-4.8-003

Build of `docs/rfc/0001-exclusive-slot-leases.md` per `COMMITTED_PLAN.md`, with BC1
discharged to the achievable, testable scope in `PRIOR_FINDINGS_AND_BC1_SCOPE.md`
(which supersedes BC1's literal wording). The default suite stays green and hermetic;
no live infra was touched.

> **Attempt 3 — atomic-failover fix (author-claude-opus-4.8-003).** The cycle-1 verifier
> (`reviewer-openai-codex-gpt-5.5-002`, `review/VERIFICATION_REVIEW.md`) returned
> `needs_revision` on **one** blocking finding: the production `dispatch()` failover
> bypassed the atomic transfer. `failover_transfer()` existed and was tested directly,
> but runtime failover released the dead shard's lease in `run_leased_shard`'s `finally`
> and then did a **separate, independent** `claim()` on the retry — a release-now,
> claim-later sequence on autocommit conns, not the single-transaction release+claim the
> RFC gate / BC4 require. Everything else verified clean (BC1-A, the honest BC1 falsifier,
> BC2, BC3, migration additivity, the `di --json` boundary, live-infra safety) and is
> **kept unchanged**. This attempt wires runtime failover through the atomic primitive:
>
> - `run_leased_shard` now raises `ShardDied` (carrying the still-held `lease_id`) when
>   the child dies while we still hold the lease, instead of releasing inline — so the
>   dead lease is **never released before the replacement claim is secured**.
> - new `run_failover_shard` performs `failover_transfer(dead_lease, [survivor])` on a
>   **single non-autocommit transfer conn, committed once** (release dead + claim survivor
>   atomically), then runs the retry child under the transferred lease.
> - `dispatch` gained a `failover_fn` seam; `main()` wires it to `run_failover_shard` with
>   a dedicated non-autocommit transfer-conn factory. A plain injected `shard_fn` with no
>   `failover_fn` keeps the old reassign-and-retry behavior (the hermetic non-lease tests).
> - new production-path guard `test_di_fleet.py::test_dispatch_failover_routes_through_atomic_transfer_not_release_then_claim`
>   fails if the dead lease is released outside the atomic transfer (proven to catch the
>   release-now bug by a mutation check). Re-ran `python3 -m pytest tests/ -q`
>   (`/tmp/praxis-s3-venv/bin/python`) → **`52 passed, 1 skipped`**.

> **Attempt 2 re-verification (author-claude-opus-4.8-002).** Re-read the committed
> plan, the RFC, and `PRIOR_FINDINGS_AND_BC1_SCOPE.md`; re-audited every source/test
> file against the falsifiable gate; confirmed BC1-A aborts the child synchronously in
> the renew-observing path of `run_leased_shard` and that the BC1 falsifier
> (`test_lost_lease_aborts_di_child_in_renew_path`) drives the production claim seam
> with no synthetic `gpu_busy`/sleep handshake (the prior-attempt cheat).

## Verbatim test result

```
52 passed, 1 skipped in 1.26s
```

- **52 passed** = 26 pre-existing hermetic tests (unchanged) + 26 new hermetic tests
  (25 from attempts 1–2 + the attempt-3 atomic-failover production-path guard).
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
| `di_fleet.py` (mod) | C+D | Lease lifecycle (claim/renew/release/`failover_transfer`, SQL constants, `TTL_SECONDS=45`/`RENEW_SECONDS=15`) folded in (see deviation 1); `run_leased_shard` = `Popen` child + per-shard renew monitor (`_monitor`/`_run_and_settle`) that aborts the child in the renew path (BC1-A) and, on child death, raises `ShardDied` with the **still-held** lease instead of releasing it; new `run_failover_shard` runs the RFC failover as a single-transaction `failover_transfer` (release dead + claim survivor atomically, BC4) then runs the retry child under the transferred lease; `dispatch` gained a `failover_fn` seam; `main()` wires it with a dedicated non-autocommit transfer-conn factory. |
| `tests/test_pick_slot.py` (new) | B | BC2, BC3, lease-free predicate. |
| `tests/test_leases.py` (new) | C | Hermetic claim/renew/release/transfer over `FakeSlotDB`. |
| `tests/test_leases_pg.py` (new) | C | Guarded ephemeral-Postgres: true concurrency, self-expiry, fencing, transfer atomicity. |
| `tests/test_di_fleet.py` (mod) | D | BC1, K-fan-out distinct leases, BC4 failover wiring through the atomic transfer (the two leased failover tests now pass a production `failover_fn`), plus the new production-path guard `test_dispatch_failover_routes_through_atomic_transfer_not_release_then_claim`; existing non-lease tests unchanged + green. |
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
| Failover releases dead lease + claims survivor **atomically** — and the **production `dispatch()` path routes through it** (the cycle-1 blocking finding) | `test_di_fleet.py::test_dispatch_failover_routes_through_atomic_transfer_not_release_then_claim` (production-path guard: fails if the dead lease is released outside the transfer), `test_di_fleet.py::test_failover_transfer_releases_dead_and_claims_survivor`, `test_leases.py::test_failover_transfer_releases_dead_and_claims_survivor`, atomicity by `test_leases_pg.py::test_failover_transfer_is_atomic` | hermetic + ephemeral PG |
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

**Runtime failover IS the atomic transfer (attempt-3 fix; resolves the cycle-1 blocking
finding).** When a shard dies while still holding its lease, `run_leased_shard` raises
`ShardDied` carrying that lease rather than releasing it; `dispatch` hands it to
`run_failover_shard`, which calls `failover_transfer(dead_lease, [survivor])` on a single
non-autocommit transfer conn committed **once** — releasing the dead lease and claiming
the survivor in the **same transaction** — then runs the retry child under the transferred
lease. The dead lease is therefore **never released before the replacement claim is
secured**, so freed capacity never hits the open pool between the two operations (the RFC's
herd-avoidance guarantee / BC4). The no-survivor branch still frees the dead lease in that
same committed transaction (slot re-claimable immediately, not at the TTL). True
release+claim commit-or-rollback atomicity is proven against real Postgres in
`test_leases_pg.py::test_failover_transfer_is_atomic`; the production wiring is pinned
hermetically by `test_dispatch_failover_routes_through_atomic_transfer_not_release_then_claim`.

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

Two gates to confirm:

1. **BC1-A** (the standing accept gate): `run_leased_shard` aborts the child in the renew
   path (production code, via `_monitor`) and `test_lost_lease_aborts_di_child_in_renew_path`
   is honest (no synthetic `gpu_busy`/sleep wait) and green. The DB-only two-transaction
   concurrency test remains necessary but not sufficient.
2. **Atomic failover in the production path** (the cycle-1 blocking finding, now fixed):
   confirm `dispatch()` routes runtime failover through `run_failover_shard` →
   `failover_transfer` (single-transaction release+claim), that the dead lease is **not**
   released before the replacement claim is secured, and that
   `test_dispatch_failover_routes_through_atomic_transfer_not_release_then_claim` is present
   and green (it fails if the dead lease is released outside the transfer). A source search
   should now find `failover_transfer` reachable from `main()` (`dispatch(..., failover_fn=
   leased_failover)` → `run_failover_shard` → `lease_ops.failover_transfer`), not only in
   its definition and direct tests.

Re-run `python3 -m pytest tests/ -q` with a pytest+psycopg interpreter (e.g.
`/tmp/praxis-s3-venv/bin/python`); optionally set `GPU_FLEET_TEST_DB` to a throwaway
cluster to exercise the 4 ephemeral-PG tests.
