---
schema_version: striatum.synthesis.v1
artifact_kind: synthesis
inputs:
  - "striatum/campaign/rfc-0003/design/dialogue/holder/BUILD_PLAN.md"
  - "striatum/campaign/rfc-0003/design/dialogue/adjudicator/COLLABORATION_LEDGER_cycle_2.md"
  - "striatum/campaign/rfc-0003/design/OPERATOR_DECISION_BC1_override.md"
author: committer-claude-opus-4.8-001
run_id: "run_7ab4211a80df8b8943ec37d0e43b2280"
workflow: "rfc-0003-design"
role: committer
title: "RFC 0003 committed build plan — stale-router epoch fencing"
summary: >-
  Holder build plan amended with binding constraints BC1-BC4 from the cycle-2
  adjudicator ledger. Effective verdict accept_with_findings via operator
  decision rfc-0003-design-override-bc1 (supersedes needs_revision). Verifier
  gates on BC1 (sticky discovery) and BC2 (endpoint-turnover freshness fence).
tags: ["rfc-0003", "committed_plan", "design_gate", "epoch_fencing"]
status: committed
---

# COMMITTED BUILD PLAN — RFC 0003: Stale-router epoch fencing

author: committer-claude-opus-4.8-001

This is the **committed** build plan: the holder's plan
(`dialogue/holder/BUILD_PLAN.md`) **amended with every binding constraint the
adjudicator recorded** (BC1–BC4 in
`dialogue/adjudicator/COLLABORATION_LEDGER_cycle_2.md`). It is the exact contract
the RFC-0003 build run will execute. Nothing here re-opens the RFC's settled
design (`docs/rfc/0003-stale-router-epoch-fencing.md`); it realizes it against the
live code (`di_fleet.py`, `pick_slot.py`, `heartbeat.py`, `heartbeat_all.py`,
`migrations/`, `tests/`) as it stands after the RFC-0001 lease build landed
(migration 007 applied; the lease lifecycle is inlined in `di_fleet.py`).

---

## 0. Acceptance basis — why this plan is committed

The cycle-2 adjudication ledger returned **`needs_revision`**, not a clearing
verdict, on one ground only: Falsifier 2 #1 (the transient `discover_served_model`
flap, **BC1**) was recorded `landed_unrebutted`, and a clearing verdict requires
every Check-B challenge to be rebutted in the trajectory (RFC 0094 §5). The
adjudicator confirmed the **defect is dischargeable in the build**, not the design
— the epoch-CASE mechanism and its column set `{served_model, max_context,
nvlink_domain}` are correct; only the `served_model` **input** must stop flapping.

The human operator then issued decision
**`rfc-0003-design-override-bc1`** (`OPERATOR_DECISION_BC1_override.md`,
`outcome: accepted_with_follow_up`, created `2026-06-23T05:35:58Z`), which
**supersedes `needs_revision` and sets the effective verdict to
`accept_with_findings`** (cycle budget exhausted; the design spine is sound and
unrefuted). The override's instruction to this committer is explicit:

> *"the committer folds BC1–BC4 into the committed plan as binding constraints;
> the build discharges them with tests; the independent verifier enforces BC1+BC2
> before accept."*

Accordingly this committed plan **folds in all four binding constraints
verbatim-faithfully** (§6), maps each to its required test (§3), and preserves the
surviving design spine (§7). **No constraint the adjudicator recorded is weakened
or dropped.** The build's independent verifier **gates on BC1 and BC2**.

---

## 1. The one fact that drives the whole build

`epoch BIGINT NOT NULL DEFAULT 0` already exists
(`migrations/001_gpu_slots.sql:36`) but is **dormant**: the heartbeat UPSERT
currently writes `epoch = EXCLUDED.epoch` (`heartbeat.py:45`), i.e. it overwrites
the DB epoch with the *static* config value (`args.epoch` / `fleet_nodes.epoch`,
default 0) on **every tick**. So today `epoch` is a constant, never a
change-counter. Turning the RFC on is two coupled moves:

1. **Writer:** make the UPSERT *preserve* the existing epoch and *bump it by 1
   only when a routing-relevant field changed* (instead of clobbering it with the
   config constant) — **and** (BC1) make the `served_model` input it diffs against
   **sticky**, so a transient discovery failure cannot flap it.
2. **Consumer:** stamp the slot's epoch onto the lease at claim time
   (`lease_epoch`), and add the column self-compare `epoch = lease_epoch` to the
   lease-renew predicate.

Because `lease_epoch` is stamped **server-side as a column** (`lease_epoch =
epoch` in the CLAIM `SET`), the renew fence is a pure **two-column SQL predicate**
(`epoch = lease_epoch`) — the Python `claim()` / `renew()` / `release()`
signatures do **not** change (surviving claim C2). The inference server never
learns the epoch; staleness is caught entirely at the registry-side renew. **No
backend changes, no new protocol** (RFC §Design).

---

## 2. Scope & slices (ordered, independently committable)

Commit order = deploy order = the RFC's **DB → readers → writers**:
`008 → pick_slot → heartbeat → di_fleet`. Each slice is green on its own; later
slices are no-ops until both writer slices land. The ledger's A–D labels are noted
for traceability.

> **BC4 disambiguation (binding policy, folded in):** "independently committable"
> means each slice is **hermetic-pytest green on its own**. It does **not** mean
> "deployable in any order against the live DB." Specifically **Slice D
> (di_fleet) is independently COMMITTABLE but NOT independently DEPLOYABLE ahead
> of Migration 008** — its queries hard-depend on the `lease_epoch` column.
> Reversibility is **revert-the-consumer-code-together-with-dropping-the-column**
> (revert Slice D's `di_fleet.py` before/with `DROP COLUMN lease_epoch`). No
> dynamic column-existence probing is required or wanted (rejected as YAGNI for
> this fleet's DB-first, in-order operator deploy with no canary).

### Slice A — DB: migration `008` (additive `lease_epoch`)  *(ledger: A)*
- **Files:** `migrations/008_lease_epoch.sql` (new).
- **Change:** `ALTER TABLE gpu_slots ADD COLUMN IF NOT EXISTS lease_epoch BIGINT;`
  (nullable, **no** default, no backfill, no index, no constraint). The `epoch`
  column already exists — untouched.
- **Blast radius:** one new nullable column. Renames/drops nothing. Reversible
  with `DROP COLUMN IF EXISTS lease_epoch`.
- **Backward compatible:** the running heartbeat UPSERT never names `lease_epoch`,
  so it is unaffected the instant the DDL commits; a NULL `lease_epoch` means
  "fencing disabled for that lease" (Slice D's NULL-guard). Migration is safe with
  `gpu-fleet-heartbeat` running; stop→migrate→start is optional and equally safe.
- **Migration-number guard (BC4):** at integration, run `ls migrations/` and take
  the **lowest UNUSED `0NN`**. Today `migrations/` holds `001`–`007`, so `008` is
  correct. `007_exclusive_slot_leases.sql`'s trailing prose mentions a *future*
  `free_slots`-drop "migration 008" — that contract migration is **not** built
  here and its number is **not** reserved by prose; if another campaign claims
  `008` first, take the next free number and the `free_slots`-drop contract
  becomes `009`. The build does **not** edit the already-applied, immutable `007`.

  ```sql
  -- migrations/008_lease_epoch.sql
  -- RFC 0003 — stale-router epoch fencing. Purely additive: one nullable column.
  -- The `epoch` column (001) already exists and is reused as the change-counter;
  -- this only records, per held lease, the epoch the holder routed against.
  ALTER TABLE gpu_slots ADD COLUMN IF NOT EXISTS lease_epoch BIGINT;  -- NULL = fence off
  -- Reverse: ALTER TABLE gpu_slots DROP COLUMN IF EXISTS lease_epoch;
  ```

### Slice C — Reader: `pick_slot` surfaces `epoch`  *(ledger: C; deploys 2nd)*
- **Files:** `pick_slot.py`, `tests/test_pick_slot.py`.
- **Change:** add `epoch` to the `PICK` `SELECT` and to `COLS`
  (`pick_slot.py:27,44`). Output dict gains an `epoch` key.
- **Blast radius:** one extra output key. `di_fleet.route_slots` reads picks via
  `.get(...)`, so an added key is harmless; un-upgraded readers ignore it.
- **Why a reader slice at all:** the lease fence does **not** need this (it is
  server-side, Slice D). Surfacing `epoch` serves the RFC's optional degenerate
  no-lease pre-flight `SELECT epoch …` path and observability. It deploys first
  (readers-before-writers) so nothing downstream can KeyError on the new shape.

### Slice B — Writer: heartbeat bumps `epoch` on routing-relevant change + sticky discovery  *(ledger: B; deploys 3rd)*
- **Files:** `heartbeat.py` (the shared `UPSERT` constant, `heartbeat.py:30-47`;
  and `discover_served_model`), `tests/test_heartbeat_epoch.py` (new), and the
  DB-gate test (Slice D test file).
- **Change B.1 — preserve-and-conditional-bump.** Replace `epoch=EXCLUDED.epoch`
  in the `ON CONFLICT … DO UPDATE SET` with:

  ```sql
  epoch = gpu_slots.epoch + CASE
      WHEN gpu_slots.served_model  IS DISTINCT FROM EXCLUDED.served_model
        OR gpu_slots.nvlink_domain IS DISTINCT FROM EXCLUDED.nvlink_domain
        OR gpu_slots.max_context   IS DISTINCT FROM EXCLUDED.max_context
      THEN 1 ELSE 0 END,
  ```

  The `VALUES (… %(epoch)s …)` INSERT path is unchanged: a brand-new row still
  seeds `epoch` from config (default 0). Only the conflict path changes. Diff set
  `{served_model, nvlink_domain, max_context}` (`IS DISTINCT FROM` is NULL-safe);
  `vram_free_mib` / `gpu_util_pct` are deliberately **excluded** → no re-pick
  storms on expected churn. `endpoint_url` is excluded because it is part of the
  PK `(node, endpoint_url, slot_id)`: an endpoint change is structurally a new row
  (a fresh INSERT seeding epoch), never an in-place conflict (see BC2 / Slice D
  for how a *held* lease on a turned-over endpoint is fenced).
- **Change B.2 — BC1 sticky discovery (BLOCKING repair — the reason the gate
  could not auto-clear).** A transient `discover_served_model` failure currently
  falls back to the static `--served-model` CLI tag; when that tag differs from
  the previously-discovered id (the common case — CLI alias vs full `/models` id),
  the heartbeat writes a **distinct** `served_model`, the epoch CASE bumps, the
  holding consumer's renew returns zero rows, `_monitor` terminates a **healthy**
  `di --json` child, and the next good tick restores the id and bumps again — the
  exact re-pick storm gate-bullet-2 exists to exclude. **The build MUST make the
  discovered model sticky:** cache the last successfully-discovered model and use
  it as the fallback on a transient `/models` failure (instead of immediately
  falling back to the differing static `--served-model` tag), OR otherwise refuse
  to overwrite a previously-discovered `served_model` with a *differing* fallback
  on transient failure. (See §3 for the **required** writer-side no-bump test;
  this is a real test, not an assertion of stability.)
- **`heartbeat_all.py` is covered transitively:** it `from heartbeat import
  UPSERT` (`heartbeat_all.py:22-28`) — both single-node and driver writers use the
  one constant, so the UPSERT edit is a single edit. The sticky-discovery change
  lives in `discover_served_model` / the per-endpoint probe path both writers call.
- **Blast radius:** one SQL constant + the discovery cache. **Backward
  compatible:** until a routing field actually changes, the bump is `+0` ⇒ epoch
  stays constant ⇒ identical to today; a real bump affects no consumer until Slice
  D stamps `lease_epoch`. The UPSERT `SET` never lists
  `lease_id/lease_holder/lease_expires/lease_epoch`, so a tick over a held slot
  leaves the lease (and its stamped `lease_epoch`) intact — only `epoch` moves
  (surviving claim C8).

### Slice D — Writer: consumer fences the lease on epoch + endpoint freshness  *(ledger: D; deploys 4th)*
- **Files:** `di_fleet.py` (the lease SQL constants), `tests/lease_fakes.py`,
  `tests/test_leases.py`, `tests/test_epoch_pg.py` (new, guarded), and
  `tests/test_leases_pg.py` (DDL fix — see §3 build hygiene).
- **Change D.1 — stamp at claim** (`di_fleet.py` `LEASE_CLAIM_SQL`, ~`:93`): add
  `lease_epoch = epoch` to the `SET` (RHS reads the row's current epoch atomically
  in the same conditional UPDATE).
- **Change D.2 — fence at renew, with the BC2 freshness/identity term**
  (`di_fleet.py` `LEASE_RENEW_SQL`, ~`:109`). The committed renew predicate is the
  holder's column self-compare **plus** the BC2 term (chosen **option (a)**:
  registry-side freshness/identity — see §6 BC2):

  ```sql
  UPDATE gpu_slots
     SET lease_expires = now() + make_interval(secs => %(ttl)s)
   WHERE lease_id = %(lease_id)s
     AND now() < lease_expires
     AND (lease_epoch IS NULL OR epoch = lease_epoch)   -- capability changed => 0 rows
     AND alive                                          -- BC2: still the live, …
     AND heartbeat_ts > now() - interval '45 seconds'   -- … fresh heartbeated row
  RETURNING lease_id
  ```

  The freshness term reuses the **same 45s window** that `live_slots` already uses
  (`migrations/001_gpu_slots.sql`) — deliberately **not** tighter, so a transient
  heartbeat-driver outage does not fence every live lease. Zero rows now means
  "lease lost **OR** the slot's capability changed underneath me **OR** my leased
  `(node, endpoint_url, slot_id)` row stopped being the live, fresh heartbeated
  endpoint for that `(node, slot_id)`." This closes the held-lease
  endpoint-turnover gap (BC2): when the node moves to a new `endpoint_url` (a new
  PK row), the old leased row stops being heartbeated, ages out of the 45s window,
  and the old lease's renew returns zero rows — instead of renewing against the
  stale row indefinitely. The consumer's existing `renew()==False ⇒ abort the
  child + drop the slot + re-pick` path (`di_fleet.py` `_monitor` BC1-A,
  `:408-414`) already handles every cause unchanged — it simply gains more reasons
  to return zero rows (surviving claim C4: the in-flight abort is **inherited**,
  not rebuilt; the build never adds a second renewer).
  `claim()/renew()/release()` signatures are untouched.
- **Change D.3 — RELEASE clears `lease_epoch` with `lease_id` (BC3).**
  `LEASE_RELEASE_SQL`'s `SET` adds `lease_epoch = NULL` **together with** clearing
  `lease_id` — so no released row carries a renewable `lease_id` alongside a stale
  `lease_epoch`, and a NULL `lease_epoch` row never carries a live lease (see BC3).
- **NULL-guard (BC3, keep the arm):** after Slice D deploys, every new claim
  stamps `lease_epoch = epoch` (non-NULL, since `epoch` is `NOT NULL DEFAULT 0`).
  A NULL `lease_epoch` therefore exists **only** for a lease claimed by
  pre-Slice-D code that is still alive at the deploy instant — bounded by one TTL
  (45s). The `(lease_epoch IS NULL)` arm keeps such in-flight leases un-fenced (no
  false re-pick) during the rollout drain; it never weakens fencing for any lease
  claimed by the deployed code. **Do not remove the arm** (removing it would break
  Slice A's order-independence and evict every in-flight lease at deploy).
- **Blast radius:** the lease SQL constants in `di_fleet.py` + their
  hermetic/PG tests + the `test_leases_pg.py` DDL fix.

---

## 3. Test plan — mapped to the RFC's Falsifiable gate, with every binding constraint folded in

Default `python3 -m pytest tests/ -q` (26 tests today) MUST stay green and
hermetic. Hermetic tests inject the existing `FakeSlotDB` / `RecordingConn` fakes
(mirroring `tests/test_leases.py`, `tests/test_pick_slot.py`,
`tests/test_probe_all.py`). Any DB-backed test is **guarded exactly like
`tests/test_leases_pg.py`**: it `pytest.importorskip("psycopg")` and skips unless
`GPU_FLEET_TEST_DB` names an **ephemeral** throwaway cluster (it refuses bare
`gpu_fleet`). The new PG tests apply the real `migrations/001,007,008` to that
ephemeral DB so they also prove the migrations apply cleanly.

### RFC falsifiable-gate → test map

| RFC gate bullet | Test(s) | Kind |
|---|---|---|
| **(1)** Bumping `served_model` makes a holder's next renew return **zero rows** (forced re-pick), proven by mutating the row mid-lease | **A.** `test_leases.py::test_epoch_change_fences_renew` — extend `FakeSlotDB` to carry `epoch`/`lease_epoch`; `claim` stamps `lease_epoch=epoch`; bump `db.row_for(slot)["epoch"] += 1`; assert `leases.renew(...) is False`, and (reusing the existing monitor harness) that `_monitor` aborts the child + raises `LeaseLost`. **B.** `test_epoch_pg.py::test_served_model_bump_fences_renew` — real DB: INSERT slot, `claim`, drive the real `heartbeat.UPSERT` with a changed `served_model`, assert `epoch` advanced and `leases.renew` returns `False`. | A: **hermetic**. B: **PG-guarded**. |
| **(2)** A VRAM/util-only change does **not** bump epoch and does **not** invalidate a lease | **C.** `test_epoch_pg.py::test_vram_util_only_change_keeps_epoch_and_lease` — `claim`, run real `heartbeat.UPSERT` changing only `vram_free_mib`/`gpu_util_pct`; assert `epoch` unchanged **and** `leases.renew` returns `True`. **D.** `test_heartbeat_epoch.py::test_bump_diff_excludes_churn_fields` — assert the `UPSERT` SQL's epoch `CASE` references `served_model/nvlink_domain/max_context` and **not** `vram_free_mib/gpu_util_pct`. | C: **PG-guarded**. D: **hermetic**. |
| **(3)** A re-pick after an epoch bump lands on the slot's **new** capability, never the stale one | **E.** `test_pick_slot.py::test_pick_surfaces_current_epoch_and_model` — `RecordingConn` returns a row with bumped `epoch` + new `served_model`; assert `pick()` output carries the new `epoch` and `served_model`. **F.** `test_epoch_pg.py::test_repick_after_bump_stamps_new_epoch` — after a bump, a fresh `claim` stamps `lease_epoch` = the **new** epoch and its renew succeeds against the new capability. | E: **hermetic**. F: **PG-guarded**. |

### Binding-constraint tests (folded in — REQUIRED, not assertions of stability)

| Constraint | REQUIRED test(s) | Kind |
|---|---|---|
| **BC1** (sticky discovery — the writer-side analog of gate-bullet-2) | **G.** `test_heartbeat_epoch.py::test_transient_discovery_failure_does_not_flap_or_bump` — after a successful discovery sets `served_model` (e.g. `'llama-3'` ≠ static fallback `'fallback-model'`), simulate a **transient** `discover_served_model` failure on the next tick and assert **(i)** `served_model` is NOT overwritten with the differing static fallback and **(ii)** `epoch` does NOT bump. (Real test of the sticky-discovery behavior, per BC1; a transient `/models` failure must be a no-op for `served_model` and `epoch`.) Optional companion PG test on `test_epoch_pg.py` driving the real UPSERT across the good→transient-fail→good tick sequence and asserting a stable `epoch`. | G: **hermetic** (+ optional PG). |
| **BC2** (endpoint-turnover fence — **option (a)** registry-side freshness/identity) | **H.** `test_epoch_pg.py::test_endpoint_turnover_fences_old_lease` — claim `(node='peecee', endpoint_url='old', slot_id=0)` and stamp `lease_epoch`; simulate heartbeat moving the **same** `(node, slot_id)` to `endpoint_url='new'` (a new PK row), so the old row stops being heartbeated; advance time **past the 45s `live_slots` window** but **before** `lease_expires`; assert the **old** lease's `renew` returns **zero rows**. Hermetic companion: extend `FakeSlotDB` to model the PK split (`bump_epoch`/turnover) and the `alive`+`heartbeat_ts` freshness term, asserting the same zero-row renew. | H: **PG-guarded** (+ hermetic companion). |
| **BC3** (keep the NULL arm; prove steady-state-unreachable) | **I.** `test_leases.py::test_post_rollout_claim_stamps_non_null_lease_epoch` — every post-Slice-D claim stamps a non-NULL `lease_epoch` (since `epoch` is `NOT NULL DEFAULT 0`). **J.** `test_leases.py::test_null_lease_epoch_still_renews` — a NULL-`lease_epoch` lease still renews (the intended pre-upgrade BC behavior). **K.** `test_leases.py::test_release_clears_lease_epoch_with_lease_id` — `release` clears `lease_epoch` **together with** `lease_id`, so no NULL-`lease_epoch` row carries a renewable `lease_id`. | I,J,K: **hermetic**. |

### Restated load-bearing claims (folded per BC1/BC2)

- **C3 (restated under BC1):** `served_model` is stable — and only routing-relevant
  changes bump epoch — **once discovery is sticky** (Change B.2). Absent sticky
  discovery, `served_model` flaps on network churn and Falsifier 2 #1 stands;
  with it (and test G), the writer-side anti-churn guarantee holds.
- **C5 (restated under BC2):** the held-lease cached-endpoint-across-restart
  failure mode is **covered by the registry fence**, because the renew predicate
  (Change D.2) requires the leased row to remain the **live, fresh heartbeated**
  endpoint for `(node, slot_id)` (the `alive` + 45s `heartbeat_ts` term), proven
  by test H. The `di --json` child-death/`ShardDied` failover remains a defensive
  backstop, **not** the primary guarantee, and is no longer claimed as coverage
  without a test.

### Build hygiene (necessary to keep the suite green; not new adjudicator constraints)

- **`tests/test_leases_pg.py` `_DDL` must add the new columns.** That file builds
  its temp `gpu_slots` from a hardcoded `_DDL` that lacks `epoch`/`lease_epoch`.
  Because Slice D modifies the shared `LEASE_CLAIM_SQL`/`LEASE_RENEW_SQL` it
  exercises, the build MUST add `epoch BIGINT NOT NULL DEFAULT 0` and `lease_epoch
  BIGINT` to that `_DDL` (or have it apply the real migrations) so the PG suite
  stays green under `GPU_FLEET_TEST_DB`. (Raised by Falsifier 2 #3; a build
  implementation requirement, not a design change.)
- **Manual `EXCLUDED.epoch` override is NOT adopted.** Falsifier 2 #4 asked for a
  `GREATEST(gpu_slots.epoch, EXCLUDED.epoch)` term so an operator could force-fence
  via `--epoch`. The adjudicator did **not** record this as a constraint and the
  preserved spine keeps the CASE column set as-is (the bump rides routing-relevant
  diffs, not the config constant). The build therefore **does not** add the
  `GREATEST` override; reintroducing it would re-open the RFC's settled design.

**Hermetic-default guarantee (surviving claim C6).** New default-suite tests (A,
D, E, G, I, J, K, and the hermetic companion of H) add to the 26 and need no DB.
Extending `FakeSlotDB`/`LEASE_*_SQL` keeps the existing lease tests green because
all existing fakes/claims have `epoch == lease_epoch == 0`, so `epoch =
lease_epoch` evaluates `True` ⇒ today's renew behavior, and existing fakes are
`alive` with a fresh `heartbeat_ts` ⇒ the BC2 freshness term is satisfied. The PG
tests (B, C, F, H, and BC1's optional PG companion) skip cleanly when
`GPU_FLEET_TEST_DB` is unset.

---

## 4. Live-infra safety & the `di --json` boundary

The build is **inert** with respect to live infra. It only:
- writes `migrations/008_lease_epoch.sql`;
- edits `pick_slot.py`, `heartbeat.py`, `di_fleet.py`, and `tests/*`;
- runs the **hermetic** `python3 -m pytest tests/ -q`.

It MUST NOT, and does not need to:
- connect to / migrate the **live `gpu_fleet`** Postgres (the PG tests refuse a
  non-ephemeral DB and skip by default; only an operator-provided
  `GPU_FLEET_TEST_DB` throwaway cluster runs them);
- restart or touch the running **`gpu-fleet-heartbeat`** service;
- touch **peecee**'s shared GPU (no probe, no decode, no `nvidia-smi`).

**The `di --json` subprocess boundary is preserved (RFC 0078/0087).** Epoch
fencing — including the BC2 freshness term — is **100% registry-side SQL**. The
lease monitor still aborts only by acting on the `Popen` handle
(`terminate()/kill()`), never importing the Node engine
(`~/git/divergent-ideation`). No code in this build crosses that boundary.
`bin/di-fleet` is a thin `exec python3 di_fleet.py` bash wrapper holding no logic
and is **not edited**. The table + the query stay the router — no central daemon,
no new service, no backend-side epoch awareness (RFC §Design).

---

## 5. Exact operator deployment steps (the RFC's rollout, restated)

The build ships green hermetic code; the **operator**, after integration, applies
it to live infra in the RFC's **DB → readers → writers** order:

1. **DB — apply `008`.** `008` is additive (`ADD COLUMN IF NOT EXISTS
   lease_epoch BIGINT`), so it is safe even with `gpu-fleet-heartbeat` running;
   `stop heartbeat → migrate → start` is optional and equally safe.
2. **Readers — deploy `pick_slot.py` (Slice C).** Surfaces `epoch`; no behavior
   change.
3. **Writers — deploy `heartbeat.py` (Slice B) and `di_fleet.py` (Slice D),
   then restart `gpu-fleet-heartbeat`.** Until both writer slices land, behavior
   equals today (the bump is `+0` and `lease_epoch` is unstamped/NULL ⇒ fence
   off). "Redeploying `bin/di-fleet`" means updating the gpu-fleet checkout on
   consumer hosts so the new `di_fleet.py`/`pick_slot.py` take effect (the wrapper
   itself is unchanged).
4. **Reversibility (BC4):** to roll back, **revert the consumer code together with
   dropping the column** — revert Slice D's `di_fleet.py`, then
   `ALTER TABLE gpu_slots DROP COLUMN IF EXISTS lease_epoch`. Do **not** drop
   `008` while live Slice-D code is deployed (its queries reference `lease_epoch`).

**Backward-compatibility invariant:** until consumers stamp/read `lease_epoch`,
fleet behavior equals today's — a NULL `lease_epoch` disables fencing, the bump is
`+0` whenever no routing field changes, and the only NULL-`lease_epoch` live
leases are pre-upgrade in-flight leases draining within one lease TTL (BC3).

---

## 6. Binding constraints folded in (from the adjudicator ledger — preserved, not weakened)

| ID | Binding | Severity | Constraint (as recorded) | Folded into |
|----|---------|----------|--------------------------|-------------|
| **BC1** | **yes (blocking gate)** | high | Slice B MUST make a transient `discover_served_model` failure unable to flap `served_model` or bump epoch / evict a healthy lease — make discovery **sticky** (cache last successfully-discovered model; do not overwrite a discovered `served_model` with a *differing* static fallback on transient failure). **Restate C3** (stable *only once sticky*). **REQUIRED** writer-side test: a transient discovery failure after a good discovery leaves `served_model` unchanged and does **not** bump epoch (the writer-side analog of gate-bullet-2; a real test, not an assertion). | §2 Slice B Change B.2; §3 test **G**; §3 restated **C3** |
| **BC2** | **yes (gate)** | high | Close the held-lease endpoint-turnover gap **with a test**, EITHER (a) a registry-side freshness/identity renew term keyed to the **same 45s `live_slots` window** so a held lease fails renew once its row stops being the fresh/alive heartbeated `(node, slot_id)` row, **or** (b) an explicit narrowing of C5 plus a child-death/failover test. **Chosen: option (a).** Do **not** keep C5's "covered" wording with no test. Preserve the `di --json` boundary. | §2 Slice D Change D.2 (freshness term); §3 test **H**; §3 restated **C5** |
| **BC3** | recommended (policy) | medium | **Keep** the `(lease_epoch IS NULL)` rollout-drain arm and **prove** the bypass is steady-state-unreachable: (i) every post-Slice-D claim stamps non-NULL `lease_epoch`; (ii) a NULL-`lease_epoch` lease still renews **and** `release` clears `lease_epoch` only together with `lease_id`; (iii) document that the only NULL-arm live leases are pre-upgrade in-flight leases draining within one lease TTL. Do **not** remove the arm. | §2 Slice D Change D.3 + NULL-guard; §3 tests **I/J/K**; §5 invariant |
| **BC4** | no (policy) | low | Disambiguate Slice D = independently **committable** (hermetic pytest green) but **not** independently **deployable** ahead of Migration 008; reversibility = revert code **with** dropping the column; no dynamic column probing (YAGNI). Keep the `ls migrations/` lowest-unused-`0NN` guard (free_slots-drop contract → `009`). | §2 BC4 disambiguation box + Slice A guard; §5 step 4 |

**Verifier gate (per the operator decision):** the build's **independent verifier
enforces BC1 and BC2** (tests **G** and **H**) before `accept`. BC3 and BC4 are
recommended/policy and verified by tests **I/J/K** and the wording/guard checks.

---

## 7. The surviving spine (preserved intact through the commit)

No challenge refuted these; they are load-bearing and are carried unchanged:

- **C1 — additive, reversible Migration 008.** One nullable `ADD COLUMN
  lease_epoch BIGINT` (no default/backfill/index/constraint); `epoch` untouched;
  the running heartbeat never writes it; reversible by `DROP COLUMN IF EXISTS
  lease_epoch`.
- **C2 — the fence is a DB-side column self-compare; the consumer carries no epoch
  state.** `LEASE_CLAIM_SQL` stamps `lease_epoch = epoch`; `LEASE_RENEW_SQL` adds
  `epoch = lease_epoch` (column-to-column); `renew(conn, lease_id)` gains no
  parameter — the deliberate, *stronger* refinement of the RFC's illustrative
  `AND epoch = $lease_epoch` bound param (no consumer clock).
- **C4 — the in-flight abort is inherited, not rebuilt.** `_monitor` already
  terminates the `di --json` child on a zero-row renew (RFC-0001 BC1-A) and names
  "an epoch change" as a renew-loss cause. RFC-0003 (and BC1/BC2) only change
  *what makes renew return zero rows*; they never add a second renewer.
- **C6 — the hermetic default stays green and DB-free; the live registry is
  unreachable.** `python3 -m pytest tests/ -q` runs the existing + new hermetic
  tests with no DB; PG tests skip behind `importorskip` + the `GPU_FLEET_TEST_DB`
  ephemeral-only guard that refuses bare `gpu_fleet`.
- **C8 — held leases survive heartbeat ticks; only `epoch` moves.** The UPSERT
  `SET` never lists the lease columns, so `lease_id/expires/lease_epoch` are
  preserved across a tick.
- **The DB → reader → writer slice discipline** and the **`di --json` subprocess
  boundary** (registry SQL + process handle only; never import
  `~/git/divergent-ideation`).

The RFC's settled design is not re-opened: the bump rides the heartbeat; the fence
rides the RFC-0001 renew; `epoch` ⟂ `lease_id`; VRAM/util are excluded.
