# RFC 0002 build — operator report

Built, verified, and integrated to `master` (merge `af991b8`). The build run's
`apply` stage never ran, so this report stands in for the `FINAL_REPORT.md` that
stage would have produced. The build is **inert wrt live infra** — nothing below
has been applied to the running fleet yet.

## What shipped

Migration `009_zero_touch_lifecycle.sql` (additive) plus the five
writer-before-reader slices from `COMMITTED_PLAN.md`:

- **Slice 0** — `gpu_slots` adds `status`/`probe_streak`/`gpu_uuid`/`boot_epoch`;
  `fleet_nodes` adds `driven_by`/`lease_until`; new single-row `fleet_meta(holder,
  lease_until)`; new `routable_slots` view alongside `live_slots`; backfill every
  existing slot to `status='routable'`.
- **Slice 1** — `heartbeat.py`: quarantine→graduate (`GRADUATION_STREAK=3`),
  `gpu_uuid` capture, strictly-monotonic `boot_epoch` ratchet (strict `>`), and the
  stale-only `PRUNE` fix.
- **Slice 2** — `heartbeat_all.py`: global puller-lease CAS (`PULLER_LEASE_TTL=15`).
- **Slice 3** — per-node driver-lease, non-gating self-push CAS, and the write-time
  `pull_write()` `FOR UPDATE` guard that closes the fetch→write single-writer race.
- **Slice 4** — `pick_slot.py` + `di_fleet.py` gate routing on `status='routable'`.

## Verification (operator-run, before merge)

Against an ephemeral Postgres 17 cluster (`dbname=gpu_fleet_test`, migrations
`001`–`009` applied; live `gpu_fleet` never touched):

- hermetic `pytest tests/ -q`: **80 passed, 3 skipped**
- full PG suite: **99 passed**, including the gate tests:
  - `test_pull_yields_when_push_acquires_after_fetch` — the two-transaction
    single-writer race: the puller yields and the self-pusher's row survives (C9/BC1).
  - `test_failed_probe_big_declared_never_graduates` +
    `test_big_declared_small_measured_routes_only_measured` — both anti-lie halves.
  - BC2 (`boot_epoch` COALESCE), BC6 (strict-`>` no-op replay), BC7 (uuid hot-swap
    re-quarantine), BC3 (puller failover, no age-out), identity-survives-churn.

## Operator deployment — NOT YET DONE

Apply order per `COMMITTED_PLAN.md` §2/§4: **DB → writer → consumers**.

1. Apply `migrations/009_zero_touch_lifecycle.sql` to the live `gpu_fleet`
   (additive; safe even with `gpu-fleet-heartbeat` running).
2. Redeploy `heartbeat.py` + `heartbeat_all.py` (Slices 1–3).
3. Redeploy `pick_slot.py` + `di_fleet.py` (Slice 4 — activates the
   `status='routable'` gate; deploy **last**).
4. `systemctl --user restart gpu-fleet-heartbeat`

The backfill leaves every existing slot `status='routable'`, so behavior equals
today's until graduation logic populates new nodes. **BC8 option (a): do NOT retire
peecee's cross-host SSH `nvidia-smi` `gpu_cmd` in v1** — peecee stays on SSH-via-pull
liveness. Deploying a second puller (SPOF kill) and any push sidecar on the trusted
quad-server are separate, out-of-band operator steps.

## Provenance

Build run `run_c0712bbd7d8ae94afd34ed89715a2cd2` was **canceled**, not completed.
Its codex review returned `needs_revision` three times on a single-writer finding
that is a **verified false positive**: the review re-ran draft#1's 95-test suite and
cited a draft#1 test name despite draft#2 having committed `pull_write()` 20 minutes
earlier — a worktree-staleness race. The `revision_routing` checkpoint's `continue`
and `override` were both blocked by a striatum blob-provenance gate (the blob bucket
is `not_provisioned`, so the GC'd `blob_exhaust` review bodies report "not
inspectable"). Landed by direct merge per operator decision
`rfc-0002-build-override-single-writer` (`OPERATOR_DECISION_single_writer_override.md`).
