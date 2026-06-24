---
schema_version: striatum.decision.v1
decision_id: "rfc-0002-build-override-single-writer"
run_id: "run_c0712bbd7d8ae94afd34ed89715a2cd2"
artifact_kind: decision
owner: human
outcome: accepted
follow_up_required: false
title: "Accept RFC 0002 build; supersede review#2 needs_revision (single-writer race verified closed, stale-code false positive)"
created_at: "2026-06-23T23:47:33Z"
---

# Accept RFC 0002 build; supersede review#2 needs_revision (single-writer race verified closed, stale-code false positive)

Decision ID: `rfc-0002-build-override-single-writer`
Run ID: `run_c0712bbd7d8ae94afd34ed89715a2cd2`
Outcome: `accepted`

## Rationale

codex review#2 (needs_revision) is a FALSE POSITIVE. Its blocking single-writer finding and reproducer used the raw heartbeat.UPSERT constant, bypassing the production write path, and it cited a draft#1 test name (test_big_declared_small_measured_not_routable) that is ABSENT from the reviewed build tip e651b0d -- it inspected stale code. The actual build closes the fetch-before-lease race in PRODUCTION: heartbeat_all.tick() routes every probed pull row through pull_write(), which runs PULL_WRITE_GUARD (SELECT 1 ... driven_by IS NOT NULL AND now() < lease_until FOR UPDATE) and writes ZERO rows (rollback) when a fresh push-lease owns the node, serializing the lease-recheck-and-write against the self-push NODE_LEASE_CAS -- without re-introducing BC1 (a no-fleet_nodes self-pusher is never in the puller FETCH). Operator independently verified against an ephemeral Postgres 17 cluster (dbname=gpu_fleet_test): hermetic suite 80 passed/3 skipped; full PG suite 99 passed, including test_pull_yields_when_push_acquires_after_fetch -- the exact two-transaction interleaving review#2 described (puller yields, pusher row m-PUSH/4242 survives, puller resumes on lease lapse) -- plus the BC2/BC6/BC7/BC3 discharge tests. Anti-lie is split into two literal halves, both green: test_failed_probe_big_declared_never_graduates (the RFC 'never graduates' clause) and test_big_declared_small_measured_routes_only_measured. The build satisfies the RFC falsifiable gate and the committed plan's C9/BC1 final-review requirement; the needs_revision verdict does not hold against the verified code. Override to accept and proceed to apply.
