#!/usr/bin/env python3
"""gpu-fleet slot picker: claim live, fitting GPU slots by capability.

The router IS this query. SELECT live + capability-matching slots, ORDER BY free
capacity, FOR UPDATE SKIP LOCKED. There is no central router daemon and no SPOF:
the heartbeat table + this query are the load-balancer + work-queue. Consumers
carry their own policy (latency class, model, VRAM need, fan-out width K); the
registry only knows mechanism. `di` calls this with k=concurrency to fan its
isolated branches across whatever slots are live at dispatch time, and degrades
by shrinking K when fewer are free.
"""

from __future__ import annotations

import argparse
import json

import psycopg

PICK = """
SELECT node, endpoint_url, served_model, latency_class, vram_free_mib,
       free_slots, nvlink_domain, probe_ms
FROM gpu_slots
WHERE alive
  AND heartbeat_ts > now() - interval '45 seconds'
  AND (%(latency_class)s::text IS NULL OR latency_class = %(latency_class)s::text)
  AND (%(model)s::text IS NULL OR served_model = %(model)s::text)
  AND (%(min_vram)s::int IS NULL OR vram_free_mib >= %(min_vram)s::int)
ORDER BY free_slots DESC, vram_free_mib DESC NULLS LAST, probe_ms ASC NULLS LAST
FOR UPDATE SKIP LOCKED
LIMIT %(k)s::int
"""

COLS = ["node", "endpoint_url", "served_model", "latency_class",
        "vram_free_mib", "free_slots", "nvlink_domain", "probe_ms"]


def pick(conn, *, latency_class=None, model=None, min_vram=None, k=1):
    rows = conn.execute(
        PICK, {"latency_class": latency_class, "model": model,
               "min_vram": min_vram, "k": k}
    ).fetchall()
    return [dict(zip(COLS, r)) for r in rows]


def main() -> int:
    p = argparse.ArgumentParser(description="pick live fitting GPU slots")
    p.add_argument("--latency-class", choices=("interactive", "batch"))
    p.add_argument("--model")
    p.add_argument("--min-vram", type=int, help="MiB free required")
    p.add_argument("-k", type=int, default=1, help="how many slots (di fan-out width)")
    p.add_argument("--db", default="dbname=gpu_fleet")
    p.add_argument("--json", action="store_true")
    a = p.parse_args()
    with psycopg.connect(a.db) as conn:
        picks = pick(conn, latency_class=a.latency_class, model=a.model,
                     min_vram=a.min_vram, k=a.k)
    if a.json:
        print(json.dumps(picks, indent=2))
        return 0
    for s in picks:
        print(f"{s['node']:9} {s['endpoint_url']:30} {s['served_model'] or '-':18} "
              f"{s['latency_class']:11} vram_free={s['vram_free_mib']} probe_ms={s['probe_ms']}")
    if not picks:
        print("(no live slots match)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
