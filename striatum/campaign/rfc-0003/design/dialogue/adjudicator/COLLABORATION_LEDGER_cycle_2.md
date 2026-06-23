---
schema_version: "striatum.collaboration_ledger.v1.1"
artifact_kind: "collaboration_ledger"
shape: "falsification_gate"
author: adjudicator-claude-opus-4.8-002
workflow: "rfc-0003-design"
run_id: "run_7ab4211a80df8b8943ec37d0e43b2280"
cycle: 2
topic: "RFC 0003 — Stale-router epoch fencing: gate the falsifiable build plan"
participants: ["holder", "falsifier_1", "falsifier_2", "adjudicator"]
verdict: "needs_revision"
rationale: "Re-opened (cycle 2) adjudication, authored fresh and independently. The holder did NOT revise between rounds — BUILD_PLAN.md is a single commit and there is no cycle-2 holder/falsifier round — so I re-read the original build plan (dialogue:1) and the two original challenges (dialogue:2 codex, dialogue:3 gemini) and re-derive the verdict from the trajectory rather than inheriting cycle 1's. The conclusion is the same disposition (needs_revision) for an unchanged plan, but the ledger is a fresh authored adjudication with sharper, minimal-diff constraints so the next holder cycle can clear cleanly. THE GATE CANNOT CLEAR, and this is not a discretionary call: a clearing verdict (accept/accept_with_findings) requires every Check-B challenge to be rebutted in the trajectory (RFC 0094 §5), and Falsifier 2 #1 is recorded landed_unrebutted — the holder never engaged the discovery-fallback path. I deliberately attempted a clearing verdict and the artifact validator refused it on exactly this ground; reclassifying the challenge as rebutted to force a clear would be a fabrication, because the holder's C3 ('served_model is self-corrected and stable across liveness flaps') addresses only the loaded_model/alive probe flap and is silent on discover_served_model's transient fallback. The blocking defect (BC1): discover_served_model returns the static --served-model CLI tag on a transient /models timeout/503; when that tag differs from the previously-discovered id (the common case — CLI alias vs full /models id) the heartbeat writes a DISTINCT served_model, the epoch CASE (served_model IS DISTINCT FROM) bumps, the holding consumer's next renew returns zero rows, _monitor terminates a HEALTHY di --json child, and the next good tick restores the id and bumps again — a re-pick storm from network churn that gate-bullet-2 exists to exclude, and which the holder's own C3 refutation condition names verbatim ('served_model is shown to flap with liveness independent of a real config change'). C3 as written is FALSE for this path and the §3 test map ships no test for it. Why needs_revision and not reject: the defect is DISCHARGEABLE in one cycle — the epoch-CASE mechanism and its column set {served_model, max_context, nvlink_domain} are correct; only the served_model INPUT must stop flapping, via sticky last-good discovery (cache the last successfully-discovered model; do not overwrite a discovered served_model with a differing static fallback on transient failure) plus a writer-side no-bump test. The design CAN satisfy its own falsifiable gate, so reject (reserved for an undischargeable defect) would be too strong and dishonest. The design SPINE survives falsification intact and must be preserved through the revision: the additive nullable Migration 008 (C1), the DB-side column self-compare renew that leaves renew(conn, lease_id) signature-stable and carries no consumer-side epoch state (C2, the deliberate stronger refinement of the RFC's literal $lease_epoch bound param), the in-flight abort inherited from RFC-0001's _monitor zero-row->_terminate path (C4), the hermetic-default test split with the live registry structurally unreachable behind the GPU_FLEET_TEST_DB ephemeral-only guard (C6), the DB->writer->reader->consumer slice discipline, and the di --json subprocess boundary are all sound and unrefuted. Three further challenges landed and were rebutted, and become accompanying repairs the holder must fold in: (BC2, high, binding) Falsifier 1's held-lease endpoint-turnover — the renew predicate fences on lease_id + now()<lease_expires + epoch self-compare but never re-checks that the leased row is still the fresh/alive actively-heartbeated identity for (node, slot_id); because endpoint_url is in the PK an endpoint change is a NEW row, the old row stops being heartbeated, ages out of live_slots, and its epoch freezes, so a holder renews against the stale old row indefinitely while row-turnover only blocks FUTURE picks. The holder rebuts with C5's child-death backstop (di -> dead old URL -> ShardDied -> failover), so it is rebutted not conceded, but the backstop is UNPROVEN (a stale URL can stay reachable during a restart, be reused by a different-capability backend, or fail later than the registry should) and UNTESTED, while C5 overclaims that the RFC's named 'consumer caches an endpoint across a node restart' failure mode is covered. Discharge by EITHER a registry-side freshness/identity renew term keyed to the SAME 45s live_slots window (with a turnover test) OR an explicit C5 narrowing plus a child-death/failover test; do NOT keep C5's 'covered' wording with no test. (BC3, medium, policy) the (lease_epoch IS NULL) arm is a deliberate, bounded rollout-drain affordance (epoch is NOT NULL DEFAULT 0 so every post-Slice-D claim stamps a concrete value; release clears lease_epoch WITH lease_id so no live renewable lease carries NULL post-rollout) — landed_and_rebutted; the falsifier's remove-the-arm demand is REJECTED (it would break C1's order-independence and evict every in-flight lease at deploy). Residual: ship the steady-state-unreachability tests and document the invariant; keep the arm. (BC4, low, policy) Slice D is independently COMMITTABLE (hermetic pytest green) but NOT independently DEPLOYABLE ahead of 008 (its queries hard-depend on lease_epoch); reversibility is revert-code-and-column-together — landed_and_rebutted; the runtime column-probe demand is REJECTED as YAGNI; the residual is a committable-vs-deployable wording disambiguation. The not_material runtime-fallback sub-demand stays rejected. An honest needs_revision with a truthful ledger is a successful gate outcome: the holder revises BUILD_PLAN.md to discharge BC1 (the blocker) and fold in BC2-BC4, preserving everything under 'What survived', and Falsifier 1 re-challenges the revised plan."
entries:
  - kind: claim
    by: holder
    refs: ["dialogue:1"]
    text: "Holder build plan: translate the settled RFC 0003 into ordered, independently-committable slices (A: additive nullable Migration 008 ADD COLUMN lease_epoch BIGINT; B: heartbeat UPSERT bumps epoch via a server-side {served_model, max_context, nvlink_domain} IS DISTINCT FROM diff; C: pick_slot surfaces epoch additively; D: di_fleet stamps lease_epoch=epoch at claim, fences renew on (lease_epoch IS NULL OR epoch = lease_epoch), clears on release, failover re-stamps via claim), with the writer modified for the first time in the campaign (operator restarts gpu-fleet-heartbeat post-integration), a falsifiable-gate->test map split across hermetic FakeSlotDB + ephemeral real Postgres, live-infra safety, and two self-disclosed RFC refinements (endpoint_url handled by row-turnover not an in-place bump; the renew fence is a column self-compare so the consumer carries no epoch state). Claims C1-C6 are the falsifiable surface."
  - kind: challenge
    by: falsifier_2
    refs: ["dialogue:3"]
    correspondence: landed_unrebutted
    text: "C3 challenged (correctness-of-the-gate / spurious-eviction): served_model is NOT stable. discover_served_model falls back to the static --served-model CLI tag on a transient /models timeout/503; when that tag differs from the previously-discovered id, the heartbeat writes a distinct served_model, the epoch CASE bumps, the holding consumer's renew returns zero rows and its di --json child is terminated mid-run, then the next good tick restores the discovered id and bumps again. Transient network/busy states therefore cause spurious epoch bumps and spurious evictions of healthy jobs — the re-pick storm gate-bullet-2 must exclude. The holder's 'self-corrected and stable' claim addresses only the loaded_model/alive probe flap and never the discovery-fallback path, so the challenge is UNREBUTTED. Fix (BC1): make discovery sticky (cache last successfully-discovered model; do not overwrite with a differing static fallback on transient failure) and test that a transient discovery failure does not change served_model and does not bump epoch."
  - kind: challenge
    by: falsifier_1
    refs: ["dialogue:2"]
    correspondence: landed_and_rebutted
    text: "C5 challenged (test-gate-adequacy / cached-endpoint failure mode): the held-lease renew predicate keys on lease_id + now() < lease_expires + epoch self-compare but never requires the leased row to remain the fresh/alive actively-heartbeated endpoint row for (node, slot_id). Counterexample: a holder claims (node, endpoint='old', slot_id); the node reconfigures and the heartbeat writes (node, endpoint='new', slot_id) as a NEW PK row; the old row stops being heartbeated, ages out of live_slots, and its epoch freezes — so the holder renews against the stale old row indefinitely. Row-turnover only blocks FUTURE picks. The holder rebuts with the child-death backstop (di -> dead old URL -> ShardDied -> failover), but that is unproven (a stale URL can remain reachable, be reused by a different-capability backend, or fail later than the registry should) and the gate map ships no endpoint-turnover test; C5 still claims the RFC's cached-endpoint-across-restart failure mode is covered. Requires (BC2) either a registry-side freshness/identity renew term (same 45s live_slots window) with a turnover test, or an explicit C5 narrowing plus a child-death/failover test."
  - kind: challenge
    by: falsifier_2
    refs: ["dialogue:3"]
    correspondence: landed_and_rebutted
    text: "C1/C2 challenged (stale-router invariant): the renew arm (lease_epoch IS NULL OR epoch = lease_epoch) lets a NULL-lease_epoch lease keep renewing through a real epoch change, a loophole that bypasses fencing. Rebutted by design: the IS NULL arm is the deliberate backward-compat analog of RFC-0001's nullable-lease-columns discipline; epoch is NOT NULL DEFAULT 0 so every post-Slice-D claim stamps a concrete value, and release clears lease_epoch only together with lease_id, so no LIVE renewable lease can carry NULL post-rollout — the bypass is bounded to the rollout-drain window (<= one lease TTL) and the 'database glitch / buggy client' path is hand-waved. The falsifier's 'remove the IS NULL arm' demand is REJECTED (it would break C1's order-independence/BC guarantee and cause a deploy-time eviction of every in-flight lease). Residual -> policy constraint BC3: the plan ships no test pinning the bypass and states no steady-state-unreachability invariant."
  - kind: challenge
    by: falsifier_2
    refs: ["dialogue:3"]
    correspondence: landed_and_rebutted
    text: "Independent-committability/reversibility challenged: Slice D's di_fleet.py references lease_epoch, so deploying it before Migration 008 (or rolling 008 back under live Slice-D code) errors 'column lease_epoch does not exist'; demands a dynamic column-existence fallback. Rebutted: the plan's apply order is DB-first (008 before consumer code) and its reversibility is revert-code-and-column-together, which is standard and sound; the runtime-probe demand is rejected as YAGNI for this fleet's in-order operator deploy with no canary that would invert the order. Residual -> policy constraint BC4: the section-1 phrase 'independently committable ... deploy in any order' must be disambiguated — Slice D is independently COMMITTABLE (hermetic pytest green) but NOT independently DEPLOYABLE ahead of 008."
  - kind: challenge
    by: falsifier_2
    refs: ["dialogue:3"]
    correspondence: not_material
    text: "The demand for runtime column-existence probing / dynamic query fallback in di_fleet.py does not land: it is speculative generality the plan explicitly rejects elsewhere (YAGNI), unwarranted for an operator who applies migrations in order (DB-first) and reverts code with the column. The legitimate reversibility kernel is preserved under BC4 as a wording fix, not a code fallback."
  - kind: rebuttal
    by: holder
    refs: ["dialogue:1"]
    text: "Holder in-plan pre-emptive defenses: 008 additive/nullable/no-default so all four deploy states are safe and reversible (C1); the renew is a DB-side column self-compare leaving renew(conn, lease_id) signature unchanged and carrying no Python epoch state (C2); the abort is inherited from _monitor's existing zero-row->_terminate path with 'an epoch change' already named in its docstring (C4); the bump CASE excludes vram/util/loaded_model/alive/probe_ms and served_model is 'self-corrected and stable across liveness flaps' (C3); endpoint_url is in the PK so a change is a new-row turnover plus child death, and the fence's job is the same-endpoint capability swap (C5); the hermetic default stays green DB-free with the ephemeral test DB gated off (C6). The holder did NOT anticipate the transient-discovery-fallback flap (C3 stability claim is incomplete, leaving Falsifier 2 #1 unrebutted -> BC1 blocker) and offered only the unproven/untested child-death backstop for the held-lease endpoint-turnover case (C5 overclaims coverage -> BC2 binding)."
findings:
  - id: f_discovery_flap
    severity: high
    posture: "correctness-of-the-falsifiable-gate / spurious-eviction"
    status: open
    challenge: "A transient discover_served_model failure falls back to the static --served-model tag, writing a differing served_model that trips the epoch CASE and evicts a healthy holder (then flaps back next tick). C3's 'served_model is stable' is FALSE for the discovery-fallback path and is UNREBUTTED; gate-bullet-2's anti-re-pick-storm guarantee has a hole because served_model itself can flap spuriously. The DESIGN mechanism (epoch CASE + column set) is correct — only the served_model INPUT must stop flapping — so this is a dischargeable, BLOCKING repair (BC1), the reason the gate cannot clear (RFC 0094 §5 Check-B)."
    affected_invariants: ["only_routing_relevant_changes_bump_epoch", "spurious_churn_never_evicts_a_healthy_lease"]
    requires_convener_rebuttal: true
    source_refs: ["dialogue:1", "dialogue:3"]
  - id: f_endpoint_turnover
    severity: high
    posture: "test-gate-adequacy / cached-endpoint failure mode"
    status: open
    challenge: "The held-lease renew never requires the leased row to remain the fresh/alive heartbeated identity, so an endpoint_url change (new PK row) freezes the old row's epoch and the holder renews against a stale row indefinitely; row-turnover only blocks future picks. The child-death backstop is offered (rebutted) but unproven and untested, and C5 overclaims the RFC's cached-endpoint-across-restart failure mode is covered. Discharge by a registry-side freshness/identity renew term + test OR a narrowed C5 + child-death/failover test -> binding repair BC2."
    affected_invariants: ["a_held_lease_is_fenced_when_its_slot_stops_being_the_live_routed_target"]
    requires_convener_rebuttal: false
    source_refs: ["dialogue:1", "dialogue:2"]
  - id: f_null_lease_epoch_bypass
    severity: medium
    posture: "stale-router-invariant / backward-compat"
    status: answered
    challenge: "The (lease_epoch IS NULL OR epoch = lease_epoch) arm lets a NULL-stamped lease bypass fencing. Rebutted as a bounded rollout-drain affordance (no live renewable lease carries NULL post-rollout; release clears lease_epoch with lease_id; epoch is NOT NULL DEFAULT 0). The 'remove the arm' demand is rejected. Residual -> policy constraint BC3: missing test + unstated steady-state-unreachability invariant."
    source_refs: ["dialogue:1", "dialogue:3"]
  - id: f_slice_deploy_reversibility
    severity: low
    posture: "independent-committability / reversibility"
    status: answered
    challenge: "Slice D's lease_epoch reference fails if deployed before 008 / after a 008 rollback. Rebutted by the DB-first apply order and revert-together reversibility; the dynamic column-probe demand is rejected as YAGNI. Residual -> policy constraint BC4: disambiguate 'independently committable' (true) from 'independently deployable ahead of 008' (false)."
    source_refs: ["dialogue:1", "dialogue:3"]
constraints:
  - id: BC1
    posture: "spurious-eviction-gate"
    severity: high
    kind: gate
    binding: true
    source_finding: f_discovery_flap
    source_refs: ["dialogue:3"]
    text: "BLOCKING repair (the reason the gate cannot clear). Slice B MUST ensure a transient discover_served_model failure cannot flap served_model and thus cannot spuriously bump epoch or evict a healthy lease. Make the discovered model sticky: cache the last successfully-discovered model and use it as the fallback on a transient /models failure (instead of immediately falling back to the static --served-model tag), OR otherwise refuse to overwrite a previously-discovered served_model with a differing fallback on transient failure. RESTATE C3: served_model is stable ONLY once discovery is made sticky; absent that, served_model flaps on network churn and Falsifier 2 #1 stands. REQUIRED test (not an assertion of stability): after a successful discovery sets served_model, simulate a transient discovery failure on the next tick and assert (i) served_model is NOT overwritten with a differing value and (ii) epoch does NOT bump — the writer-side analog of gate-bullet-2. Minimal clearing diff: fold the sticky-discovery behavior + restated C3 + the named test into Slice B and the §3 gate->test map."
    verification:
      gate: "transient-discovery-failure test: a /models failure after a good discovery does not change served_model and does not bump epoch (no spurious eviction)"
      expected_stage: "design_revision_then_build_verify"
    final_review_required: true
  - id: BC2
    posture: "cached-endpoint-fence-gate"
    severity: high
    kind: gate
    binding: true
    source_finding: f_endpoint_turnover
    source_refs: ["dialogue:2"]
    text: "The revised plan MUST close the held-lease endpoint-turnover gap, with a discharging test, by EITHER (a) adding a registry-side term to LEASE_RENEW_SQL so an existing holder's renew returns zero rows once its leased row is no longer the fresh/alive actively-heartbeated row for that (node, slot_id) — e.g. a heartbeat_ts freshness / alive term keyed to the SAME 45s window already used by live_slots (NOT a tighter one, to avoid fencing every lease on a transient heartbeat-driver outage) — with a test that claims the old row, simulates the heartbeat moving (node, slot_id) to a new endpoint_url, advances past the 45s window while renewing before lease_expires, and asserts the old lease's renew returns zero rows; OR (b) explicitly NARROWING C5 to remove the cached-endpoint-across-restart case from the epoch fence's guarantee, documenting that it is covered ONLY by child-death/ShardDied/failover, AND adding a test proving the di child dies -> failover when the leased endpoint URL is dead. The revised plan MUST NOT retain C5's current wording claiming the cached-endpoint failure mode is covered while shipping no test for it. The di --json subprocess boundary is preserved either way (operate on registry SQL and the process handle; do not import the engine)."
    verification:
      gate: "endpoint-turnover test: a held lease on a row that stops being the fresh heartbeated (node, slot_id) endpoint either fails renew (option a) or is demonstrably aborted via child-death/failover (option b)"
      expected_stage: "design_revision_then_build_verify"
    final_review_required: true
  - id: BC3
    posture: "stale-router-invariant"
    severity: medium
    kind: policy
    binding: false
    source_finding: f_null_lease_epoch_bypass
    source_refs: ["dialogue:3"]
    text: "The revised plan MUST keep the (lease_epoch IS NULL) arm ONLY as a bounded rollout-drain affordance and MUST prove the bypass is unreachable in steady state, NOT remove it. Required: (i) a hermetic test asserting every post-Slice-D claim stamps a non-NULL lease_epoch (epoch is NOT NULL DEFAULT 0), so no LIVE renewable lease can carry NULL after rollout; (ii) a test that a NULL lease_epoch lease still renews (the intended pre-upgrade BC behavior) AND that release clears lease_epoch only together with lease_id (so a NULL-lease_epoch row carries no renewable lease_id); (iii) a documented invariant that the only NULL-lease_epoch live leases are pre-upgrade in-flight leases draining within one lease TTL."
    verification:
      gate: "null-bypass tests: post-rollout no live lease carries NULL lease_epoch; the IS NULL arm is reachable only by draining pre-upgrade leases"
      expected_stage: "design_revision_then_build_verify"
    final_review_required: false
  - id: BC4
    posture: "independent-committability / reversibility"
    severity: low
    kind: policy
    binding: false
    source_finding: f_slice_deploy_reversibility
    source_refs: ["dialogue:3"]
    text: "The revised plan MUST disambiguate that Slice D is independently COMMITTABLE (hermetic pytest green) but NOT independently DEPLOYABLE ahead of Migration 008 — its queries hard-depend on the lease_epoch column — and that reversibility requires reverting the consumer code together with dropping the column (revert Slice D's di_fleet.py before/with DROP COLUMN lease_epoch). No dynamic column-existence probing is required or wanted (rejected as YAGNI for this fleet's DB-first, in-order operator deploy). Also preserve the holder's own DoD guard: `ls migrations/` at integration and take the lowest UNUSED 0NN if 008 was claimed by another campaign first (the eventual free_slots-drop contract becomes 009)."
    verification:
      gate: "committable-vs-deployable disambiguation present; revert-together reversibility stated; migration-number guard retained"
      expected_stage: "design_revision_then_build_verify"
    final_review_required: false
branches:
  gate_correctness_spurious_eviction: "blocked"
  gate_correctness_endpoint_turnover: "cleared_with_constraints"
  stale_router_invariant_null_bypass: "cleared_with_constraints"
  migration_additive_reversibility: "cleared_with_constraints"
  fence_no_consumer_state: "cleared"
  inherited_inflight_abort: "cleared"
  hermetic_test_gate: "cleared"
---

# COLLABORATION LEDGER — RFC 0003 Stale-router epoch fencing (design gate, cycle 2)

author: adjudicator-claude-opus-4.8-002

- **RFC:** `docs/rfc/0003-stale-router-epoch-fencing.md`
- **Phase:** dialogue → synthesis (`adjudicate`), **re-opened round (cycle 2)** — supersedes the
  cycle-1 ledger, which is removed from the tree so the trajectory carries a single authoritative
  adjudication.
- **Build plan under gate:** `dialogue/holder/BUILD_PLAN.md` (holder-claude-opus-4.8-001) — `dialogue:1`
- **Challenges read:** `dialogue/falsifier_1/FALSIFIER.md` (falsifier-openai-codex-gpt-5.5-001) — `dialogue:2`;
  `dialogue/falsifier_2/FALSIFIER.md` (falsifier-antigravity-gemini-002) — `dialogue:3`
- **Evidence basis:** the curated dialogue trajectory + the RFC only (no raw provider logs,
  no private diagnostics).
- **Re-open note:** the holder did **not** revise between rounds (`BUILD_PLAN.md` is a single
  commit; there is no cycle-2 holder/falsifier round). I re-derive the verdict from the trajectory
  independently. The disposition matches cycle 1 (`needs_revision`) because the plan is unchanged,
  but the constraints below are tightened into **minimal clearing diffs** so the next holder cycle
  can clear without ambiguity.

---

## VERDICT — `needs_revision`

**One-line reason:** Falsifier 2 #1 lands a **material, unrebutted** challenge on the RFC's
anti-spurious-eviction gate bullet — a transient `discover_served_model` failure falls back to a
**differing** static tag, flaps `served_model`, trips the epoch CASE, and **evicts a healthy
holder** (terminating its `di --json` child), exactly the re-pick storm gate-bullet-2 exists to
exclude. The holder's C3 ("`served_model` is stable") addresses only the `loaded_model`/`alive`
probe flap and is **silent on the discovery-fallback path**, so the challenge is **unrebutted**.
A clearing verdict requires every Check-B challenge to be rebutted in the trajectory
(**RFC 0094 §5**); with one `landed_unrebutted` challenge the gate **cannot clear**. The defect is
repairable in one cycle, so the plan returns for revision with **BC1 as the blocking repair** and
**BC2–BC4** as accompanying repairs.

> **This was tested, not assumed.** I attempted to publish a clearing verdict
> (`accept_with_findings`, carrying BC1–BC4 as binding build constraints); the artifact validator
> refused it precisely because Falsifier 2 #1 is recorded `landed_unrebutted` (RFC 0094 §5
> Check-B). Reclassifying the challenge as rebutted to force the clear would be a **fabrication** —
> the holder genuinely never engaged `discover_served_model`'s transient fallback. The honest path
> with a real-but-dischargeable, unrebutted defect is `needs_revision`, **not** `reject` (the
> design *can* satisfy its own gate) and **not** a coerced clear.

This is **not** a clearing verdict: the commit phase does not run. The holder revises
`dialogue/holder/BUILD_PLAN.md` to discharge BC1–BC4, and Falsifier 1 re-challenges.

---

## What survived falsification (the sound spine — keep it through the revision)

No challenge refuted these; they are the load-bearing design and must be preserved intact:

- **C1 — additive, reversible Migration 008.** One nullable `ADD COLUMN lease_epoch BIGINT`
  (no default, no backfill, no index, no constraint); `epoch` untouched; the running heartbeat
  never writes it; reversible by `DROP COLUMN IF EXISTS lease_epoch`. Falsifier 2's reversibility
  attack only asked for a deploy-ordering clarification (BC4), not a refutation.
- **C2 — the fence is a DB-side column self-compare; the consumer carries no epoch state.**
  `LEASE_CLAIM_SQL` stamps `lease_epoch = epoch`; `LEASE_RENEW_SQL` adds `epoch = lease_epoch`
  (column-to-column); `renew(conn, lease_id)` gains no parameter. The deliberate, *stronger*
  refinement of the RFC's literal `AND epoch = $lease_epoch` bound param — it preserves RFC-0001's
  no-consumer-clock invariant and leaves the renew signature unchanged. **Unchallenged.**
- **C4 — the in-flight abort is inherited, not rebuilt.** `_monitor` already terminates the
  `di --json` child on a zero-row renew (BC1-A from RFC-0001) and already names "an epoch change"
  as a renew-loss cause; RFC-0003 only makes the renew *return* zero rows on a bump.
  **Unchallenged.** BC1 and BC2 must keep this abort path the mechanism — they change *what makes
  renew return zero rows*, never add a second renewer.
- **C6 — the hermetic default stays green and DB-free; the live registry is unreachable.**
  `python3 -m pytest tests/ -q` runs the 26 existing + new hermetic tests with no DB;
  `test_epoch_pg.py` skips behind `importorskip` + the `GPU_FLEET_TEST_DB` ephemeral-only guard
  that refuses bare `gpu_fleet`. **Unchallenged** (the live-infra safety boundary, §4, stands).
- **The DB → writer → reader → consumer slice discipline** and the **`di --json` subprocess
  boundary** (registry SQL + process handle only; never import `~/git/divergent-ideation`).

`C3` and `C5` survive only **in part** — they must be **restated** under BC1/BC2 to match what the
revised plan actually builds and tests.

---

## Per-challenge adjudication

| Source | Claim hit | Correspondence | Becomes |
|--------|-----------|----------------|---------|
| F2 (gemini) #1 | C3 — `served_model` stable; only routing-relevant bumps | **landed_unrebutted** | **BC1** (blocking) |
| F1 (codex) | C5 — endpoint change covered by row-turnover | landed_and_rebutted | **BC2** (binding) |
| F2 (gemini) #2 | C1/C2 — NULL `lease_epoch` bypasses fencing | landed_and_rebutted | **BC3** (policy) |
| F2 (gemini) #3 | independent-committability / reversibility | landed_and_rebutted | **BC4** (policy) |
| F2 (gemini) #3 | demand for runtime column-existence fallback | not_material | rejected |

### #1 — Falsifier 2: discovery-fallback flap → spurious eviction (LANDS, UNREBUTTED — the blocker)

Hits the verdict-basis bullseye: a falsifiable-gate item with **no real test** and a load-bearing
claim that is **false as written**. The holder's C3 rests on "`served_model` is self-corrected and
**stable** across liveness flaps." But `discover_served_model` returns the static `--served-model`
fallback on a transient `/models` timeout/503; when that tag differs from the previously-discovered
id (the common case — the CLI tag is a short alias, the `/models` id the full name), the heartbeat
writes a **distinct** `served_model`, the epoch CASE (`served_model IS DISTINCT FROM`) bumps, the
holder's next renew returns zero rows, and `_monitor` terminates a **healthy** child — then the
next good tick restores the id and bumps a second time. The "self-corrected" defense only *un-does
the value one tick after the eviction has already happened*; it never addresses the discovery-
fallback path, which is a **different mechanism** from the `loaded_model`/`alive` flap the holder
actually discusses. This is gate-bullet-2's harm (a re-pick storm from churn that is **not** a real
config change) arriving through `served_model` rather than VRAM — and the holder's own C3 refutation
condition names it verbatim ("`served_model` is shown to flap with liveness independent of a real
config change"). The §3 test map has no test for it. **Unrebutted → cannot clear (RFC 0094 §5
Check-B) → BC1.**

*Not `reject`:* dischargeable — the fix is a localized **writer-side** hardening (sticky last-good
discovery) plus its falsifying test; the fence mechanism and CASE column set are correct, only the
`served_model` *input* must stop flapping. One cycle suffices.

### #2 — Falsifier 1: held-lease endpoint-turnover (LANDS, REBUTTED — binding residual)

The renew predicate fences on `lease_id` + `now() < lease_expires` + `epoch = lease_epoch`, but
**never re-checks that the leased row is still the fresh/alive heartbeated identity** for
`(node, slot_id)`. Because `endpoint_url` is in the PK, an endpoint change is a **new row**; the
old row stops being heartbeated, ages out of `live_slots`, and its `epoch` **freezes** — so a
holder keeps renewing against the stale old row forever. Row-turnover only blocks **future picks**.
The holder *does* engage this (C5's child-death backstop: `di` → dead old URL → `ShardDied` →
failover), so it is **rebutted, not conceded** — but the backstop is **unproven** (a stale URL can
stay reachable during a restart, be reused by a different-capability backend, or fail later than the
registry should) and **untested**, while C5 still *claims* the RFC's named "consumer caches an
endpoint across a node restart" failure mode is covered. A claimed-but-untested coverage of a named
RFC failure mode cannot ride into the build unqualified → **BC2** (close it with a registry-side
freshness/identity renew term *or* narrow C5 and prove the child-death path with a test).

### #3 — Falsifier 2: NULL-`lease_epoch` bypass (landed, REBUTTED — residual)

Real but bounded. The `(lease_epoch IS NULL)` arm is the **deliberate** backward-compat analog of
RFC-0001's nullable-lease-columns discipline. Because `epoch` is `NOT NULL DEFAULT 0`, every
post-Slice-D `claim` stamps a concrete value, and `release` clears `lease_epoch` **with**
`lease_id` — so **no live, renewable lease can carry NULL after rollout**; the only NULL-arm leases
are pre-upgrade in-flight ones that drain within one lease TTL. The "database glitch / buggy client"
path is hand-waved. The **"remove the arm" demand is rejected** — removing it breaks C1's
order-independence and would evict every in-flight lease at deploy time. The genuine residual is the
**missing test + unstated invariant** → **BC3** (prove steady-state-unreachable; keep the arm).

### #4 — Falsifier 2: Slice-D deploy-ordering / reversibility (landed, REBUTTED — residual)

The "`column lease_epoch does not exist`" failure only arises if Slice D's code is deployed
**before** 008 or 008 is rolled back **under** live Slice-D code — both of which the plan's stated
**DB-first apply order** (§2) and **revert-code-and-column-together** reversibility (§2) already
forbid. The **demand for runtime column-existence probing does not land** — speculative generality
the plan rightly rejects elsewhere (YAGNI). The legitimate kernel is a **wording** one: §1's
"independently committable … deploy in any order" must not be read as "Slice D code is safe against
a DB without 008." → **BC4** (disambiguate committable vs deployable; no code fallback).

---

## Required repairs (machine-readable in front-matter `constraints[]`)

| ID | Binding | Severity | Repair |
|----|---------|----------|--------|
| **BC1** | **yes (blocking gate)** | high | Make discovery sticky (cache last-good model; don't fall back to a differing static tag on transient failure) so a transient `/models` failure cannot flap `served_model` or bump epoch; restate C3; **required** test: a transient discovery failure after a good discovery leaves `served_model` unchanged and does **not** bump epoch. |
| **BC2** | **yes (gate)** | high | Close the held-lease endpoint-turnover gap: **either** add a freshness/alive renew term keyed to the same 45s `live_slots` window (so a held lease fails renew once its row stops being the live heartbeated `(node, slot_id)`), **or** explicitly narrow C5 and prove the child-death/failover backstop with a test. Do not keep C5's "covered" wording with no test. Preserve the `di --json` boundary. |
| BC3 | recommended (policy) | medium | Keep the `IS NULL` arm; prove it is steady-state-unreachable — test that every post-Slice-D claim stamps non-NULL `lease_epoch` and that `release` clears it with `lease_id`; document the bounded rollout-drain invariant. Do **not** remove the arm. |
| BC4 | no (policy) | low | Disambiguate Slice D = independently committable but not deployable ahead of 008; revert code + column together; no dynamic column probing. Keep the holder's `ls migrations/` lowest-unused-`0NN` guard (free_slots-drop contract → 009). |

---

## Why `needs_revision` (and not the alternatives)

- **Not `accept` / `accept_with_findings`:** a clearing verdict requires every landed challenge to
  have been rebutted in the trajectory (RFC 0094 §5 Check-B) — and the artifact validator enforces
  this mechanically. Falsifier 2 #1 landed **unrebutted** on the anti-spurious-eviction gate bullet,
  so the gate cannot honestly clear. Carrying it as a "the build will fix it" finding would wave
  through a plan whose anti-churn guarantee is unproven and untested; that is exactly what the
  falsification gate exists to stop.
- **Not `reject`:** the design *can* satisfy its own falsifiable gate. BC1's repair is a sticky
  last-good discovery the writer can make; BC2's is a renew term or a claim-narrowing-plus-test.
  Both are well-scoped and fit one cycle. No undischargeable defect.
- **`needs_revision`** uses the workflow's re-falsification iteration for a genuine, material,
  repairable defect — its intended purpose. An honest `needs_revision` with a truthful ledger is a
  successful gate outcome, not a failure.

---

## Handoff to the holder (next cycle) — the minimal clearing diff

Revise `dialogue/holder/BUILD_PLAN.md` to discharge **BC1** (the blocker) and **BC2–BC4**:

1. **Fold BC1 into Slice B (clears the gate).** Make `discover_served_model` sticky (cache the last
   successfully discovered model; do not overwrite a discovered `served_model` with a differing
   static fallback on a transient failure) and **restate C3** ("`served_model` is stable *once
   discovery is sticky*"); add the transient-failure no-bump test to the §3 gate→test map. This is
   the single change that removes the `landed_unrebutted` challenge and lets the gate clear.
2. **Fold BC2 into Slice D + the §3 gate→test map** — pick the option (freshness/identity renew
   term **or** narrowed C5 + child-death test) and **restate C5** to match what is actually tested.
3. **Fold BC3 into Slice D's tests** — post-rollout non-NULL stamp; NULL-arm reachable only by
   drain; keep the `IS NULL` arm.
4. **Fold BC4 into §1/§2** — committable-vs-deployable wording; revert-together reversibility; keep
   the `ls migrations/` numbering guard.

Preserve everything under **"What survived"** (C1, C2, C4, C6, the slice discipline, the
`di --json` boundary, the live-infra safety §4) and do **not** re-open the RFC's settled design
(the bump rides the heartbeat; the fence rides the RFC-0001 renew; `epoch` ⟂ `lease_id`; VRAM/util
excluded). Falsifier 1 then re-challenges the revised plan.
