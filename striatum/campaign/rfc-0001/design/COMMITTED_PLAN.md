---
schema_version: "striatum.synthesis.v1"
artifact_kind: "synthesis"
---

# COMMITTED_PLAN — RFC 0001 Exclusive slot leases

author: committer-claude-opus-4.8-001

This is the **committed build plan** for RFC 0001 (`docs/rfc/0001-exclusive-slot-leases.md`).
It is the holder's leading build proposal (`dialogue/holder/BUILD_PLAN.md`,
holder-claude-opus-4.8-001) **amended with every binding constraint** the adjudicator
recorded. It is the exact contract the downstream build run executes — read it as the
single source of truth; the dialogue artifacts are provenance, this file is the order.

It does **not** re-open the RFC's settled design (capacity is derived; Postgres is the
only clock; expiry and fencing are separate; leases inherit load-aware liveness). It
commits the *engineering* the RFC leaves open — migration safety, per-slice blast radius,
the gate→test map, and live-infra safety — and folds in BC1–BC4.

---

## 0. Acceptance link — why this plan is committed

**Clearing authority:** operator decision
`striatum/campaign/rfc-0001/design/OPERATOR_DECISION_BC1_override.md`
(`decision_id: rfc-0001-design-override-bc1`, outcome `accepted_with_follow_up`,
2026-06-22T17:39:40Z).

**Gate history:**

- **Cycle 1 ledger** (`dialogue/adjudicator/COLLABORATION_LEDGER_cycle_1.md`,
  adjudicator-claude-opus-4.8-001) — verdict `needs_revision`. Falsifier 1 landed an
  unrebutted challenge on the RFC's primary falsifiable gate (physical exclusivity);
  Falsifier 2 landed an unrebutted backward-compat challenge. Recorded four constraints
  **BC1 (critical, gate)** and **BC2–BC4 (residual)**.
- **Cycle 2 ledger** (`dialogue/adjudicator/COLLABORATION_LEDGER_cycle_2.md`,
  adjudicator-claude-opus-4.8-002) — **re-confirmed** `needs_revision` with the same four
  landed constraints. The workflow's single revision iteration routed to `falsifier_1`
  (re-challenge) rather than back to the `holder` (revise), so the plan could not be
  repaired in-cycle and the cycle budget exhausted — a **template routing limitation, not
  a design rejection**.
- **Operator override** — superseded the exhausted `needs_revision` with
  `accepted_with_follow_up`. The honest disposition is `accept_with_findings`: BC1 is a
  well-scoped, dischargeable **build** constraint (the holder itself named the Popen +
  per-shard lease-monitor fix), not an undischargeable design defect.

**Binding effect of the override (preserved verbatim below, not weakened or dropped):**

1. The committer (this plan) folds **BC1–BC4 into the committed plan as binding
   constraints**.
2. The build **MUST implement BC1 and its no-live-infra falsifying test**.
3. The independent verifier **MUST confirm the in-flight-abort test before accept** —
   the verifier gates on BC1's test.

**What survived falsification (the sound spine — keep through the build, do not re-open):**

- DB-side lease lifecycle (claim/renew/release/expire SQL; single Postgres `now()` clock;
  `lease_id` fencing). Exclusivity, deadman expiry, zombie-fencing are sound **at the DB
  layer**. *The gap BC1 closes is the bridge from DB-lease-loss to stop-touching-the-GPU.*
- Additive expand/contract migration 006 (add `capacity` + nullable lease columns,
  backfill, new partial index; `free_slots` / `gpu_slots_claim_idx` untouched; reversible).
  The capacity-drift / YAGNI attack on it **did not land** (rejected).
- Slice ordering DB → readers → writers; hermetic-default + env-guarded real-Postgres test
  split; the live-infra safety boundary.
- The `di --json` subprocess boundary — leases stay in Python around the shell-out; BC1's
  fix operates on the process **handle**, never by importing the engine.

---

## 1. Binding constraints (folded in — the contract the build owes)

These are recorded verbatim from the adjudicator ledger and re-confirmed across both
cycles. The build run MUST discharge every one; the verifier gates on BC1.

### BC1 — physical-exclusivity gate (CRITICAL, BINDING GATE) — `source_finding: f_inflight_abort`

> Slice D MUST replace the blocking `subprocess.run` with `subprocess.Popen` plus a
> per-shard lease monitor (or move renew+cancel into the worker that owns the child handle)
> so a lost lease **immediately terminates the `di --json` child before any second consumer
> can use the GPU**. C7 MUST be restated: as specified (central renewer plus blocking
> `subprocess.run`), renewal **IS on the correctness path**. Add a no-live-infra falsifying
> test: under a disposable lease, a long-running fake child is terminated before any second
> claim can run concurrently. The DB-only two-transaction concurrency test is **necessary
> but NOT sufficient** for the RFC's exactly-one-holder-at-any-instant gate. The `di --json`
> shell-out boundary is preserved (operate on the process handle; do not import the engine).

- **Verification gate:** *no-live-infra in-flight-abort test* — lease loss terminates the
  running child before any second claim; physical double-use is observably prevented.
- **`final_review_required: true`** — the independent verifier MUST confirm this test
  before `accept`. This is the one gate the override explicitly re-asserts.

### BC2 — migration backward-compat (medium) — `source_finding: f_pick_backcompat`

> `pick_slot.py` MUST keep surfacing `free_slots` in its returned dict / `--json` output
> (e.g. alias `capacity` to `free_slots`) until the out-of-scope contract migration retires
> it, so the readers-before-writers rollout never `KeyError`s an un-upgraded reader; add a
> regression test pinning the `free_slots` key.

### BC3 — stable-jitter correctness (low) — `source_finding: f_jitter_null`

> Make the jitter `ORDER BY` NULL-safe at the SQL layer
> (`hashtext(COALESCE(job,'') || node || slot_id::text)`) so an explicit `job=None` degrades
> safely instead of collapsing every row's hash to NULL; test the tie-breaker stays active
> for `job=''` and `job=None`.

### BC4 — failover lifecycle (low) — `source_finding: f_failover_nosurvivor`

> Make the no-survivor failover branch explicitly release the dead shard's lease so the slot
> frees immediately rather than waiting up to the TTL; keep the atomic release+claim of the
> survivor path (it serves the RFC's herd-avoidance); test that a no-survivor failover frees
> the slot without waiting for the TTL.

---

## 2. Ground truth (current source, re-read at build time)

Source lives at the repo root. Columns/queries the RFC touches today:

- `migrations/001_gpu_slots.sql` — `gpu_slots` has `free_slots INT NOT NULL DEFAULT 1
  CHECK (free_slots >= 0)`, `epoch BIGINT`, `alive`, `heartbeat_ts`, PK
  `(node, endpoint_url, slot_id)`; index `gpu_slots_claim_idx ON (latency_class, alive,
  free_slots DESC, heartbeat_ts DESC)`; view `live_slots` (alive AND fresh heartbeat).
- `migrations/002_fleet_nodes.sql` — `fleet_nodes` (the desired set) also has a `free_slots`
  column; seed rows are the current proximal + peecee fleet.
- `migrations/005_peecee_load_aware.sql` — added `fleet_nodes.min_load_vram_mib`; flipped
  peecee slot 0 to `probe_model='ollama-ondemand'` (load-aware liveness, #2).
- `pick_slot.py` — `PICK` SQL selects `free_slots`, `ORDER BY free_slots DESC, …`,
  `FOR UPDATE SKIP LOCKED LIMIT k`; `pick(conn, latency_class, model, min_vram, k)`.
- `heartbeat.py` / `heartbeat_all.py` — the **live writer**. `UPSERT` INSERTs
  `… free_slots …` and `ON CONFLICT … DO UPDATE SET … free_slots=EXCLUDED.free_slots …`;
  `heartbeat_all.FETCH` selects `free_slots` from `fleet_nodes` and carries it into the
  per-tick row. Runs under systemd (`gpu-fleet-heartbeat`) and must keep working untouched
  across migration 006.
- `di_fleet.py` — `route_slots` → `dispatch` → `run_shard` (one **blocking**
  `subprocess.run` of `di --json` per shard, inside a `ThreadPoolExecutor`); failover
  reassigns a dead shard's frames to a survivor and retries once. Injectable seams are
  `pick_fn`, `shard_fn` (mirrors `probe_fn`).
- `bin/di-fleet` — thin bash wrapper `exec python3 di_fleet.py "$@"`; re-deploying it is an
  operator step.
- `tests/` — 26 tests today (`test_di_fleet.py`, `test_load_aware_liveness.py`,
  `test_probe_all.py`), **all hermetic** via injected fakes; `conftest.py` only puts the
  repo root on `sys.path`. No test touches a real DB/HTTP/subprocess.

**Load-bearing fact shaping the migration:** the *running* heartbeat writer and `pick_slot`
both reference the column name `free_slots`. A literal `ALTER TABLE … RENAME COLUMN
free_slots TO capacity` would break the live writer the instant the DDL commits — before any
consumer change — which is **not** the backward-compatibility the RFC and the task require.
This plan therefore implements the RFC's rename as an **expand/contract (parallel-change)**:
add `capacity` now, retire `free_slots` in a later, out-of-scope contract migration. End
state is identical to the RFC; the in-between state never breaks a running process and is
fully reversible.

---

## 3. Scope & slices (ordered, independently committable)

Each slice is one commit, lands green on `python3 -m pytest tests/ -q`, and is safe to stop
after. Order encodes the migration discipline **DB → readers → writers**.

### Slice A — Migration 006 (additive expand) + backfill

**Blast radius:** `migrations/006_exclusive_slot_leases.sql` (new). No code changes. No
existing query rewritten in this slice.

- `ALTER TABLE gpu_slots ADD COLUMN IF NOT EXISTS capacity INT NOT NULL DEFAULT 1
  CHECK (capacity >= 1);` (immutable max concurrent leases).
- Backfill `UPDATE gpu_slots SET capacity = GREATEST(free_slots, 1);` (current fleet is all
  capacity-1; `free_slots` defaulted to 1).
- `ADD COLUMN IF NOT EXISTS lease_id UUID;` (NULL = free), `lease_holder TEXT`,
  `lease_expires TIMESTAMPTZ` — all nullable, no default, so a fresh INSERT that omits them
  (today's heartbeat UPSERT) leaves them NULL ⇒ every slot reads free ⇒ today's behavior.
- New partial/covering index for the lease-free pick path, e.g.
  `CREATE INDEX IF NOT EXISTS gpu_slots_lease_pick_idx ON gpu_slots (alive, heartbeat_ts DESC)
  WHERE lease_id IS NULL;` (complements, does not replace, `gpu_slots_claim_idx`).
- **Keep** `free_slots` and `gpu_slots_claim_idx` untouched. They are dropped only in the
  out-of-scope contract migration (§4).
- Add a one-line comment in 006 (and in `pick_slot.py`) that `capacity` is the expand-half
  of the RFC-mandated `free_slots → capacity` rename and is intentionally not dynamically
  branched on in the capacity-1 pick path — so a future reader does not mistake it for a
  dead/drifting column. *(non-binding clarity note from the cycle-1 adjudication)*

**Why safe with the live writer running:** purely additive DDL; the heartbeat's
`INSERT … (… free_slots …)` and `ON CONFLICT … free_slots=EXCLUDED.free_slots` still
reference only existing columns; new columns default NULL. `ADD COLUMN` with a non-volatile
default is a metadata-only change on modern Postgres (no table rewrite).

### Slice B — `pick_slot.py` learns the lease-free predicate + stable jitter **(folds BC2, BC3)**

**Blast radius:** `pick_slot.py`, `tests/test_pick_slot.py` (new, hermetic).

- Add to the `WHERE`: `AND (lease_id IS NULL OR now() >= lease_expires)` (lease-free only —
  derives availability from live leases, no counter read).
- Derive availability from `capacity` (capacity-1 ⇒ the lease-free predicate *is* the
  availability test). Order by warm-pref then `vram_free_mib DESC, probe_ms ASC NULLS LAST`,
  with a trailing **stable-jitter** tie-breaker. **BC3:** the jitter expression MUST be
  NULL-safe at the SQL layer — `hashtext(COALESCE(job,'') || node || slot_id::text)` — so an
  explicit `job=None` / SQL NULL degrades safely instead of collapsing every row's hash to
  NULL. Add an optional `job` parameter (default `''`) so a no-arg call still works and the
  jitter is stable per `(job, slot)`.
- **BC2 (binding backward-compat):** `pick_slot.py` MUST keep surfacing `free_slots` in its
  returned dict / `--json` output until the out-of-scope contract migration retires it — the
  simplest correct form is to **alias `capacity` to `free_slots`** in the output. The
  readers-before-writers rollout (Slice B before Slice D) opens a mixed-version window; an
  un-upgraded reader (old `di_fleet`, a fleet tool, `pick_slot.py --json`) reading
  `result["free_slots"]` MUST NOT `KeyError`. Drop the `free_slots` *reference from
  `SELECT`/`ORDER BY`* (replaced by the lease predicate + capacity) but **retain the
  `free_slots` output key**.
- Keep `FOR UPDATE SKIP LOCKED LIMIT k` — now a throughput tweak, not the correctness path.
  Return `lease_id` / `lease_expires` columns so a consumer can claim what it picked.

**Tests (BC2, BC3):** `test_pick_slot.py` (hermetic, fake `conn`) pins (a) the lease-free
predicate + jitter, (b) **BC2** — the returned dict still contains `free_slots`, (c) **BC3**
— the tie-breaker stays active for both `job=''` and `job=None`. The existing 26 tests stay
green unchanged.

### Slice C — Lease lifecycle module (`leases.py`)

**Blast radius:** `leases.py` (new), `tests/test_leases.py` (new, hermetic),
`tests/test_leases_pg.py` (new, **guarded** real-Postgres).

A single small module of pure functions over an injected `conn` (mirrors the "`conn` in, no
global DB" discipline of `pick_slot.pick`). All time predicates use Postgres `now()`; **no
Python clock is ever read** for expiry or fencing.

- `claim(conn, slot, holder, ttl_seconds, model_mib) -> lease_id | None` — atomic
  conditional `UPDATE … SET lease_id=gen_random_uuid(), lease_holder=$holder,
  lease_expires=now() + $ttl WHERE (node,endpoint_url,slot_id)=$chosen AND alive AND
  heartbeat_ts > now() - interval '45 seconds' AND vram_free_mib >= $model_mib AND
  (lease_id IS NULL OR now() >= lease_expires) RETURNING lease_id`. Zero rows → `None`.
- `renew(conn, lease_id, ttl_seconds) -> bool` — `UPDATE … SET lease_expires=now()+$ttl
  WHERE lease_id=$held AND now() < lease_expires RETURNING lease_id`. Zero rows → `False` =
  "lease lost — stop touching the GPU."
- `release(conn, lease_id) -> None` — `UPDATE … SET lease_id=NULL, lease_holder=NULL,
  lease_expires=NULL WHERE lease_id=$held`.
- `failover_transfer(conn, dead_lease_id, candidate_slots, holder, ttl, model_mib)
  -> lease | None` — **one transaction**: `release(dead_lease_id)` then `claim()` the first
  claimable candidate; commit together or roll back together. Returns the new lease, or
  `None` if no candidate was claimable.
- Constants: `TTL_SECONDS = 45` (folds into the heartbeat TTL), `RENEW_SECONDS = 15`
  (TTL/3). `model_mib` defaults to `0` when the consumer supplies none.

### Slice D — `di_fleet.py` claims / renews / releases around each shard **(folds BC1, BC4)**

**Blast radius:** `di_fleet.py`, `tests/test_di_fleet.py` (extend).

- Before running a shard, **claim** its slot's lease; renew while the shard runs; **release**
  on completion (clean or error).
- **BC1 (critical gate) — in-flight abort, MANDATORY.** Replace the blocking
  `subprocess.run` of `di --json` with **`subprocess.Popen` plus a per-shard lease monitor**
  (or move renew+cancel into the worker that owns the child handle). When the shard's lease
  is lost — renewer death, renew failure from heartbeat staleness, or a zombie re-claim
  winning — the monitor MUST **terminate the `di --json` child immediately, before any second
  consumer can claim and use the GPU**. As specified in the holder's original C7 (central
  renewer + blocking `subprocess.run`), renewal **was on the correctness path**, not off it:
  C7 is restated accordingly. The `di --json` shell-out boundary is preserved — the monitor
  operates on the **process handle** (`Popen.terminate()` / `kill()`), it does **not** import
  the Node engine (`~/git/divergent-ideation`).
- Renewal mechanism: a single bounded renewer (off the correctness path) keeps active leases
  fresh; **but it is not the exclusivity guarantee** — the per-shard `Popen` + lease monitor
  is. If renewal stalls/dies, the lease expires and the per-shard monitor aborts that shard's
  child exactly like a deadman. (This supersedes the holder's "zero extra threads / piggyback
  on the shard loop" aside — that literal form left the child uncancellable; see BC1.)
- **BC4 — failover.** Replace plain reassign-and-retry with `leases.failover_transfer` so a
  dead shard's lease is released **in the same commit** that claims its replacement (no
  double-hold, no leak). **The no-survivor branch MUST explicitly release the dead shard's
  lease** so the slot frees immediately rather than waiting up to the TTL; then degrade as
  today (frames abandoned, said on stderr). Keep the survivor-path atomic transfer (it serves
  the RFC's herd-avoidance — freed capacity never hits the open pool).
- Make the lease operations injectable (`lease_ops=` carrying claim/renew/release/transfer,
  default = the real `leases` module) so every new behavior is hermetically testable with
  fakes — same pattern as `shard_fn`/`pick_fn`. The `di` subprocess boundary (`run_shard`)
  keeps its shell-out; lease logic lives entirely in `di_fleet.py` Python.

### Slice E — "No consumer wall-clock" inspection test + deploy docs

**Blast radius:** `tests/test_lease_no_consumer_clock.py` (new, hermetic),
`migrations/006_exclusive_slot_leases.sql` header + `README.md` (deploy-ordering note).

- A source-inspection test asserting the lease SQL strings contain `now()` and the
  `leases.py` / `di_fleet.py` lease functions never call `time.*` / `datetime.*` to decide
  expiry or fencing (the renewer's *sleep interval* is allowed; the *predicate* must be
  Postgres-side). Pure import + string/AST inspection; no DB.

> **Deferred, NOT built in v1** (RFC open questions): sub-second soft-reservation (gated
> behind a flag), the `capacity > 1` `slot_leases` table, and `lease_token` fencing. Slices
> stop at E.

---

## 4. Migration plan (exact schema, apply order, reversibility)

**Next number is 006** (001–005 taken). One new file:
`migrations/006_exclusive_slot_leases.sql`, content per Slice A.

**Backward-compatibility (the core claim):** 006 is purely additive — `ADD COLUMN`
(nullable lease columns; `capacity` with a constant default), a backfill `UPDATE`, and one
new index. It renames nothing and drops nothing. Until `pick_slot` and `di_fleet` are updated
(Slices B–D), **fleet behavior equals today's**: leases are NULL ⇒ `live_slots` and the
unchanged `PICK` see every slot as before; the running heartbeat writer's `free_slots` column
still exists and is still written; with BC2, `pick_slot` output still carries `free_slots`.

**Apply order (operator, AFTER integration — not part of this build):**

1. **DB:** apply `006` (additive ⇒ safe even with the heartbeat service running; the operator
   may still prefer stop→migrate→start, equally safe).
2. **Readers:** the new `pick_slot.py` (Slice B) — picks lease-free slots, still emits
   `free_slots`.
3. **Writers/consumers:** the new `di_fleet.py` (Slice D) + re-deploy `bin/di-fleet` — begins
   claiming/renewing/releasing with the BC1 in-flight abort active.

The heartbeat writer needs **no change** in v1 (see Boundaries §6).

**Reversibility:** before any consumer claims, `006` is reversible with
`ALTER TABLE gpu_slots DROP COLUMN lease_id, DROP COLUMN lease_holder, DROP COLUMN
lease_expires, DROP COLUMN capacity; DROP INDEX gpu_slots_lease_pick_idx;` — `free_slots`
was never touched, so rollback restores the exact prior schema and behavior.

**Out of scope — the contract migration (future 007):** once `pick_slot`/`di_fleet` no longer
read `free_slots` AND the heartbeat is updated to stop writing it, a later migration drops
`gpu_slots.free_slots` (+ `fleet_nodes.free_slots`) and `gpu_slots_claim_idx`. Sequenced as:
(1) heartbeat stops writing `free_slots`, (2) 007 drops the column. **Not built here** —
this build stays strictly additive and reversible.

---

## 5. Falsifiable gate → test map (binding constraints folded in)

The default `python3 -m pytest tests/ -q` (26 today) **stays green and hermetic**. New
hermetic tests add to that count and need no DB. DB-backed tests are **guarded**: they
`pytest.importorskip("psycopg")` and skip unless an ephemeral test DB is provided via an env
var (e.g. `GPU_FLEET_TEST_DB`), so the hermetic default is never broken by a missing DB. The
guard points at a throwaway/ephemeral cluster (a tmp `initdb` or a disposable
`CREATE DATABASE`), **never** `dbname=gpu_fleet`.

| RFC gate bullet | Concrete test | Kind |
|---|---|---|
| Two concurrent consumers on a capacity-1 slot → **exactly one** holds (loser's CLAIM returns 0 rows) | `test_leases_pg.py::test_two_concurrent_claims_exactly_one_wins` — two real connections issue the conditional CLAIM concurrently; assert exactly one `RETURNING` a row. Hermetic companion `test_leases.py::test_claim_returns_none_when_predicate_unmet`. | **Ephemeral real Postgres** (atomicity is a DB property a fake can't prove) |
| **BC1 — physical exclusivity:** a lost lease terminates the running `di --json` child **before any second claim** (DB-only test is necessary but NOT sufficient) | `test_di_fleet.py::test_lease_loss_terminates_child_before_second_claim` — under a disposable lease, a **long-running fake child** is terminated before a second claim can run concurrently; assert the child is killed and no second claim overlaps physical use. **No live infra.** | **Hermetic — the mandatory BC1 gate the verifier confirms before accept** |
| Consumer stops renewing (simulated crash) → slot free within ≤ TTL, **no reaper running** | `test_leases_pg.py::test_unrenewed_lease_self_expires` — claim with a short TTL, do not renew, assert a second CLAIM succeeds after the TTL with only the two test connections alive. Hermetic companion `test_di_fleet.py::test_release_called_on_completion_and_no_renew_after`. | **Ephemeral real Postgres** + hermetic |
| Zombie renew after re-claim → **zero rows** (fenced) | `test_leases_pg.py::test_zombie_renew_after_reclaim_is_fenced` — claim (lease₁), expire, re-claim (lease₂), assert renew `WHERE lease_id=lease₁` returns 0 rows. Hermetic companion `test_di_fleet.py::test_failed_renew_aborts_shard`. | **Ephemeral real Postgres** + hermetic |
| K-fan-out across N slots holds **N distinct** leases; failover releases dead lease + claims survivor **atomically** | `test_di_fleet.py::test_kfanout_claims_n_distinct_leases` and `::test_failover_transfer_releases_dead_and_claims_survivor` (injected fake `lease_ops`); atomicity by `test_leases_pg.py::test_failover_transfer_is_atomic` (force mid-transfer failure ⇒ both release and claim roll back). | **Hermetic** (wiring) + **ephemeral real Postgres** (atomicity) |
| **BC4 — no-survivor failover** frees the slot immediately (not after TTL) | `test_di_fleet.py::test_no_survivor_failover_releases_dead_lease` — no claimable candidate ⇒ the dead lease is explicitly released, slot free without waiting for the TTL. | **Hermetic** |
| **No consumer wall-clock** read in claim/renew/release (inspection) | `test_lease_no_consumer_clock.py` — assert lease SQL uses `now()` and the lease functions never read `time.*`/`datetime.*` for an expiry/fence decision. | **Hermetic** (source inspection) |
| **BC2 — pick_slot backward-compat** | `test_pick_slot.py::test_output_still_contains_free_slots` — returned dict / `--json` still has the `free_slots` key (aliased from `capacity`). | **Hermetic** |
| **BC3 — NULL-safe jitter** | `test_pick_slot.py::test_jitter_active_for_empty_and_none_job` — tie-breaker active for both `job=''` and `job=None` (COALESCE keeps the hash non-NULL). | **Hermetic** |

**Verifier gate (from the operator override):** the build is **not** accepted until the
independent verifier confirms **BC1's** `test_lease_loss_terminates_child_before_second_claim`
— the DB-only two-transaction concurrency test alone is insufficient for the RFC's
exactly-one-holder-at-any-instant invariant.

---

## 6. Live-infra safety & boundaries to preserve

The build writes **only** migration SQL, Python, and tests, and runs the **hermetic**
`pytest`. It MUST NOT:

- touch the live `gpu_fleet` Postgres DB (no migration is applied to it; DB-backed tests use
  an ephemeral throwaway cluster gated behind `GPU_FLEET_TEST_DB`, defaulting OFF);
- restart or perturb the running `gpu-fleet-heartbeat` service (Slice A is designed so the
  *running* writer keeps working unchanged; the build never restarts it);
- touch peecee's shared GPU or `marker` (no probes, no loads — the load-aware liveness from
  #2 is *inherited* as a claim precondition, not re-exercised).

**Boundaries to preserve:**

- **di → `di` is a subprocess.** `run_shard` still shells `node … di … --json` and never
  imports the Node engine (`~/git/divergent-ideation`). BC1's abort operates on the process
  **handle**; the boundary is unchanged.
- **`bin/di-fleet` re-deploy is an operator step** — the build edits the file in-repo only.
- **The heartbeat writer is untouched in v1.** `capacity` is *immutable* (Principle 1): set
  once by the migration backfill / the `ADD COLUMN` default for new nodes, never mutated per
  tick. The heartbeat keeps writing `free_slots` harmlessly. Plumbing `capacity` from
  `fleet_nodes` into the heartbeat belongs to the capacity>1 evolution, not v1.
- **`epoch` is not overloaded** for lease fencing (RFC Principle 2 / RFC-0003). Lease
  identity is `lease_id`; `epoch` stays for topology/model-change.

---

## 7. Operator deployment steps (the RFC's required rollout — restate in the build's final report)

Performed by the operator **after** the build integrates; **nothing in the build performs
these.** This is the exact ordering the RFC mandates (DB → readers → writers), restated so the
build's final report can hand it to the operator verbatim:

1. **DB:** apply `migrations/006_exclusive_slot_leases.sql` (additive ⇒ safe with the
   heartbeat running; `stop → migrate → start` optional and equally safe).
2. **Readers:** deploy the new `pick_slot.py` — picks lease-free slots, still emits
   `free_slots` (BC2).
3. **Writers/consumers:** deploy the new `di_fleet.py` and re-deploy `bin/di-fleet` — begins
   claiming / renewing / releasing with the BC1 in-flight abort active.

No heartbeat change in v1. The later contract migration (007, out of scope) drops
`free_slots` only after the heartbeat stops writing it.

---

## 8. Definition of done (for the downstream build run)

- `migrations/006_exclusive_slot_leases.sql` exists, additive, reversible (§4).
- `pick_slot.py`, `leases.py`, `di_fleet.py` implement claim/renew/release/transfer with
  injectable seams; `bin/di-fleet` unchanged in behavior.
- **BC1 discharged:** `di_fleet.py` uses `Popen` + per-shard lease monitor that terminates
  the `di --json` child on lease loss; `test_lease_loss_terminates_child_before_second_claim`
  exists, is no-live-infra, and passes. **The verifier confirms this test before accept.**
- **BC2, BC3, BC4 discharged** with their named tests (free_slots key preserved; NULL-safe
  jitter for `job=''`/`job=None`; no-survivor failover frees immediately).
- Every §5 gate row has its named test; `python3 -m pytest tests/ -q` is green and hermetic
  (≥ 26 + new hermetic tests); DB-backed tests skip without `GPU_FLEET_TEST_DB`.
- No live infra touched (§6). Operator applies 006 + re-deploys (§7) post-integration.
