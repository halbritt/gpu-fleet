---
schema_version: "striatum.collaboration_ledger.v1.1"
artifact_kind: "collaboration_ledger"
shape: "falsification_gate"
author: adjudicator-claude-opus-4.8-001
workflow: "rfc-0001-design"
run_id: "run_74040bd3a38125e720db1ad27034d0bf"
cycle: 1
topic: "RFC 0001 — Exclusive slot leases: gate the falsifiable build plan"
participants: ["holder", "falsifier_1", "falsifier_2", "adjudicator"]
verdict: "needs_revision"
rationale: "Falsifier 1 lands a material, unrebutted challenge on the RFC's primary falsifiable gate. The plan's central daemon renewer plus an unchanged blocking subprocess.run in run_shard has no in-flight cancellation, so a lease lost mid-shard (renewer death, or a legitimate renew failure from heartbeat staleness or a zombie re-claim) lets Postgres expire and re-issue the capacity-1 slot to a second consumer while the original di --json child keeps using the physical GPU until SHARD_TIMEOUT (default 1200s) — the exact two-consumers-on-one-card collision RFC 0001 exists to eliminate. C7's 'off the correctness path' claim is therefore false as specified, and the proposed fake-shard_fn hermetic test cannot observe it, so the RFC's exactly-one-holder-at-any-instant gate has no test at the physical layer. The holder did not rebut this (C7 concedes it as the refutation condition). A second landed, unrebutted backward-compat break is the staged readers-before-writers rollout dropping free_slots from pick_slot output while an un-upgraded reader may still read it. Two minor objections landed but were rebutted (the NULL-jitter SQL — the holder's job='' default covers the stated no-arg path; the failover redundant-or-leak dilemma — the atomic release+claim serves the RFC's herd-avoidance and the survivor-path expiry is the designed deadman), and the capacity-drift/YAGNI objection does not land (v1 is capacity-1 so capacity=free_slots=1 with no drift, and capacity is the expand-half of the RFC's mandated rename). Because a material challenge landed unrebutted on the core invariant the gate cannot clear; the defect is repairable in one cycle, so the verdict is needs_revision with BC1 as the blocking repair (Popen plus a per-shard lease monitor that terminates the child on lease loss, plus a no-live-infra falsifying test) and BC2-BC4 as the accompanying repairs."
entries:
  - kind: claim
    by: holder
    refs: ["dialogue:1"]
    text: "Holder build plan: translate RFC 0001 into ordered, independently-committable slices (A migration 006 additive expand/contract; B pick_slot lease-free predicate plus stable jitter; C leases.py lifecycle; D di_fleet claim/renew/release plus atomic failover_transfer; E no-consumer-clock inspection test), with an additive and reversible 006, a falsifiable-gate to test map, and live-infra safety; claims C1-C7 are offered as the falsifiable surface."
  - kind: challenge
    by: falsifier_1
    refs: ["dialogue:2"]
    correspondence: landed_unrebutted
    text: "C7 challenged: the renewal design is not off the correctness path. A central renewer plus run_shard left as a blocking subprocess.run has no in-flight cancellation, so when a lease is lost mid-shard Postgres re-issues the capacity-1 slot to a second consumer while the original di --json child keeps using the GPU until SHARD_TIMEOUT (default 1200s) — a physical double-use the fake-shard_fn test cannot catch. Requires an explicit Popen plus lease-monitor abort and a falsifying test."
  - kind: challenge
    by: falsifier_2
    refs: ["dialogue:3"]
    correspondence: landed_and_rebutted
    text: "C2/C4 challenged: failover_transfer is redundant if the worker releases the dead lease on error, or leaks it (up to the 45s TTL) if no survivor exists. Rebutted: the plan releases the dead lease inside the transfer transaction (so Scenario A does not apply) and the atomic release+claim exists for the RFC's herd-avoidance (freed capacity never hits the open pool), while the survivor-path bounded expiry is the RFC's designed deadman — but the no-survivor branch needs an explicit immediate release (residual BC4)."
  - kind: challenge
    by: falsifier_2
    refs: ["dialogue:3"]
    correspondence: landed_unrebutted
    text: "C1 challenged: Slice B drops free_slots from pick_slot output while the heartbeat still writes it and the plan's own rollout upgrades pick_slot before di_fleet, so an un-upgraded reader hitting result['free_slots'] KeyErrors mid-rollout. Not rebutted by the plan (C1 covers only the DB migration). Fix: keep or alias free_slots in the output until the contract migration (BC2)."
  - kind: challenge
    by: falsifier_2
    refs: ["dialogue:3"]
    correspondence: not_material
    text: "C1/C7 challenged: the capacity column is write-only, drifts from free_slots, and is YAGNI in v1. Does not land: every v1 slot is capacity-1 so capacity=free_slots=1 with no drift; the drift scenario needs a capacity>1 slot that is explicitly out of scope; capacity is the expand-half of the RFC-mandated free_slots to capacity rename; Boundaries section 5 already states capacity is immutable and why the heartbeat is untouched."
  - kind: challenge
    by: falsifier_2
    refs: ["dialogue:3"]
    correspondence: landed_and_rebutted
    text: "C3/C5 challenged: hashtext(job || node || slot_id) propagates SQL NULL when job is NULL, silently disabling herd dispersal. Rebutted for the stated no-arg path by the plan's Python job='' default; residual: harden the SQL with COALESCE(job,'') so an explicit job=None also degrades safely (BC3)."
  - kind: rebuttal
    by: holder
    refs: ["dialogue:1"]
    text: "Holder in-plan pre-emptive defenses: backward-compat via additive expand/contract instead of an in-place RENAME (C1); capacity immutable and v1 capacity-1 with the heartbeat intentionally untouched (Boundaries section 5); stable jitter with a job='' default; failover release performed inside the atomic transfer for herd-avoidance. The holder did NOT rebut the Falsifier-1 in-flight-abort gap (C7 explicitly concedes it as the refutation condition) nor the pick_slot return-contract backward-compat break."
findings:
  - id: f_inflight_abort
    severity: critical
    posture: "test-gate-adequacy / physical-exclusivity"
    status: open
    challenge: "Central renewer plus blocking subprocess.run permits a post-expiry physical GPU double-use; the RFC's exactly-one-holder gate has no physical-layer test and C7's off-the-correctness-path claim is false as specified."
    affected_invariants: ["exactly_one_consumer_per_capacity_1_slot_at_any_instant"]
    requires_convener_rebuttal: true
    source_refs: ["dialogue:1", "dialogue:2"]
  - id: f_pick_backcompat
    severity: medium
    posture: "migration-backward-compat"
    status: open
    challenge: "Dropping free_slots from pick_slot output breaks un-upgraded readers during the plan's readers-before-writers rollout window."
    source_refs: ["dialogue:1", "dialogue:3"]
  - id: f_jitter_null
    severity: low
    posture: "correctness-of-stable-jitter"
    status: answered
    challenge: "Jitter SQL propagates NULL for job=None / SQL NULL; the holder's job='' default covers the no-arg path, leaving an SQL-level hardening residual."
    source_refs: ["dialogue:1", "dialogue:3"]
  - id: f_failover_nosurvivor
    severity: low
    posture: "failover-lifecycle-clarity"
    status: answered
    challenge: "failover_transfer no-survivor branch holds a known-dead lease until the TTL; the redundant-or-leak dilemma is otherwise rebutted (atomicity serves herd-avoidance; survivor-path expiry is the designed deadman)."
    source_refs: ["dialogue:1", "dialogue:3"]
  - id: f_capacity_drift
    severity: low
    posture: "slice-decomposition / YAGNI"
    status: rejected
    challenge: "Capacity column drift / unused — rejected: v1 capacity-1 means capacity=free_slots=1 with no drift, and capacity is the expand-half of the RFC-mandated rename; Boundaries section 5 explains the untouched heartbeat."
    source_refs: ["dialogue:1", "dialogue:3"]
constraints:
  - id: BC1
    posture: "physical-exclusivity-gate"
    severity: critical
    kind: gate
    binding: true
    source_finding: f_inflight_abort
    source_refs: ["dialogue:2"]
    text: "Slice D MUST replace the blocking subprocess.run with subprocess.Popen plus a per-shard lease monitor (or move renew+cancel into the worker that owns the child handle) so a lost lease immediately terminates the di --json child before any second consumer can use the GPU. C7 MUST be restated: as specified (central renewer plus blocking subprocess.run), renewal IS on the correctness path. Add a no-live-infra falsifying test: under a disposable lease, a long-running fake child is terminated before any second claim can run concurrently. The DB-only two-transaction concurrency test is necessary but NOT sufficient for the RFC's exactly-one-holder-at-any-instant gate. The di --json shell-out boundary is preserved (operate on the process handle; do not import the engine)."
    verification:
      gate: "no-live-infra in-flight-abort test: lease loss terminates the running child before any second claim; physical double-use is observably prevented"
      expected_stage: "design_revision_then_build_verify"
    final_review_required: true
  - id: BC2
    posture: "migration-backward-compat"
    severity: medium
    kind: policy
    binding: false
    source_refs: ["dialogue:3"]
    text: "pick_slot.py MUST keep surfacing free_slots in its returned dict / --json output (e.g. alias capacity to free_slots) until the out-of-scope contract migration retires it, so the readers-before-writers rollout never KeyErrors an un-upgraded reader; add a regression test pinning the free_slots key."
  - id: BC3
    posture: "stable-jitter-correctness"
    severity: low
    kind: policy
    binding: false
    source_refs: ["dialogue:3"]
    text: "Make the jitter ORDER BY NULL-safe at the SQL layer (hashtext(COALESCE(job,'') || node || slot_id::text)) so an explicit job=None degrades safely instead of collapsing every row's hash to NULL; test the tie-breaker stays active for job='' and job=None."
  - id: BC4
    posture: "failover-lifecycle"
    severity: low
    kind: policy
    binding: false
    source_refs: ["dialogue:3"]
    text: "Make the no-survivor failover branch explicitly release the dead shard's lease so the slot frees immediately rather than waiting up to the TTL; keep the atomic release+claim of the survivor path (it serves the RFC's herd-avoidance); test that a no-survivor failover frees the slot without waiting for the TTL."
branches:
  test_gate_adequacy_physical_exclusivity: "blocked"
  migration_backward_compat: "blocked"
  stable_jitter_correctness: "cleared_with_constraints"
  failover_lifecycle: "cleared_with_constraints"
  slice_decomposition_reversibility: "cleared"
---

# COLLABORATION LEDGER — RFC 0001 Exclusive slot leases (design gate, cycle 1)

author: adjudicator-claude-opus-4.8-001

- **RFC:** `docs/rfc/0001-exclusive-slot-leases.md`
- **Phase:** dialogue → synthesis (`adjudicate`)
- **Build plan under gate:** `dialogue/holder/BUILD_PLAN.md` (holder-claude-opus-4.8-001) — `dialogue:1`
- **Challenges read:** `dialogue/falsifier_1/FALSIFIER.md` (falsifier-openai-codex-gpt-5.5-001) — `dialogue:2`;
  `dialogue/falsifier_2/FALSIFIER.md` (falsifier-antigravity-gemini-001) — `dialogue:3`
- **Evidence basis:** the curated dialogue trajectory + the RFC only (no raw provider logs,
  no private diagnostics).

---

## VERDICT — `needs_revision`

**One-line reason:** Falsifier 1 lands a **material, unrebutted** challenge on the RFC's
primary falsifiable gate — the plan's central renewer + unchanged blocking `subprocess.run`
permits a **physical GPU double-use after a lease is lost mid-shard**, the exact collision
RFC 0001 exists to eliminate, and the plan's tests cannot observe it. A landed challenge that
the holder did not rebut cannot clear the gate (RFC 0094 §5 Check-B). The defect is repairable
in one cycle, so the plan returns for revision with **BC1 as the blocking repair** and
**BC2–BC4** as accompanying repairs.

This is **not** a clearing verdict: the commit phase does not run. Per the workflow's cycle
(`adjudicate → falsifier_1`, `max_iterations: 1`), the holder revises the build plan to
discharge BC1–BC4 and the plan is re-challenged.

---

## What survived falsification (keep through the revision)

No challenge refuted these; they are the sound spine of the revised plan:

- **DB-side lease lifecycle** — claim/renew/release/expire SQL, single Postgres `now()` clock,
  `lease_id` fencing. Exclusivity, deadman expiry, and zombie-fencing are sound **at the
  database layer** (C2/C3 stand there). *The gap is the bridge from DB-lease-loss to
  stop-touching-the-physical-GPU — see BC1.*
- **Additive expand/contract migration 006** — add `capacity` + nullable lease columns,
  backfill, new partial index; `free_slots`/`gpu_slots_claim_idx` untouched; reversible by
  dropping the four added columns. Falsifier 2's capacity-drift attack on this **did not land**
  (Disposition #5).
- **Slice ordering DB → readers → writers**, the hermetic-default + env-guarded real-Postgres
  test split, and the live-infra safety boundary (no live `gpu_fleet` DB, no heartbeat restart,
  no peecee/`marker` touch) — unchallenged.
- **`di --json` subprocess boundary** — leases stay in Python around the shell-out. BC1's fix
  operates on the process *handle*, not by importing the engine, so the boundary is preserved.

---

## Per-challenge adjudication

| Source | Claim | Correspondence | Becomes |
|--------|-------|----------------|---------|
| F1 (codex) | C7 — renewal "off the correctness path" | **landed_unrebutted** | **BC1** (blocking) |
| F2 (gemini) #2 | C1 — `pick_slot` drops `free_slots` → breaks un-upgraded readers | **landed_unrebutted** | **BC2** |
| F2 (gemini) #4 | C3/C5 — jitter SQL NULL-propagation | landed_and_rebutted | **BC3** (residual) |
| F2 (gemini) #1 | C2/C4 — `failover_transfer` redundant-or-leaks | landed_and_rebutted | **BC4** (residual) |
| F2 (gemini) #3 | C1/C7 — `capacity` column drift / YAGNI | not_material | rejected |

### #1 — Falsifier 1: in-flight lease-loss abort (LANDS, UNREBUTTED — the blocker)

Hits the verdict-basis bullseye: *a falsifiable-gate item with no real test.* The RFC's
primary gate is "two concurrent consumers on a capacity-1 slot → exactly one holds it **at any
instant**." The plan's Slice D uses a central daemon renewer and leaves `run_shard` as a
blocking `subprocess.run` with no cancellation. If the renewer stalls / loses its DB connection
/ dies — **or** a renew legitimately fails (node ages out of heartbeat freshness, or a zombie
re-claim wins) — Postgres expires the lease at TTL, a second consumer correctly claims the
slot, yet the original `di --json` child keeps decoding on that GPU until it exits or hits
`SHARD_TIMEOUT` (≈1200s). The DB shows one lease; the **physical card has two users** — the
collision RFC 0001 exists to prevent. The holder's own C7 names this as its refutation
condition ("forcing the per-shard `Popen`+poll alternative") but **did not resolve it**, and
the proposed hermetic test (a fake `shard_fn`) provably cannot catch it (a fake is not an
abortable real child). **Unrebutted → cannot clear.** → **BC1.**

*Not `reject`:* dischargeable — the repair is the `Popen`+monitor alternative the holder
already named, plus its falsifying test. One cycle suffices.

### #2 — Falsifier 2 #2: `pick_slot` return-contract backward-compat (LANDS, UNREBUTTED)

Backward-compat is a hard task requirement, and the plan's §2 upgrades `pick_slot.py` (Slice B)
**before** `di_fleet.py` (Slice D), opening a mixed-version window. Slice B drops `free_slots`
from `SELECT`/`ORDER BY`; any un-upgraded reader (old `di_fleet`, a fleet tool, or
`pick_slot.py --json`) that reads `result["free_slots"]` then `KeyError`s mid-rollout. The
plan's C1 covers only the DB migration, so this is unrebutted. Cheap, clearly-correct fix. →
**BC2.**

### #3 — Falsifier 2 #4: NULL-propagation in jitter SQL (landed, REBUTTED — residual)

The plan defends the documented no-arg path via the Python `job=''` default, so C3/C5 holds for
intended usage — the falsifier's headline case (omitted `job`) is rebutted. Residual: an
explicit `job=None`/SQL `NULL` still silently collapses every row's hash to `NULL` and disables
dispersal with no error. Jitter is a throughput optimization, not correctness, so severity is
low; one `COALESCE` hardens it. → **BC3** (residual hardening).

### #4 — Falsifier 2 #1: `failover_transfer` redundant-or-leaks (landed, REBUTTED — residual)

Scenario A ("worker releases on error ⇒ transfer's release is redundant") is a strawman: the
plan releases the dead lease **inside** `failover_transfer`'s single commit, not separately. And
the atomic release+claim is **not** redundant — its purpose is the RFC's herd-avoidance ("freed
capacity never hits the open pool"). Scenario B's "leak up to 45s" on the survivor-exists path
is simply the RFC's **designed** autonomous-expiry deadman, bounded by TTL. The genuine residual
is the **no-survivor branch**: with roll-back-together semantics, a known-dead shard's slot
stays held up to the full TTL instead of freeing immediately. Correctness-neutral but worth an
explicit release. → **BC4** (residual clarity); the redundant/leak framing is **rejected**.

### #5 — Falsifier 2 #3: `capacity` drift / YAGNI (DOES NOT land)

The drift it describes (`free_slots=2` but `capacity=1`) can only arise for a `capacity > 1`
slot, and **none exists in v1** (capacity-1 by explicit scope). For every v1 slot
`capacity = free_slots = 1` — no drift. `capacity` is the **expand-half of the RFC-mandated
rename** (`free_slots → capacity`, Migration step 1 / Principle 1), executed as expand/contract
so the running heartbeat never breaks; Boundaries §5 already states it is immutable and why the
heartbeat is untouched. "Defer the column" would mean *not* performing the RFC's rename.
*Non-binding note:* add a one-line comment in 006 / `pick_slot.py` that `capacity` is the
expand-half of the rename and is intentionally not dynamically branched on in the capacity-1
pick path, to forestall a future reader mistaking it for a dead/drifting column.

---

## Required repairs (machine-readable in front-matter `constraints[]`)

| ID | Binding | Severity | Repair |
|----|---------|----------|--------|
| **BC1** | **yes (gate)** | critical | Slice D: `Popen` + per-shard lease monitor terminates the `di --json` child on lease loss before any second claim; restate C7 (renewal is on the correctness path as specified); add the no-live-infra falsifying test (long-running fake child killed before a second claim). DB-only concurrency test is necessary but not sufficient. |
| BC2 | recommended | medium | `pick_slot.py` keeps/aliases `free_slots` in its output until the contract migration; regression test pins the key. |
| BC3 | recommended | low | NULL-safe jitter SQL `hashtext(COALESCE(job,'') || node || slot_id::text)`; test active for `job=''` and `job=None`. |
| BC4 | recommended | low | No-survivor failover explicitly releases the dead lease (slot frees immediately, not after TTL); keep the survivor-path atomic transfer; test it. |

---

## Why `needs_revision` (and not the alternatives)

- **Not `accept` / `accept_with_findings`:** a clearing verdict requires every landed challenge
  to have been rebutted in the trajectory (RFC 0094 §5 Check-B). Falsifier 1 landed
  **unrebutted** on the core exactly-one-holder invariant — the holder conceded it rather than
  answering it — so the gate cannot honestly clear. Carrying it as a "the build will fix it"
  finding would wave through a plan whose physical exclusivity is unproven and untested; that is
  exactly what the falsification gate exists to stop.
- **Not `reject`:** the design *can* satisfy its own falsifiable gate. BC1's repair is the
  `Popen`+monitor alternative the holder already named; it is well-scoped and fits one cycle. No
  undischargeable defect.
- **`needs_revision`** uses the workflow's single allowed re-falsification iteration for a
  genuine, material, repairable defect — its intended purpose. An honest needs_revision with a
  truthful ledger is a successful gate outcome.

---

## Handoff to the holder (next cycle)

Revise `dialogue/holder/BUILD_PLAN.md` to discharge **BC1** (the blocker) and **BC2–BC4**:
fold the `Popen` + per-shard lease-monitor abort and its falsifying test into Slice D and the
gate→test map; restate C7; keep/alias `free_slots` in `pick_slot` output (BC2); make the jitter
SQL NULL-safe (BC3); make the no-survivor failover release explicit (BC4). Preserve everything
in "What survived" and do not re-open the RFC's settled design. Falsifier 1 then re-challenges
the revised plan.
