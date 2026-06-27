---
schema_version: "striatum.collaboration_ledger.v1.1"
artifact_kind: "collaboration_ledger"
shape: "falsification_gate"
author: adjudicator-claude-opus-4.8-004
workflow: "rfc-0005-design"
run_id: "run_0e0a6f7601cc744dec24f48b43bea9e1"
cycle: 3
topic: "RFC 0005 — Exporter-fed capacity signal (probe-anchored): third adjudication of the falsifiable build plan; re-derived fresh on the current (still-unrevised) trajectory by a fresh adjudicator session"
participants: ["holder", "falsifier_1", "falsifier_2", "adjudicator"]
verdict: "needs_revision"
rationale: |-
  Third adjudication of an UNREVISED build plan, re-derived fresh on the current trajectory (this is a fresh adjudicator session, ordinal 004; the prior recorded finding the daemon tracks is cycle_2 / attempt 2, verdict needs_revision). I did not default to the prior answer: I re-read every artifact and re-tested each challenge against the plan as it stands. The trajectory is provably unchanged — holder BUILD_PLAN.md is a single commit 5111c9e, falsifier_1 is 1d84e2f, falsifier_2 is 9aba38b; git log shows no second holder commit and no edits to either falsifier file across cycles 1, 2, 3. Because the inputs are byte-identical, the substance of the verdict is necessarily the same, but the derivation and this ledger are my own.

  THE BLOCKER (unchanged on the merits, re-confirmed): Falsifier 1 lands a material, landed_unrebutted challenge on the RFC's central reader-side headroom invariant. Slice 3 writes the headroom SQL (COALESCE(c.effective_free_mib, vram_free_mib) >= min_vram, and the di_fleet claim predicate effective_free >= model_mib + kv_bytes(max_context)) but supplies NO production path for the request side: route_slots() calls pick() with no model / no min_vram; _split_argv() passes --model and the context flags through opaquely; main() / run_leased_shard() / run_failover_shard() pass no model_mib and no max_context; claim() gains only a DEFAULTED optional max_context (model_mib stays 0). With those defaults the production predicate is byte-equivalent to today, so a 32k-context request and a 4k-context request route IDENTICALLY in the only consumer path that matters — the exact behavior the RFC's reader invariant exists to deliver. Two further strikes ride this one: the Slice 3 SQL names kv_bytes(%(max_context)s) but NO slice and NOT Migration 010 create any kv_bytes symbol (the predicate as written cannot run), and §5 asserts the di --json boundary is preserved without ever saying where model_footprint / max_context come from (an ad-hoc fill — Node-engine inspection, querying a running backend, measuring real GPUs — would break that boundary and the live-infra posture). The holder's in-plan defenses (Slice 3 Change B, claim C7) cover only the empty-companion COALESCE fall-through; C7 in fact CONFIRMS the gap by treating the predicate as byte-equivalent-to-today and kv_bytes as defaulting to 0. The challenge is therefore landed_unrebutted.

  WHY THE GATE CANNOT CLEAR: a clearing verdict (accept / accept_with_findings) requires every landed challenge to be rebutted in the trajectory (RFC 0094 §5 Check-B), and that check is enforced MECHANICALLY by the artifact validator — a clearing ledger carrying any landed_unrebutted challenge is refused at publish. So accept / accept_with_findings are off the table on both substance and mechanism.

  WHY NOT reject: reject is reserved for an UNDISCHARGEABLE defect — the design as specified cannot satisfy its own falsifiable gate. That is not the case here. The design SPINE survives falsification intact: neither falsifier refuted C-EPOCH (fast capacity bands never bump epoch and gate NEW claims only; only slow capability bands mig/ecc bump epoch and fence held leases, dissolving the self-abort loop), the companion-table fault isolation (separate savepoint-guarded write mirroring NODE_LEASE_CAS), LEAST(probe_floor, exporter) probe-anchoring, phantom-shrink over self-lease, the fleet-floor dead-man guard, additive/reversible Migration 010 at the lowest-unused number, the residency-only ollama-ondemand floor, or the live-infra-inert posture. And BC1 is concretely dischargeable in ONE cycle: di-fleet ALREADY splits --model and the context flags at its own layer (_split_argv), so model_footprint can come from a registry-side model→mib policy row and max_context from the already-handled argv WITHOUT importing DI/Node internals or touching hardware; kv_bytes can be a Python helper or a 010-created SQL function / policy lookup; the same inputs thread through route_slots / first-attempt claim / failover claim; and an e2e di_fleet.main() test pins 32k-vs-4k divergence. Labeling a repairable plan defect undischargeable would be untrue. The honest classification of a real, material, repairable-in-one-cycle defect that has not been repaired and cannot clear under Check-B is needs_revision.

  PROCESS FINDING (the genuinely new contribution of cycle 3, f_revision_loop_exhausted): the normal revision loop is now provably exhausted, not merely slow. workflow.json declares cycles[0] = {from: adjudicate, to: holder, on_verdict: needs_revision, max_iterations: 2}. Cycle 1 (verdict needs_revision) consumed iteration 1 and routed to the holder; cycle 2 (verdict needs_revision) consumed iteration 2 and routed again; both routed opportunities produced ZERO revision (the holder commit and both falsifier files are byte-identical across all three rounds). With max_iterations=2 spent, a third needs_revision has no remaining adjudicate→holder iteration to consume — it is the honest verdict on the DEFECT but it will NOT, by itself, re-route to a holder or unstick the gate. Resolution lies OUTSIDE the holder↔falsifier loop: the operator/convener must either re-task a fresh holder lane to author the BC1–BC5 revision of dialogue/holder/BUILD_PLAN.md, or escalate the design gate for human review and a termination decision. This finding does not alter the verdict (the spine is sound, BC1 is dischargeable); it records that the gate is stuck under the declared cycle budget and names the only paths out. I am surfacing it both here and via a control-plane escalation.

  THE BINDING CONSTRAINTS: BC1 (high, gate, requires_convener_rebuttal) is the blocker. FOUR accompanying repairs carry forward unchanged, all from Falsifier 2 and all landed_and_rebutted: BC2 (high, gate) make freshness staleness SINGLE-CLOCK (node-local now − exporter/probe source_ts, both sampled on the writing node) rather than node-clock fast_source_ts vs DB-clock heartbeat_ts; do NOT adopt the falsifier's own fix of stamping source_ts with DB now(), which defeats frozen-exporter detection (gate bullet 1); test BOTH skew-resistance AND frozen-source decay. BC3 (medium, policy) guard live_slowdown_factor against probe_ms None (failed decode_probe; and the ollama-ondemand residency-only path, which by the plan's OWN design returns probe_ms None on every tick) and cold_probe_ms None/0 (write NULL/sentinel + capacity_source absence, never raise, inside the savepoint-guarded boundary); define the ollama-ondemand no-decode-baseline rule; add failed-probe + cold-ollama-ondemand tests. BC4 (medium, policy) wire CAPACITY_UPSERT into the puller write-path (heartbeat_all.py pull_write / tick completion) with the same separate-savepoint-guarded discipline, so pull-mode slots — including peecee, Principle 3's motivating co-tenant host — get companion rows; add an integration test that the puller populates gpu_slots_capacity. BC5 (low, policy) disambiguate that slices are independently COMMITTABLE (each green under hermetic pytest) but NOT freely deploy-ordered — Slice 2 has a HARD deploy-order precondition on 010 because mig_mode/ecc_mode ride the NON-savepoint-guarded gpu_slots liveness UPSERT; state DB→writer→reader as the operative apply order; do NOT move mig/ecc into the guarded companion write (they must bump epoch, which lives in the gpu_slots UPSERT by design) and do NOT add runtime column-existence probing. The revision (whoever authors it) discharges BC1 and folds in BC2–BC5, preserves everything under 'What survived', and does not re-open the settled RFC; Falsifier 1 then re-challenges the revised plan.
entries:
  - kind: claim
    by: holder
    refs: ["dialogue:1"]
    text: |-
      Holder build plan (unchanged since cycle 1; single commit 5111c9e): realize the settled RFC 0005 as ordered, independently-committable slices mirroring DB→writer→reader. Slice 0 — additive Migration 010 (gpu_slots_capacity companion table, all columns nullable/defaulted; capacity_policy band-edges / M-of-N / half-lives as DATA rows; a capacity_slots LEFT-JOIN view exposing freshness-decayed effective_free; two nullable gpu_slots columns mig_mode/ecc_mode). Slice 1 — Writer A: live_slowdown_factor + a captured cold baseline, written via a SEPARATE savepoint-guarded CAPACITY_UPSERT (cheapest first, zero new side effect). Slice 2 — Writer B: probe-floor behind per-backend adapters (ollama-ondemand residency-only), exporter enrichment with effective_free = LEAST(floor, exporter), per-PID phantom that shrinks effective_free, and mig/ecc folded into the gpu_slots UPSERT + epoch CASE. Slice 3 — Reader: pick_slot / di_fleet swap the flat vram_free predicate for a probe-anchored headroom predicate while keeping legacy keys (BC2 discipline). Self-identified load-bearing decision C-EPOCH ('falsifiers: attack this first'): fast bands never bump epoch and gate NEW claims only; only slow capability bands bump epoch and fence held leases, avoiding the self-abort loop. Falsifiable surface offered: C1, C2, C-EPOCH, C3–C8, plus OQ-A/B/C/E/P.
  - kind: challenge
    by: falsifier_1
    refs: ["dialogue:2"]
    correspondence: landed_unrebutted
    text: |-
      Slice 3 has no production path for request-specific headroom. The RFC reader invariant is headroom = effective_free − (model_footprint + kv_bytes(max_context)), not merely 'use a lower free number'. route_slots() calls pick() with no model / no min_vram; _split_argv() treats --model and context flags as opaque passthrough; main() / run_leased_shard() / run_failover_shard() pass no model_mib and no max_context; claim() defaults model_mib=0 and the plan only adds a DEFAULTED optional max_context — so production routes a 32k and a 4k request identically. Where model_footprint / max_context come from is undefined, and any ad-hoc fill (Node-engine inspection, querying a running backend, measuring real GPUs) would break the di --json boundary / live-infra posture. Second strike: the Slice 3 SQL names kv_bytes(%(max_context)s) but Migration 010 creates no kv_bytes function or model-footprint object — if Python-side the SQL shape is wrong, if SQL-side the migration is incomplete (the predicate as written cannot run). None of the proposed gate tests proves di_fleet.main() threads request capacity through arg-parse → route_slots → first-attempt claim → failover claim → LEASE_CLAIM_SQL. Required: define the request-capacity contract, define kv_bytes and its owning slice, thread the same inputs through all claim paths, and add the e2e test. ADJUDICATION (cycle 3, re-derived on the unchanged trajectory): LANDS on two verdict-basis axes (a falsifiable-gate item with no real test; a broken/at-risk di --json boundary) and is UNREBUTTED — the holder's pre-emptive defenses (Slice 3 Change B, C7) cover only the empty-companion COALESCE fall-through, and C7 actually concedes the gap by treating the predicate as byte-equivalent-to-today with kv_bytes defaulting to 0. By RFC 0094 §5 Check-B (mechanically enforced) a clearing verdict cannot issue while this is unrebutted → BC1, the blocker. Dischargeable in one cycle → needs_revision, not reject.
  - kind: challenge
    by: falsifier_2
    refs: ["dialogue:3"]
    correspondence: landed_and_rebutted
    text: |-
      Challenge 4 (clock-skew in freshness decay): OQ-C claims skew resistance by decaying a field when fast_source_ts lags the row's own heartbeat_ts by k×half_life, but fast_source_ts is node/exporter-clock and heartbeat_ts is DB now()-clock, so the comparison is cross-clock; with a seconds-scale fast half-life a node↔DB NTP skew above k×half_life spuriously marks fresh capacity stale fleet-wide. The holder DID pre-emptively engage skew (OQ-C exists) → rebutted-in-engagement, but the mechanism as written is not single-clock. CRITICAL: the falsifier's own fix (stamp source_ts with DB now()) is WRONG — it defeats frozen-exporter detection (gate bullet 1 needs the source's own measurement time, which stops advancing when the exporter freezes). Residual → BC2 (gate): single-CLOCK staleness (node-local now − source_ts, both node-sampled), keep source_ts as the source measurement time, and test BOTH skew-resistance AND frozen-source decay.
  - kind: challenge
    by: falsifier_2
    refs: ["dialogue:3"]
    correspondence: landed_and_rebutted
    text: |-
      Challenge 2 (None/0 probe_ms crash): live_slowdown_factor = probe_ms / cold_probe_ms raises TypeError when probe_ms is None (decode_probe returns False,None on a failed/timed-out probe; ollama-ondemand returns True,None and skips the decode probe — so by the plan's OWN residency-only design probe_ms is None on EVERY tick for that slot, a guaranteed hit) and ZeroDivisionError when cold_probe_ms is 0/None. Happy-path mocks miss it; the savepoint-guarded companion write is a PARTIAL pre-emptive cover (it isolates a thrown capacity write from liveness IF the division is inside the guarded block, but the ollama-ondemand slot would then never produce a well-formed companion row) → rebutted-in-engagement. Residual → BC3 (policy): explicitly guard probe_ms None / cold_probe_ms None-or-0 (write NULL/sentinel + capacity_source absence, never raise), define the ollama-ondemand no-decode-baseline rule, and add hermetic tests for a failed probe and a cold loadable ollama-ondemand slot.
  - kind: challenge
    by: falsifier_2
    refs: ["dialogue:3"]
    correspondence: landed_and_rebutted
    text: |-
      Challenge 1 (puller never writes the companion): heartbeat_all.py runs the puller with its own pull_write()/tick() and does not call heartbeat_once(); the plan describes CAPACITY_UPSERT only inside heartbeat_once (Slice 1) and names heartbeat_all only for the exporter proxy + the shared epoch-CASE UPSERT (Slice 2), never wiring the companion write into the pull path. Result: every pull-mode slot — including peecee, the host whose co-tenant motivates Principle 3 — gets no companion row and silently COALESCE-falls-back to legacy vram_free. The plan DID name heartbeat_all and route peecee's capacity through the puller-lease holder over the existing pull channel (rebutted-in-intent), but the specific write wiring + an integration test are absent. Degrades gracefully (no crash). Residual → BC4 (policy): wire CAPACITY_UPSERT into the puller write-path and add an integration test that running the puller populates gpu_slots_capacity for a pulled node.
  - kind: challenge
    by: falsifier_2
    refs: ["dialogue:3"]
    correspondence: landed_and_rebutted
    text: |-
      Challenge 3 (independent committability vs deploy order): Slice 2 adds mig_mode/ecc_mode to the NON-savepoint-guarded liveness UPSERT and extends the epoch CASE; deploying Slice 2 against the un-migrated schema (before 010) fails the liveness UPSERT with column-not-found and ages slots out — so the slices are not freely deploy-independent. Partly a misread: 'safe in either deploy order' refers to writer A-vs-B, and §2 already MANDATES DB-first apply order (010 before the writers), which forbids the crash → rebutted by the existing apply-order discipline. The falsifier's option to move mig/ecc into the guarded companion write is REJECTED (mig/ecc must bump epoch, which lives in the gpu_slots UPSERT by design). Residual → BC5 (policy): scope 'independently committable' to git/test isolation, and state Slice 2's HARD deploy-order precondition on 010 explicitly.
  - kind: rebuttal
    by: holder
    refs: ["dialogue:1"]
    text: |-
      Holder in-plan pre-emptive defenses (these survive falsification and define the kept spine): companion table LEFT JOINed + a separate savepoint-guarded CAPACITY_UPSERT (mirrors NODE_LEASE_CAS) so a flaky/garbage exporter cannot sink the liveness UPSERT (C3); C-EPOCH — fast bands never bump epoch (gate NEW claims only), only mig/ecc bump epoch and fence held leases, avoiding the self-abort loop (OQ-E, gate tests C/D/E); effective_free = LEAST(floor, exporter) (C4); phantom shrinks effective_free rather than minting a self-lease (OQ-P); fleet-floor guard so pick never returns empty (C5); additive/reversible 010 at the lowest-unused number (C1/C2); reader COALESCE fall-through + legacy keys for backward-compat (C7); ollama-ondemand residency-only floor never force-loads (OQ-B, gate test K); live-infra inert. The holder did NOT pre-emptively defend, and (the plan being UNREVISED across cycles 1→2→3) still does not defend: where di_fleet sources model_footprint / max_context in production nor define kv_bytes (Falsifier 1 → BC1, landed_unrebutted, the blocker); the single-clock requirement behind OQ-C (BC2); the None/0 probe_ms guard incl. the ollama-ondemand no-baseline case (BC3); or wiring the companion write into the puller path (BC4).
findings:
  - id: f_reader_request_capacity
    severity: high
    posture: "correctness-of-the-falsifiable-gate / di --json boundary"
    status: open
    challenge: |-
      Slice 3 ships the headroom SQL but no production path to supply model_footprint / request max_context (route_slots / main / first-claim / failover all omit them; claim() gains only a defaulted kwarg → production is a no-op so a 32k and a 4k request route identically), references an undefined kv_bytes() that no slice/migration creates (the SQL as written cannot run), and never reconciles the di --json boundary with sourcing the request capacity (an ad-hoc fill risks crossing the boundary or probing live hardware). The RFC's central reader invariant (32k vs 4k route differently) has no production path and no end-to-end test. UNREBUTTED — C7 / Slice-3 cover only the COALESCE / default fall-through and C7 concedes the predicate is byte-equivalent-to-today. This is the reason the gate cannot clear (RFC 0094 §5 Check-B, enforced mechanically by the validator). Dischargeable in one cycle, so needs_revision, not reject → BC1.
    affected_invariants: ["routing_uses_request_specific_headroom_at_actual_context_length", "di_json_subprocess_boundary_preserved", "no_live_infra_dependency_in_the_reader"]
    requires_convener_rebuttal: true
    source_refs: ["dialogue:1", "dialogue:2"]
  - id: f_freshness_clock_skew
    severity: high
    posture: "correctness-of-the-falsifiable-gate / freshness decay"
    status: open
    challenge: |-
      OQ-C's relative-cadence decay compares a node/exporter-clock fast_source_ts against a DB-clock heartbeat_ts — cross-clock — so NTP skew above the seconds-scale fast half-life spuriously decays fresh capacity fleet-wide. Rebutted-in-engagement (OQ-C exists) but the mechanism is not single-clock as written. The falsifier's fix (DB-now source_ts) would defeat frozen-exporter detection (gate bullet 1). Discharge with single-clock staleness + a skew-resistance AND a frozen-source-decay test → BC2.
    affected_invariants: ["frozen_exporter_decays_within_k_half_life", "fresh_capacity_is_not_spuriously_marked_stale_under_clock_skew"]
    requires_convener_rebuttal: false
    source_refs: ["dialogue:1", "dialogue:3"]
  - id: f_probe_none_crash
    severity: medium
    posture: "writer-robustness / ollama-ondemand handling"
    status: answered
    challenge: |-
      live_slowdown_factor = probe_ms / cold_probe_ms raises on probe_ms None (failed probe; ollama-ondemand residency-only returns probe_ms None on every tick by design) or cold_probe_ms 0/None; happy-path mocks miss it. The savepoint guard is a partial cover (it isolates liveness but leaves the ollama-ondemand companion row never written). Discharge with an explicit None/0 guard (NULL/sentinel + capacity_source absence), an ollama-ondemand no-baseline rule, and failed-probe + cold-ollama-ondemand tests → BC3.
    affected_invariants: ["heartbeat_tick_never_crashes_on_a_none_or_zero_probe", "ollama_ondemand_capacity_is_well_formed_without_a_decode_baseline"]
    requires_convener_rebuttal: false
    source_refs: ["dialogue:1", "dialogue:3"]
  - id: f_puller_companion_absent
    severity: medium
    posture: "writer-coverage / pull-mode slots"
    status: answered
    challenge: |-
      CAPACITY_UPSERT is described only in heartbeat_once; the puller (heartbeat_all.py pull_write/tick) is never wired to write the companion, so all pull-mode slots — including peecee (Principle 3's motivating co-tenant host) — silently fall back to legacy vram_free. Rebutted-in-intent (the plan routes peecee's exporter through the puller) but the write wiring + an integration test are missing → BC4. Degrades gracefully (no crash); the RFC's features just never reach pull-mode slots.
    affected_invariants: ["pull_mode_slots_receive_capacity_telemetry_in_the_companion"]
    requires_convener_rebuttal: false
    source_refs: ["dialogue:1", "dialogue:3"]
  - id: f_slice_deploy_order
    severity: low
    posture: "independent-committability vs deployability"
    status: answered
    challenge: |-
      mig/ecc ride the non-savepoint-guarded liveness UPSERT, so Slice 2 deployed before 010 fails the UPSERT and ages slots out — Slice 2 has a hard deploy-order precondition on 010. Partly a misread of 'either deploy order' (which means writer A-vs-B; §2 already mandates DB-first). The move-mig/ecc-to-guarded-write alternative is rejected (mig/ecc must bump epoch in the gpu_slots UPSERT). Residual → BC5: disambiguate committable (git/test) vs deployable, and state the 010 precondition explicitly.
    source_refs: ["dialogue:1", "dialogue:3"]
  - id: f_revision_loop_exhausted
    severity: high
    posture: "gate-process / revision-routing cycle budget spent (cycle-3 observation)"
    status: open
    challenge: |-
      NEW in cycle 3 (a process finding, not a build constraint), now stated against the declared cycle budget: workflow.json cycles[0] = {from: adjudicate, to: holder, on_verdict: needs_revision, max_iterations: 2}. Cycle 1 (verdict_72678985…, needs_revision) consumed iteration 1 and routed to the holder; cycle 2 (verdict_45afc71f…, needs_revision) consumed iteration 2 and routed again; this is cycle 3. Git shows a single holder commit 5111c9e with BUILD_PLAN.md / falsifier_1 / falsifier_2 byte-identical across all three rounds — both routed revision opportunities produced ZERO revision. With max_iterations=2 spent, a third needs_revision has no remaining adjudicate→holder iteration to consume: it is the honest classification of the DEFECT (BC1 is repairable, not undischargeable) but it cannot, by itself, re-route to a holder or unstick the gate. RESOLUTION (outside the holder↔falsifier loop): operator/convener intervention is required — re-task a fresh holder lane to deliver the BC1–BC5 revision, or escalate the gate for human review and a termination decision. This finding does NOT change the verdict (the design spine is sound and BC1 is dischargeable); it records that the gate is stuck under the declared cycle budget and names the only paths out. Surfaced both here and via a control-plane escalation.
    affected_invariants: ["a_needs_revision_verdict_must_have_a_remaining_cycle_iteration_to_be_actionable"]
    requires_convener_rebuttal: false
    source_refs: ["dialogue:1", "dialogue:2"]
constraints:
  - id: BC1
    posture: "reader-side-headroom-gate / di --json boundary"
    severity: high
    kind: gate
    binding: true
    source_finding: f_reader_request_capacity
    source_refs: ["dialogue:2"]
    text: |-
      BLOCKING repair (the reason the gate cannot clear). Slice 3 MUST define the request-capacity contract explicitly, with a discharging test, such that the RFC's headroom invariant is enforced in PRODUCTION, not just in the SQL: (a) di_fleet MUST obtain model_footprint (model_mib) and request max_context at the di-fleet layer — from the already-handled --model / context argv (di-fleet already splits these in _split_argv) and/or a registry-side model→mib policy row — WITHOUT importing DI/Node engine internals or probing live hardware; if neither source suffices the build MUST escalate rather than cross the di --json boundary or measure real GPUs. (b) Define kv_bytes EXPLICITLY and name its owning slice: a SQL function / generated expression created in Migration 010, a capacity_policy lookup, or a Python helper — the Slice 3 SQL must reference only symbols that actually exist, and the chosen form must be created AND tested in a named slice. (c) Thread the SAME capacity inputs (model_mib + the max_context-derived KV budget) through route_slots()/pick, the first-attempt run_leased_shard()/claim, AND failover_transfer()/run_failover_shard()/claim — a defaulted optional kwarg that production never populates does NOT satisfy this. (d) Add an end-to-end hermetic test of di_fleet.main() (or the nearest production orchestration surface) proving a high-context (e.g. 32k) request and a low-context (4k) request route DIFFERENTLY against the SAME slot whose effective_free sits between the two headroom thresholds, asserting that pick and BOTH claim paths receive non-default capacity inputs and that kv_bytes resolves to a defined symbol. RESTATE C7 so it covers the production threading, not only the empty-companion COALESCE fall-through. The di --json boundary MUST be preserved (parse argv + registry SQL only; never import the engine).
    verification:
      gate: "e2e di_fleet.main() test: a 32k request is refused and a 4k request accepted on the SAME slot whose effective_free is between the two headroom thresholds; pick + first-attempt claim + failover claim all receive non-default model_mib and max_context; kv_bytes resolves to a defined symbol; no engine import, no live-hardware read"
      expected_stage: "design_revision_then_build_verify"
    final_review_required: true
  - id: BC2
    posture: "freshness-decay-gate / clock-skew"
    severity: high
    kind: gate
    binding: true
    source_finding: f_freshness_clock_skew
    source_refs: ["dialogue:3"]
    text: |-
      The freshness-decay comparison MUST be SINGLE-CLOCK. Staleness MUST be computed from two timestamps sampled on the SAME clock — e.g. node-local now − exporter/probe source_ts, both measured on the writing node (written as the computed staleness, or as two like-clock fields the capacity_slots view compares) — NOT node-clock fast_source_ts vs DB-clock heartbeat_ts. The build MUST NOT adopt the falsifier's literal fix of stamping fast_source_ts/slow_source_ts with DB now(), because that DEFEATS frozen-exporter detection (RFC gate bullet 1 needs the source's own measurement time, which stops advancing when the exporter freezes). RESTATE OQ-C to name which clock each timestamp uses. Required tests: (i) gate-test-A MUST additionally prove a node↔DB clock skew of several × half_life does NOT spuriously decay a FRESH slot; (ii) gate-test-B MUST still prove a genuinely frozen source_ts (no writer touching the row) decays to stale within k × half_life.
    verification:
      gate: "skew + frozen-source tests: a several-×-half_life node↔DB skew leaves a fresh slot measured; a frozen source_ts decays to stale within k × half_life"
      expected_stage: "design_revision_then_build_verify"
    final_review_required: true
  - id: BC3
    posture: "writer-robustness / probe-none"
    severity: medium
    kind: policy
    binding: false
    source_finding: f_probe_none_crash
    source_refs: ["dialogue:3"]
    text: |-
      Slice 1 MUST guard the live_slowdown_factor computation against probe_ms is None (failed/timed-out decode_probe; and the ollama-ondemand residency-only path which by the plan's own design returns probe_ms=None on every tick) and against cold_probe_ms None-or-0: write NULL / a sentinel with capacity_source reflecting absence and NEVER raise, and keep the computation inside the savepoint-guarded fault-isolation boundary so even an unexpected raise cannot sink the liveness UPSERT. Define explicitly that an ollama-ondemand slot (no decode baseline) yields a well-formed companion row (live_slowdown_factor NULL / capacity_source set accordingly), not a crash and not a silently-absent row. Required hermetic tests: (i) a failed/None probe leaves the heartbeat tick complete and the companion row well-formed; (ii) a cold loadable ollama-ondemand slot (probe_ms None) produces a well-formed companion row and is never force-loaded.
    verification:
      gate: "probe-none tests: a None/0 probe_ms and a cold ollama-ondemand slot both yield a well-formed companion row with the heartbeat tick completing and liveness unaffected"
      expected_stage: "design_revision_then_build_verify"
    final_review_required: false
  - id: BC4
    posture: "writer-coverage / pull-mode companion"
    severity: medium
    kind: policy
    binding: false
    source_finding: f_puller_companion_absent
    source_refs: ["dialogue:3"]
    text: |-
      Slice 2 (or Slice 1, wherever CAPACITY_UPSERT first lands) MUST wire the companion-table CAPACITY_UPSERT into the PULLER write-path (heartbeat_all.py pull_write / the tick completion step), so pull-mode slots — including peecee, the host whose co-tenant motivates Principle 3 — actually get gpu_slots_capacity rows rather than only the legacy COALESCE fall-through. The puller's companion write MUST keep the same fault-isolation discipline (separate, savepoint-guarded) as the push-mode write, and MUST honor 'only the card-owning node writes its phantom' (per-PID attribution for peecee handled per the plan's existing proxy/deferral, not invented). Required integration test: running the puller driver populates gpu_slots_capacity for a pulled node (asserting the companion row is written, not just the liveness UPSERT).
    verification:
      gate: "puller integration test: heartbeat_all.py's pull path writes a gpu_slots_capacity companion row for a pulled node"
      expected_stage: "design_revision_then_build_verify"
    final_review_required: false
  - id: BC5
    posture: "independent-committability vs deployability"
    severity: low
    kind: policy
    binding: false
    source_finding: f_slice_deploy_order
    source_refs: ["dialogue:3"]
    text: |-
      The revised plan MUST disambiguate that the slices are independently COMMITTABLE (each green under hermetic pytest, which applies all migrations) but NOT freely deploy-ordered: Slice 2 has a HARD deploy-order precondition on Migration 010 because mig_mode/ecc_mode ride the NON-savepoint-guarded gpu_slots liveness UPSERT, so deploying Slice 2 against the un-migrated schema fails the liveness UPSERT and ages slots out. State the DB→writer→reader apply order as the operative invariant (it already does in §2; tighten §1's 'independently committable … safe in either deploy order' so 'either order' is scoped to writer A-vs-B only). Do NOT move mig/ecc into the guarded companion write (they must bump epoch, which lives in the gpu_slots UPSERT by design) and do NOT add runtime column-existence probing (YAGNI for this DB-first, in-order operator deploy). Keep the holder's lowest-unused-migration-number guard.
    verification:
      gate: "committable-vs-deployable disambiguation present; Slice 2's 010 precondition stated explicitly; mig/ecc remain in the gpu_slots UPSERT epoch CASE"
      expected_stage: "design_revision_then_build_verify"
    final_review_required: false
branches:
  reader_request_capacity_contract: "blocked"
  freshness_decay_clock_skew: "cleared_with_constraints"
  writer_robustness_probe_none: "cleared_with_constraints"
  pull_mode_companion_write: "cleared_with_constraints"
  slice_committable_vs_deployable: "cleared_with_constraints"
  revision_loop_exhausted: "blocked"
  epoch_fence_fast_vs_slow_bands_C_EPOCH: "cleared"
  companion_table_fault_isolation: "cleared"
  probe_anchoring_least_floor_exporter: "cleared"
  phantom_shrink_not_self_lease: "cleared"
  fleet_floor_dead_man_guard: "cleared"
  migration_010_additive_reversible: "cleared"
  ollama_ondemand_residency_only_never_force_load: "cleared"
  live_infra_safety: "cleared"
---

# COLLABORATION LEDGER — RFC 0005 Exporter-fed capacity signal (design gate, cycle 3)

author: adjudicator-claude-opus-4.8-004

- **RFC:** `docs/rfc/0005-exporter-capacity-signal.md`
- **Phase:** dialogue → synthesis (`adjudicate`), **cycle 3 / re-opened** — a fresh adjudicator
  session (ordinal 004). The daemon's last *recorded* finding is **cycle 2 / attempt 2**
  (`needs_revision`); a prior session for this attempt wrote a cycle-3 draft but never recorded a
  verdict, so the job was re-leased to me. I re-derived from scratch.
- **Build plan under gate:** `dialogue/holder/BUILD_PLAN.md` (holder-claude-opus-4.8-001) — `dialogue:1`
  — **byte-identical across all three cycles** (single holder commit `5111c9e`; no second holder
  commit exists)
- **Challenges read:** `dialogue/falsifier_1/FALSIFIER.md` (falsifier-openai-codex-gpt-5.5-001) — `dialogue:2`;
  `dialogue/falsifier_2/FALSIFIER.md` (falsifier-antigravity-gemini-001) — `dialogue:3` — both unchanged
  (commits `1d84e2f`, `9aba38b`)
- **Prior adjudications:** cycle 1 (committed `b0292f4`, `needs_revision`); cycle 2 (committed
  `38d319d`, `needs_revision` — the daemon's tracked prior finding)
- **Evidence basis:** the curated dialogue trajectory + the RFC only, plus the git/verdict
  provenance of the trajectory and `workflow.json`'s declared cycle budget (to establish that the
  plan is unrevised and the revision loop is exhausted). No raw provider logs, no private
  diagnostics, no live-code spelunking.

---

## VERDICT — `needs_revision` (the gate does not clear; the commit phase does not run)

**One-line reason:** Re-derived fresh on the still-unchanged trajectory, the single thing blocking
the clear is unchanged: **Falsifier 1 lands a material, `landed_unrebutted`** challenge on the RFC's
central **reader-side headroom invariant** — Slice 3 writes the
`headroom = effective_free − (model_footprint + kv_bytes(max_context))` SQL but ships **no
production path** to supply `model_footprint`/`max_context` (only a defaulted kwarg production never
populates), references an **undefined `kv_bytes`** symbol that no slice/migration creates (so the SQL
as written cannot run), and never reconciles the *di --json* boundary with where the request capacity
comes from. A clearing verdict requires every landed challenge to be rebutted in the trajectory
(**RFC 0094 §5 Check-B**), and that is **enforced mechanically by the artifact validator**. The
defect is **repairable in one cycle**, so the verdict is `needs_revision` with **BC1 as the blocking
repair** and **BC2–BC5** accompanying it.

### Why I re-derived rather than defaulting to the prior answer

The guidance for a re-opened round is to review the **current** revision and not republish. I did:
I re-read the plan and both falsifiers, re-tested each challenge against the plan-as-it-stands, and
re-weighed all four verdicts. The trajectory files are byte-identical to cycle 2's (same commits
`5111c9e` / `1d84e2f` / `9aba38b`), so the **substance** of the verdict is the same — *because the
inputs are the same* — but this ledger is my own composition, and it adds a sharper cycle-3 process
finding (below) grounded in the workflow's **declared cycle budget**, which the prior cycles did not
cite.

### Why both clearing and terminal alternatives fail

- **`accept` / `accept_with_findings` — refused.** Mechanically blocked by Check-B while Falsifier 1
  is `landed_unrebutted`; and substantively wrong — the holder defended only the empty-companion
  `COALESCE` fall-through (C7 actually **concedes** the gap by treating the predicate as
  byte-equivalent-to-today with `kv_bytes` defaulting to 0). Relabeling F1 as rebutted to force a
  clear would be a **fabrication**.
- **`reject` — rejected.** `reject` is reserved for an **undischargeable** defect (the design cannot
  satisfy its own falsifiable gate). The **design spine survives falsification intact** (see "What
  survived"), and BC1 is **dischargeable in one cycle**: `di-fleet` already splits `--model` and the
  context flags at its own layer (`_split_argv`), so footprint can come from a registry-side
  model→mib policy row and `max_context` from the already-handled argv **without** importing the
  engine or touching hardware; `kv_bytes` can be a Python helper or a 010-created SQL function; the
  same inputs thread through all claim paths; and an e2e `di_fleet.main()` test pins 32k-vs-4k
  divergence. Calling a repairable plan defect *undischargeable* would be **untrue**. That two routed
  revision cycles produced no fix is an **orchestration** failure, not a property of the defect.

The honest classification of a real, material, **repairable-in-one-cycle** defect that has **not**
been repaired and **cannot** clear under Check-B is **`needs_revision`**.

---

## ⚠️ Cycle-3 process finding — the revision loop is *exhausted*, not just slow (f_revision_loop_exhausted)

This is the **new** contribution of cycle 3, and it is sharper than a generic "stall": it is grounded
in the workflow's own declared cycle budget.

- `workflow.json` declares `cycles[0] = {from: adjudicate, to: holder, on_verdict: needs_revision,
  max_iterations: 2}`.
- **Cycle 1** (`needs_revision`) consumed iteration 1 and routed to the holder; **cycle 2**
  (`needs_revision`) consumed iteration 2 and routed again; **this is cycle 3.** Git shows a single
  holder commit `5111c9e` and byte-identical falsifier files across all rounds — **both routed
  revision opportunities produced zero revision.**
- With `max_iterations=2` **spent**, a third `needs_revision` has **no remaining adjudicate→holder
  iteration** to consume. It is the honest verdict on the **defect**, but it will **not**, by itself,
  re-route to a holder or unstick the gate.
- **Required intervention (outside the holder↔falsifier loop):** the operator/convener must either
  **(a) re-task a fresh holder lane** to author the BC1–BC5 revision of
  `dialogue/holder/BUILD_PLAN.md`, or **(b) escalate the gate for human/convener review** and decide
  whether to terminate the design run with this truthful ledger as its record.
- **Do not** read a third `needs_revision` as license to clear: BC1 remains `landed_unrebutted` and
  Check-B still refuses any clearing verdict.

I am surfacing this finding **both here and via a control-plane escalation** so it is not buried in
the artifact alone.

---

## What survived falsification (the sound spine — keep it through the revision)

No challenge refuted these; they are the load-bearing design and must be preserved intact:

- **C-EPOCH — the plan's self-identified "attack this first" decision survives untouched.** Fast
  capacity bands (headroom / util / `live_slowdown_factor` / phantom) live **only** in the companion
  table and **never bump `gpu_slots.epoch`**; they gate **NEW** picks/claims — exactly RFC-0002's
  "demotion gates new claims, not renews." Only the **slow capability bands** (`mig_mode`/`ecc_mode`,
  from local `nvidia-smi`, joining RFC-0003's `{served_model, nvlink_domain, max_context}`
  `IS DISTINCT FROM` set) bump `epoch` and fence held leases. This dissolves the genuine **self-abort
  loop** (a running job's own KV allocation dropping its headroom band would otherwise fence its own
  renew). **Neither falsifier attacked it** (Falsifier 2 #3 touches `mig/ecc` only on deploy-ordering).
- **C3 — companion-table fault isolation.** `gpu_slots_capacity` LEFT JOINed by `pick`, written by a
  **separate, savepoint-guarded** statement (mirrors `NODE_LEASE_CAS`), so a flaky/garbage exporter
  degrades the fleet to liveness-only routing and **cannot poison the `gpu_slots` liveness UPSERT**.
- **C4 — probe-anchoring.** `effective_free_mib = LEAST(probe_floor_mib, exporter_free_mib)` — trust
  the lower so an over-reporting exporter cannot claim headroom the probe could not allocate.
- **OQ-P — phantom shrinks `effective_free`** rather than minting a synthetic self-lease.
- **C5 — fleet-floor / dead-man guard.** `pick` never returns empty when all fast fields are stale.
- **C1/C2 — Migration 010 additive, reversible, correct lowest-unused number.**
- **OQ-B / gate test K — `ollama-ondemand` residency-only floor never force-loads** (Falsifier 2 #2
  surfaces a *consequence* of the residency-only path → BC3, but does not refute never-force-load).
- **Live-infra safety (§4) and the DB→writer→reader slice discipline** — all hardware reads are
  injected fakes; PG tests are `GPU_FLEET_TEST_DB`-guarded and refuse bare `gpu_fleet`.

`C7` survives only **in part** — it must be **restated** under BC1 to cover the production threading
of request capacity, not only the empty-companion `COALESCE` fall-through.

---

## Per-challenge adjudication

| Source | Claim hit | Correspondence | Becomes |
|--------|-----------|----------------|---------|
| F1 (codex) | Slice 3 / C7 — reader-side headroom has no production path; `kv_bytes` undefined; boundary unreconciled | **landed_unrebutted** | **BC1** (blocking) |
| F2 (gemini) #4 | OQ-C — freshness decay claimed clock-skew resistant | landed_and_rebutted | **BC2** (gate) |
| F2 (gemini) #2 | Slice 1 — `live_slowdown_factor` division on `None`/`0` | landed_and_rebutted | **BC3** (policy) |
| F2 (gemini) #1 | Slices 1/2 — puller never writes the companion (peecee blind) | landed_and_rebutted | **BC4** (policy) |
| F2 (gemini) #3 | Slice 2 — slices not independently committable / deploy order | landed_and_rebutted | **BC5** (policy) |
| (cycle-3) | Revision loop exhausted — `max_iterations=2` spent, 0 revisions | process finding | escalation / re-task |

### #1 — Falsifier 1: Slice 3 has no production path for request-specific headroom (LANDS, UNREBUTTED — the blocker)

Hits the verdict-basis bullseye on **two** axes: *a falsifiable-gate item with no real test* and *an
at-risk `di --json` boundary*. The RFC's reader invariant is
`headroom = effective_free − (model_footprint + kv_bytes(max_context))` — "a 32k-context request and a
4k-context request correctly see different slots as routable." Slice 3 writes the SQL, but:

- `route_slots()` calls `pick()` with **no** `model`/`min_vram`; `_split_argv()` passes `--model` and
  context flags through **opaquely**; `main()`/`run_leased_shard()`/`run_failover_shard()` pass **no**
  `model_mib`/`max_context`; and `claim()` gains only a **defaulted optional** `max_context`. With
  defaults, the production predicate is **byte-equivalent to today** — so a 32k and a 4k request are
  **indistinguishable** in the only consumer path that matters.
- The Slice 3 SQL names `kv_bytes(%(max_context)s)`, but **no slice and not Migration 010 create a
  `kv_bytes` function / model-footprint object**. The symbol is **undefined** — the predicate as
  written **cannot run** — and the plan never says whether `kv_bytes` is SQL-side, a generated column,
  a policy-table lookup, or Python-side.
- §5 asserts the boundary is preserved but **never says where `model_footprint`/`max_context` come
  from**. An ad-hoc fill (inspect the Node engine, query a running backend, measure real GPUs) would
  **break** the boundary / live-infra posture.

The holder offered **no pre-emptive defense**, and — the plan being unrevised across all three cycles
— still offers none. **Unrebutted → cannot clear (RFC 0094 §5 Check-B, mechanically enforced) →
BC1.** *Not `reject`:* dischargeable in one cycle (argv already split at the di-fleet layer; footprint
from a registry policy row; `kv_bytes` as a defined helper/SQL fn; threading + an e2e test). The
design **can** satisfy its own gate.

### #2 — Falsifier 2 #4: clock-skew in freshness decay (LANDS, REBUTTED — binding gate residual)

OQ-C claims skew resistance by decaying a field when `fast_source_ts` lags **the row's own
`heartbeat_ts`** by `k × half_life`. But `fast_source_ts` is **node/exporter-clock** and
`heartbeat_ts` is the **DB `now()` clock** — **cross-clock** — so a node↔DB NTP skew above the
*seconds-scale* fast half-life spuriously marks fresh capacity `stale` fleet-wide. The holder **did**
engage skew (OQ-C exists) → **rebutted-in-engagement, not conceded** — but the mechanism is not
single-clock as written. **Critically, the falsifier's own fix is wrong:** stamping `fast_source_ts`
with DB `now()` would **defeat frozen-exporter detection** (RFC gate bullet 1 needs the *source's own
measurement time*). → **BC2:** single-clock staleness (node-local now − `source_ts`, both node-
sampled), keep `source_ts` as the source measurement time, ship **both** a skew-resistance and a
frozen-source-decay test.

### #3 — Falsifier 2 #2: `live_slowdown_factor` division on `None`/`0` (LANDS, REBUTTED — policy residual)

`live_slowdown_factor = probe_ms / cold_probe_ms` raises `TypeError` when `probe_ms` is `None`
(`decode_probe` → `False, None` on failure) and — **by the plan's own design** — on the
`ollama-ondemand` residency-only path, which skips the decode probe and returns `True, None`, so
`probe_ms` is `None` on **every** tick for that slot (a guaranteed hit); and `ZeroDivisionError` when
`cold_probe_ms` is `0`/`None`. Happy-path mocks miss it. The savepoint-guarded companion write is a
**partial** pre-emptive cover — it isolates liveness from the throw, but then the `ollama-ondemand`
companion row is **never written**. → **BC3:** explicit `None`/`0` guard (NULL/sentinel +
`capacity_source` absence, never raise), a defined `ollama-ondemand` no-baseline rule, and
failed-probe + cold-`ollama-ondemand` tests.

### #4 — Falsifier 2 #1: puller never writes the companion (LANDS, REBUTTED — policy residual)

`heartbeat_all.py` runs the puller with its own `pull_write()`/`tick()` and does **not** call
`heartbeat_once()`; the plan describes `CAPACITY_UPSERT` only inside `heartbeat_once` (Slice 1) and
names `heartbeat_all` only for the exporter proxy + the shared epoch-`CASE` UPSERT (Slice 2), **never
wiring the companion write into the pull path**. So every pull-mode slot — including **peecee, the host
whose co-tenant motivates Principle 3** — gets no companion row and silently `COALESCE`-falls-back to
legacy `vram_free`. The holder **did** route peecee's exporter through the puller-lease holder
(rebutted-in-intent), but the write wiring + an integration test are absent. Degrades **gracefully**
(no crash) → **BC4:** wire `CAPACITY_UPSERT` into the puller write-path + an integration test that the
puller populates `gpu_slots_capacity`.

### #5 — Falsifier 2 #3: independent committability vs deploy order (LANDS, REBUTTED — policy residual)

`mig_mode`/`ecc_mode` ride the **non-savepoint-guarded** liveness UPSERT, so deploying Slice 2 against
an un-migrated schema fails the UPSERT and ages slots out — Slice 2 has a **hard deploy-order
precondition** on 010. The challenge **partly misreads** the plan ("safe in either deploy order"
refers to writer **A-vs-B**, and §2 already mandates **DB-first** apply order) → rebutted by the
existing apply-order discipline. The falsifier's alternative of moving `mig/ecc` into the guarded
companion write is **rejected** (`mig/ecc` *must* bump `epoch`, which lives in the `gpu_slots` UPSERT
by design). → **BC5:** scope "independently committable" to git/test isolation and state the 010
precondition explicitly; no runtime column probing.

---

## Required repairs (machine-readable in front-matter `constraints[]`)

| ID | Binding | Severity | Repair |
|----|---------|----------|--------|
| **BC1** | **yes (blocking gate)** | high | Define the request-capacity contract: (a) source `model_footprint`/`max_context` at the di-fleet layer from argv + a registry policy row, never importing the engine or probing hardware (escalate if neither suffices); (b) define `kv_bytes` and its owning slice (SQL fn / generated col / policy lookup / Python helper); (c) thread the SAME inputs through `route_slots`/pick, first-attempt claim, AND failover claim; (d) e2e `di_fleet.main()` test proving 32k vs 4k route differently on the same slot. Restate C7 for production threading. |
| **BC2** | **yes (gate)** | high | Single-CLOCK staleness (node-local now − `source_ts`, both node-sampled); keep `source_ts` as the source measurement time (do **not** stamp it with DB `now()` — that breaks frozen-exporter detection); test skew-resistance AND frozen-source decay. |
| BC3 | recommended (policy) | medium | Guard `live_slowdown_factor` on `probe_ms` None (incl. the cold `ollama-ondemand` path) and `cold_probe_ms` `0`/None (NULL/sentinel, never raise, inside the fault-isolation boundary); test a failed probe and a cold `ollama-ondemand` slot. |
| BC4 | recommended (policy) | medium | Wire `CAPACITY_UPSERT` into the puller write-path (`heartbeat_all.py`) so pull-mode slots (peecee) get companion rows; integration test that the puller populates `gpu_slots_capacity`. |
| BC5 | recommended (policy) | low | Disambiguate committable (git/test) vs deployable; state Slice 2's hard 010 precondition (mig/ecc ride the unguarded liveness UPSERT); keep mig/ecc in the `gpu_slots` UPSERT epoch CASE; no runtime column probing. |

---

## Handoff (next step) — who acts, and on what

Because the holder↔falsifier loop's declared budget (`max_iterations=2`) is **spent** and produced no
revision, the next action is **orchestration-level**, not another silent re-route:

1. **Re-task a fresh holder** (or escalate) to revise `dialogue/holder/BUILD_PLAN.md`. The minimal
   clearing diff:
   - **Fold BC1 into Slice 3 (clears the gate).** Define where `di_fleet` gets `model_footprint` (a
     registry-side model→mib policy row) and `max_context` (the already-handled argv), define
     `kv_bytes` and its owning slice, thread both through `route_slots`/first-claim/failover, restate
     C7 for production threading, and add the e2e `di_fleet.main()` 32k-vs-4k test to the §3 gate→test
     map. This is the single change that removes the `landed_unrebutted` challenge so the gate can
     clear.
   - **Fold BC2 into Slice 0/3 + the gate→test map** — single-clock staleness; restate OQ-C naming
     each timestamp's clock; add the skew-resistance test alongside the frozen-source decay test.
   - **Fold BC3 into Slice 1 + its tests** — guard `None`/`0`; `ollama-ondemand` no-baseline rule;
     failed-probe + cold-`ollama-ondemand` tests.
   - **Fold BC4 into Slice 2** — wire `CAPACITY_UPSERT` into the puller; integration test.
   - **Fold BC5 into §1/§2** — committable-vs-deployable wording; explicit 010 precondition.
2. Preserve everything under **"What survived"** — above all **C-EPOCH** (fast bands never bump
   `epoch`; only `mig/ecc` do), the companion-table fault isolation, the `LEAST` probe-anchoring, the
   phantom-shrink choice, the fleet-floor guard, and the live-infra safety boundary — and do **not**
   re-open the RFC's settled design. Falsifier 1 then re-challenges the revised plan.
3. If a fresh holder cannot be tasked, **escalate the gate** and record this ledger as the design
   run's truthful outcome (an honest non-clear, not a silent stall).
