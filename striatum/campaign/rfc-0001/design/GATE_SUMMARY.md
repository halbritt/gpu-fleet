---
schema_version: striatum.synthesis.v1
artifact_kind: synthesis
author: adjudicator-claude-opus-4.8-003
run_id: run_74040bd3a38125e720db1ad27034d0bf
workflow: rfc-0001-design
role: adjudicator
title: "GATE SUMMARY — RFC 0001 Exclusive slot leases (design gate)"
summary: "Design→build gate cleared with findings (accept_with_findings, via operator override superseding an exhausted needs_revision cycle). BC1–BC4 binding; verifier gates on BC1. Build executes COMMITTED_PLAN.md."
status: accept_with_findings
tags: [rfc-0001, design-gate, accept_with_findings, operator-override, BC1, BC2, BC3, BC4, verifier-gates-on-BC1]
---

# GATE SUMMARY — RFC 0001 Exclusive slot leases (design gate)

author: adjudicator-claude-opus-4.8-003

The design→build gate for [`docs/rfc/0001-exclusive-slot-leases.md`](../../../../docs/rfc/0001-exclusive-slot-leases.md)
is **cleared with findings**. The build run executes the committed plan at
[`striatum/campaign/rfc-0001/design/COMMITTED_PLAN.md`](./COMMITTED_PLAN.md), which folds in the four
binding constraints (BC1–BC4) recorded by the falsification gate. This file is the one-page disposition;
the committed plan is the order, and the dialogue ledgers are the provenance.

---

## 1. Verdict

**`accept_with_findings`** — cleared by operator override, BC1–BC4 binding.

**One-line reason:** the RFC's lease design survived falsification at the database layer (claim/renew/release,
single Postgres clock, `lease_id` fencing all sound); the one material gap — a lost lease mid-shard could leave the
original `di --json` child physically using the GPU while a second consumer claims the freed slot — is a **well-scoped,
dischargeable build constraint (BC1)**, not an undischargeable design defect, so the honest disposition is
`accept_with_findings` and the plan proceeds to build under binding constraints.

### Verdict chain (how the gate actually resolved)

| Step | Author | Recorded verdict | Substance |
|---|---|---|---|
| Cycle 1 ledger | adjudicator-claude-opus-4.8-001 | `needs_revision` | Falsifier 1 landed an **unrebutted** challenge on the RFC's primary falsifiable gate (physical exclusivity); Falsifier 2 landed an **unrebutted** backward-compat challenge. Recorded **BC1 (critical, gate)** + **BC2–BC4 (residual)**. |
| Cycle 2 ledger | adjudicator-claude-opus-4.8-002 | `needs_revision` (re-confirmed) | Same four landed constraints. The workflow's single revision iteration routed to `falsifier_1` (re-challenge) rather than back to the `holder` (revise), so the plan could not be repaired in-cycle and the cycle budget exhausted — a **template routing limitation, not a design rejection**. |
| Operator override | [`OPERATOR_DECISION_BC1_override.md`](./OPERATOR_DECISION_BC1_override.md) (`rfc-0001-design-override-bc1`) | `accepted_with_follow_up` → **`accept_with_findings`** | Superseded the exhausted `needs_revision`. BC1 is a dischargeable BUILD constraint (the holder itself named the `Popen` + per-shard lease-monitor fix), not a design defect; the gate clears with BC1–BC4 carried verbatim into the committed plan. |

The DB-layer spine that **survived falsification** (keep through the build, do not re-open): the lease lifecycle SQL
(claim/renew/release/expire on a single Postgres `now()` clock with `lease_id` fencing); the additive expand/contract
migration 006; the DB→readers→writers slice ordering with the hermetic-default + env-guarded real-Postgres test split;
and the `di --json` subprocess boundary (leases stay in Python around the shell-out).

---

## 2. Falsifier challenges that landed → binding constraints

Two falsifiers ran (re-spawned each cycle): `falsifier_1` = openai-codex-gpt-5.5, `falsifier_2` = antigravity-gemini.
Five challenges were adjudicated; four landed and became BC1–BC4, one was rejected.

| Source | Challenge | Correspondence | Became | Severity |
|---|---|---|---|---|
| F1 (codex) | C7 — renewal is **not** "off the correctness path": a central renewer + an unchanged blocking `subprocess.run` has no in-flight cancellation, so a lease lost mid-shard lets Postgres re-issue the capacity-1 slot while the original `di --json` child keeps using the GPU until `SHARD_TIMEOUT` (~1200s) — a physical double-use the hermetic fake-`shard_fn` test cannot observe. | **landed, unrebutted** (holder's C7 concedes it as the refutation condition) | **BC1** (`f_inflight_abort`) — **critical, gate** | critical |
| F2 (gemini) #2 | C1 — Slice B drops `free_slots` from `pick_slot` output while the heartbeat still writes it and the rollout upgrades `pick_slot` before `di_fleet`, so an un-upgraded reader hitting `result["free_slots"]` `KeyError`s mid-rollout. | **landed, unrebutted** | **BC2** (`f_pick_backcompat`) | medium |
| F2 (gemini) #4 | C3/C5 — `hashtext(job ‖ node ‖ slot_id)` propagates SQL `NULL` when `job` is NULL, silently disabling herd dispersal. Holder's Python `job=''` default covers the no-arg path (rebutted), leaving an SQL-level hardening residual. | landed, **rebutted** | **BC3** (`f_jitter_null`) — residual | low |
| F2 (gemini) #1 | C2/C4 — `failover_transfer` redundant-or-leaks. Rebutted for the survivor path (atomic release+claim serves herd-avoidance; survivor-path expiry is the designed deadman); genuine residual is the **no-survivor branch** holding a known-dead lease up to the TTL. | landed, **rebutted** | **BC4** (`f_failover_nosurvivor`) — residual | low |
| F2 (gemini) #3 | C1/C7 — `capacity` column is write-only / drifts from `free_slots` / YAGNI. | **not material** (v1 is capacity-1 ⇒ `capacity=free_slots=1`, no drift; `capacity` is the expand-half of the RFC-mandated rename) | **rejected** | — |

**How they became binding:** the cycle-1 ledger recorded each landed challenge as a machine-readable `constraints[]`
entry keyed to its `source_finding`, re-confirmed in cycle 2. The operator override then bound all four verbatim
("not weakened or dropped"), and the committer **folded BC1–BC4 into `COMMITTED_PLAN.md`** — BC1 into Slice D, BC2+BC3
into Slice B, BC4 into Slice D's failover path — each with a named falsifying test in the gate→test map.

---

## 3. Committed build plan — what the build run must execute

> **Pointer:** [`striatum/campaign/rfc-0001/design/COMMITTED_PLAN.md`](./COMMITTED_PLAN.md)
> (`artifact_kind: synthesis`, committer-claude-opus-4.8-001) — the single source of truth for the build run.

It is the holder's leading build plan amended with every binding constraint, decomposed into five ordered,
independently-committable slices (each lands green on hermetic `python3 -m pytest tests/ -q`):

- **Slice A** — migration `006_exclusive_slot_leases.sql`: additive expand (`ADD COLUMN capacity`, nullable `lease_id` /
  `lease_holder` / `lease_expires`, backfill, new partial pick index). `free_slots` and `gpu_slots_claim_idx` untouched; fully reversible.
- **Slice B** — `pick_slot.py` learns the lease-free predicate + NULL-safe stable jitter. **Folds BC2** (keep/alias `free_slots` in output) **and BC3** (`COALESCE(job,'')` jitter).
- **Slice C** — `leases.py`: claim / renew / release / `failover_transfer` over an injected `conn`; all time predicates are Postgres `now()`, no Python clock.
- **Slice D** — `di_fleet.py` claims/renews/releases around each shard. **Folds BC1** (`subprocess.Popen` + per-shard lease monitor terminates the `di --json` child on lease loss before any second claim) **and BC4** (no-survivor failover explicitly releases the dead lease).
- **Slice E** — "no consumer wall-clock" source-inspection test + deploy-ordering docs.

**Definition of done** is enumerated in COMMITTED_PLAN §8; the gate→test map is §5.

---

## 4. Residual follow-up & risk for the operator to watch during the build

1. **BC1 is the gate the verifier blocks on (`final_review_required: true`).** The build is **not accepted** until the
   independent verifier confirms `test_di_fleet.py::test_lease_loss_terminates_child_before_second_claim` — a
   **no-live-infra** test that a long-running fake child is terminated before any second claim. **The DB-only
   two-transaction concurrency test is necessary but NOT sufficient** for the RFC's exactly-one-holder-at-any-instant
   invariant. Watch that the build does not substitute the DB-only test for the physical-layer abort test.

2. **Preserve the `di --json` subprocess boundary.** BC1's fix must operate on the process **handle**
   (`Popen.terminate()/kill()`); it must **not** import the Node engine (`~/git/divergent-ideation`). The renewer keeps
   leases fresh but is **not** the exclusivity guarantee — the per-shard `Popen` + monitor is.

3. **Backward-compat window (BC2).** The readers-before-writers rollout opens a mixed-version window; `pick_slot` must
   keep emitting `free_slots` (aliased from `capacity`) until the **out-of-scope future contract migration (007)** retires it.
   Do not let the build drop the `free_slots` output key or touch the running heartbeat writer.

4. **Live-infra safety boundary.** The build writes **only** migration SQL, Python, and tests and runs **hermetic**
   pytest. It must NOT apply migration 006 to the live `gpu_fleet` DB, restart/perturb the `gpu-fleet-heartbeat`
   service, or touch peecee's shared GPU / `marker`. DB-backed tests are guarded behind `GPU_FLEET_TEST_DB`
   (default OFF, ephemeral throwaway cluster only — never `dbname=gpu_fleet`).

5. **Deploy + contract-migration sequencing is an operator step, not part of this build.** After the build integrates,
   the operator applies 006 → deploys readers (`pick_slot.py`) → deploys writers (`di_fleet.py`, re-deploy `bin/di-fleet`).
   The later contract migration (007) drops `free_slots` only after the heartbeat stops writing it. No heartbeat change in v1.

6. **Process note (not a design risk).** The `needs_revision` exhaustion was a **workflow routing limitation** (the single
   revision iteration re-challenged instead of returning to the holder), resolved by the operator override — the plan was
   never design-rejected. No action required of the build beyond discharging BC1–BC4.
