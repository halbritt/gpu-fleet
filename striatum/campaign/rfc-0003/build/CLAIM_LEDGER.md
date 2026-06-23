---
schema_version: striatum.handoff.v1
artifact_kind: handoff
logical_name: claim_ledger
inputs:
  - "striatum/campaign/rfc-0003/design/COMMITTED_PLAN.md"
  - "docs/rfc/0003-stale-router-epoch-fencing.md"
author: author-claude-opus-4.8-001
run_id: "run_2ecf55525f7b2cf69217837e283f228d"
workflow: "rfc-0003-build"
role: author
job: draft
title: "RFC 0003 build — claim ledger (stale-router epoch fencing)"
summary: >-
  Implemented the committed build plan as the ordered slices A/C/B/D with every
  binding constraint (BC1 sticky discovery, BC2 endpoint-turnover freshness fence,
  BC3 NULL-arm invariants, BC4 migration-number/ reversibility discipline) folded
  in and discharged by tests. Each RFC falsifiable-gate bullet maps to a named
  test. Hermetic default suite: 63 passed, 2 skipped. The two skipped files are the
  PG-guarded suites; run against an ephemeral throwaway cluster they are 9 passed.
tags: ["rfc-0003", "epoch_fencing", "claim_ledger", "build"]
status: implemented
---

# CLAIM LEDGER — RFC 0003: Stale-router epoch fencing (build)

author: author-claude-opus-4.8-001

This ledger records exactly what the build did: the files changed, the migration,
each RFC falsifiable-gate bullet mapped to the test that proves it, the binding
constraints and their tests, and the verbatim pytest result line. The code,
migration, and test changes live in the repository within the declared write scope
(`migrations/`, `bin/`, `tests/`, `di_fleet.py`, `pick_slot.py`, `heartbeat.py`,
`heartbeat_all.py`, `conftest.py`, `striatum/campaign/rfc-0003/build/`).

The independent reviewer re-runs the tests and re-verifies the gate — this build's
own green run is not treated as acceptance.

---

## 1. Migration

| Migration | What | Why this number |
|---|---|---|
| `migrations/008_lease_epoch.sql` (new) | `ALTER TABLE gpu_slots ADD COLUMN IF NOT EXISTS lease_epoch BIGINT;` — one nullable column, no default/backfill/index/constraint. NULL = fence off. | BC4 lowest-unused-`0NN` guard: `ls migrations/` holds `001`–`007`, so `008` is correct. (The work-packet objective text said "migration 006", but `006_peecee_dense_27b.sql` already exists; the committed plan and the `next-UNUSED-number` rule both resolve to `008`. The trailing prose in `007` that mentions a *future* `free_slots`-drop "migration 008" reserves nothing — that contract migration is not built here.) |

The reused `epoch BIGINT NOT NULL DEFAULT 0` column already exists in
`001_gpu_slots.sql` and is **not** touched by the migration; Slice B turns it on.

---

## 2. Files changed

| File | Slice | Change |
|---|---|---|
| `migrations/008_lease_epoch.sql` | A | **new** — additive `lease_epoch BIGINT` (nullable). |
| `pick_slot.py` | C | Added `epoch` to the `PICK` `SELECT` and `COLS`; output dict gains an `epoch` key (readers-before-writers; un-upgraded readers ignore the extra key via `.get`). |
| `heartbeat.py` | B | **B.1** Replaced `epoch=EXCLUDED.epoch` in the UPSERT `ON CONFLICT … DO UPDATE SET` with `epoch = gpu_slots.epoch + CASE WHEN served_model/nvlink_domain/max_context IS DISTINCT FROM EXCLUDED.* THEN 1 ELSE 0 END` (preserve-and-conditional-bump; VRAM/util excluded). **B.2** Made `discover_served_model` **sticky** (BC1): a module cache `_DISCOVERED` (+ `reset_discovery_cache()`); a transient `/models` failure returns the last successfully-resolved id instead of flapping to the differing static `--served-model` tag. |
| `heartbeat_all.py` | B | **none** — it `from heartbeat import UPSERT, discover_served_model`, so both the UPSERT bump and the sticky-discovery change apply transitively (single edit point). |
| `di_fleet.py` | D | **D.1** `LEASE_CLAIM_SQL` SET adds `lease_epoch = epoch` (stamp at claim, server-side). **D.2** `LEASE_RENEW_SQL` WHERE adds `(lease_epoch IS NULL OR epoch = lease_epoch)` + the BC2 freshness/identity term `alive AND heartbeat_ts > now() - interval '45 seconds'`. **D.3** `LEASE_RELEASE_SQL` SET adds `lease_epoch = NULL` (cleared with `lease_id`). The `claim()/renew()/release()` Python signatures are unchanged (column self-compare; no consumer epoch state). |
| `tests/lease_fakes.py` | D | Extended `FakeSlotDB` to model `epoch`/`lease_epoch` (claim stamps, release clears), the renew epoch self-compare + the `alive`+45s freshness term, and a `turnover_endpoint()` PK-split helper; `advance()` now refreshes only still-heartbeating rows so a turned-over endpoint can age out. |
| `tests/test_pick_slot.py` | C | `_row()` gains `epoch`; added gate-3 reader test `test_pick_surfaces_current_epoch_and_model`. |
| `tests/test_leases.py` | D | Added gate-1 (`test_epoch_change_fences_renew`, `test_epoch_bump_aborts_di_child_in_renew_path`), BC2 hermetic companion (`test_endpoint_turnover_fences_old_lease`), and BC3 (`test_post_rollout_claim_stamps_non_null_lease_epoch`, `test_null_lease_epoch_still_renews`, `test_release_clears_lease_epoch_with_lease_id`). |
| `tests/test_heartbeat_epoch.py` | B | **new** — gate-2 writer SQL (`test_bump_diff_excludes_churn_fields`) + BC1 sticky discovery (`test_transient_discovery_failure_does_not_flap_or_bump` and two companions). |
| `tests/test_epoch_pg.py` | B/D | **new, PG-guarded** — gate 1/2/3 + BC2 + BC1 against a real ephemeral Postgres, applying real migrations `001/007/008`. Skips unless `GPU_FLEET_TEST_DB` names an ephemeral throwaway cluster (refuses bare `gpu_fleet`). |
| `tests/test_leases_pg.py` | D | Build hygiene: added `epoch BIGINT NOT NULL DEFAULT 0` + `lease_epoch BIGINT` to the hardcoded `_DDL` (Slice D mutates the shared `LEASE_*_SQL` it exercises). |

---

## 3. RFC falsifiable-gate → test map

| RFC gate bullet | Test(s) | Kind | Result |
|---|---|---|---|
| **(1)** Bumping `served_model` makes a holder's next renew return **zero rows** (forced re-pick), proven by mutating the row mid-lease | `tests/test_leases.py::test_epoch_change_fences_renew` (+ end-to-end via the monitor: `test_epoch_bump_aborts_di_child_in_renew_path`); `tests/test_epoch_pg.py::test_served_model_bump_fences_renew` | hermetic + PG | pass / pass |
| **(2)** A VRAM/util-only change does **not** bump epoch and does **not** invalidate a lease | `tests/test_heartbeat_epoch.py::test_bump_diff_excludes_churn_fields`; `tests/test_epoch_pg.py::test_vram_util_only_change_keeps_epoch_and_lease` | hermetic + PG | pass / pass |
| **(3)** A re-pick after an epoch bump lands on the slot's **new** capability, never the stale one | `tests/test_pick_slot.py::test_pick_surfaces_current_epoch_and_model`; `tests/test_epoch_pg.py::test_repick_after_bump_stamps_new_epoch` | hermetic + PG | pass / pass |

## Binding-constraint → test map (folded in; required, not assertions of stability)

| Constraint | Test(s) | Kind | Result |
|---|---|---|---|
| **BC1** sticky discovery (writer-side analog of gate-2; the gated repair) | `tests/test_heartbeat_epoch.py::test_transient_discovery_failure_does_not_flap_or_bump` (+ `_before_any_discovery_uses_static_fallback`, `_successful_rediscovery_updates_the_sticky_value`); PG companion `tests/test_epoch_pg.py::test_sticky_discovery_keeps_epoch_stable` | hermetic + PG | pass / pass |
| **BC2** endpoint-turnover fence — option (a), registry-side freshness/identity | `tests/test_epoch_pg.py::test_endpoint_turnover_fences_old_lease`; hermetic companion `tests/test_leases.py::test_endpoint_turnover_fences_old_lease` | PG + hermetic | pass / pass |
| **BC3** keep the NULL arm; prove steady-state-unreachable | `tests/test_leases.py::test_post_rollout_claim_stamps_non_null_lease_epoch`, `::test_null_lease_epoch_still_renews`, `::test_release_clears_lease_epoch_with_lease_id` | hermetic | pass |
| **BC4** migration-number / committable-not-deployable / reversibility / no column-probing | `migrations/008_lease_epoch.sql` (lowest-unused number; reverse stanza); §5 of the committed plan restated below | policy | satisfied |

**Verifier gate (per the operator decision):** BC1 (test G) and BC2 (test H) are
enforced before accept. Both pass hermetically and against the ephemeral PG cluster.

---

## 4. Test result (verbatim)

Default hermetic suite (no DB; `GPU_FLEET_TEST_DB` unset), run from the build worktree
with the project interpreter:

```
63 passed, 2 skipped in 1.21s
```

The **2 skipped** are the PG-guarded files, skipped by the `GPU_FLEET_TEST_DB`
ephemeral-only guard:

```
SKIPPED [1] tests/test_epoch_pg.py:30: set GPU_FLEET_TEST_DB to an ephemeral throwaway cluster to run these
SKIPPED [1] tests/test_leases_pg.py:23: set GPU_FLEET_TEST_DB to an ephemeral throwaway cluster to run these
```

Collected hermetic counts: `test_di_fleet.py` 19, `test_heartbeat_epoch.py` 4,
`test_lease_no_consumer_clock.py` 2, `test_leases.py` 17, `test_load_aware_liveness.py`
12, `test_pick_slot.py` 6, `test_probe_all.py` 3 = **63**.

PG-guarded suites run against an **ephemeral throwaway** Postgres 17 cluster
(initdb in `/tmp`, unix-socket-only, no TCP, torn down after — the live `gpu_fleet`
DB and the `:5432` cluster were never touched):

```
9 passed in 2.69s
```

(`tests/test_epoch_pg.py` 5 + `tests/test_leases_pg.py` 4 — the latter proving the
`_DDL` epoch/lease_epoch addition keeps the existing lease PG gate green.)

---

## 5. Live-infra safety & operator deploy note

This build is inert with respect to live infra: it wrote `migrations/008_lease_epoch.sql`,
edited `pick_slot.py` / `heartbeat.py` / `di_fleet.py` / `tests/*`, and ran the hermetic
pytest suite. It did **not** connect to or migrate the live `gpu_fleet` Postgres, restart
`gpu-fleet-heartbeat`, or touch peecee or its GPU. The `di --json` subprocess boundary is
preserved — epoch fencing (including the BC2 freshness term) is 100% registry-side SQL; no
code here imports the Node engine.

`di_fleet.py` changed, so the operator re-deploy step (to be performed by the operator after
integration, **not** here) is: `cp bin/di-fleet ~/.local/bin/` on consumer hosts after updating
the gpu-fleet checkout (the `bin/di-fleet` wrapper itself is unchanged — it `exec`s
`python3 di_fleet.py`). Operator rollout order is the RFC's DB → readers → writers:
apply `008`; deploy `pick_slot.py`; deploy `heartbeat.py` + `di_fleet.py` and restart
`gpu-fleet-heartbeat`. Reversibility (BC4): revert Slice D's `di_fleet.py` **with** dropping
the column (`ALTER TABLE gpu_slots DROP COLUMN IF EXISTS lease_epoch`) — never drop `008`
while live Slice-D code is deployed.
