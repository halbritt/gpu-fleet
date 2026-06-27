#!/usr/bin/env python3
"""gpu-fleet slot picker: claim live, fitting GPU slots by capability.

The router IS this query. SELECT live + capability-matching slots that are
LEASE-FREE, ORDER BY warm-preference then fit, FOR UPDATE SKIP LOCKED. There is no
central router daemon and no SPOF: the heartbeat table + this query are the load-
balancer + work-queue. Consumers carry their own policy (latency class, model, VRAM
need, fan-out width K); the registry only knows mechanism. `di` calls this with
k=concurrency to fan its isolated branches across whatever slots are live and unleased
at dispatch time, and degrades by shrinking K when fewer are free.

RFC 0001: availability is now DERIVED from live leases, not a mutable counter. A slot
is pickable when `lease_id IS NULL OR now() >= lease_expires`. `capacity` is the
expand-half of the RFC-mandated `free_slots -> capacity` rename (migration 007); for
the current capacity-1 fleet the lease-free predicate IS the availability test, so
`capacity` is not branched on here. `free_slots` is still surfaced in the output
(aliased from `capacity`) so an un-upgraded reader never KeyErrors during the
readers-before-writers rollout — until the out-of-scope contract migration retires it.
"""

from __future__ import annotations

import argparse
import json

# RFC 0005 (Slice 3, F-LOCK) — the router locks the BASE table, never a join view.
# PICK keeps `FROM gpu_slots` as its base relation and adds INLINE LEFT JOINs to the
# companion (gpu_slots_capacity) + the per-model footprint/KV policy (model_capacity),
# plus a CROSS JOIN to the SINGLETON capacity_policy (WHERE id = 1). Because model_capacity
# is PK-keyed on `model` and capacity_policy is the singleton, the join is provably ONE
# ROW per (node, endpoint_url, slot_id) — pick(k=2) on a one-slot fleet returns it once,
# never duplicated (F-CARD). The lock clause is `FOR UPDATE OF gpu_slots SKIP LOCKED`,
# naming the base table so Postgres locks exactly the gpu_slots row and does NOT try to
# lock the read-only companion/policy/model joins (which would error on a non-lockable
# join / view). The capacity_slots VIEW is read-only/diagnostic and is NEVER locked here.
#
# The VRAM predicate is the request-aware, freshness-decayed HEADROOM form (BC1): the fresh
# effective_free (decayed to NULL once stale, BC2 single-clock) COALESCEs through to
# vram_free_mib, and the requirement adds the per-slot model footprint + the
# max_context-derived KV budget. With max_context NULL and no model_capacity row this is
# BYTE-EQUIVALENT to today's `vram_free_mib >= COALESCE(min_vram,0)` (C7).
_FRESH_EFFECTIVE = """
        CASE WHEN c.capacity_source = 'measured'
               AND (COALESCE(c.fast_source_age_s, 0)
                      + GREATEST(0, EXTRACT(EPOCH FROM (now() - c.updated_ts))))
                   <= cp.decay_k * cp.fast_half_life_s
             THEN c.effective_free_mib ELSE NULL END"""
_DECAYED_SOURCE = """
        CASE WHEN c.node IS NULL THEN 'absent'
             WHEN c.capacity_source = 'measured'
               AND (COALESCE(c.fast_source_age_s, 0)
                      + GREATEST(0, EXTRACT(EPOCH FROM (now() - c.updated_ts))))
                   > cp.decay_k * cp.fast_half_life_s
             THEN 'stale' ELSE c.capacity_source END"""

PICK = """
SELECT gpu_slots.node, gpu_slots.endpoint_url, gpu_slots.slot_id, served_model,
       latency_class, vram_free_mib, capacity, nvlink_domain, probe_ms,
       lease_id, lease_expires, epoch,
       ({fresh}) AS effective_free_mib,
       ({source}) AS capacity_source,
       ({source}) IS DISTINCT FROM 'measured' AS degraded
FROM gpu_slots
LEFT JOIN gpu_slots_capacity c
       ON (c.node, c.endpoint_url, c.slot_id)
        = (gpu_slots.node, gpu_slots.endpoint_url, gpu_slots.slot_id)
LEFT JOIN model_capacity mc ON mc.model = gpu_slots.served_model
CROSS JOIN (SELECT decay_k, fast_half_life_s FROM capacity_policy WHERE id = 1) cp
WHERE alive
  AND heartbeat_ts > now() - interval '45 seconds'
  AND status = 'routable'                              -- RFC 0002: route only MEASURED-verified slots
  AND (lease_id IS NULL OR now() >= lease_expires)
  AND (%(latency_class)s::text IS NULL OR latency_class = %(latency_class)s::text)
  AND (%(model)s::text IS NULL OR served_model = %(model)s::text)
  -- RFC 0005 request-aware headroom (BC1). kv_bytes is the DEFINED inline expression
  -- CEIL(kv_mib_per_1k_tokens * max_context / 1000)::int — no dangling symbol.
  AND COALESCE(({fresh}), vram_free_mib)
      >= COALESCE(%(min_vram)s::int, 0)
       + COALESCE(mc.footprint_mib, 0)
       + CEIL(COALESCE(mc.kv_mib_per_1k_tokens, 0) * COALESCE(%(max_context)s, 0)::numeric / 1000.0)::int
ORDER BY (({source}) = 'measured') DESC,              -- trust measured provenance first (decaying discount)
         (probe_ms IS NOT NULL) DESC,                 -- warm-pref: decode-verified slots first
         COALESCE(({fresh}), vram_free_mib) DESC NULLS LAST,
         probe_ms ASC NULLS LAST,
         hashtext(COALESCE(%(job)s::text, '') || gpu_slots.node || gpu_slots.slot_id::text)  -- stable, NULL-safe jitter
FOR UPDATE OF gpu_slots SKIP LOCKED
LIMIT %(k)s::int
""".format(fresh=_FRESH_EFFECTIVE.strip(), source=_DECAYED_SOURCE.strip())

COLS = ["node", "endpoint_url", "slot_id", "served_model", "latency_class",
        "vram_free_mib", "capacity", "nvlink_domain", "probe_ms",
        "lease_id", "lease_expires", "epoch",
        # RFC 0005 additive output keys (legacy keys above are untouched).
        "effective_free_mib", "capacity_source", "degraded"]


def pick(conn, *, latency_class=None, model=None, min_vram=None, max_context=None,
         k=1, job=""):
    """Up to k live, lease-free, fitting slots. Returns a list of dicts.

    `job` seeds the stable-jitter tie-breaker so simultaneous pickers fan across
    equally-ranked rows yet a retry of the same job stays sticky. It is NULL-safe at
    the SQL layer (COALESCE(...,'')): an explicit job=None degrades to '' instead of
    collapsing every row's hash to NULL (BC3).

    `max_context` (BC1) is the request's context length; the SQL adds its KV budget
    (CEIL(kv_mib_per_1k_tokens * max_context / 1000)) plus the per-slot model footprint
    to the headroom requirement, so a 32k request and a 4k request correctly see
    different slots as routable. Defaulted None => 0 KV => today's flat-VRAM predicate.

    Each dict carries `lease_id` / `lease_expires` (so a consumer can claim what it
    picked) and still carries `free_slots` aliased from `capacity` (BC2). It additionally
    surfaces `effective_free_mib` (the freshness-decayed probe-anchored free), the decayed
    `capacity_source`, and `degraded` (True when routing on the legacy/last-known number
    rather than a fresh measured one). C5 dead-man guard: stale slots are NOT dropped —
    the predicate COALESCEs through to vram_free_mib — so `pick` degrades to last-known-good
    with `degraded=True` instead of returning empty. It also surfaces the slot's current
    `epoch` (RFC 0003) for the optional no-lease pre-flight compare."""
    rows = conn.execute(
        PICK, {"latency_class": latency_class, "model": model,
               "min_vram": min_vram, "max_context": max_context, "k": k, "job": job}
    ).fetchall()
    out = []
    for r in rows:
        d = dict(zip(COLS, r))
        # BC2: keep surfacing `free_slots` until the contract migration retires it,
        # so an un-upgraded reader (old di_fleet, a fleet tool) never KeyErrors.
        d["free_slots"] = d["capacity"]
        out.append(d)
    return out


def main() -> int:
    import psycopg  # lazy: importing pick_slot (e.g. for tests) needs no driver

    p = argparse.ArgumentParser(description="pick live fitting GPU slots")
    p.add_argument("--latency-class", choices=("interactive", "batch"))
    p.add_argument("--model")
    p.add_argument("--min-vram", type=int, help="MiB free required")
    p.add_argument("--max-context", type=int,
                   help="request context length; adds its KV budget to the headroom need (BC1)")
    p.add_argument("-k", type=int, default=1, help="how many slots (di fan-out width)")
    p.add_argument("--job", default="", help="seed for the stable-jitter tie-breaker")
    p.add_argument("--db", default="dbname=gpu_fleet")
    p.add_argument("--json", action="store_true")
    a = p.parse_args()
    with psycopg.connect(a.db) as conn:
        picks = pick(conn, latency_class=a.latency_class, model=a.model,
                     min_vram=a.min_vram, max_context=a.max_context, k=a.k, job=a.job)
    if a.json:
        print(json.dumps(picks, indent=2, default=str))
        return 0
    for s in picks:
        print(f"{s['node']:9} {s['endpoint_url']:30} {s['served_model'] or '-':18} "
              f"{s['latency_class']:11} vram_free={s['vram_free_mib']} probe_ms={s['probe_ms']}")
    if not picks:
        print("(no live slots match)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
