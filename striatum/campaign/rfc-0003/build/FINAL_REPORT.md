---
schema_version: striatum.synthesis.v1
artifact_kind: synthesis
inputs:
  - "striatum/campaign/rfc-0003/build/review/VERIFICATION_REVIEW.md"
  - "striatum/campaign/rfc-0003/build/CLAIM_LEDGER.md"
  - "striatum/campaign/rfc-0003/design/COMMITTED_PLAN.md"
  - "docs/rfc/0003-stale-router-epoch-fencing.md"
author: author-claude-opus-4.8-002
run_id: "run_2ecf55525f7b2cf69217837e283f228d"
workflow: "rfc-0003-build"
role: author
title: "RFC 0003 build — final report (stale-router epoch fencing)"
summary: >-
  Applied the accepted review findings, confirmed the tree is green, and recorded
  the exact operator deployment steps. The verifier
  (reviewer-openai-codex-gpt-5.5-001) returned accept_with_findings with NO
  blocking implementation issue; the two findings were environmental (host
  /usr/bin/python3 lacks pytest; the PG-guarded companion tests were skipped
  because no ephemeral GPU_FLEET_TEST_DB was set). Both are discharged here: the
  hermetic default suite is green (63 passed, 2 skipped), and the PG-guarded
  companions were run against an ephemeral throwaway Postgres 16 cluster
  (9 passed; full suite 72 passed with the DB configured). No source code change
  was required. The build did NOT perform any deployment step.
tags: ["rfc-0003", "epoch_fencing", "final_report", "build", "apply"]
status: finalized
---

# FINAL REPORT — RFC 0003: Stale-router epoch fencing (build / apply)

author: author-claude-opus-4.8-002

This is the apply/finalize report for the RFC-0003 build run
(`run_2ecf55525f7b2cf69217837e283f228d`). It (1) records how the accepted review
findings were addressed, (2) confirms the tree is green with the FINAL verbatim
pytest line, (3) marks every binding constraint from the committed plan
discharged, and (4) states the EXACT operator deployment steps. **The build did
NOT perform any deployment step** — those are for the operator.

---

## 0. Disposition of the accepted review findings

The independent verifier (`reviewer-openai-codex-gpt-5.5-001`,
`striatum/campaign/rfc-0003/build/review/VERIFICATION_REVIEW.md`) recorded
**`accept_with_findings`** and stated explicitly: *"I found no blocking
implementation issue in the default hermetic path."* The two findings are
**environmental, not code defects**:

| # | Finding (as recorded) | Disposition in this apply step |
|---|---|---|
| F1 | The host `/usr/bin/python3` lacks `pytest`, so the required command fails on the bare host interpreter. | **Not a code defect.** Confirmed green by running the suite with the project's test interpreter (`/tmp/gpu-fleet-rfc3-venv`, `pytest 9.1.1`, `psycopg 3.3.4`). The host-interpreter gap is an operator-env note, not a source change. See §2. |
| F2 | The real-Postgres companion tests (`test_epoch_pg.py`, `test_leases_pg.py`) were **skipped** because no ephemeral `GPU_FLEET_TEST_DB` was configured. | **Discharged by actually running them.** Stood up an ephemeral throwaway Postgres 16 cluster (initdb in `/tmp`, unix-socket-only, no TCP, `dbname=gpu_fleet_test`), ran the PG-guarded suite: **9 passed**; full suite with the DB configured: **72 passed**. Cluster torn down; the live `gpu_fleet` DB and the `:5432` cluster were never touched. See §2. |

**No source code was modified in this apply step** — there was no blocking
implementation issue to repair. The work was: confirm hermetic green, close the
F2 skip gap by running the PG companions against a throwaway cluster, and write
this report. The verifier's BC1+BC2 gate (tests G and H) passes both hermetically
and against the ephemeral PG cluster.

---

## 1. Final files changed and the migration

Source-change commit on `striatum/rfc-0003-build`:
`aecc72d` (`striatum: lane source changes (job
job_run_2ecf55525f7b2cf69217837e283f228d_draft)`) — 10 files, +615/−18.

| File | Slice | Change |
|---|---|---|
| `migrations/008_lease_epoch.sql` | A | **new** — `ALTER TABLE gpu_slots ADD COLUMN IF NOT EXISTS lease_epoch BIGINT;` one nullable column, no default/backfill/index/constraint. NULL = fence off. Reverse stanza documented (`DROP COLUMN IF EXISTS lease_epoch`). |
| `pick_slot.py` | C | Added `epoch` to the `PICK` `SELECT` and `COLS`; output dict gains an `epoch` key (readers-before-writers; un-upgraded readers ignore the extra key via `.get`). |
| `heartbeat.py` | B | **B.1** Replaced `epoch=EXCLUDED.epoch` in the UPSERT `ON CONFLICT … DO UPDATE SET` with `epoch = gpu_slots.epoch + CASE WHEN served_model/nvlink_domain/max_context IS DISTINCT FROM EXCLUDED.* THEN 1 ELSE 0 END` (preserve-and-conditional-bump; `vram_free_mib`/`gpu_util_pct` excluded). **B.2** Made `discover_served_model` **sticky** (BC1): a per-endpoint cache returns the last successfully-resolved id on a transient `/models` failure instead of flapping to the differing static `--served-model` tag. |
| `di_fleet.py` | D | **D.1** `LEASE_CLAIM_SQL` `SET` adds `lease_epoch = epoch` (stamp at claim, server-side). **D.2** `LEASE_RENEW_SQL` `WHERE` adds `(lease_epoch IS NULL OR epoch = lease_epoch)` plus the BC2 freshness/identity term `alive AND heartbeat_ts > now() - interval '45 seconds'`. **D.3** `LEASE_RELEASE_SQL` `SET` adds `lease_epoch = NULL` (cleared together with `lease_id`). `claim()/renew()/release()` Python signatures unchanged. |
| `tests/lease_fakes.py` | D | Extended `FakeSlotDB` to model `epoch`/`lease_epoch`, the renew self-compare + the `alive`+45s freshness term, and a `turnover_endpoint()` PK-split helper. |
| `tests/test_pick_slot.py` | C | `_row()` gains `epoch`; added gate-3 reader test. |
| `tests/test_leases.py` | D | Added gate-1, BC2 hermetic companion, and BC3 tests. |
| `tests/test_heartbeat_epoch.py` | B | **new** — gate-2 writer SQL + BC1 sticky-discovery tests. |
| `tests/test_epoch_pg.py` | B/D | **new, PG-guarded** — gates 1/2/3 + BC1 + BC2 against a real ephemeral Postgres, applying real migrations `001/007/008`. |
| `tests/test_leases_pg.py` | D | Build hygiene: added `epoch BIGINT NOT NULL DEFAULT 0` + `lease_epoch BIGINT` to the hardcoded `_DDL`. |

**The migration is `migrations/008_lease_epoch.sql` (number `008`).** Rationale
(BC4 lowest-unused-`0NN` guard): `migrations/` holds `001`–`007`, so `008` is the
next unused number. The work-packet objective's loose "migration 006" wording is
superseded — `006_peecee_dense_27b.sql` already exists; the committed plan and the
next-unused-number rule both resolve to `008`. The trailing prose in `007` that
mentions a *future* `free_slots`-drop "migration 008" reserves nothing; that
contract migration is not built here.

**Not edited (confirms scope):** `bin/di-fleet` (thin `exec python3 di_fleet.py`
wrapper, unchanged), `heartbeat_all.py` (covered transitively via `from heartbeat
import UPSERT, discover_served_model`), `conftest.py`, `docs/rfc/`.

---

## 2. Falsifiable-gate → test map, with the FINAL verbatim pytest line

### RFC falsifiable-gate → test map

| RFC gate bullet | Test(s) | Kind | Result |
|---|---|---|---|
| **(1)** Bumping `served_model` makes a holder's next renew return **zero rows** (forced re-pick), proven by mutating the row mid-lease | `tests/test_leases.py::test_epoch_change_fences_renew` (+ end-to-end monitor: `::test_epoch_bump_aborts_di_child_in_renew_path`); `tests/test_epoch_pg.py::test_served_model_bump_fences_renew` | hermetic + PG | pass / pass |
| **(2)** A VRAM/util-only change does **not** bump epoch and does **not** invalidate a lease | `tests/test_heartbeat_epoch.py::test_bump_diff_excludes_churn_fields`; `tests/test_epoch_pg.py::test_vram_util_only_change_keeps_epoch_and_lease` | hermetic + PG | pass / pass |
| **(3)** A re-pick after an epoch bump lands on the slot's **new** capability, never the stale one | `tests/test_pick_slot.py::test_pick_surfaces_current_epoch_and_model`; `tests/test_epoch_pg.py::test_repick_after_bump_stamps_new_epoch` | hermetic + PG | pass / pass |

### Binding-constraint → test map

| Constraint | Test(s) | Kind | Result |
|---|---|---|---|
| **BC1** sticky discovery (writer-side analog of gate-2; the gated repair — verifier-enforced) | `tests/test_heartbeat_epoch.py::test_transient_discovery_failure_does_not_flap_or_bump` (+ `_before_any_discovery_uses_static_fallback`, `_successful_rediscovery_updates_the_sticky_value`); PG companion `tests/test_epoch_pg.py::test_sticky_discovery_keeps_epoch_stable` | hermetic + PG | pass / pass |
| **BC2** endpoint-turnover fence — option (a), registry-side freshness/identity (verifier-enforced) | `tests/test_epoch_pg.py::test_endpoint_turnover_fences_old_lease`; hermetic companion `tests/test_leases.py::test_endpoint_turnover_fences_old_lease` | PG + hermetic | pass / pass |
| **BC3** keep the NULL arm; prove steady-state-unreachable | `tests/test_leases.py::test_post_rollout_claim_stamps_non_null_lease_epoch`, `::test_null_lease_epoch_still_renews`, `::test_release_clears_lease_epoch_with_lease_id` | hermetic | pass |
| **BC4** migration-number / committable-not-deployable / reversibility / no column-probing | `migrations/008_lease_epoch.sql` (lowest-unused number; reverse stanza); committed-plan §5 (restated §4 below) | policy | satisfied |

### FINAL verbatim pytest result line

The required command is `python3 -m pytest tests/ -q`. On the bare host
interpreter it fails (finding F1: `/usr/bin/python3: No module named pytest`); run
with the project test interpreter (`/tmp/gpu-fleet-rfc3-venv`) from the integrated
tree, the **canonical default hermetic line is**:

```
63 passed, 2 skipped in 1.21s
```

The 2 skipped are the PG-guarded files, skipped by the `GPU_FLEET_TEST_DB`
ephemeral-only guard when no DB is provided:

```
SKIPPED [1] tests/test_epoch_pg.py:30: set GPU_FLEET_TEST_DB to an ephemeral throwaway cluster to run these
SKIPPED [1] tests/test_leases_pg.py:23: set GPU_FLEET_TEST_DB to an ephemeral throwaway cluster to run these
```

Addressing finding F2, the PG-guarded companions were then run against an
**ephemeral throwaway** Postgres cluster (initdb in `/tmp`, unix-socket-only, no
TCP, `dbname=gpu_fleet_test`, torn down after — the live `gpu_fleet` DB was never
touched). The applied DDL reuses the real `migrations/001,007,008`:

```
# PG-guarded only:  GPU_FLEET_TEST_DB set, tests/test_epoch_pg.py tests/test_leases_pg.py
9 passed in 3.04s
# Full suite with the ephemeral DB configured (the 2 skips now run):
72 passed in 4.02s
```

So: **hermetic default = 63 passed, 2 skipped; with the ephemeral PG cluster = 72
passed, 0 skipped.** The tree is green.

---

## 3. Binding constraints from the committed plan — discharged

Every binding constraint folded into `COMMITTED_PLAN.md` §6 is discharged, with
the verifier-enforced BC1/BC2 gate satisfied both hermetically and on real PG:

- **BC1 — sticky discovery (BLOCKING gate; the reason the design gate could not
  auto-clear).** **DISCHARGED.** `heartbeat.discover_served_model` caches the last
  successfully-resolved `served_model` per endpoint and returns it on a transient
  `/models` failure instead of flapping to the differing static `--served-model`
  tag (`heartbeat.py:188`, `heartbeat.py:205`). Proven by the required writer-side
  no-bump test (`test_transient_discovery_failure_does_not_flap_or_bump`) plus the
  cold-fallback and genuine-rediscovery companions, and the PG companion
  (`test_sticky_discovery_keeps_epoch_stable`). Verifier confirmed.
- **BC2 — endpoint-turnover fence, option (a) registry-side freshness/identity.**
  **DISCHARGED.** `LEASE_RENEW_SQL` requires the leased row to remain `alive` and
  fresh within the same 45s `live_slots` window (`di_fleet.py:133`); when a node
  turns over to a new `endpoint_url` (new PK row), the old leased row ages out and
  its renew returns zero rows. Proven by `test_endpoint_turnover_fences_old_lease`
  (PG) and its hermetic companion. The `di --json` subprocess boundary is
  preserved (fencing is 100% registry-side SQL). Verifier confirmed.
- **BC3 — keep the NULL arm; prove steady-state-unreachable.** **DISCHARGED.** The
  `(lease_epoch IS NULL)` rollout-drain arm is kept; every post-Slice-D claim
  stamps non-NULL `lease_epoch` (`epoch` is `NOT NULL DEFAULT 0`), a NULL lease
  still renews, and `release` clears `lease_epoch` together with `lease_id`. Proven
  by `test_post_rollout_claim_stamps_non_null_lease_epoch`,
  `test_null_lease_epoch_still_renews`, `test_release_clears_lease_epoch_with_lease_id`.
- **BC4 — migration-number / committable-not-deployable / reversibility / no
  column-probing.** **DISCHARGED.** Migration is `008` (lowest unused);
  reversibility = revert Slice D's `di_fleet.py` **with** dropping the column;
  Slice D is independently committable (hermetic-green) but NOT independently
  deployable ahead of `008`; no dynamic column-existence probing. Reverse stanza
  documented in `migrations/008_lease_epoch.sql`.

The surviving design spine (`COMMITTED_PLAN.md` §7, claims C1/C2/C4/C6/C8) is
carried intact: additive reversible migration; DB-side column self-compare with no
consumer epoch state; the in-flight abort inherited (never a second renewer); the
hermetic default stays DB-free; held leases survive ticks (only `epoch` moves).

---

## 4. EXACT operator deployment steps

> These were **NOT** performed by the build. The operator runs them, in the RFC's
> **DB → readers → writers** order, against live infra.

1. **Confirm green on the integrated tree.** `python3 -m pytest tests/ -q` is green
   — canonical hermetic result `63 passed, 2 skipped in 1.21s` (the 2 skips are the
   `GPU_FLEET_TEST_DB`-guarded PG companions). Note the host `/usr/bin/python3`
   lacks `pytest`; use an interpreter that has `pytest` + `psycopg[binary]` (e.g.
   the `/tmp/gpu-fleet-rfc3-venv` test venv). Optional: to also run the PG
   companions, point `GPU_FLEET_TEST_DB` at an **ephemeral throwaway** cluster
   (dbname must contain `test`, never bare `gpu_fleet`) — that yields `72 passed`.

2. **Apply migration `008_lease_epoch.sql` to the live `gpu_fleet` DB —
   migrate-before-restart is sufficient.** The change does **not** alter
   `probe_model`/sentinels (the heartbeat diff touches only the UPSERT epoch `CASE`
   and the sticky `discover_served_model`, not the `probe_model`/sentinel branches),
   and the migration is purely additive (`ADD COLUMN IF NOT EXISTS lease_epoch
   BIGINT`), so it is safe with `gpu-fleet-heartbeat` running. Therefore the
   stop → migrate → start dance is **not** required here; migrate-before-restart
   suffices. (Stop → migrate → start remains available and equally safe if the
   operator prefers it.)

3. **Re-deploy `cp bin/di-fleet ~/.local/bin/` only if `bin/di-fleet` changed —
   it did NOT.** `bin/di-fleet` is unchanged (a thin `exec python3 di_fleet.py`
   wrapper). What changed is `di_fleet.py` and `pick_slot.py`; for those to take
   effect, update the gpu-fleet checkout on consumer hosts. (If your deploy copies
   the wrapper anyway, the `cp` is a harmless no-op.)

4. **`systemctl --user restart gpu-fleet-heartbeat`** so the new `heartbeat.py`
   (preserve-and-conditional-bump UPSERT + sticky discovery) takes effect.

**Backward-compatibility / rollback (BC3/BC4):** until consumers stamp/read
`lease_epoch`, behavior equals today's — the bump is `+0` when no routing field
changes and a NULL `lease_epoch` disables fencing; the only NULL-arm live leases
are pre-upgrade in-flight leases draining within one lease TTL (~45s). To roll
back: revert Slice D's `di_fleet.py` **with** `ALTER TABLE gpu_slots DROP COLUMN
IF EXISTS lease_epoch` — never drop `008` while live Slice-D code is deployed.

---

## 5. Live-infra safety (this apply step)

This apply step was inert with respect to live infra. It ran the hermetic suite
and stood up a disposable Postgres cluster in `/tmp` (unix-socket-only, no TCP,
torn down after) to discharge finding F2. It did **not** connect to or migrate the
live `gpu_fleet` Postgres, did **not** touch the `:5432` cluster, did **not**
restart `gpu-fleet-heartbeat`, and did **not** touch peecee or its GPU. No source
file was modified; the `di --json` subprocess boundary is untouched.
