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
from concurrent.futures import ThreadPoolExecutor, as_completed

import psycopg

from heartbeat import UPSERT, decode_probe, discover_served_model, gpu_stats

FETCH = """
SELECT node, slot_id, endpoint_url, served_model, probe_model, latency_class,
       gpu_cmd, nvlink_domain, max_context, free_slots, epoch
FROM fleet_nodes WHERE enabled ORDER BY node, slot_id
"""
COLS = ["node", "slot_id", "endpoint_url", "served_model", "probe_model",
        "latency_class", "gpu_cmd", "nvlink_domain", "max_context", "free_slots", "epoch"]

# Fast-fail probe budgets. A liveness probe must resolve quickly: with nodes
# probed concurrently, the tick is as slow as the slowest probe, so each leg is
# bounded well under the 45s live_slots TTL. A node mid model-reload (e.g. ollama
# after its VRAM was taken) trips these and correctly de-lists until it recovers.
GPU_TIMEOUT = 10.0       # nvidia-smi (local or over ssh)
DISCOVER_TIMEOUT = 5.0   # GET /v1/models
PROBE_TIMEOUT = 10.0     # the decode-probe itself


def probe_node(n: dict) -> dict:
    """Probe one node (nvidia-smi + decode-probe), with NO database access, and
    return an UPSERT-ready row. Pure I/O so it is safe to run in a worker thread;
    the caller owns the single DB connection and does the write."""
    stats = gpu_stats(n["gpu_cmd"], GPU_TIMEOUT) or {}
    gpu_err = stats.pop("_error", None)
    if (n["probe_model"] or n["served_model"]) in ("-", "none", "gpu-only"):
        # Non-LLM capability (e.g. marker): liveness is GPU reachability, not an
        # LLM decode-probe. A decode-probe here would needlessly load a model and,
        # for a node mid document-conversion, fight that job for VRAM.
        served = n["served_model"]
        alive = gpu_err is None and stats.get("gpu_model") is not None
        probe_ms, probe_err = None, None
    else:
        served = discover_served_model(
            n["endpoint_url"], n["probe_model"] or n["served_model"], DISCOVER_TIMEOUT)
        alive, probe_ms, probe_err = decode_probe(n["endpoint_url"], served, PROBE_TIMEOUT)
    note = "; ".join(x for x in (gpu_err, probe_err) if x) or None
    return {
        "node": n["node"], "endpoint": n["endpoint_url"], "slot_id": n["slot_id"],
        "gpu_model": stats.get("gpu_model"), "nvlink": n["nvlink_domain"],
        "vram_total": stats.get("vram_total_mib"), "vram_free": stats.get("vram_free_mib"),
        "util": stats.get("gpu_util_pct"),
        "loaded_model": served if alive else None,
        "served_model": served, "max_context": n["max_context"],
        "latency_class": n["latency_class"], "free_slots": n["free_slots"],
        "epoch": n["epoch"], "alive": alive, "probe_ms": probe_ms, "note": note,
    }


def _failed_row(n: dict, exc: Exception) -> dict:
    """An UPSERT-ready, alive=false row for a node whose probe crashed outright,
    built from its `fleet_nodes` config so the directory still tells the truth."""
    return {
        "node": n.get("node"), "endpoint": n.get("endpoint_url"), "slot_id": n.get("slot_id"),
        "gpu_model": None, "nvlink": n.get("nvlink_domain"),
        "vram_total": None, "vram_free": None, "util": None,
        "loaded_model": None, "served_model": n.get("served_model"),
        "max_context": n.get("max_context"), "latency_class": n.get("latency_class"),
        "free_slots": n.get("free_slots"), "epoch": n.get("epoch"),
        "alive": False, "probe_ms": None, "note": f"probe crashed: {exc}",
    }


def probe_each(nodes: list[dict], probe_fn=None, max_workers: int | None = None):
    """Probe every node concurrently and YIELD each row as its probe completes,
    so one slow/black-hole node can't serialize the tick and age the healthy
    nodes out of `live_slots`. A crashed probe is isolated into an alive=false
    row; it never sinks the others. Order follows completion, not input."""
    if not nodes:
        return
    fn = probe_fn or probe_node
    workers = max_workers or min(len(nodes), 16)
    with ThreadPoolExecutor(max_workers=workers) as ex:
        futs = {ex.submit(fn, n): n for n in nodes}
        for fut in as_completed(futs):
            try:
                yield fut.result()
            except Exception as exc:  # a crashed probe must not sink the others
                yield _failed_row(futs[fut], exc)


def probe_all(nodes: list[dict], probe_fn=None, max_workers: int | None = None) -> list[dict]:
    """Barrier form of `probe_each`: all rows, once every probe has resolved."""
    return list(probe_each(nodes, probe_fn, max_workers))


PRUNE = """
DELETE FROM gpu_slots
WHERE (node, slot_id) NOT IN (SELECT node, slot_id FROM fleet_nodes WHERE enabled)
"""


def tick(conn: psycopg.Connection) -> list[dict]:
    nodes = [dict(zip(COLS, r)) for r in conn.execute(FETCH).fetchall()]
    out = []
    # Probe concurrently; commit each node's row the moment its probe lands, so a
    # slow node never delays the heartbeat (heartbeat_ts) of the fast ones.
    for row in probe_each(nodes, probe_fn=probe_node):
        try:
            conn.execute(UPSERT, row)
            conn.commit()
        except Exception as exc:  # one bad row never stops the others
            conn.rollback()
            row = {**row, "alive": False, "note": f"upsert failed: {exc}"}
        out.append({"node": row["node"], "alive": row["alive"], "probe_ms": row["probe_ms"],
                    "vram_free_mib": row["vram_free"], "note": row["note"]})
    # Autonomous decommission: drop directory rows we no longer track (node
    # removed or disabled in fleet_nodes), so a retired node fully disappears.
    conn.execute(PRUNE)
    conn.commit()
    return out


def main() -> int:
    p = argparse.ArgumentParser(description="gpu-fleet heartbeat driver")
    p.add_argument("--db", default="dbname=gpu_fleet")
    p.add_argument("--interval", type=float, default=15.0, help="seconds; 0 = once")
    a = p.parse_args()
    with psycopg.connect(a.db, autocommit=False) as conn:
        while True:
            t0 = time.monotonic()
            res = tick(conn)
            live = sum(1 for r in res if r.get("alive"))
            print(json.dumps({"ts": int(time.time()), "live": live, "nodes": res}), flush=True)
            if not a.interval:
                return 0
            # Sleep the remainder of the interval, not a full interval on top of a
            # slow tick — keeps the per-node refresh cadence bounded by the TTL.
            time.sleep(max(0.0, a.interval - (time.monotonic() - t0)))


if __name__ == "__main__":
    raise SystemExit(main())
