#!/usr/bin/env python3
"""gpu-fleet heartbeat driver: refresh EVERY declared node, every tick, forever.

Reads the desired fleet from `fleet_nodes` on each iteration (so adding a node is
a pure INSERT -- no restart needed), probes its GPU and model, and UPSERTs
gpu_slots. A node that fails its probe is written `alive=false` and ages out of
`live_slots`; a node that reappears comes back automatically. While a consumer
lease is active, GPU reachability replaces the contending decode probe; normal
decode verification resumes after release. One node's failure (timeout, ssh
down) never blocks the others. Built to run under a Restart=always systemd-user
service so the registry stays live with zero human intervention.
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
    absent_capacity_fields,
    capacity_telemetry,
    decode_probe,
    discover_served_model,
    gpu_stats,
    ollama_ondemand_liveness,
    write_capacity,
)

# RFC 0002 Slice 3 Change B — the puller SKIPS a node whose per-node driver-lease is
# held-and-FRESH (a self-pusher owns it), and probes the rest. Freshness is decided
# SERVER-SIDE by the DB clock (now() >= lease_until), never the puller host's clock
# (BC4/C12) — so push and pull never both write a node (C9). With driven_by NULL /
# lease_until expired everywhere (today) this reduces to `WHERE enabled` = today's
# behavior, so the puller drives every node until a push sidecar is deployed.
FETCH = """
SELECT node, slot_id, endpoint_url, served_model, probe_model, latency_class,
       gpu_cmd, nvlink_domain, max_context, free_slots, epoch, min_load_vram_mib,
       COALESCE((
           SELECT gpu_slots.lease_id IS NOT NULL
              AND now() < gpu_slots.lease_expires
             FROM gpu_slots
            WHERE (gpu_slots.node, gpu_slots.endpoint_url, gpu_slots.slot_id)
                = (fleet_nodes.node, fleet_nodes.endpoint_url, fleet_nodes.slot_id)
         ), false) AS lease_active
FROM fleet_nodes
WHERE enabled AND (driven_by IS NULL OR now() >= lease_until)
ORDER BY node, slot_id
"""
COLS = ["node", "slot_id", "endpoint_url", "served_model", "probe_model",
        "latency_class", "gpu_cmd", "nvlink_domain", "max_context", "free_slots",
        "epoch", "min_load_vram_mib", "lease_active"]

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
    if n.get("lease_active"):
        # Diagnostic decode would contend with the holder on a single-slot server.
        # This weaker positive check cannot promote the slot; UPSERT demotes it to
        # one verified decode away from routable until the lease is released.
        served = n["served_model"]
        alive = gpu_err is None and stats.get("gpu_model") is not None
        probe_ms = None
        probe_err = "lease active: decode probe suppressed" if alive else None
    elif (n["probe_model"] or n["served_model"]) == "ollama-ondemand":
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
    # RFC 0005 (BC4): the puller computes the SAME companion telemetry it can reach for a
    # pulled node and carries it in the row dict; pull_write issues the savepoint-guarded
    # CAPACITY_UPSERT (closing the gap where pull-mode slots — including peecee — silently
    # COALESCE-fell back to legacy vram_free). probe_node stays pure I/O (no DB): the
    # telemetry is computed from the already-measured stats + injected adapters, never a
    # GPU/exporter read of its own here.
    cap = capacity_telemetry(served, stats, probe_ms)
    return {
        "node": n["node"], "endpoint": n["endpoint_url"], "slot_id": n["slot_id"],
        "gpu_model": stats.get("gpu_model"), "nvlink": n["nvlink_domain"],
        "vram_total": stats.get("vram_total_mib"), "vram_free": stats.get("vram_free_mib"),
        "util": stats.get("gpu_util_pct"),
        "loaded_model": served if alive else None,
        "served_model": served, "max_context": n["max_context"],
        "latency_class": n["latency_class"], "free_slots": n["free_slots"],
        "epoch": n["epoch"], "alive": alive, "probe_ms": probe_ms, "note": note,
        "probe_verified": not n.get("lease_active", False),
        # RFC 0002: the pull driver carries the MEASURED gpu_uuid (from nvidia-smi,
        # local or cross-host SSH) but leaves boot_epoch NULL — an HTTP/SSH probe has
        # no boot identity to stamp, so the ratchet stays inert for pull-driven rows.
        # RFC 0005 (F-KEYS): mig_mode/ecc_mode carried so the shared UPSERT never KeyErrors.
        "gpu_uuid": stats.get("gpu_uuid"), "boot_epoch": None,
        "mig_mode": stats.get("mig_mode"), "ecc_mode": stats.get("ecc_mode"),
        **cap,
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
        "probe_verified": True,
        # NOT alive -> the UPSERT zeroes the streak / re-quarantines; a NULL uuid here
        # COALESCE-preserves any known identity, and boot_epoch stays inert (pull).
        # RFC 0005 (F-KEYS): mig_mode/ecc_mode None (a crashed probe knows no capability;
        # NULL IS DISTINCT FROM a prior NULL is false -> no spurious epoch bump). The
        # absent capacity fields keep CAPACITY_UPSERT well-formed (a benign 'absent' row).
        "gpu_uuid": None, "boot_epoch": None, "mig_mode": None, "ecc_mode": None,
        **absent_capacity_fields(),
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


# RFC 0002 Slice 3 (single-writer, C9) — the puller RE-VALIDATES the per-node
# driver-lease at WRITE time, not only at FETCH time. The FETCH is a snapshot; the
# concurrent probe phase that follows it takes seconds, and a self-pusher can acquire
# the node's lease in that window (after the puller fetched it as eligible, before the
# puller writes its probed row). Skipping that re-check is the fetch->probe->write race:
# both writers would land a row for the same node in the contending tick. This guard
# closes it. It locks the fleet_nodes row (FOR UPDATE) and re-tests the lease, so the
# decision serializes against the self-push NODE_LEASE_CAS (an UPDATE of the same row):
# if a FRESH push-lease now owns the node, the puller writes ZERO rows for it this tick
# and the self-pusher is the sole writer. Freshness is the DB clock (now() < lease_until),
# never the puller host's (BC4/C12). A node with NO fleet_nodes row is never in the
# puller's FETCH, so this guard never runs for it (BC1 self-push registration is untouched).
PULL_WRITE_GUARD = """
SELECT 1 FROM fleet_nodes
 WHERE node = %(node)s AND slot_id = %(slot_id)s
   AND driven_by IS NOT NULL
   AND now() < lease_until
 FOR UPDATE
"""


def pull_write(conn: psycopg.Connection, row: dict) -> bool:
    """Write one probed PULL row through the per-node single-writer guard, in ONE
    transaction. Returns True if the row was written, or False if a fresh push-lease
    owns the node now (the puller YIELDS — the self-pusher is the sole writer for that
    node this tick, C9). The guard SELECT ... FOR UPDATE and the UPSERT commit together,
    so the lease re-check and the write are atomic and serialize against the self-push
    NODE_LEASE_CAS. This is the write-time half of the single-writer guarantee whose
    FETCH-time half is the FETCH lease predicate."""
    if conn.execute(PULL_WRITE_GUARD,
                    {"node": row["node"], "slot_id": row["slot_id"]}).fetchone():
        conn.rollback()      # a self-pusher leased this node since the FETCH -> yield
        return False
    conn.execute(UPSERT, row)
    # RFC 0005 (BC4): write the companion capacity row for the pulled node, under the same
    # savepoint guard (C3), AFTER the liveness UPSERT and BEFORE the commit — so pull-mode
    # slots (including peecee) get gpu_slots_capacity rows, and a companion failure
    # ROLLBACK TO SAVEPOINTs without aborting the liveness write the puller already did.
    write_capacity(conn, row)
    conn.commit()
    return True


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
    # Probe concurrently; write each node's row the moment its probe lands (so a slow
    # node never delays the heartbeat of the fast ones), through the single-writer guard
    # so a node a self-pusher leased DURING this probe phase is yielded, not double-written.
    for row in probe_each(nodes, probe_fn=probe_node):
        skipped = False
        try:
            skipped = not pull_write(conn, row)   # C9: yield a now-push-held node
        except Exception as exc:  # one bad row never stops the others
            conn.rollback()
            row = {**row, "alive": False, "note": f"upsert failed: {exc}"}
        if skipped:
            out.append({"node": row["node"], "alive": None, "probe_ms": None,
                        "vram_free_mib": None,
                        "note": "skipped: self-push holds the node (single-writer C9)"})
        else:
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
