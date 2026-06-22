# RFC 0002 — Zero-touch node lifecycle

- **Status:** Draft (design) — ready for striatum design→build→verify
- **Backlog:** gpu-fleet README "Next" — *"each node self-heartbeats (kills the
  proximal SSH-driver SPOF)"* + *"node self-register on boot"*
- **Composes with:** RFC-0001 (leases), RFC-0003 (epoch), #2 load-aware liveness
- **Prepared via:** `/adhd` (5 isolated frames × 6 ideas, 2 deepened pillars)

## Summary

Remove the two remaining human/SPOF touches in fleet membership: (1) one host
("proximal") SSH-drives every node's `nvidia-smi` — a single point of failure,
and the SSH-into-Windows path is fragile (peecee runs PowerShell); (2) adding a
node is a manual `fleet_nodes` INSERT. The `/adhd` run produced a **reframe** of
the naive "make every node push its own heartbeat": that framing is a trap,
because the hardest node (peecee — Windows, tray-app-not-a-service, no DB creds)
is exactly the one you don't want running fleet code + credentials. The design
instead is **pull-first with a peer-runnable driver**, **push as an opt-in
optimization for trusted nodes**, and **registration = the first heartbeat**, with
a **quarantine→graduate** trust gate so a self-registering node can't lie itself
into routing.

## Motivation

- Kill the proximal-SSH-driver SPOF without putting fragile fleet code on every
  node.
- Make adding a node a zero-touch event (no human INSERT, no central action).
- Hold the founding invariant: **mechanism in the table, policy in consumers, no
  central daemon.**

## Design

Pillars, each a `/adhd` **convergence** (provenance at the end). The wild "let
Postgres `pg_cron` be the sole driver" idea was **tempered by the on-call frame**
into the peer-runnable form below — see Traps.

### Pillar 1 — Pull-first, peer-runnable driver (kills the SPOF, not per-node push)

- The driver loop (`heartbeat_all.tick()`) is **not pinned to proximal**. Any
  Linux node can run it as a service; a **global puller-lease** (CAS on a
  `fleet_meta` row, deadman TTL — same shape as RFC-0001's slot lease) ensures
  exactly one puller drives at a time. Kill the puller host → its lease expires →
  another node grabs it → no SPOF, no config change.
- **Pull is the floor:** the driver probes each node's **existing inference HTTP
  endpoint** (the decode-probe and #2's `ollama-ondemand` `/api/ps` check are
  *already* HTTP pulls). A node "self-reports" by merely answering HTTP — **zero
  fleet code, zero DB credentials on the node.** This is what makes peecee
  participate safely.
- **`pg_cron`-in-Postgres is an OPTIONAL zero-host mode**, not the default —
  see the load-bearing risk in Traps (Postgres has no heartbeat of its own; a
  wedged endpoint in a synchronous loop with no `ThreadPoolExecutor` ages out the
  whole fleet, and outbound HTTP inside the DB is egress in the one component you
  can least afford to wedge). Default to the peer-runnable external puller; offer
  `pg_cron` only for a truly host-free deployment, behind `pg_net` (async).

### Pillar 2 — Push as a per-node opt-in optimization (trusted Linux nodes only)

- The "push sidecar" is **literally the existing `heartbeat.py --node self
  --gpu-cmd nvidia-smi`** the repo already ships — local, no SSH. Push and pull
  are **one codebase, two run-modes** (drive-others vs drive-self), not a forked
  agent.
- Give it to the **trusted quad-server** (Linux, real local `nvidia-smi`);
  **withhold from peecee** (don't put fleet code/creds on the flaky Windows tray
  app — it stays pull-only).
- A **per-node driver-lease** (`driven_by` + `lease_until` on `fleet_nodes`, CAS)
  arbitrates: a self-pushing node holds the lease; the puller **skips** any node
  whose lease is held-and-fresh and probes the rest. Push and pull **never both
  write** a node; a dead pusher's lease expires and pull resumes — self-healing.
- **Hybrid is the default posture, not a migration endpoint:** pull monitors
  every node with zero cooperation; push merely offloads probe cost for trusted
  nodes. A node flips push→pull just by letting its lease lapse.

### Pillar 3 — Registration = the first heartbeat (idempotent UPSERT)

- There is **no separate `INSERT INTO fleet_nodes` step**. The heartbeat UPSERT
  creates the `gpu_slots` row if absent, so "register" and "report" are one code
  path and **a node can't exist in the directory without currently proving it's
  alive** (no orphaned registered-but-dead rows).
- `fleet_nodes` degrades from a *precondition for joining* to an **optional
  declared allowlist / probe-config hint**. `gpu_slots` is the measured
  observed-state. **Do not merge the two tables** — that boundary (declared vs
  measured) is load-bearing for Pillar 4.

### Pillar 4 — Quarantine→graduate; capability is MEASURED, not declared

- A new slot enters **`status='unverified'`** (zero routable weight) and graduates
  `unverified → probationary → routable` only after **N consecutive DB-stamped
  passing decode-probes** (a `probe_streak` counter the UPSERT increments on
  `alive`, zeroes on failure); it is **demoted** back the instant the streak
  breaks. So "booted but GPU not ready" and a "lying node" both sit harmlessly
  unverified.
- **Declared** (from `fleet_nodes`: `served_model`, `latency_class`,
  `max_context` ceiling, `nvlink_domain`) is separated from **measured** (the
  probe writes: `gpu_uuid`, `vram_free_mib`, `probe_ms`→tokens/sec, the real
  served model via `discover_served_model`, the real accepted context). **Routing
  reads only the measured columns gated by `status='routable'`** — a node can
  *claim* an 80 GB A100 but only ever routes the throughput the probe measures.
- `live_slots` narrows to **`routable_slots`** = `alive AND fresh AND
  status='routable'`. **RFC-0001's lease CLAIM inherits this for free** — adding
  `AND status='routable'` makes a slot leasable only after it's verified.

### Pillar 5 — Split-brain, replay, and clock skew as table mechanics

- **Monotonic per-boot epoch ratchet:** each heartbeat carries `boot_id + seq`;
  the registry ignores any write whose epoch is ≤ the one on record. A resurrected
  SSH-driver (or stale second writer) can never overwrite a node that has started
  self-reporting — the transition is a **one-way ratchet**, and replay is refused.
  (This is the membership cousin of RFC-0003's capability epoch; keep them
  separate columns.)
- **DB-stamped `heartbeat_ts`** (`DEFAULT now()` / trigger using transaction
  time), **never** the node's clock → client skew and forged-future timestamps
  can't extend liveness past its real life. The single DB clock is the only
  authority on "when."
- **Per-node DB role + RLS** (for **push** nodes only — pull needs no node creds):
  a node may UPDATE only the rows whose `node_id` matches its login role, so a
  leaked peecee credential can't forge proximal's slots. Blast-radius-bounded.

### Pillar 6 — Trust-tier the VRAM signal (don't let a lying server mislead routing)

A pull-only node with **no independent `nvidia-smi`** (the peecee case) has only
its own server's word for free VRAM — which sees *model-resident* footprint, not
whole-card/co-tenant truth (marker eating the card), and could be stale or
optimistic. So: tag such `vram_free_mib` as **endpoint-asserted (lower trust)**,
and let #2's load-aware liveness stay the gate — **prefer warm/resident over
self-reported-loadable, treat "not loadable" conservatively** — so the fleet
degrades to *"don't route here"* rather than *"route and fail."* `nvidia-smi`
survives exactly where there is no model endpoint to ask (the `gpu-only`/marker
branch) and as a **local** whole-card cross-check on push nodes; only the
**cross-host SSH fan-out** (the fragile peecee PowerShell `2>/dev/null` path)
dies.

### Windows tray-app — the problem largely evaporates

In the pull model **peecee runs no fleet code**, so the tray-app-not-a-service
restart problem mostly disappears: peecee only needs `ollama` up (its existing
concern), and the puller probes it over HTTP. (If push were ever wanted on
Windows, a **Scheduled Task** watchdog relaunches the sidecar — but the
recommendation is **peecee stays pull-only**.)

## Failure modes addressed

| Failure | Defense |
|---|---|
| Proximal SSH-driver dies → half the fleet vanishes | Peer-runnable puller-lease; another node takes over within ≤ lease TTL |
| Split-brain (two writers for one node) | Per-node driver-lease (single writer) + boot-epoch ratchet (ignore ≤ epoch) |
| Replayed/forged heartbeat | Monotonic boot-epoch refused if ≤ recorded; DB-stamped `heartbeat_ts` |
| Self-registering node lies about its GPU | Measured-only routing; quarantine until N probes pass; routes only what it serves |
| Booted but GPU not ready | Stays `unverified`; never reaches routing until probes pass |
| Clock skew / future-dating | `heartbeat_ts` stamped by the DB, never the node |
| DB-credential distribution to flaky Windows node | Pull needs no node creds; push uses a per-node RLS role (bounded) |
| Lying/stale self-reported VRAM | Trust-tier endpoint-asserted VRAM; load-aware liveness stays the gate |
| Windows tray-app didn't restart | peecee is pull-only (no fleet code); puller probes it over HTTP |
| Node flaps (silent then revives) | Ages out of `routable_slots` (45s TTL); re-presents stable `gpu_uuid` → carries trust forward on first pass |

## Falsifiable gate (for the build/verify workflows)

- **No SPOF:** kill the puller-lease holder → another node drives within ≤ lease
  TTL; the fleet does **not** age out. Proven by killing the holder.
- **Zero-touch register:** a node self-reports with no prior `fleet_nodes` row,
  appears `unverified`, and graduates to `routable` only after N probes.
- **Anti-lie:** a node claiming a big GPU whose probe shows small never graduates;
  it routes only measured throughput.
- **Single writer:** with both a proximal-driver and a self-push contending, the
  registry shows exactly one driver-lease holder; the other is skipped.
- **Identity survives churn:** a rebooted node re-presents its `gpu_uuid` and
  skips re-quarantine when its first probe passes.
- **peecee runs zero fleet code/creds**, is still monitored (pull), and is
  correctly de-listed when marker owns the card.
- **No node wall-clock** is trusted for `heartbeat_ts` (inspection).

## Migration / rollout (backward-compatible, incremental)

1. **Spike first (lowest risk):** install `pg_net` + `pg_cron`; port only the
   plain decode-probe branch into a function that probes proximal's
   `localhost:8081` and UPSERTs its row every 15s, **side-by-side** with the
   existing `heartbeat_all.py` service; diff the two rows for a few minutes to
   prove parity before touching the `ollama-ondemand`/`gpu-only` branches or
   retiring any SSH. *(Or skip `pg_cron` entirely and go straight to the
   peer-runnable external puller — recommended.)*
2. **Migration 006:** add `status` (CHECK in unverified/probationary/routable/
   demoted, default unverified), `probe_streak INT DEFAULT 0`, `gpu_uuid TEXT`,
   `boot_epoch BIGINT`; add `driven_by`/`lease_until` to `fleet_nodes`; redefine
   `live_slots` → `routable_slots`. Columns-only, backward-compatible.
2. **heartbeat:** capture `gpu_uuid` (`nvidia-smi --query-gpu=uuid` on push nodes /
   endpoint-reported on pull); increment/reset `probe_streak`; promote/demote
   `status`; stamp `boot_epoch`; honor the per-node driver-lease.
3. **Puller-lease:** add the global puller-lease CAS so the driver is
   peer-runnable; deploy the driver as a service on ≥2 Linux nodes.
4. **Consumers:** `pick_slot` reads `routable_slots`; RFC-0001 CLAIM adds `AND
   status='routable'`.

Order mirrors the #2/#4 migration-first discipline; until graduation logic ships,
every existing slot is treated as routable (today's behavior).

## Alternatives considered & rejected (traps surfaced by `/adhd`)

- **`pg_cron` as the SOLE driver** (remove-assumption frame) — Postgres has no
  heartbeat of its own; a black-hole endpoint in a synchronous in-transaction loop
  (no `ThreadPoolExecutor`) ages out the whole fleet in 45s, and outbound HTTP
  inside the DB wedges the one component you can't afford to lose. **Reframed** to
  a peer-runnable puller-lease; `pg_cron` is an optional host-free mode only.
- **Per-node PUSH everywhere** (the naive backlog framing) — puts fleet code + DB
  creds on the flakiest node (peecee/Windows). **Rejected for peecee;** push is
  opt-in for trusted Linux nodes only.
- **Trusting self-declared capability** — a lying node claims an 80 GB GPU.
  **Rejected;** routing reads measured columns only.
- **mDNS / LAN-announce discovery** (remove-assumption) — a discovery protocol +
  reflector for a 3-node LAN is YAGNI vs. the self-insert UPSERT.
- **Consumers poke peecee's wake endpoint** ("complement opsonization", biology) —
  couples consumers to a node's Windows ops; too clever.
- **Signed per-node-key heartbeats** (competitor/remove-assumption) — crypto for a
  home LAN behind the DB's own auth is over-engineered vs. per-node RLS roles.

## Open questions

- **`N`-probe graduation threshold** vs an EWMA trust score: ship a flat `N` (≈3)
  first (falsifiable, explainable); reserve EWMA for when a flapping node should
  not route like a rock-solid one.
- **Graduation latency for slow-to-warm nodes** (peecee's cold MoE): a node in #2's
  *cold-loadable* state shouldn't be forced through N *hot* decode-probes it can
  only pass by paying the cold-load cost every tick — let it graduate on its
  load-aware-alive ticks instead. (Verification = "GPU is real and was ready";
  liveness = "can serve this tick" — keep orthogonal.)
- **The 1-token probe's blind spot:** it proves decode + latency + VRAM headroom
  but **not** sustained throughput, real context length, or numerical correctness
  — a quantized/wrong/throttled model can pass. A periodic deeper canary is a
  possible follow-up; out of scope for v1.
- **`pg_cron` vs peer-runnable puller** as the shipped default (recommend
  peer-runnable; `pg_cron` documented as an option).

## `/adhd` provenance

5 isolated frames — **biology, competitor-trying-to-break-it, logistics,
3am-on-call, remove-the-load-bearing-assumption** — × 6 ideas, then 2 deepened
pillars (pull-first/driver-placement; quarantine-graduate registration). The
design is the **convergence**: all five frames independently reached
"quarantine→graduate, measured-not-declared"; four reached "monotonic boot-epoch
ratchet kills split-brain"; the wild remove-assumption frame's "Postgres is the
driver" was **tempered by the on-call frame** into the peer-runnable puller-lease
— the generator/critic split doing exactly its job.
