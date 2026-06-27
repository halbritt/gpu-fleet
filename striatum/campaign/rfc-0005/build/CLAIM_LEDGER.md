---
schema_version: "striatum.handoff.v1"
artifact_kind: "handoff"
---

# CLAIM_LEDGER — RFC 0005 build (Exporter-fed capacity signal, probe-anchored)

author: author-claude-opus-4.8-001

This is the build handoff for RFC 0005. It implements the committed build plan
(`striatum/campaign/rfc-0005/design/COMMITTED_PLAN.md`) as its ordered DB→writer→reader
slices, folding in every binding constraint the design gate recorded (BC1–BC5) and the
holder's self-hardening (F-CARD/F-KEYS/F-LOCK/F-BASE). The default hermetic suite is green:

> **`94 passed, 4 skipped in 1.26s`** — `python3 -m pytest tests/ -q`

The 4 skipped are the `GPU_FLEET_TEST_DB`-guarded PG modules (`test_capacity_pg`,
`test_epoch_pg`, `test_lifecycle_pg`, `test_leases_pg`); they refuse a non-ephemeral DB and
skip by default. Self-verified against an **ephemeral throwaway** Postgres 17 cluster (NOT
the live `gpu_fleet`): with `GPU_FLEET_TEST_DB` set, the full suite is **`124 passed, 0
skipped`** — so every PG gate proof (decay, no-op, epoch-fence, headroom-refusal, puller
companion write, 010 idempotence) runs green, and migration `010` applies + re-applies
cleanly on the real schema. The reviewer should independently re-run both.

## Files changed (all within the declared write scope)

| File | Slice | Change |
|------|-------|--------|
| `migrations/010_exporter_capacity_signal.sql` *(new)* | 0 | Additive companion table `gpu_slots_capacity`, **singleton** `capacity_policy` (`id PK CHECK (id=1)`), `model_capacity` (model PK), the read-only `capacity_slots` view, and two nullable `gpu_slots` columns `mig_mode`/`ecc_mode`. Reversible, idempotent. |
| `heartbeat.py` | 1 + 2 | `GPU_QUERY`/`gpu_stats` parse `mig.mode.current`/`ecc.mode.current` (indices 6,7; uuid stays index 5). Shared `UPSERT` carries `mig_mode`/`ecc_mode` (INSERT/VALUES/SET) and its epoch `CASE` extends to them (C-EPOCH slow bands). New `CAPACITY_UPSERT` (SQL-side `live_slowdown_factor` via `CASE`/`NULLIF`, sticky `cold_probe_ms` COALESCE, within-band no-op `WHERE … IS DISTINCT FROM`), `write_capacity` savepoint guard, and pure helpers `capacity_telemetry`/`probe_floor`/`phantom_from_pids`/`_least_present`/`_band_mib`/`capacity_staleness_s`/`is_fast_stale`. `heartbeat_once` writes the companion after the liveness UPSERT under the savepoint. |
| `heartbeat_all.py` | 2 (BC4) | Imports `CAPACITY_UPSERT`/`capacity_telemetry`/`write_capacity`/`absent_capacity_fields`. `probe_node` carries `mig_mode`/`ecc_mode` + the companion telemetry; `_failed_row` carries the keys + a benign `absent` companion; `pull_write` issues the savepoint-guarded companion write after the liveness UPSERT (pull-mode slots — incl. peecee — get companion rows). |
| `pick_slot.py` | 3 (F-LOCK/F-CARD/BC1) | `PICK` keeps `FROM gpu_slots` (base) with **inline** LEFT JOINs to the companion + `model_capacity` and a `CROSS JOIN` to the singleton policy, locks `FOR UPDATE OF gpu_slots SKIP LOCKED`, and uses the request-aware freshness-decayed **headroom** predicate. Additive output keys `effective_free_mib`/`capacity_source`/`degraded`; legacy keys kept. `pick()` gains `max_context`. |
| `di_fleet.py` | 3 (BC1) | `LEASE_CLAIM_SQL` becomes the same headroom predicate via **correlated scalar subqueries** (UPDATE can't add a FROM); `model_mib` kept as an additive floor. `claim`/`failover_transfer`/`route_slots`/`run_leased_shard`/`run_failover_shard` thread `max_context`; `_split_argv` consumes `--max-context` (peeks `--model`, 6-tuple); `main` resolves it once (flag else `capacity_policy.default_request_context_tokens`) and threads the SAME scalar through route_slots/pick, first-claim, AND failover-claim. |
| `tests/test_capacity_signal.py` *(new)* | — | 9 hermetic gate proofs (A1/A2, C, C-KEYS, F, H, K, K2, M2). |
| `tests/test_capacity_pg.py` *(new)* | — | 11 `GPU_FLEET_TEST_DB`-guarded gate proofs (A3/A4, D, E, G, I, K3, M, N2, P2, Q). |
| `tests/test_pick_slot.py` | — | + J (degrade-not-empty), P1 (locks base table), max_context threading; `_row()` extended for the 3 additive columns. |
| `tests/test_di_fleet.py` | — | + N1 (max_context threads through pick + first-claim + failover-claim; 4k claims, 32k refused), N3 (no-engine-import boundary); route_slots/`_Ops` fakes updated for the `max_context` kwarg. |
| `tests/test_graduation.py`, `tests/test_epoch_pg.py`, `tests/test_lifecycle_pg.py`, `tests/test_leases_pg.py` | — | Row-builders carry `mig_mode`/`ecc_mode` (F-KEYS); `test_epoch_pg` applies `010`; `test_leases_pg` temp DDL carries `served_model` + the empty companion/policy/model tables; `test_graduation` locates the liveness UPSERT among conn calls (no longer last). |

**Operator re-deploy note (NOT performed by the build):** `di_fleet.py` changed, so on each
consumer host the operator updates the gpu-fleet checkout and runs `cp bin/di-fleet
~/.local/bin/` (`bin/di-fleet` itself — a thin `exec python3 di_fleet.py` wrapper — was not
edited). Deploy order is **DB (apply `010`) → writers (`heartbeat*.py`) → reader
(`pick_slot.py`/`di_fleet.py`)**, optionally then seed `model_capacity` (BC5).

## Migration

**`migrations/010_exporter_capacity_signal.sql`** — `010` is the lowest unused number
(`migrations/` holds `001`–`009`; the `free_slots`→`capacity` contract migration is unbuilt
so it never consumed a number). Additive only: 3 new tables + 1 view + 2 nullable
`gpu_slots` columns; renames/drops nothing; `IF NOT EXISTS`/nullable/seeded-`ON CONFLICT`
throughout ⇒ idempotent re-apply. Behavior-neutral until the heartbeat populates the
companion AND the reader switches AND the operator seeds `model_capacity`.

## Falsifiable-gate → test map (each RFC gate bullet + folded constraint → proving test)

| RFC gate bullet (+ constraint) | Test(s) | Kind |
|---|---|---|
| 1. Frozen/stale source decays to `stale` & drops out of pick within `k×half_life`, **and (BC2) a node↔DB skew does NOT decay a fresh slot** | `test_capacity_signal.py::test_decay_marks_stale_by_single_clock` (A1), `::test_skew_does_not_decay_fresh_slot` (A2); `test_capacity_pg.py::test_frozen_source_decays_out_of_pick` (A3), `::test_db_skew_keeps_fresh_slot_measured` (A4) | A1/A2 hermetic; A3/A4 PG |
| 2. Within-band churn = identical UPSERT, no epoch bump; only a band-crossing bumps, **and (F-KEYS) the shared UPSERT never KeyErrors a writer** | `::test_capacity_upsert_stores_only_banded_values` (C), `::test_all_upsert_row_builders_have_mig_ecc_keys` (C-KEYS); `test_capacity_pg.py::test_within_band_churn_noop_and_no_epoch_bump` (D), `::test_mig_ecc_crossing_bumps_epoch_and_fences` (E) | C/C-KEYS hermetic; D/E PG |
| 3. A slot whose exporter free exceeds the probe floor routes on the **lower** (probe) number | `::test_effective_free_is_least_of_floor_and_exporter` (F); `test_capacity_pg.py::test_pick_routes_on_probe_floor_not_exporter` (G) | F hermetic; G PG |
| 4. An unrecognized PID becomes a measured phantom, shrinks `effective_free`, clears on exit, **and (BC4) the puller writes the companion** | `::test_unrecognized_pid_becomes_phantom_and_clears` (H), `::test_pull_write_invokes_capacity_upsert_inside_savepoint` (M2); `test_capacity_pg.py::test_phantom_drops_slot_from_pick` (I), `::test_puller_writes_companion_row` (M) | H/M2 hermetic; I/M PG |
| 5. `pick` never returns empty when all fast fields are stale — degrades to last-known-good with `degraded` | `test_pick_slot.py::test_pick_degrades_not_empty_when_all_stale` (J) | hermetic |
| 5b. **(F-LOCK)** `pick` locks the BASE table, never a join view, and never duplicates a slot | `test_pick_slot.py::test_pick_locks_base_table_not_view` (P1); `test_capacity_pg.py::test_pick_k2_one_slot_returns_unique_pk` (P2) | P1 hermetic; P2 PG |
| 6. peecee `ollama-ondemand` is never force-loaded (residency-only floor), **and (BC3/F-BASE) a None/0/hot-restart baseline never crashes the tick** | `::test_ollama_ondemand_floor_is_residency_only` (K), `::test_none_probe_yields_well_formed_row` (K2); `test_capacity_pg.py::test_capacity_upsert_null_and_sticky_baseline` (K3) | K/K2 hermetic; K3 PG |
| 7. Hermetic default suite stays green; per-PID/exporter reads are injected fakes; DB tests guarded | the whole `test_capacity_signal.py` (all fakes, no DB) + every `test_capacity_pg.py` test skips without `GPU_FLEET_TEST_DB`; `94 passed, 4 skipped` | hermetic + guarded |
| 8. **BC1** — reader headroom enforced IN PRODUCTION: 32k vs 4k route differently on the same slot; pick + first-claim + failover-claim all receive non-default `max_context`; `kv_bytes` is a defined symbol; no engine import / live-hardware read | `test_di_fleet.py::test_request_context_threads_through_all_claim_paths` (N1), `::test_no_engine_import_in_reader` (N3); `test_capacity_pg.py::test_headroom_predicate_refuses_oversized_context` (N2); `test_pick_slot.py::test_pick_threads_max_context_into_request_aware_headroom` | N1/N3 hermetic; N2 PG |
| 9. **(F-CARD)** `010` idempotent on re-apply, `capacity_policy` singleton, companion-empty reader is one-row-per-slot | `test_capacity_pg.py::test_010_reapply_singleton_and_view_cardinality` (Q) + P2 | PG |

## Binding-constraint discharge (the build's verify gate)

- **BC1** *(gate, final_review_required)* — request-capacity contract in production: `max_context` from the di-fleet argv layer (`_split_argv` `--max-context`, else `capacity_policy.default_request_context_tokens`); per-slot footprint/KV from `model_capacity` joined on `served_model`; `kv_bytes` is the **defined inline SQL** `CEIL(COALESCE(mc.kv_mib_per_1k_tokens,0)*%(max_context)s::numeric/1000.0)::int`; the SAME non-default scalar threads through `route_slots`→`pick`, first-attempt `claim`, AND `failover_transfer`. No engine import, no GPU read. **Tests N1/N2/N3** (+ the pick-level threading test).
- **BC2** *(gate, final_review_required)* — single-clock decay: staleness = node-clock `fast_source_age_s` + DB-clock `now()-updated_ts`; never a node-ts vs DB-ts comparison; `source_ts` is never stamped with DB `now()`. **Tests A1–A4** (skew + frozen).
- **BC3** *(policy)* — `live_slowdown_factor` computed in SQL (`CASE`/`NULLIF`); None/0/hot-restart baseline ⇒ NULL, never raises, inside the savepoint; ollama-ondemand yields a well-formed `measured` row. **Tests K/K2/K3.**
- **BC4** *(policy)* — `CAPACITY_UPSERT` wired into the puller (`heartbeat_all.pull_write`) under the same savepoint, after the liveness UPSERT. **Tests M/M2.**
- **BC5** *(policy)* — committable-vs-deployable disambiguated; Slice 2's hard `010` precondition stated; `mig`/`ecc` stay in the `gpu_slots` UPSERT epoch `CASE` (not the guarded companion). Migration §2 + the `010` header comment; epoch-CASE assertion in test C.
- **F-CARD** — `capacity_policy` singleton (`id PK CHECK (id=1)`), `model_capacity` model-PK, view/pick reference policy via `WHERE id=1`. **Tests Q/P2.**
- **F-KEYS** — all three row-builders (`heartbeat_once`, `probe_node`, `_failed_row`) carry `mig_mode`/`ecc_mode`. **Test C-KEYS.**
- **F-LOCK** — `PICK` locks `FOR UPDATE OF gpu_slots SKIP LOCKED` over the base table; the `capacity_slots` view is read-only/diagnostic. **Tests P1/P2.**
- **F-BASE** — sticky cold baseline via `COALESCE(gpu_slots_capacity.cold_probe_ms, EXCLUDED.cold_probe_ms)`. **Test K3.**

## Live-infra safety (C6)

The build is inert with respect to live infra: it only writes `migrations/010_…sql`, edits
`heartbeat*.py`/`pick_slot.py`/`di_fleet.py`/`tests/*`, and runs the **hermetic** suite. It
does NOT connect to / migrate the live `gpu_fleet` DB (the PG tests refuse a non-ephemeral
DB and skip by default; self-verification used an ephemeral throwaway cluster), restart
`gpu-fleet-heartbeat`, or touch peecee/its GPU. Every floor/exporter/per-PID read is an
**injected fake** in units; the ollama-ondemand adapter is residency-only by construction;
`model_capacity` is operator-seeded data (the build measures no real GPUs); the di-fleet
request capacity is **argv + registry SQL only** — the engine is never imported (N3).

The reviewer will independently re-run the tests and the falsifiable gate — this build does
not treat its own pass as acceptance.
