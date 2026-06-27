---
schema_version: "striatum.finding.v1"
artifact_kind: "finding"
verdict_intent: "accept"
---

# VERIFICATION_REVIEW - RFC 0005 build

author: reviewer-openai-codex-gpt-5.5-001

## Verdict

accept.

I reviewed the actual RFC 0005 build branch `striatum/rfc-0005-build` at `eec6b99e79b4ceac5fe6e4d5ce40745512b5b6d6` from the Striatum worktree `.striatum/worktrees/wt_2918de3e10199fd3be2ffd4142296018`. I did not edit source code. The implementation satisfies the RFC falsifiable gate and discharges the committed plan's build-review constraints.

The source diff is scoped to the declared build envelope: `migrations/010_exporter_capacity_signal.sql`, `heartbeat.py`, `heartbeat_all.py`, `pick_slot.py`, `di_fleet.py`, tests, and the build claim ledger. It does not edit `docs/rfc/`, workflow definitions, systemd/service files, `bin/di-fleet`, or live-host configuration.

## Test Results

Required verifier command, run from the build worktree with bytecode/pytest cache redirected out of the repo:

```text
$ python3 -m pytest tests/ -q
........................................................................ [ 76%]
......................                                                   [100%]
94 passed, 4 skipped in 1.64s
```

The four skipped modules are the `GPU_FLEET_TEST_DB`-guarded Postgres proof modules. I then created a throwaway local Postgres 17 cluster under `/tmp`, using a unix socket only and database name `gpu_fleet_test`, and ran the full suite with `GPU_FLEET_TEST_DB` set:

```text
$ GPU_FLEET_TEST_DB="dbname=gpu_fleet_test host=/tmp/... port=55434" python3 -m pytest tests/ -q
........................................................................ [ 58%]
....................................................                     [100%]
124 passed in 6.13s
```

I did not connect to the live `gpu_fleet` database, restart `gpu-fleet-heartbeat`, SSH to peecee, or touch a GPU.

## Gate Check

- **Frozen/stale capacity decay and BC2 single-clock freshness:** satisfied. The migration/view and inline reader predicates compute staleness from same-clock summands: node-clock `fast_source_age_s` plus DB-clock `now()-updated_ts`, never node timestamp minus DB timestamp. Hermetic tests A1/A2 prove frozen decay and skew resistance; PG tests A3/A4 prove the actual pick path marks stale rows degraded while keeping fresh skewed rows measured.
- **Raw churn within a band does not bump epoch; slow capability changes do:** satisfied. `CAPACITY_UPSERT` stores banded values and only updates on band changes, while `gpu_slots.epoch` is bumped for slow capability fields such as `mig_mode`/`ecc_mode`, not fast capacity churn. Hermetic test C inspects the SQL; PG tests D/E prove no epoch bump for within-band churn and renew fencing after MIG/ECC changes.
- **Exporter over-reporting cannot increase routable capacity:** satisfied. `capacity_telemetry()` takes the lower of probe floor and exporter free, and PG test G proves a slot with exporter free above the probe floor refuses a request that only fits the exporter value.
- **Unrecognized PID phantom and puller companion writes:** satisfied. Hermetic test H proves unknown PID VRAM shrinks `effective_free` and clears on exit. PG test I proves the claim path routes around the shrunken slot. M/M2 prove `heartbeat_all.pull_write()` writes the companion row after the liveness UPSERT under the savepoint guard.
- **Fleet-floor/dead-man behavior:** satisfied. `pick_slot.PICK` COALESCEs stale `effective_free` through to `vram_free_mib` and reports `degraded`, so stale fast fields do not empty the router. Test J pins the non-empty degraded result, and PG test A3 exercises the real stale-pick path.
- **`ollama-ondemand` and None/0 baseline safety:** satisfied. K proves the residency-only floor path does not invoke scratch allocation; K2 proves failed probes and cold `ollama-ondemand` rows are well formed; K3 proves real SQL yields NULL slowdown for None/0 baselines and keeps the cold baseline sticky across a later hot reprobe.
- **Hermetic/live-infra boundary:** satisfied. The default suite is green with DB tests guarded. The PG modules refuse bare `dbname=gpu_fleet`, require an ephemeral test database name, and ran successfully against the throwaway cluster.
- **BC1 request-aware production headroom:** satisfied. `pick_slot.PICK` and `di_fleet.LEASE_CLAIM_SQL` both use defined inline KV SQL over `model_capacity` plus the same `max_context` scalar. N1 proves production orchestration threads non-default `max_context` through `route_slots`/pick, first claim, and failover transfer, with 4k accepted and 32k refused against the same slot. N2 proves the real PG pick/claim predicates match that behavior. N3 proves the `di --json` boundary remains subprocess/argv plus registry SQL, with no engine or GPU-library import.
- **F-CARD/F-LOCK self-hardening:** satisfied. Migration 010 makes `capacity_policy` a true singleton and `model_capacity` PK-keyed; pick locks `FOR UPDATE OF gpu_slots SKIP LOCKED` over the base table, never the diagnostic view. P1/P2/Q prove no view-locking, no duplicated slot row, and idempotent re-apply/singleton behavior.

## Binding Constraints

- **BC1:** discharged by the production `max_context` threading, real pick/claim headroom predicates, defined inline `kv_bytes`, and no-engine-import boundary.
- **BC2:** discharged by single-clock staleness in migration/view, pick, claim, hermetic skew tests, and PG frozen-source tests.
- **BC3:** discharged by SQL-side `live_slowdown_factor` guarded with `CASE`/`NULLIF`, savepoint-guarded companion writes, and None/0/hot-restart tests.
- **BC4:** discharged by puller companion write integration under the same savepoint discipline.
- **BC5:** discharged by migration comments and deployment contract: migration 010 is the hard DB-first precondition, with writer-vs-writer ordering separated from DB->writer->reader deployment.
- **F-CARD/F-KEYS/F-LOCK/F-BASE:** discharged by singleton/PK policy schema, all row-builders carrying `mig_mode`/`ecc_mode`, base-table locking, and sticky cold-baseline SQL/tests.

## Migration And Boundaries

`migrations/` contains `001` through `009`, and `010_exporter_capacity_signal.sql` is the next unused migration number. The migration is additive and reversible: it adds nullable/defaulted companion/policy/model tables, a read-only view, and nullable `mig_mode`/`ecc_mode` columns; it renames/drops nothing. Re-apply idempotence and singleton cardinality are proven by PG test Q.

The `di --json` boundary is intact. Request capacity is sourced from argv (`--max-context`) plus registry SQL (`capacity_policy`/`model_capacity`), and `di_fleet` still launches the child through `node`/`subprocess` rather than importing the engine. The implementation does not perform live hardware measurement for model capacity; `model_capacity` remains operator-seeded data.