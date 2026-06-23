# BUILD_PLAN — RFC 0003: Stale-router epoch fencing

author: holder-claude-opus-4.8-003

Translates the settled design in `docs/rfc/0003-stale-router-epoch-fencing.md` into
an ordered, falsifiable build plan. The RFC is settled; this plan does **not**
re-open its design, only realizes it against the live code (`di_fleet.py`,
`pick_slot.py`, `heartbeat.py`, `heartbeat_all.py`, `migrations/`, `tests/`) as it
stands after the RFC-0001 lease build landed (migration 007 applied; the lease
lifecycle is inlined in `di_fleet.py`, not a separate `leases.py`).

## The one fact that drives the whole build

`epoch BIGINT NOT NULL DEFAULT 0` already exists (`migrations/001_gpu_slots.sql:36`)
but is **dormant**: the heartbeat UPSERT currently writes `epoch = EXCLUDED.epoch`
(`heartbeat.py:45`), i.e. it overwrites the DB epoch with the *static* config value
(`args.epoch` / `fleet_nodes.epoch`, default 0) on **every tick**. So today epoch is
a constant, never a change-counter. Turning the RFC on is therefore two coupled
moves:

1. **Writer:** make the UPSERT *preserve* the existing epoch and *bump it by 1 only
   when a routing-relevant field changed* (instead of clobbering it with the config
   constant).
2. **Consumer:** stamp the slot's epoch onto the lease at claim time
   (`lease_epoch`), and add `epoch = lease_epoch` to the lease-renew predicate.

Because `lease_epoch` is stamped **server-side as a column** (`lease_epoch = epoch`
in the CLAIM `SET`), the renew fence is a pure **two-column SQL predicate**
(`epoch = lease_epoch`) — the Python `claim()` / `renew()` / `release()` signatures
do **not** change. This is the RFC's own statement ("the claim stamps `lease_epoch`
… onto the lease") taken to its literal conclusion; it is strictly simpler than the
RFC's illustrative `AND epoch = $lease_epoch` sketch (no parameter, no consumer
state) and is within the settled design, not a deviation.

The inference server never learns the epoch — staleness is caught entirely at the
registry-side renew. **No backend changes, no new protocol** (RFC §Design).

---

## 1. Scope & slices (ordered, independently committable)

Deploy/commit order mirrors the RFC's **DB → readers → writers**. Each slice is
green on its own; later slices are no-ops until both writer slices land.

### Slice 0 — DB: migration `008` (additive `lease_epoch`)
- **Files:** `migrations/008_lease_epoch.sql` (new).
- **Change:** `ALTER TABLE gpu_slots ADD COLUMN IF NOT EXISTS lease_epoch BIGINT;`
  (nullable, **no** default). The `epoch` column already exists — untouched.
- **Blast radius:** one new nullable column. Renames/drops nothing. Reversible with
  `DROP COLUMN IF EXISTS lease_epoch`.
- **Backward compatible:** the running heartbeat UPSERT never names `lease_epoch`, so
  it is unaffected the instant the DDL commits; a NULL `lease_epoch` (every existing
  row, and any lease claimed by pre-Slice-3 code) means **fencing disabled for that
  lease** (see Slice 3's NULL-guard), so adding the column changes no behavior until
  a consumer stamps it. Migration is safe with `gpu-fleet-heartbeat` running;
  stop→migrate→start is optional and equally safe.

### Slice 1 — Reader: `pick_slot` surfaces `epoch`
- **Files:** `pick_slot.py`, `tests/test_pick_slot.py`.
- **Change:** add `epoch` to the `PICK` `SELECT` and to `COLS`
  (`pick_slot.py:27,44`). Output dict gains an `epoch` key.
- **Blast radius:** one extra output key. `di_fleet.route_slots` reads picks via
  `.get(...)`, so an added key is harmless; un-upgraded readers ignore it.
- **Why a reader slice at all:** the lease fence does **not** need this (it is
  server-side, Slice 3). Surfacing `epoch` serves (a) the RFC's optional degenerate
  no-lease pre-flight `SELECT epoch …` path and (b) observability. It deploys first
  (readers-before-writers) so nothing downstream can KeyError on the new shape.

### Slice 2 — Writer: heartbeat bumps `epoch` on routing-relevant change
- **Files:** `heartbeat.py` (the shared `UPSERT` constant, `heartbeat.py:30-47`),
  `tests/test_heartbeat_epoch.py` (new), and the DB-gate test (Slice 3 test file).
- **Change:** replace `epoch=EXCLUDED.epoch` in the `ON CONFLICT … DO UPDATE SET`
  with a preserve-and-conditional-bump expression:

  ```sql
  epoch = gpu_slots.epoch + CASE
      WHEN gpu_slots.served_model  IS DISTINCT FROM EXCLUDED.served_model
        OR gpu_slots.nvlink_domain IS DISTINCT FROM EXCLUDED.nvlink_domain
        OR gpu_slots.max_context   IS DISTINCT FROM EXCLUDED.max_context
      THEN 1 ELSE 0 END,
  ```

  The `VALUES (… %(epoch)s …)` INSERT path is unchanged: a brand-new row still seeds
  `epoch` from config (default 0). Only the conflict path changes.
- **`heartbeat_all.py` is covered transitively:** it `from heartbeat import UPSERT`
  (`heartbeat_all.py:22-28`) — both the single-node and driver writers use the one
  constant, so this is a single edit.
- **Diff set = `{served_model, nvlink_domain, max_context}`** (`IS DISTINCT FROM`
  is NULL-safe). `vram_free_mib` / `gpu_util_pct` are deliberately **excluded** → no
  re-pick storms on expected churn. `endpoint_url` is excluded because it is part of
  the PK `(node, endpoint_url, slot_id)`: an endpoint change is structurally a new
  row (a fresh INSERT seeding epoch), never an in-place conflict — see Open Q1.
- **Blast radius:** one SQL constant. **Backward compatible:** until a routing field
  actually changes, the bump is `+0` ⇒ epoch stays constant ⇒ identical to today;
  and even a real bump affects no consumer until Slice 3 stamps `lease_epoch`.
- **Lease columns are preserved:** the UPSERT `SET` never lists
  `lease_id/lease_holder/lease_expires/lease_epoch`, so a heartbeat tick over a held
  slot leaves the lease (and its stamped `lease_epoch`) intact — only `epoch` moves.

### Slice 3 — Writer: consumer fences the lease on epoch
- **Files:** `di_fleet.py` (two SQL constants), `tests/lease_fakes.py`,
  `tests/test_leases.py`, `tests/test_epoch_pg.py` (new, guarded).
- **Change A — stamp at claim** (`di_fleet.py` `LEASE_CLAIM_SQL`, ~`:93`): add
  `lease_epoch = epoch` to the `SET` (RHS reads the row's current epoch atomically in
  the same conditional UPDATE).
- **Change B — fence at renew** (`di_fleet.py` `LEASE_RENEW_SQL`, ~`:109`): add one
  predicate:

  ```sql
  UPDATE gpu_slots SET lease_expires = now() + make_interval(secs => %(ttl)s)
   WHERE lease_id = %(lease_id)s
     AND now() < lease_expires
     AND (lease_epoch IS NULL OR epoch = lease_epoch)   -- config changed => 0 rows
  RETURNING lease_id
  ```

  Zero rows now means "lease lost **or** the slot's capability changed underneath me."
  The consumer's existing `renew()==False ⇒ abort the child + drop the slot + re-pick`
  path (`di_fleet.py` `_monitor` BC1-A, `:408-414`) already handles it unchanged — it
  simply gains a second cause. `claim()/renew()/release()` signatures are untouched.
- **`RELEASE` unchanged:** `lease_epoch` is cleared implicitly when the row is
  re-claimed (CLAIM overwrites it) or can be left as-is on release (it is only read
  while a lease is held). For tidiness the build adds `lease_epoch = NULL` to
  `LEASE_RELEASE_SQL`'s `SET`; this is cosmetic, not load-bearing.
- **NULL-guard rationale:** after Slice 3 deploys, every new claim stamps
  `lease_epoch = epoch` (non-NULL, since `epoch` is `NOT NULL DEFAULT 0`). A NULL
  `lease_epoch` therefore only exists for a lease claimed by pre-Slice-3 code that is
  still alive at the deploy instant — bounded by one TTL (45s). The guard keeps such
  in-flight leases un-fenced (no false re-pick), which is the standard expand/contract
  safety; it never weakens fencing for any lease claimed by the deployed code.
- **Blast radius:** two SQL constants in `di_fleet.py` + their hermetic/PG tests.

**Slice independence & ordering.** Slices 1 and 2 do not depend on migration 008
(the `epoch` column predates it). Slice 3 references `lease_epoch`, so 008 must be
**applied** before Slice 3 is *deployed* (the tests apply it themselves). Commit
order = deploy order = `008 → pick_slot → heartbeat → di_fleet`. The two writer
slices are safe in **either** deploy order (Open claim C5).

---

## 2. Migration plan

- **Number: `008`** — `migrations/` holds `001`–`007`; `008` is the lowest unused
  **file** number (per the task's "take the lowest unused 0NN"). Note:
  `007_exclusive_slot_leases.sql`'s trailing prose references a *"future contract
  migration 008"* that would drop `free_slots`. That contract migration is **not
  built** and its number is not reserved by prose — migration numbers are assigned by
  build order. RFC-0003 takes `008` for `lease_epoch`; the eventual `free_slots`
  contract migration takes the next free number (`009`) when it is authored. The
  `008` header will state this explicitly. The build does **not** edit the
  already-applied, immutable `007`.

- **Exact schema change (`008_lease_epoch.sql`):**
  ```sql
  -- RFC 0003 — stale-router epoch fencing. Purely additive: one nullable column.
  -- The `epoch` column (001) already exists and is reused as the change-counter;
  -- this only records, per held lease, the epoch the holder routed against.
  ALTER TABLE gpu_slots ADD COLUMN IF NOT EXISTS lease_epoch BIGINT;  -- NULL = fence off
  -- Reverse: ALTER TABLE gpu_slots DROP COLUMN IF EXISTS lease_epoch;
  ```
  No index needed (read only via the existing `lease_id`-keyed renew). No `epoch`
  DDL (it exists). No backfill (NULL is the correct "fence-off" default).

- **Apply order (operator, after integration): DB → readers → writers.**
  1. **DB:** apply `008` (additive ⇒ safe even with `gpu-fleet-heartbeat` running).
  2. **Readers:** deploy `pick_slot.py` (Slice 1) — surfaces `epoch`, no behavior
     change.
  3. **Writers:** deploy `heartbeat.py` (Slice 2) and `di_fleet.py` (Slice 3) in
     either order. Until both land, behavior equals today.

- **Backward compatibility invariant:** until consumers stamp/read `lease_epoch`,
  fleet behavior equals today's — a NULL `lease_epoch` disables fencing, and the bump
  is `+0` whenever no routing field changes.

---

## 3. Test plan — mapped to the RFC's Falsifiable gate

Default `python3 -m pytest tests/ -q` (26 tests today) MUST stay green and hermetic.
Hermetic tests inject the existing `FakeSlotDB` / `RecordingConn` fakes (mirroring
`tests/test_leases.py`, `tests/test_pick_slot.py`, `tests/test_probe_all.py`). Any
DB-backed test is **guarded exactly like `tests/test_leases_pg.py`**: it
`pytest.importorskip("psycopg")` and skips unless `GPU_FLEET_TEST_DB` names an
**ephemeral** throwaway cluster (it refuses bare `gpu_fleet`). The new PG tests apply
the real `migrations/001,007,008` to that ephemeral DB so they also prove the
migrations apply cleanly.

| RFC gate bullet | Test(s) | Kind |
|---|---|---|
| **(1)** Bumping `served_model` makes a holder's next renew return **zero rows** (forced re-pick), proven by mutating the row mid-lease | **A.** `test_leases.py::test_epoch_change_fences_renew` — extend `FakeSlotDB` to carry `epoch`/`lease_epoch`; `claim` stamps `lease_epoch=epoch`; bump `db.row_for(slot)["epoch"] += 1`; assert `leases.renew(...) is False`, and (reusing the existing monitor harness) that `_monitor` aborts the child + raises `LeaseLost`. **B.** `test_epoch_pg.py::test_served_model_bump_fences_renew` — real DB: INSERT slot, `claim`, drive the real `heartbeat.UPSERT` with a changed `served_model`, assert `epoch` advanced and `leases.renew` returns `False`. | A: **hermetic** (default suite). B: **PG-guarded**. |
| **(2)** A VRAM/util-only change does **not** bump epoch and does **not** invalidate a lease | **C.** `test_epoch_pg.py::test_vram_util_only_change_keeps_epoch_and_lease` — `claim`, run real `heartbeat.UPSERT` changing only `vram_free_mib`/`gpu_util_pct`; assert `epoch` unchanged **and** `leases.renew` returns `True`. **D.** `test_heartbeat_epoch.py::test_bump_diff_excludes_churn_fields` — assert the `UPSERT` SQL's epoch `CASE` references `served_model/nvlink_domain/max_context` and **not** `vram_free_mib/gpu_util_pct` (string-shape assert, à la `test_pick_slot`'s SQL asserts). | C: **PG-guarded**. D: **hermetic** (default suite). |
| **(3)** A re-pick after an epoch bump lands on the slot's **new** capability, never the stale one | **E.** `test_pick_slot.py::test_pick_surfaces_current_epoch_and_model` — `RecordingConn` returns a row with bumped `epoch` + new `served_model`; assert `pick()` output carries the new `epoch` and `served_model`. **F.** `test_epoch_pg.py::test_repick_after_bump_stamps_new_epoch` — after a bump, a fresh `claim` stamps `lease_epoch` = the **new** epoch and its renew succeeds against the new capability. | E: **hermetic** (default suite). F: **PG-guarded**. |

**Hermetic-default guarantee.** New default-suite tests (A, D, E) add to the 26 and
need no DB. Extending `FakeSlotDB`/`LEASE_*_SQL` keeps the existing lease tests green
because all existing fakes/claims have `epoch == lease_epoch == 0`, so
`epoch = lease_epoch` evaluates `True` ⇒ today's renew behavior (Open claim C6). The
PG tests (B, C, F) skip cleanly when `GPU_FLEET_TEST_DB` is unset.

---

## 4. Live-infra safety

The build is **inert** with respect to live infra. It only:
- writes `migrations/008_lease_epoch.sql`;
- edits `pick_slot.py`, `heartbeat.py`, `di_fleet.py`, and `tests/*`;
- runs the **hermetic** `python3 -m pytest tests/ -q`.

It MUST NOT, and does not need to:
- connect to / migrate the **live `gpu_fleet`** Postgres (the PG tests refuse a
  non-ephemeral DB and skip by default; only an operator-provided `GPU_FLEET_TEST_DB`
  throwaway cluster runs them);
- restart or touch the running **`gpu-fleet-heartbeat`** service;
- touch **peecee**'s shared GPU (no probe, no decode, no `nvidia-smi`).

The operator, **after** integration, applies `008` (stop heartbeat → migrate →
start) and redeploys the consumer checkout. Migration `008` is additive, so even an
unstopped heartbeat is safe.

---

## 5. Boundaries to preserve

- **`di` stays a subprocess (RFC 0078/0087).** Epoch fencing is 100% registry-side
  SQL; the lease monitor still aborts only by acting on the `Popen` handle
  (`terminate()/kill()`), never importing the Node engine
  (`~/git/divergent-ideation`). No code in this build crosses that boundary.
- **`bin/di-fleet` is a thin `exec python3 di_fleet.py` bash wrapper** — it holds no
  logic and is **not edited**. "Redeploying `bin/di-fleet`" is the operator step of
  updating the gpu-fleet checkout on consumer hosts so the new `di_fleet.py`/
  `pick_slot.py` take effect.
- **The table + the query stay the router.** No central daemon, no new service, no
  backend-side epoch awareness (RFC §Design).

---

## 6. Open questions — the build's answers

- **Q1 — exact "routing-relevant" set.** Adopt **`{served_model, nvlink_domain,
  max_context}`** for the in-place ON-CONFLICT diff. `served_model` is mandated by
  gate (1); `nvlink_domain` is the RFC-0004 forward-compat case (a re-formed NVLink
  domain must fence stale TP routing — RFC failure table); `max_context` per Q2.
  **`endpoint_url` is intentionally *not* in the in-place diff** even though the RFC
  lists it: it is part of the PK `(node, endpoint_url, slot_id)`, so an endpoint
  change is a *different row* (fresh INSERT, epoch re-seeded), and the old row stops
  being heartbeated — a holder's lease on it renews until expiry, then re-picks. That
  staleness is caught by the key + liveness, not by an in-place bump, so listing it
  in the diff would be dead code. Start minimal; widen only if a real staleness bug
  appears (RFC's own guidance).
- **Q2 — `max_context` shrink: hard-fence or warn?** **Hard-fence** (include
  `max_context` in the diff set). A big-context job stranded on a shrunk slot would
  otherwise issue an over-length request that the backend rejects mid-run; forcing a
  re-pick to a slot that still advertises the needed context is strictly safer than a
  silent mid-run failure. The cost is a rare extra re-pick when context changes —
  bounded and acceptable. If operators later find it too aggressive, dropping
  `max_context` from the `CASE` is a one-line revert (recorded as the cheap reversal).

---

## 7. Load-bearing claims (falsifiers, attack these)

- **C1 — Migration 008 is additive, reversible, and behavior-neutral.**
  *Support:* `ADD COLUMN IF NOT EXISTS lease_epoch BIGINT` with no default/NOT-NULL;
  the heartbeat UPSERT never names it; `pytest tests/ -q` stays green before any
  consumer reads it. *Refuted by:* it alters/drops an existing column, breaks the
  running UPSERT, or a NULL `lease_epoch` causes a live lease's renew to fail.
- **C2 — The fence is a pure two-column server-side predicate; no consumer Python
  signature changes.** *Support:* CLAIM adds `lease_epoch = epoch`; RENEW adds
  `AND (lease_epoch IS NULL OR epoch = lease_epoch)`; `claim/renew/release`
  signatures are byte-identical; `FakeSlotDB` drives the real constants. *Refuted by:*
  any path must thread `epoch` through Python, or `pick_slot`'s `epoch` output is
  required for the fence to trip.
- **C3 — One UPSERT edit covers both writers.** *Support:* `heartbeat_all` imports
  `UPSERT` from `heartbeat`. *Refuted by:* a writer path emits its own UPSERT or
  bypasses the constant.
- **C4 — Epoch bumps iff a routing-relevant field changed; VRAM/util churn never
  bumps.** *Support:* the `CASE` references only `served_model/nvlink_domain/
  max_context` via `IS DISTINCT FROM`. *Refuted by:* PG test C shows a vram/util-only
  tick advancing epoch, or a `served_model` change failing to bump.
- **C5 — The two writer slices are safe to deploy in either order.** *Support:*
  heartbeat-first ⇒ leases carry NULL `lease_epoch` ⇒ NULL-guard ⇒ no false fence;
  consumer-first ⇒ epoch never moves ⇒ fence is a no-op. *Refuted by:* either order
  yields a spurious re-pick or a missed fence once both are deployed.
- **C6 — The 26 existing hermetic tests stay green with no DB.** *Support:*
  `pick_slot` gains an additive output key; the new lease predicate evaluates `True`
  for all existing `epoch==lease_epoch==0` fakes; new DB tests are
  `GPU_FLEET_TEST_DB`-guarded. *Refuted by:* `pytest tests/ -q` drops below 26 passing
  or demands a DB.
- **C7 — `008` is the correct migration number and reuses nothing.** *Support:*
  `migrations/` holds `001`–`007`; `008` is the lowest unused file; `007`'s prose
  reference to a future-008 contract migration is illustrative and unbuilt.
  *Refuted by:* an `008` file already exists, or this campaign builds the `free_slots`
  contract migration under `008` elsewhere.
- **C8 — Held leases survive heartbeat ticks; only `epoch` moves.** *Support:* the
  UPSERT `SET` never lists the lease columns, so `lease_id/expires/lease_epoch` are
  preserved across a tick. *Refuted by:* a benign tick clears or rewrites a lease
  column.
