---
schema_version: "striatum.collaboration_ledger.v1.1"
artifact_kind: "collaboration_ledger"
shape: "falsification_gate"
author: adjudicator-claude-opus-4.8-002
workflow: "rfc-0002-design"
run_id: "run_aa1f69f24463027c2466994e9f655b08"
cycle: 2
topic: "RFC 0002 — Zero-touch node lifecycle: re-gate the REVISED falsifiable build plan after cycle-1 needs_revision"
participants: ["holder", "falsifier_1", "falsifier_2", "adjudicator"]
verdict: "needs_revision"
rationale: "Cycle-2 re-falsification of the holder's REVISED plan (dialogue/holder/BUILD_PLAN.md, holder-claude-opus-4.8-002, run-branch tip 5bb63d1) against the two re-issued challenges (falsifier-openai-codex-gpt-5.5-002; falsifier-antigravity-gemini-002), adjudicated from the curated dialogue trajectory + the settled RFC only — no raw provider logs or private diagnostics. CONTEXT THAT DRIVES THE VERDICT: cycle-1 returned needs_revision and routed revision iteration 1 (revision.cycle_routed, iteration 1 / max_iterations 2) with a minimal clearing diff of five concrete repairs (BC1-BC5). The holder used that cycle but discharged NONE of the five mechanical repairs: the only substantive edits (git diff 2918657->5bb63d1) are (a) three new explanatory sub-bullets under Slice-1 Change B reframing the boot-epoch ratchet as 'defense-in-depth, not the primary guarantee' with a 'why >= not >' justification, (b) a new load-bearing claim C6a, and (c) a Section-5 bullet stating the cross-host SSH retirement is an operator fleet_nodes DATA step. The Slice-3 CAS-before-UPSERT (BC1), the SET clause boot_epoch=EXCLUDED.boot_epoch with no COALESCE (BC2), the unpinned puller-lease TTL (BC3), the Python-side driver-lease freshness filter (BC4), and the fleet_meta.puller-vs-CAS-holder column mismatch (BC5) are ALL byte-unchanged from the refuted attempt-1 plan. THE GATE CANNOT CLEAR, and this is not discretionary: a clearing verdict (accept/accept_with_findings) requires every landed challenge to be rebutted in the trajectory; the re-falsification records FIVE carried-and-still-unrebutted challenges plus TWO new landed challenges, several on named falsifiable-gate items. Carried, still landing: (BC1, gemini #6 / corroborates the cycle-1 codex whole-challenge) the central zero-touch-register gate still fails for the exact node it names — Slice 3 makes a self-pushing node CAS-acquire its per-node driver-lease on fleet_nodes BEFORE the UPSERT and yield on CAS failure, but a zero-touch self-pusher has NO fleet_nodes row, the CAS updates zero rows, the writer yields, the first gpu_slots row is never created, and the directory-driven puller (FETCH reads only enabled fleet_nodes rows) never rescues it; the proposed test_self_register_no_fleet_node_graduates still exercises only the raw Slice-1 UPSERT, never the composed Slice-1+3 push entry path. The holder never engaged this across two attempts. landed_unrebutted. (BC2, gemini #2) Change B's SET boot_epoch=EXCLUDED.boot_epoch still lets a puller (EXCLUDED.boot_epoch NULL, because HTTP probes carry no boot identity) overwrite a self-pusher's stored integer with NULL during the plan's OWN documented push->pull lease-lapse flip, after which gpu_slots.boot_epoch IS NULL admits any later strictly-stale write. The holder's new 'defense-in-depth' prose (C6a) does NOT discharge this: it concedes the NULL arm 'lets the write through' and relies on an out-of-BUILD operator step (retiring the SSH driver) to close the window, while the primary guarantee it leans on — the per-node driver-lease — is itself broken (BC1) and wall-clock-dependent (BC4). The one-token fix (COALESCE(EXCLUDED.boot_epoch, gpu_slots.boot_epoch)) and its PG test are still absent. landed_unrebutted (prose argued, SQL unrepaired). (BC5, gemini #1) Slice-0 DDL still declares fleet_meta.puller while the Slice-2 CAS still SETs/matches/RETURNs holder, so the puller-lease CAS still errors 'column \"holder\" does not exist' on Slice-2 deploy, refuting C8. Mechanical, byte-unchanged. landed_unrebutted. (BC3, gemini #5) the puller-lease deadman TTL is still unpinned and unconstrained below the 45s live_slots/routable_slots staleness window; a TTL >= 45s lets live slots age out during failover. landed_unrebutted (the cycle-1 'rebutted-but-unsupported' rebuttal was not strengthened). (BC4, gemini #4) the per-node driver-lease freshness is still a Python-side filter over lease_until with no server-side now() predicate and no no-wall-clock test; a skewed puller clock double-writes a still-leased node or skips a lapsed one. landed_unrebutted. NEW, introduced or exposed by the revision: (BC6, codex whole-challenge) the holder's OWN newly-added 'why >= not >' justification opens an equal-epoch replay hole: because boot_epoch is a per-boot CONSTANT and the comparator is >=, a resurrected/replayed writer that re-presents the SAME boot_epoch with a STALE payload (alive=false, an old served_model, an older gpu_uuid) takes the ON CONFLICT DO UPDATE path, mutates the whole row, AND re-stamps heartbeat_ts=now() so the replay is no longer stale to the DB. The RFC's rule is 'ignore epoch <= recorded'; the plan only refuses strictly-lower, so equal-epoch replays still overwrite live registry state. The build has no equal-epoch no-op test. This directly refutes the holder's C6/C6a >= defense. landed_unrebutted. (BC7, gemini #3) a GPU hot-swap (gpu_uuid changes) bypasses re-quarantine: probe_streak resets ONLY on NOT EXCLUDED.alive, so a different-but-alive GPU increments the streak instead of resetting it; the status CASE falls through the matching-UUID short-circuit but then satisfies the streak>=N graduation arm, so the slot stays routable under the NEW uuid without ever re-entering quarantine — violating Pillar 4 'measured, not declared'. C10 is false for the uuid-mismatch case. landed_unrebutted. WHY needs_revision AND NOT reject: every one of the seven defects is mechanically dischargeable in one cycle (BC1: pick one arbitration model so a no-fleet_nodes self-pusher registers, or scope it out and narrow C3/gate-D, + a composed Slice-1+3 test; BC2: COALESCE + a no-wipe PG test; BC3: pin TTL < 45s + a no-age-out test; BC4: push the freshness predicate server-side + a no-client-timestamp test; BC5: one column rename across DDL/CAS/tests; BC6: change the non-NULL predicate to '>' OR add a provable equality no-op path that touches nothing and does not refresh heartbeat_ts, + an equal-epoch replay test; BC7: reset probe_streak and demote to unverified when gpu_slots.gpu_uuid IS DISTINCT FROM EXCLUDED.gpu_uuid, + a hot-swap test). The DESIGN (the settled RFC) can still satisfy its own falsifiable gate — none of these is an undischargeable defect — so reject (reserved for an undischargeable defect / a design that cannot satisfy its own gate) would be too strong and untruthful. The plan's SPINE again survives falsification and MUST be preserved: C1 (migration number 009 is correct; the RFC's 'Migration 006' is stale), C2 (009 is purely additive/reversible/behavior-neutral until Slice 4 — the puller-CAS column bug and the SET-clause bug are writer/Slice-2 code defects, not violations of 009's additivity), C4 (status quarantine changes no routing until the consumer slice), C5 (writer-before-reader ordering strands no node), C3-PRUNE (the stale-only PRUNE fix preserves a fresh row — sound given a row exists; upstream-gated by BC1), C7 (boot_epoch and epoch never alias), C11 (hermetic default green, every DB-backed test guarded verbatim like test_leases_pg.py/test_epoch_pg.py), C12 (heartbeat_ts DB-stamped — for heartbeat_ts; the new lease/replay timing decisions extend to BC4/BC6), the di --json subprocess boundary, peecee-pull-only, and the live-infra inertness of Section 4. PROCESS NOTE (binding on the next cycle): this is the SECOND and FINAL budgeted revision iteration (revision iteration 2 of max_iterations 2). Iteration 1 discharged none of BC1-BC5 and the re-falsification surfaced two further landed defects, so the plan is not yet converging. If the next re-falsification still finds these seven (or any blocker among them) landed_unrebutted, the honest terminal outcome becomes reject — not because any single defect is intrinsically undischargeable, but because the gate's revision budget will have been exhausted without the plan surviving falsification. The minimal clearing diff is small and fully enumerated in constraints[]; the holder must APPLY the SQL/logic/test changes, not re-argue them."
entries:
  - kind: claim
    by: holder
    refs: ["dialogue:1"]
    text: "Holder REVISED build plan (attempt 2, holder-claude-opus-4.8-002). Same five-slice spine as attempt 1 (DB migration 009 -> heartbeat graduation writer + boot-epoch ratchet + PRUNE fix -> global puller-lease -> per-node driver-lease -> consumer status gate; RLS deferred; migration number corrected to 009). The ONLY substantive revision edits vs attempt 1 are prose, not mechanics: (a) Slice-1 Change B gains three sub-bullets — 'what value is stamped, and by whom' (boot_epoch is a per-boot monotonic scalar set only by push/self-report via --boot-epoch; pull probes leave it NULL because HTTP carries no boot identity), 'why >= not >' (boot_epoch is constant within a boot, so >= must accept the equal value consecutive same-boot pushes carry), and 'Honest scope (defense-in-depth, not the primary guarantee)' (the per-node driver-lease is the primary single-writer guarantee; the ratchet is a secondary guard; the NULL-admitted residual window is closed by an operator step retiring the cross-host SSH driver, not by SQL); (b) a new claim C6a restating that defense-in-depth framing; (c) a Section-5 bullet declaring the SSH nvidia-smi retirement an operator fleet_nodes DATA step, not a code slice. The Slice-3 CAS-before-UPSERT push path, the SET boot_epoch=EXCLUDED.boot_epoch clause, the unpinned puller-lease TTL, the Python-side driver-lease skip filter, and the fleet_meta.puller vs CAS-holder column names are all byte-unchanged from the refuted attempt-1 plan."
  - kind: challenge
    by: falsifier_1
    refs: ["dialogue:2"]
    correspondence: landed_unrebutted
    text: "(codex attempt 2, whole challenge) C6/C6a/Pillar-5 challenged on a NEW axis the revision itself opened — the EQUAL-epoch replay. The holder's added 'why >= not >' justification admits the comparator accepts equal boot_epoch values. But the RFC's load-bearing rule is 'ignore any write whose epoch is <= the one on record' (boot_id+seq), so equal-epoch writes ARE replays and must be ignored. Counterexample (post-Slice-1): a row has boot_epoch=42, alive=true, status=routable, fresh heartbeat_ts; a resurrected SSH driver / stale second writer / replayed heartbeat re-presents the same (node,endpoint_url,slot_id) with boot_epoch=42 but a STALE payload (alive=false, old served_model, older gpu_uuid). Under '>=' Postgres takes ON CONFLICT DO UPDATE: alive/status/probe_streak/measured fields/note and heartbeat_ts=now() all move on the replay, and the re-stamped heartbeat_ts means the replay is no longer stale to the DB — the row can demote, drop from routable_slots, or churn the RFC-0003 epoch. The plan has NO equal-epoch no-op test (the C6 refutation target only checks a strictly-lower epoch). The holder's idempotent-retry rationale fails because the conflict path cannot distinguish an identical retry from a same-epoch stale-payload replay and updates the whole row regardless. UNREBUTTED -> BC6: change the non-NULL predicate to '> ' OR add a provable equality no-op branch (every mutable field identical, heartbeat_ts not refreshed) + an equal-epoch replay PG test. This refutes the holder's explicit '>=' design defense."
  - kind: challenge
    by: falsifier_2
    refs: ["dialogue:3"]
    correspondence: landed_unrebutted
    text: "(gemini attempt 2, #1) C8 fleet_meta column-name mismatch — UNCHANGED from cycle 1: Slice-0 DDL still creates fleet_meta with `puller TEXT` while the Slice-2 CAS still SETs/matches/RETURNs `holder` (UPDATE fleet_meta SET holder=:me ... WHERE ... OR holder=:me RETURNING holder). The CAS errors `column \"holder\" does not exist` on Slice-2 deploy, breaking the puller and refuting C8 ('a single puller is unaffected'). The holder did not reconcile the two SQL fragments in the revision. landed_unrebutted -> BC5 (carried): align DDL + CAS + tests A/B on one name and run the real CAS against the real 009 DDL."
  - kind: challenge
    by: falsifier_2
    refs: ["dialogue:3"]
    correspondence: landed_unrebutted
    text: "(gemini attempt 2, #2) C6/Pillar-5 boot-epoch NULL pull-overwrite — UNCHANGED from cycle 1: SET boot_epoch=EXCLUDED.boot_epoch still overwrites a stored non-NULL boot_epoch with NULL whenever the puller (EXCLUDED.boot_epoch NULL) writes a row a self-pusher previously stamped — the plan's OWN documented push->pull lease-lapse flip. After that, gpu_slots.boot_epoch IS NULL admits any later strictly-stale write, re-opening the resurrected-stale-writer split-brain. The holder's new C6a 'defense-in-depth' framing does not discharge it: C6a concedes the NULL arm 'lets the write through' and pushes the closure onto an out-of-BUILD operator step (retiring the SSH driver), while the 'primary' guarantee it relies on (the per-node driver-lease) is itself broken for zero-touch (BC1) and wall-clock-dependent (BC4). The one-token fix is still absent. landed_unrebutted -> BC2 (carried): SET boot_epoch=COALESCE(EXCLUDED.boot_epoch, gpu_slots.boot_epoch) + a PG no-wipe test."
  - kind: challenge
    by: falsifier_2
    refs: ["dialogue:3"]
    correspondence: landed_unrebutted
    text: "(gemini attempt 2, #3) C10/Pillar-4 GPU-identity hot-swap bypasses quarantine — NEW: the status CASE short-circuits on a MATCHING gpu_uuid, but on a MISMATCH it falls through; meanwhile probe_streak = CASE WHEN EXCLUDED.alive THEN gpu_slots.probe_streak+1 ELSE 0 END resets only on NOT alive. So a node that reboots with a DIFFERENT GPU (gpu_uuid changes) but is alive keeps its already-high streak, the fall-through reaches the streak>=N graduation arm, and the slot stays `routable` under the new uuid WITHOUT ever re-entering quarantine. A hot-swapped/false-identity card is routed on inherited trust — the exact 'measured, not declared' guarantee Pillar 4 exists to enforce. C10 ('carry-forward only on matching UUID + passing probe') is false for the mismatch path. landed_unrebutted -> BC7 (new): when gpu_slots.gpu_uuid IS DISTINCT FROM EXCLUDED.gpu_uuid, reset probe_streak (to 1 if alive) and set status to unverified (not routable) + a hot-swap PG/hermetic test."
  - kind: challenge
    by: falsifier_2
    refs: ["dialogue:3"]
    correspondence: landed_unrebutted
    text: "(gemini attempt 2, #4) C9/C12 client wall-clock in the per-node driver-lease skip — UNCHANGED from cycle 1: Slice 3 still describes the skip as a Python-side 'FETCH/skip honoring driven_by + lease_until' with no stated server-side now() comparison and no no-wall-clock test. A puller clock skewed vs the DB either treats a fresh lease as expired and double-writes the node (refuting C9) or skips a lapsed one and leaves it unmonitored. C12 is proven only for heartbeat_ts (test L). landed_unrebutted -> BC4 (carried): push the freshness predicate into the FETCH SQL (WHERE enabled AND (driven_by IS NULL OR now() >= lease_until)) + a no-client-timestamp test."
  - kind: challenge
    by: falsifier_2
    refs: ["dialogue:3"]
    correspondence: landed_unrebutted
    text: "(gemini attempt 2, #5) C8/No-SPOF puller-lease TTL vs 45s age-out — UNCHANGED from cycle 1: Slice 2 still says only 'deadman TTL identical in shape to RFC-0001's slot lease' and pins no value below the 45s live_slots/routable_slots staleness window; if TTL >= 45s the standby waits out the lease while no heartbeats are written and live slots age out before failover completes, violating the gate's 'fleet does not age out'. landed_unrebutted (the cycle-1 'rebutted-but-unsupported' rebuttal was not strengthened) -> BC3 (carried): pin TTL strictly < 45s (e.g. <=15s) and turn test B into a real failover-no-age-out proof."
  - kind: challenge
    by: falsifier_2
    refs: ["dialogue:3"]
    correspondence: landed_unrebutted
    text: "(gemini attempt 2, #6) C3/zero-touch-register self-push deadlock — UNCHANGED from cycle 1 and CORROBORATES the cycle-1 codex whole-challenge: a self-pushing node with no fleet_nodes row CAS-acquires on fleet_nodes (Slice 3), the update affects zero rows, it yields, the gpu_slots write never occurs, and the puller skips it (not in fleet_nodes) -> the node never registers. The central 'registration = first heartbeat; fleet_nodes is optional, not a prerequisite' fact (Pillar 3) requires this to work; the revision left Slice 3 and test D byte-unchanged. landed_unrebutted -> BC1 (carried, blocking): choose ONE arbitration model that lets a no-fleet_nodes self-pusher register with C9 preserved (or scope it out and narrow C3/gate-D) + a composed Slice-1+3 registration test."
  - kind: rebuttal
    by: holder
    refs: ["dialogue:1"]
    text: "Holder in-plan defenses (attempt 2; there was no separate holder rebuttal round this cycle — the rebuttal surface is the revised plan's C1-C12 + new C6a). SURVIVING/unchallenged spine stands: C1 (009 correct, RFC '006' stale), C2 (009 additive/reversible/behavior-neutral until Slice 4), C4 (status changes no routing until consumer slice), C5 (writer-before-reader strands no node), C7 (boot_epoch ⟂ epoch), C11 (hermetic default green, PG tests guarded), C12 (heartbeat_ts DB-stamped). REFUTED/INSUFFICIENT this cycle: C6/C6a — the '>=' justification (defended as a deliberate per-boot-scalar realization) is refuted by the equal-epoch replay (BC6), and the 'defense-in-depth' framing does not discharge the NULL pull-overwrite (BC2) because it leans on a broken primary lease (BC1/BC4) and an out-of-build operator step; C8 still breaks on the puller-CAS column mismatch (BC5); C9 broken by both the zero-touch deadlock (BC1) and the wall-clock skip (BC4); C10 false for the gpu_uuid-mismatch hot-swap (BC7); C3 still has no real test for the composed no-fleet_nodes path (BC1). The revision added prose and a peripheral SSH-retirement data-step note but applied none of the cycle-1 BC1-BC5 mechanical repairs."
findings:
  - id: f_zero_touch_lease_deadlock
    severity: high
    posture: "correctness-of-the-falsifiable-gate / zero-touch register"
    status: open
    challenge: "Slice 3's CAS-acquire-on-fleet_nodes-before-UPSERT + yield-on-failure still makes the central 'zero-touch register' gate fail for the exact node it names: a self-pushing node with no fleet_nodes row CASes zero rows, yields, never writes its first gpu_slots row, and the directory-driven puller never rescues it. Byte-unchanged across two attempts; raised again by gemini #6 (corroborating the cycle-1 codex whole-challenge). The proposed test still covers only the raw Slice-1 UPSERT, never the composed Slice-1+3 path. landed_unrebutted -> BLOCKING repair BC1, the primary reason the gate cannot clear."
    affected_invariants: ["registration_equals_first_heartbeat", "zero_touch_register_no_prior_fleet_nodes_row", "push_and_pull_never_both_write_a_node"]
    requires_convener_rebuttal: true
    source_refs: ["dialogue:2", "dialogue:3"]
  - id: f_boot_epoch_null_overwrite
    severity: high
    posture: "split-brain / replay ratchet correctness"
    status: open
    challenge: "SET boot_epoch=EXCLUDED.boot_epoch still lets a NULL-epoch puller wipe a self-pusher's stored boot_epoch during the documented push->pull lease-lapse flip; the row then satisfies gpu_slots.boot_epoch IS NULL and admits any strictly-stale write. The holder's new 'defense-in-depth' prose (C6a) argues but does not repair: it concedes the NULL arm lets the write through and defers closure to an out-of-build operator SSH-retirement step, while leaning on a primary lease that is itself broken (BC1) and wall-clock-dependent (BC4). landed_unrebutted -> BLOCKING repair BC2. Fix: COALESCE(EXCLUDED.boot_epoch, gpu_slots.boot_epoch) + a writer-side no-wipe PG test."
    affected_invariants: ["boot_epoch_is_a_one_way_monotonic_ratchet", "a_pull_write_never_resets_a_push_stamped_ratchet"]
    requires_convener_rebuttal: true
    source_refs: ["dialogue:3"]
  - id: f_boot_epoch_equal_replay
    severity: high
    posture: "replay ratchet correctness (RFC 'ignore <= recorded')"
    status: open
    challenge: "NEW this cycle, opened by the holder's own added 'why >= not >' justification: because boot_epoch is a per-boot CONSTANT and the comparator is '>=', a resurrected/replayed writer that re-presents the SAME boot_epoch with a STALE payload takes ON CONFLICT DO UPDATE, mutates the whole row, and re-stamps heartbeat_ts=now() (so the replay is no longer stale to the DB). The RFC's rule is 'ignore epoch <= recorded'; the plan only refuses strictly-lower, leaving equal-epoch replays able to overwrite live registry state. No equal-epoch no-op test exists. Refutes the holder's explicit '>=' defense. landed_unrebutted -> BLOCKING repair BC6. Fix: non-NULL predicate '> ' OR a provable equality no-op branch (all mutable fields identical, heartbeat_ts not refreshed) + an equal-epoch replay PG test."
    affected_invariants: ["registry_ignores_writes_with_epoch_less_than_or_equal_to_recorded", "an_equal_epoch_replay_is_a_no_op"]
    requires_convener_rebuttal: true
    source_refs: ["dialogue:2"]
  - id: f_gpu_uuid_mismatch_no_requarantine
    severity: high
    posture: "measured-not-declared / Pillar 4 quarantine"
    status: open
    challenge: "NEW this cycle: probe_streak resets only on NOT alive, and the status CASE short-circuits only on a MATCHING gpu_uuid. A node that reboots with a DIFFERENT (alive) GPU keeps its already-high streak, falls through to the streak>=N graduation arm, and stays 'routable' under the new uuid without re-entering quarantine. A hot-swapped / false-identity card is routed on inherited trust. C10 is false for the gpu_uuid-mismatch path. landed_unrebutted -> BLOCKING repair BC7. Fix: when gpu_slots.gpu_uuid IS DISTINCT FROM EXCLUDED.gpu_uuid, reset probe_streak (to 1 if alive) and set status='unverified' (not routable) + a hot-swap test."
    affected_invariants: ["a_changed_gpu_uuid_forces_re_quarantine", "routing_trust_is_measured_per_identity_not_inherited"]
    requires_convener_rebuttal: true
    source_refs: ["dialogue:3"]
  - id: f_fleet_meta_column_mismatch
    severity: low
    posture: "correctness / internal-consistency (no-SPOF puller-lease)"
    status: open
    challenge: "Slice-0 DDL column fleet_meta.puller vs Slice-2 CAS column `holder` — the CAS errors 'column holder does not exist' and breaks the puller on Slice-2 deploy, refuting C8. Byte-unchanged from cycle 1; the revision did not reconcile the fragments. landed_unrebutted -> BC5. Align DDL + CAS + tests A/B on one name and run the real CAS against the real 009 DDL."
    affected_invariants: ["puller_lease_cas_executes_on_the_declared_schema"]
    requires_convener_rebuttal: false
    source_refs: ["dialogue:3"]
  - id: f_puller_lease_ttl_ageout
    severity: medium
    posture: "no-SPOF gate / failover timing"
    status: open
    challenge: "The puller-lease deadman TTL is still unpinned and unconstrained below the 45s directory staleness window, so a TTL >= 45s lets live slots age out during failover, violating 'fleet does not age out'. The cycle-1 unsupported rebuttal was not strengthened. landed_unrebutted -> BC3: pin TTL strictly < 45s (e.g. <=15s) and make test B prove no age-out across the failover gap."
    affected_invariants: ["puller_failover_completes_before_any_live_slot_ages_out"]
    requires_convener_rebuttal: false
    source_refs: ["dialogue:3"]
  - id: f_driver_lease_client_clock
    severity: medium
    posture: "no-node-wall-clock / single-writer timing"
    status: open
    challenge: "Slice 3's per-node skip is still a Python-side filter over lease_until with no stated server-side now() evaluation and no no-wall-clock test; a skewed puller clock double-writes a still-leased node or skips a lapsed one, violating C12/C9. landed_unrebutted -> BC4: evaluate freshness server-side in the FETCH SQL (now() >= lease_until) + a no-client-timestamp test (the driver-lease analog of test_lease_no_consumer_clock.py)."
    affected_invariants: ["all_liveness_timing_decisions_use_the_db_clock_not_a_node_clock"]
    requires_convener_rebuttal: false
    source_refs: ["dialogue:3"]
constraints:
  - id: BC1
    posture: "zero-touch-register gate"
    severity: high
    kind: gate
    binding: true
    source_finding: f_zero_touch_lease_deadlock
    source_refs: ["dialogue:2", "dialogue:3"]
    text: "BLOCKING repair (carried unrepaired from cycle 1; the primary reason the gate cannot clear). Resolve the Slice-3 CAS-before-UPSERT deadlock so a self-pushing node with NO pre-existing fleet_nodes row can still complete registration = first heartbeat, by choosing exactly ONE coherent arbitration model and stating how C9 still holds for it: (a) the per-node driver-lease is NOT stored exclusively on fleet_nodes; OR (b) the push path ATOMICALLY creates the fleet_nodes arbitration row as part of zero-touch registration (test the create is atomic wrt the single-writer rule); OR (c) the first registering UPSERT proceeds unconditionally and the driver-lease governs only ONGOING contention once both writers can reach the node; OR (d) explicitly scope no-fleet_nodes self-push OUT and narrow the 'zero-touch register' gate + C3 to pull-only. RESTATE C3/C9/gate-D to match what is built. REQUIRED test: execute the COMPOSED post-Slice-1+3 push path for a node absent from fleet_nodes with probes stubbed passing, and assert a gpu_slots row appears 'unverified' and graduates to 'routable' after N probes (or, under (d), a test pinning the narrowed pull-only scope). The current test_self_register_no_fleet_node_graduates (raw Slice-1 UPSERT only) does NOT discharge this."
    verification:
      gate: "composed-path test: a self-push for a node with no fleet_nodes row registers (gpu_slots row appears unverified and graduates), with C9 preserved — or the gate is explicitly narrowed to pull-only and tested as such"
      expected_stage: "design_revision_then_build_verify"
    final_review_required: true
  - id: BC2
    posture: "boot-epoch replay-ratchet gate (NULL overwrite)"
    severity: high
    kind: gate
    binding: true
    source_finding: f_boot_epoch_null_overwrite
    source_refs: ["dialogue:3"]
    text: "BLOCKING repair (carried unrepaired from cycle 1; prose reframing is not a fix). Slice-1 Change B MUST preserve a stored non-NULL boot_epoch when the incoming write supplies NULL: change the SET to boot_epoch = COALESCE(EXCLUDED.boot_epoch, gpu_slots.boot_epoch) (or an equivalent that never lowers/erases a recorded epoch), so a puller (or any NULL-epoch writer) cannot wipe a self-pusher's ratchet during the documented push->pull lease-lapse flip. RESTATE C6/C6a to cover the SET-overwrite path; the 'defense-in-depth' framing may stay, but it MUST NOT be the sole defense — the in-build SQL must not self-erase the ratchet. REQUIRED PG test: stamp gpu_slots.boot_epoch=K via a push write; have the puller UPSERT the same (node,slot) with boot_epoch NULL and assert boot_epoch stays K; then assert a strictly-stale (< K) write is still refused after any number of pull ticks."
    verification:
      gate: "ratchet-survives-NULL test: a NULL-epoch (puller) write does not erase a stored boot_epoch, and a strictly-stale write is still refused after any number of pull ticks"
      expected_stage: "design_revision_then_build_verify"
    final_review_required: true
  - id: BC6
    posture: "boot-epoch replay-ratchet gate (equal-epoch replay)"
    severity: high
    kind: gate
    binding: true
    source_finding: f_boot_epoch_equal_replay
    source_refs: ["dialogue:2"]
    text: "BLOCKING repair (NEW; opened by the revision's own '>=' justification). The ratchet MUST refuse an equal-epoch replay that carries a stale or different mutable payload, per the RFC's 'ignore epoch <= recorded'. EITHER (a) change the non-NULL predicate to EXCLUDED.boot_epoch > gpu_slots.boot_epoch and carry within-boot liveness on heartbeat_ts only (do NOT rely on boot_epoch equality to refresh the row); OR (b) keep '>=' but add a provable equality NO-OP branch that, when EXCLUDED.boot_epoch = gpu_slots.boot_epoch, performs no mutation of any mutable heartbeat/capability/status field and does NOT advance heartbeat_ts unless every mutable field is byte-identical. RESTATE C6 so the refutation target includes the equal-epoch case. REQUIRED PG test: stamp boot_epoch=K, then replay the same primary key with boot_epoch=K and deliberately different alive/served_model/gpu_uuid/probe_ms/note, and assert the mutable fields and heartbeat_ts do not move."
    verification:
      gate: "equal-epoch-replay test: a same-boot_epoch write carrying a different mutable payload is a no-op (mutable fields and heartbeat_ts unchanged); a strictly-greater epoch is still accepted"
      expected_stage: "design_revision_then_build_verify"
    final_review_required: true
  - id: BC7
    posture: "measured-not-declared / Pillar 4 quarantine on identity change"
    severity: high
    kind: gate
    binding: true
    source_finding: f_gpu_uuid_mismatch_no_requarantine
    source_refs: ["dialogue:3"]
    text: "BLOCKING repair (NEW). A GPU identity change MUST force re-quarantine: when gpu_slots.gpu_uuid IS DISTINCT FROM EXCLUDED.gpu_uuid, the UPSERT MUST reset probe_streak (to 1 if EXCLUDED.alive, else 0) and set status to 'unverified' (never carry 'routable' forward across a uuid change). Today probe_streak resets only on NOT alive and the status CASE short-circuits only on a MATCHING uuid, so a hot-swapped alive GPU inherits the prior high streak and stays routable. RESTATE C10 to state that carry-forward applies ONLY on a matching uuid and that a mismatch demotes to unverified. REQUIRED test (hermetic state-machine + PG): a stored routable row with uuid=U1 and streak>=N receives an alive probe with uuid=U2; assert the row becomes 'unverified' with probe_streak reset and is absent from routable_slots until it re-graduates."
    verification:
      gate: "hot-swap test: an alive probe whose gpu_uuid differs from the stored uuid resets probe_streak and demotes status to unverified (no inherited routable)"
      expected_stage: "design_revision_then_build_verify"
    final_review_required: true
  - id: BC3
    posture: "no-SPOF failover timing"
    severity: medium
    kind: policy
    binding: false
    source_finding: f_puller_lease_ttl_ageout
    source_refs: ["dialogue:3"]
    text: "Carried from cycle 1, still unaddressed. Pin the fleet_meta puller-lease deadman TTL strictly SHORTER than the 45s live_slots/routable_slots staleness window (e.g. <=15s, matching the RFC's ~15s probe cadence) so a standby acquires the lease and resumes heartbeats before any live slot ages out, AND turn test B into a real proof: kill/expire the holder's lease, advance time past the failover gap, and assert the standby acquires within TTL AND that no node leaves routable_slots/live_slots during failover. 'Deadman TTL identical in shape to RFC-0001's slot lease' is NOT sufficient — state the concrete TTL and its relation to the staleness window."
    verification:
      gate: "failover-no-ageout test: TTL < staleness window is stated, and a failover from a killed holder keeps every live node in the directory"
      expected_stage: "design_revision_then_build_verify"
    final_review_required: false
  - id: BC4
    posture: "no-node-wall-clock / single-writer"
    severity: medium
    kind: policy
    binding: false
    source_finding: f_driver_lease_client_clock
    source_refs: ["dialogue:3"]
    text: "Carried from cycle 1, still unaddressed. Evaluate the per-node driver-lease freshness SERVER-SIDE using the DB clock, not the puller host's local clock: push the skip predicate into the FETCH SQL (e.g. SELECT ... FROM fleet_nodes WHERE enabled AND (driven_by IS NULL OR now() >= lease_until)) so the puller never compares lease_until to its own wall clock. RESTATE C12 to cover this timing decision (today it is proven only for heartbeat_ts via test L). REQUIRED test (the driver-lease analog of test_lease_no_consumer_clock.py): assert the FETCH/skip decision carries no client timestamp param and is driven by DB now(); a node whose lease is fresh-by-DB-clock is skipped and one whose lease is expired-by-DB-clock is probed, independent of the test's local clock."
    verification:
      gate: "server-side-freshness test: the per-node skip is decided by DB now() with no client timestamp; puller-clock skew cannot cause a double-write or an unmonitored node"
      expected_stage: "design_revision_then_build_verify"
    final_review_required: false
  - id: BC5
    posture: "puller-lease internal-consistency"
    severity: low
    kind: policy
    binding: false
    source_finding: f_fleet_meta_column_mismatch
    source_refs: ["dialogue:3"]
    text: "Carried from cycle 1, still unaddressed. Align the fleet_meta column name across the Slice-0 DDL, the Slice-2 CAS, and the puller-lease tests onto a single name (puller OR holder). As written the DDL declares `puller` and the CAS uses `holder`, so the CAS errors 'column holder does not exist' on Slice-2 deploy. Trivial but mandatory — the hermetic + PG puller-lease tests (A/B) must execute the actual CAS SQL against the actual 009 DDL so this class of mismatch cannot recur."
    verification:
      gate: "puller-lease CAS executes against the 009 fleet_meta DDL without a column error (proven by the hermetic + PG lease tests running the real SQL)"
      expected_stage: "design_revision_then_build_verify"
    final_review_required: false
branches:
  zero_touch_register_self_push: "blocked"
  boot_epoch_replay_ratchet_null_overwrite: "blocked"
  boot_epoch_replay_ratchet_equal_epoch: "blocked"
  gpu_uuid_change_forces_requarantine: "blocked"
  no_spof_puller_lease_cas: "blocked"
  no_spof_failover_no_ageout: "blocked"
  single_writer_no_node_wallclock: "blocked"
  migration_009_additive_reversible: "cleared"
  status_quarantine_no_routing_until_slice4: "cleared"
  writer_before_reader_ordering: "cleared"
  prune_fix_fresh_selfpush_survives: "cleared"
  boot_epoch_not_alias_epoch: "cleared"
  hermetic_test_gate: "cleared"
  heartbeat_ts_db_stamped: "cleared"
  di_subprocess_boundary_and_live_infra_inertness: "cleared"
---

# COLLABORATION LEDGER — RFC 0002 Zero-touch node lifecycle (design gate, cycle 2)

author: adjudicator-claude-opus-4.8-002

- **RFC:** `docs/rfc/0002-zero-touch-node-lifecycle.md` (settled; prepared via `/adhd`)
- **Phase:** dialogue → synthesis (`adjudicate`), **cycle 2** (re-falsification of the holder's revised plan)
- **Revised build plan under gate:** `dialogue/holder/BUILD_PLAN.md` (holder-claude-opus-4.8-**002**, run-branch tip `5bb63d1`) — `dialogue:1`
- **Re-issued challenges read:** `dialogue/falsifier_1/FALSIFIER.md` (falsifier-openai-codex-gpt-5.5-**002**) — `dialogue:2`;
  `dialogue/falsifier_2/FALSIFIER.md` (falsifier-antigravity-gemini-**002**) — `dialogue:3`
- **Evidence basis:** the curated dialogue trajectory + the RFC only — no raw provider logs, no
  private diagnostics. There was **no separate holder rebuttal round**; the rebuttal surface is the
  revised plan's own load-bearing claims **C1–C12 + the new C6a**.
- **Cycle-1 record:** `dialogue/adjudicator/COLLABORATION_LEDGER_cycle_1.md`
  (adjudicator-claude-opus-4.8-001) — verdict `needs_revision`, which routed **revision iteration 1
  of max 2** back to the holder.

---

## VERDICT — `needs_revision`

**One-line reason:** The holder's revision **discharged none** of cycle-1's five required repairs
(it added prose, not mechanics), so all five still land — and the re-falsification surfaces **two new
landed defects** the revision itself opened. Seven challenges now land **unrebutted** on named
falsifiable-gate items, so the gate **cannot clear**; but every defect is **mechanically repairable
in one cycle** and the **design can still satisfy its own gate**, so the verdict is `needs_revision`,
not `reject`. **This is the second and final budgeted revision iteration.**

### What the revision actually changed

`git diff` of the build plan (attempt 1 → attempt 2) shows the **only** substantive edits are prose:

1. Three new sub-bullets under **Slice-1 Change B** — *what `boot_epoch` is and who stamps it*
   (per-boot scalar, push-only; pull leaves it `NULL`), *why `>=` not `>`*, and *"defense-in-depth,
   not the primary guarantee"*.
2. A new load-bearing claim **C6a** restating that defense-in-depth framing.
3. A **Section-5** bullet declaring the cross-host SSH `nvidia-smi` retirement an operator
   `fleet_nodes` **data** step (not a code slice).

The **mechanics named in cycle-1's BC1–BC5 are byte-unchanged**: Slice-3 CAS-before-UPSERT (BC1),
`SET boot_epoch = EXCLUDED.boot_epoch` with no `COALESCE` (BC2), the unpinned puller-lease TTL (BC3),
the Python-side driver-lease skip (BC4), and the `fleet_meta.puller` vs Slice-2-CAS-`holder` mismatch
(BC5).

---

## Per-challenge adjudication (cycle 2)

| Source | Claim hit | Correspondence | Becomes |
|--------|-----------|----------------|---------|
| F2 (gemini) #6 | C3 — zero-touch self-push deadlock (carried) | **landed_unrebutted** | **BC1** (blocking) |
| F2 (gemini) #2 | C6 — boot-epoch NULL pull-overwrite (carried) | **landed_unrebutted** | **BC2** (blocking) |
| F1 (codex) | C6/C6a — **equal-epoch replay** (new) | **landed_unrebutted** | **BC6** (blocking) |
| F2 (gemini) #3 | C10 — **gpu_uuid hot-swap bypasses quarantine** (new) | **landed_unrebutted** | **BC7** (blocking) |
| F2 (gemini) #1 | C8 — `fleet_meta` column mismatch (carried) | **landed_unrebutted** | **BC5** (mechanical) |
| F2 (gemini) #5 | C8/No-SPOF — puller-lease TTL vs 45s age-out (carried) | **landed_unrebutted** | **BC3** (policy) |
| F2 (gemini) #4 | C12/C9 — client wall-clock in per-node skip (carried) | **landed_unrebutted** | **BC4** (policy) |

### BC1 — Zero-touch self-push still deadlocks on the per-node lease (carried, blocker)

Slice 3 is byte-unchanged: a self-pusher CAS-acquires its per-node driver-lease **on `fleet_nodes`**
before the UPSERT and yields on failure; a zero-touch node has **no `fleet_nodes` row**, so the CAS
touches zero rows → yield → no UPSERT → no `gpu_slots` row → the directory-driven puller never probes
a node it cannot see. The plan's own **fact #1 / Pillar 3** ("registration = first heartbeat;
`fleet_nodes` is optional, not a prerequisite") *requires* this to work, and the proposed test still
covers only the **raw Slice-1 UPSERT**, never the composed Slice-1+3 path. The holder did not engage
it across two attempts. **Unrebutted → BC1.**

### BC2 — Boot-epoch ratchet still wiped by a NULL pull-write (carried, blocker)

`SET boot_epoch = EXCLUDED.boot_epoch` is unchanged, so the puller (`EXCLUDED.boot_epoch` `NULL`)
still overwrites a self-pusher's stored integer with `NULL` during the plan's **own** documented
push→pull lease-lapse flip; thereafter `gpu_slots.boot_epoch IS NULL` admits any strictly-stale
write. The new **C6a "defense-in-depth"** framing argues but does **not** repair: it concedes the
`NULL` arm "lets the write through" and defers closure to an **out-of-build** operator SSH-retirement
step, while the "primary" guarantee it leans on — the per-node driver-lease — is itself broken (BC1)
and wall-clock-dependent (BC4). **Unrebutted → BC2.** Fix is one token (`COALESCE`) + a no-wipe test.

### BC6 — Equal-epoch replay overwrites live state (NEW, blocker)

The revision's own **"why `>=` not `>`"** justification opens this. Because `boot_epoch` is a
**per-boot constant** and the comparator is `>=`, a resurrected/replayed writer presenting the
**same** `boot_epoch` with a **stale** payload takes the `ON CONFLICT DO UPDATE` path, mutates the
whole row, and **re-stamps `heartbeat_ts = now()`** — so the replay is no longer stale to the DB. The
RFC's rule is "ignore epoch **≤** recorded"; the plan refuses only strictly-lower, and has **no
equal-epoch no-op test**. This directly **refutes the holder's `>=` design defense**. **Unrebutted →
BC6.** Fix: predicate `>` (carry within-boot liveness on `heartbeat_ts`), **or** a provable
equality-no-op branch + an equal-epoch replay test.

### BC7 — A GPU hot-swap bypasses quarantine (NEW, blocker)

`probe_streak` resets only on `NOT alive`, and the `status` CASE short-circuits only on a **matching**
`gpu_uuid`. A node that reboots with a **different** (alive) GPU keeps its already-high streak, falls
through to the `streak ≥ N` graduation arm, and stays **`routable` under the new uuid** without
re-entering quarantine — routing trust on a **declared** identity, the exact thing Pillar 4's
"measured, not declared" exists to stop. **C10 is false** for the mismatch path. **Unrebutted →
BC7.** Fix: when `gpu_slots.gpu_uuid IS DISTINCT FROM EXCLUDED.gpu_uuid`, reset `probe_streak` and
set `status = 'unverified'` + a hot-swap test.

### BC5 / BC3 / BC4 — carried mechanical + policy repairs (unchanged)

- **BC5** (low, but a hard break): `fleet_meta.puller` (DDL) vs `holder` (Slice-2 CAS) →
  `column "holder" does not exist` on deploy; refutes C8. Align on one name; run the real CAS against
  the real `009` DDL in tests A/B.
- **BC3** (medium): no puller-lease TTL pinned below the 45s staleness window; a TTL ≥ 45s ages the
  fleet out during failover. Pin TTL `< 45s` and make test B a real no-age-out proof.
- **BC4** (medium): the per-node skip is still a Python-side `lease_until` filter; move the freshness
  predicate **server-side** (`now() >= lease_until`) and add the no-client-timestamp test.

---

## What survived falsification (the sound spine — keep it through the revision)

No challenge refuted these; they remain load-bearing and must be preserved intact:

- **C1** — migration number `009` is correct; the RFC's "Migration 006" is stale
  (006/007/008 taken by the peecee dense flip / RFC-0001 leases / RFC-0003 epoch).
- **C2** — migration `009` is purely additive, reversible, behavior-neutral until Slice 4. (BC5 and
  BC2 are **Slice-2/writer code** defects, not violations of `009`'s additivity; the DDL itself is
  sound.)
- **C4** — `status` quarantine changes no routing until the consumer slice; **C5** —
  writer-before-reader ordering strands no node; **C3-PRUNE** — the stale-only PRUNE fix preserves a
  fresh row (sound *given a row exists*; upstream-gated by BC1).
- **C7** — `boot_epoch` and `epoch` never alias; **C11** — hermetic default green, every DB-backed
  test guarded verbatim like `test_leases_pg.py`/`test_epoch_pg.py`; **C12** — `heartbeat_ts`
  DB-stamped (for `heartbeat_ts`; the *new* lease/replay timing decisions extend to BC4/BC6).
- The **`di --json` subprocess boundary**, **peecee stays pull-only**, and the **live-infra inertness
  of §4**.

`C3`, `C6`, `C6a`, `C8`, `C9`, `C10`, and `C12` survive only **in part** — they must be **restated**
under BC1–BC7 to match what the revised plan actually builds and tests.

---

## Why `needs_revision` (and not the alternatives)

- **Not `accept` / `accept_with_findings`:** a clearing verdict requires every landed challenge to
  have been rebutted in the trajectory. Seven challenges are `landed_unrebutted` — including the
  central zero-touch gate (BC1), a replay ratchet defeated **two** independent ways (BC2 NULL
  overwrite, BC6 equal-epoch), a quarantine bypass (BC7), and a puller-lease that throws
  `column "holder" does not exist` on deploy (BC5). Waving these through would ship a plan whose
  central gate is broken for the node it names.
- **Not `reject`:** the design *can* satisfy its own falsifiable gate. Each defect has a concrete,
  bounded repair (BC1 a one-of-four arbitration choice + composed test; BC2 a `COALESCE` + test; BC6
  a `>`-or-equality-no-op + test; BC7 a streak-reset-on-uuid-change + test; BC3 a TTL bound + test;
  BC4 a server-side predicate + test; BC5 a column rename). None is an undischargeable defect, so
  `reject` would be too strong and untruthful.
- **`needs_revision`** uses the workflow's **second and final** budgeted revision iteration
  (iteration 2 of `max_iterations` 2). An honest `needs_revision` with a truthful ledger is a
  successful gate outcome.

> **Final-iteration notice (binding on the next cycle).** Revision iteration 1 discharged **none** of
> BC1–BC5 and the re-falsification added **two** further landed defects, so the plan is **not yet
> converging**. The minimal clearing diff is small and fully enumerated in `constraints[]`. The holder
> must **APPLY** the SQL/logic/test changes, not re-argue them. If the next re-falsification still
> finds any blocker among BC1, BC2, BC6, BC7 (or the residual BC3–BC5) `landed_unrebutted`, the honest
> **terminal** outcome becomes `reject` — the gate's revision budget will have been spent without the
> plan surviving falsification.

---

## Handoff to the holder (final cycle) — the minimal clearing diff

Revise `dialogue/holder/BUILD_PLAN.md` to **APPLY** (not argue) these, then the falsifiers
re-challenge:

1. **BC1 (blocker):** pick one arbitration model (a/b/c/d) so a no-`fleet_nodes` self-pusher
   registers; restate C3/C9/gate-D; add the **composed** Slice-1+3 registration test.
2. **BC2 (blocker):** `SET boot_epoch = COALESCE(EXCLUDED.boot_epoch, gpu_slots.boot_epoch)`; restate
   C6/C6a so the in-build SQL never self-erases the ratchet; add the push-stamp → pull-NULL → stale-refused PG test.
3. **BC6 (blocker):** predicate `EXCLUDED.boot_epoch > gpu_slots.boot_epoch` (carry within-boot
   liveness on `heartbeat_ts`) **or** a provable equality-no-op branch; add the equal-epoch replay test.
4. **BC7 (blocker):** on `gpu_slots.gpu_uuid IS DISTINCT FROM EXCLUDED.gpu_uuid`, reset `probe_streak`
   and demote to `unverified`; restate C10; add the hot-swap test.
5. **BC3 / BC4 / BC5 (fold in):** pin the TTL `< 45s` + no-age-out test; server-side lease freshness
   predicate + no-client-timestamp test; one `fleet_meta` column name across DDL/CAS/tests.

Preserve everything under **"What survived"** and do **not** re-open the RFC's settled design
(pull-first peer-runnable driver; push opt-in for trusted Linux nodes only; registration = first
heartbeat; measured-not-declared quarantine→graduate; `boot_epoch` ⟂ `epoch`).
