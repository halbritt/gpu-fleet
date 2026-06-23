---
schema_version: "striatum.synthesis.v1"
artifact_kind: "synthesis"
author: adjudicator-claude-opus-4.8-008
workflow: "rfc-0002-design"
run_id: "run_aa1f69f24463027c2466994e9f655b08"
cycle: 3
title: "RFC 0002 — Zero-touch node lifecycle: design-gate summary"
summary: "Design gate CLEARED accept_with_findings after a 3-cycle falsification. The build run executes COMMITTED_PLAN.md (committer-001, art_63f5b53) — migration 009 rolled out across five writer-before-reader slices. Cycles 1-2 raised seven defects (BC1-BC7); the cycle-3 holder revision discharged all seven as real SQL/control-flow/tests (falsifier_2: 'No Remaining Falsifying Gaps'; falsifier_1 dropped every one), so the cycle-2 terminal-reject trigger did not fire. Cycle 3 surfaced one new finding, BC8 (peecee pull-only liveness vs an SSH-nvidia-smi retirement step): its false plan text is already fixed in the committed plan via option (a); its verify test is the build's to write. Final-review-gating: BC1, BC2, BC6, BC7, BC8."
inputs: []
---

# GATE SUMMARY — RFC 0002: Zero-touch node lifecycle (design gate)

author: adjudicator-claude-opus-4.8-008

This is the one page the **build run** should read before opening the contract. The
falsification design gate for **RFC 0002 — Zero-touch node lifecycle**
(`docs/rfc/0002-zero-touch-node-lifecycle.md`, settled) ran the holder → two
model-diverse falsifiers (codex, gemini) → adjudicator loop for **three cycles** and is now
**closed and cleared**. Below: the verdict and why, the contract to execute, the objections
that became binding, and the risks to watch through the build.

## Verdict

| Field | Value |
|---|---|
| **Verdict** | `accept_with_findings` — a **clearing** verdict (the commit phase published the plan) |
| **Clearing ledger** | `striatum/campaign/rfc-0002/design/dialogue/adjudicator/COLLABORATION_LEDGER_cycle_3.md` — `adjudicator-claude-opus-4.8-003`, `art_ef8ee7f10e606252c52dfbb3d29ed1f8` |
| **Cycles** | 3. The `max_iterations = 2` revision budget was exhausted at cycle 2; cycle 3 was the **terminal re-falsification** of the holder's revised plan |
| **Posture path** | cycle 1 `needs_revision` → cycle 2 `needs_revision` (budget spent) → cycle 3 `accept_with_findings` |

**One-line reason.** The holder's cycle-3 revision *applies* — as concrete SQL,
control-flow, and tests, not prose — **all seven** cycle-2 constraints; `falsifier_2`
independently certified them (*"No Remaining Falsifying Gaps … sound and ready to
proceed"*) and `falsifier_1` dropped every one. So the cycle-2 binding trigger — *terminal
`reject` iff a blocker among BC1/BC2/BC6/BC7 still lands* — **did not fire**, and the
build-correctness spine **survived falsification**. The single objection to survive cycle 3
(`falsifier_1`'s new **BC8**) lands on a false narrative sentence and a harmful operator
step — **not** on any in-build SQL — so it rides forward as a binding build/verify
constraint, not an undischargeable defect.

**Why not the alternatives.** `reject` was untruthful: the design *does* satisfy its own
falsifiable gate and the terminal-reject trigger was precisely not met. `needs_revision` was
wrong: substance had converged 7/7, the revision budget was already spent, and the lone
residual (BC8) is bounded and build-dischargeable — exactly the shape of a binding finding,
not a re-gate.

## The committed build plan the build run MUST execute

➡ **`striatum/campaign/rfc-0002/design/COMMITTED_PLAN.md`** —
`committer-claude-opus-4.8-001`, `art_63f5b5367df08777cbeddd536f3c1b85`.

It is the holder's cycle-3 plan (`holder-claude-opus-4.8-003`, `art_6d3d474a`) with **every
binding constraint folded in** — the exact, self-contained contract. Spine: **five ordered,
independently-committable slices**, committed *and* deployed **writer-before-reader** (the
load-bearing ordering claim **C5**, deliberately the *opposite* of RFC-0003's reader-first
order, because here the consumer slice *filters* on `status` and would strand live nodes if
it led):

- **Slice 0 — `migrations/009_zero_touch_lifecycle.sql`** (purely additive, reversible):
  `gpu_slots` gains `status` / `probe_streak` / `gpu_uuid` / `boot_epoch`; `fleet_nodes`
  gains `driven_by` / `lease_until`; new single-row `fleet_meta` table (column **`holder`**);
  new `routable_slots` view *alongside* (not replacing) `live_slots`. Backfill every existing
  row to `status='routable'` so the migration instant strands nothing.
- **Slice 1 — heartbeat writer:** quarantine→graduate (`GRADUATION_STREAK = 3`), captured
  `gpu_uuid`, the **strictly-monotonic-per-write** `boot_epoch` ratchet (strict `>`), and the
  **stale-only PRUNE** fix so a self-pushed node with no `fleet_nodes` row is not deleted.
- **Slice 2 — global puller-lease** (`fleet_meta` CAS, `PULLER_LEASE_TTL = 15 s`): makes the
  driver peer-runnable and kills the proximal-SSH-driver single point of failure.
- **Slice 3 — per-node driver-lease arbitration** (`NODE_LEASE_TTL = 30 s`, **non-gating**
  CAS): one writer between push and pull; push is opt-in for trusted Linux nodes only.
- **Slice 4 — consumers gate routing on `status='routable'`** (`pick_slot.py` +
  `di_fleet.py`, one predicate each): the slice that *activates* quarantine, so it **deploys
  last**.

**Slice 5 (per-node RLS) is deferred** — v1 has no untrusted push credential to bound, and
enabling RLS early risks fencing the puller's own writes. The build is **inert wrt live
infra** (§4): it writes `migrations/009`, edits four modules + tests, and runs the hermetic
suite — it does **not** touch the live `gpu_fleet` DB, the running `gpu-fleet-heartbeat`
service, or peecee. The `di --json` subprocess boundary is preserved (`bin/di-fleet`
unedited).

## Falsifier challenges that landed → binding constraints

Cycles 1–2 surfaced seven defects (**BC1–BC7**); cycle 3 verified all seven **discharged in
the design** and converts them into must-stay-green **verify tests** the build inherits.
Cycle 3 added one new landed objection, **BC8** — the only constraint still *open* at
clearance (plan-text half repaired in the committed plan; verify test is the build's to
write).

| BC | Sev | What the falsifier landed | Discharge / how it binds | Build verify test | Final review |
|----|-----|---------------------------|--------------------------|-------------------|--------------|
| **BC1** | high | push path CAS-gated its UPSERT → a node with no `fleet_nodes` row never wrote its first `gpu_slots` row (zero-touch deadlock) | arbitration **model (c)**: per-node lease CAS made **non-gating**; UPSERT runs **unconditionally** | `test_self_push_no_fleet_node_registers_and_graduates` (composed Slice-1+3) | **required** |
| **BC2** | high | a NULL (pull) write wiped a push-stamped `boot_epoch` | `boot_epoch = COALESCE(EXCLUDED.boot_epoch, gpu_slots.boot_epoch)` | `test_boot_epoch_survives_null_pull_write` | **required** |
| **BC6** | high | an equal-epoch replay overwrote live state (the `>=` hole) | `boot_epoch` made **strictly monotonic per write** → ratchet predicate is a **strict `>`** | `test_equal_epoch_replay_is_noop` + `test_ratchet_predicate_is_strict_gt` | **required** |
| **BC7** | high | a hot-swapped GPU inherited the prior trust streak | `probe_streak` reset + `status='unverified'` on a **non-NULL** `gpu_uuid` mismatch | `test_uuid_mismatch_resets_streak_and_demotes` + `test_hot_swap_demotes_to_unverified` | **required** |
| **BC3** | med | the puller-lease TTL could exceed the 45 s age-out window | `PULLER_LEASE_TTL = 15 s` (`< 45 s`) | `test_puller_failover_no_ageout` | carry |
| **BC4** | med | a puller-host wall-clock decided the per-node skip | freshness pushed **server-side** into the `FETCH` (`now() >= lease_until`) | `test_fetch_freshness_uses_db_now_no_client_clock` | carry |
| **BC5** | low | the `fleet_meta` column name diverged (`puller` vs `holder`) | one name **`holder`** across DDL / CAS / tests, run on the real `009` DDL | tests A/B/G/H | carry |
| **BC8** | med | **new (cycle 3, `falsifier_1`/codex-003)**: the plan's claim *"peecee's liveness already comes from its HTTP endpoint"* is **false** — `ollama_ondemand_liveness` fails closed on a missing `gpu_stats` (`heartbeat.py:168`, before `/api/ps` and the VRAM-headroom branch), so retiring peecee's SSH `nvidia-smi` leg would **de-list** peecee (`alive=False`, never graduates) | committed plan adopts **option (a)**: do **not** retire the SSH leg in v1; the §2-step-2 de-listing operator step is **deleted** and §4/§5/Q5 corrected | `test_load_aware_liveness.py` + `test_pull_only_node_has_no_db_path` + plan-text inspection | **required** |

**Gating.** `final_review_required: true` for **BC1, BC2, BC6, BC7, BC8**. BC3, BC4, BC5 are
must-stay-green carries but not final-review-gating.

**Why BC8 landed yet did not block the gate.** The build's *code* deliverable (migration
`009` + the writer/consumer edits + the seven fixes) does **not** remove peecee's `gpu_cmd`
and does **not** touch `probe_node` / `gpu_stats` / `ollama_ondemand_liveness`; §4 keeps the
build inert wrt live infra, so as code it leaves peecee monitored exactly as today. The
defect lived in a **false narrative sentence** (§5) and a **harmful operator apply-order
step** (§2 step 2), and the holder's own hedge — *"the in-build ratchet is correct without
the SSH step; not load-bearing for any C-claim"* — is **true and survives**. The committed
plan already repaired the plan-text half (option a); the remaining verification is the
build's to write. Either resolution path (keep SSH-via-pull liveness, or build+test a real
HTTP-only peecee path per option (b), Pillar 6 / Q5) leaves BC2/BC6 untouched.

## Residual follow-up / risk the operator must watch during the build

1. **BC8 is the only live finding.** Plan-text half discharged (option a); **verify test
   still open.** Keep peecee monitored via its **existing SSH-via-pull liveness**, de-listed
   when the marker owns the card, and ship **no** false "HTTP-only liveness" claim and **no**
   de-listing SSH-retirement step. **Do not retire peecee's cross-host SSH `nvidia-smi`
   `gpu_cmd` in v1.** (The full HTTP-only peecee path — option (b), which finally retires the
   cross-host SSH fan-out — is a documented, bounded follow-up, out of v1 scope.)
2. **Never weaken the ratchet predicate to `>=` (BC6).** The strict `>` is correct *only*
   because `boot_epoch` is strictly-monotonic-per-write (`next_boot_epoch`). Reverting either
   half re-opens the equal-epoch replay hole.
3. **Deploy order is load-bearing (C5):** DB → writer → puller → consumers. **Slice 4 deploys
   last** — before Slice 1 has graduated live nodes, the `status='routable'` gate would
   strand them.
4. **The migration number is `009`, not the RFC body's stale "006"** (006/007/008 are the
   peecee dense flip / RFC-0001 leases / RFC-0003 epoch) — claim C1. Never reuse 006/007/008.
5. **`boot_epoch` ⟂ `epoch` (C7):** the RFC-0003 `epoch` CASE stays byte-unchanged; never
   alias the two columns.
6. **Hermetic suite stays green (C11):** every PG-backed test is guarded exactly like
   `test_leases_pg.py` / `test_epoch_pg.py`, runs only against an ephemeral
   `GPU_FLEET_TEST_DB` (dbname must contain `test`; never the live `gpu_fleet`), and applies
   the real `migrations/001,007,008,009` against the real schema (which also proves `009`
   applies cleanly). The "26 tests" figure in the RFC/prompt is **stale** — preserve the
   *invariant* (hermetic default green, DB tests guarded), not a count.
7. **Operator steps come AFTER integration** (none are in the build's diff): apply `009`
   (`stop→migrate→start`, or live since it is additive), redeploy the writer then the consumer
   checkouts, deploy a **second** puller (the actual SPOF-kill), and optionally a **push**
   sidecar (`heartbeat.py --node self`) on the trusted quad-server. There is **no**
   SSH-retirement step in v1.
8. **Out of v1 scope, documented:** the option-(b) HTTP-only peecee liveness path (BC8 / Q5);
   per-node RLS (Slice 5 / Q4); an explicit endpoint-asserted VRAM trust tier (Q5); a deeper
   periodic canary beyond the 1-token probe (Q6); the `pg_cron` host-free driver mode (Q3).
9. **Do not re-open the settled RFC design:** pull-first peer-runnable driver; push opt-in for
   trusted Linux nodes only; registration = first heartbeat; measured-not-declared
   quarantine→graduate; `boot_epoch` separate from `epoch`.

---

**Handoff.** Design gate closed `accept_with_findings`. The build run executes
`COMMITTED_PLAN.md` and must, at final review, keep the BC1/BC2/BC6/BC7 discharge tests green
(strict `>` intact) and **discharge BC8** (peecee stays pull-monitored and de-lists when the
marker owns the card; no false liveness claim, no de-listing step). BC3/BC4/BC5 ride forward
as must-stay-green carries.
