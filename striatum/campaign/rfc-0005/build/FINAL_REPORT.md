---
schema_version: "striatum.synthesis.v1"
artifact_kind: "synthesis"
---

# FINAL_REPORT — RFC 0005: Exporter-fed capacity signal (probe-anchored)

author: author-claude-opus-4.8-002

This is the build's final report for RFC 0005. The independent verifier
(`reviewer-openai-codex-gpt-5.5-001`, `review/VERIFICATION_REVIEW.md`) recorded
**`accept`** against branch `striatum/rfc-0005-build` @ `eec6b99e79b4ceac5fe6e4d5ce40745512b5b6d6`,
confirming the BC1 e2e and BC2 skew+frozen gate tests (the two `final_review_required`
constraints) plus the full falsifiable gate. **No findings remained to address** — the
verdict was a clean `accept`, not `accept_with_findings` or `needs_revision` — so this
report makes no further code changes. It confirms the integrated tree is green and lists
the exact operator deployment steps the build did **not** perform.

## Tree is green (re-confirmed on the integrated branch)

Re-run from the build worktree (hermetic default suite — `GPU_FLEET_TEST_DB` unset):

```text
$ python3 -m pytest tests/ -q
........................................................................ [ 76%]
......................                                                   [100%]
94 passed, 4 skipped in 1.42s
```

This matches the verifier's hermetic run exactly (`94 passed, 4 skipped`). The 4 skipped
are the `GPU_FLEET_TEST_DB`-guarded Postgres proof modules (`test_capacity_pg`,
`test_epoch_pg`, `test_lifecycle_pg`, `test_leases_pg`), which refuse a non-ephemeral DB and
skip by default. The verifier additionally ran the suite against a throwaway Postgres 17
cluster (`GPU_FLEET_TEST_DB` set, unix-socket, db `gpu_fleet_test`) and observed
**`124 passed in 6.13s`** — so every PG gate proof runs green and migration `010` applies +
re-applies cleanly on the real schema. No connection was made to the live `gpu_fleet` DB.

## Final files changed + the migration

14 files, `+1553 / −57`, all inside the declared write scope (no edits to `docs/rfc/`,
`striatum/workflows/`, `.striatum/`, systemd/service files, `bin/di-fleet`, or live-host
config):

| File | Slice | Final change |
|------|-------|--------------|
| **`migrations/010_exporter_capacity_signal.sql`** *(new, +164)* | 0 | Additive companion table `gpu_slots_capacity`; **singleton** `capacity_policy` (`id INT PK DEFAULT 1 CHECK (id=1)`, seeded `ON CONFLICT DO NOTHING`); `model_capacity` (`model PRIMARY KEY`, `footprint_mib`, `kv_mib_per_1k_tokens`); the read-only `capacity_slots` view (single-clock decay); two nullable `gpu_slots` columns `mig_mode`/`ecc_mode`. Reversible (committed `DROP` comment block), idempotent (`IF NOT EXISTS`/PK seed). |
| **`heartbeat.py`** *(+267)* | 1 + 2 | `GPU_QUERY`/`gpu_stats` parse `mig.mode.current`/`ecc.mode.current`; shared `UPSERT` carries `mig_mode`/`ecc_mode` and its epoch `CASE` extends to them (C-EPOCH slow bands only). New `CAPACITY_UPSERT` (SQL-side `live_slowdown_factor` via `CASE`/`NULLIF`, sticky `cold_probe_ms` via `COALESCE`, within-band no-op `IS DISTINCT FROM`); `write_capacity` savepoint guard; pure helpers (`capacity_telemetry`/`probe_floor`/`phantom_from_pids`/`capacity_staleness_s`/…). `heartbeat_once` writes the companion after the liveness UPSERT, savepoint-guarded. |
| **`heartbeat_all.py`** *(+24)* | 2 (BC4) | Imports `CAPACITY_UPSERT`/`capacity_telemetry`/`write_capacity`; `probe_node` + `_failed_row` carry `mig_mode`/`ecc_mode` (F-KEYS); `pull_write` issues the savepoint-guarded companion write after the liveness UPSERT so pull-mode slots (incl. peecee) get companion rows. |
| **`pick_slot.py`** *(+91)* | 3 (BC1/F-LOCK/F-CARD) | `PICK` keeps `FROM gpu_slots` (base) with inline LEFT JOINs to companion + `model_capacity` and a `CROSS JOIN` to the singleton policy; locks `FOR UPDATE OF gpu_slots SKIP LOCKED`; request-aware freshness-decayed headroom predicate; additive output keys (`effective_free_mib`/`capacity_source`/`degraded`), legacy keys kept; `pick()` gains `max_context`. |
| **`di_fleet.py`** *(+116)* | 3 (BC1) | `LEASE_CLAIM_SQL` becomes the headroom predicate via correlated scalar subqueries (`model_mib` kept as an additive floor); `claim`/`failover_transfer`/`route_slots`/`run_leased_shard`/`run_failover_shard` thread `max_context`; `_split_argv` consumes `--max-context` (peeks `--model`, now a 6-tuple); `main` resolves `max_context` once (flag else `capacity_policy.default_request_context_tokens`) and threads the **same** scalar through route_slots/pick, first-claim, AND failover-claim. |
| `tests/test_capacity_signal.py` *(new, +258)* | — | 9 hermetic gate proofs (A1/A2, C, C-KEYS, F, H, K, K2, M2). |
| `tests/test_capacity_pg.py` *(new, +368)* | — | 11 `GPU_FLEET_TEST_DB`-guarded gate proofs (A3/A4, D, E, G, I, K3, M, N2, P2, Q). |
| `tests/test_pick_slot.py` *(+60)* | — | + J (degrade-not-empty), P1 (locks base table), `max_context` threading. |
| `tests/test_di_fleet.py` *(+125)* | — | + N1 (32k-vs-4k threads through pick + first-claim + failover-claim), N3 (no-engine-import boundary). |
| `tests/test_epoch_pg.py`, `tests/test_leases_pg.py`, `tests/test_lifecycle_pg.py`, `tests/test_graduation.py` | — | Row-builders carry `mig_mode`/`ecc_mode` (F-KEYS); `test_epoch_pg` applies `010`; minor fixture updates. |
| `striatum/campaign/rfc-0005/build/CLAIM_LEDGER.md` *(new, +94)* | — | Build handoff (operational provenance). |

**Migration number: `010`** — `migrations/` holds `001`–`009`; `010` is the lowest unused
number (the `free_slots`→`capacity` contract migration was never built, so it never consumed
a number). The migration is **additive and reversible**: 3 new tables + 1 view + 2 nullable
columns; it renames/drops nothing.

## Falsifiable-gate → test map (FINAL)

Verbatim result line for the whole suite: **`94 passed, 4 skipped in 1.42s`**
(`python3 -m pytest tests/ -q`); **`124 passed`** with `GPU_FLEET_TEST_DB` set against an
ephemeral cluster (verifier-reproduced).

| RFC gate bullet (+ folded constraint) | Proving test(s) | Kind |
|---|---|---|
| 1. Frozen/stale source decays to `stale` & drops out of `pick` within `k×half_life`; **(BC2)** a node↔DB skew does NOT decay a fresh slot | `test_capacity_signal.py::test_decay_marks_stale_by_single_clock` (A1), `::test_skew_does_not_decay_fresh_slot` (A2); `test_capacity_pg.py::test_frozen_source_decays_out_of_pick` (A3), `::test_db_skew_keeps_fresh_slot_measured` (A4) | A1/A2 hermetic; A3/A4 PG |
| 2. Within-band churn = identical UPSERT, no epoch bump; only a band-crossing bumps; **(F-KEYS)** the shared UPSERT never KeyErrors a writer | `::test_capacity_upsert_stores_only_banded_values` (C), `::test_all_upsert_row_builders_have_mig_ecc_keys` (C-KEYS); `test_capacity_pg.py::test_within_band_churn_noop_and_no_epoch_bump` (D), `::test_mig_ecc_crossing_bumps_epoch_and_fences` (E) | C/C-KEYS hermetic; D/E PG |
| 3. A slot whose exporter free exceeds the probe floor routes on the **lower** (probe) number | `::test_effective_free_is_least_of_floor_and_exporter` (F); `test_capacity_pg.py::test_pick_routes_on_probe_floor_not_exporter` (G) | F hermetic; G PG |
| 4. Unrecognized PID → measured phantom, shrinks `effective_free`, clears on exit; **(BC4)** the puller writes the companion | `::test_unrecognized_pid_becomes_phantom_and_clears` (H), `::test_pull_write_invokes_capacity_upsert_inside_savepoint` (M2); `test_capacity_pg.py::test_phantom_drops_slot_from_pick` (I), `::test_puller_writes_companion_row` (M) | H/M2 hermetic; I/M PG |
| 5. `pick` never returns empty when all fast fields are stale — degrades to last-known-good with `degraded` | `test_pick_slot.py::test_pick_degrades_not_empty_when_all_stale` (J) | hermetic |
| 5b. **(F-LOCK)** `pick` locks the BASE table, never a join view, and never duplicates a slot | `test_pick_slot.py::test_pick_locks_base_table_not_view` (P1); `test_capacity_pg.py::test_pick_k2_one_slot_returns_unique_pk` (P2) | P1 hermetic; P2 PG |
| 6. peecee `ollama-ondemand` never force-loaded (residency-only floor); **(BC3/F-BASE)** a None/0/hot-restart baseline never crashes the tick | `::test_ollama_ondemand_floor_is_residency_only` (K), `::test_none_probe_yields_well_formed_row` (K2); `test_capacity_pg.py::test_capacity_upsert_null_and_sticky_baseline` (K3) | K/K2 hermetic; K3 PG |
| 7. Hermetic default suite stays green; per-PID/exporter reads are injected fakes; DB tests guarded | all of `test_capacity_signal.py` (fakes, no DB) + every `test_capacity_pg.py` test skips without `GPU_FLEET_TEST_DB`; `94 passed, 4 skipped` | hermetic + guarded |
| 8. **BC1** — reader headroom enforced IN PRODUCTION: 32k vs 4k route differently on the same slot; pick + first-claim + failover-claim all receive non-default `max_context`; `kv_bytes` is a defined symbol; no engine import / live-hardware read | `test_di_fleet.py::test_request_context_threads_through_all_claim_paths` (N1), `::test_no_engine_import_in_reader` (N3); `test_capacity_pg.py::test_headroom_predicate_refuses_oversized_context` (N2); `test_pick_slot.py::test_pick_threads_max_context_into_request_aware_headroom` | N1/N3 hermetic; N2 PG |
| 9. **(F-CARD)** `010` idempotent on re-apply, `capacity_policy` singleton, companion-empty reader is one-row-per-slot | `test_capacity_pg.py::test_010_reapply_singleton_and_view_cardinality` (Q) + P2 | PG |

## Binding constraints — all discharged

The verifier confirmed each (`review/VERIFICATION_REVIEW.md` → "Binding Constraints").

- **BC1** *(high / gate / final_review_required)* — **DISCHARGED.** Request-capacity contract
  lives in production: `max_context` parsed at the di-fleet argv layer (`_split_argv`
  `--max-context`, else `capacity_policy.default_request_context_tokens`); per-slot
  footprint/KV from `model_capacity` joined on `served_model`; `kv_bytes` is the **defined
  inline SQL** `CEIL(COALESCE(mc.kv_mib_per_1k_tokens,0) * %(max_context)s::numeric/1000.0)::int`;
  the **same** non-default scalar threads through `route_slots`→`pick`, first-attempt
  `claim`, AND `failover_transfer`. No engine import, no GPU read. Proven N1/N2/N3.
- **BC2** *(high / gate / final_review_required)* — **DISCHARGED.** Single-clock decay:
  staleness = node-clock `fast_source_age_s` + DB-clock `now()-updated_ts`; never a
  node-timestamp vs DB-timestamp comparison; `source_ts` is never stamped with DB `now()`.
  Proven A1–A4 (skew-resistance + frozen-source decay).
- **BC3** *(medium / policy)* — **DISCHARGED.** `live_slowdown_factor` computed in SQL
  (`CASE`/`NULLIF`); a None/0/hot-restart baseline yields NULL, never raises, inside the
  savepoint; ollama-ondemand yields a well-formed row. Proven K/K2/K3.
- **BC4** *(medium / policy)* — **DISCHARGED.** `CAPACITY_UPSERT` wired into the puller
  (`heartbeat_all.pull_write`) under the same savepoint, after the liveness UPSERT. Proven
  M/M2.
- **BC5** *(low / policy)* — **DISCHARGED.** Committable-vs-deployable disambiguated; Slice 2's
  hard `010` precondition stated; `mig`/`ecc` remain in the `gpu_slots` UPSERT epoch `CASE`
  (not the guarded companion). Migration §2 + `010` header comment; epoch-`CASE` assertion in
  test C.
- **F-CARD** — **DISCHARGED.** `capacity_policy` singleton (`id PK CHECK (id=1)`),
  `model_capacity` model-PK; view/pick reference policy via `WHERE id=1`. Proven Q/P2.
- **F-KEYS** — **DISCHARGED.** All three row-builders (`heartbeat_once`, `probe_node`,
  `_failed_row`) carry `mig_mode`/`ecc_mode`. Proven C-KEYS.
- **F-LOCK** — **DISCHARGED.** `PICK` locks `FOR UPDATE OF gpu_slots SKIP LOCKED` over the
  base table; the `capacity_slots` view is read-only/diagnostic. Proven P1/P2.
- **F-BASE** — **DISCHARGED.** Sticky cold baseline via
  `COALESCE(gpu_slots_capacity.cold_probe_ms, EXCLUDED.cold_probe_ms)`. Proven K3.

## EXACT operator deployment steps (the build did NOT perform these)

The build is **inert** w.r.t. live infra: it wrote only `migrations/010_*.sql`, edited
`heartbeat*.py`/`pick_slot.py`/`di_fleet.py`/`tests/*`, and ran the hermetic suite. The
operator performs the following, in order. The operative deploy invariant is
**DB → writers → reader** (BC5: Slice 2 has a hard precondition on `010` because
`mig_mode`/`ecc_mode` ride the non-savepoint-guarded liveness UPSERT).

1. **Confirm green on the integrated tree:**
   ```bash
   cd /home/halbritt/git/gpu-fleet
   python3 -m pytest tests/ -q          # expect: 94 passed, 4 skipped
   ```

2. **Apply migration `010` to the live `gpu_fleet` DB.** Migration `010` is **additive and
   does NOT alter `probe_model` or any sentinel** (verified: no `probe_model`/sentinel
   references in the migration or in the `heartbeat.py` diff), so the conditional resolves to
   **migrate-before-restart is sufficient** — applying `010` while `gpu-fleet-heartbeat` is
   still running is safe because the old writer names none of the new columns/tables. (A
   `stop → migrate → start` is a safe superset and equally fine, but not required here.)
   ```bash
   psql "$GPU_FLEET_DSN" -f migrations/010_exporter_capacity_signal.sql
   ```
   This step MUST precede deploying the new writer code (Slice 2 references `mig_mode`/`ecc_mode`).

3. **Re-deploy `bin/di-fleet` — NOT required this deploy.** `bin/di-fleet` is **unchanged**
   (it is a thin `exec python3 $FLEET/di_fleet.py "$@"` wrapper that runs `di_fleet.py`
   straight from the gpu-fleet checkout). Since only `di_fleet.py` changed (not the wrapper),
   `cp bin/di-fleet ~/.local/bin/` is a no-op — updating the gpu-fleet checkout on each
   consumer host (so the wrapper execs the new `di_fleet.py`) is all that is needed for the
   reader change to take effect. Run `cp bin/di-fleet ~/.local/bin/` only on a future deploy
   in which `bin/di-fleet` itself is edited.

4. **Restart the heartbeat writer:**
   ```bash
   systemctl --user restart gpu-fleet-heartbeat
   ```
   This brings the new writers (Slice 1 + Slice 2) online: companion enrichment + MIG/ECC
   into the epoch `CASE`. The reader (`pick_slot.py`/`di_fleet.py`, Slice 3) goes live via
   the updated checkout. Behavior remains byte-equivalent to today until **`model_capacity`
   is seeded** — until then the headroom predicate `COALESCE`s through to today's
   `vram_free_mib` and footprint/KV are 0.

5. **(Optional) Seed `model_capacity`** to turn on request-aware footprint/KV routing. Rows
   are **operator-measured offline data** (`model`, `footprint_mib`, `kv_mib_per_1k_tokens`),
   like `min_load_vram_mib` already is — the build measures no real GPUs and crosses no
   `di --json` boundary. Until seeded, the reader is byte-equivalent to today's flat-VRAM
   routing.

**Reversibility (before the reader is relied upon):** the committed `DROP` comment block at
the foot of `migrations/010_exporter_capacity_signal.sql` removes the view, the three new
tables, and the two `gpu_slots` columns; re-applying `010` is safe and idempotent (gate test
Q). All deployment actions remain with the operator; the build performed none of them.
