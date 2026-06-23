---
schema_version: striatum.synthesis.v1
artifact_kind: synthesis
author: adjudicator-claude-opus-4.8-004
run_id: "run_7ab4211a80df8b8943ec37d0e43b2280"
workflow: "rfc-0003-design"
role: adjudicator
status: committed
title: "RFC 0003 design gate — summary (cleared via operator override; BC1–BC4 binding)"
inputs:
  - "docs/rfc/0003-stale-router-epoch-fencing.md"
  - "striatum/campaign/rfc-0003/design/dialogue/adjudicator/COLLABORATION_LEDGER_cycle_2.md"
  - "striatum/campaign/rfc-0003/design/OPERATOR_DECISION_BC1_override.md"
  - "striatum/campaign/rfc-0003/design/COMMITTED_PLAN.md"
summary: >-
  Cycle-2 ledger verdict was needs_revision (one landed_unrebutted blocker, BC1 —
  the transient discover_served_model flap). Operator decision
  rfc-0003-design-override-bc1 superseded it to an effective accept_with_findings:
  the design spine is sound and the blocker is dischargeable in the build, so
  BC1-BC4 are folded into the committed plan as binding constraints and the
  independent verifier gates on BC1 + BC2 before accept. Gate cleared; the build
  run executes striatum/campaign/rfc-0003/design/COMMITTED_PLAN.md.
tags: ["rfc-0003", "design_gate", "gate_summary", "epoch_fencing"]
---

# RFC 0003 design gate — summary

author: adjudicator-claude-opus-4.8-004

**RFC:** `docs/rfc/0003-stale-router-epoch-fencing.md` — turn the dormant
`gpu_slots.epoch` column into a stale-router fence: bump it when a routing-relevant
capability changes, stamp it onto the RFC-0001 lease at claim, and add a column
self-compare to the lease-renew predicate so a mid-flight config change forces a
re-pick.

---

## 1. Verdict

| | |
|---|---|
| **Cycle-2 adjudicator ledger verdict** | `needs_revision` |
| **Effective verdict (after operator decision)** | **`accept_with_findings`** |
| **Gate state** | **Cleared — via operator override, carrying BC1–BC4 as binding build constraints** |

**One-line reason.** The cycle-2 ledger returned `needs_revision` on a single
ground — Falsifier 2 #1 (the transient `discover_served_model` flap, **BC1**) was
recorded `landed_unrebutted`, and a clearing verdict requires every Check-B
challenge to be rebutted in the trajectory (RFC 0094 §5), so the gate could not
auto-clear. The adjudicator confirmed the blocking defect is **dischargeable in the
build, not a design flaw** (the epoch-CASE mechanism and its column set
`{served_model, max_context, nvlink_domain}` are correct; only the `served_model`
*input* must stop flapping). With the design spine sound and unrefuted and the
cycle budget exhausted, the human operator issued decision
**`rfc-0003-design-override-bc1`** (`OPERATOR_DECISION_BC1_override.md`,
`outcome: accepted_with_follow_up`, `2026-06-23T05:35:58Z`), which **supersedes
`needs_revision` and sets the effective verdict to `accept_with_findings`**: the
committer folds BC1–BC4 into the committed plan as binding constraints, the build
discharges them with tests, and the independent verifier enforces **BC1 + BC2**
before `accept`.

---

## 2. Challenges that landed → binding constraints

The falsification round was two independent challengers against the holder's
`dialogue/holder/BUILD_PLAN.md`: Falsifier 1 (`falsifier-openai-codex-gpt-5.5-001`,
`dialogue:2`) and Falsifier 2 (`falsifier-antigravity-gemini-002`, `dialogue:3`).
The holder did not revise between rounds, so the cycle-2 ledger re-derived the
verdict independently from the trajectory.

| Source | Hit | Correspondence | Became | Binding |
|---|---|---|---|---|
| **F2 #1** — discovery-fallback flap → spurious eviction | C3 (`served_model` stable) | **landed_unrebutted** | **BC1** (gate, high) | **yes — blocking** |
| **F1** — held-lease endpoint-turnover | C5 (endpoint change covered by row-turnover) | landed_and_rebutted | **BC2** (gate, high) | **yes** |
| **F2 #2** — NULL `lease_epoch` bypass | C1/C2 (NULL arm bypasses fence) | landed_and_rebutted | **BC3** (policy, medium) | no (recommended) |
| **F2 #3** — independent-committability / reversibility | §1 "deploy in any order" wording | landed_and_rebutted | **BC4** (policy, low) | no (recommended) |
| F2 #3 — demand for runtime column-existence fallback | — | **not_material** | rejected (YAGNI) | — |

**How each landed challenge became a constraint:**

- **BC1 (blocking).** A transient `discover_served_model` failure falls back to the
  static `--served-model` CLI tag; when that tag differs from the previously-
  discovered id (the common case — CLI alias vs full `/models` id) the heartbeat
  writes a *distinct* `served_model`, the epoch CASE bumps, the holder's renew
  returns zero rows, `_monitor` terminates a **healthy** `di --json` child, and the
  next good tick restores the id and bumps again — exactly the re-pick storm
  gate-bullet-2 exists to exclude. C3's "stable" claim addressed only the
  `loaded_model`/`alive` probe flap and was silent on the discovery-fallback path.
  **Repair:** make discovery **sticky** (cache the last successfully-discovered
  model; do not overwrite a discovered `served_model` with a *differing* static
  fallback on transient failure), restate C3 ("stable *once discovery is sticky*"),
  and ship a **writer-side no-bump test** (a transient discovery failure after a
  good discovery leaves `served_model` unchanged and does **not** bump epoch).

- **BC2.** The held-lease renew fences on `lease_id` + `now() < lease_expires` +
  the epoch self-compare, but never re-checks that the leased row is still the
  fresh/alive heartbeated identity for `(node, slot_id)`. Because `endpoint_url` is
  in the PK, an endpoint change is a **new row**; the old leased row stops being
  heartbeated, ages out of `live_slots`, and its `epoch` freezes — so the holder
  renews against the stale row indefinitely. Rebutted (the `di` child-death/
  `ShardDied`/failover backstop) but unproven and untested. **Repair (committed
  plan chose option (a)):** add a registry-side freshness/identity renew term keyed
  to the **same 45s `live_slots` window** (`alive AND heartbeat_ts > now() -
  interval '45 seconds'`), with an endpoint-turnover test; restate C5 to the fence
  being the primary guarantee. The `di --json` subprocess boundary is preserved.

- **BC3 (policy).** The `(lease_epoch IS NULL)` arm is the deliberate, bounded
  rollout-drain affordance, not a fencing hole (`epoch` is `NOT NULL DEFAULT 0`, so
  every post-Slice-D claim stamps a concrete value, and `release` clears
  `lease_epoch` *with* `lease_id`). The "remove the arm" demand was **rejected**
  (it would break Slice A's order-independence and evict every in-flight lease at
  deploy). **Repair:** keep the arm; prove it steady-state-unreachable with tests +
  a documented bounded-drain invariant.

- **BC4 (policy).** Slice D (`di_fleet`) is independently **committable** (hermetic
  pytest green) but **not** independently **deployable** ahead of Migration 008 (its
  queries hard-depend on `lease_epoch`). The runtime column-probe demand was
  rejected as YAGNI. **Repair:** disambiguate committable-vs-deployable; reversibility
  = revert consumer code *together with* dropping the column; keep the `ls migrations/`
  lowest-unused-`0NN` guard.

**Survived falsification intact (the spine — preserved through the commit):** the
additive nullable Migration 008 (C1); the DB-side column self-compare renew that
keeps `renew(conn, lease_id)` signature-stable and carries no consumer-side epoch
state (C2); the in-flight abort inherited from RFC-0001's `_monitor` zero-row →
`_terminate` path (C4); the hermetic-default + ephemeral-PG-guarded test split (C6);
held leases surviving heartbeat ticks (C8); the DB → reader → writer slice
discipline and the `di --json` subprocess boundary.

---

## 3. Pointer — the committed build plan the build run MUST execute

**`striatum/campaign/rfc-0003/design/COMMITTED_PLAN.md`**
(`committer-claude-opus-4.8-001`, `status: committed`) — the holder's build plan
amended with BC1–BC4 folded in verbatim-faithfully, each mapped to its required
test. This is the exact contract for the RFC-0003 **build** run. In outline:

- **Slice A** — `migrations/008_lease_epoch.sql`: additive `ADD COLUMN IF NOT
  EXISTS lease_epoch BIGINT` (nullable, no default/backfill/index/constraint).
- **Slice C** — `pick_slot.py`: surface `epoch` (deploys 2nd; reader-before-writer).
- **Slice B** — `heartbeat.py`: preserve-and-conditional-bump UPSERT over
  `{served_model, nvlink_domain, max_context}` (VRAM/util excluded) **+ BC1 sticky
  discovery**.
- **Slice D** — `di_fleet.py`: stamp `lease_epoch = epoch` at claim; renew fence =
  `(lease_epoch IS NULL OR epoch = lease_epoch) AND alive AND heartbeat_ts > now()
  - interval '45 seconds'` (**BC2** option (a)); `release` clears `lease_epoch` with
  `lease_id` (**BC3**).
- **Commit/deploy order:** `008 → pick_slot → heartbeat → di_fleet`, then operator
  restarts `gpu-fleet-heartbeat`.
- **Verifier gate:** BC1 (test G — transient-discovery no-bump) and BC2 (test H —
  endpoint-turnover fences the old lease) are **enforced before `accept`**.

---

## 4. Residual follow-up & risks the operator should watch during the build

1. **BC1 is the gate.** The build is only honestly cleared once sticky discovery
   ships **with** its real writer-side test (G), not an assertion of stability. The
   verifier must reject the build if a transient `/models` failure can still flap
   `served_model` or bump epoch.
2. **BC2 — do not tighten the 45s window.** The freshness term must reuse the
   **same** 45s `live_slots` window, not a tighter one; a tighter window would fence
   every live lease on a transient heartbeat-driver outage. Watch for an
   accidentally shorter interval and confirm test H actually advances past 45s while
   renewing *before* `lease_expires`.
3. **BC3 — keep the NULL arm.** Removing `(lease_epoch IS NULL)` would evict every
   in-flight lease at deploy. The build must keep it and prove it steady-state-
   unreachable (tests I/J/K), not delete it.
4. **BC4 / deploy ordering.** Slice D is committable but not deployable ahead of
   008; reversibility is revert-code-**and**-column-together. At integration, take
   the lowest-unused migration number (`008` today; the future `free_slots`-drop
   contract becomes `009` if another campaign claims `008` first). Do not edit the
   already-applied, immutable `007`.
5. **Build hygiene (not new constraints, but suite-breaking if missed).**
   `tests/test_leases_pg.py`'s hardcoded `_DDL` must gain `epoch BIGINT NOT NULL
   DEFAULT 0` and `lease_epoch BIGINT` (or apply the real migrations) to stay green.
   The `GREATEST(gpu_slots.epoch, EXCLUDED.epoch)` operator-force-fence override
   (Falsifier 2 #4) is **not** adopted — reintroducing it would re-open the RFC's
   settled design.
6. **Live-infra safety.** The build is inert: it must **not** connect to or migrate
   the live `gpu_fleet` Postgres, restart `gpu-fleet-heartbeat`, or touch peecee's
   GPU. PG tests run only against an operator-provided ephemeral `GPU_FLEET_TEST_DB`
   and skip by default. The `di --json` boundary (registry SQL + `Popen` handle
   only; never import `~/git/divergent-ideation`) must remain uncrossed.

**Bottom line:** the design gate is **cleared** (effective `accept_with_findings`
via the operator override). The build run executes `COMMITTED_PLAN.md` and the
independent verifier gates on BC1 and BC2 before accepting.
