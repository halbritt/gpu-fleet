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
import os
import socket
import time
from concurrent.futures import ThreadPoolExecutor, as_completed

import psycopg

from heartbeat import (
    UPSERT,
    decode_probe,
    discover_served_model,
    gpu_stats,
    ollama_ondemand_liveness,
)

# RFC 0002 Slice 3 Change B — the puller SKIPS a node whose per-node driver-lease is
# held-and-FRESH (a self-pusher owns it), and probes the rest. Freshness is decided
# SERVER-SIDE by the DB clock (now() >= lease_until), never the puller host's clock
# (BC4/C12) — so push and pull never both write a node (C9). With driven_by NULL /
# lease_until expired everywhere (today) this reduces to `WHERE enabled` = today's
# behavior, so the puller drives every node until a push sidecar is deployed.
FETCH = """
SELECT node, slot_id, endpoint_url, served_model, probe_model, latency_class,
       gpu_cmd, nvlink_domain, max_context, free_slots, epoch, min_load_vram_mib
FROM fleet_nodes
WHERE enabled AND (driven_by IS NULL OR now() >= lease_until)
ORDER BY node, slot_id
"""
COLS = ["node", "slot_id", "endpoint_url", "served_model", "probe_model",
        "latency_class", "gpu_cmd", "nvlink_domain", "max_context", "free_slots",
        "epoch", "min_load_vram_mib"]

# RFC 0002 Slice 2 — global puller-lease (peer-runnable driver; kills the SPOF). A CAS
# on the single fleet_meta row: the holder drives the tick and renews; a standby loses
# the CAS and idles. Column `holder` is identical in the DDL, this CAS, and the tests
# (BC5). Deadman TTL = PULLER_LEASE_TTL, pinned strictly below the 45s live window (BC3)
# so a killed holder's standby takes over and writes fresh heartbeats well before any
# live slot ages out. `now() >= lease_until` is server-side, so standby clock skew
# cannot mis-time the takeover (C12).
PULLER_LEASE_TTL = 15

PULLER_LEASE_CAS = """
UPDATE fleet_meta
   SET holder = %(me)s, lease_until = now() + make_interval(secs => %(ttl)s)
 WHERE id = 1
   AND (holder IS NULL OR now() >= lease_until OR holder = %(me)s)
RETURNING holder
"""


def puller_id() -> str:
    """Identity this driver writes into the puller-lease (host/pid). A lone puller wins
    the CAS trivially and renews each tick; a second puller idles instead of double-driving."""
    return f"puller/{socket.gethostname()}/{os.getpid()}"


def acquire_puller_lease(conn, holder: str, ttl: int = PULLER_LEASE_TTL) -> bool:
    """Try to hold (or renew) the global puller-lease. Returns True if THIS driver holds
    it for the next tick. The CAS is committed immediately so a standby on another host
    sees the takeover. Freshness/expiry is decided by the DB clock, never a host clock."""
    row = conn.execute(PULLER_LEASE_CAS, {"me": holder, "ttl": ttl}).fetchone()
    conn.commit()
    return row is not None

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
    if (n["probe_model"] or n["served_model"]) == "ollama-ondemand":
        # Load-aware liveness for the on-demand ollama MoE that shares its card
        # with marker. Evaluated BEFORE the decode path so the heartbeat never
        # forces a load (it decode-probes ONLY when the model is already resident).
        # served_model is the real tag consumers request.
        served = n["served_model"]
        alive, probe_ms, probe_err = ollama_ondemand_liveness(
            n["endpoint_url"], served, stats, gpu_err,
            n.get("min_load_vram_mib"), PROBE_TIMEOUT)
    elif (n["probe_model"] or n["served_model"]) in ("-", "none", "gpu-only"):
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
        # RFC 0002: the pull driver carries the MEASURED gpu_uuid (from nvidia-smi,
        # local or cross-host SSH) but leaves boot_epoch NULL — an HTTP/SSH probe has
        # no boot identity to stamp, so the ratchet stays inert for pull-driven rows.
        "gpu_uuid": stats.get("gpu_uuid"), "boot_epoch": None,
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
        # NOT alive -> the UPSERT zeroes the streak / re-quarantines; a NULL uuid here
        # COALESCE-preserves any known identity, and boot_epoch stays inert (pull).
        "gpu_uuid": None, "boot_epoch": None,
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
  AND heartbeat_ts <= now() - interval '45 seconds'
"""
# RFC 0002 Slice 1 Change C (C3-PRUNE): delete only rows that are BOTH absent from
# enabled fleet_nodes AND already stale. A self-pushed node with no fleet_nodes row
# keeps its row FRESH, so it is never pruned (that is what lets "registration = first
# heartbeat" coexist with the pull driver's housekeeping); a genuinely removed/disabled
# node goes stale first, then is pruned. WITHOUT the staleness term the PRUNE would
# delete a live self-pushed node on the very next tick.


def tick(conn: psycopg.Connection, *, holder: str | None = None,
         lease_ttl: int = PULLER_LEASE_TTL, acquire_fn=acquire_puller_lease) -> list[dict]:
    # RFC 0002 Slice 2: when run as a peer-runnable driver (holder set), only the
    # puller that HOLDS the global fleet_meta lease drives this tick; a standby that
    # loses the CAS idles, so two pullers never double-write a node. `holder=None`
    # (a direct/test call) skips the lease and drives unconditionally = today's behavior.
    if holder is not None and not acquire_fn(conn, holder, lease_ttl):
        return []
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
    p.add_argument("--no-puller-lease", action="store_true",
                   help="drive every tick without the peer-runnable puller-lease "
                        "(single-driver mode; the lease is the SPOF-killer, on by default)")
    a = p.parse_args()
    # RFC 0002 Slice 2: peer-runnable by default — hold the global puller-lease to drive,
    # idle if a peer holds it. A lone driver wins the CAS trivially (today's behavior).
    holder = None if a.no_puller_lease else puller_id()
    with psycopg.connect(a.db, autocommit=False) as conn:
        while True:
            t0 = time.monotonic()
            try:
                res = tick(conn, holder=holder)
            except Exception as exc:
                # A tick-level failure (a transient DB error, or FETCH meeting a
                # schema mid-migration) must NOT crash this always-on driver: under
                # systemd Restart=always a crash-loop commits no UPSERT, so EVERY
                # slot goes stale and the whole fleet ages out of live_slots in 45s.
                # Roll back any aborted txn, log, and retry on the next tick instead.
                # (A genuinely dead connection makes rollback raise -> we crash ->
                # systemd restarts and re-establishes the connection, which is right.)
                conn.rollback()
                print(json.dumps({"ts": int(time.time()), "error": f"tick failed: {exc}"}),
                      flush=True)
                res = []
            else:
                live = sum(1 for r in res if r.get("alive"))
                print(json.dumps({"ts": int(time.time()), "live": live, "nodes": res}),
                      flush=True)
            if not a.interval:
                return 0
            # Sleep the remainder of the interval, not a full interval on top of a
            # slow tick — keeps the per-node refresh cadence bounded by the TTL.
            time.sleep(max(0.0, a.interval - (time.monotonic() - t0)))


if __name__ == "__main__":
    raise SystemExit(main())
