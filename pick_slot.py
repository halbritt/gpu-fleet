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

PICK = """
SELECT node, endpoint_url, slot_id, served_model, latency_class, vram_free_mib,
       capacity, nvlink_domain, probe_ms, lease_id, lease_expires, epoch
FROM gpu_slots
WHERE alive
  AND heartbeat_ts > now() - interval '45 seconds'
  AND (lease_id IS NULL OR now() >= lease_expires)
  AND (%(latency_class)s::text IS NULL OR latency_class = %(latency_class)s::text)
  AND (%(model)s::text IS NULL OR served_model = %(model)s::text)
  AND (%(min_vram)s::int IS NULL OR vram_free_mib >= %(min_vram)s::int)
ORDER BY (probe_ms IS NOT NULL) DESC,                 -- warm-pref: decode-verified slots first
         vram_free_mib DESC NULLS LAST,
         probe_ms ASC NULLS LAST,
         hashtext(COALESCE(%(job)s::text, '') || node || slot_id::text)  -- stable, NULL-safe jitter
FOR UPDATE SKIP LOCKED
LIMIT %(k)s::int
"""

COLS = ["node", "endpoint_url", "slot_id", "served_model", "latency_class",
        "vram_free_mib", "capacity", "nvlink_domain", "probe_ms",
        "lease_id", "lease_expires", "epoch"]


def pick(conn, *, latency_class=None, model=None, min_vram=None, k=1, job=""):
    """Up to k live, lease-free, fitting slots. Returns a list of dicts.

    `job` seeds the stable-jitter tie-breaker so simultaneous pickers fan across
    equally-ranked rows yet a retry of the same job stays sticky. It is NULL-safe at
    the SQL layer (COALESCE(...,'')): an explicit job=None degrades to '' instead of
    collapsing every row's hash to NULL (BC3).

    Each dict carries `lease_id` / `lease_expires` (so a consumer can claim what it
    picked) and still carries `free_slots` aliased from `capacity` (BC2). It also
    surfaces the slot's current `epoch` (RFC 0003): the lease fence is server-side
    (di_fleet stamps `lease_epoch = epoch` at claim), so surfacing `epoch` is for
    observability and the optional no-lease pre-flight compare — a re-pick after a
    bump reads the NEW epoch here, never a stale one."""
    rows = conn.execute(
        PICK, {"latency_class": latency_class, "model": model,
               "min_vram": min_vram, "k": k, "job": job}
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
    p.add_argument("-k", type=int, default=1, help="how many slots (di fan-out width)")
    p.add_argument("--job", default="", help="seed for the stable-jitter tie-breaker")
    p.add_argument("--db", default="dbname=gpu_fleet")
    p.add_argument("--json", action="store_true")
    a = p.parse_args()
    with psycopg.connect(a.db) as conn:
        picks = pick(conn, latency_class=a.latency_class, model=a.model,
                     min_vram=a.min_vram, k=a.k, job=a.job)
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
