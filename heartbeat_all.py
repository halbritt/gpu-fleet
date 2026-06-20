#!/usr/bin/env python3
"""gpu-fleet heartbeat driver: refresh EVERY declared node, every tick, forever.

Reads the desired fleet from `fleet_nodes` on each iteration (so adding a node is
a pure INSERT -- no restart needed), runs nvidia-smi + a decode-probe per node,
and UPSERTs gpu_slots. A node that fails its probe is written `alive=false` and
ages out of `live_slots`; a node that reappears comes back automatically. One
node's failure (timeout, ssh down) never blocks the others. Built to run under a
Restart=always systemd-user service so the registry stays live with zero human
intervention.
"""

from __future__ import annotations

import argparse
import json
import time

import psycopg

from heartbeat import UPSERT, decode_probe, discover_served_model, gpu_stats

FETCH = """
SELECT node, slot_id, endpoint_url, served_model, probe_model, latency_class,
       gpu_cmd, nvlink_domain, max_context, free_slots, epoch
FROM fleet_nodes WHERE enabled ORDER BY node, slot_id
"""
COLS = ["node", "slot_id", "endpoint_url", "served_model", "probe_model",
        "latency_class", "gpu_cmd", "nvlink_domain", "max_context", "free_slots", "epoch"]


def beat(conn: psycopg.Connection, n: dict) -> dict:
    stats = gpu_stats(n["gpu_cmd"]) or {}
    gpu_err = stats.pop("_error", None)
    served = discover_served_model(n["endpoint_url"], n["probe_model"] or n["served_model"])
    alive, probe_ms, probe_err = decode_probe(n["endpoint_url"], served, 30.0)
    note = "; ".join(x for x in (gpu_err, probe_err) if x) or None
    conn.execute(UPSERT, {
        "node": n["node"], "endpoint": n["endpoint_url"], "slot_id": n["slot_id"],
        "gpu_model": stats.get("gpu_model"), "nvlink": n["nvlink_domain"],
        "vram_total": stats.get("vram_total_mib"), "vram_free": stats.get("vram_free_mib"),
        "util": stats.get("gpu_util_pct"),
        "loaded_model": served if alive else None,
        "served_model": served, "max_context": n["max_context"],
        "latency_class": n["latency_class"], "free_slots": n["free_slots"],
        "epoch": n["epoch"], "alive": alive, "probe_ms": probe_ms, "note": note,
    })
    conn.commit()
    return {"node": n["node"], "alive": alive, "probe_ms": probe_ms,
            "vram_free_mib": stats.get("vram_free_mib"), "note": note}


def tick(conn: psycopg.Connection) -> list[dict]:
    nodes = [dict(zip(COLS, r)) for r in conn.execute(FETCH).fetchall()]
    out = []
    for n in nodes:
        try:
            out.append(beat(conn, n))
        except Exception as exc:  # one node's failure never stops the others
            conn.rollback()
            out.append({"node": n["node"], "alive": False, "error": str(exc)})
    return out


def main() -> int:
    p = argparse.ArgumentParser(description="gpu-fleet heartbeat driver")
    p.add_argument("--db", default="dbname=gpu_fleet")
    p.add_argument("--interval", type=float, default=15.0, help="seconds; 0 = once")
    a = p.parse_args()
    with psycopg.connect(a.db, autocommit=False) as conn:
        while True:
            res = tick(conn)
            live = sum(1 for r in res if r.get("alive"))
            print(json.dumps({"ts": int(time.time()), "live": live, "nodes": res}), flush=True)
            if not a.interval:
                return 0
            time.sleep(a.interval)


if __name__ == "__main__":
    raise SystemExit(main())
