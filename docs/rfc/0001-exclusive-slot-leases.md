# RFC 0001 — Exclusive slot leases

- **Status:** Draft (design) — ready for striatum design→build→verify
- **Backlog:** gpu-fleet v2 #4 (the prereq for exclusive K-fan-out)
- **Supersedes:** advisory `FOR UPDATE SKIP LOCKED` claims
- **Prepared via:** `/adhd` (5 isolated frames × 6 ideas, 3 deepened pillars)

## Summary

Make `di-fleet`'s K-fan-out claims **exclusive** instead of advisory. Today a
consumer picks live slots with `SELECT … FOR UPDATE SKIP LOCKED`, but the row
lock releases when the transaction ends — so two concurrent consumers can claim
the same GPU and fight over it. Add a **lease**: a slot is held by exactly one
consumer for a bounded, self-renewing TTL evaluated entirely by Postgres, with
capacity **derived** from live leases (no mutable counter, no reaper). A crashed
or frozen consumer's lease expires autonomously; a zombie that wakes is fenced
out. This holds the registry's founding invariant — **the table + a query IS the
router; no central daemon, no SPOF.**

## Motivation

- #1 fan-out is advisory: concurrent consumers collide on a GPU.
- Must survive a consumer crash mid-run (deadman) and a node going silent.
- Must compose with the `free_slots` accounting, the di-fleet shard/failover
  model, and the heterogeneous fleet (one scarce warm GPU + cold-loadable shared
  GPUs, peecee being time-shared with `marker`).

## Design

Three load-bearing principles, each the **convergence** of multiple independent
`/adhd` frames (provenance at the end).

### Principle 1 — Capacity is DERIVED, not counted

Rename the mutable `free_slots` counter to an immutable `capacity` (max
concurrent leases; `= 1` for every slot in the current fleet). Availability is
computed at pick time as `capacity − count(active leases)`. Nothing mutates a
counter, so nothing drifts, and there is **no reaper job** to deadlock or page
on — expired capacity reappears the instant anyone queries.

> Convergent across: ant-colony ("reinforcement renewal — the trail vanishes
> when no ant re-walks it"), 3am-on-call ("free_slots as a computed column"),
> inversion ("fuse capacity + exclusivity into one conditional write").

### Principle 2 — Postgres is the ONLY clock; expiry and fencing are SEPARATE

Two orthogonal mechanisms. **Conflating them is the central trap of this RFC.**

- **Expiry (reaping)** = autonomous wall-clock `now() + ttl`, evaluated
  server-side. It advances even when every consumer is frozen, so a hung
  consumer is reaped by a clock it does not control.
- **Fencing (identity)** = a per-lease token. v1 uses the `lease_id` UUID — a
  zombie's renew `WHERE lease_id = $old` matches **zero rows** after re-claim. A
  per-slot strictly-increasing `lease_token BIGINT` is the belt-and-suspenders /
  `capacity > 1` evolution.

No consumer wall-clock is ever consulted, so **clock skew is structurally
impossible**. **Rejected trap:** pure logical-epoch leasing (expiry driven by a
heartbeat-advanced sequence) — a stalled consumer would freeze the very clock
meant to reap it. Expiry MUST advance autonomously; only fencing advances on
claim.

> The existing `epoch` column is **not** overloaded for lease fencing — it stays
> for topology/model-change (see RFC-0003, stale-router fencing). Lease identity
> is a separate `lease_id` / `lease_token`.

### Principle 3 — Leases inherit load-aware liveness (don't duplicate it)

`alive AND heartbeat_ts` fresh `AND vram_free_mib >= model_mib` is a
**precondition of the claim itself**, not a separate guard. So #2's load-aware
liveness — which already ages peecee out when `marker` owns the card — also makes
the lease physically unclaimable. A lease is never offered on a marker-owned GPU.

### Data model (v1: capacity-1, lease as columns on `gpu_slots`)

```sql
ALTER TABLE gpu_slots
  RENAME COLUMN free_slots TO capacity;          -- immutable max concurrent leases
ALTER TABLE gpu_slots
  ADD COLUMN lease_id      UUID,                  -- NULL = free
  ADD COLUMN lease_holder  TEXT,                  -- consumer id (observability)
  ADD COLUMN lease_expires TIMESTAMPTZ;           -- server-stamped
  -- future (capacity>1 / extra fencing): lease_token BIGINT NOT NULL DEFAULT 0
```

A slot is **FREE** ⇔ `lease_id IS NULL OR now() >= lease_expires`.

For `capacity > 1` slots (none in the current fleet — e.g. a 24 GiB card
advertising 3 small-job slots), graduate to a separate `slot_leases(slot_pk,
lease_id, holder, renew_ts, ttl_ms, released)` table with availability via
`count(active) < capacity`. Documented as the evolution; **out of scope for v1.**

### Lifecycle protocol (all server-side, single clock)

**CLAIM** — atomic conditional UPDATE; exclusivity comes from the `WHERE`, not
the row lock:

```sql
UPDATE gpu_slots
   SET lease_id = gen_random_uuid(), lease_holder = $consumer,
       lease_expires = now() + $ttl
 WHERE (node, endpoint_url, slot_id) = $chosen
   AND alive AND heartbeat_ts > now() - interval '45 seconds'
   AND vram_free_mib >= $model_mib                 -- inherits load-aware liveness
   AND (lease_id IS NULL OR now() >= lease_expires) -- free or expired
RETURNING lease_id;
```

Zero rows = lost the race → try the next candidate from the picker.

**RENEW** — every `ttl/3`, piggybacked on di-fleet's existing shard loop (zero
extra connections/threads):

```sql
UPDATE gpu_slots SET lease_expires = now() + $ttl
 WHERE lease_id = $held AND now() < lease_expires
RETURNING lease_id;
```

Zero rows = **"lease lost (expired or re-claimed) — stop touching the GPU
immediately."**

**RELEASE** — on clean shard completion:

```sql
UPDATE gpu_slots SET lease_id = NULL, lease_holder = NULL, lease_expires = NULL
 WHERE lease_id = $held;
```

**EXPIRE** — implicit: a lease with `lease_expires < now()` is simply free to the
next claimant. No reaper, no detector.

TTL = **45s** (aligned with the heartbeat TTL so the two timers fold into one
liveness fact); renew at **15s** (TTL/3) so two missed renewals still leave
margin. `alive` becomes effectively `alive AND now() < lease_expires`.

### Pick query (`pick_slot.py`) — derive availability + disperse the herd

```sql
SELECT … FROM gpu_slots
 WHERE alive AND heartbeat_ts > now() - interval '45 seconds'
   AND <capability> AND vram_free_mib >= $model_mib
   AND (lease_id IS NULL OR now() >= lease_expires)         -- lease-free only
 ORDER BY <warm-pref bias>, vram_free_mib DESC, probe_ms ASC NULLS LAST,
          hashtext($job || node || slot_id::text)           -- stable jitter
 FOR UPDATE SKIP LOCKED                                       -- now a throughput
 LIMIT k;                                                     -- tweak, not the
                                                              -- correctness path
```

`FOR UPDATE SKIP LOCKED` is demoted from the correctness mechanism (the
conditional CLAIM is now the sole authority on who holds a slot) to a mere
contention-reduction optimization.

### Failover = atomic transfer (not return-to-pool)

di-fleet's existing dead-shard re-pin widens to do the lease handoff in **one
transaction**: release the dead lease (fenced on `lease_id`) **and** claim a
survivor (`… SELECT … LIMIT 1`) in the same commit. Freed capacity is handed
directly to the re-pinned shard and never hits the open pool — so failover can't
spawn its own thundering herd, and a dead shard can never outlive its frames.
**Deadman recovery and shard failover become the same code path:** stop renewing
→ self-expire → claim a replacement.

### Thundering herd (the one scarce warm GPU)

Coordinator-free dispersal:
1. **Stable jitter** — `hashtext($job || slot)` as the last `ORDER BY`
   tie-breaker, so simultaneous pickers fan across equally-ranked rows; stable
   per `(job, slot)` so a retry is sticky rather than thrashing.
2. **Optional sub-second soft-reservation** — the picker stamps
   `reserved_until = now() + 250ms, reserved_by = $job` on the warm row; losers
   *see* it in the same scan and treat it as `−1` capacity, self-diverting to a
   cold slot instead of re-polling the warm row. Auto-expires if the winner
   crashes before converting it to a real lease. **(Deferred behind a flag — see
   Open Questions; the current 1–2-consumer fleet's herd is mild.)**

### Heterogeneity (warm proximal vs cold shared peecee) — two numbers, not branches

- **warm (proximal):** long lease TTL + a `warm-pref` `ORDER BY` boost → re-warmed
  rarely, held sticky across a job's frames.
- **cold (peecee, shared with marker):** short churning TTL, and the
  `vram_free_mib >= model_mib` claim precondition means it's leasable only when
  load-aware liveness says it can actually serve.

## Failure modes addressed (the adversarial sweep)

| Failure | Defense |
|---|---|
| Lease leak on consumer crash | Lease lives only while re-renewed; absence → autonomous wall-clock expiry. No reaper. |
| Clock skew (consumer vs Postgres) | No consumer clock ever read; all predicates use Postgres `now()`. |
| lease-TTL vs heartbeat-TTL drift | One clock; lease TTL = heartbeat TTL (45s); renew at TTL/3. |
| Zombie consumer re-asserts after reclaim | `lease_id` fence — its renew matches zero rows. |
| Frozen-but-TCP-alive consumer pins the warm GPU | Reaped by autonomous expiry; it can't keep its own clock alive. |
| Node ages out while a lease is held | Claim/renew require fresh `heartbeat_ts`; a dead node's slot can't renew → lease expires. |
| Thundering herd on the warm slot | Jittered `ORDER BY` + optional sub-second soft-reservation → losers self-divert to cold. |
| Failover re-creates a herd | Atomic release+reclaim transfer; freed capacity never hits the open pool. |

## Falsifiable gate (for the build/verify workflows)

- Two concurrent consumers hammering a capacity-1 slot → **exactly one** holds it
  at any instant (the loser's CLAIM returns zero rows). Proven by a 2-transaction
  concurrency test.
- A consumer that stops renewing (simulated crash) frees the slot within ≤ TTL,
  with **no reaper process running**.
- A zombie renew after re-claim returns **zero rows** (fenced).
- di-fleet K-fan-out across N slots holds **N distinct** leases; a shard failover
  releases its dead lease and claims a survivor **atomically** (no double-hold,
  no leak).
- **No consumer wall-clock** is read anywhere in claim/renew/release (inspection).

## Migration / rollout (backward-compatible)

1. **DB:** rename `free_slots`→`capacity`; add `lease_id, lease_holder,
   lease_expires`; backfill `capacity = 1`. (Until consumers claim, lease columns
   are NULL → every slot reads free = today's behavior.)
2. **`pick_slot.py`:** add the lease-free predicate + jitter; keep SKIP-LOCKED as
   a throughput tweak.
3. **`di_fleet.py`:** claim on dispatch, renew per shard-loop tick, release on
   completion, atomic failover transfer.

Deploy DB → pick_slot → di_fleet in that order (mirrors the #2 migration-first
discipline).

## Alternatives considered & rejected (traps surfaced by `/adhd`)

- **Pure logical-epoch leasing** — REJECTED: a stalled consumer freezes the clock
  meant to reap it. Expiry must be autonomous wall-clock.
- **Vickrey / sealed-bid auction for the warm slot** (markets) — over-engineered
  for a 2–3-node home fleet; YAGNI.
- **Demand-priced preemption / shrinking-TTL surge** (markets) — preempting a
  running di shard throws away expensive partial LLM work + the cold-load cost.
- **JIT milk-run scheduling** (logistics) — a fixed per-consumer schedule idles
  the scarce warm GPU when that consumer isn't asking.
- **Speculative futures pre-warm on peecee** (markets) — pre-warming the shared
  card starves `marker`; conflicts with #2.
- **Mutating a `free_slots` counter** (the obvious answer) — drifts, needs a
  reaper; derived capacity removes the whole class.

## Open questions

- **Soft-reservation in v1 or deferred?** Current fleet has ~1–2 consumers; herd
  is mild. Recommend: ship the jitter in v1, gate the soft-reservation behind a
  flag until contention is observed.
- **`capacity > 1` slots** (a 24 GiB card advertising several small-job slots):
  defer to the `slot_leases` table evolution; v1 is capacity-1 columns.
- **Where does `model_mib` per slot come from?** A new column, or reuse
  `min_load_vram_mib` introduced by #2's `ollama-ondemand` mode?

## `/adhd` provenance

5 isolated frames — **logistics, ant-colony, markets, inversion, 3am-on-call** —
× 6 ideas, then 3 deepened pillars. The design is the **convergence**: 4 frames
independently reached "Postgres is the only clock"; 3 reached "the lease lives
only while re-dripped"; 3 reached "fence the zombie." The cross-frame agreement
is the confidence signal; the traps above are the divergence that didn't survive
scoring.
