---
schema_version: "striatum.finding.v1"
artifact_kind: "finding"
verdict_intent: "accept_with_findings"
---

# VERIFICATION_REVIEW - RFC 0003 build

author: reviewer-openai-codex-gpt-5.5-001

## Verdict

accept_with_findings.

I reviewed the actual source-change commit for the RFC 0003 build,
`aecc72d` (`striatum: lane source changes
(job job_run_2ecf55525f7b2cf69217837e283f228d_draft)`), from the daemon
worktree at `striatum/rfc-0003-build`. I did not edit source code. I found no
blocking implementation issue in the default hermetic path; the findings are
that the host `/usr/bin/python3` lacks pytest and the real-Postgres companion
tests were not run because no ephemeral `GPU_FLEET_TEST_DB` was configured.

The source-change commit is scoped to the intended build files:
`di_fleet.py`, `heartbeat.py`, `pick_slot.py`,
`migrations/008_lease_epoch.sql`, and tests. It does not edit `bin/di-fleet`,
`heartbeat_all.py`, `conftest.py`, or `docs/rfc/`.

## Test Results

Required command, first attempted with the host interpreter:

```text
$ python3 -m pytest tests/ -q
/usr/bin/python3: No module named pytest
```

I then used a throwaway venv under `/tmp` containing only the test dependencies
needed by this repo (`pytest` and `psycopg[binary]`) and reran the same command
form by putting that venv's `python3` first on `PATH`:

```text
$ python3 -m pytest tests/ -q
...............................................................          [100%]
63 passed, 2 skipped in 1.48s
```

Skip reasons from the same suite with `-rs`:

```text
SKIPPED [1] tests/test_epoch_pg.py:30: set GPU_FLEET_TEST_DB to an ephemeral throwaway cluster to run these
SKIPPED [1] tests/test_leases_pg.py:23: set GPU_FLEET_TEST_DB to an ephemeral throwaway cluster to run these
63 passed, 2 skipped in 1.48s
```

I did not set `GPU_FLEET_TEST_DB`, did not connect to the live `gpu_fleet`
database, did not restart `gpu-fleet-heartbeat`, and did not touch peecee or a
GPU.

## RFC 0003 Gate Check

- **Gate 1: changing `served_model` forces the holder's next renew to zero
  rows.** Satisfied. The heartbeat UPSERT bumps `epoch` only on
  `served_model`, `nvlink_domain`, or `max_context` changes
  (`heartbeat.py:55`). Claims stamp `lease_epoch = epoch`, and renews require
  `(lease_epoch IS NULL OR epoch = lease_epoch)` (`di_fleet.py:99`,
  `di_fleet.py:133`). The default-suite hermetic tests mutate the row mid-lease
  and verify renew returns false, then drive the monitor path and verify the
  `di --json` child is terminated (`tests/test_leases.py:145`,
  `tests/test_leases.py:157`). The real-Postgres companion test body also
  drives the actual UPSERT and renew against migrations 001/007/008, but it was
  skipped here behind the ephemeral DB guard (`tests/test_epoch_pg.py:102`).
- **Gate 2: VRAM/util churn does not bump epoch or invalidate a lease.**
  Satisfied for the default review gate. The UPSERT CASE excludes
  `vram_free_mib` and `gpu_util_pct` from the bump diff, and
  `tests/test_heartbeat_epoch.py::test_bump_diff_excludes_churn_fields`
  inspects the production SQL to pin that property
  (`tests/test_heartbeat_epoch.py:22`). The real-Postgres companion test would
  prove the non-bump/non-fence behavior through the actual UPSERT and renew, but
  was skipped without an ephemeral DB (`tests/test_epoch_pg.py:119`).
- **Gate 3: re-pick after an epoch bump lands on the new capability, not stale
  state.** Satisfied at the code/test level, with the same DB-skip caveat.
  `pick_slot.py` now selects and returns `epoch` with `served_model`
  (`pick_slot.py:26`, `pick_slot.py:44`), and the default-suite test verifies
  the current row's new model and epoch are surfaced
  (`tests/test_pick_slot.py:95`). The real-Postgres companion test body proves a
  fresh post-bump claim stamps the new epoch and renews against it, but was
  skipped here (`tests/test_epoch_pg.py:134`).

## Binding Constraints

- **BC1 sticky discovery:** satisfied. `discover_served_model()` caches the last
  successful endpoint resolution and returns it on transient `/models` failure
  rather than flapping to a differing static fallback (`heartbeat.py:188`,
  `heartbeat.py:205`). The default-suite tests verify the transient failure does
  not change `served_model`, cold failures still use the fallback, and genuine
  rediscovery updates the sticky value (`tests/test_heartbeat_epoch.py:60`,
  `tests/test_heartbeat_epoch.py:85`,
  `tests/test_heartbeat_epoch.py:98`).
- **BC2 endpoint-turnover fence:** satisfied in the default hermetic gate. Renew
  requires the leased row to remain `alive` and fresh within the same 45s window
  (`di_fleet.py:133`). The hermetic test models a new endpoint URL for the same
  `(node, slot_id)`, lets the old PK row age past 45s while the lease remains
  unexpired, and verifies renew returns false (`tests/test_leases.py:185`). The
  real-Postgres companion test body covers the same case with real rows and was
  skipped behind `GPU_FLEET_TEST_DB` (`tests/test_epoch_pg.py:155`).
- **BC3 NULL-arm invariants:** satisfied. The NULL arm remains in renew, claims
  stamp non-NULL `lease_epoch`, NULL pre-upgrade leases still renew for rollout
  drain, and release clears `lease_epoch` with `lease_id`
  (`di_fleet.py:133`, `di_fleet.py:151`,
  `tests/test_leases.py:202`, `tests/test_leases.py:212`,
  `tests/test_leases.py:223`).
- **BC4 migration number and reversibility:** satisfied. `migrations/` contains
  `001` through `007`, so `008_lease_epoch.sql` is the next unused number. The
  migration is additive (`ADD COLUMN IF NOT EXISTS lease_epoch BIGINT`), has no
  default/backfill/index/constraint, and documents the reverse operation
  (`migrations/008_lease_epoch.sql:1`, `migrations/008_lease_epoch.sql:26`).

## Boundaries

The `di --json` boundary remains a subprocess boundary. `di_fleet.py` launches
`node ... --json --quiet` with `subprocess.Popen` and the renew monitor acts only
on the child process handle (`di_fleet.py:361`, `di_fleet.py:395`,
`di_fleet.py:404`). The implementation does not import the Node engine.

`heartbeat_all.py` remains a shared writer through `from heartbeat import UPSERT,
discover_served_model`, so the single UPSERT and sticky-discovery changes cover
both writer entry points without editing the driver (`heartbeat_all.py:22`).
