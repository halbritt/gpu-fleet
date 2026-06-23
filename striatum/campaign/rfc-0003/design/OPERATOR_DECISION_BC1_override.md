---
schema_version: striatum.decision.v1
decision_id: "rfc-0003-design-override-bc1"
run_id: "run_7ab4211a80df8b8943ec37d0e43b2280"
artifact_kind: decision
owner: human
outcome: accepted_with_follow_up
follow_up_required: true
title: "Accept RFC 0003 BC1-BC4 as binding build constraints; supersede needs_revision (cycle budget exhausted)"
created_at: "2026-06-23T05:35:58Z"
---

# Accept RFC 0003 BC1-BC4 as binding build constraints; supersede needs_revision (cycle budget exhausted)

Decision ID: `rfc-0003-design-override-bc1`
Run ID: `run_7ab4211a80df8b8943ec37d0e43b2280`
Outcome: `accepted_with_follow_up`

## Rationale

The adjudicator confirmed RFC 0003's design SPINE is sound and unrefuted (additive nullable migration 008 lease_epoch; DB-side column self-compare renew leaving renew(conn,lease_id) signature-stable; in-flight abort inherited from RFC-0001 _monitor; hermetic+ephemeral-PG test split; DB->writer->reader->consumer order; di --json boundary). Verdict needs_revision (not reject) because the blocking defect is dischargeable in the BUILD: BC1 = a real spurious-eviction interaction where discover_served_model's transient static-tag fallback flaps served_model, bumps epoch, and evicts a healthy di child (the re-pick storm gate-bullet-2 excludes). The design mechanism (epoch CASE + column set) is correct; only the served_model INPUT must stop flapping. Override to accept_with_findings: the committer folds BC1-BC4 into the committed plan as binding constraints; the build discharges them with tests; the independent verifier enforces BC1+BC2 before accept.

## Follow-Up

Build discharges: BC1 (sticky discovery — cache last successfully-discovered served_model; do NOT overwrite with a differing static --served-model fallback on transient /models failure; writer-side test that a transient discovery failure does not change served_model and does not bump epoch). BC2 (held-lease endpoint-turnover — EITHER a registry-side freshness/identity renew term keyed to the same 45s live_slots window with a turnover test, OR an explicit narrowing of the child-death/failover claim plus a child-death/failover test; do not keep 'covered' wording with no test). BC3 (keep the lease_epoch IS NULL rollout-drain arm; ship steady-state-unreachability tests + document the invariant). BC4 (disambiguate Slice D independently-committable vs not independently-deployable-ahead-of-008). Verifier gates on BC1 and BC2 tests.
