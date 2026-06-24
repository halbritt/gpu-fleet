# RFC 0005 — Exporter-fed capacity signal (probe-anchored)

- **Status:** Draft (design) — ready for striatum design→build→verify
- **Backlog:** README "Next" — *"richer capacity signal from the nvidia exporter
  (VRAM/util/topology) feeding the same rows"*
- **Composes with:** the v2 spine — exclusive leases (RFC 0001), epoch fencing
  (RFC 0003), zero-touch lifecycle (RFC 0002), and the load-aware
  `ollama-ondemand` liveness. No new hardware required.
- **Prepared via:** `/adhd` (5 isolated frames × 6 ideas, 3 deepened pillars)

## Summary

Make the registry's capacity signal **richer without trusting the exporter.** The
decode-probe that already runs every 15 s becomes the capacity **meter**: it stamps a
probe-measured free-VRAM floor and a contention ratio (probe latency vs the slot's cold
baseline) that no exporter exposes. The Prometheus/nvidia exporter is demoted to
**enrichment** (power/temp/topology). Every signal carries provenance + a freshness
half-life and is **hysteresis-banded**, so stale/noisy telemetry self-erases and never
bumps `epoch` or storms the UPSERT. A **per-PID VRAM cross-check** turns the invisible
co-tenant (marker on peecee) into a *measured* phantom the router routes around. The
table + a query stays the router — no exporter on the hot path, no cross-host fanout, no
central daemon.

## Motivation

- `pick` gates on raw `vram_free_mib >= model_mib` (`di_fleet.py`) — a flat number that
  (a) the exporter can lie about or cache, (b) ignores KV-cache cost at the *actual*
  context length, (c) misreads a thermally-throttled-at-100%-util card as busy-capable,
  and (d) is blind to a co-tenant (marker) eating peecee's card.
- The richer signals (util/power/temp/ECC/topology) are available from the
  Prometheus nvidia/DCGM exporters, but **naively** scraping them into the rows would
  couple consumers to Prometheus, re-introduce a cross-host fanout SPOF (the one RFC 0002
  just killed), and storm `epoch` with churn.
- Must compose with leases/epoch/lifecycle and honor **capability MEASURED, not
  declared** + **no central daemon / no SPOF**.

## Design

Three load-bearing principles, each the **convergence** of multiple independent `/adhd`
frames (provenance at the end).

### Principle 1 — The decode-probe is the capacity meter; the exporter only enriches

> Convergent across **remove-the-assumption**, **competitor**, and **hardware-engineer**
> frames — all independently reached "the probe that already runs is the truth, not the
> exporter."

- **`live_slowdown_factor`** = this tick's `probe_ms` ÷ the slot's stored cold/idle
  baseline `probe_ms`. A single *measured* ratio capturing PCIe/memory/scheduler/
  co-tenant contention that no exporter exposes. **Ships first** — it uses data already in
  hand (`probe_ms` exists; the baseline is captured at registration), with zero new side
  effects.
- **`effective_free_mib`** = `LEAST(probe-measured floor, exporter free)`. Trust the
  **lower**: a lying or stale exporter cannot claim headroom the probe could not actually
  allocate.
- derived **`headroom_mib`** = `effective_free − (model_footprint + kv_bytes(max_context))`.
  The pick predicate becomes `headroom_mib >= 0` instead of the flat
  `vram_free_mib >= model_mib`, so a 32k-context request and a 4k-context request
  correctly see different slots as routable.

### Principle 2 — Provenance + freshness + hysteresis; churn never touches `epoch`

> Convergent across **3am-on-call**, **competitor**, and **ant-colony** frames.

- Each field carries `(value, source, source_ts, half_life)`. `pick` decays a field to
  **`unknown`** once it ages past `k × half_life` judged by the **source** timestamp (the
  exporter/probe scrape clock), **not** the row's UPSERT time — so a frozen/cached
  exporter self-erases instead of routing toward a stale number. A `capacity_source` enum
  `{measured, stale, exporter_down, absent}` makes provenance first-class; `ORDER BY`
  trusts `source=measured` (optionally weighting `stale` at a decaying discount rather
  than a hard cliff).
- Stored values are **quantized into coarse bands**; a band changes only after **M-of-N
  consecutive confirmations** crossing an edge. Raw VRAM/util churn writes the *same* band
  → a no-op → **never bumps `epoch`** (extends the RFC-0003 `IS DISTINCT FROM` exclusion).
  Only a genuine band-crossing — or a topology/MIG/ECC change — is routing-relevant.
- Fast fields (VRAM/util) get **seconds**-scale half-life; slow capability fields
  (topology/MIG/ECC) get **hours**, so a missed slow scrape doesn't blank capability while
  a missed fast scrape does.
- **Fleet-floor / dead-man guard:** `pick` never empties the router — if every slot's
  fast fields have decayed to `stale` (a skew event or exporter outage), fall back to
  last-known-good band with a `degraded` flag rather than returning empty.

### Principle 3 — Hidden co-tenants become a *measured* phantom via per-PID attribution

> Convergent across **competitor** + **ant-colony** + the deepen pass — which also
> dissolved the naive "residual = total − Σ declared-lease-footprint" idea (it would
> re-introduce *declared-not-measured* by guessing each lease's bytes).

- The heartbeat reads **per-PID VRAM-used** (`nvidia-smi`/DCGM), sums the PIDs the fleet
  *recognizes* (its own inference servers, bound to leases), and treats **all
  unrecognized-PID VRAM as a phantom occupant** — a *direct measurement* of marker, not an
  estimate.
- The phantom shrinks `effective_free_mib` and may mint a synthetic
  `lease_holder='phantom:<card>'` self-lease that the existing `FOR UPDATE SKIP LOCKED`
  pick routes around — **zero consumer changes**. It clears via normal lease expiry / a
  lower release threshold when the gap drops. **Only the node that physically owns the
  card writes its phantom** (no SPOF).
- Complements (does not replace) the load-aware `ollama-ondemand` liveness, and doubles as
  a grep-able diagnostic for leaked/forgotten VRAM (`phantom:unknown`).

### Signal path (no new SPOF)

- Capacity lives in a **`gpu_slots_capacity` companion table** LEFT JOINed by `pick` (so a
  malformed/crashed exporter degrades the fleet to liveness-only routing instead of
  poisoning the liveness UPSERT), written **only** by the heartbeat/puller that already
  touches the row.
- A node reads its **own local** exporter (`localhost`) during its heartbeat — no
  cross-host scrape. **peecee (pull-only)** has its exporter read by the puller-lease
  holder over the existing pull channel (proxied, attributed `proxied_by=<puller>`), or
  drops a signed blob to the Garage S3 bucket keyed in the row — reusing blessed channels,
  never a new SSH fanout, never fleet code/creds on the node.
- Consumers never touch Prometheus; they read derived columns. **Policy in the consumer**
  (the `headroom >= 0` predicate), **mechanism in the table.**

## Falsifiable gate (for the build/verify workflows)

- A frozen/stale exporter (its `source_ts` stops advancing) causes its capacity fields to
  decay to `stale` and drop out of `pick`'s `ORDER BY` within `k × half_life`, **with no
  writer touching the row** — proven by a test that freezes `source_ts` into the past.
- Raw VRAM/util churn *within a band* produces an **identical** UPSERT and does **not**
  bump `epoch`; only a band-crossing does — proven by a churn test + the
  `IS DISTINCT FROM` inspection.
- A slot whose exporter free-VRAM exceeds the probe-measured floor routes on the **lower**
  (probe) number — proven by a fake exporter over-reporting free VRAM.
- An unrecognized PID holding VRAM shrinks `effective_free` / mints a phantom lease so
  `pick` routes around the card, and it clears when the PID exits — proven by a fake
  per-PID source with an unknown PID.
- `pick` **never returns empty** when all fast fields are stale — it degrades to
  last-known-good with a `degraded` flag (fleet-floor test).
- The peecee `ollama-ondemand` slot is **never force-loaded** by the floor probe (it uses
  the residency-only floor) — inspection + a test (honors the RFC-0002/load-aware
  invariant).
- The hermetic default suite stays green; per-PID and exporter reads are injected fakes
  (no real `nvidia-smi`/HTTP in units); DB-backed tests guarded behind
  `GPU_FLEET_TEST_DB`.

## Migration / rollout (additive, backward-compatible)

1. **Migration 010** (or 011 if the `free_slots` contract migration lands first): add the
   `gpu_slots_capacity` companion table (all fields nullable/defaulted so behavior == today
   until populated); a small `capacity_policy` table holding band edges + M/N + half-lives
   **as data, not code** (tuning is a row edit); and the derived `effective_free`/`headroom`
   view or generated columns. Extend the epoch `IS DISTINCT FROM` exclusion to the banded
   capacity fields.
2. **heartbeat (writer):** capture the cold baseline at registration; write
   `live_slowdown_factor` first (cheapest, zero new side effect); then the probe-floor +
   per-PID attribution behind **per-backend adapters** (peecee `ollama-ondemand` =
   residency-only, never the aggressive scratch-allocation floor).
3. **`pick_slot` / `di_fleet` (readers):** swap `vram_free_mib >= model_mib` →
   `headroom_mib >= 0`; keep emitting the legacy keys for un-upgraded readers (the RFC-0001
   BC2 discipline).

Order mirrors the DB → writer → reader discipline; until the readers switch, behavior ==
today's.

## Alternatives considered & rejected (traps surfaced by `/adhd`)

- **`LISTEN/NOTIFY` push firehose** on threshold crossings — a second event-driven signal
  path; over-engineered for a 1–3-node fleet; complicates the single-writer heartbeat model.
- **Consumer pulls-and-parses Prometheus at pick time** — couples every consumer to the
  exporter on the hot path (latency + coupling); violates "don't couple consumers to
  Prometheus."
- **Cross-row diffusing VRAM gradient** — emergent-for-its-own-sake; no benefit at 1–3
  nodes; extra writes.
- **Self-tuning dynamic scrape richness** — per-slot scrape-set churn; premature.
- **Stored latency-curve / boost-clock V·F mapping / co-tenant bandwidth accounting** —
  premature physical sophistication for a home fleet; good child ideas, not v1.
- **MPS/MIG hard partitions** and a **cgroup-fenced fail-closed probe** — delete the
  shared-pool dynamism that makes the home fleet useful / high blast radius.
- **VRAM futures + settlement-liquidation market** — a settlement state machine that buys
  nothing over a plain penalty signal.
- **Residual = `total − Σ(declared lease footprint)` without per-PID** — re-introduces
  *declared-not-measured* (guessing each lease's bytes); replaced by direct per-PID
  attribution (Principle 3).

## Open questions

- Companion table vs columns on `gpu_slots` — recommend the **separate table** for fault
  isolation (a flaky exporter can't poison the liveness UPSERT).
- Probe-floor aggressiveness — the **observer effect** (a heavy floor probe *becomes* the
  contention it measures, and risks force-loading the `ollama-ondemand` slot) is the
  load-bearing risk. Recommend: ship `live_slowdown_factor` first (no new side effect),
  gate the scratch-allocation floor per-backend, residency-only for `ollama-ondemand`.
- **Clock-skew sensitivity** of `source_ts` decay — judge freshness against the slot's own
  heartbeat **cadence** (relative), not wall-clock `now()`, so NTP skew between hosts isn't
  load-bearing (the failure that looks like "no capacity" fleet-wide).
- **Betrayal pheromone** (consumers write delivered-rate-vs-probed back on lease release) as
  a *between-scrape* backstop the exporter cross-check structurally can't cover — a strong
  complementary follow-up; defer to a v2 of this RFC or a tracked issue.

## `/adhd` provenance

5 isolated frames — **3am-on-call, ant-colony, remove-the-load-bearing-assumption,
competitor-trying-to-break-it, hardware-engineer** — × 6 ideas, then 3 deepened pillars.
The design is the **convergence**: 3 frames independently reached "the decode-probe is the
truth-meter, derive capacity from it" (Principle 1); 3 reached "provenance + freshness
decay + hysteresis banding keep stale/noisy data from misrouting or storming epoch"
(Principle 2); competitor + ant-colony + the deepen pass converged on "per-PID attribution
turns the invisible co-tenant into a *measured* phantom" (Principle 3). The traps above are
the divergence that didn't survive scoring.

**Provocation (worth a separate decision):** make marker — and every LAN VRAM consumer you
control — *speak the lease protocol*. A ~10-line wrapper that writes its own `gpu_slots`
lease row before grabbing VRAM and releases it after turns co-tenant detection into a
*non-problem* for processes you own, leaving the machinery above as defense only against
genuinely **foreign** occupants. Is the real win a smarter detector, or making every
consumer a fleet citizen by default?
