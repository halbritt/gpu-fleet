---
schema_version: "striatum.collaboration_ledger.v1.1"
artifact_kind: "collaboration_ledger"
shape: "falsification_gate"
author: adjudicator-claude-opus-4.8-003
workflow: "rfc-0002-design"
run_id: "run_aa1f69f24463027c2466994e9f655b08"
cycle: 3
topic: "RFC 0002 — Zero-touch node lifecycle: re-gate the cycle-3 REVISED build plan (final budgeted iteration)"
participants: ["holder", "falsifier_1", "falsifier_2", "adjudicator"]
verdict: "accept_with_findings"
rationale: "Cycle-3 re-falsification of the holder's cycle-2->cycle-3 REVISED plan, adjudicated from the curated dialogue trajectory + the settled RFC only (no raw provider logs / private diagnostics). REVISION UNDER GATE: dialogue/holder/BUILD_PLAN.md author holder-claude-opus-4.8-003 (run-branch tip 4c06885; the holder fan-in commit is 8e87d85 'durable artifact publication (holder)'). CHALLENGES READ: dialogue/falsifier_1/FALSIFIER.md (falsifier-openai-codex-gpt-5.5-003) and dialogue/falsifier_2/FALSIFIER.md (falsifier-antigravity-gemini-003). PROVENANCE NOTE (auditable): the worktree the daemon anchored for this adjudicate job (wt_c33a9d9702f51880126c69452c50e27f) is checked out at the STALE commit b1a6adc — the cycle-2 ledger publication — whose tree still carries the attempt-1 BUILD_PLAN (holder-001) and the -001 falsifier files. Per the packet's revision_context ('Review the CURRENT revision of the target'), I reviewed the attempt-3 artifacts from the run-branch tip (striatum/rfc-0002-design @ 4c06885), confirmed via author lines holder-003 / codex-003 / gemini-003 and a git diff (480 insertions / 297 deletions vs attempt 1). VERDICT BASIS: cycle 2 (the second and FINAL budgeted revision iteration, iteration 2 of max 2) recorded SEVEN landed_unrebutted constraints — BC1, BC2, BC6, BC7 (blocking) + BC3, BC4, BC5 (fold-in) — and its binding final-iteration notice said the terminal outcome becomes 'reject' IF the next re-falsification still finds any blocker among BC1/BC2/BC6/BC7 (or the residual BC3-BC5) landed_unrebutted. That trigger DID NOT FIRE: attempt 3 APPLIES all seven as concrete SQL / control-flow / test changes (the discharge is real, not argued), and I verified each in the plan text: BC1 — Slice-3 Change A makes the per-node driver-lease CAS NON-GATING and runs the gpu_slots UPSERT UNCONDITIONALLY (arbitration model c), so a no-fleet_nodes self-pusher registers; composed Slice-1+3 test_self_push_no_fleet_node_registers_and_graduates added. BC2 — SET boot_epoch = COALESCE(EXCLUDED.boot_epoch, gpu_slots.boot_epoch); test_boot_epoch_survives_null_pull_write added. BC6 — boot_epoch is now STRICTLY MONOTONIC PER WRITE (next_boot_epoch via a max(_last+1, time_ns) guard), so the WHERE predicate is a STRICT 'EXCLUDED.boot_epoch > gpu_slots.boot_epoch' (no '>='); an equal-epoch replay is refused and does not re-stamp heartbeat_ts; test_equal_epoch_replay_is_noop + the hermetic test_ratchet_predicate_is_strict_gt substring assertion added. BC7 — probe_streak resets to 1 (if alive) and status -> 'unverified' when gpu_slots.gpu_uuid and EXCLUDED.gpu_uuid are both non-NULL and differ; carry-forward only on a match/unknown uuid; test_uuid_mismatch_resets_streak_and_demotes (hermetic) + test_hot_swap_demotes_to_unverified (PG). BC3 — PULLER_LEASE_TTL = 15 s, pinned strictly < the 45 s staleness window; test_puller_failover_no_ageout advances past the failover gap and asserts no node leaves routable_slots/live_slots. BC4 — the per-node driver-lease freshness predicate is pushed SERVER-SIDE into the FETCH ('WHERE enabled AND (driven_by IS NULL OR now() >= lease_until)'); test_fetch_freshness_uses_db_now_no_client_clock added. BC5 — the fleet_meta column is 'holder' verbatim in the DDL, the Slice-2 CAS, and tests A/B/G/H, which run the real SQL against the real 009 DDL. falsifier_2 (gemini-003) independently CONFIRMS all seven resolved and records 'No Remaining Falsifying Gaps — sound and ready to proceed'; falsifier_1 (codex-003) DROPS every one of BC1-BC7. So the seven cycle-2 constraints SURVIVED falsification and are DISCHARGED — the plan converged on the budgeted gate. WHY accept_with_findings AND NOT reject: reject is reserved for an undischargeable defect / a design that cannot satisfy its own falsifiable gate; the cycle-2 terminal-reject trigger (BC1/BC2/BC6/BC7 still landing) is precisely NOT met, the design satisfies its gate, and the in-build SQL is correct and inert. A reject here would be untruthful. WHY accept_with_findings AND NOT a clean accept: falsifier_1 raises ONE NEW objection that LANDS — the peecee pull-only liveness vs the SSH-nvidia-smi retirement step (BC8). The plan's Section-5 / Section-2-step-2 assert that retiring peecee's cross-host SSH 'nvidia-smi' gpu_cmd is a harmless one-row fleet_nodes DATA step because 'in the pull model peecee's liveness already comes from its HTTP endpoint (ollama-ondemand)'. That factual claim is FALSE against the live code the build is meant to realize: probe_node calls gpu_stats(n['gpu_cmd']) FIRST for every node (heartbeat_all.py), gpu_stats shells nvidia-smi (local or via SSH) and returns {'_error':...} with no gpu_model when the command is absent (heartbeat.py:65-71), and ollama_ondemand_liveness FAILS CLOSED — 'if gpu_err is not None or stats.get(\"gpu_model\") is None: return False, None, None' (heartbeat.py:168) — BEFORE the /api/ps residency check (line 175) and the COLD/loadable VRAM-headroom decision (line 180, which itself needs stats['vram_free_mib']). So executing the named SSH-retirement step would make peecee report alive=False, never accumulate probe_streak, never graduate, and drop out of routable_slots once Slice 4 gates on status='routable' — refuting the gate bullet 'peecee runs zero fleet code/creds, is still monitored (pull), de-listed when marker owns the card', and planned test K (which only asserts the pull path writes through the driver connection and stamps boot_epoch NULL) does NOT exercise the no-SSH peecee path. WHY this is a finding, not a clear-blocking blocker: the build's actual CODE deliverable (migration 009 + the writer/consumer edits + the seven discharged fixes) does NOT remove peecee's SSH gpu_cmd and does NOT change probe_node/gpu_stats/ollama_ondemand_liveness — it is inert wrt live infra (Section 4), so as code the build leaves peecee monitored exactly as today. The defect is in (a) a false load-bearing narrative sentence in Section 5 and (b) a harmful operator apply-order instruction in Section 2 step 2 — NOT in any in-build SQL or any of C1-C12. The plan's OWN hedge survives and is correct: 'the in-build ratchet (strict > + COALESCE) is already correct without it; this step only narrows an operational window, it is not load-bearing for any C-claim' — so the challenge is partially self-rebutted (the seven core C-claims hold; the SSH step's safety/HTTP-liveness framing does not). It is therefore carried as BINDING constraint BC8 the build MUST discharge at build/verify, not a reason to send a fully-converged plan back through a revision iteration the budget no longer has. The minimal discharge (one of): (a) DO NOT retire peecee's SSH 'nvidia-smi' leg in v1 — keep peecee on its existing, working SSH-via-pull liveness, DELETE the Section-2-step-2 SSH-retirement step, and correct Section 5 / Q5 so the 'zero-SSH pull-only' claim is narrowed (peecee is pull-only as to no fleet code/creds on the node, but its liveness still uses an nvidia-smi side channel driven by the puller); OR (b) implement AND test a real HTTP-only peecee liveness path (probe_node skips gpu_stats for an 'ollama-ondemand' node and derives loadable/resident state from the endpoint, recording the lower-trust endpoint-asserted VRAM per Pillar 6 / Q5), with the discharging test falsifier_1 specifies (no SSH/nvidia-smi invoked; alive=True when the endpoint is serveable, boot_epoch stays NULL, can graduate; alive=False when marker owns the card). Either path is bounded and does NOT reopen BC2/BC6 (the ratchet is correct independent of the SSH step). PRESERVED SPINE (survived every cycle, keep intact): C1 (migration number 009 is correct; the RFC's 'Migration 006' is stale — 006/007/008 are the peecee dense flip / RFC-0001 leases / RFC-0003 epoch), C2 (009 purely additive/reversible/behavior-neutral until Slice 4), C4 (status changes no routing until the consumer slice), C5 (writer-before-reader strands no node), C3-PRUNE (stale-only PRUNE preserves a fresh self-push row — now reachable because BC1 makes registration unconditional), C7 (boot_epoch and epoch never alias; the epoch CASE is byte-unchanged), C11 (hermetic default green, every DB-backed test guarded verbatim like test_leases_pg.py/test_epoch_pg.py and runs the real SQL against the real 009 DDL), C12 (every liveness/lease/replay timing decision uses the DB clock; the new boot_epoch ordering token is node-sourced by design and only ever refuses a node's OWN stale replay), the di --json subprocess boundary, peecee-pull-only (no fleet code/creds on the node), and the Section-4 live-infra inertness. PROCESS NOTE: this clears the design gate (accept_with_findings is a clearing verdict) so the commit phase MAY publish the committed plan; the committed plan and the build's verify gate MUST carry forward the discharge tests for BC1-BC7 (they are design-level proofs that become build-level requirements) AND the new binding constraint BC8. An honest accept_with_findings with a truthful ledger is the correct gate outcome: the plan survived falsification on every material build-correctness dimension and the single surviving objection is a bounded, build-dischargeable constraint."
entries:
  - kind: claim
    by: holder
    refs: ["dialogue:1"]
    text: "Holder cycle-3 REVISED build plan (attempt 3, holder-claude-opus-4.8-003, run-branch tip 4c06885). Same five-slice spine (DB migration 009 -> heartbeat graduation writer + boot-epoch ratchet + PRUNE fix -> global puller-lease -> per-node driver-lease -> consumer status gate; RLS deferred; migration number 009). Unlike attempt 2 (which only added prose), attempt 3 APPLIES every cycle-2 constraint as concrete SQL/control-flow/test, with a Section-8 discharge ledger: BC1 -> Slice-3 Change A non-gating per-node lease CAS + unconditional gpu_slots UPSERT (arbitration model c) + composed Slice-1+3 registration test; BC2 -> SET boot_epoch=COALESCE(EXCLUDED.boot_epoch, gpu_slots.boot_epoch) + no-wipe PG test; BC6 -> boot_epoch made strictly-monotonic-per-write (next_boot_epoch) so the ratchet WHERE is a STRICT '>' + equal-epoch-replay-noop PG test + a hermetic strict-'>' substring assertion; BC7 -> probe_streak reset to 1 / status->'unverified' on a non-NULL uuid mismatch + hot-swap hermetic+PG tests; BC3 -> PULLER_LEASE_TTL=15 s (<45 s) + failover-no-ageout PG test; BC4 -> server-side FETCH freshness predicate (now() >= lease_until) + no-client-clock test; BC5 -> fleet_meta column 'holder' aligned across DDL/CAS/tests A/B/G/H. The plan restates C3/C6/C8/C9/C10/C12 to match what is built and declares the sound spine (C1,C2,C4,C5,C3-PRUNE,C7,C11,C12, di-subprocess, peecee-pull-only, Section-4 inertness) preserved."
  - kind: challenge
    by: falsifier_2
    refs: ["dialogue:3"]
    correspondence: not_material
    text: "(gemini attempt 3) Raises NO material falsifying gap. Reviews the revised plan and CONFIRMS all seven cycle-2 constraints resolved with verification: BC1 (unconditional UPSERT, lease is best-effort coordination; composed Slice-1+3 test), BC2 (COALESCE preserves a stored epoch under a NULL pull write; PG test), BC6 (strict '>' on a strictly-monotonic-per-write boot_epoch; equal-epoch replay is a no-op; PG test), BC7 (probe_streak reset + status='unverified' on uuid mismatch; hermetic+PG tests), BC3 (TTL 15 s < 45 s; failover-no-ageout test), BC4 (server-side now() freshness; no-client-clock test), BC5 (one 'holder' name run against the real 009 DDL). Explicitly records 'No Remaining Falsifying Gaps — the plan is sound and ready to proceed to the build and verify phases.' No surviving challenge from falsifier_2; the seven prior constraints are discharged."
  - kind: challenge
    by: falsifier_1
    refs: ["dialogue:2"]
    correspondence: landed_and_rebutted
    text: "(codex attempt 3, NEW — drops all of BC1-BC7) Challenges the peecee pull-only liveness gate against the SSH-'nvidia-smi'-retirement step the plan names. The plan (Section 5 / Section 2 step 2) calls retiring peecee's cross-host SSH 'nvidia-smi' gpu_cmd a harmless one-row fleet_nodes DATA step because 'in the pull model peecee's liveness already comes from its HTTP endpoint (ollama-ondemand)'. That is FALSE against the live code: heartbeat_all.probe_node calls gpu_stats(n['gpu_cmd']) FIRST for every node; gpu_stats shells nvidia-smi (local or SSH) and yields gpu_err / no gpu_model when the command is absent; ollama_ondemand_liveness FAILS CLOSED ('if gpu_err is not None or stats.get(\"gpu_model\") is None: return False, None, None') BEFORE the /api/ps residency check and the VRAM-headroom (COLD/loadable) branch — both of which also need the nvidia-smi VRAM reading. So retiring the SSH leg de-lists peecee (alive=False, never graduates, absent from routable_slots after Slice 4), while RETAINING it leaves the cross-host SSH fan-out the RFC/plan claim to retire still in place. Planned test K does not exercise the no-SSH peecee path. The plan must either implement+test an HTTP-only peecee liveness path (recording its lower-trust endpoint-asserted VRAM per Pillar 6) OR narrow the claim so peecee is not zero-SSH pull-only in v1. landed: lands materially on a named gate bullet and on a false live-infra claim; the holder did not anticipate the fail-closed gpu_stats dependency, so it is unrebutted IN PART — but the plan's own hedge ('not load-bearing for any C-claim') correctly survives, so the in-build SQL correctness is intact -> non-blocking binding constraint BC8."
  - kind: rebuttal
    by: holder
    refs: ["dialogue:1"]
    text: "Holder in-plan defenses (attempt 3; no separate holder rebuttal round — the rebuttal surface is the revised plan's restated C1-C12 + the Section-8 discharge ledger). SURVIVING/CONFIRMED: all seven cycle-2 constraints (BC1-BC7) are applied as real SQL/logic/tests and corroborated by falsifier_2; the sound spine (C1,C2,C4,C5,C3-PRUNE,C7,C11,C12, di-subprocess, peecee-pull-only, Section-4 inertness) stands. PARTIALLY REBUTTED: the peecee SSH-retirement challenge (BC8). The plan's claim that this step is non-load-bearing for any C-claim and that the in-build ratchet is correct without it is TRUE and survives — so the build's in-scope correctness is unaffected; but the adjoining claim that 'peecee's liveness already comes from its HTTP endpoint' (making SSH retirement a safe data step) is FALSE against the live ollama_ondemand_liveness fail-closed-on-missing-gpu_stats path, and there is no in-plan defense of the no-SSH peecee liveness path nor a test for it. The narrative/operator-step defect is unrebutted; the core-correctness defense holds."
findings:
  - id: f_zero_touch_lease_deadlock
    severity: high
    posture: "correctness-of-the-falsifiable-gate / zero-touch register"
    status: answered
    challenge: "DISCHARGED (BC1). Slice-3 Change A makes the per-node driver-lease CAS non-gating and runs the gpu_slots UPSERT unconditionally (arbitration model c), so a self-pusher with no fleet_nodes row still registers (UPSERT creates the row 'unverified'); the stale-only PRUNE keeps it fresh; the directory-driven puller never contends a node it cannot see, so C9 holds. The composed Slice-1+3 test test_self_push_no_fleet_node_registers_and_graduates exercises exactly the path cycle-1/2 said had no real test. Confirmed by falsifier_2."
    affected_invariants: ["registration_equals_first_heartbeat", "zero_touch_register_no_prior_fleet_nodes_row", "push_and_pull_never_both_write_a_node"]
    requires_convener_rebuttal: false
    source_refs: ["dialogue:1", "dialogue:3"]
  - id: f_boot_epoch_null_overwrite
    severity: high
    posture: "split-brain / replay ratchet correctness"
    status: answered
    challenge: "DISCHARGED (BC2). SET boot_epoch = COALESCE(EXCLUDED.boot_epoch, gpu_slots.boot_epoch) — a NULL (pull) write can no longer wipe a push-stamped epoch; the strictly-stale write stays refused after any number of pull ticks. test_boot_epoch_survives_null_pull_write added. Confirmed by falsifier_2."
    affected_invariants: ["boot_epoch_is_a_one_way_monotonic_ratchet", "a_pull_write_never_resets_a_push_stamped_ratchet"]
    requires_convener_rebuttal: false
    source_refs: ["dialogue:1", "dialogue:3"]
  - id: f_boot_epoch_equal_replay
    severity: high
    posture: "replay ratchet correctness (RFC 'ignore <= recorded')"
    status: answered
    challenge: "DISCHARGED (BC6). boot_epoch is now strictly monotonic per write (next_boot_epoch with a max(_last+1, time_ns) guard), so the ratchet WHERE is a STRICT 'EXCLUDED.boot_epoch > gpu_slots.boot_epoch' (no '>='); an equal-epoch replay carries a value not greater than recorded and is refused — no mutable field moves and heartbeat_ts is not re-stamped. test_equal_epoch_replay_is_noop (PG) + test_ratchet_predicate_is_strict_gt (hermetic substring). The 'why >= not >' hole the attempt-2 revision opened is closed at its root by making the token per-write rather than per-boot. Confirmed by falsifier_2."
    affected_invariants: ["registry_ignores_writes_with_epoch_less_than_or_equal_to_recorded", "an_equal_epoch_replay_is_a_no_op"]
    requires_convener_rebuttal: false
    source_refs: ["dialogue:1", "dialogue:3"]
  - id: f_gpu_uuid_mismatch_no_requarantine
    severity: high
    posture: "measured-not-declared / Pillar 4 quarantine"
    status: answered
    challenge: "DISCHARGED (BC7). probe_streak resets to 1 (if alive) and status -> 'unverified' when gpu_slots.gpu_uuid and EXCLUDED.gpu_uuid are both non-NULL and differ; the carry-forward arm keeps 'routable' only on a matching/unknown uuid. A hot-swapped alive card can no longer inherit the prior streak. test_uuid_mismatch_resets_streak_and_demotes (hermetic) + test_hot_swap_demotes_to_unverified (PG). The pull-only no-uuid swap is correctly scoped to Pillar 6 / Q5. Confirmed by falsifier_2."
    affected_invariants: ["a_changed_gpu_uuid_forces_re_quarantine", "routing_trust_is_measured_per_identity_not_inherited"]
    requires_convener_rebuttal: false
    source_refs: ["dialogue:1", "dialogue:3"]
  - id: f_puller_lease_ttl_ageout
    severity: medium
    posture: "no-SPOF gate / failover timing"
    status: answered
    challenge: "DISCHARGED (BC3). PULLER_LEASE_TTL = 15 s, pinned strictly < the 45 s live_slots/routable_slots staleness window and stated against it; test_puller_failover_no_ageout expires the holder's lease, advances past the failover gap, and asserts the standby acquires within TTL and no node leaves routable_slots/live_slots. Confirmed by falsifier_2."
    affected_invariants: ["puller_failover_completes_before_any_live_slot_ages_out"]
    requires_convener_rebuttal: false
    source_refs: ["dialogue:1", "dialogue:3"]
  - id: f_driver_lease_client_clock
    severity: medium
    posture: "no-node-wall-clock / single-writer timing"
    status: answered
    challenge: "DISCHARGED (BC4). The per-node driver-lease freshness is evaluated server-side in the FETCH ('WHERE enabled AND (driven_by IS NULL OR now() >= lease_until)'); no puller-host clock enters the skip decision. test_fetch_freshness_uses_db_now_no_client_clock added; C12 restated to cover this decision. Confirmed by falsifier_2."
    affected_invariants: ["all_liveness_timing_decisions_use_the_db_clock_not_a_node_clock"]
    requires_convener_rebuttal: false
    source_refs: ["dialogue:1", "dialogue:3"]
  - id: f_fleet_meta_column_mismatch
    severity: low
    posture: "correctness / internal-consistency (no-SPOF puller-lease)"
    status: answered
    challenge: "DISCHARGED (BC5). The fleet_meta column is 'holder' verbatim in the 009 DDL, the Slice-2 CAS, and tests A/B/G/H, which run the real SQL against the real 009 DDL so a holder/puller divergence would fail the suite. Confirmed by falsifier_2."
    affected_invariants: ["puller_lease_cas_executes_on_the_declared_schema"]
    requires_convener_rebuttal: false
    source_refs: ["dialogue:1", "dialogue:3"]
  - id: f_peecee_ssh_retirement_delists
    severity: medium
    posture: "peecee pull-only gate / live-infra claim correctness"
    status: open
    challenge: "NEW (BC8, falsifier_1). The plan's Section-5 claim 'in the pull model peecee's liveness already comes from its HTTP endpoint (ollama-ondemand)' — and the Section-2-step-2 named apply-order step to 'retire the cross-host SSH nvidia-smi driver leg' — are false/harmful against the live code: ollama_ondemand_liveness fails closed ('if gpu_err is not None or stats.get(\"gpu_model\") is None: return False, None, None') before the /api/ps residency and VRAM-headroom branches, and gpu_stats is an nvidia-smi parser; so removing peecee's SSH gpu_cmd de-lists peecee (alive=False, no graduation, absent from routable_slots after Slice 4). Planned test K does not cover the no-SSH peecee path. NON-BLOCKING for the gate because the build's in-scope code is inert wrt peecee (it does not remove the gpu_cmd or change the liveness path) and the plan's own 'not load-bearing for any C-claim' hedge is correct, so the seven discharged C-claims and the in-build SQL are unaffected. Carried as binding constraint BC8 for the build/verify phase."
    affected_invariants: ["peecee_is_monitored_via_pull_with_no_fleet_code_or_creds", "peecee_de_lists_when_marker_owns_the_card", "the_build_does_not_ship_a_false_live_infra_claim_or_a_de_listing_operator_step"]
    requires_convener_rebuttal: false
    source_refs: ["dialogue:2"]
constraints:
  - id: BC8
    posture: "peecee pull-only liveness vs SSH-nvidia-smi retirement"
    severity: medium
    kind: policy
    binding: false
    source_finding: f_peecee_ssh_retirement_delists
    source_refs: ["dialogue:2"]
    text: "BINDING (carried into the build/verify gate; does NOT block the design gate from clearing because the in-build SQL is inert wrt peecee and the plan's 'not load-bearing for any C-claim' hedge holds). The build MUST resolve the peecee pull-only liveness contradiction by exactly ONE coherent path and MUST NOT ship the current false claim/instruction: EITHER (a) DO NOT retire peecee's cross-host SSH 'nvidia-smi' gpu_cmd in v1 — keep peecee on its existing, working SSH-via-pull liveness — DELETE the Section-2-step-2 SSH-retirement apply step, and correct Section 5 / Q5 so the 'zero-SSH pull-only' framing is narrowed (peecee is pull-only as to running no fleet code/creds on the node, but its load-aware liveness still consumes an nvidia-smi VRAM reading driven by the puller); OR (b) implement AND test a real HTTP-only peecee liveness path — probe_node must skip gpu_stats for an 'ollama-ondemand' node and derive resident/loadable state from the endpoint, recording the lower-trust endpoint-asserted VRAM per Pillar 6 / Q5 — proven by the discharging test falsifier_1 specifies: a peecee slot 0 row with probe_model='ollama-ondemand' and NO SSH/nvidia-smi gpu_cmd, endpoint stubbed serveable, asserts no SSH/nvidia-smi is invoked, alive=True when serveable with boot_epoch NULL and the row can graduate to 'routable', and alive=False (de-listed) when marker owns the card. This does NOT reopen BC2/BC6 — the boot_epoch ratchet is correct independent of the SSH step."
    verification:
      gate: "peecee-pull-liveness test: under the chosen model, peecee is still monitored and de-lists when marker owns the card; no false 'HTTP-only liveness' claim and no de-listing SSH-retirement step ship in the committed plan"
      expected_stage: "build_then_verify"
    final_review_required: true
  - id: BC1
    posture: "zero-touch-register gate (DISCHARGED — verify-carry)"
    severity: high
    kind: gate
    binding: true
    source_finding: f_zero_touch_lease_deadlock
    source_refs: ["dialogue:1", "dialogue:3"]
    text: "DISCHARGED in design (non-gating lease CAS + unconditional UPSERT, model c). Carried into the build's verify gate as a REQUIRED test: the composed Slice-1+3 push path for a node ABSENT from fleet_nodes registers ('unverified') and graduates to 'routable' after N probes, with C9 preserved (test_self_push_no_fleet_node_registers_and_graduates). The build MUST keep this test green."
    verification:
      gate: "composed-path test stays green: a no-fleet_nodes self-push registers and graduates; C9 preserved"
      expected_stage: "build_then_verify"
    final_review_required: true
  - id: BC2
    posture: "boot-epoch ratchet — NULL overwrite (DISCHARGED — verify-carry)"
    severity: high
    kind: gate
    binding: true
    source_finding: f_boot_epoch_null_overwrite
    source_refs: ["dialogue:1", "dialogue:3"]
    text: "DISCHARGED in design (COALESCE(EXCLUDED.boot_epoch, gpu_slots.boot_epoch)). Verify-carry: test_boot_epoch_survives_null_pull_write — a NULL (pull) write keeps the stored epoch and a strictly-stale write stays refused after any number of pull ticks. The build MUST keep this test green."
    verification:
      gate: "ratchet-survives-NULL test stays green"
      expected_stage: "build_then_verify"
    final_review_required: true
  - id: BC6
    posture: "boot-epoch ratchet — equal-epoch replay (DISCHARGED — verify-carry)"
    severity: high
    kind: gate
    binding: true
    source_finding: f_boot_epoch_equal_replay
    source_refs: ["dialogue:1", "dialogue:3"]
    text: "DISCHARGED in design (strictly-monotonic-per-write boot_epoch + STRICT '>' predicate). Verify-carry: test_equal_epoch_replay_is_noop (an equal-epoch replay with a different payload moves no mutable field and does not re-stamp heartbeat_ts) + test_ratchet_predicate_is_strict_gt (the UPSERT WHERE contains '>' and not '>='). The build MUST keep both green and MUST NOT reintroduce '>='."
    verification:
      gate: "equal-epoch-replay no-op test + strict-'>' assertion stay green"
      expected_stage: "build_then_verify"
    final_review_required: true
  - id: BC7
    posture: "Pillar-4 quarantine on identity change (DISCHARGED — verify-carry)"
    severity: high
    kind: gate
    binding: true
    source_finding: f_gpu_uuid_mismatch_no_requarantine
    source_refs: ["dialogue:1", "dialogue:3"]
    text: "DISCHARGED in design (probe_streak reset + status='unverified' on a non-NULL uuid mismatch; carry-forward only on match/unknown). Verify-carry: test_uuid_mismatch_resets_streak_and_demotes (hermetic) + test_hot_swap_demotes_to_unverified (PG). The build MUST keep these green."
    verification:
      gate: "hot-swap re-quarantine tests stay green"
      expected_stage: "build_then_verify"
    final_review_required: true
  - id: BC3
    posture: "no-SPOF failover timing (DISCHARGED — verify-carry)"
    severity: medium
    kind: policy
    binding: false
    source_finding: f_puller_lease_ttl_ageout
    source_refs: ["dialogue:1", "dialogue:3"]
    text: "DISCHARGED in design (PULLER_LEASE_TTL = 15 s < 45 s). Verify-carry: test_puller_failover_no_ageout proves a killed-holder failover keeps every live node in the directory. The build MUST keep the TTL < the staleness window and this test green."
    verification:
      gate: "failover-no-ageout test stays green; TTL < staleness window"
      expected_stage: "build_then_verify"
    final_review_required: false
  - id: BC4
    posture: "no-node-wall-clock / single-writer (DISCHARGED — verify-carry)"
    severity: medium
    kind: policy
    binding: false
    source_finding: f_driver_lease_client_clock
    source_refs: ["dialogue:1", "dialogue:3"]
    text: "DISCHARGED in design (server-side now() freshness in the FETCH). Verify-carry: test_fetch_freshness_uses_db_now_no_client_clock — the skip decision carries no client timestamp. The build MUST keep the predicate server-side and this test green."
    verification:
      gate: "server-side-freshness test stays green"
      expected_stage: "build_then_verify"
    final_review_required: false
  - id: BC5
    posture: "puller-lease internal-consistency (DISCHARGED — verify-carry)"
    severity: low
    kind: policy
    binding: false
    source_finding: f_fleet_meta_column_mismatch
    source_refs: ["dialogue:1", "dialogue:3"]
    text: "DISCHARGED in design (one 'holder' name across DDL/CAS/tests, run against the real 009 DDL). Verify-carry: tests A/B/G/H execute the real CAS/FETCH against the real 009 DDL so a column divergence fails the suite. The build MUST keep them green."
    verification:
      gate: "puller-lease CAS + driver FETCH execute against the real 009 DDL without a column error"
      expected_stage: "build_then_verify"
    final_review_required: false
branches:
  zero_touch_register_self_push: "cleared"
  boot_epoch_replay_ratchet_null_overwrite: "cleared"
  boot_epoch_replay_ratchet_equal_epoch: "cleared"
  gpu_uuid_change_forces_requarantine: "cleared"
  no_spof_puller_lease_cas: "cleared"
  no_spof_failover_no_ageout: "cleared"
  single_writer_no_node_wallclock: "cleared"
  peecee_pull_only_liveness_vs_ssh_retirement: "cleared_with_constraints"
  migration_009_additive_reversible: "cleared"
  status_quarantine_no_routing_until_slice4: "cleared"
  writer_before_reader_ordering: "cleared"
  prune_fix_fresh_selfpush_survives: "cleared"
  boot_epoch_not_alias_epoch: "cleared"
  hermetic_test_gate: "cleared"
  heartbeat_ts_db_stamped: "cleared"
  di_subprocess_boundary_and_live_infra_inertness: "cleared"
---

# COLLABORATION LEDGER — RFC 0002 Zero-touch node lifecycle (design gate, cycle 3)

author: adjudicator-claude-opus-4.8-003

- **RFC:** `docs/rfc/0002-zero-touch-node-lifecycle.md` (settled; prepared via `/adhd`)
- **Phase:** dialogue → synthesis (`adjudicate`), **cycle 3** (final budgeted iteration; re-falsification of the holder's cycle-3 revised plan)
- **Revised build plan under gate:** `dialogue/holder/BUILD_PLAN.md` (holder-claude-opus-4.8-**003**) — `dialogue:1`
- **Challenges read:** `dialogue/falsifier_1/FALSIFIER.md` (falsifier-openai-codex-gpt-5.5-**003**) — `dialogue:2`;
  `dialogue/falsifier_2/FALSIFIER.md` (falsifier-antigravity-gemini-**003**) — `dialogue:3`
- **Evidence basis:** the curated dialogue trajectory + the settled RFC only — no raw provider logs, no
  private diagnostics. There was **no separate holder rebuttal round**; the rebuttal surface is the
  revised plan's restated **C1–C12** + its **§8 discharge ledger**. Load-bearing source claims made by
  both parties (peecee's `ollama-ondemand` liveness path) were checked against the committed source the
  build realizes — that source is shared, auditable artifact, not a private diagnostic.
- **Prior records:** `dialogue/adjudicator/COLLABORATION_LEDGER_cycle_1.md` (verdict `needs_revision`,
  routed revision iteration 1) and `…_cycle_2.md` (verdict `needs_revision`, the **second and final**
  budgeted revision iteration; its binding notice made cycle 3 terminal **iff** a blocker among
  BC1/BC2/BC6/BC7 — or residual BC3–BC5 — still landed `landed_unrebutted`).

> **Provenance note (auditable).** The worktree the daemon anchored for this job is checked out at the
> **stale** commit `b1a6adc` (the cycle-2 ledger publication), whose tree still carries the **attempt-1**
> build plan and `-001` falsifier files. Per the packet's `revision_context` ("Review the CURRENT
> revision of the target"), I adjudicated the **attempt-3** artifacts read from the run-branch tip
> (`striatum/rfc-0002-design` @ `4c06885`; holder fan-in `8e87d85`), confirmed by author lines
> `holder-003` / `codex-003` / `gemini-003` and a `+480/-297` diff against attempt 1.

---

## VERDICT — `accept_with_findings`

**One-line reason:** The holder's cycle-3 revision **APPLIES** (not argues) all seven cycle-2
constraints as concrete SQL / control-flow / test changes — verified in the plan and **independently
confirmed by `falsifier_2`** — so the cycle-2 terminal-`reject` trigger (a blocker among BC1/BC2/BC6/BC7
still landing) **does not fire** and the build-correctness spine **survives falsification**.
`falsifier_1` drops every prior blocker and raises **one new, non-core objection** (peecee pull-only
liveness vs. the SSH-`nvidia-smi`-retirement step) that **lands** but does **not** break the build's
in-scope SQL; it is carried as **binding constraint BC8** for the build/verify phase. This is a
**clearing** verdict: the commit phase may publish, carrying BC8 (new) and the BC1–BC7 discharge tests
forward into the build's verify gate.

### The seven cycle-2 constraints are DISCHARGED (verified + confirmed)

| BC | Cycle-2 defect | Applied fix (verified in attempt-3 plan) | Confirmed by |
|----|----------------|------------------------------------------|--------------|
| **BC1** | zero-touch self-push deadlock | Slice-3 lease CAS made **non-gating**; `gpu_slots` UPSERT runs **unconditionally** (model c); composed Slice-1+3 test | falsifier_2 |
| **BC2** | NULL pull-write wipes the ratchet | `boot_epoch = COALESCE(EXCLUDED.boot_epoch, gpu_slots.boot_epoch)` | falsifier_2 |
| **BC6** | equal-epoch replay overwrites | `boot_epoch` strictly **monotonic per write**; ratchet `WHERE` is a **strict `>`**; equal-epoch replay is a no-op | falsifier_2 |
| **BC7** | gpu_uuid hot-swap bypass | `probe_streak` reset + `status='unverified'` on a **non-NULL uuid mismatch** | falsifier_2 |
| **BC3** | puller-lease TTL ≥ age-out | `PULLER_LEASE_TTL = 15 s` (`< 45 s`) + failover-no-ageout test | falsifier_2 |
| **BC4** | client wall-clock in skip | freshness predicate moved **server-side** into the `FETCH` | falsifier_2 |
| **BC5** | `fleet_meta` column mismatch | one name **`holder`** across DDL/CAS/tests, run against the real `009` DDL | falsifier_2 |

This is the convergence the gate was iterating toward: attempt 2 added prose and discharged none;
attempt 3 ships the SQL/logic/tests, and the diverse second falsifier independently certifies them.

### The one surviving objection — BC8 (peecee), landed, non-blocking

`falsifier_1` (codex-003) abandons BC1–BC7 and challenges the **peecee pull-only gate** against the
plan's own named **SSH-`nvidia-smi`-retirement** step:

- The plan (**§5** + **§2 step 2**) says retiring peecee's cross-host SSH `nvidia-smi` `gpu_cmd` is a
  harmless one-row `fleet_nodes` data step because *"peecee's liveness already comes from its HTTP
  endpoint (ollama-ondemand)."*
- The **live code refutes this**: `heartbeat_all.probe_node` calls `gpu_stats(n["gpu_cmd"])` **first**;
  `gpu_stats` shells `nvidia-smi` (local or SSH) and returns `_error`/no `gpu_model` if absent
  (`heartbeat.py:65–71`); `ollama_ondemand_liveness` **fails closed** —
  `if gpu_err is not None or stats.get("gpu_model") is None: return False, None, None`
  (`heartbeat.py:168`) — **before** the `/api/ps` residency check (`:175`) and the VRAM-headroom
  COLD/loadable branch (`:180`, which itself reads `stats["vram_free_mib"]`).
- ⇒ Executing the named step **de-lists peecee** (`alive=False`, never graduates, gone from
  `routable_slots` after Slice 4). Retaining SSH leaves the cross-host fan-out the plan claims to
  retire still in place. Planned **test K** does not exercise the no-SSH peecee path.

**Why this lands but does not block the gate.** The build's *code* deliverable (migration `009` + the
writer/consumer edits + the seven fixes) does **not** remove peecee's `gpu_cmd` and does **not** touch
`probe_node`/`gpu_stats`/`ollama_ondemand_liveness`; §4 keeps the build inert wrt live infra, so as code
it leaves peecee monitored exactly as today. The defect is in a **false narrative sentence** (§5) and a
**harmful operator apply-order instruction** (§2 step 2) — and the plan's own hedge, *"the in-build
ratchet is already correct without it … not load-bearing for any C-claim,"* is **true and survives**. So
the challenge is **partially self-rebutted**: the seven core C-claims hold; only the SSH-step's
safety/HTTP-liveness framing is refuted. It is therefore a **binding constraint (BC8)** the build must
discharge, not a reason to send a fully-converged plan back through a revision iteration the budget no
longer has.

**BC8 — minimal discharge (choose one), required at build/verify:**
- **(a)** Do **not** retire peecee's SSH `nvidia-smi` leg in v1 — keep peecee on its existing, working
  SSH-via-pull liveness; **delete** the §2-step-2 SSH-retirement step; **correct §5 / Q5** so the
  "zero-SSH pull-only" framing is narrowed (peecee runs no fleet code/creds on the node, but its
  load-aware liveness still consumes an `nvidia-smi` VRAM reading driven by the puller); **or**
- **(b)** Implement **and test** a real HTTP-only peecee liveness path (`probe_node` skips `gpu_stats`
  for an `ollama-ondemand` node and derives resident/loadable state from the endpoint, recording the
  lower-trust endpoint-asserted VRAM per Pillar 6 / Q5), proven by the discharging test `falsifier_1`
  specifies (no SSH/`nvidia-smi` invoked; `alive=True` & `boot_epoch` NULL & can graduate when the
  endpoint is serveable; `alive=False` when marker owns the card).

Neither path reopens BC2/BC6 — the `boot_epoch` ratchet is correct independent of the SSH step.

---

## Why `accept_with_findings` (and not the alternatives)

- **Not `reject`.** `reject` is reserved for an **undischargeable** defect / a design that cannot satisfy
  its own falsifiable gate. The cycle-2 terminal-`reject` trigger was *"a blocker among BC1/BC2/BC6/BC7
  (or residual BC3–BC5) still `landed_unrebutted`."* That trigger is **precisely not met** — all seven
  are discharged and confirmed. The remaining BC8 is bounded and build-dischargeable, and the design
  satisfies its gate. A `reject` here would be **untruthful**.
- **Not `needs_revision`.** The substantive gate has **converged** (7/7 discharged + a full clear from
  one falsifier), and the revision budget (`max_iterations` 2) was spent at cycle 2. The single surviving
  objection is a **non-core, out-of-build, dischargeable** narrative/operator-step defect that the plan
  itself flags as non-load-bearing — exactly the kind of residual that becomes a **binding finding**, not
  a re-gate of a sound plan.
- **`accept_with_findings`** is the truthful clearing verdict: the plan **survives falsification** on
  every material build-correctness dimension; the one landed objection (**BC8**) is carried forward as a
  binding constraint the build MUST discharge, alongside the **BC1–BC7 discharge tests** (design-level
  proofs that become build-level requirements).

---

## What survived falsification (the sound spine — keep it through the build)

- **C1** — migration number `009` is correct; the RFC's "Migration 006" is stale (006/007/008 = peecee
  dense flip / RFC-0001 leases / RFC-0003 epoch).
- **C2** — `009` is purely additive, reversible, behavior-neutral until Slice 4.
- **C4** — `status` quarantine changes no routing until the consumer slice; **C5** — writer-before-reader
  ordering strands no node; **C3-PRUNE** — the stale-only PRUNE preserves a fresh self-push row (now
  reachable, because **BC1** makes registration unconditional).
- **C7** — `boot_epoch` and `epoch` never alias (the `epoch` CASE is byte-unchanged); **C11** — hermetic
  default green, every DB-backed test guarded verbatim like `test_leases_pg.py`/`test_epoch_pg.py` and run
  against the real `009` DDL; **C12** — every liveness/lease/replay timing decision uses the DB clock (the
  new `boot_epoch` ordering token is node-sourced **by design** and only ever refuses a node's **own**
  stale replay).
- The **`di --json` subprocess boundary**, **peecee runs no fleet code/creds on the node**, and the
  **§4 live-infra inertness** of the build.

`C3`, `C6`, `C8`, `C9`, `C10`, `C12` were **restated** by the holder to match what is built and now hold;
the peecee bullet's §5/Q5 framing is the one piece that must be corrected per **BC8**.

---

## Handoff

- **Commit phase (cleared):** publish the committed plan; **fold in BC8** (correct §5/§2-step-2/Q5 per
  option (a) or (b)) and **carry the BC1–BC7 discharge tests** into the build's verify gate as required,
  must-stay-green proofs.
- **Build + verify:** keep `python3 -m pytest tests/ -q` hermetic-green; run the PG-guarded suite against
  an ephemeral `GPU_FLEET_TEST_DB` exactly as the plan specifies; **discharge BC8** with the peecee
  liveness test before the build's final review (`final_review_required: true`).
- **Do not re-open** the RFC's settled design (pull-first peer-runnable driver; push opt-in for trusted
  Linux nodes only; registration = first heartbeat; measured-not-declared quarantine→graduate;
  `boot_epoch` ⟂ `epoch`).
