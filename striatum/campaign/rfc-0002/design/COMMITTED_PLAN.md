---
schema_version: "striatum.synthesis.v1"
artifact_kind: "synthesis"
---

# COMMITTED_PLAN — RFC 0002: Zero-touch node lifecycle

author: committer-claude-opus-4.8-001

This is the **gated, committed build plan** for RFC 0002. It is the holder's cycle-3
build plan (`dialogue/holder/BUILD_PLAN.md`, `holder-claude-opus-4.8-003`) **amended with
every binding constraint** the adjudicator recorded — the exact contract the build run
will execute. It is self-contained: the ordered committable slices and their blast
radius, the migration `009` schema + apply order, the falsifiable-gate → test map with
each binding constraint folded in, the live-infra and `di --json` boundaries, and the
operator deployment steps.

## Gate clearance (the clearing ledger this plan commits to)

- **Clearing ledger:** `dialogue/adjudicator/COLLABORATION_LEDGER_cycle_3.md`
  (`adjudicator-claude-opus-4.8-003`, artifact `art_ef8ee7f10e606252c52dfbb3d29ed1f8`),
  run `run_aa1f69f24463027c2466994e9f655b08`, workflow `rfc-0002-design`, cycle 3.
- **Verdict:** `accept_with_findings` — a **clearing** verdict, so the commit phase may
  publish. The cycle-3 re-falsification of the holder's cycle-3 revised plan found the
  seven cycle-2 constraints **discharged and confirmed** (falsifier_2 records "No
  Remaining Falsifying Gaps"; falsifier_1 drops all seven), so the cycle-2 terminal-`reject`
  trigger (a blocker among BC1/BC2/BC6/BC7 still landing) **did not fire**. One **new**
  objection landed (BC8, the peecee pull-only liveness vs the SSH-`nvidia-smi`-retirement
  step) — non-blocking for the gate, carried forward as a binding build/verify constraint.
- **Settled, do-not-reopen design** (from the RFC + the ledger spine): pull-first
  peer-runnable driver; push opt-in for trusted Linux nodes only; registration = first
  heartbeat; measured-not-declared quarantine→graduate; `boot_epoch` ⟂ `epoch`.

## Binding constraints folded in (the build's verify gate)

Every constraint below is preserved exactly as the adjudicator recorded it; none is
weakened or dropped. **BC1, BC2, BC6, BC7** are discharged *in design* and carry forward
as REQUIRED, must-stay-green verify tests (`binding: true`, `final_review_required: true`).
**BC3, BC4, BC5** are discharged and carry forward as verify tests (`binding: false`
policy). **BC8** is the new, open constraint; this committed plan **discharges its
plan-text half now** (option (a) below — the false claim and the de-listing operator step
are removed from this document) and carries its verification test into the build's final
review (`final_review_required: true`).

| BC | Sev | Discharge status | The contract the build MUST satisfy | Proving test(s) | Final review |
|----|-----|------------------|-------------------------------------|-----------------|--------------|
| **BC1** | high | design-discharged → verify-carry | Per-node driver-lease CAS is **non-gating**; the `gpu_slots` UPSERT runs **unconditionally** (arbitration model c). A self-push node ABSENT from `fleet_nodes` registers `unverified` and graduates to `routable` after N probes, **with C9 preserved**. | `test_lifecycle_pg.py::test_self_push_no_fleet_node_registers_and_graduates` (composed Slice-1+3) | **required** |
| **BC2** | high | design-discharged → verify-carry | `boot_epoch = COALESCE(EXCLUDED.boot_epoch, gpu_slots.boot_epoch)` — a NULL (pull) write never erases a push-stamped ratchet; a strictly-stale write stays refused after any number of pull ticks. | `test_lifecycle_pg.py::test_boot_epoch_survives_null_pull_write` | **required** |
| **BC6** | high | design-discharged → verify-carry | `boot_epoch` is **strictly monotonic per write**; the ratchet `WHERE` is a **strict `EXCLUDED.boot_epoch > gpu_slots.boot_epoch`** (NOT `>=`); an equal-epoch replay is a no-op (no mutable field moves, `heartbeat_ts` not re-stamped). **MUST NOT reintroduce `>=`.** | `test_lifecycle_pg.py::test_equal_epoch_replay_is_noop` + `test_graduation.py::test_ratchet_predicate_is_strict_gt` | **required** |
| **BC7** | high | design-discharged → verify-carry | `probe_streak` resets to 1 (if alive) and `status → 'unverified'` when `gpu_slots.gpu_uuid` and `EXCLUDED.gpu_uuid` are **both non-NULL and differ**; trust carries forward only on a matching/unknown uuid. A hot-swapped alive card cannot inherit the prior streak. | `test_graduation.py::test_uuid_mismatch_resets_streak_and_demotes` (hermetic) + `test_lifecycle_pg.py::test_hot_swap_demotes_to_unverified` (PG) | **required** |
| **BC3** | medium | design-discharged → verify-carry | `PULLER_LEASE_TTL = 15 s`, pinned **strictly `< 45 s`** (the `live_slots`/`routable_slots` staleness window). A killed-holder failover keeps every live node in the directory. | `test_lifecycle_pg.py::test_puller_failover_no_ageout` | not required |
| **BC4** | medium | design-discharged → verify-carry | Per-node driver-lease freshness is evaluated **server-side** in the `FETCH` (`WHERE enabled AND (driven_by IS NULL OR now() >= lease_until)`); no puller-host clock enters the skip decision. | `test_driver_lease.py::test_fetch_freshness_uses_db_now_no_client_clock` | not required |
| **BC5** | low | design-discharged → verify-carry | The `fleet_meta` column is **`holder`** verbatim in the `009` DDL, the Slice-2 CAS, and tests A/B/G/H, which run the real SQL against the real `009` DDL so a divergence fails the suite. | tests A/B/G/H | not required |
| **BC8** | medium | **open → plan-text discharged here (option a); test carried to verify** | The build MUST resolve the peecee pull-only liveness contradiction by **exactly ONE coherent path** and MUST NOT ship the false claim/instruction. **COMMITTED CHOICE: option (a)** — do **not** retire peecee's cross-host SSH `nvidia-smi` `gpu_cmd` in v1; keep peecee on its existing, working SSH-via-pull liveness; the §2-step-2 SSH-retirement step is **deleted** and §4/§5/Q5 are **corrected** in this document (peecee is pull-only as to running no fleet code/creds on the node, but its load-aware liveness still consumes an `nvidia-smi` VRAM reading driven by the puller). Verify: peecee is still monitored via pull and de-lists when marker owns the card; no false "HTTP-only liveness" claim and no de-listing SSH-retirement step ship. | `test_load_aware_liveness.py` + `test_pull_only_node_has_no_db_path` (test K); committed-plan text inspection (no false claim / no de-listing step) | **required** |

### BC8 — full constraint text (preserved verbatim; do not weaken or drop)

> **BC8 (binding; carried into the build/verify gate; does NOT block the design gate from
> clearing because the in-build SQL is inert wrt peecee and the plan's "not load-bearing
> for any C-claim" hedge holds).** The build MUST resolve the peecee pull-only liveness
> contradiction by exactly ONE coherent path and MUST NOT ship the current false
> claim/instruction:
> **(a)** DO NOT retire peecee's cross-host SSH `nvidia-smi` `gpu_cmd` in v1 — keep peecee
> on its existing, working SSH-via-pull liveness — DELETE the §2-step-2 SSH-retirement
> apply step, and correct §5 / Q5 so the "zero-SSH pull-only" framing is narrowed (peecee
> is pull-only as to running no fleet code/creds on the node, but its load-aware liveness
> still consumes an `nvidia-smi` VRAM reading driven by the puller); **OR**
> **(b)** implement AND test a real HTTP-only peecee liveness path — `probe_node` must skip
> `gpu_stats` for an `ollama-ondemand` node and derive resident/loadable state from the
> endpoint, recording the lower-trust endpoint-asserted VRAM per Pillar 6 / Q5 — proven by
> the discharging test `falsifier_1` specifies: a peecee slot-0 row with
> `probe_model='ollama-ondemand'` and NO SSH/`nvidia-smi` `gpu_cmd`, endpoint stubbed
> serveable, asserts no SSH/`nvidia-smi` is invoked, `alive=True` when serveable with
> `boot_epoch` NULL and the row can graduate to `routable`, and `alive=False` (de-listed)
> when marker owns the card.
> Neither path reopens BC2/BC6 — the `boot_epoch` ratchet is correct independent of the SSH
> step.
>
> **Committed resolution for v1: option (a).** Rationale: (a) keeps the build's §4
> live-infra inertness intact (no new `probe_node`/`gpu_stats`/`ollama_ondemand_liveness`
> code), keeps peecee monitored exactly as today, and removes the false narrative + the
> harmful operator step from the contract. Option (b) — the full HTTP-only peecee liveness
> path that finally retires the cross-host SSH fan-out — is a **documented, bounded
> follow-up** (see §5, §6 Q5), not v1 scope. The verification gate is unchanged: peecee
> stays monitored via pull and de-lists when marker owns the card (test K), and the
> committed plan ships no false "HTTP-only liveness" claim and no de-listing SSH-retirement
> step.

---

# BUILD PLAN (committed)

Translates the settled design in `docs/rfc/0002-zero-touch-node-lifecycle.md` into an
ordered, falsifiable build plan. The RFC is **settled** (prepared via `/adhd`, traps
recorded); this plan does **not** re-open its design or resurrect a rejected
alternative — it only realizes the design against the live code as it stands *after*
the RFC-0001 lease build (migration 007) and the RFC-0003 epoch build (migration 008)
landed: `di_fleet.py`, `pick_slot.py`, `heartbeat.py`, `heartbeat_all.py`,
`migrations/`, `tests/`.

## The three facts that drive the whole build

1. **"Registration = first heartbeat" is ALREADY half-true and the writer is the
   `gpu_slots` UPSERT.** `heartbeat.py`'s `INSERT … ON CONFLICT … DO UPDATE` (the shared
   `UPSERT` constant, `heartbeat.py:30-62`) *already* creates the `gpu_slots` row on
   first sight, and `heartbeat_all.py` imports that same constant
   (`heartbeat_all.py:22-28`). What is missing is (a) the **quarantine state** so a
   fresh row is not instantly routable, and (b) decoupling *who may appear in the
   directory* from the *pull driver's node list* (`fleet_nodes`) — today
   `heartbeat_all.tick()` probes only `fleet_nodes WHERE enabled` (`heartbeat_all.py:30-34`)
   and then **`PRUNE`s every `gpu_slots` row not in `fleet_nodes`** (`heartbeat_all.py:124-127`).
   That PRUNE would **delete a self-pushed node** that has no `fleet_nodes` row — the
   single most load-bearing correctness interaction in this build (Slice 1 fixes it).

2. **The directory already has a change-counter named `epoch`** (RFC-0003,
   `migrations/001` + `008`, bumped by the UPSERT CASE at `heartbeat.py:55-59`). The
   RFC's Pillar-5 **boot-epoch ratchet is a SEPARATE concern and MUST be a separate
   column** (`boot_epoch`) — the RFC says so explicitly ("keep them separate columns").
   `epoch` = "routing-relevant capability changed"; `boot_epoch` = "monotonic
   write-ordering token; refuse anything ≤ recorded." This build never touches the
   `epoch` CASE (C7).

3. **`heartbeat_ts` is already DB-stamped** (`DEFAULT now()` in `migrations/001`; the
   UPSERT writes `heartbeat_ts=now()` on both the INSERT and the conflict path,
   `heartbeat.py:38,61`). Gate bullet "no node wall-clock" is a **preserve-and-prove**
   invariant for liveness, not new code — and this revision **extends** that discipline
   to the two *new* timing decisions (the per-node driver-lease freshness, BC4, and the
   replay ratchet, BC6/BC2), so every routing/liveness decision stays on the DB clock.

These three facts make the build *additive and incremental*: every slice is green on
its own and **fleet behavior equals today's until the final consumer slice flips
routing onto `status='routable'`**.

---

## 1. Scope & slices (ordered, independently committable)

Commit/deploy order mirrors the RFC's migration section: **DB → heartbeat (writer) →
puller-lease → consumers (reader/claim)**. Note this is **writer-before-reader**, the
*opposite* of RFC-0003's reader-first order, and deliberately so: RFC-0003's reader only
*surfaced* `epoch` (no filter), so it was safe first; here the consumer slice *filters*
on `status='routable'`, so the writer that populates `status` MUST lead it or live nodes
would be stranded out of routing. This ordering is a load-bearing claim (C5).

### Slice 0 — DB: migration `009` (additive columns + new table + new view)
- **Files:** `migrations/009_zero_touch_lifecycle.sql` (new).
- **Change (exact SQL in §2).** On `gpu_slots`: add `status` (CHECK in
  `unverified/probationary/routable/demoted`, default `unverified`), `probe_streak INT
  DEFAULT 0`, `gpu_uuid TEXT`, `boot_epoch BIGINT`. On `fleet_nodes`: add `driven_by
  TEXT`, `lease_until TIMESTAMPTZ` (the per-node driver-lease). Create `fleet_meta`
  (single-row puller-lease holder, deadman TTL) — **column named `holder`** to match the
  Slice-2 CAS verbatim (BC5). **Backfill every existing `gpu_slots` row to
  `status='routable'`** so the migration instant strands nothing. Add `routable_slots`
  **as a new view ALONGSIDE** `live_slots` (expand, do not drop — `live_slots` retires in
  a later out-of-scope contract migration, exactly as 007 kept `free_slots`).
- **Blast radius:** four new nullable/defaulted columns on `gpu_slots`, two on
  `fleet_nodes`, one new table, one new view. Renames nothing; drops nothing.
- **Backward compatible:** the **unchanged** heartbeat UPSERT never named any new column
  *before* Slice 1, so the instant the DDL commits nothing breaks. New rows default to
  `status='unverified'`, but **no consumer reads `status` until Slice 4**, so during the
  rollout window consumers still resolve every live node and behavior equals today.
  `routable_slots` exists but is unread until Slice 4. Fully reversible (drop the
  view/table + six columns) before Slice 4 deploys.

### Slice 1 — Heartbeat (writer): quarantine→graduate, gpu_uuid, boot-epoch ratchet, PRUNE fix
- **Files:** `heartbeat.py` (the shared `UPSERT` constant + `heartbeat_once` row build +
  argparse/`--boot-epoch`-source + captured `gpu_uuid`), `heartbeat_all.py`
  (`FETCH`/`COLS` gain the new `fleet_nodes` columns + **server-side lease predicate**;
  `probe_node` leaves `boot_epoch` NULL; **`PRUNE` predicate fix**),
  `tests/test_graduation.py` (new, hermetic), `tests/test_lifecycle_pg.py` (new,
  PG-guarded).
- **The exact revised conflict path (this is the heart of BC2/BC6/BC7):**
  ```sql
  ON CONFLICT (node, endpoint_url, slot_id) DO UPDATE SET
      gpu_model=EXCLUDED.gpu_model, nvlink_domain=EXCLUDED.nvlink_domain,
      vram_total_mib=EXCLUDED.vram_total_mib, vram_free_mib=EXCLUDED.vram_free_mib,
      gpu_util_pct=EXCLUDED.gpu_util_pct, loaded_model=EXCLUDED.loaded_model,
      served_model=EXCLUDED.served_model, max_context=EXCLUDED.max_context,
      latency_class=EXCLUDED.latency_class, free_slots=EXCLUDED.free_slots,
      epoch = gpu_slots.epoch + CASE   -- RFC 0003, UNCHANGED (C7: never aliased to boot_epoch)
          WHEN gpu_slots.served_model  IS DISTINCT FROM EXCLUDED.served_model
            OR gpu_slots.nvlink_domain IS DISTINCT FROM EXCLUDED.nvlink_domain
            OR gpu_slots.max_context   IS DISTINCT FROM EXCLUDED.max_context
          THEN 1 ELSE 0 END,
      -- BC2: a NULL-epoch (pull) writer must NEVER erase a push-stamped ratchet.
      boot_epoch = COALESCE(EXCLUDED.boot_epoch, gpu_slots.boot_epoch),
      -- A NULL (pull) uuid report must NEVER erase a known measured identity.
      gpu_uuid   = COALESCE(EXCLUDED.gpu_uuid, gpu_slots.gpu_uuid),
      -- BC7: reset the streak on a failed probe OR a GPU IDENTITY CHANGE, so a
      -- hot-swapped alive card cannot inherit the prior streak.
      probe_streak = CASE
          WHEN NOT EXCLUDED.alive THEN 0
          WHEN gpu_slots.gpu_uuid IS NOT NULL AND EXCLUDED.gpu_uuid IS NOT NULL
               AND gpu_slots.gpu_uuid <> EXCLUDED.gpu_uuid THEN 1
          ELSE gpu_slots.probe_streak + 1 END,
      -- BC7 + C10: identity change re-quarantines to 'unverified'; trust carries
      -- forward only on a matching/unknown uuid; otherwise graduate at the streak N.
      status = CASE
          WHEN NOT EXCLUDED.alive THEN 'unverified'
          WHEN gpu_slots.gpu_uuid IS NOT NULL AND EXCLUDED.gpu_uuid IS NOT NULL
               AND gpu_slots.gpu_uuid <> EXCLUDED.gpu_uuid THEN 'unverified'
          WHEN gpu_slots.status = 'routable' THEN 'routable'
          WHEN gpu_slots.probe_streak + 1 >= {GRADUATION_STREAK} THEN 'routable'
          ELSE 'probationary' END,
      alive=EXCLUDED.alive, probe_ms=EXCLUDED.probe_ms,
      note=EXCLUDED.note, heartbeat_ts=now()
  WHERE EXCLUDED.boot_epoch IS NULL          -- pull write: no boot identity, admit + COALESCE-preserve
     OR gpu_slots.boot_epoch IS NULL          -- pull-only node never push-stamped: ratchet off
     OR EXCLUDED.boot_epoch > gpu_slots.boot_epoch;   -- BC6: STRICT '>' refuses equal-or-lower replays
  ```
  `{GRADUATION_STREAK}` is the module constant `GRADUATION_STREAK = 3` (Q1),
  interpolated once into the SQL constant at import (a trusted int literal, not user
  input), so the row-dict passed to `conn.execute` is unchanged.

- **Change A — `boot_epoch` is a STRICTLY-MONOTONIC-PER-WRITE token (the fix that makes
  `>` correct AND keeps liveness).** This is the substantive correction over attempt 2,
  which made `boot_epoch` a *per-boot constant* and was therefore forced to `>=` —
  opening the equal-epoch replay hole (BC6). The RFC's Pillar-5 token is `boot_id +
  seq`: **strictly increasing on every write.** The push writer realizes that as one
  scalar:
  ```python
  GRADUATION_STREAK = 3
  _last_epoch = 0
  def next_boot_epoch() -> int:
      # node wall-clock ns, guarded to never regress within a process, so two writes
      # always STRICTLY increase. Across a reboot the wall clock has advanced; across a
      # heartbeat-process restart within one boot the wall clock is global so it still
      # advances. This is the RFC's boot_id+seq collapsed to one strictly-increasing
      # scalar — which is exactly why the ratchet predicate is a STRICT '>'.
      global _last_epoch
      _last_epoch = max(_last_epoch + 1, time.time_ns())
      return _last_epoch
  ```
  Only the **push / `--node self`** path stamps `boot_epoch = next_boot_epoch()`; the
  **pull** driver (`heartbeat_all.probe_node`) leaves it **NULL** (an HTTP probe carries
  no boot identity, so the puller has nothing truthful to stamp). Because every real
  push tick carries a strictly-greater value, the strict-`>` predicate **admits** it
  (liveness refreshes `heartbeat_ts=now()`); a replay re-presents an OLD value → strictly
  less → **refused** (BC6). No equal-epoch write is ever both legitimate and refused.
  - **Why this does NOT violate C12 / "no node wall-clock."** C12 is about *liveness and
    routing-timing* decisions — those stay on the DB clock (`heartbeat_ts=now()`, the
    lease `now()` predicates). `boot_epoch` is a per-node **ordering** token whose ONLY
    effect is to refuse *that node's own* stale replays; it never decides liveness, never
    gates routing, and a writer can only write its own `(node, endpoint_url, slot_id)`
    row. The worst a skewed node clock can do is make a node briefly refuse *its own*
    next write (self-inflicted, transient, self-healing via the `max(_last+1, …)`
    guard); it can neither extend the node's DB-stamped liveness nor forge another
    node's row. A boot-ordering token is *inherently* node-sourced (a boot id is the
    node's, not the DB's) — using the node's own monotonic source for its own ordering
    is the RFC design, not a clock-trust violation.
- **Change B — INSERT path seeds quarantine.** The `VALUES` list adds `status`
  (`'unverified'`), `probe_streak` (`1` if alive else `0`), `gpu_uuid`, `boot_epoch`, so
  a brand-new self-reporting row **appears `unverified`** (gate "zero-touch register").
- **Change C — PRUNE fix (load-bearing; C3-PRUNE, preserved from attempt 1).** Replace
  `heartbeat_all.py`'s `PRUNE` so it deletes only rows that are **both** absent from
  enabled `fleet_nodes` **and already stale**:
  ```sql
  DELETE FROM gpu_slots
  WHERE (node, slot_id) NOT IN (SELECT node, slot_id FROM fleet_nodes WHERE enabled)
    AND heartbeat_ts <= now() - interval '45 seconds';
  ```
  A self-pushed node with no `fleet_nodes` row keeps its row **fresh**, so it is never
  pruned; a genuinely removed/disabled node goes stale, then is pruned. This is what lets
  "registration = first heartbeat" coexist with the pull driver's housekeeping.
- **Blast radius:** one SQL constant (the `UPSERT`) + the `boot_epoch` stamp helper + the
  `PRUNE` predicate + the row-build dicts in `heartbeat_once`/`probe_node`. Because
  `heartbeat_all.py` shares the `UPSERT`, the SET/WHERE change covers both the
  single-node and driver writers at once.
- **Backward compatible:** until Slice 4 no consumer reads `status`/`probe_streak`, so
  populating them changes no routing. The ratchet `WHERE` only ever *refuses* a
  stale/equal replay; with `boot_epoch` NULL everywhere pre-rollout it is a no-op (both
  NULL arms). Held leases are untouched (the SET never names the lease columns).

### Slice 2 — Global puller-lease (peer-runnable driver; kills the SPOF)
- **Files:** `heartbeat_all.py` (acquire/renew a `fleet_meta` puller-lease CAS at the top
  of each tick; idle the tick if not held), `tests/test_puller_lease.py` (new, hermetic
  CAS logic over a recording fake) + a PG case in `tests/test_lifecycle_pg.py`.
- **Change — the CAS, byte-aligned with the Slice-0 DDL (BC5):**
  ```sql
  UPDATE fleet_meta
     SET holder = %(me)s, lease_until = now() + make_interval(secs => %(ttl)s)
   WHERE id = 1
     AND (holder IS NULL OR now() >= lease_until OR holder = %(me)s)
  RETURNING holder
  ```
  Holds → drive the tick and renew; loses → sleep one interval and retry. **Column
  `holder` is identical in the DDL, the CAS, and tests A/B** — the cycle-1/2
  `puller`-vs-`holder` mismatch is gone (BC5).
- **TTL is PINNED below the staleness window (BC3).** The puller-lease deadman TTL =
  **`PULLER_LEASE_TTL = 15` s**, strictly `< 45 s` (the `live_slots`/`routable_slots`
  window) and equal to the RFC's ~15 s probe cadence. So when the holder dies, a standby
  acquires the lease and writes fresh heartbeats **within ≤ 15 s**, well before any live
  slot ages out at 45 s. (`now() >= lease_until` is evaluated **server-side**, so a
  standby's clock skew cannot mis-time the takeover.)
- **Blast radius:** a wrapper around the existing `tick()`; the probe/UPSERT body is
  unchanged.
- **Backward compatible:** a **single** puller (today's deployment) wins the CAS trivially
  and drives exactly as now; the only new behavior is that a **second** puller idles
  instead of double-driving. The fleet is unchanged until a second driver is actually
  deployed (an operator step, out of this build's scope).

### Slice 3 — Per-node driver-lease arbitration (single writer; push opt-in) — **BC1 rewritten**
The cycle-1/2 blocker (BC1) was that attempt 1/2 made the push path **CAS-acquire its
per-node lease on `fleet_nodes` BEFORE the UPSERT and yield on failure** — so a
zero-touch node with no `fleet_nodes` row CAS'd zero rows, yielded, and never wrote its
first `gpu_slots` row. This revision adopts **arbitration model (c)**: *the registering
write is unconditional; the per-node driver-lease governs only ongoing contention, and
contention can only exist for a node that is in `fleet_nodes`.*

- **Files:** `heartbeat_all.py` (`FETCH` gains the **server-side** lease predicate +
  `driven_by`/`lease_until` columns), `heartbeat.py` (push/`--node self` mode does a
  **best-effort** per-node lease CAS that does **NOT** gate the UPSERT),
  `tests/test_driver_lease.py` (new, hermetic) + PG cases in `tests/test_lifecycle_pg.py`.
- **Change A — registration is UNCONDITIONAL (the BC1 fix).** The push path ALWAYS runs
  the `gpu_slots` UPSERT (registration = first heartbeat). It additionally, and only as a
  *coordination signal*, attempts a per-node lease CAS on its `fleet_nodes` row:
  ```sql
  UPDATE fleet_nodes
     SET driven_by = %(me)s, lease_until = now() + make_interval(secs => %(node_ttl)s)
   WHERE node = %(node)s AND slot_id = %(slot_id)s
     AND (driven_by IS NULL OR driven_by = %(me)s OR now() >= lease_until)
  RETURNING node
  ```
  The CAS result is **ignored for the purpose of writing the slot** — zero rows (no
  `fleet_nodes` row, or another writer holds a fresh lease) does **not** stop the UPSERT.
  For a **no-`fleet_nodes` self-pusher** the CAS simply matches zero rows and the node
  still registers; the directory-driven puller never probes it (it isn't in
  `fleet_nodes`), so **no contention exists and none is needed.**
- **Change B — the puller skips push-held nodes SERVER-SIDE (BC4).** The driver's `FETCH`
  evaluates lease freshness with the DB clock, never the puller host's:
  ```sql
  SELECT node, slot_id, endpoint_url, served_model, probe_model, latency_class,
         gpu_cmd, nvlink_domain, max_context, free_slots, epoch, min_load_vram_mib
  FROM fleet_nodes
  WHERE enabled AND (driven_by IS NULL OR now() >= lease_until)
  ORDER BY node, slot_id
  ```
  A node whose lease is **fresh by the DB clock** is excluded (its self-pusher owns it); a
  node whose lease is **expired by the DB clock** is probed. The per-node driver-lease TTL
  = **`NODE_LEASE_TTL = 30` s** (< 45 s), so a dead pusher's lease lapses and the puller
  resumes and refreshes `heartbeat_ts` within one puller interval of lapse — before the
  slot ages out.
- **Why C9 ("push and pull never both write a node") still holds**, restated for what is
  built:
  - *node NOT in `fleet_nodes`*: the puller's `FETCH` never returns it, so push is the
    sole writer. ✓
  - *node in `fleet_nodes`, push live*: the pusher holds a fresh lease → the server-side
    `FETCH` predicate excludes it → only push writes. ✓
  - *node in `fleet_nodes`, push dead*: the lease lapses (`now() >= lease_until`) → the
    `FETCH` includes it → only the puller writes. ✓
  The window where both could write is closed because the puller's inclusion test and the
  pusher's lease are **the same DB-clock predicate on the same row**.
- **Blast radius:** the puller's node-selection filter (one `WHERE` clause) + a
  non-gating CAS in the push path. No new agent, no new codebase — push is the *existing*
  `heartbeat.py --node self --gpu-cmd nvidia-smi` run-mode.
- **Backward compatible:** with `driven_by` NULL / `lease_until` expired everywhere
  (today), the `FETCH` predicate reduces to `WHERE enabled` and the puller drives every
  node = today's behavior. Push is opt-in for the trusted Linux quad-server only;
  **peecee stays pull-only** (no fleet code/creds).

### Slice 4 — Consumers gate routing on `status='routable'` (turns quarantine ON)
- **Files:** `pick_slot.py` (`PICK` adds `AND status='routable'`; may surface `status`),
  `di_fleet.py` (`LEASE_CLAIM_SQL` adds `AND status='routable'`), `tests/test_pick_slot.py`
  + `tests/test_leases.py` (hermetic) + a PG case.
- **Change A — picker:** add `AND status = 'routable'` to `pick_slot.PICK`'s existing
  inline live predicate (`pick_slot.py:30-32` — note the picker queries `gpu_slots`
  directly with `WHERE alive AND heartbeat_ts > now()-45s AND (lease free)`, it does
  **not** read the `live_slots` view, so the change is one predicate on that query, not a
  view swap). `pick` already reads **measured** columns (`vram_free_mib`, `probe_ms`,
  `served_model`); gate "anti-lie" needs only the `status` gate.
- **Change B — claim:** add `AND status = 'routable'` to `di_fleet.LEASE_CLAIM_SQL`
  (`di_fleet.py:99-111`) — the RFC's "RFC-0001's CLAIM inherits this for free," literally
  one predicate. `renew`/`release` are unchanged: a slot already leased while routable
  stays renewable through a transient demote within its TTL; demotion gates *new* claims,
  which is the intended behavior.
- **Blast radius:** two SQL predicates + their tests. `routable_slots` (the view) is the
  RFC's narrowed `live_slots`, created in Slice 0 for observability/parity and any direct
  reader; the *code* consumers gate inline (matching how RFC-0001/0003 inlined their live
  predicate).
- **Backward compatible:** this is the slice that **activates** quarantine. By the time it
  deploys, Slice 1 (writer) has graduated every live node to `routable` and the Slice-0
  backfill set existing rows routable, so flipping the gate strands nothing. **Deploy
  LAST.**

### Slice 5 — (DEFERRED, not built in v1) Per-node DB role + RLS
Pillar 5's per-node RLS role bounds the blast radius of a *leaked push credential*. In v1
the only push node is the **trusted** quad-server (shared creds) and peecee is pull-only
(no creds), so **no untrusted push credential exists to bound** — enabling RLS on
`gpu_slots` prematurely risks fencing the puller's own writes. **Documented, not built**
(Open Q4); it becomes a separate additive migration the day an untrusted push node is
provisioned.

**Slice independence & ordering.** 0 → 1 → 2 → 3 → 4. Slices 1–3 only *populate* new
columns / add a driver wrapper + a non-gating CAS; none changes routing. Slice 4 alone
changes routing and is gated on Slice 1 having shipped. Commit order = deploy order.

---

## 2. Migration plan

- **Number: `009`** — `migrations/` holds `001`–`008` (`001_gpu_slots`,
  `002_fleet_nodes`, `003_marker_capability`, `004_peecee_moe_slot`,
  `005_peecee_load_aware`, `006_peecee_dense_27b`, `007_exclusive_slot_leases`,
  `008_lease_epoch`). **`009` is the lowest unused file number.** The RFC body says
  "Migration 006" — that number is **stale/illustrative**: it was written before this
  campaign's peecee dense flip took `006`, RFC-0001 took `007`, and RFC-0003 took `008`.
  The build **MUST use `009`** and never reuse `006`/`007`/`008` (load-bearing claim C1).

- **Exact schema change (`009_zero_touch_lifecycle.sql`), purely additive:**
  ```sql
  -- RFC 0002 — Zero-touch node lifecycle. Columns-only / additive (one new table,
  -- one new view). Backward-compatible: BEFORE Slice 1 the running heartbeat UPSERT
  -- names none of these, so it is unaffected the instant this commits; consumers do
  -- not read `status` until Slice 4, so until then behavior == today.

  -- Pillar 4 — quarantine->graduate, MEASURED capability.
  ALTER TABLE gpu_slots
      ADD COLUMN IF NOT EXISTS status TEXT NOT NULL DEFAULT 'unverified'
          CHECK (status IN ('unverified','probationary','routable','demoted')),
      ADD COLUMN IF NOT EXISTS probe_streak INT NOT NULL DEFAULT 0,
      ADD COLUMN IF NOT EXISTS gpu_uuid TEXT,        -- measured identity (NULL = unknown / pull-only)
      ADD COLUMN IF NOT EXISTS boot_epoch BIGINT;    -- Pillar 5 ratchet (SEPARATE from `epoch`); NULL = ratchet off

  -- Backfill: every slot live TODAY is treated as routable (RFC migration note),
  -- so flipping the consumer gate later strands nothing already in service.
  UPDATE gpu_slots SET status = 'routable';

  -- Pillar 2 — per-node driver-lease (single-writer arbitration on the DECLARED table).
  ALTER TABLE fleet_nodes
      ADD COLUMN IF NOT EXISTS driven_by  TEXT,        -- which writer holds this node (NULL = puller drives)
      ADD COLUMN IF NOT EXISTS lease_until TIMESTAMPTZ; -- deadman TTL; expired => puller resumes

  -- Pillar 1 — global puller-lease row (deadman TTL; same shape as RFC-0001 slot lease).
  -- Column `holder` matches the Slice-2 CAS VERBATIM (BC5).
  CREATE TABLE IF NOT EXISTS fleet_meta (
      id          INT PRIMARY KEY DEFAULT 1 CHECK (id = 1),  -- single-row
      holder      TEXT,
      lease_until TIMESTAMPTZ
  );
  INSERT INTO fleet_meta (id) VALUES (1) ON CONFLICT (id) DO NOTHING;

  -- Pillar 4 — routable_slots, ADDED ALONGSIDE live_slots (expand/contract; do NOT
  -- drop live_slots here — a later contract migration retires it, as 007 did for
  -- free_slots). routable = live AND graduated.
  CREATE VIEW routable_slots AS
      SELECT *, (now() - heartbeat_ts) AS staleness
      FROM gpu_slots
      WHERE alive
        AND heartbeat_ts > now() - interval '45 seconds'
        AND status = 'routable';
  ```
  ```sql
  -- Reverse (before the consumer slice deploys):
  --   DROP VIEW IF EXISTS routable_slots;
  --   DROP TABLE IF EXISTS fleet_meta;
  --   ALTER TABLE fleet_nodes DROP COLUMN IF EXISTS lease_until, DROP COLUMN IF EXISTS driven_by;
  --   ALTER TABLE gpu_slots  DROP COLUMN IF EXISTS boot_epoch, DROP COLUMN IF EXISTS gpu_uuid,
  --                          DROP COLUMN IF EXISTS probe_streak, DROP COLUMN IF EXISTS status;
  ```

- **Apply order (operator, AFTER integration): DB → heartbeat → puller → consumers.**
  1. **DB:** apply `009` (additive ⇒ safe even with `gpu-fleet-heartbeat` running;
     `stop→migrate→start` is optional and equally safe). `ADD COLUMN IF NOT EXISTS` /
     `CREATE … IF NOT EXISTS` make re-apply idempotent.
  2. **Writer:** deploy `heartbeat.py` + `heartbeat_all.py` (Slices 1–3). New nodes appear
     `unverified` and graduate; the PRUNE fix protects self-push rows; push nodes stamp
     `boot_epoch`; the puller honors the per-node lease server-side. **No SSH-retirement
     step in v1 (BC8, option (a)):** peecee keeps its existing cross-host SSH `nvidia-smi`
     `gpu_cmd` and stays on its current SSH-via-pull liveness. The in-build ratchet
     (strict `>` + `COALESCE`) is already correct **without** retiring that leg, so there
     is no pre-rollout window to close by a `fleet_nodes` data change. Retiring the SSH
     fan-out is deferred to the option-(b) follow-up (see §5, §6 Q5).
  3. **Consumers:** deploy `pick_slot.py` + `di_fleet.py` (Slice 4). Routing now gates on
     `status='routable'`.
- **Backward-compatibility invariant:** until the consumer slice gates on `status`,
  **fleet behavior equals today's** — the writer merely populates new columns; the
  picker/claim are unchanged; `live_slots` is untouched.

---

## 3. Test plan — mapped to the RFC's Falsifiable gate

Default `python3 -m pytest tests/ -q` MUST stay **green and hermetic**. (The RFC/prompt
cite "26 tests"; that figure is **stale** — the suite has grown well past it after the
RFC-0001/0003 builds. The invariant to preserve is *"the hermetic default stays green and
every DB-backed test stays guarded,"* not a specific integer; the build run establishes
the exact new count in the project env where `psycopg` is importable.)

Hermetic tests inject the existing fakes (mirroring `tests/test_probe_all.py`,
`tests/test_pick_slot.py`, `tests/test_leases.py`, `tests/test_lease_no_consumer_clock.py`).
Every DB-backed test is **guarded exactly like `tests/test_leases_pg.py` /
`tests/test_epoch_pg.py`**: `pytest.importorskip("psycopg")`, skip unless
`GPU_FLEET_TEST_DB` names an **ephemeral** cluster (dbname must contain `test`, never bare
`gpu_fleet`), and apply the real `migrations/001,007,008,009` to that throwaway DB (which
also proves `009` applies cleanly on the real schema). **Every PG test that asserts CAS /
ratchet / lease behavior runs the REAL SQL constant against the REAL `009` DDL**, so a
column-name or predicate mismatch (the BC5 class of bug) can never recur silently.

| RFC gate bullet | Test(s) | Kind |
|---|---|---|
| **No SPOF** — kill the puller-lease holder ⇒ another node drives within ≤ TTL; fleet does not age out | **A.** `test_puller_lease.py::test_cas_grants_one_then_deadman_failover` — recording fake: holder A wins the CAS, B idles; expire A's `lease_until`; B's next CAS wins. **B.** `test_lifecycle_pg.py::test_puller_failover_no_ageout` — real DB, runs the **real CAS against the real `009` `fleet_meta`** (BC5): two pullers; expire the holder's 15 s lease, advance past the failover gap, assert the standby acquires within TTL **and that no node leaves `routable_slots`/`live_slots`** across the gap (BC3, since 15 s < 45 s). | A: **hermetic**. B: **PG-guarded**. |
| **Zero-touch register** — a node self-reports with no prior `fleet_nodes` row, appears `unverified`, graduates to `routable` only after N probes | **C.** `test_graduation.py::test_streak_promotes_after_N_and_demotes_on_break` — pure state machine over (old row, incoming alive). **D (BC1, COMPOSED).** `test_lifecycle_pg.py::test_self_push_no_fleet_node_registers_and_graduates` — exercises the **composed Slice-1+3 push entry path** for a node ABSENT from `fleet_nodes` with probes stubbed passing: the non-gating lease CAS matches zero rows, **the UPSERT still creates the row `unverified`** & absent from `routable_slots`; N alive ticks ⇒ `routable` & present; and the **stale-only PRUNE** does not delete it while fresh. | C: **hermetic**. D: **PG-guarded**. |
| **Anti-lie** — a node claiming a big GPU whose probe shows small never graduates; routes only measured throughput | **E.** `test_graduation.py::test_failing_or_cold_probe_never_increments_streak`. **F.** `test_pick_slot.py::test_pick_gates_on_status_and_reads_measured` (hermetic `RecordingConn`) + `test_lifecycle_pg.py::test_big_declared_small_measured_not_routable` — large *declared* `max_context`/`served_model`, small *measured* `vram_free_mib`/`probe_ms` ⇒ excluded from `routable_slots` until graduated; routing reads measured columns. | E,F-herm: **hermetic**. F-pg: **PG-guarded**. |
| **Single writer** — proximal-driver vs self-push ⇒ exactly one driver-lease holder; the other skipped | **G.** `test_driver_lease.py::test_fetch_predicate_skips_fresh_lease` — runs the **real `FETCH` SQL** against a fake/recording conn: a `fleet_nodes` row with a fresh `lease_until` is excluded, an expired one is included; the decision is the DB `now()` predicate (no client timestamp). **H.** `test_lifecycle_pg.py::test_push_and_pull_never_both_write` — real DB: a held per-node lease ⇒ the driver `FETCH` omits that node; lapse it ⇒ pull resumes. | G: **hermetic**. H: **PG-guarded**. |
| **Identity survives churn** — a rebooted node re-presents `gpu_uuid`, skips re-quarantine on first passing probe | **I.** `test_graduation.py::test_matching_uuid_carries_routable_forward` — an alive probe whose `gpu_uuid` matches a stored `routable` row stays `routable`; a NULL incoming uuid (pull) keeps the stored identity (COALESCE) and stays routable. **J.** `test_lifecycle_pg.py::test_reboot_same_uuid_skips_requarantine`. | I: **hermetic**. J: **PG-guarded**. |
| **peecee** runs zero fleet code/creds, is still monitored (pull), de-listed when marker owns the card | **K (BC8).** Existing `tests/test_load_aware_liveness.py` proves the de-list under peecee's **existing SSH-via-pull liveness** (which v1 keeps — option (a)); extend with `test_pull_only_node_has_no_db_path` — the pull path writes through the **driver's** connection only and stamps `boot_epoch` NULL (no node creds; `probe_node` is pure I/O). The "no false HTTP-only-liveness claim / no de-listing SSH-retirement step" half of BC8 is discharged by this committed plan's §2-step-2/§4/§5/Q5 text. | **hermetic** (+ existing suite). |
| **No node wall-clock** trusted for `heartbeat_ts` (inspection) | **L.** `test_graduation.py::test_upsert_stamps_heartbeat_ts_from_db_clock` — mirror `tests/test_lease_no_consumer_clock.py`: assert the `UPSERT` writes `heartbeat_ts=now()` on both paths and the row dict carries no `heartbeat_ts`. | **hermetic**. |

**New tests the binding constraints add (all guarded as above):**

| Constraint | Test | Kind |
|---|---|---|
| **BC2** (NULL pull-write never erases the ratchet) | `test_lifecycle_pg.py::test_boot_epoch_survives_null_pull_write` — push-stamp `boot_epoch=K`; a puller UPSERT with `boot_epoch` NULL leaves it `K`; a strictly-stale (`<K`) push is still **refused** after any number of pull ticks. | **PG-guarded** |
| **BC6** (equal-epoch replay is a no-op) | `test_lifecycle_pg.py::test_equal_epoch_replay_is_noop` — stamp `boot_epoch=K`, then replay the same PK with `boot_epoch=K` and **different** `alive`/`served_model`/`gpu_uuid`/`probe_ms`/`note`; assert every mutable field **and `heartbeat_ts` do not move**; then a strictly-greater epoch IS accepted. Hermetic companion `test_graduation.py::test_ratchet_predicate_is_strict_gt` asserts the `UPSERT` `WHERE` contains `EXCLUDED.boot_epoch > gpu_slots.boot_epoch` and not `>=`. | **PG-guarded** (+ hermetic substring) |
| **BC7** (uuid change re-quarantines) | `test_graduation.py::test_uuid_mismatch_resets_streak_and_demotes` (hermetic state machine) + `test_lifecycle_pg.py::test_hot_swap_demotes_to_unverified` — a stored `routable` row, `uuid=U1`, `streak>=N`, receives an alive probe with `uuid=U2`: becomes `unverified`, `probe_streak` reset, absent from `routable_slots` until it re-graduates under U2. | hermetic + **PG-guarded** |
| **BC4** (server-side lease freshness; no node wall-clock) | `test_driver_lease.py::test_fetch_freshness_uses_db_now_no_client_clock` — the driver-lease analog of `test_lease_no_consumer_clock.py`: AST + substring assert that the `FETCH` decides freshness via `now() >= lease_until` and the puller carries no client timestamp param for the skip decision. | **hermetic** |
| **BC5** (fleet_meta column name) | discharged by tests **A/B/G/H** running the real CAS + real `FETCH` against the real `009` DDL — a `holder`/`puller` divergence would raise `column … does not exist` and fail the suite. | hermetic + **PG-guarded** |
| **BC8** (peecee pull-only liveness vs SSH-retirement) | option (a) committed: peecee keeps SSH-via-pull liveness, so test **K** (`test_load_aware_liveness.py` + `test_pull_only_node_has_no_db_path`) proves peecee is still monitored via pull and de-lists when marker owns the card; the "no false claim / no de-listing step" half is discharged by this committed plan's §2/§4/§5/Q5 text (inspection). | **hermetic** (+ committed-plan inspection) |

**Hermetic-default guarantee (C11).** All new default-suite tests (C, E, F-herm, G, I, K,
L, BC6-substring, BC7-herm, BC4) inject fakes / inspect SQL and need no DB. Existing
lease/pick tests stay green because (a) the Slice-0 backfill + Slice-1 writer leave
`status='routable'` for every fake/row those tests build, and (b) the consumer gate `AND
status='routable'` evaluates `True` for them. The PG tests skip cleanly when
`GPU_FLEET_TEST_DB` is unset.

---

## 4. Live-infra safety

The build is **inert** with respect to live infra. It only:
- writes `migrations/009_zero_touch_lifecycle.sql`;
- edits `heartbeat.py`, `heartbeat_all.py`, `pick_slot.py`, `di_fleet.py`, and `tests/*`;
- runs the **hermetic** `python3 -m pytest tests/ -q`.

It MUST NOT, and does not need to:
- connect to / migrate the **live `gpu_fleet`** Postgres (the PG tests refuse a
  non-ephemeral DB and skip by default; only an operator-provided `GPU_FLEET_TEST_DB`
  throwaway cluster runs them);
- restart or touch the running **`gpu-fleet-heartbeat`** service;
- touch **peecee**'s shared GPU (no probe, no decode, no `nvidia-smi`, no SSH).

The operator, **after** integration, applies `009` (`stop→migrate→start`), redeploys the
writer then consumer checkouts, and deploys a **second** puller (the SPOF kill) + any
**push** sidecar on the trusted quad-server. **No SSH-retirement step ships in v1**
(BC8, option (a)): peecee keeps its cross-host SSH `nvidia-smi` `gpu_cmd` and its existing
SSH-via-pull liveness; retiring the SSH fan-out is the deferred option-(b) follow-up
(§5, §6 Q5). Migration `009` is additive, so even an unstopped heartbeat is safe.

---

## 5. Boundaries to preserve

- **`di` stays a subprocess.** Nothing in this build imports the Node engine
  (`~/git/divergent-ideation`); di-fleet consumers shell out to `di --json`. The `status`
  gate is registry-side SQL only.
- **`bin/di-fleet` is a thin `exec python3 di_fleet.py` wrapper** — no logic, **not
  edited**. "Re-deploying `bin/di-fleet`" is the operator step of updating the gpu-fleet
  checkout on consumer hosts so the new `di_fleet.py` / `pick_slot.py` take effect.
- **The table + the query stay the router.** No central daemon, no new always-on service
  beyond the *already-existing* heartbeat driver (now peer-runnable via the puller-lease).
  `pg_cron` is **not** adopted as the driver (RFC Pillar 1 / Traps); the peer-runnable
  external puller is the shipped default, `pg_cron` a documented host-free option,
  **out of scope**.
- **No fleet code or DB credentials land on peecee.** peecee stays pull-only; the build
  adds no node-side agent for it, and a pull write stamps `boot_epoch` NULL (no boot
  identity asserted).
- **peecee's cross-host SSH `nvidia-smi` leg is NOT retired in v1 (BC8, option (a) —
  corrects the cycle-3 holder plan's false claim).** The RFC's Pillar 6 *eventually*
  retires the **cross-host SSH fan-out** (the brittle `gpu_cmd='ssh … peecee nvidia-smi'`
  path), but **v1 does not do this**, because peecee's liveness does **not** come from its
  HTTP endpoint alone. The live code refutes the "HTTP endpoint already provides liveness"
  framing: `heartbeat_all.probe_node` calls `gpu_stats(n["gpu_cmd"])` **first** for every
  node; `gpu_stats` shells `nvidia-smi` (local or SSH) and returns `_error`/no `gpu_model`
  when the command is absent (`heartbeat.py:65–71`); and `ollama_ondemand_liveness`
  **fails closed** — `if gpu_err is not None or stats.get("gpu_model") is None: return
  False, None, None` (`heartbeat.py:168`) — **before** the `/api/ps` residency check
  (`:175`) and the COLD/loadable VRAM-headroom branch (`:180`, which itself reads
  `stats["vram_free_mib"]`). So **removing peecee's SSH `gpu_cmd` would de-list peecee**
  (`alive=False`, never graduates, gone from `routable_slots` after Slice 4). Therefore v1
  **keeps** peecee's SSH-via-pull liveness exactly as today. peecee is "pull-only" in the
  load-bearing sense — **no fleet code or DB credentials run on the node** — but its
  load-aware liveness still consumes an `nvidia-smi` VRAM reading driven by the *puller*
  (cross-host, from the puller host, not on peecee). The in-build `boot_epoch` ratchet
  (strict `>` + `COALESCE`) is correct **without** retiring the SSH leg, so there is no
  pre-rollout window to close. **Deferred follow-up (BC8 option (b)):** a real HTTP-only
  peecee liveness path — `probe_node` skips `gpu_stats` for an `ollama-ondemand` node and
  derives resident/loadable state from the endpoint, recording the lower-trust
  endpoint-asserted VRAM per Pillar 6 / Q5 — proven by a test that invokes no
  SSH/`nvidia-smi`, returns `alive=True` (`boot_epoch` NULL, can graduate) when the
  endpoint is serveable and `alive=False` when marker owns the card. That is what finally
  retires the cross-host SSH fan-out; it is **out of scope for v1**.
- **`epoch` (RFC-0003) is not touched.** `boot_epoch` is a new, separate column; the
  `epoch` CASE is byte-unchanged (C7).
- **`live_slots` is preserved** (expand/contract); no current reader of it breaks at
  migration time.

---

## 6. Open questions — the build's answers

- **Q1 — `N`-probe graduation threshold (flat N vs EWMA).** Adopt **flat `N = 3`**
  (`GRADUATION_STREAK = 3`, a module constant in `heartbeat.py`, interpolated into the
  `UPSERT`). Falsifiable and explainable; EWMA deferred. Ladder: `unverified
  --(streak≥1)--> probationary --(streak≥N)--> routable`; demote to `unverified` on any
  failed probe **or** a `gpu_uuid` change (BC7).
- **Q2 — graduation latency for slow-to-warm nodes (peecee's cold MoE).** A node in #2's
  *cold-loadable* state (`alive=true, probe_ms=NULL`) **counts toward the streak on its
  load-aware-alive ticks** — graduation must NOT require *hot* decode-probes it can only
  pass by paying the cold-load cost every tick. The streak increments on `alive`, warm or
  cold-loadable; verification ("GPU is real & was ready") and liveness ("can serve this
  tick") stay orthogonal, and the heartbeat never forces a load (existing invariant).
- **Q3 — `pg_cron` vs peer-runnable puller.** Ship the **peer-runnable external puller**
  (Slice 2). `pg_cron` documented, **not built** (the RFC Traps' load-bearing risk).
- **Q4 — per-node RLS / signed heartbeats.** **Deferred** (Slice 5). In v1 the only push
  node is the trusted quad-server (shared creds) and peecee is pull-only (no creds), so no
  untrusted push credential needs bounding; enabling RLS prematurely risks fencing the
  puller's own writes. Signed per-node-key heartbeats are rejected by the RFC
  (over-engineered for a LAN behind the DB's own auth).
- **Q5 — trust-tier the endpoint-asserted VRAM (Pillar 6).** v1 does **not** add a
  `vram_trust` column. The behavioral defense already exists: pull-reported VRAM flows
  into the measured columns, but routing leans on **load-aware liveness + warm-first**
  (`di_fleet.route_slots`, `_filter_llm_slots`), so a stale/optimistic self-reported VRAM
  degrades to *"don't route here"* (ages out) rather than *"route and fail."* **BC8
  clarification:** in v1 peecee's liveness is still driven by the puller's cross-host
  `nvidia-smi` reading (option (a)), so the *endpoint-asserted* lower-trust VRAM tier only
  becomes load-bearing under the deferred HTTP-only liveness path (option (b)); until then
  peecee's VRAM signal is the puller-measured `nvidia-smi` value, not an endpoint
  assertion. The pull-only GPU-swap case BC7 cannot see (a pull-only node that swaps cards
  while reporting **no** `gpu_uuid`) is covered by Pillar-6 trust-tiering + load-aware
  liveness, NOT by the uuid ratchet (which fires only on two *known, different* uuids —
  see §7 C10). An explicit lower-trust tag, and the HTTP-only liveness path, are cheap
  additive follow-ups; out of scope to keep `009` columns-faithful to the RFC's migration
  list.
- **Q6 — the 1-token probe's blind spot.** Acknowledged, **out of scope for v1** (RFC open
  question): the decode-probe proves decode + latency + VRAM headroom, not sustained
  throughput / real context / numerical correctness. A periodic deeper canary is a
  possible follow-up.

---

## 7. Load-bearing claims (carried into verify)

- **C1 — `009` is the correct, unused migration number; the RFC's "006" is stale.**
  *Support:* `migrations/` contains `001`–`008`; `009` is the lowest unused file; the
  build reuses none. *Refuted by:* an `009` file already exists, or a live process
  references `006`/`007`/`008` as this RFC's migration.
- **C2 — Migration `009` is purely additive, reversible, and behavior-neutral until Slice
  4.** *Support:* only `ADD COLUMN IF NOT EXISTS` / `CREATE … IF NOT EXISTS` / one new
  view + one backfill `UPDATE`; the running UPSERT names no new column before Slice 1;
  consumers gate nothing until Slice 4; the reverse block restores the prior schema.
  *Refuted by:* the DDL alters/drops an existing column or view, the running heartbeat
  errors after it commits, or routing changes before Slice 4.
- **C3 — Registration = first heartbeat works for a no-`fleet_nodes` self-pusher
  (RESTATED for BC1).** *Support:* the push path's lease CAS is **non-gating** (Slice 3
  Change A); the `gpu_slots` UPSERT runs unconditionally and creates the row `unverified`;
  the **stale-only** PRUNE (Slice 1 Change C) keeps a fresh self-push row; the puller
  never prunes/contends a node it cannot see. *Refuted by:* the composed
  Slice-1+3 test (test D) showing a no-`fleet_nodes` self-push fails to create or graduate
  a row, or the PRUNE deleting a fresh self-push row.
- **C4 — `status` quarantine changes no routing until the consumer slice.** *Support:*
  `pick_slot`/`di_fleet` do not gate on `status` before Slice 4; backfill + writer keep
  every live row `routable`. *Refuted by:* `pytest tests/ -q` regresses, or a live slot
  drops out of routing at migration time.
- **C5 — Writer-before-reader ordering strands no node.** *Support:* Slice 1 graduates
  live nodes to `routable` and Slice 0 backfills existing rows before Slice 4 flips the
  gate. *Refuted by:* a deploy order where Slice 4 precedes Slice 1 leaving live nodes
  un-routable (the plan forbids it).
- **C6 — The boot-epoch ratchet refuses every write whose epoch is ≤ recorded, and is
  inert when either side's `boot_epoch` is NULL (RESTATED for BC2 + BC6).** *Support:*
  `boot_epoch` is **strictly monotonic per write** (`next_boot_epoch`), so the `WHERE`
  predicate is a STRICT `EXCLUDED.boot_epoch > gpu_slots.boot_epoch`; an equal-epoch
  replay carries a value **not greater** than recorded and is **refused** (no field moves,
  `heartbeat_ts` not re-stamped — BC6); `boot_epoch = COALESCE(EXCLUDED.boot_epoch,
  gpu_slots.boot_epoch)` so a NULL (pull) write never erases a stored stamp and a later
  strictly-stale write is still refused (BC2); both `IS NULL` arms keep it a no-op for
  pull-only nodes and pre-rollout. *Refuted by:* a PG test where an equal- or lower-epoch
  write mutates the row or moves `heartbeat_ts`, a NULL pull write zeroing `boot_epoch`,
  or the `WHERE` still containing `>=`.
- **C7 — `boot_epoch` and `epoch` never alias.** *Support:* distinct columns; the
  RFC-0003 `epoch` CASE is byte-unchanged; this build touches only `boot_epoch`. *Refuted
  by:* any edit to the `epoch` expression, or `boot_epoch` reusing the `epoch` column.
- **C8 — The puller-lease CAS executes on the declared schema; a single puller is
  unaffected, only a second idles (RESTATED for BC5/BC3).** *Support:* the `fleet_meta`
  column is `holder` in the DDL, the CAS, and tests A/B; the CAS is won trivially by a
  lone holder and renewed each 15 s tick; TTL = 15 s < 45 s. *Refuted by:* the CAS raising
  `column … does not exist`, two pullers both driving, or a TTL ≥ 45 s aging the fleet out
  during failover.
- **C9 — Push and pull never both write a node (RESTATED for BC1/BC4).** *Support:* the
  puller's `FETCH` excludes a node with a fresh lease via a **server-side** `now() >=
  lease_until` predicate; a no-`fleet_nodes` node is never in the `FETCH` at all; a dead
  pusher's lease lapses and pull resumes. *Refuted by:* a test showing two concurrent
  committed writers for one `(node, slot)`, or the skip decision reading a client clock.
- **C10 — Trust carries forward ONLY on a matching/unknown uuid; a change to a known,
  different uuid re-quarantines (RESTATED for BC7).** *Support:* `probe_streak` resets to
  1 and `status` becomes `unverified` when `gpu_slots.gpu_uuid` and `EXCLUDED.gpu_uuid`
  are **both non-NULL and differ**; the carry-forward arm keeps `routable` only on a
  match (or a NULL incoming uuid, which asserts no new identity and COALESCE-preserves the
  stored one). *Refuted by:* a hot-swap test (test BC7) where a different known uuid keeps
  the prior streak/`routable`, or a matching/NULL uuid being needlessly re-quarantined.
  (The pull-only no-uuid swap is explicitly Pillar-6/Q5 scope, not a C10 counterexample.)
- **C11 — The hermetic default suite stays green and every DB-backed test is guarded.**
  *Support:* new default-suite tests inject fakes / inspect SQL; PG tests use the
  `importorskip`+`GPU_FLEET_TEST_DB`+non-ephemeral-refusal guard verbatim from
  `test_leases_pg.py`/`test_epoch_pg.py` and run the real SQL against the real `009` DDL.
  *Refuted by:* a new test demanding a DB in the default run, or `pytest tests/ -q`
  regressing without `GPU_FLEET_TEST_DB`.
- **C12 — Every liveness / lease / replay timing decision uses the DB clock; no node
  wall-clock is trusted for any routing decision (RESTATED for BC4).** *Support:* the
  `UPSERT` stamps `heartbeat_ts=now()`; the puller-lease and per-node driver-lease
  freshness are `now()` predicates evaluated server-side; the row dicts carry no
  timestamp. `boot_epoch` is a per-node *ordering* token (not a routing/liveness clock)
  and is COALESCE-guarded; the worst a node clock can do is make a node refuse its *own*
  next write. *Refuted by:* a client-supplied timestamp entering any write/lease
  predicate, or a node wall-clock value deciding liveness or routing.

---

## 8. Binding-constraint discharge ledger (clearing ledger cycle 3 → this committed plan)

Each binding constraint the adjudicator recorded is **carried into this committed plan**
and is the build's verify gate. BC1–BC7 were discharged *in design* (the SQL/control-flow
is already in §1–§2 above) and carry forward as must-stay-green tests; BC8's plan-text
half is discharged **here** (option (a): the false claim and the de-listing operator step
are removed from §2-step-2/§4/§5/Q5) and its verification test carries to the build's
final review.

| BC | Severity | Where discharged in this plan | Proving test | Restated claim | Final review |
|----|----------|-------------------------------|--------------|----------------|--------------|
| **BC1** zero-touch self-push deadlock | high (blocker) | Slice 3 Change A (non-gating CAS) + Slice 1 unconditional UPSERT (model c) | `test_lifecycle_pg.py::test_self_push_no_fleet_node_registers_and_graduates` (composed Slice-1+3) | C3, C9 | **required** |
| **BC2** NULL pull-write erases the ratchet | high (blocker) | Slice 1 SET: `boot_epoch = COALESCE(EXCLUDED.boot_epoch, gpu_slots.boot_epoch)` | `test_lifecycle_pg.py::test_boot_epoch_survives_null_pull_write` | C6 | **required** |
| **BC6** equal-epoch replay overwrites live state | high (blocker) | Slice 1 Change A (`next_boot_epoch`, strictly monotonic per write) + strict `>` `WHERE` | `test_lifecycle_pg.py::test_equal_epoch_replay_is_noop` + `test_graduation.py::test_ratchet_predicate_is_strict_gt` | C6 | **required** |
| **BC7** gpu_uuid hot-swap bypasses quarantine | high (blocker) | Slice 1 `probe_streak`/`status` CASE (reset + `unverified` on non-NULL uuid mismatch) | `test_graduation.py::test_uuid_mismatch_resets_streak_and_demotes` + `test_lifecycle_pg.py::test_hot_swap_demotes_to_unverified` | C10 | **required** |
| **BC3** puller-lease TTL vs 45 s age-out | medium | Slice 2: `PULLER_LEASE_TTL = 15` s `< 45` s | `test_lifecycle_pg.py::test_puller_failover_no_ageout` | C8 | not required |
| **BC4** client wall-clock in per-node skip | medium | Slice 3 Change B server-side `FETCH` freshness | `test_driver_lease.py::test_fetch_freshness_uses_db_now_no_client_clock` | C9, C12 | not required |
| **BC5** `fleet_meta.puller` vs CAS `holder` | low | Slice 0 DDL + Slice 2 CAS + tests A/B/G/H all name `holder` | tests A/B/G/H (real SQL on real `009` DDL) | C8 | not required |
| **BC8** peecee pull-only liveness vs SSH-retirement | medium (new) | **option (a) committed:** §2-step-2 SSH-retirement step deleted; §4/§5/Q5 corrected (no false HTTP-only-liveness claim; peecee keeps SSH-via-pull liveness); option (b) deferred follow-up | `test_load_aware_liveness.py` + `test_pull_only_node_has_no_db_path` (test K) + committed-plan text inspection | new C-claim (see §5 peecee bullet) | **required** |

**Preserved intact (the sound spine the ledger told the holder to keep):** C1, C2, C4, C5,
C3-PRUNE, C7, C11, C12, the `di --json` subprocess boundary, peecee runs no fleet
code/creds on the node, and the §4 live-infra inertness. **Not re-opened:** the RFC's
settled design — pull-first peer-runnable driver; push opt-in for trusted Linux nodes
only; registration = first heartbeat; measured-not-declared quarantine→graduate;
`boot_epoch` ⟂ `epoch`.

## Handoff to build + verify

- Keep `python3 -m pytest tests/ -q` **hermetic-green**; run the PG-guarded suite against
  an ephemeral `GPU_FLEET_TEST_DB` exactly as §3 specifies (apply real `migrations/
  001,007,008,009`).
- **Required at final review (`final_review_required: true`):** BC1, BC2, BC6, BC7 (the
  discharge tests stay green and the `>` predicate is never weakened to `>=`) and **BC8**
  (peecee stays monitored via pull and de-lists when marker owns the card; the build ships
  no false "HTTP-only liveness" claim and no de-listing SSH-retirement step — option (a)).
- **Carry forward (`binding: false`, must-stay-green):** BC3, BC4, BC5.
- **Do not re-open** the RFC's settled design.
