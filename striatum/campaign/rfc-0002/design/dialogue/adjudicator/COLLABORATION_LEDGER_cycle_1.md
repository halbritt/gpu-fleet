---
schema_version: "striatum.collaboration_ledger.v1.1"
artifact_kind: "collaboration_ledger"
shape: "falsification_gate"
author: adjudicator-claude-opus-4.8-001
workflow: "rfc-0002-design"
run_id: "run_aa1f69f24463027c2466994e9f655b08"
cycle: 1
topic: "RFC 0002 — Zero-touch node lifecycle: gate the falsifiable build plan"
participants: ["holder", "falsifier_1", "falsifier_2", "adjudicator"]
verdict: "needs_revision"
rationale: "Adjudicated from the curated dialogue trajectory only — the build plan (dialogue:1, holder-claude-opus-4.8-001) and the two falsifier challenges (dialogue:2, falsifier-openai-codex-gpt-5.5-001; dialogue:3, falsifier-antigravity-gemini-001) — plus the settled RFC in context_docs; no raw provider logs or private diagnostics. The holder did NOT revise between rounds: BUILD_PLAN.md is the single dialogue artifact and there is no holder rebuttal round, so the only in-trajectory rebuttals are the plan's own pre-emptive load-bearing claims C1-C12 (§7). THE GATE CANNOT CLEAR, and this is not discretionary: a clearing verdict (accept/accept_with_findings) requires every landed challenge to be rebutted in the trajectory (RFC 0094 §5 Check-B), and THREE challenges are recorded landed_unrebutted. (1) BLOCKER BC1 — the central zero-touch-register gate fails for the exact node shape the gate names, raised independently by BOTH falsifiers (codex whole-challenge; gemini #5): Slice 3 makes a self-pushing node CAS-acquire its per-node driver-lease on fleet_nodes BEFORE the UPSERT and yield on CAS failure, but a zero-touch self-pusher has NO fleet_nodes row, so the CAS updates zero rows, the writer yields, the first gpu_slots row is never created, and the directory-driven puller (FETCH reads only enabled fleet_nodes rows) never rescues it — the node stays unregistered. The plan never reconciles its own load-bearing fact #1 / Pillar 3 ('registration = first heartbeat; fleet_nodes is an OPTIONAL allowlist, not a prerequisite') with Slice 3's CAS-before-UPSERT, and the proposed test test_self_register_no_fleet_node_graduates exercises only the raw Slice-1 UPSERT, never the composed Slice-1+3 push entry path — so the gate item has NO real test for the case it claims. landed_unrebutted. (2) BLOCKER BC2 — gemini #2 defeats Pillar 5's replay ratchet (C6 false as written): Change B's SET clause is boot_epoch = EXCLUDED.boot_epoch, so when the puller (which cannot stamp a boot_epoch ⇒ EXCLUDED.boot_epoch NULL) resumes writing a row a self-pusher previously stamped — the plan's OWN documented push→pull flip when a lease lapses, Pillar 2 'a dead pusher's lease expires and pull resumes' — the WHERE's EXCLUDED.boot_epoch IS NULL arm passes and the SET overwrites the stored integer with NULL, after which gpu_slots.boot_epoch IS NULL admits any subsequent strictly-stale write. A resurrected SSH-driver/stale writer then overwrites freely — the exact split-brain/replay Pillar 5 exists to kill. The holder engaged NULL only for the WHERE (inertness pre-rollout), never for the SET-overwrite path; that is a different mechanism, so the rebuttal is incomplete = landed_unrebutted. Fix is one token: boot_epoch = COALESCE(EXCLUDED.boot_epoch, gpu_slots.boot_epoch). (3) BLOCKER-as-written BC5 — gemini #1: Slice-0 DDL names the column fleet_meta.puller but the Slice-2 CAS SETs/matches/RETURNs holder, so the puller-lease CAS errors 'column holder does not exist' on Slice-2 deploy, refuting C8 ('a single puller is unaffected'); the holder never reconciled the two SQL fragments = landed_unrebutted (mechanical, low severity, but a hard break). Two further challenges landed and were partially rebutted, becoming residual policy constraints (recommended, non-blocking) that do NOT themselves block clearing: (BC3, gemini #4, medium) the gate bullet 'fleet does not age out' is asserted via test B but the plan pins NO puller-lease TTL and never constrains it below the 45s live_slots/routable_slots staleness window — if TTL ≥ 45s the standby waits out the lease while no heartbeats are written and live slots age out before failover completes; landed_and_rebutted (the holder named the property but supplied no constraint making it true) ⇒ pin TTL strictly < staleness window and make test B actually advance past the failover gap and assert no age-out. (BC4, gemini #3, medium) Slice 3 describes the per-node driver-lease skip as a Python-side 'selection filter' over driven_by + lease_until and never states the freshness comparison is server-side; the plan's C12 ('no node wall-clock trusted') is proven only for heartbeat_ts (test L) and the NEW lease-timing decision ships no such test — a puller clock skewed vs the DB either double-writes a still-leased node or skips a lapsed one; landed_and_rebutted (the plan's DB-clock ethos + the server-side Slice-2 CAS imply the intent but do not enforce or test it for the per-node skip) ⇒ evaluate freshness server-side in the FETCH SQL (now() >= lease_until) and test no client timestamp enters the decision. Why needs_revision and not reject: every defect is dischargeable in ONE cycle without re-opening the settled RFC — BC1 picks one coherent arbitration model that lets a no-fleet_nodes self-pusher register (or scopes it out and narrows the gate) + a composed test; BC2 is COALESCE + a writer-side no-wipe test; BC3 pins a TTL + a no-age-out test; BC4 moves a predicate server-side + a no-wall-clock test; BC5 renames a column. The DESIGN can satisfy its own falsifiable gate, so reject (reserved for an undischargeable defect) would be too strong and dishonest. The plan's SPINE survives falsification intact and MUST be preserved through the revision: C1 (migration number 009 is correct; the RFC's 'Migration 006' is stale — 006/007/008 are taken by the peecee-dense flip, RFC-0001 leases, RFC-0003 epoch — a load-bearing correction, unchallenged), C2 (009 is purely additive/reversible/behavior-neutral until Slice 4 — the running UPSERT names no new column, consumers read live_slots until Slice 4; the only SQL the falsifiers hit inside 009 is BC5's naming typo and BC2's SET clause, neither of which refutes additivity), C4 (status quarantine changes no routing until the consumer slice), C5 (writer-before-reader ordering strands no node — the deliberate opposite of RFC-0003's reader-first, correct here because Slice 4 FILTERS on status), C3-PRUNE (the stale-only PRUNE fix preserves a fresh self-push row — sound given a row exists; it is upstream-gated by BC1 because the deadlock prevents the row's creation), C7 (boot_epoch and epoch never alias), C10 (gpu_uuid carry-forward only on matching UUID + passing probe), C11 (hermetic default green, every DB test guarded verbatim like test_leases_pg.py/test_epoch_pg.py behind importorskip + GPU_FLEET_TEST_DB ephemeral-only refusal), C12 (heartbeat_ts DB-stamped — for heartbeat_ts; the new lease-timing decision extends to BC4), the di --json subprocess boundary (registry SQL only; no engine import), peecee-pull-only (no fleet code/creds), and the live-infra inertness of §4 (the build writes migrations/009 + edits + hermetic pytest; touches no live gpu_fleet DB, no running gpu-fleet-heartbeat, no peecee GPU). An honest needs_revision with a truthful ledger is a successful gate outcome: the holder revises dialogue/holder/BUILD_PLAN.md to discharge BC1+BC2 (the blockers) and fold in BC3-BC5, preserving everything under 'What survived', and the falsifiers re-challenge the revised plan."
entries:
  - kind: claim
    by: holder
    refs: ["dialogue:1"]
    text: "Holder build plan: realize the settled RFC 0002 against the post-RFC-0001/0003 code in five ordered, independently-committable slices, commit-order = deploy-order = DB→writer→puller→consumer (writer-before-reader, the deliberate opposite of RFC-0003). Slice 0: additive migration 009 (status/probe_streak/gpu_uuid/boot_epoch on gpu_slots; driven_by/lease_until on fleet_nodes; new fleet_meta puller-lease table; routable_slots view ALONGSIDE live_slots; backfill existing rows status='routable'). Slice 1: the shared UPSERT gains a streak/status state machine, gpu_uuid capture, a boot-epoch ratchet (ON CONFLICT … WHERE EXCLUDED.boot_epoch IS NULL OR gpu_slots.boot_epoch IS NULL OR EXCLUDED.boot_epoch >= gpu_slots.boot_epoch), and the load-bearing PRUNE fix (delete only rows absent from enabled fleet_nodes AND already stale). Slice 2: global fleet_meta puller-lease CAS (peer-runnable driver, kills the SPOF). Slice 3: per-node driver-lease arbitration (self-push CAS-acquires fleet_nodes lease before UPSERT, yields on failure; puller skips held-fresh-lease nodes). Slice 4: consumers add AND status='routable' to PICK and LEASE_CLAIM_SQL (turns quarantine ON, deploy LAST). Slice 5 (RLS) deferred/not built. Migration number corrected to 009 (RFC's '006' stale). Falsifiable-gate→test map split hermetic + GPU_FLEET_TEST_DB-guarded PG. Load-bearing claims C1-C12 (§7) are the pre-emptive falsifiable surface."
  - kind: challenge
    by: falsifier_1
    refs: ["dialogue:2"]
    correspondence: landed_unrebutted
    text: "C3/C9/gate-D challenged (zero-touch register vs single-writer arbitration): the central gate ('a node self-reports with NO prior fleet_nodes row, appears unverified, graduates') cannot hold under Slice 3 as written, because the per-node driver-lease lives on fleet_nodes while the zero-touch case explicitly has no fleet_nodes row. Counterexample (post-Slice-0..3, consumer gating irrelevant): a new trusted Linux node runs heartbeat.py --node self with no fleet_nodes row → Slice-3 CAS-acquire on fleet_nodes updates ZERO rows → plan says yield to the puller → puller FETCHes only enabled fleet_nodes rows so it never probes this node → the heartbeat.py UPSERT that creates the first gpu_slots row is never reached → the PRUNE fix is irrelevant (no fresh row to preserve). The proposed test_self_register_no_fleet_node_graduates exercises only the raw Slice-1 UPSERT, NOT the composed Slice-1+3 push entry path, so the gate item has no real test. The holder's plan never engages the no-fleet_nodes self-push case; its own fact #1/Pillar 3 ('registration = first heartbeat; fleet_nodes optional, not a prerequisite') REQUIRES it to work. The trusted-quad-server-already-has-a-row escape is pre-rebutted (the plan's gate names the no-row case) and the Slice-1-lands-first escape fails (Slice 3 is committed v1 — a later slice must not invalidate a gate an earlier slice claimed). UNREBUTTED → BC1 (blocker): choose ONE coherent arbitration model for no-fleet_nodes nodes and test the composed path."
  - kind: challenge
    by: falsifier_2
    refs: ["dialogue:3"]
    correspondence: landed_unrebutted
    text: "(gemini #2) C6/Pillar-5 challenged (boot-epoch ratchet defeated by puller NULL overwrite): Change B's SET clause boot_epoch = EXCLUDED.boot_epoch overwrites a stored non-NULL boot_epoch with NULL whenever the puller (which has no boot_epoch ⇒ EXCLUDED.boot_epoch NULL) writes a row a self-pusher previously stamped. Sequence: pusher stamps boot_epoch=K → pusher's lease lapses → puller resumes (Pillar 2's documented push→pull flip) → puller UPSERT conflicts → WHERE EXCLUDED.boot_epoch IS NULL passes → SET writes boot_epoch=NULL → now gpu_slots.boot_epoch IS NULL admits ANY later strictly-stale write, including a resurrected stale self-pusher (boot_epoch<K). The ratchet is defeated in the exact hybrid steady state the design embraces — Pillar 5's split-brain/replay defense. The holder engaged the NULL case only for WHERE inertness (pre-rollout), never the SET-overwrite, so C6 ('refuses a strictly-stale write') is FALSE for any push-then-pull row and UNREBUTTED → BC2 (blocker). Correction: boot_epoch = COALESCE(EXCLUDED.boot_epoch, gpu_slots.boot_epoch) + a PG test (stamp K, puller-NULL write keeps K, stale<K refused)."
  - kind: challenge
    by: falsifier_2
    refs: ["dialogue:3"]
    correspondence: landed_unrebutted
    text: "(gemini #1) C8 challenged (fleet_meta column-name mismatch): Slice-0 DDL creates fleet_meta with column `puller TEXT`, but the Slice-2 CAS SETs/matches/RETURNs `holder` (UPDATE fleet_meta SET holder=:me … WHERE … OR holder=:me RETURNING holder). Executing the CAS on the defined schema errors `column \"holder\" does not exist`, breaking the puller immediately on Slice-2 deploy and refuting C8 ('a single puller is unaffected; only a second idles'). The holder never reconciled the two SQL fragments → landed_unrebutted (mechanical, low severity, but a hard break) → BC5: align the DDL, the CAS, and the tests on ONE column name (puller or holder)."
  - kind: challenge
    by: falsifier_2
    refs: ["dialogue:3"]
    correspondence: landed_and_rebutted
    text: "(gemini #4) C8/No-SPOF-gate challenged (puller-lease TTL vs 45s directory staleness): if the puller-lease deadman TTL is ≥ the 45s live_slots/routable_slots staleness window, a dead holder's standby must wait out the lease before resuming heartbeats; during that wait no node is written, so live slots age out before failover completes — violating the gate's 'the fleet does NOT age out'. The plan pins no TTL value and never constrains it below the staleness window; test B asserts 'rows stay fresh, do not age out' but supplies no mechanism making that true. landed_and_rebutted (the holder NAMED the gate property via test B but the rebuttal is unsupported) → BC3: specify a puller-lease TTL strictly shorter than the staleness window (e.g. ≤15s) and make test B advance time past the failover gap and assert no node leaves routable_slots/live_slots."
  - kind: challenge
    by: falsifier_2
    refs: ["dialogue:3"]
    correspondence: landed_and_rebutted
    text: "(gemini #3) C12/No-node-wall-clock challenged (client wall-clock in driver-lease skip): Slice 3 describes the puller's per-node skip as 'FETCH/skip honoring driven_by + lease_until' — a Python-side selection filter. If lease_until is compared against the puller HOST's local clock, a skewed puller either treats a fresh lease as expired and double-writes (refuting C9) or skips a lapsed lease and leaves a node unmonitored — violating C12/Pillar-5 'the single DB clock is the only authority on when'. C12 is proven only for heartbeat_ts (test L); the NEW lease-timing decision ships no no-wall-clock test. landed_and_rebutted (the plan's DB-clock ethos + the server-side Slice-2 CAS imply server-side intent but never state or test it for the per-node skip) → BC4: evaluate freshness server-side in the FETCH SQL (e.g. WHERE enabled AND (driven_by IS NULL OR now() >= lease_until)) and test that no client timestamp enters the decision."
  - kind: challenge
    by: falsifier_2
    refs: ["dialogue:3"]
    correspondence: landed_unrebutted
    text: "(gemini #5) C3/zero-touch-register challenged — CORROBORATES falsifier_1: a self-pushing node with no fleet_nodes row CAS-acquires on fleet_nodes, the update affects zero rows, it yields, the gpu_slots write never occurs, and the puller skips it (not in fleet_nodes) → node never registers. Same defect as the falsifier_1 whole-challenge, raised independently by the second falsifier → reinforces BC1 (blocker). Correction (same option set): bypass the CAS when no fleet_nodes row (with a documented C9 preservation), OR auto-insert a default fleet_nodes arbitration row atomically, OR scope no-fleet_nodes self-push out and narrow the gate + C3."
  - kind: rebuttal
    by: holder
    refs: ["dialogue:1"]
    text: "Holder in-plan pre-emptive defenses (§7 C1-C12; there was no holder rebuttal round). SURVIVING/unchallenged: C1 (009 correct, RFC '006' stale), C2 (009 additive/reversible/behavior-neutral until Slice 4), C4 (status changes no routing until consumer slice), C5 (writer-before-reader strands no node), C7 (boot_epoch ⟂ epoch), C10 (gpu_uuid carry-forward on matching UUID + pass only), C11 (hermetic default green, PG tests guarded), C12 (heartbeat_ts DB-stamped) — these are the sound spine and stand. INCOMPLETE/falsified: the plan never anticipated the no-fleet_nodes self-push deadlock (C3/C9 silent on it → BC1 blocker, raised by both falsifiers), engaged boot_epoch NULL only for the WHERE inertness and not the SET-overwrite (C6 false for push-then-pull rows → BC2 blocker), left fleet_meta.puller vs the Slice-2 `holder` CAS unreconciled (C8 breaks as written → BC5), named the no-age-out gate via test B without pinning a TTL below the staleness window (→ BC3), and proved C12 only for heartbeat_ts while leaving the new per-node lease-freshness decision unstated/untested for client-clock dependence (→ BC4)."
findings:
  - id: f_zero_touch_lease_deadlock
    severity: high
    posture: "correctness-of-the-falsifiable-gate / zero-touch register"
    status: open
    challenge: "Slice 3's CAS-acquire-on-fleet_nodes-before-UPSERT + yield-on-failure makes the central 'zero-touch register' gate fail for the exact node shape it names: a self-pushing node with no fleet_nodes row CASes zero rows, yields, never writes its first gpu_slots row, and the directory-driven puller never rescues it. The plan's own fact #1/Pillar 3 require no-fleet_nodes registration to work; the proposed test covers only the raw Slice-1 UPSERT, never the composed Slice-1+3 path. Raised independently by BOTH falsifiers (codex whole-challenge, gemini #5) → landed_unrebutted → BLOCKING repair BC1, the reason the gate cannot clear (RFC 0094 §5 Check-B)."
    affected_invariants: ["registration_equals_first_heartbeat", "zero_touch_register_no_prior_fleet_nodes_row", "push_and_pull_never_both_write_a_node"]
    requires_convener_rebuttal: true
    source_refs: ["dialogue:2", "dialogue:3"]
  - id: f_boot_epoch_null_overwrite
    severity: high
    posture: "split-brain / replay ratchet correctness"
    status: open
    challenge: "Change B's SET boot_epoch = EXCLUDED.boot_epoch lets the puller (EXCLUDED.boot_epoch NULL) overwrite a self-pusher's stored boot_epoch with NULL during the plan's own documented push→pull lease-lapse flip; the row then satisfies gpu_slots.boot_epoch IS NULL and admits any strictly-stale write, re-opening the resurrected-stale-writer split-brain Pillar 5 exists to kill. C6 is false as written for push-then-pull rows; the holder addressed NULL only in the WHERE (inertness), not the SET. landed_unrebutted → BLOCKING repair BC2. Fix: COALESCE(EXCLUDED.boot_epoch, gpu_slots.boot_epoch) + a writer-side no-wipe test."
    affected_invariants: ["boot_epoch_is_a_one_way_monotonic_ratchet", "a_pull_write_never_resets_a_push_stamped_ratchet"]
    requires_convener_rebuttal: true
    source_refs: ["dialogue:3"]
  - id: f_fleet_meta_column_mismatch
    severity: low
    posture: "correctness / internal-consistency (no-SPOF puller-lease)"
    status: open
    challenge: "Slice-0 DDL column fleet_meta.puller vs Slice-2 CAS column `holder` — the CAS errors 'column holder does not exist' and breaks the puller on Slice-2 deploy, refuting C8. Mechanical and trivially repairable, but unreconciled in the plan = landed_unrebutted → BC5. Align DDL + CAS + tests on one name."
    affected_invariants: ["puller_lease_cas_executes_on_the_declared_schema"]
    requires_convener_rebuttal: false
    source_refs: ["dialogue:3"]
  - id: f_puller_lease_ttl_ageout
    severity: medium
    posture: "no-SPOF gate / failover timing"
    status: answered
    challenge: "No constraint binds the puller-lease deadman TTL below the 45s directory staleness window, so a TTL ≥ 45s lets live slots age out during failover, violating the gate's 'fleet does not age out'. The holder named the property (test B) but supplied no constraint making it hold. landed_and_rebutted → residual BC3: pin TTL strictly < staleness window and make test B prove no age-out across the failover gap."
    affected_invariants: ["puller_failover_completes_before_any_live_slot_ages_out"]
    source_refs: ["dialogue:3"]
  - id: f_driver_lease_client_clock
    severity: medium
    posture: "no-node-wall-clock / single-writer timing"
    status: answered
    challenge: "Slice 3's per-node skip is described as a Python-side filter over lease_until with no stated server-side evaluation and no no-wall-clock test; a skewed puller clock double-writes a still-leased node or skips a lapsed one, violating C12/C9. C12 is proven only for heartbeat_ts (test L). landed_and_rebutted (DB-clock ethos + server-side Slice-2 CAS imply but do not enforce the intent for the per-node skip) → residual BC4: evaluate freshness server-side in FETCH SQL (now() >= lease_until) + a no-client-timestamp test."
    affected_invariants: ["all_liveness_timing_decisions_use_the_db_clock_not_a_node_clock"]
    source_refs: ["dialogue:3"]
constraints:
  - id: BC1
    posture: "zero-touch-register gate"
    severity: high
    kind: gate
    binding: true
    source_finding: f_zero_touch_lease_deadlock
    source_refs: ["dialogue:2", "dialogue:3"]
    text: "BLOCKING repair (the reason the gate cannot clear, corroborated by both falsifiers). The revised plan MUST resolve the Slice-3 CAS-before-UPSERT deadlock so a self-pushing node with NO pre-existing fleet_nodes row can still complete registration = first heartbeat, by choosing exactly ONE coherent arbitration model and stating how C9 (push and pull never both write a node) still holds for it: (a) the per-node driver-lease is NOT stored exclusively on fleet_nodes (so a no-row self-pusher can arbitrate); OR (b) the push path ATOMICALLY creates the required fleet_nodes arbitration row as part of zero-touch registration (test the create is atomic wrt the single-writer rule); OR (c) the first registering UPSERT proceeds unconditionally and the driver-lease governs only ONGOING contention once both writers can reach the node (registration is not lease-gated); OR (d) explicitly scope no-fleet_nodes self-push OUT — narrow the 'zero-touch register' gate and C3 to state zero-touch is pull-only and push requires a pre-existing fleet_nodes row. RESTATE C3/C9 and gate-mapping-D to match what is built. REQUIRED test (the discharging one the plan currently lacks): execute the COMPOSED post-Slice-1+3 push path for a node absent from fleet_nodes with probes stubbed passing, and assert a gpu_slots row appears 'unverified' and graduates to 'routable' after N probes — OR, under option (d), a test pinning the narrowed pull-only scope. The current test_self_register_no_fleet_node_graduates (raw Slice-1 UPSERT only) does NOT discharge this."
    verification:
      gate: "composed-path test: a self-push for a node with no fleet_nodes row registers (gpu_slots row appears unverified and graduates), with C9 preserved — or the gate is explicitly narrowed to pull-only and tested as such"
      expected_stage: "design_revision_then_build_verify"
    final_review_required: true
  - id: BC2
    posture: "boot-epoch replay-ratchet gate"
    severity: high
    kind: gate
    binding: true
    source_finding: f_boot_epoch_null_overwrite
    source_refs: ["dialogue:3"]
    text: "BLOCKING repair. Slice-1 Change B MUST preserve a stored non-NULL boot_epoch when the incoming write supplies NULL, so a puller (or any NULL-epoch writer) cannot wipe a self-pusher's ratchet during the documented push→pull lease-lapse flip: change the SET to boot_epoch = COALESCE(EXCLUDED.boot_epoch, gpu_slots.boot_epoch) (or an equivalent that never lowers/erases a recorded epoch). RESTATE C6 to cover the SET-overwrite path, not only the WHERE inertness. REQUIRED test (PG): stamp gpu_slots.boot_epoch=K via a push write; have the puller UPSERT the same (node, slot) with boot_epoch NULL and assert boot_epoch stays K; then assert a strictly-stale write (boot_epoch < K) is refused. Without this, a resurrected stale self-pusher overwrites a live row after one pull tick — the split-brain/replay Pillar 5 exists to exclude."
    verification:
      gate: "ratchet-survives-NULL test: a NULL-epoch (puller) write does not erase a stored boot_epoch, and a strictly-stale write is still refused after any number of pull ticks"
      expected_stage: "design_revision_then_build_verify"
    final_review_required: true
  - id: BC3
    posture: "no-SPOF failover timing"
    severity: medium
    kind: policy
    binding: false
    source_finding: f_puller_lease_ttl_ageout
    source_refs: ["dialogue:3"]
    text: "The revised plan MUST pin the fleet_meta puller-lease deadman TTL strictly SHORTER than the 45s live_slots/routable_slots staleness window (e.g. ≤15s, matching the RFC's 15s probe cadence) so a standby acquires the lease and resumes heartbeats before any live slot ages out, AND must turn test B into a real proof: kill/expire the holder's lease, advance time past the failover gap, and assert the standby acquires within TTL AND that no node leaves routable_slots/live_slots during failover. 'Deadman TTL identical in shape to RFC-0001's slot lease' is NOT sufficient — state the concrete TTL and its relation to the staleness window."
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
    text: "The revised plan MUST evaluate the per-node driver-lease freshness SERVER-SIDE using the DB clock, not the puller host's local clock: push the skip predicate into the FETCH SQL (e.g. SELECT … FROM fleet_nodes WHERE enabled AND (driven_by IS NULL OR now() >= lease_until)) so the puller never compares lease_until to its own wall clock. RESTATE C12 to cover this new timing decision (today it is proven only for heartbeat_ts via test L). REQUIRED test (the driver-lease analog of test_lease_no_consumer_clock.py): assert the FETCH/skip decision carries no client timestamp param and is driven by DB now(); a node whose lease is fresh-by-DB-clock is skipped and one whose lease is expired-by-DB-clock is probed, independent of the test's local clock."
    verification:
      gate: "server-side-freshness test: the per-node skip is decided by DB now() with no client timestamp; skew of the puller clock cannot cause a double-write or an unmonitored node"
      expected_stage: "design_revision_then_build_verify"
    final_review_required: false
  - id: BC5
    posture: "puller-lease internal-consistency"
    severity: low
    kind: policy
    binding: false
    source_finding: f_fleet_meta_column_mismatch
    source_refs: ["dialogue:3"]
    text: "The revised plan MUST align the fleet_meta column name across the Slice-0 DDL, the Slice-2 CAS, and the puller-lease tests onto a single name (puller OR holder). As written the DDL declares `puller` and the CAS uses `holder`, so the CAS errors 'column holder does not exist' on Slice-2 deploy. Trivial but mandatory — the hermetic + PG puller-lease tests (A/B) must execute the actual CAS SQL against the actual 009 DDL so this class of mismatch cannot recur."
    verification:
      gate: "puller-lease CAS executes against the 009 fleet_meta DDL without a column error (proven by the hermetic + PG lease tests running the real SQL)"
      expected_stage: "design_revision_then_build_verify"
    final_review_required: false
branches:
  zero_touch_register_self_push: "blocked"
  boot_epoch_replay_ratchet: "blocked"
  no_spof_puller_lease_cas: "blocked"
  no_spof_failover_no_ageout: "cleared_with_constraints"
  single_writer_no_node_wallclock: "cleared_with_constraints"
  migration_009_additive_reversible: "cleared"
  status_quarantine_no_routing_until_slice4: "cleared"
  writer_before_reader_ordering: "cleared"
  prune_fix_fresh_selfpush_survives: "cleared"
  boot_epoch_not_alias_epoch: "cleared"
  gpu_uuid_carry_forward: "cleared"
  hermetic_test_gate: "cleared"
  heartbeat_ts_db_stamped: "cleared"
  di_subprocess_boundary_and_live_infra_inertness: "cleared"
---

# COLLABORATION LEDGER — RFC 0002 Zero-touch node lifecycle (design gate, cycle 1)

author: adjudicator-claude-opus-4.8-001

- **RFC:** `docs/rfc/0002-zero-touch-node-lifecycle.md` (settled; prepared via `/adhd`)
- **Phase:** dialogue → synthesis (`adjudicate`), cycle 1
- **Build plan under gate:** `dialogue/holder/BUILD_PLAN.md` (holder-claude-opus-4.8-001) — `dialogue:1`
- **Challenges read:** `dialogue/falsifier_1/FALSIFIER.md` (falsifier-openai-codex-gpt-5.5-001) — `dialogue:2`;
  `dialogue/falsifier_2/FALSIFIER.md` (falsifier-antigravity-gemini-001) — `dialogue:3`
- **Evidence basis:** the curated dialogue trajectory + the RFC only — no raw provider logs, no
  private diagnostics. There was **no holder rebuttal round**; the only in-trajectory rebuttals are
  the plan's own pre-emptive load-bearing claims **C1–C12 (§7)**.

---

## VERDICT — `needs_revision`

**One-line reason:** Three challenges land **unrebutted** on named falsifiable-gate items, so the
gate **cannot clear** (RFC 0094 §5 Check-B), but every defect is **repairable in one cycle** without
re-opening the settled RFC — so the plan returns for revision, not rejection.

The two blockers strike the heart of the design:

1. **BC1 — the zero-touch-register gate fails for the exact node it names**, raised **independently
   by both falsifiers** (codex whole-challenge; gemini #5). Slice 3 makes a self-pushing node
   **CAS-acquire its per-node driver-lease on `fleet_nodes` *before* the UPSERT and yield on
   failure** — but a zero-touch self-pusher has **no `fleet_nodes` row**, so the CAS touches zero
   rows, the writer yields, the first `gpu_slots` row is never created, and the directory-driven
   puller (which `FETCH`es only enabled `fleet_nodes` rows) never rescues it. The plan never
   reconciles this with its own load-bearing **fact #1 / Pillar 3** ("registration = first
   heartbeat; `fleet_nodes` is an *optional* allowlist, not a prerequisite"), and its proposed
   `test_self_register_no_fleet_node_graduates` exercises only the **raw Slice-1 UPSERT**, never the
   **composed Slice-1+3** push entry path — so the gate item has **no real test** for the case it
   claims.
2. **BC2 — the boot-epoch replay ratchet (Pillar 5) is defeated by a NULL pull-write.** Change B's
   `SET boot_epoch = EXCLUDED.boot_epoch` overwrites a self-pusher's stored epoch with `NULL` the
   moment the puller resumes a node after a lease lapses (the plan's **own** documented push→pull
   flip). Once `gpu_slots.boot_epoch IS NULL`, any strictly-stale write is admitted — re-opening the
   resurrected-stale-writer split-brain the ratchet exists to kill. The holder engaged `NULL` only
   in the `WHERE` (inertness), never in the `SET`, so **C6 is false as written** for push-then-pull
   rows.

A third, mechanical break also lands unrebutted (**BC5**: `fleet_meta.puller` in the DDL vs `holder`
in the Slice-2 CAS ⇒ `column "holder" does not exist`). Two further challenges landed and were only
**partially** rebutted, becoming residual policy repairs that do not themselves block the gate
(**BC3** puller-lease TTL vs the 45s age-out window; **BC4** client-wall-clock in the per-node skip).

> **This is the honest disposition, not a coerced one.** A clearing verdict
> (`accept`/`accept_with_findings`) requires every landed challenge to have been **rebutted in the
> trajectory** (RFC 0094 §5 Check-B). Three challenges are `landed_unrebutted` — the holder's plan
> genuinely never engages the no-`fleet_nodes` push path, the `SET`-overwrite vector, or the column
> mismatch. Reclassifying any of them as rebutted to force a clear would be a **fabrication**.
> `reject` is also wrong: the **design can satisfy its own falsifiable gate** — the repairs are a
> coherent arbitration model + test (BC1), a `COALESCE` + test (BC2), a TTL bound + test (BC3), a
> server-side predicate + test (BC4), and a column rename (BC5). One cycle suffices, so
> `needs_revision` is the truthful outcome — and an honest `needs_revision` is a **successful gate
> outcome**, not a failure.

This is **not** a clearing verdict: the commit phase does not run. The holder revises
`dialogue/holder/BUILD_PLAN.md` to discharge **BC1–BC2** (blockers) and fold in **BC3–BC5**, and the
falsifiers re-challenge.

---

## What survived falsification (the sound spine — keep it through the revision)

No challenge refuted these; they are load-bearing and must be preserved intact:

- **C1 — migration number `009` is correct; the RFC's "Migration 006" is stale.** `migrations/`
  holds `001`–`008` (006 = peecee dense flip, 007 = RFC-0001 leases, 008 = RFC-0003 epoch); `009` is
  the lowest unused number and the build reuses none. A genuine, unchallenged, load-bearing
  correction of the RFC's illustrative number.
- **C2 — migration `009` is purely additive, reversible, and behavior-neutral until Slice 4.**
  `ADD COLUMN IF NOT EXISTS` / `CREATE … IF NOT EXISTS` + one backfill `UPDATE`; the running UPSERT
  names no new column; consumers read `live_slots` until Slice 4; `routable_slots` is added
  **alongside** `live_slots` (expand/contract). The only SQL the falsifiers hit *inside* `009` is
  BC5's naming typo and BC2's `SET` clause — neither refutes additivity/reversibility.
- **C4 — `status` quarantine changes no routing until the consumer slice;** **C5 —
  writer-before-reader ordering strands no node** (the deliberate *opposite* of RFC-0003's
  reader-first, correct here because Slice 4 *filters* on `status`); **C3-PRUNE — the stale-only
  PRUNE fix** preserves a fresh self-push row (sound *given a row exists*; upstream-gated by BC1,
  which is what prevents the row's creation).
- **C7 — `boot_epoch` and `epoch` never alias;** **C10 — `gpu_uuid` carry-forward only on a matching
  UUID + passing probe;** **C11 — hermetic default green, every DB-backed test guarded** verbatim
  like `test_leases_pg.py`/`test_epoch_pg.py` (`importorskip` + `GPU_FLEET_TEST_DB` ephemeral-only
  refusal); **C12 — `heartbeat_ts` DB-stamped** (for `heartbeat_ts`; the *new* lease-timing decision
  extends to BC4).
- **The `di --json` subprocess boundary** (registry SQL only; no engine import), **peecee stays
  pull-only** (no fleet code/creds), and the **live-infra inertness of §4** (the build writes
  `migrations/009` + edits + hermetic `pytest`; it touches no live `gpu_fleet` DB, no running
  `gpu-fleet-heartbeat`, no peecee GPU).

`C3`, `C6`, `C8`, `C9`, and `C12` survive only **in part** — they must be **restated** under BC1–BC5
to match what the revised plan actually builds and tests.

---

## Per-challenge adjudication

| Source | Claim hit | Correspondence | Becomes |
|--------|-----------|----------------|---------|
| F1 (codex), whole challenge | C3 / C9 / gate-D — zero-touch register vs per-node lease | **landed_unrebutted** | **BC1** (blocking) |
| F2 (gemini) #5 | C3 — same zero-touch deadlock (corroborates F1) | **landed_unrebutted** | **BC1** (reinforces) |
| F2 (gemini) #2 | C6 / Pillar 5 — ratchet defeated by NULL pull-write | **landed_unrebutted** | **BC2** (blocking) |
| F2 (gemini) #1 | C8 — `fleet_meta` column-name mismatch | **landed_unrebutted** | **BC5** (mechanical) |
| F2 (gemini) #4 | C8 / No-SPOF — puller-lease TTL vs 45s age-out | landed_and_rebutted | **BC3** (policy residual) |
| F2 (gemini) #3 | C12 / C9 — client wall-clock in per-node skip | landed_and_rebutted | **BC4** (policy residual) |

### BC1 — Zero-touch self-push deadlocks on the per-node lease (LANDS, UNREBUTTED — blocker, corroborated)

Hits the verdict-basis bullseye: a falsifiable-gate item with **no real test** for the case it
names. The per-node driver-lease lives on `fleet_nodes`; the zero-touch gate explicitly names a node
with **no** `fleet_nodes` row. Slice 3's "CAS-acquire then yield on failure" therefore deadlocks the
**first** registration: zero rows updated → yield → no UPSERT → no `gpu_slots` row → the puller
(directory-driven) never probes a node it can't see. The PRUNE fix (C3) is *irrelevant* here because
there is no fresh row to preserve. The plan's pre-emptive `fleet_nodes`-is-optional framing and gate
bullet **require** this to work; the plan never reconciles them with Slice 3, and the proposed test
covers only the raw Slice-1 UPSERT. **Both falsifiers raise it independently** — the strongest
possible signal. The "the quad-server already has a row" and "Slice 1 lands first" escapes are
pre-rebutted by F1 (the gate names the no-row case; Slice 3 is committed v1, and a later slice must
not invalidate an earlier slice's gate). **Unrebutted → cannot clear → BC1.**

*Not `reject`:* dischargeable in one cycle by choosing **one** arbitration model (BC1 a–d) and
shipping the composed-path test.

### BC2 — Boot-epoch ratchet defeated by a NULL pull-write (LANDS, UNREBUTTED — blocker)

The `SET boot_epoch = EXCLUDED.boot_epoch` is the flaw: the puller cannot stamp a `boot_epoch`, so
its `EXCLUDED.boot_epoch` is `NULL`, and the moment it resumes a node after a self-pusher's lease
lapses — **the plan's own self-healing push→pull flip (Pillar 2)** — the `WHERE … EXCLUDED.boot_epoch
IS NULL` arm passes and the `SET` overwrites the stored integer with `NULL`. Now
`gpu_slots.boot_epoch IS NULL` admits any later strictly-stale write, including a **resurrected stale
self-pusher** — exactly the split-brain/replay the ratchet exists to refuse. The holder's C6 defense
covers only the `WHERE`'s pre-rollout inertness; the `SET`-overwrite is a **different mechanism** the
plan never addresses, so C6 is false-as-written for any push-then-pull row. **Unrebutted → BC2.**
Fix is a single token (`COALESCE`) plus a writer-side no-wipe test; the CASE column set and the
one-way intent are otherwise correct, so this is dischargeable, not a `reject`.

### BC5 — `fleet_meta` column-name mismatch (LANDS, UNREBUTTED — mechanical)

Slice-0 DDL declares `fleet_meta.puller`; the Slice-2 CAS `SET`s/matches/`RETURN`s `holder`. The CAS
errors `column "holder" does not exist` on Slice-2 deploy, breaking the puller and refuting C8. The
holder never reconciled the two fragments. Trivial, but it lands unrebutted and the puller-lease
tests (A/B) must run the **real** CAS against the **real** `009` DDL so this cannot recur. → BC5.

### BC3 — Puller-lease TTL vs the 45s age-out window (LANDS, REBUTTED — gate residual)

Real and binding, but the holder *engaged* the gate (test B asserts "rows stay fresh, do not age
out"), so it is **rebutted, not conceded** — the rebuttal is merely **unsupported**: no TTL value is
pinned and nothing constrains it below the 45s `live_slots`/`routable_slots` staleness window. If TTL
≥ 45s, the standby waits out the lease while no heartbeats are written and the fleet ages out before
failover completes — the No-SPOF gate's "does not age out" clause fails. → BC3: pin TTL strictly <
staleness window and make test B advance past the failover gap and assert no node leaves the
directory. (Does not block clearing on its own.)

### BC4 — Client wall-clock in the per-node driver-lease skip (LANDS, REBUTTED — gate residual)

Slice 3 describes the skip as a Python-side filter over `driven_by`/`lease_until` and never states
the freshness comparison is server-side. The plan's overall DB-clock ethos and the **server-side
Slice-2 puller-lease CAS** constitute an implicit rebuttal (the intent is clearly DB-clock), so this
is **rebutted, not conceded** — but the per-node skip is neither stated server-side nor tested, and
C12 is proven only for `heartbeat_ts` (test L). A skewed puller clock would double-write a
still-leased node (refuting C9) or skip a lapsed one (leaving it unmonitored). → BC4: move the
predicate into the FETCH SQL (`now() >= lease_until`) and add the no-client-timestamp test (the
driver-lease analog of `test_lease_no_consumer_clock.py`). (Does not block clearing on its own.)

---

## Required repairs (machine-readable in front-matter `constraints[]`)

| ID | Binding | Severity | Repair |
|----|---------|----------|--------|
| **BC1** | **yes (blocking gate)** | high | Resolve the zero-touch self-push deadlock: pick **one** arbitration model — (a) lease not stored exclusively on `fleet_nodes`, (b) push path atomically creates the `fleet_nodes` arbitration row, (c) the first registering UPSERT is not lease-gated (lease governs ongoing contention only), or (d) scope no-`fleet_nodes` push out and narrow the gate + C3 — and show C9 still holds. **Required** test: the **composed Slice-1+3** push path for a node with no `fleet_nodes` row registers (`unverified` → graduates) — or, under (d), a test pinning the narrowed pull-only scope. Restate C3/C9/gate-D. |
| **BC2** | **yes (blocking gate)** | high | `SET boot_epoch = COALESCE(EXCLUDED.boot_epoch, gpu_slots.boot_epoch)` (never erase/lower a recorded epoch). Restate C6 to cover the SET-overwrite path. **Required** PG test: a NULL-epoch (puller) write keeps a stored `boot_epoch=K`, and a strictly-stale (`< K`) write is still refused after any number of pull ticks. |
| **BC3** | recommended (policy) | medium | Pin the puller-lease deadman TTL strictly **shorter** than the 45s staleness window (e.g. ≤15s) and turn test B into a real failover-no-age-out proof (kill the holder, advance past the gap, assert no node leaves `routable_slots`/`live_slots`). |
| **BC4** | recommended (policy) | medium | Evaluate per-node lease freshness **server-side** in the FETCH SQL (`now() >= lease_until`); restate C12 to cover this decision; add a no-client-timestamp test (driver-lease analog of `test_lease_no_consumer_clock.py`). |
| **BC5** | recommended (policy) | low | Align `fleet_meta` column name across the DDL, the Slice-2 CAS, and the lease tests (one of `puller`/`holder`); run the real CAS against the real `009` DDL in tests A/B. |

---

## Why `needs_revision` (and not the alternatives)

- **Not `accept` / `accept_with_findings`:** a clearing verdict requires every landed challenge to
  have been rebutted in the trajectory (RFC 0094 §5 Check-B). Three challenges (BC1 ×2 falsifiers,
  BC2, BC5) are `landed_unrebutted` on named gate items. Waving them through as "the build will fix
  it" would ship a plan whose central zero-touch gate is **broken for the node it names** and whose
  replay ratchet is **defeated by its own self-healing flip** — exactly what the falsification gate
  exists to stop.
- **Not `reject`:** the design *can* satisfy its own falsifiable gate. BC1 is a one-of-four
  arbitration choice + a composed test; BC2 is a `COALESCE` + a test; BC3/BC4 are a TTL bound and a
  server-side predicate, each + a test; BC5 is a rename. All are well-scoped and fit one cycle. No
  undischargeable defect.
- **`needs_revision`** uses the workflow's re-falsification iteration for genuine, material,
  repairable defects — its intended purpose. An honest `needs_revision` with a truthful ledger is a
  **successful** gate outcome.

---

## Handoff to the holder (next cycle) — the minimal clearing diff

Revise `dialogue/holder/BUILD_PLAN.md` to discharge **BC1–BC2** (blockers) and fold in **BC3–BC5**:

1. **Fold BC1 into Slice 3 + the §3 gate→test map (clears the gate).** Choose one arbitration model
   so a no-`fleet_nodes` self-pusher registers; restate C3/C9/gate-D; add the **composed** Slice-1+3
   no-`fleet_nodes` registration test. This is the single change that removes the headline
   `landed_unrebutted` challenge.
2. **Fold BC2 into Slice 1 Change B + the §3 map.** `COALESCE` the `boot_epoch` SET; restate C6; add
   the push-stamp → pull-NULL-write → stale-refused PG test.
3. **Fold BC3 into Slice 2 + the §3 map.** Pin TTL < 45s; make test B prove no age-out across
   failover.
4. **Fold BC4 into Slice 3 + the §3 map.** Server-side freshness predicate; restate C12; add the
   no-client-timestamp test.
5. **Fold BC5 into Slice 0/2 + tests A/B.** One column name across DDL, CAS, and tests.

Preserve everything under **"What survived"** (C1, C2, C4, C5, C7, C10, C11, C12, the PRUNE fix, the
`di --json` boundary, peecee-pull-only, the live-infra inertness of §4) and do **not** re-open the
RFC's settled design (pull-first peer-runnable driver; push opt-in for trusted Linux nodes only;
registration = first heartbeat; measured-not-declared quarantine→graduate; `boot_epoch` ⟂ `epoch`).
The falsifiers then re-challenge the revised plan.
