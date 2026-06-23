---
schema_version: "striatum.synthesis.v1"
artifact_kind: "handoff"
---

# CLAIM_LEDGER — RFC 0002: Zero-touch node lifecycle (build)

author: author-claude-opus-4.8-002

This is the build handoff for RFC 0002. It executes the committed build plan
(`striatum/campaign/rfc-0002/design/COMMITTED_PLAN.md`) as ordered, additive slices,
maps **every** falsifiable-gate bullet and **every** binding constraint (BC1–BC8) to the
test that proves it, and records the verbatim pytest result lines. The reviewer re-runs
the tests and the gate independently; this ledger is the map, not the acceptance.

## Revision — attempt 2 (addressing the verification review)

Attempt 1 was returned **`needs_revision`** by the reviewer
(`striatum/campaign/rfc-0002/build/review/VERIFICATION_REVIEW.md`,
`reviewer-openai-codex-gpt-5.5-001`) with two findings, both fixed here:

1. **BLOCKING — Single-writer not enforced under the fetch-before-CAS race.** Attempt 1
   skipped a push-held node only at the puller's `FETCH`, then probed (seconds) and wrote
   every fetched row unconditionally. A self-pusher acquiring the per-node lease *during*
   that probe window left both writers landing the same `(node, slot)` row in the
   contending tick. **Fix:** the puller now re-validates the per-node driver-lease at
   **WRITE time**, in one transaction, via `heartbeat_all.PULL_WRITE_GUARD` /
   `pull_write()` — a `SELECT … FOR UPDATE` on the `fleet_nodes` row that **serializes
   against the self-push `NODE_LEASE_CAS`** and writes ZERO rows when a fresh push-lease
   owns the node. `tick()` routes every probed write through it. Proven by the new
   **two-real-transaction** test `test_lifecycle_pg.py::test_pull_yields_when_push_
   acquires_after_fetch` (the loser — the puller — writes zero rows; the registry keeps
   the pusher's row) plus the hermetic structural guards in `test_driver_lease.py`.
2. **Anti-lie gate wording.** Attempt 1's `test_big_declared_small_measured_not_routable`
   proved measured-routing but advanced the node to `routable`, contradicting the RFC's
   literal "never graduates." **Fix:** the RFC gate's two halves are now proven
   separately — `test_failed_probe_big_declared_never_graduates` (a node that never
   actually serves never graduates / never routable — the **never-graduates** half) and
   the renamed `test_big_declared_small_measured_routes_only_measured` (a real small GPU
   graduates per Q2 but routes only its **measured** throughput — the **routes-only-
   measured** half), with the hermetic `test_failing_or_cold_probe_never_increments_streak`.

**Residual, documented honestly (bounded, ratchet-safe):** registration = first heartbeat
keeps the self-push write **unconditional** (BC1), so a single pull→push *handoff* tick —
where the puller legitimately writes a node an instant before a recovering self-pusher
takes it over — can briefly overlap. This is the intended ownership transition, not
split-brain: the boot-epoch ratchet (strict `>`) + `COALESCE` keep the row consistent and
the next tick is single-writer. Eliminating even that one-tick overlap would require
gating the self-push registration write, which would re-open the BC1 zero-touch deadlock.
The write-time guard closes the realistic, seconds-wide race the reviewer identified (a
healthy self-pusher holding its lease while the puller writes from a stale fetch).

## Verbatim pytest result

- **Hermetic default** (`python3 -m pytest tests/ -q`, no `GPU_FLEET_TEST_DB`):
  **`80 passed, 3 skipped in 1.27s`** — green and hermetic; the 3 skips are the
  PG-guarded modules (`test_leases_pg`, `test_epoch_pg`, `test_lifecycle_pg`), which skip
  cleanly when no ephemeral cluster is provided. (78 → 80: the two new hermetic
  write-time single-writer-guard structural tests in `test_driver_lease.py`.)
- **Full PG-guarded run** (against a throwaway `dbname=gpu_fleet_test` cluster, the
  designed verification path — applies the real migrations 001–009): **`99 passed in
  5.23s`** (the same 80 hermetic + 19 PG tests). 95 → 99: +2 hermetic guards above and +2
  new PG tests (the two-transaction single-writer race + the never-graduates anti-lie
  half). Run on an **isolated, disposable** Postgres cluster (own data dir, own unix
  socket, no TCP, port 54330); the live `gpu_fleet` DB and the `gpu-fleet-heartbeat`
  service were never touched, and the cluster was destroyed after the run. The PG modules
  refuse any non-ephemeral DB by guard.

## Migration

- **`migrations/009_zero_touch_lifecycle.sql`** (new; the lowest unused number — 001–008
  are landed, the RFC body's "006" is stale). Purely additive, reversible, behavior-
  neutral until Slice 4: on `gpu_slots` adds `status` (CHECK
  unverified/probationary/routable/demoted, default `unverified`), `probe_streak`,
  `gpu_uuid`, `boot_epoch`, and **backfills every existing row to `routable`**; on
  `fleet_nodes` adds `driven_by`/`lease_until`; creates the single-row `fleet_meta`
  (column **`holder`**, BC5) and the `routable_slots` view **alongside** `live_slots`
  (expand/contract — `live_slots` is not dropped). Reverse block included. C1, C2.

## Files changed (all within the declared write scope)

| File | Change | Slice |
|------|--------|-------|
| `migrations/009_zero_touch_lifecycle.sql` | new additive DDL (above) | 0 |
| `heartbeat.py` | revised `UPSERT` (seed-quarantine INSERT + BC2/BC6/BC7 conflict CASE + strict-`>` ratchet WHERE); `next_boot_epoch()` (strictly-monotonic-per-write token); `gpu_stats` captures `gpu_uuid`; `--push` mode (stamp `boot_epoch`, non-gating `NODE_LEASE_CAS`); `GRADUATION_STREAK=3`, `NODE_LEASE_TTL=30` | 1, 3 |
| `heartbeat_all.py` | `FETCH` gains server-side lease predicate (`driven_by IS NULL OR now() >= lease_until`); **`PULL_WRITE_GUARD`/`pull_write()` — WRITE-time per-node lease re-check (`SELECT … FOR UPDATE`, serializes against the push CAS; yields → zero rows when push-held); `tick()` routes every probed write through it** (single-writer race fix, C9); `probe_node`/`_failed_row` carry `gpu_uuid` + `boot_epoch=NULL`; **stale-only `PRUNE`** (C3-PRUNE); puller-lease `PULLER_LEASE_CAS`/`acquire_puller_lease`/`puller_id`, `PULLER_LEASE_TTL=15`; `tick`/`main` peer-runnable wrapper (`--no-puller-lease` escape) | 1, 2, 3 |
| `pick_slot.py` | `PICK` adds `AND status = 'routable'` | 4 |
| `di_fleet.py` | `LEASE_CLAIM_SQL` adds `AND status = 'routable'` (renew/release unchanged) | 4 |
| `tests/test_graduation.py` | new hermetic — graduation/ratchet/uuid via `FakeRegistryDB` over the real `UPSERT` + SQL inspection | — |
| `tests/test_puller_lease.py` | new hermetic — puller-lease CAS via `FakeMetaDB` over the real CAS | — |
| `tests/test_driver_lease.py` | new hermetic — FETCH/CAS server-side-clock + non-gating-CAS inspection; **+ write-time `PULL_WRITE_GUARD`/`pull_write` structural guards (attempt 2)** | — |
| `tests/test_lifecycle_pg.py` | new PG-guarded — composed register+graduate, ratchet, hot-swap, failover, single-writer (FETCH-time **and** the new **two-transaction write-time race**), anti-lie (never-graduates **and** routes-only-measured) against real migrations | — |
| `tests/test_load_aware_liveness.py` | extended — `test_pull_only_node_has_no_db_path` (BC8/K) | — |
| `tests/lease_fakes.py` | `FakeSlotDB` carries `status` (default `routable`) + claim gate models it | — |
| `tests/test_leases_pg.py` | temp DDL gains `status` column (claim gate) | — |
| `tests/test_epoch_pg.py` | apply real 001/002/007/008/009; `_hb_row` carries `gpu_uuid`/`boot_epoch`; `_seed_routable` graduates seeded slots | — |

`bin/di-fleet` is **unchanged** (it is a thin `exec python3 di_fleet.py` wrapper). Operator
re-deploy step (note only, NOT performed): `cp bin/di-fleet ~/.local/bin/` is unnecessary —
the wrapper is byte-identical; redeploying the gpu-fleet checkout picks up the new
`di_fleet.py`/`pick_slot.py`.

## Falsifiable gate → proving test

| RFC gate bullet | Test(s) | Kind |
|---|---|---|
| **No SPOF** (kill the puller-lease holder ⇒ another drives within ≤ TTL; fleet does not age out) | `test_puller_lease.py::test_cas_grants_one_then_deadman_failover`; `test_lifecycle_pg.py::test_puller_failover_no_ageout` | hermetic + PG |
| **Zero-touch register** (self-report with no `fleet_nodes` row ⇒ `unverified`, graduates after N) | `test_graduation.py::test_streak_promotes_after_N_and_demotes_on_break`; `test_lifecycle_pg.py::test_self_push_no_fleet_node_registers_and_graduates` (composed Slice-1+3) | hermetic + PG |
| **Anti-lie**, two literal halves — (a) a node that never serves **never graduates**; (b) a real small GPU graduates but **routes only measured** | (a) `test_graduation.py::test_failing_or_cold_probe_never_increments_streak` + `test_lifecycle_pg.py::test_failed_probe_big_declared_never_graduates`; (b) `test_lifecycle_pg.py::test_big_declared_small_measured_routes_only_measured` | hermetic + PG |
| **Single writer** (proximal-driver vs self-push ⇒ exactly one writer; the other writes zero rows) — **FETCH-time skip + WRITE-time race guard** | `test_driver_lease.py::test_fetch_predicate_skips_fresh_lease` + `::test_pull_write_guard_revalidates_lease_server_side` + `::test_tick_writes_through_the_single_writer_guard`; `test_lifecycle_pg.py::test_push_and_pull_never_both_write` (FETCH-time) + **`::test_pull_yields_when_push_acquires_after_fetch`** (two-transaction write-time race) | hermetic + PG |
| **Identity survives churn** (rebooted node re-presents `gpu_uuid`, skips re-quarantine) | `test_graduation.py::test_matching_uuid_carries_routable_forward`; `test_lifecycle_pg.py::test_reboot_same_uuid_skips_requarantine` | hermetic + PG |
| **peecee runs zero fleet code/creds, still monitored (pull), de-listed when marker owns card** | `test_load_aware_liveness.py` (existing de-list suite, option (a)) + `test_load_aware_liveness.py::test_pull_only_node_has_no_db_path` | hermetic |
| **No node wall-clock** trusted for `heartbeat_ts` (inspection) | `test_graduation.py::test_upsert_stamps_heartbeat_ts_from_db_clock` | hermetic |

## Binding constraints (the build's verify gate)

| BC | Restated claim | Proving test(s) | Final review |
|----|----------------|-----------------|--------------|
| **BC1** | Per-node lease CAS is **non-gating**; the UPSERT runs unconditionally; a no-`fleet_nodes` self-push registers `unverified` and graduates (C9 preserved) | `test_driver_lease.py::test_push_lease_cas_does_not_gate_the_upsert`; `test_lifecycle_pg.py::test_self_push_no_fleet_node_registers_and_graduates` | **required** |
| **BC2** | `boot_epoch = COALESCE(EXCLUDED.boot_epoch, gpu_slots.boot_epoch)` — a NULL pull write never erases the ratchet; a strictly-stale write stays refused | `test_lifecycle_pg.py::test_boot_epoch_survives_null_pull_write`; `test_graduation.py::test_ratchet_predicate_is_strict_gt` (COALESCE assert) | **required** |
| **BC6** | Ratchet WHERE is **strict `>`** (never `>=`); equal-epoch replay is a no-op (no field moves, `heartbeat_ts` not re-stamped) | `test_graduation.py::test_ratchet_predicate_is_strict_gt` + `::test_equal_epoch_replay_is_a_noop_then_greater_is_accepted`; `test_lifecycle_pg.py::test_equal_epoch_replay_is_noop` | **required** |
| **BC7** | `probe_streak`→1 and `status`→`unverified` when both uuids non-NULL and differ; trust carries on matching/unknown uuid | `test_graduation.py::test_uuid_mismatch_resets_streak_and_demotes`; `test_lifecycle_pg.py::test_hot_swap_demotes_to_unverified` | **required** |
| **BC3** | `PULLER_LEASE_TTL = 15` s, strictly `< 45` s | `test_puller_lease.py::test_puller_lease_ttl_is_below_the_ageout_window`; `test_lifecycle_pg.py::test_puller_failover_no_ageout` | not required |
| **BC4** | Per-node lease freshness evaluated **server-side** (`now() >= lease_until`); no client clock — at FETCH time **and** at the new WRITE-time race guard | `test_driver_lease.py::test_fetch_freshness_uses_db_now_no_client_clock` + `::test_node_lease_cas_freshness_is_db_now` + `::test_pull_write_guard_revalidates_lease_server_side` | not required |
| **BC5** | `fleet_meta` column is **`holder`** verbatim in DDL, CAS, and tests | `test_puller_lease.py` + `test_lifecycle_pg.py::test_puller_failover_no_ageout` run the real CAS on the real `009` `fleet_meta` (a name divergence ⇒ `column does not exist`) | not required |
| **BC8** | Option (a) committed: peecee keeps SSH-via-pull liveness; no false "HTTP-only liveness" claim and no de-listing SSH-retirement step ship; peecee still de-lists when marker owns the card | `test_load_aware_liveness.py` (de-list) + `::test_pull_only_node_has_no_db_path`; committed-plan text inspection (§2/§4/§5/Q5 carry no SSH-retirement step) | **required** |

## Live-infra safety (preserved)

The build is **inert** w.r.t. live infra: it only writes `migrations/009`, edits the four
source files + tests, and runs the hermetic suite. The PG suite was verified on a
**throwaway** cluster and then destroyed; it never connected to the live `gpu_fleet` DB,
never ran `systemctl`/restarted `gpu-fleet-heartbeat`, and never touched peecee or its GPU.
`epoch` (RFC-0003) is byte-unchanged (C7); `live_slots` is preserved; the `di --json`
subprocess boundary is untouched; **no SSH-retirement step ships in v1** (BC8 option (a)).

## Handoff to verify

- Re-run `python3 -m pytest tests/ -q` (hermetic) and, for the PG gate, against an
  ephemeral `GPU_FLEET_TEST_DB` (the suite applies real `migrations/001–009`).
- Required at final review: **BC1, BC2, BC6, BC7** (discharge tests green; the ratchet
  `>` never weakened to `>=`) and **BC8** (peecee stays pull-monitored, de-lists under
  marker; no false HTTP-only-liveness claim / no de-listing step).
- Do not re-open the RFC's settled design.
