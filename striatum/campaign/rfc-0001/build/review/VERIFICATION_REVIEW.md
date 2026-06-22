---
schema_version: "striatum.finding.v1"
artifact_kind: "finding"
verdict_intent: "accept_with_findings"
---

# VERIFICATION_REVIEW - RFC 0001 build

author: reviewer-openai-codex-gpt-5.5-003

## Verdict

accept_with_findings.

I reviewed the current `striatum/rfc-0001-build-2` revision at
`a1739d1db7487dd3d58ccac70b8341aad3636336` from a clean `/tmp` archive of that
branch. I did not edit source code. I found no blocking implementation issue that
requires another revision.

The prior attempt's blocking finding was that runtime failover bypassed the atomic
release-plus-claim path. That is fixed in this revision: production `main()` wires
`dispatch(..., failover_fn=leased_failover)` (`di_fleet.py:896`, `di_fleet.py:903`);
`dispatch()` routes leased failures through the supplied failover function
(`di_fleet.py:609`, `di_fleet.py:617`); `run_leased_shard()` leaves a still-held dead
lease on `ShardDied` so it is not released before replacement claim
(`di_fleet.py:442`, `di_fleet.py:466`); and `run_failover_shard()` uses a
non-autocommit transfer connection, calls `failover_transfer()`, and commits once
(`di_fleet.py:505`, `di_fleet.py:508`, `di_fleet.py:511`). The new production-path guard
`test_dispatch_failover_routes_through_atomic_transfer_not_release_then_claim`
fails if the dead lease is released outside the transfer (`tests/test_di_fleet.py:486`).

## Test Results

Required verifier command, run from the clean target-branch archive:

```text
$ python3 -m pytest tests/ -q
/usr/bin/python3: No module named pytest
```

The host's `/usr/bin/python3` cannot import `pytest`, so the literal command is not
runnable in this environment. I then ran the same suite with the available
pytest/psycopg interpreter:

```text
$ /tmp/praxis-s3-venv/bin/python -m pytest tests/ -q
....................................................                     [100%]
52 passed, 1 skipped in 1.30s
```

`GPU_FLEET_TEST_DB` was not set. The skip is the guarded ephemeral-Postgres module;
I did not connect to the live `gpu_fleet` database or touch live infrastructure.

## Gate Check

- **BC1-A responsive abort:** satisfied against the scoped criterion in
  `PRIOR_FINDINGS_AND_BC1_SCOPE.md`. `run_leased_shard()` claims before launch, uses
  `subprocess.Popen`, and `_monitor()` terminates the child synchronously in the same
  path that observes `renew()` returning false (`di_fleet.py:372`, `di_fleet.py:408`,
  `di_fleet.py:411`). `test_lost_lease_aborts_di_child_in_renew_path` drives the
  production claim/renew seam through `FakeSlotDB` and a real successor claim; there is
  no synthetic `gpu_busy` or production-absent sleep handshake (`tests/test_di_fleet.py:309`).
- **BC1 residual:** documented, not hidden. `_monitor()` and `CLAIM_LEDGER.md` state the
  accepted client-side deadman residual for fully frozen consumers / zombie races
  (`di_fleet.py:388`, `striatum/campaign/rfc-0001/build/CLAIM_LEDGER.md:157`).
- **Two concurrent capacity-1 claims:** the real-Postgres test uses two connections and a
  barrier and asserts exactly one `claim()` returns a lease
  (`tests/test_leases_pg.py:80`). It was skipped here because no throwaway DB was
  configured.
- **Deadman expiry with no reaper:** covered by the guarded PG test
  `test_unrenewed_lease_self_expires` and hermetic companion
  `test_renew_false_after_autonomous_expiry` (`tests/test_leases_pg.py:101`,
  `tests/test_leases.py:64`).
- **Zombie renew fencing:** covered by guarded PG and hermetic tests
  (`tests/test_leases_pg.py:114`, `tests/test_leases.py:71`).
- **K-fan-out and failover:** K-fan-out claims distinct leases
  (`tests/test_di_fleet.py:423`); production failover now routes through the atomic
  transfer guard (`tests/test_di_fleet.py:486`); transfer rollback atomicity is covered
  by the guarded PG test (`tests/test_leases_pg.py:127`); and the no-survivor branch frees
  the dead lease immediately (`tests/test_di_fleet.py:466`).
- **No consumer wall-clock in claim/renew/release:** lease SQL uses Postgres `now()`, and
  the AST inspection test confirms the lease predicate functions do not read
  `time`/`datetime` (`tests/test_lease_no_consumer_clock.py:20`,
  `tests/test_lease_no_consumer_clock.py:31`).
- **BC2 backward compatibility:** `pick_slot.py` keeps returning `free_slots` as a
  `capacity` alias, pinned by `test_output_still_contains_free_slots`
  (`pick_slot.py:66`, `tests/test_pick_slot.py:58`).
- **BC3 NULL-safe jitter:** the picker uses
  `hashtext(COALESCE(%(job)s::text, '') || node || slot_id::text)`, with tests for
  `job=''` and `job=None` (`pick_slot.py:39`, `tests/test_pick_slot.py:70`).

## Migration And Boundaries

The branch uses `migrations/007_exclusive_slot_leases.sql` because the repository already
has `006_peecee_dense_27b.sql`; this is the correct next migration number in the current
tree. The migration is additive and reversible, leaves `free_slots` and
`gpu_slots_claim_idx` intact, and records DB -> readers -> writers deployment ordering
(`migrations/007_exclusive_slot_leases.sql:19`, `migrations/007_exclusive_slot_leases.sql:23`,
`migrations/007_exclusive_slot_leases.sql:55`).

The source diff touches only `di_fleet.py`, `pick_slot.py`, the new migration, tests, and
the build claim ledger. It does not change `heartbeat.py`, `heartbeat_all.py`,
`bin/di-fleet`, `conftest.py`, or `docs/rfc/`. I did not apply any migration, restart
`gpu-fleet-heartbeat`, touch peecee, or touch a GPU. The `di --json` boundary remains a
subprocess boundary; BC1 acts only on the `Popen` handle, not by importing the Node engine.