---
schema_version: striatum.decision.v1
decision_id: "rfc-0001-design-override-bc1"
run_id: "run_74040bd3a38125e720db1ad27034d0bf"
artifact_kind: decision
owner: human
outcome: accepted_with_follow_up
follow_up_required: true
title: "Accept BC1-BC4 as binding build constraints; supersede needs_revision (cycle budget exhausted)"
created_at: "2026-06-22T17:39:40Z"
---

# Accept BC1-BC4 as binding build constraints; supersede needs_revision (cycle budget exhausted)

Decision ID: `rfc-0001-design-override-bc1`
Run ID: `run_74040bd3a38125e720db1ad27034d0bf`
Outcome: `accepted_with_follow_up`

## Rationale

The needs_revision verdict (re-confirmed) identified four landed constraints. BC1 (critical) -- central renewer + blocking subprocess.run permits a physical GPU double-use after mid-shard lease loss -- is a well-scoped, dischargeable BUILD constraint (the holder itself named the Popen + per-shard lease-monitor fix), not an undischargeable design defect; the honest disposition is accept_with_findings. The workflow's revision cycle routed to falsifier_1 (re-challenge) rather than the holder (revise), so the plan could not be repaired in-cycle and the budget exhausted -- a template routing limitation, not a design rejection. Superseding: the committer MUST fold BC1-BC4 into the committed plan as binding constraints; the build MUST implement BC1 and its no-live-infra falsifying test; the independent verifier MUST confirm the in-flight-abort test before accept.

## Follow-Up

Build discharges BC1 (Popen + per-shard lease monitor terminates the di --json child on lease loss, preserving the process-handle boundary; + falsifying test that a long-running fake child is killed before any second claim), BC2 (alias free_slots in pick_slot output until the contract migration + regression test), BC3 (NULL-safe jitter via hashtext(COALESCE(job,'')||node||slot_id::text)), BC4 (no-survivor failover explicitly releases the dead lease). Verifier gates on BC1's test.
