# BUILD_PLAN — RFC 0001 Exclusive slot leases

author: holder-claude-opus-4.8-001

This is the **leading build proposal** translating the settled RFC
`docs/rfc/0001-exclusive-slot-leases.md` into an ordered, independently-committable,
falsifiable plan. It does **not** re-open the RFC's design decisions (capacity is
derived; Postgres is the only clock; expiry and fencing are separate; leases inherit
load-aware liveness). It commits the *engineering* the RFC leaves open: migration
safety, the exact blast radius per slice, the gate→test map, and live-infra safety.

Where this plan **refines** the RFC's literal wording (the `RENAME` rollout step and
the "zero extra threads" renewal aside), it says so explicitly and makes the refinement
a falsifiable claim — because the task's hard requirement ("backward-compatible: until
consumers use the new columns/state, fleet behavior equals today's") *contradicts* a
literal in-place `RENAME`, and the holder's job is to surface that, not paper over it.

---

## 0. Ground truth (current source, read this build cycle)

Source lives at the repo root. The columns/queries the RFC touches today:

- `migrations/001_gpu_slots.sql` — `gpu_slots` has `free_slots INT NOT NULL DEFAULT 1
  CHECK (free_slots >= 0)`, `epoch BIGINT`, `alive`, `heartbeat_ts`, PK
  `(node, endpoint_url, slot_id)`; index `gpu_slots_claim_idx ON (latency_class, alive,
  free_slots DESC, heartbeat_ts DESC)`; view `live_slots` (alive AND fresh heartbeat).
- `migrations/002_fleet_nodes.sql` — `fleet_nodes` (the desired set) also has a
  `free_slots` column; the seed rows are the current proximal + peecee fleet.
- `migrations/005_peecee_load_aware.sql` — added `fleet_nodes.min_load_vram_mib`; flipped
  peecee slot 0 to `probe_model='ollama-ondemand'` (the load-aware liveness #2).
- `pick_slot.py` — `PICK` SQL selects `free_slots`, `ORDER BY free_slots DESC, …`,
  `FOR UPDATE SKIP LOCKED LIMIT k`; `pick(conn, latency_class, model, min_vram, k)`.
- `heartbeat.py` / `heartbeat_all.py` — the **live writer**. `UPSERT` INSERTs
  `… free_slots …` and `ON CONFLICT … DO UPDATE SET … free_slots=EXCLUDED.free_slots …`;
  `heartbeat_all.FETCH` selects `free_slots` from `fleet_nodes` and carries it into the
  per-tick row. This process runs under systemd (`gpu-fleet-heartbeat`) and must keep
  working untouched across migration 006.
- `di_fleet.py` — `route_slots` → `dispatch` → `run_shard` (one **blocking**
  `subprocess.run` of `di --json` per shard, inside a `ThreadPoolExecutor`); failover
  reassigns a dead shard's frames to a survivor and retries once. The injectable seams
  are `pick_fn`, `shard_fn` (mirrors `probe_fn`).
- `bin/di-fleet` — thin bash wrapper `exec python3 di_fleet.py "$@"`; re-deploying it is
  an operator step.
- `tests/` — 26 tests today (`test_di_fleet.py`, `test_load_aware_liveness.py`,
  `test_probe_all.py`), **all hermetic** via injected fakes; `conftest.py` only puts the
  repo root on `sys.path`. No test touches a real DB/HTTP/subprocess.

**The load-bearing fact that shapes the migration:** the *running* heartbeat writer and
`pick_slot` both reference the column name `free_slots`. A literal `ALTER TABLE … RENAME
COLUMN free_slots TO capacity` would break the live writer the instant the DDL commits —
before any consumer change — which is **not** the backward-compatibility the RFC and the
task require. This plan therefore implements the RFC's rename as an **expand/contract**
(parallel-change): add `capacity` now, retire `free_slots` in a later, out-of-scope
contract migration. End state is identical to the RFC; the in-between state never breaks
a running process and is fully reversible.

---

## 1. Scope & slices (ordered, independently committable)

Each slice is one commit, lands green on `python3 -m pytest tests/ -q`, and is safe to
stop after. Order encodes the migration discipline **DB → readers → writers**.

### Slice A — Migration 006 (additive expand) + backfill

**Files touched (blast radius):** `migrations/006_exclusive_slot_leases.sql` (new). No
code changes. No existing query is rewritten in this slice.

- `ALTER TABLE gpu_slots ADD COLUMN IF NOT EXISTS capacity INT NOT NULL DEFAULT 1
  CHECK (capacity >= 1);`  (immutable max concurrent leases)
- Backfill `UPDATE gpu_slots SET capacity = GREATEST(free_slots, 1);` (current fleet is
  all capacity-1; `free_slots` defaulted to 1).
- `ADD COLUMN IF NOT EXISTS lease_id UUID;` (NULL = free), `lease_holder TEXT`,
  `lease_expires TIMESTAMPTZ` — all nullable, no default, so a fresh INSERT that omits
  them (today's heartbeat UPSERT) leaves them NULL ⇒ every slot reads free ⇒ today's
  behavior.
- New partial/covering index for the lease-free pick path, e.g.
  `CREATE INDEX IF NOT EXISTS gpu_slots_lease_pick_idx ON gpu_slots
   (alive, heartbeat_ts DESC) WHERE lease_id IS NULL;` (complements, does not replace,
  `gpu_slots_claim_idx`).
- **Keep** `free_slots` and `gpu_slots_claim_idx` untouched. They are dropped only in the
  out-of-scope contract migration (see §2).

**Why it is safe with the live writer running:** purely additive DDL; the heartbeat's
`INSERT … (… free_slots …)` and `ON CONFLICT … free_slots=EXCLUDED.free_slots` still
reference only existing columns; the new columns default to NULL. `ADD COLUMN` with a
non-volatile default is a metadata-only change on modern Postgres (no table rewrite).

### Slice B — `pick_slot.py` learns the lease-free predicate + stable jitter

**Files touched:** `pick_slot.py`, `tests/test_pick_slot.py` (new, hermetic).

- Add to the `WHERE`: `AND (lease_id IS NULL OR now() >= lease_expires)` (lease-free
  only — derives availability from live leases, no counter read).
- Derive availability from `capacity` (capacity-1 ⇒ the lease-free predicate *is* the
  availability test). Drop the `free_slots` reference from `SELECT`/`ORDER BY`; order by
  warm-pref then `vram_free_mib DESC, probe_ms ASC NULLS LAST`, with a trailing
  `hashtext(%(job)s || node || slot_id::text)` **stable jitter** tie-breaker (RFC
  thundering-herd item 1). Add an optional `job` parameter (default `''`) so the jitter
  is stable per `(job, slot)` and a no-arg call still works.
- Keep `FOR UPDATE SKIP LOCKED LIMIT k` — now a throughput tweak, not the correctness
  path. Return `lease_id`/`lease_expires` columns so a consumer can claim what it picked.

### Slice C — Lease lifecycle module (`leases.py`)

**Files touched:** `leases.py` (new), `tests/test_leases.py` (new, hermetic),
`tests/test_leases_pg.py` (new, **guarded** real-Postgres).

A single small module of pure functions over an injected `conn` (mirrors the
"`conn` in, no global DB" discipline of `pick_slot.pick`). All time predicates use
Postgres `now()`; **no Python clock is ever read** for expiry or fencing.

- `claim(conn, slot, holder, ttl_seconds, model_mib) -> lease_id | None` — the atomic
  conditional `UPDATE … SET lease_id=gen_random_uuid(), lease_holder=$holder,
  lease_expires=now() + $ttl WHERE (node,endpoint_url,slot_id)=$chosen AND alive AND
  heartbeat_ts > now() - interval '45 seconds' AND vram_free_mib >= $model_mib AND
  (lease_id IS NULL OR now() >= lease_expires) RETURNING lease_id`. Zero rows → `None`
  (lost the race / not claimable).
- `renew(conn, lease_id, ttl_seconds) -> bool` — `UPDATE … SET lease_expires=now()+$ttl
  WHERE lease_id=$held AND now() < lease_expires RETURNING lease_id`. Zero rows → `False`
  = "lease lost — stop touching the GPU."
- `release(conn, lease_id) -> None` — `UPDATE … SET lease_id=NULL, lease_holder=NULL,
  lease_expires=NULL WHERE lease_id=$held`.
- `failover_transfer(conn, dead_lease_id, candidate_slots, holder, ttl, model_mib)
  -> lease | None` — **one transaction**: `release(dead_lease_id)` then `claim()` the
  first claimable candidate; commit together or roll back together. Returns the new lease
  or `None` if no candidate was claimable (degrade to the existing no-survivor path).
- Constants: `TTL_SECONDS = 45` (folds into the heartbeat TTL), `RENEW_SECONDS = 15`
  (TTL/3). `model_mib` defaults to `0` when the consumer supplies none (no extra VRAM
  gate beyond the liveness already encoded in `alive`).

### Slice D — `di_fleet.py` claims / renews / releases around each shard

**Files touched:** `di_fleet.py`, `tests/test_di_fleet.py` (extend).

- Before running a shard, **claim** its slot's lease; renew every `RENEW_SECONDS` for as
  long as the shard's `di` subprocess runs; **release** on completion (clean or error).
- Renewal mechanism: a **single bounded daemon renewer** (one thread + one psycopg
  connection) started before `dispatch`'s `ThreadPoolExecutor` and stopped after. It
  renews every active lease each `RENEW_SECONDS`. This is **off the correctness path**:
  if the renewer dies, leases simply expire and each shard's next claim/renew check fails
  → the shard self-aborts exactly like a deadman. (This refines the RFC's "piggyback on
  the existing shard loop / zero extra threads" aside — see Claim C7 for why and the
  observation that would force the per-shard `Popen`+poll alternative instead.)
- Failover: replace the plain reassign-and-retry with `leases.failover_transfer` so a
  dead shard's lease is released **in the same commit** that claims its replacement — no
  double-hold, no leak. If no survivor is claimable, degrade exactly as today (frames
  abandoned, said on stderr).
- Make the lease operations injectable (`lease_ops=` carrying claim/renew/release/
  transfer, default = the real `leases` module) so every new behavior is hermetically
  testable with fakes — same pattern as `shard_fn`/`pick_fn`. The `di` subprocess
  boundary (`run_shard`) is **unchanged**; leases live entirely in `di_fleet.py` Python.

### Slice E — "No consumer wall-clock" inspection test + deploy docs

**Files touched:** `tests/test_lease_no_consumer_clock.py` (new, hermetic),
`migrations/006_exclusive_slot_leases.sql` header + `README.md` (deploy ordering note).

- A source-inspection test asserting the lease SQL strings contain `now()` and the
  `leases.py` / `di_fleet.py` lease functions never call `time.*`/`datetime.*` to decide
  expiry or fencing (the renewer's *sleep interval* is allowed; the *predicate* must be
  Postgres-side). Pure import + string/AST inspection; no DB.

> **Deferred, NOT built in v1** (RFC open questions): the sub-second soft-reservation
> (gated behind a flag), the `capacity > 1` `slot_leases` table, and `lease_token`
> fencing. Slices stop at E.

---

## 2. Migration plan (exact schema changes, apply order, reversibility)

**Next number is 006** (001–005 taken). One new file:
`migrations/006_exclusive_slot_leases.sql`, content per Slice A.

**Backward-compatibility argument (the core claim):** 006 is purely additive — `ADD
COLUMN` (nullable lease columns; `capacity` with a constant default), a backfill `UPDATE`,
and one new index. It renames nothing and drops nothing. Therefore, until `pick_slot` and
`di_fleet` are updated (Slices B–D), **fleet behavior equals today's**: leases are NULL ⇒
`live_slots` and the unchanged `PICK` see every slot as before; the running heartbeat
writer's `free_slots` column still exists and is still written.

**Apply order (operator, AFTER integration — not part of this build):**
1. **DB:** apply `006` (additive ⇒ safe even with the heartbeat service running; the
   operator may still prefer stop→migrate→start, which is equally safe).
2. **Readers:** the new `pick_slot.py` (Slice B) — picks lease-free slots.
3. **Writers/consumers:** the new `di_fleet.py` (Slice D) + re-deploy `bin/di-fleet` —
   begins claiming/renewing/releasing.
The heartbeat writer needs **no change** in v1 (see Boundaries §5).

**Reversibility:** before any consumer claims, `006` is reversible with
`ALTER TABLE gpu_slots DROP COLUMN lease_id, DROP COLUMN lease_holder, DROP COLUMN
lease_expires, DROP COLUMN capacity; DROP INDEX gpu_slots_lease_pick_idx;` — `free_slots`
was never touched, so rollback restores the exact prior schema and behavior.

**Out of scope — the contract migration (future 007):** once `pick_slot`/`di_fleet` no
longer read `free_slots` AND the heartbeat is updated to stop writing it, a later
migration drops `gpu_slots.free_slots` (+ `fleet_nodes.free_slots`) and
`gpu_slots_claim_idx`. Sequenced as: (1) heartbeat stops writing `free_slots`, (2) 007
drops the column. **Not built here** — keeping this build strictly additive and
reversible.

---

## 3. Test plan mapped to the RFC's "Falsifiable gate"

The default `python3 -m pytest tests/ -q` (26 today) **stays green and hermetic**. New
hermetic tests add to that count and need no DB. DB-backed tests are **guarded**: they
`pytest.importorskip("psycopg")` and skip unless an ephemeral test DB is provided via an
env var (e.g. `GPU_FLEET_TEST_DB`), so the hermetic default is never broken by a missing
DB. The guard points at a throwaway/ephemeral cluster (e.g. a tmp `initdb` or a disposable
`CREATE DATABASE`), **never** `dbname=gpu_fleet`.

| RFC gate bullet | Concrete test | Kind |
|---|---|---|
| Two concurrent consumers on a capacity-1 slot → **exactly one** holds (loser's CLAIM returns 0 rows) | `test_leases_pg.py::test_two_concurrent_claims_exactly_one_wins` — two real connections issue the conditional CLAIM concurrently; assert exactly one `RETURNING` a row. (Hermetic companion `test_leases.py::test_claim_returns_none_when_predicate_unmet` pins the consumer's "0 rows → try next" handling.) | **Ephemeral real Postgres** (atomicity is a DB property a fake can't prove) |
| Consumer stops renewing (simulated crash) → slot free within ≤ TTL, **no reaper running** | `test_leases_pg.py::test_unrenewed_lease_self_expires` — claim with a short TTL, do not renew, assert a second CLAIM succeeds after the TTL with only the two test connections alive (no reaper). Hermetic companion: `test_di_fleet.py::test_release_called_on_completion_and_no_renew_after`. | **Ephemeral real Postgres** + hermetic |
| Zombie renew after re-claim → **zero rows** (fenced) | `test_leases_pg.py::test_zombie_renew_after_reclaim_is_fenced` — claim (lease₁), expire, re-claim (lease₂), assert renew `WHERE lease_id=lease₁` returns 0 rows. Hermetic companion: `test_di_fleet.py::test_failed_renew_aborts_shard` (renew→False ⇒ shard stops). | **Ephemeral real Postgres** + hermetic |
| K-fan-out across N slots holds **N distinct** leases; failover releases dead lease + claims survivor **atomically** (no double-hold, no leak) | `test_di_fleet.py::test_kfanout_claims_n_distinct_leases` and `::test_failover_transfer_releases_dead_and_claims_survivor` (injected fake lease_ops — N distinct ids, dead released, survivor claimed, no double-hold). Atomicity of the transfer proven by `test_leases_pg.py::test_failover_transfer_is_atomic` (force a failure mid-transfer ⇒ both release and claim roll back). | **Hermetic** (fan-out/failover wiring) + **ephemeral real Postgres** (transfer atomicity) |
| **No consumer wall-clock** read in claim/renew/release (inspection) | `test_lease_no_consumer_clock.py` — assert lease SQL uses `now()` and the lease functions never read `time.*`/`datetime.*` for an expiry/fence decision. | **Hermetic** (source inspection) |

Plus regression: `test_pick_slot.py` (Slice B) pins the lease-free predicate + jitter
hermetically with a fake `conn`; the existing 26 tests must remain green unchanged.

---

## 4. Live-infra safety

The build writes **only** migration SQL, Python, and tests, and runs the **hermetic**
`pytest`. It MUST NOT:
- touch the live `gpu_fleet` Postgres DB (no migration is applied to it; DB-backed tests
  use an ephemeral throwaway cluster gated behind `GPU_FLEET_TEST_DB`, defaulting OFF);
- restart or perturb the running `gpu-fleet-heartbeat` service (Slice A is designed so the
  *running* writer keeps working unchanged; the build never restarts it);
- touch peecee's shared GPU or `marker` (no probes, no loads — the load-aware liveness from
  #2 is *inherited* as a claim precondition, not re-exercised).

The operator, **after** integration, applies `006` (additive; stop→migrate→start optional)
and re-deploys `bin/di-fleet` / the heartbeat as in §2. Nothing in the build performs those
steps.

---

## 5. Boundaries to preserve

- **di → `di` is a subprocess.** `run_shard` still shells `node … di … --json` and never
  imports the Node engine (`~/git/divergent-ideation`). Lease claim/renew/release live in
  `di_fleet.py`/`leases.py` (Python + psycopg) **around** the subprocess — the boundary is
  unchanged.
- **`bin/di-fleet` re-deploy is an operator step** — the build edits the file in-repo only.
- **The heartbeat writer is untouched in v1.** `capacity` is *immutable* (Principle 1):
  set once by the migration backfill / the `ADD COLUMN` default for new nodes, never
  mutated per tick. So the heartbeat keeps writing `free_slots` harmlessly and is not
  modified. Plumbing `capacity` from `fleet_nodes` into the heartbeat is part of the
  capacity>1 evolution, not v1.
- **`epoch` is not overloaded** for lease fencing (RFC Principle 2 / RFC-0003). Lease
  identity is `lease_id`; `epoch` stays for topology/model-change.

---

## 6. Open questions — answered with the choice the build adopts

1. **Soft-reservation in v1 or deferred?** → **Deferred behind a flag.** v1 ships only the
   stable-jitter `ORDER BY` tie-breaker (Slice B). Why: the current 1–2-consumer fleet's
   herd is mild (RFC's own recommendation); the soft-reservation adds a `reserved_until`/
   `reserved_by` write + scan semantics worth gating until contention is *observed*.
2. **`capacity > 1` slots?** → **Out of scope.** v1 is capacity-1 columns on `gpu_slots`
   (no slot in the fleet advertises >1). The `slot_leases(slot_pk, lease_id, holder,
   renew_ts, ttl_ms, released)` table with `count(active) < capacity` is the documented
   evolution. Why: building the multi-lease table now is speculative generality (YAGNI)
   for a fleet where every slot is capacity-1.
3. **Where does `model_mib` (the claim's `vram_free_mib >= $model_mib`) come from?** →
   **v1 reuses the picker's existing `min_vram` value, supplied by the consumer**, and
   defaults to `0` when none is given. Why: di_fleet already knows the model it dispatches
   and `pick_slot.pick` already takes `min_vram`; passing the same value into `claim`
   keeps pick and claim consistent with **no new `gpu_slots` column**. `fleet_nodes.
   min_load_vram_mib` (from #2/005) is the right per-slot knob only once we need per-slot
   model footprints for capacity>1 — not needed in v1.

---

## 7. Load-bearing claims (falsifiable — attack these)

**C1 — Migration 006 is backward-compatible and reversible.**
*Supports:* 006 is purely additive (ADD COLUMN + backfill + new index; no RENAME, no DROP);
the running heartbeat's UPSERT and the old `pick_slot` reference only columns that still
exist; new lease columns default NULL ⇒ every slot reads free ⇒ today's behavior. Provable
by applying 006 to an ephemeral DB seeded with the *current* schema and running the
*unmodified* heartbeat + pick against it (both succeed; `live_slots` unchanged), then
dropping the four columns to restore the exact prior schema.
*Refutes:* the running heartbeat or old `pick_slot` errors after 006 applies; or `006`
renames/drops any column in use; or `pytest` regresses.

**C2 — Exclusivity comes from the conditional CLAIM, not the row lock.**
*Supports:* `test_two_concurrent_claims_exactly_one_wins` — concurrent real CLAIMs, exactly
one `RETURNING` a row, with `FOR UPDATE SKIP LOCKED` absent from the CLAIM path.
*Refutes:* both concurrent CLAIMs return a row (double-hold), or exclusivity is observed to
depend on holding a transaction open (the demoted-row-lock failure mode).

**C3 — Deadman + zombie safety with no reaper.**
*Supports:* `test_unrenewed_lease_self_expires` (frees ≤ TTL, only test connections alive)
and `test_zombie_renew_after_reclaim_is_fenced` (stale `lease_id` renew → 0 rows). No
reaper process or detector exists anywhere (inspection).
*Refutes:* a slot stays held past TTL with no renewer; a zombie renew returns a row; or a
background reaper is found to be required.

**C4 — K-fan-out holds N distinct leases; failover transfer is atomic and leak-free.**
*Supports:* hermetic `test_kfanout_claims_n_distinct_leases` /
`test_failover_transfer_releases_dead_and_claims_survivor`; DB-level
`test_failover_transfer_is_atomic` (mid-transfer failure rolls back both ops).
*Refutes:* two shards share a `lease_id`; a transfer commits the claim but not the release
(double-hold) or the release but not the claim (leak); or a dead shard outlives its frames.

**C5 — No consumer wall-clock is read in claim/renew/release.**
*Supports:* `test_lease_no_consumer_clock.py` — every expiry/fence predicate uses Postgres
`now()`; no `time.*`/`datetime.*` feeds a lease decision.
*Refutes:* any claim/renew/release/transfer path computes expiry or fencing from a Python
clock.

**C6 — The hermetic default stays green and DB-free.**
*Supports:* `python3 -m pytest tests/ -q` runs the 26 existing + the new hermetic tests
green with **no DB present**; the DB-backed tests skip cleanly (importorskip + env guard).
*Refutes:* any test requires a live DB/HTTP/subprocess to pass under the default invocation,
or the existing 26 change behavior.

**C7 — Renewal does not introduce a correctness-path background process.**
*Supports:* a single bounded daemon renewer (one thread + one connection), started/stopped
around `dispatch`, renews active leases every `RENEW_SECONDS`; it is off the correctness
path — if it dies, leases expire and shards self-abort on the next failed renew (identical
to the deadman path). Hermetically testable via injected `lease_ops` + a short real
interval (a slow fake `shard_fn` ⇒ assert renew called ≥N times, release once).
*Refutes:* a held lease can be lost while the shard is healthy because renewal stalls
(forcing the per-shard `Popen`+poll-in-worker alternative); or the renewer is shown to be
on the correctness path (its failure corrupts state rather than degrading to deadman); or
it leaks threads/connections across runs.

> **Note on C1/C7 vs. the RFC's literal wording.** The RFC's rollout step 1 says "rename
> `free_slots`→`capacity`" and its renew aside says "zero extra connections/threads." This
> plan keeps the RFC's *intent* (capacity immutable & derived; one renewal mechanism off the
> reaper/correctness path) while refining the *mechanism* (expand/contract instead of an
> in-place rename; one bounded renewer instead of zero) precisely because the task's
> backward-compat requirement and di_fleet's blocking-subprocess shard structure make the
> literal versions unsafe/unimplementable as written. Both refinements are stated as
> falsifiable claims above so the gate — not this author — decides.

---

## 8. Definition of done (for the downstream build run)

- `migrations/006_exclusive_slot_leases.sql` exists, additive, reversible (§2).
- `pick_slot.py`, `leases.py`, `di_fleet.py` implement claim/renew/release/transfer with
  injectable seams; `bin/di-fleet` unchanged in behavior.
- Every §3 gate row has its named test; `python3 -m pytest tests/ -q` is green and hermetic
  (≥ 26 + new hermetic tests); DB-backed tests skip without `GPU_FLEET_TEST_DB`.
- No live infra touched (§4). Operator applies 006 + re-deploys (§2) post-integration.
