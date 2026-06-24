---
schema_version: "striatum.finding.v1"
artifact_kind: "finding"
verdict_intent: "accept_with_findings"
---

# VERIFICATION_REVIEW - RFC 0002 build

author: reviewer-openai-codex-gpt-5.5-001

## Verdict

accept_with_findings.

I reviewed `striatum/rfc-0002-build-2` at
`ce891b19d63c3caff6b3202f41c11aa8462bf652` from a clean `/tmp` archive. I did not edit
source code. The branch state satisfies the RFC 0002 falsifiable gate and discharges the
committed plan's BC1-BC8 verification constraints.

Finding: the current run's Git delta from `origin/master` is artifact/workflow-only
(`CLAIM_LEDGER.md`, `PRIOR_FINDINGS.md`, and the workflow branch/context update); no
implementation files changed in this run. I therefore verified the committed branch
source itself, not just the run delta or the claim ledger. The source implementation is
present in the branch/base and is green under both the hermetic and PG-gated suites.

## Test Results

Default verifier command, run from the clean target-branch archive:

```text
$ python3 -m pytest tests/ -q
........................................................................ [ 90%]
........                                                                 [100%]
80 passed, 3 skipped in 1.36s
```

Full PG-gated run, against a throwaway Postgres 17 cluster created under `/tmp`, using a
unix socket only, no TCP, `fsync=off`, and `GPU_FLEET_TEST_DB` set to
`dbname=gpu_fleet_test`:

```text
$ GPU_FLEET_TEST_DB="dbname=gpu_fleet_test host=$PGDATA user=postgres" python3 -m pytest tests/ -q
........................................................................ [ 72%]
...........................                                              [100%]
99 passed in 4.06s
```

The PG test modules guard against live DB use and refuse bare `dbname=gpu_fleet`; I did
not touch the live registry, restart `gpu-fleet-heartbeat`, SSH to peecee, or touch a GPU.

## Gate Check

- **No SPOF:** satisfied. The global puller lease uses `fleet_meta.holder` with a 15s TTL
  (`heartbeat_all.PULLER_LEASE_TTL = 15`), which is strictly below the 45s freshness
  window. `test_puller_lease.py::test_cas_grants_one_then_deadman_failover` proves one
  holder and deadman takeover, and
  `test_lifecycle_pg.py::test_puller_failover_no_ageout` runs the real CAS against
  migration 009 and verifies the slot remains in `routable_slots` across takeover.
- **Zero-touch register:** satisfied. `heartbeat.UPSERT` inserts new rows as
  `status='unverified'`, seeds `probe_streak`, and stamps `heartbeat_ts=now()`;
  `heartbeat_once(..., push=True)` runs the node lease CAS as non-gating and always
  executes the UPSERT. `test_self_push_no_fleet_node_registers_and_graduates` proves a
  node absent from `fleet_nodes` registers, graduates after `GRADUATION_STREAK`, and is
  not pruned while fresh.
- **Anti-lie:** satisfied. Failed probes reset or hold streak at zero and never enter
  `routable_slots`; routing/claiming also requires `status='routable'` and measured
  `vram_free_mib`. `test_failed_probe_big_declared_never_graduates` proves a never-serving
  big claim cannot graduate or be claimed, and `test_big_declared_small_measured_routes_only_measured`
  proves a real small GPU can graduate but only routes measured VRAM.
- **Single writer:** satisfied, including the prior blocking race. The puller skips fresh
  per-node leases at FETCH time, and `heartbeat_all.pull_write()` rechecks a fresh push
  lease with `SELECT ... FOR UPDATE` in the same transaction as the UPSERT. The PG test
  `test_pull_yields_when_push_acquires_after_fetch` drives the exact fetch-before-push-
  before-write interleaving and verifies the stale pull write returns zero rows while the
  pusher's row remains.
- **Identity survives churn:** satisfied. `gpu_uuid` is COALESCE-preserved on unknown
  pull reports, matching UUIDs keep a routable row routable, and known mismatches reset
  streak/status. Covered by `test_matching_uuid_carries_routable_forward`,
  `test_reboot_same_uuid_skips_requarantine`, and `test_hot_swap_demotes_to_unverified`.
- **peecee pull-only / BC8:** satisfied for committed option (a). The code keeps peecee's
  existing SSH-via-pull `gpu_cmd`; `ollama_ondemand_liveness` fails closed on
  `gpu_stats` errors, and `probe_node` has no DB connection/path and stamps
  `boot_epoch=None` for pull rows. `test_probe_node_ollama_ondemand_not_loadable_does_not_probe`
  proves de-listing when marker owns the card, and `test_pull_only_node_has_no_db_path`
  proves no fleet code/DB credential path on peecee.
- **No node wall-clock for `heartbeat_ts`:** satisfied. The UPSERT writes `now()` on both
  insert and conflict paths, and the production row dict carries no `heartbeat_ts`.
  `test_upsert_stamps_heartbeat_ts_from_db_clock` pins that. Lease and driver freshness
  predicates also use Postgres `now()`; `test_lease_no_consumer_clock.py` and
  `test_driver_lease.py` pin the no-client-clock structure.

## Binding Constraints

- **BC1:** discharged. Self-push lease CAS is non-gating and no-`fleet_nodes` self-push
  registration graduates under the real migrations.
- **BC2:** discharged. `boot_epoch = COALESCE(EXCLUDED.boot_epoch, gpu_slots.boot_epoch)`;
  the PG test proves NULL pull writes preserve the push ratchet and stale writes remain
  refused.
- **BC6:** discharged. The ratchet predicate is strict `EXCLUDED.boot_epoch > gpu_slots.boot_epoch`,
  and equal-epoch replay moves no fields and does not restamp `heartbeat_ts`.
- **BC7:** discharged. Known `gpu_uuid` mismatch resets `probe_streak` to 1 and status to
  `unverified`; matching/unknown identities preserve trust as specified.
- **BC3:** discharged. Puller lease TTL is 15s, strictly below the 45s live/routable
  window, and PG failover preserves routability across takeover.
- **BC4:** discharged. Per-node lease freshness is evaluated server-side in both FETCH
  and write-time guard paths; the guard binds only node identity, not a client timestamp.
- **BC5:** discharged. Migration 009 creates `fleet_meta(holder, lease_until)`, matching
  the CAS and PG tests.
- **BC8:** discharged. Option (a) is preserved: no HTTP-only peecee liveness is claimed,
  no SSH-retirement step ships, and peecee remains pull-monitored without local fleet
  code or DB credentials.

## Migration And Boundaries

`migrations/` contains 001 through 009, and `009_zero_touch_lifecycle.sql` is the next
unused number. It is additive, backfills existing slots to `routable`, creates
`routable_slots` alongside `live_slots`, and includes a reverse block.

The consumer boundary is intact: `di_fleet.py` still launches `node ... --json --quiet`
with `subprocess.Popen` and acts on the process handle. The branch diff contains no live
infra operation; live-infra references are documentation or guarded tests only.
