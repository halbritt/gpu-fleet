---
schema_version: "striatum.synthesis.v1"
artifact_kind: "handoff"
---

# CLAIM_LEDGER — RFC 0002: Zero-touch node lifecycle (build)

author: author-claude-opus-4.8-001

This is the build handoff for RFC 0002. It executes the committed build plan
(`striatum/campaign/rfc-0002/design/COMMITTED_PLAN.md`) as ordered, additive slices,
maps **every** falsifiable-gate bullet and **every** binding constraint (BC1–BC8) to the
test that proves it, and records the verbatim pytest result lines this run produced. The
reviewer re-runs the tests and the gate independently; this ledger is the map, not the
acceptance.

## What this run did (re-execution against the committed source + MUST-FIX verification)

The committed plan's slices are realized in the source on this build branch
(migration `009` + the four source files + the new/extended tests). This run re-executed
the build contract and, per `PRIOR_FINDINGS.md`, **re-verified the two items the prior
canceled attempt was correctly rejected on** — the write-time single-writer fence
(MUST-FIX 1 / BC1·C9) and BC8 option (a). Both are present, correct, and now proven green
against a real Postgres gate:

1. **Single-writer race — write-time driver-lease fence (MUST-FIX 1, was the blocking
   finding).** The puller re-validates the per-node driver-lease at **WRITE time**, not
   only at FETCH time, via `heartbeat_all.PULL_WRITE_GUARD` / `pull_write()`
   (`heartbeat_all.py:198,207`): a `SELECT … FOR UPDATE` on the node's `fleet_nodes` row,
   in the **same transaction** as the `UPSERT`, that **serializes against the self-push
   `NODE_LEASE_CAS`** and writes **ZERO rows** when a fresh push-lease owns the node;
   `tick()` routes every probed write through it (`heartbeat_all.py:240`). The exact
   `FETCH → pusher NODE_LEASE_CAS → UPSERT` interleaving the verifier reproduced (puller
   fetches the node as eligible, a self-pusher then wins the lease and writes, the
   puller's later stale pull write must NOT land) is proven by the **two-real-transaction**
   PG test `test_lifecycle_pg.py::test_pull_yields_when_push_acquires_after_fetch` — the
   puller (the loser) writes zero rows, the registry keeps the pusher's row
   (`served_model='m-PUSH'`, `boot_epoch=4242`), and the puller RESUMES once the lease
   lapses — plus hermetic structural guards in `test_driver_lease.py`. Exactly one
   committed writer per `(node, slot)` in the contending tick.
2. **BC8 — peecee pull-only liveness, option (a) (MUST-FIX 2).** peecee's cross-host SSH
   `nvidia-smi` leg is **NOT retired** in v1: `ollama_ondemand_liveness` still calls
   `gpu_stats(...)` first and **fails closed** when the GPU read errors
   (`heartbeat.py:257–258`, `return False, None, None` before the residency/headroom
   branches), so removing the SSH leg would de-list peecee. No `probe_node` / `gpu_stats`
   / `ollama_ondemand_liveness` change, no operator SSH-retirement step, and the committed
   plan ships no false "HTTP-only liveness" claim (§2-step-2/§4/§5/Q5). Proven by
   `test_load_aware_liveness.py` (the de-list-under-marker suite) + `::test_pull_only_node_has_no_db_path`.

**No source/test/migration change was required by this run** — the committed-plan
implementation already satisfies the gate and both MUST-FIX items; the working-tree change
in this run is this ledger only. The pytest results below were produced by re-running the
suites against the committed source on a freshly-built, then destroyed, ephemeral Postgres
17 cluster.

**Residual, documented honestly (bounded, ratchet-safe, by design).** Registration =
first heartbeat keeps the self-push write **unconditional** (BC1), so a single pull→push
*handoff* tick — where the puller legitimately writes a node an instant before a recovering
self-pusher takes it over — can briefly overlap. This is the intended ownership transition,
not split-brain: the write-time guard closes the realistic seconds-wide race (a healthy
self-pusher holding a fresh lease while the puller writes from a stale fetch); the
boot-epoch ratchet (strict `>`) + `COALESCE` keep the row consistent; and the next tick is
single-writer. Eliminating even that one-tick overlap would require gating the self-push
registration write, which would re-open the BC1 zero-touch deadlock the committed plan
forbids.

## Verbatim pytest result (this run, re-run against the committed source)

- **Hermetic default** (`python3 -m pytest tests/ -q`, no `GPU_FLEET_TEST_DB`):
  **`80 passed, 3 skipped`** — green and hermetic; the 3 skips are the PG-guarded modules
  (`test_leases_pg`, `test_epoch_pg`, `test_lifecycle_pg`), which skip cleanly when no
  ephemeral cluster is provided.
- **Full PG-guarded run** (against a throwaway `dbname=gpu_fleet_test` cluster — the
  designed verification path; applies the real migration chain 001–009): **`99 passed`**
  (the same 80 hermetic + 19 PG tests, including the two-transaction single-writer race
  and both anti-lie halves). Run on an **isolated, disposable** Postgres 17 cluster (own
  data dir, **unix-socket only, no TCP**, `fsync=off`) that was **destroyed** after the
  run; the live `gpu_fleet` DB and the heartbeat driver were never touched. The PG modules
  refuse any non-ephemeral DB by guard (dbname must contain `test`, never bare `gpu_fleet`).

### Reproducing the PG gate (for the reviewer)

`initdb` is not on `PATH` but ships at `/usr/lib/postgresql/17/bin`:

```bash
PGBIN=/usr/lib/postgresql/17/bin
BASE=$(mktemp -d /tmp/gpu-fleet-rfc0002-pg.XXXXXX); PGDATA=$BASE/data
$PGBIN/initdb -D "$PGDATA" -U postgres --auth=trust -E UTF8 >/dev/null
$PGBIN/pg_ctl -D "$PGDATA" -o "-k $PGDATA -c listen_addresses='' -c fsync=off" -w start
$PGBIN/createdb -h "$PGDATA" -U postgres gpu_fleet_test
GPU_FLEET_TEST_DB="dbname=gpu_fleet_test host=$PGDATA user=postgres" python3 -m pytest tests/ -q
$PGBIN/pg_ctl -D "$PGDATA" -w stop && rm -rf "$BASE"     # destroy the throwaway cluster
```

## Migration

- **`migrations/009_zero_touch_lifecycle.sql`** (new; the lowest unused number — 001–008
  are landed, the RFC body's "006" is stale per plan C1). Purely additive, reversible,
  behavior-neutral until Slice 4: on `gpu_slots` adds `status` (CHECK
  unverified/probationary/routable/demoted, default `unverified`), `probe_streak`,
  `gpu_uuid`, `boot_epoch`, and **backfills every existing row to `routable`**; on
  `fleet_nodes` adds `driven_by`/`lease_until`; creates the single-row `fleet_meta`
  (column **`holder`**, BC5) and the `routable_slots` view **alongside** `live_slots`
  (expand/contract — `live_slots` is not dropped). Reverse block included. C1, C2.

## Files realized by the build (all within the declared write scope)

| File | Change | Slice |
|------|--------|-------|
| `migrations/009_zero_touch_lifecycle.sql` | new additive DDL (above) | 0 |
| `heartbeat.py` | revised `UPSERT` (seed-quarantine INSERT + BC2/BC6/BC7 conflict CASE + strict-`>` ratchet WHERE); `next_boot_epoch()` (strictly-monotonic-per-write token); `gpu_stats` captures `gpu_uuid`; `--push` mode (stamp `boot_epoch`, non-gating `NODE_LEASE_CAS`); `GRADUATION_STREAK=3`, `NODE_LEASE_TTL=30` | 1, 3 |
| `heartbeat_all.py` | `FETCH` gains server-side lease predicate (`driven_by IS NULL OR now() >= lease_until`); **`PULL_WRITE_GUARD`/`pull_write()` — WRITE-time per-node lease re-check (`SELECT … FOR UPDATE`, serializes against the push CAS; yields → zero rows when push-held); `tick()` routes every probed write through it** (single-writer race fix, C9); `probe_node`/`_failed_row` carry `gpu_uuid` + `boot_epoch=NULL`; **stale-only `PRUNE`** (C3-PRUNE); puller-lease `PULLER_LEASE_CAS`/`acquire_puller_lease`/`puller_id`, `PULLER_LEASE_TTL=15`; `tick`/`main` peer-runnable wrapper (`--no-puller-lease` escape) | 1, 2, 3 |
| `pick_slot.py` | `PICK` adds `AND status = 'routable'` (`pick_slot.py:32`) | 4 |
| `di_fleet.py` | `LEASE_CLAIM_SQL` adds `AND status = 'routable'` (`di_fleet.py:108`; renew/release unchanged) | 4 |
| `tests/test_graduation.py` | hermetic — graduation/ratchet/uuid via `FakeRegistryDB` over the real `UPSERT` + SQL inspection | — |
| `tests/test_puller_lease.py` | hermetic — puller-lease CAS via `FakeMetaDB` over the real CAS | — |
| `tests/test_driver_lease.py` | hermetic — FETCH/CAS server-side-clock + non-gating-CAS inspection; **+ write-time `PULL_WRITE_GUARD`/`pull_write` structural guards** | — |
| `tests/test_lifecycle_pg.py` | PG-guarded — composed register+graduate, ratchet, hot-swap, failover, single-writer (FETCH-time **and** the **two-transaction write-time race**), anti-lie (never-graduates **and** routes-only-measured) against real migrations | — |
| `tests/test_load_aware_liveness.py` | `test_pull_only_node_has_no_db_path` (BC8/K) | — |
| `tests/lease_fakes.py` | `FakeSlotDB` carries `status` (default `routable`) + claim gate models it | — |
| `tests/test_leases_pg.py` / `tests/test_epoch_pg.py` | apply the real migration chain incl. `009`; `_hb_row` carries `gpu_uuid`/`boot_epoch`; seeded slots graduated to `routable` so the Slice-4 gate evaluates `True` | — |

`bin/di-fleet` is **unchanged** (a thin `exec python3 di_fleet.py` wrapper). The operator
re-deploy is just updating the gpu-fleet checkout on consumer hosts so the new
`di_fleet.py`/`pick_slot.py` take effect — `bin/di-fleet` itself is byte-identical.

## Falsifiable gate → proving test

| RFC gate bullet | Test(s) | Kind |
|---|---|---|
| **No SPOF** (kill the puller-lease holder ⇒ another drives within ≤ TTL; fleet does not age out) | `test_puller_lease.py::test_cas_grants_one_then_deadman_failover`; `test_lifecycle_pg.py::test_puller_failover_no_ageout` | hermetic + PG |
| **Zero-touch register** (self-report with no `fleet_nodes` row ⇒ `unverified`, graduates after N) | `test_graduation.py::test_streak_promotes_after_N_and_demotes_on_break`; `test_lifecycle_pg.py::test_self_push_no_fleet_node_registers_and_graduates` (composed Slice-1+3) | hermetic + PG |
| **Anti-lie**, two literal halves — (a) a node that never serves **never graduates**; (b) a real small GPU graduates but **routes only measured** | (a) `test_graduation.py::test_failing_or_cold_probe_never_increments_streak` + `test_lifecycle_pg.py::test_failed_probe_big_declared_never_graduates`; (b) `test_lifecycle_pg.py::test_big_declared_small_measured_routes_only_measured` | hermetic + PG |
| **Single writer** (proximal-driver vs self-push ⇒ exactly one writer; the other writes zero rows) — **FETCH-time skip + WRITE-time race guard** | `test_driver_lease.py::test_fetch_predicate_skips_fresh_lease` + `::test_pull_write_guard_revalidates_lease_server_side` + `::test_tick_writes_through_the_single_writer_guard`; `test_lifecycle_pg.py::test_push_and_pull_never_both_write` (FETCH-time) + **`::test_pull_yields_when_push_acquires_after_fetch`** (two-transaction write-time race) | hermetic + PG |
| **Identity survives churn** (rebooted node re-presents `gpu_uuid`, skips re-quarantine) | `test_graduation.py::test_matching_uuid_carries_routable_forward`; `test_lifecycle_pg.py::test_reboot_same_uuid_skips_requarantine` | hermetic + PG |
| **peecee runs zero fleet code/creds, still monitored (pull), de-listed when marker owns card** | `test_load_aware_liveness.py` (existing de-list suite, option (a)) + `::test_pull_only_node_has_no_db_path` | hermetic |
| **No node wall-clock** trusted for `heartbeat_ts` (inspection) | `test_graduation.py::test_upsert_stamps_heartbeat_ts_from_db_clock` | hermetic |

## Binding constraints (the build's verify gate)

| BC | Restated claim | Proving test(s) | Final review |
|----|----------------|-----------------|--------------|
| **BC1** | Per-node lease CAS is **non-gating**; the UPSERT runs unconditionally; a no-`fleet_nodes` self-push registers `unverified` and graduates (C9 preserved) | `test_driver_lease.py::test_push_lease_cas_does_not_gate_the_upsert`; `test_lifecycle_pg.py::test_self_push_no_fleet_node_registers_and_graduates` | **required** |
| **BC2** | `boot_epoch = COALESCE(EXCLUDED.boot_epoch, gpu_slots.boot_epoch)` — a NULL pull write never erases the ratchet; a strictly-stale write stays refused | `test_lifecycle_pg.py::test_boot_epoch_survives_null_pull_write`; `test_graduation.py::test_ratchet_predicate_is_strict_gt` (COALESCE assert) | **required** |
| **BC6** | Ratchet WHERE is **strict `>`** (never `>=`); equal-epoch replay is a no-op (no field moves, `heartbeat_ts` not re-stamped) | `test_graduation.py::test_ratchet_predicate_is_strict_gt` + `::test_equal_epoch_replay_is_a_noop_then_greater_is_accepted`; `test_lifecycle_pg.py::test_equal_epoch_replay_is_noop` | **required** |
| **BC7** | `probe_streak`→1 and `status`→`unverified` when both uuids non-NULL and differ; trust carries on matching/unknown uuid | `test_graduation.py::test_uuid_mismatch_resets_streak_and_demotes`; `test_lifecycle_pg.py::test_hot_swap_demotes_to_unverified` | **required** |
| **BC3** | `PULLER_LEASE_TTL = 15` s, strictly `< 45` s | `test_puller_lease.py::test_puller_lease_ttl_is_below_the_ageout_window`; `test_lifecycle_pg.py::test_puller_failover_no_ageout` | not required |
| **BC4** | Per-node lease freshness evaluated **server-side** (`now() >= lease_until`); no client clock — at FETCH time **and** at the WRITE-time race guard | `test_driver_lease.py::test_fetch_freshness_uses_db_now_no_client_clock` + `::test_node_lease_cas_freshness_is_db_now` + `::test_pull_write_guard_revalidates_lease_server_side` | not required |
| **BC5** | `fleet_meta` column is **`holder`** verbatim in DDL, CAS, and tests | `test_puller_lease.py` + `test_lifecycle_pg.py::test_puller_failover_no_ageout` run the real CAS on the real `009` `fleet_meta` (a name divergence ⇒ `column does not exist`) | not required |
| **BC8** | Option (a) committed: peecee keeps SSH-via-pull liveness; no false "HTTP-only liveness" claim and no de-listing SSH-retirement step ship; peecee still de-lists when marker owns the card | `test_load_aware_liveness.py` (de-list) + `::test_pull_only_node_has_no_db_path`; committed-plan text inspection (§2/§4/§5/Q5 carry no SSH-retirement step) | **required** |

## Live-infra safety (preserved)

The build is **inert** w.r.t. live infra: it writes `migrations/009`, edits the four
source files + tests, and runs the suites. The PG gate was verified on a **throwaway**
Postgres 17 cluster (unix-socket only, no TCP, `fsync=off`) that was then **destroyed**; it
never connected to the live `gpu_fleet` DB, never ran `systemctl`/restarted any heartbeat
service, and never touched peecee or its GPU. `epoch` (RFC-0003) is byte-unchanged (C7,
`heartbeat.py:77`); `live_slots` is preserved; the `di --json` subprocess boundary is
untouched; **no SSH-retirement step ships in v1** (BC8 option (a)).

## Handoff to verify

- Re-run `python3 -m pytest tests/ -q` (hermetic) and, for the PG gate, against an
  ephemeral `GPU_FLEET_TEST_DB` (see the reproduction block above; the suite applies the
  real migration chain `001–009`).
- Required at final review: **BC1, BC2, BC6, BC7** (discharge tests green; the ratchet
  `>` never weakened to `>=`) and **BC8** (peecee stays pull-monitored, de-lists under
  marker; no false HTTP-only-liveness claim / no de-listing step).
- Do not re-open the RFC's settled design.
