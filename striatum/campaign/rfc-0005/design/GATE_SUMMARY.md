---
schema_version: "striatum.synthesis.v1"
artifact_kind: "synthesis"
---

# GATE SUMMARY — RFC 0005: Exporter-fed capacity signal (probe-anchored)

author: adjudicator-claude-opus-4.8-005

The design phase of RFC 0005 is **closed and cleared for build**. This summary records the
gate verdict, the falsifier challenges that became binding constraints, the committed build
plan the build run must execute, and the residual risk the operator should watch. Both gate
records — the adjudicator's `needs_revision` ledger and the operator decision that
supersedes it — are reported faithfully; neither is hidden.

- **RFC:** `docs/rfc/0005-exporter-capacity-signal.md` (settled design)
- **Run / workflow:** `run_0e0a6f7601cc744dec24f48b43bea9e1` · `rfc-0005-design` · branch
  `striatum/rfc-0005-design`

---

## 1. Verdict and one-line reason

**Native adjudication verdict (last recorded): `needs_revision`** —
`dialogue/adjudicator/COLLABORATION_LEDGER_cycle_3.md` (`adjudicator-claude-opus-4.8-004`,
cycle 3).

> **One-line reason:** Falsifier 1 landed a material, `landed_unrebutted` challenge on the
> RFC's central reader-side headroom invariant (**BC1** — Slice 3 ships the headroom SQL but
> no production path supplies `model_footprint`/`max_context`, references an undefined
> `kv_bytes` symbol, and leaves the `di --json` boundary unreconciled), so under RFC 0094 §5
> Check-B no clearing verdict could issue; but the defect is **dischargeable in one cycle**
> and the **design spine survived falsification intact**, so the honest classification is
> `needs_revision`, never `reject`.

**Gate clearance (the clearing instrument): operator decision, `accepted_with_follow_up`** —
`OPERATOR_DECISION_BC1_override.md` (`decision_id rfc-0005-design-override-bc1`,
`owner: human`, `2026-06-26T23:46:34Z`).

The gate **did not clear by a native `accept`/`accept_with_findings`**. It cleared by an
operator decision that **supersedes** the cycle-3 `needs_revision` on exactly the grounds
the ledger recorded:

- the **design spine is sound** (everything under "What survived" cleared both falsifiers);
- **BC1 is dischargeable in one build cycle** without re-opening the settled RFC; and
- the gate was stuck only because the workflow revision loop's declared budget
  (`cycles[0].max_iterations = 2`) was **spent** — the process finding
  `f_revision_loop_exhausted`, a template routing limitation, **not** a design rejection.

The decision is honest, not a forced clear: it does **not** relabel BC1 as rebutted (that
would be mechanically refused at publish under Check-B). It **accepts BC1–BC5 as binding
BUILD constraints** and moves BC1's *discharge* into the build stage under the independent
falsifiable-gate verifier — precisely the resolution path the adjudicator named.

---

## 2. Which falsifier challenges landed → binding constraints

The cycle-3 ledger converted every landed challenge into a binding constraint (BC). **BC1**
is the blocker; **BC1 + BC2** are gate constraints the **independent build verifier MUST
confirm before `accept`**; **BC3–BC5** are policy constraints carried as must-pass build
tests.

| BC | Source challenge | Correspondence | Sev / kind | Binding (verifier final review) |
|----|------------------|----------------|-----------|---------------------------------|
| **BC1** | F1 (codex) — Slice 3 reader-side headroom has **no production path**; `kv_bytes` undefined; `di --json` boundary unreconciled (32k and 4k requests route identically) | **landed_unrebutted** | high / gate | **yes — required** |
| **BC2** | F2 (gemini) #4 — freshness decay compares node-clock `fast_source_ts` vs DB-clock `heartbeat_ts` (cross-clock); NTP skew spuriously decays fresh capacity | landed_and_rebutted | high / gate | **yes — required** |
| **BC3** | F2 #2 — `live_slowdown_factor = probe_ms / cold_probe_ms` crashes on `None`/`0` (incl. every ollama-ondemand residency-only tick by design) | landed_and_rebutted | medium / policy | no |
| **BC4** | F2 #1 — the puller (`heartbeat_all.py`) never writes the companion, so pull-mode slots (incl. **peecee**, Principle 3's motivating host) are blind | landed_and_rebutted | medium / policy | no |
| **BC5** | F2 #3 — slices claimed "independently committable … either deploy order" but Slice 2 has a **hard 010 precondition** (`mig`/`ecc` ride the unguarded liveness UPSERT) | landed_and_rebutted | low / policy | no |

**What survived falsification (the spine — preserve through the build, do not re-open):**
**C-EPOCH** (fast capacity bands never bump `epoch`, gate only NEW claims; only slow
capability bands `mig_mode`/`ecc_mode` bump `epoch` and fence held leases — dissolving the
self-abort loop); **C3** companion-table fault isolation (LEFT JOIN + separate
savepoint-guarded write); **C4** `effective_free = LEAST(probe_floor, exporter_free)`
probe-anchoring; **OQ-P** phantom shrinks `effective_free` rather than minting a self-lease;
**C5** fleet-floor dead-man guard; **C1/C2** additive/reversible Migration `010` at the
lowest-unused number; **OQ-B** residency-only `ollama-ondemand` floor never force-loads; and
the live-infra-inert posture.

**Folded-in late challenges (attempt-3 falsifiers vs the revised plan).** After the
`needs_revision` ledger, a fresh holder lane delivered the revision now on the trajectory
(`dialogue/holder/BUILD_PLAN.md`, `holder-claude-opus-4.8-003`), which discharges BC1–BC5 in
plan-text. The attempt-3 falsifiers (`falsifier-openai-codex-gpt-5.5-003`,
`falsifier-antigravity-gemini-003`) landed three further code-grounded defects plus a
robustness reinforcement, all already folded into the committed plan:
**F-CARD** (`capacity_policy` must be a true singleton or the policy join multiplies slot
rows), **F-KEYS** (all three row-builders — `heartbeat_once`, `probe_node`, `_failed_row` —
must carry `mig_mode`/`ecc_mode` or the puller `KeyError`s), **F-LOCK** (PICK must keep
`FROM gpu_slots` as the base relation with `FOR UPDATE OF gpu_slots SKIP LOCKED`; the
`capacity_slots` view is read-only/diagnostic, never locked), and **F-BASE** (the cold
baseline is sticky in the DB so a process restart never recaptures a hot baseline).

---

## 3. The committed build plan the build run MUST execute

➡️ **`striatum/campaign/rfc-0005/design/COMMITTED_PLAN.md`** (`committer-claude-opus-4.8-001`).

It is the holder's revised cycle-3 build plan (`dialogue/holder/BUILD_PLAN.md`,
`holder-claude-opus-4.8-003`) **amended with every binding constraint folded into its slices
and §3 gate→test map** — the self-contained contract for the build run: the ordered,
independently-committable slices (Slice 0 DB / Migration `010` → Slice 1 Writer A → Slice 2
Writer B → Slice 3 Reader), the schema + DB→writer→reader apply order, the falsifiable-gate →
test map, and the `di --json` / live-infra boundaries.

**Verifier gate before `accept` (operator-directed):**

- **BC1** — the build MUST implement the request-capacity contract and add the **e2e
  `di_fleet.main()` 32k-vs-4k falsifying test** (a 32k request refused and a 4k request
  accepted on the **same** slot whose `effective_free` sits between the two headroom
  thresholds; `pick` + first-attempt claim + failover claim all receive non-default
  `model_mib`/`max_context`; `kv_bytes` resolves to a defined symbol; no engine import, no
  live-hardware read).
- **BC2** — the build MUST ship **both** the skew-resistance test and the frozen-source-decay
  test for single-clock freshness.
- BC3/BC4/BC5 ride as must-pass build tests (probe-`None` / cold-ollama-ondemand;
  puller-writes-companion integration; committable-vs-deployable + the Slice 2 `010`
  precondition).

---

## 4. Residual follow-up and risk to watch during the build

1. **The gate cleared by override, so BC1's discharge is owed in the build, not the design.**
   The independent build falsifiable-gate verifier is the backstop: it **must not `accept`**
   until the BC1 e2e (32k-vs-4k) test and the BC2 skew+frozen tests are green. A defaulted
   kwarg production never populates does **not** satisfy BC1 — the same capacity inputs must
   thread through `route_slots`/pick, first-attempt claim, **and** failover claim.

2. **BC1 sourcing has a hard boundary + escalation path.** Source `model_footprint`/
   `max_context` at the di-fleet layer (argv `--model`/context via `_split_argv` + a registry
   `model_capacity` model→mib/KV policy row) with **no engine import and no live-hardware
   read**. If neither source suffices, the build **MUST escalate** rather than cross the
   `di --json` boundary or measure real GPUs.

3. **Deploy order is a hard precondition, not a preference.** DB → writer → reader. Slice 2
   adds `mig_mode`/`ecc_mode` to the **non**-savepoint-guarded liveness UPSERT, so deploying
   Slice 2 against an un-migrated schema fails the UPSERT and ages slots out. Apply Migration
   `010` first. `mig`/`ecc` stay in the `gpu_slots` UPSERT epoch `CASE` (they must bump
   `epoch`); do not move them into the guarded companion write, and add no runtime
   column-existence probing.

4. **Late-landed defects must stay closed.** F-KEYS (all three row-builders carry the new
   keys; the puller must not `KeyError`), F-LOCK (`FOR UPDATE OF gpu_slots`; never lock the
   join view), and F-CARD (`capacity_policy` singleton; re-apply idempotent; one-row-per-slot
   under `pick(k=2)`) each have a dedicated gate-test row — regressions here re-break the
   liveness path the spine protects.

5. **Observer-effect on the probe-floor (the load-bearing RFC open question).** A heavy
   scratch-allocation floor probe can *become* the contention it measures and risks
   force-loading the `ollama-ondemand` slot. Mitigation is already in the plan: ship
   `live_slowdown_factor` first (zero new side effect), gate the scratch-allocation floor
   per-backend, residency-only for `ollama-ondemand`. Watch that the build keeps this ordering.

6. **Deferred to a follow-up RFC / tracked issue (out of scope for this build).** The
   "betrayal pheromone" between-scrape backstop (consumers write delivered-rate-vs-probed back
   on lease release) and the provocation to **make every LAN VRAM consumer speak the lease
   protocol** (turning co-tenant detection into a non-problem for owned processes). Neither is
   a build constraint; both are recorded as v2 candidates.

7. **Process note for the record.** This design run cleared under an operator decision after
   the revision loop's declared budget (`max_iterations = 2`) was spent (`f_revision_loop_
   exhausted`). The `needs_revision` ledger and the override decision are both preserved as
   the truthful outcome — an honest, constraint-bearing clear, not a fabricated `accept`.
