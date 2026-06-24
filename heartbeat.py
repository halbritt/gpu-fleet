#!/usr/bin/env python3
"""gpu-fleet heartbeat: publish one node's GPU slot into the registry.

Reads local GPU stats via nvidia-smi (or a remote `--gpu-cmd` like
`ssh peecee nvidia-smi`), runs a real 2-token decode-probe against the node's
OpenAI-compatible endpoint, and UPSERTs the `gpu_slots` row. Pure stdlib +
psycopg. Run as a node's own loop, or proximal-driven for a node that can't yet
self-heartbeat (e.g. the Windows desktop until it runs its own).

Liveness is the decode-probe, not /health: a wedged model loop serves 200s but
fails to decode. `alive=false` is written on probe failure so the directory
tells the truth.
"""

from __future__ import annotations

import argparse
import json
import os
import shlex
import socket
import subprocess
import time
import urllib.error
import urllib.request

import psycopg

# uuid LAST so the existing 5-field parse stays index-stable; it is the MEASURED GPU
# identity used by the RFC-0002 quarantine ratchet (BC7: a hot-swapped card differs).
GPU_QUERY = "--query-gpu=name,memory.total,memory.used,memory.free,utilization.gpu,uuid"
GPU_FORMAT = "--format=csv,noheader,nounits"

# RFC 0002 — quarantine->graduate threshold (Q1). A slot graduates
# unverified -> probationary -> routable after this many consecutive DB-stamped
# passing probes (the registration probe counts as the first). Interpolated ONCE into
# the UPSERT constant at import (a trusted int literal, not user input), so the row-dict
# passed to conn.execute is unchanged.
GRADUATION_STREAK = 3

# RFC 0002 Slice 3 — per-node driver-lease TTL (push opt-in). < 45s (the live window),
# so a dead pusher's lease lapses and the puller resumes within one interval of lapse,
# before the slot ages out. Evaluated server-side (DB now()), never a node clock.
NODE_LEASE_TTL = 30

UPSERT = """
INSERT INTO gpu_slots (
    node, endpoint_url, slot_id, gpu_model, nvlink_domain, vram_total_mib,
    vram_free_mib, gpu_util_pct, loaded_model, served_model, max_context,
    latency_class, free_slots, epoch, alive, probe_ms, note,
    status, probe_streak, gpu_uuid, boot_epoch, heartbeat_ts)
VALUES (
    %(node)s, %(endpoint)s, %(slot_id)s, %(gpu_model)s, %(nvlink)s, %(vram_total)s,
    %(vram_free)s, %(util)s, %(loaded_model)s, %(served_model)s, %(max_context)s,
    %(latency_class)s, %(free_slots)s, %(epoch)s, %(alive)s, %(probe_ms)s, %(note)s,
    -- RFC 0002 Slice-1 Change B: a brand-new self-reporting row appears 'unverified'
    -- (zero-touch register), with probe_streak seeded 1 on a passing first probe.
    'unverified', CASE WHEN %(alive)s THEN 1 ELSE 0 END, %(gpu_uuid)s, %(boot_epoch)s,
    now())
ON CONFLICT (node, endpoint_url, slot_id) DO UPDATE SET
    gpu_model=EXCLUDED.gpu_model, nvlink_domain=EXCLUDED.nvlink_domain,
    vram_total_mib=EXCLUDED.vram_total_mib, vram_free_mib=EXCLUDED.vram_free_mib,
    gpu_util_pct=EXCLUDED.gpu_util_pct, loaded_model=EXCLUDED.loaded_model,
    served_model=EXCLUDED.served_model, max_context=EXCLUDED.max_context,
    latency_class=EXCLUDED.latency_class, free_slots=EXCLUDED.free_slots,
    -- RFC 0003: PRESERVE the existing epoch and bump it by 1 only when a
    -- ROUTING-RELEVANT field changed, instead of clobbering it with the static
    -- config value (%(epoch)s) every tick. The CASE compares the OLD row
    -- (gpu_slots.*) against the incoming tick (EXCLUDED.*); IS DISTINCT FROM is
    -- NULL-safe. vram_free_mib / gpu_util_pct are deliberately EXCLUDED from the
    -- diff so expected VRAM/util churn never bumps epoch (no re-pick storms).
    -- endpoint_url is part of the PK, so an endpoint change is a new INSERT row
    -- (seeding epoch), never an in-place conflict (BC2 handles held leases on a
    -- turned-over endpoint registry-side). A brand-new INSERT still seeds epoch
    -- from %(epoch)s via the VALUES list above; only this conflict path changed.
    -- RFC 0002 keeps `epoch` BYTE-UNCHANGED (C7): boot_epoch below is a SEPARATE column.
    epoch = gpu_slots.epoch + CASE
        WHEN gpu_slots.served_model   IS DISTINCT FROM EXCLUDED.served_model
          OR gpu_slots.nvlink_domain  IS DISTINCT FROM EXCLUDED.nvlink_domain
          OR gpu_slots.max_context    IS DISTINCT FROM EXCLUDED.max_context
        THEN 1 ELSE 0 END,
    -- RFC 0002 BC2: a NULL-epoch (pull) writer must NEVER erase a push-stamped
    -- ratchet, and a NULL (pull) uuid report must NEVER erase a known identity.
    boot_epoch = COALESCE(EXCLUDED.boot_epoch, gpu_slots.boot_epoch),
    gpu_uuid   = COALESCE(EXCLUDED.gpu_uuid, gpu_slots.gpu_uuid),
    -- RFC 0002 BC7 + C10: reset the streak on a failed probe OR a GPU IDENTITY
    -- CHANGE (both uuids known and different), so a hot-swapped alive card cannot
    -- inherit the prior streak; trust carries forward only on a matching/unknown uuid.
    probe_streak = CASE
        WHEN NOT EXCLUDED.alive THEN 0
        WHEN gpu_slots.gpu_uuid IS NOT NULL AND EXCLUDED.gpu_uuid IS NOT NULL
             AND gpu_slots.gpu_uuid <> EXCLUDED.gpu_uuid THEN 1
        ELSE gpu_slots.probe_streak + 1 END,
    status = CASE
        WHEN NOT EXCLUDED.alive THEN 'unverified'
        WHEN gpu_slots.gpu_uuid IS NOT NULL AND EXCLUDED.gpu_uuid IS NOT NULL
             AND gpu_slots.gpu_uuid <> EXCLUDED.gpu_uuid THEN 'unverified'
        WHEN gpu_slots.status = 'routable' THEN 'routable'
        WHEN gpu_slots.probe_streak + 1 >= {GRADUATION_STREAK} THEN 'routable'
        ELSE 'probationary' END,
    alive=EXCLUDED.alive, probe_ms=EXCLUDED.probe_ms,
    note=EXCLUDED.note, heartbeat_ts=now()
-- RFC 0002 BC6 ratchet: a write is admitted iff it carries no boot identity (pull),
-- the stored row has none yet (pull-only / pre-rollout), or its boot_epoch is STRICTLY
-- greater. An equal-or-lower replay matches the WHERE as FALSE -> no field moves and
-- heartbeat_ts is NOT re-stamped. STRICT '>' (never '>=') is what closes the
-- equal-epoch replay hole; do NOT weaken it.
WHERE EXCLUDED.boot_epoch IS NULL
   OR gpu_slots.boot_epoch IS NULL
   OR EXCLUDED.boot_epoch > gpu_slots.boot_epoch
""".format(GRADUATION_STREAK=GRADUATION_STREAK)

# RFC 0002 Slice 3 Change A — best-effort per-node driver-lease CAS (push opt-in).
# A self-pushing node attempts to hold its fleet_nodes lease as a COORDINATION SIGNAL
# only; the result is IGNORED for the purpose of writing the slot (the UPSERT runs
# UNCONDITIONALLY — registration = first heartbeat, BC1). For a node absent from
# fleet_nodes the CAS simply matches zero rows; the node still registers, and the
# directory-driven puller never probes it, so no contention exists. Freshness is the
# DB clock (now() >= lease_until), never the pusher's host clock (BC4/C12).
NODE_LEASE_CAS = """
UPDATE fleet_nodes
   SET driven_by = %(me)s, lease_until = now() + make_interval(secs => %(node_ttl)s)
 WHERE node = %(node)s AND slot_id = %(slot_id)s
   AND (driven_by IS NULL OR driven_by = %(me)s OR now() >= lease_until)
RETURNING node
"""

# Strictly-monotonic-per-write boot token (the RFC's Pillar-5 boot_id+seq collapsed to
# one scalar). Guarded to never regress within a process, so two writes ALWAYS strictly
# increase -> the ratchet predicate is a STRICT '>'. Across a reboot the wall clock has
# advanced; across a heartbeat-process restart within one boot the wall clock is global
# so it still advances. Its ONLY effect is to refuse THIS node's own stale replays; it
# never decides liveness or gates routing (C12), and a writer can only write its own row.
_last_epoch = 0


def next_boot_epoch() -> int:
    global _last_epoch
    _last_epoch = max(_last_epoch + 1, time.time_ns())
    return _last_epoch


def _push_holder() -> str:
    """Identity a self-pushing node stamps into its per-node driver-lease (observability
    + CAS self-match). host/pid is enough to distinguish a pusher from the puller."""
    return f"push/{socket.gethostname()}/{os.getpid()}"


def gpu_stats(gpu_cmd: str, timeout: float = 20) -> dict | None:
    """Run nvidia-smi (local or via ssh) and parse the first GPU's stats."""
    argv = shlex.split(gpu_cmd) + [GPU_QUERY, GPU_FORMAT]
    try:
        out = subprocess.run(argv, capture_output=True, text=True, timeout=timeout, check=True)
    except (subprocess.SubprocessError, OSError) as exc:
        return {"_error": f"gpu_stats: {exc}"}
    line = out.stdout.strip().splitlines()
    if not line:
        return {"_error": "gpu_stats: empty nvidia-smi output"}
    parts = [x.strip() for x in line[0].split(",")]
    name, total, used, free, util = parts[:5]
    # uuid is appended (RFC 0002 measured identity); tolerate an older nvidia-smi /
    # gpu_cmd that does not emit it (then identity is unknown -> NULL, ratchet inert).
    uuid = parts[5] if len(parts) > 5 else None
    return {
        "gpu_model": name,
        "vram_total_mib": int(total),
        "vram_free_mib": int(free),
        "gpu_util_pct": int(float(util)) if util not in ("[N/A]", "") else None,
        "gpu_uuid": uuid or None,
    }


def decode_probe(endpoint: str, model: str, timeout: float) -> tuple[bool, int | None, str | None]:
    """Real liveness: a 1-token chat completion. alive iff a choice comes back."""
    url = endpoint.rstrip("/") + "/chat/completions"
    body = json.dumps(
        {"model": model, "messages": [{"role": "user", "content": "ping"}],
         "max_tokens": 1, "temperature": 0}
    ).encode()
    req = urllib.request.Request(url, data=body, headers={"Content-Type": "application/json"})
    t0 = time.monotonic()
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            d = json.load(r)
    except (urllib.error.URLError, OSError, json.JSONDecodeError, TimeoutError) as exc:
        return False, None, f"probe: {exc}"
    ms = int((time.monotonic() - t0) * 1000)
    return bool(d.get("choices")), ms, None


def ollama_resident(endpoint: str, model: str, timeout: float) -> bool:
    """Is `model` currently loaded in ollama's VRAM? (GET <base sans /v1>/api/ps).

    ollama's /api/ps returns {"models":[{"name": ...}, ...]} for what is resident
    right now ({"models":[]} when nothing is). This is a pure read — it does NOT
    load anything — so it is safe to call on the shared card every tick. Used by
    the 'ollama-ondemand' liveness mode to tell WARM (resident) from COLD (a load
    would be needed) without forcing that load. On any error, treat as not
    resident (the caller then falls back to the VRAM-headroom check)."""
    base = endpoint.rstrip("/")
    if base.endswith("/v1"):
        base = base[:-3]
    url = base.rstrip("/") + "/api/ps"
    try:
        with urllib.request.urlopen(url, timeout=timeout) as r:
            models = json.load(r).get("models") or []
    except (urllib.error.URLError, OSError, json.JSONDecodeError, TimeoutError):
        return False
    return any(m.get("name") == model for m in models)


# Default free-VRAM (MiB) required to call an on-demand ollama model "loadable"
# when fleet_nodes.min_load_vram_mib is NULL. This is the free VRAM needed to LOAD
# the model (the peecee MoE's weights are ~21.85 GiB and it loads, with a small CPU
# spill, whenever the card is otherwise idle — measured idle free 21690-22095 MiB),
# NOT its total resident footprint. A per-node column is the right knob for a
# model-specific footprint; a card-fraction heuristic (e.g. 95% of vram_total)
# misfires on a card with irreducible desktop/driver overhead (peecee never has
# 23 GiB free), so the fallback is a flat default, not a fraction of the card.
DEFAULT_MIN_LOAD_VRAM_MIB = 21000


def ollama_ondemand_liveness(
    endpoint: str,
    model: str,
    stats: dict,
    gpu_err: str | None,
    min_load_vram_mib: int | None,
    timeout: float,
    *,
    resident_fn=None,
    decode_fn=None,
) -> tuple[bool, int | None, str | None]:
    """Load-aware liveness for an on-demand ollama model that time-shares its GPU
    (the peecee MoE vs. marker). Returns (alive, probe_ms, note).

    Three honest states, mapped onto the existing schema with no consumer change:
      - WARM  (model already resident): decode-probe to confirm warmth (this does
               NOT force a load — it is already loaded) -> alive, probe_ms set.
      - COLD/LOADABLE (not resident, but free VRAM >= threshold): the card is free
               enough to load on demand -> alive, probe_ms=None. We do NOT decode-
               probe (that would force the load the heartbeat must never trigger).
      - NOT LOADABLE (not resident, free VRAM < threshold): marker owns the card,
               so a real request could not load the model -> alive=False, so it
               ages out of live_slots and di never routes a request it can't serve.

    GPU unreachable -> alive=False (as for every other slot). `min_load_vram_mib`
    falls back to a flat DEFAULT_MIN_LOAD_VRAM_MIB when NULL (the threshold is a
    model-specific load footprint, so the per-node column is the right knob; a
    fraction-of-card default misfires when the card has desktop/driver overhead).

    `resident_fn`/`decode_fn` default to the module-level `ollama_resident` /
    `decode_probe`, resolved at call time so a test can monkeypatch them on the
    module (and so probe_node's plain call honours such a patch)."""
    resident_fn = resident_fn or ollama_resident
    decode_fn = decode_fn or decode_probe
    if gpu_err is not None or stats.get("gpu_model") is None:
        return False, None, None  # gpu_err is surfaced by the caller's note join

    threshold = min_load_vram_mib
    if threshold is None:
        threshold = DEFAULT_MIN_LOAD_VRAM_MIB

    if resident_fn(endpoint, model, timeout):
        alive, probe_ms, probe_err = decode_fn(endpoint, model, timeout)
        note = "resident" if alive else (probe_err or "resident but probe failed")
        return alive, probe_ms, note

    free = stats.get("vram_free_mib")
    if free is not None and free >= threshold:
        return True, None, f"loadable: free={free}MiB"
    return False, None, (
        f"not loadable: marker owns card (free={free}MiB < {threshold})"
    )


# BC1 (RFC 0003) — sticky discovery. The last served_model SUCCESSFULLY resolved for
# an endpoint, keyed by endpoint_url. On a TRANSIENT /models failure discover_served_model
# returns this cached value instead of flapping to the (often differing) static
# `--served-model` tag. A flap would make the heartbeat write a distinct served_model,
# bump epoch via the UPSERT CASE, fence a healthy holder's renew to zero rows, and force
# a needless re-pick on the next good tick — the exact churn RFC 0003's gate excludes.
# Keyed by endpoint so heartbeat_all's per-node probe threads stay independent (plain
# dict get/set on distinct keys is atomic under the GIL; no lock needed).
_DISCOVERED: dict[str, str] = {}


def reset_discovery_cache() -> None:
    """Clear the sticky-discovery cache. A test seam (so cross-test state never leaks);
    also lets a caller drop stale entries if an endpoint is decommissioned."""
    _DISCOVERED.clear()


def discover_served_model(endpoint: str, fallback: str | None, timeout: float = 6.0) -> str | None:
    """Self-correct the served model from the endpoint.

    If the endpoint serves exactly ONE model (the llama-server case), report it —
    so a node swapped from ollama to llama-server auto-updates with no reconfig.
    If it lists many (the ollama case), keep the configured tag and don't disrupt
    by probe-loading some arbitrary big model.

    BC1 sticky discovery (RFC 0003): a TRANSIENT /models failure MUST NOT flap
    served_model. Once we have successfully resolved an endpoint's served_model
    (single-model id, or the static tag in the multi-model case) we cache it; on a
    later transient failure we return that cached value rather than the differing
    static `fallback`, so a network blip cannot bump epoch and evict a healthy lease.
    The cache is updated only on a SUCCESSFUL /models read, so a genuine capability
    change (a real, non-transient new answer) still flows through and is allowed to
    bump epoch. Stickiness only PROTECTS a value already learned: before any success
    a transient failure still degrades to the static `fallback` (today's behavior).
    """
    url = endpoint.rstrip("/") + "/models"
    try:
        with urllib.request.urlopen(url, timeout=timeout) as r:
            ids = [m.get("id") for m in json.load(r).get("data", []) if m.get("id")]
    except (urllib.error.URLError, OSError, json.JSONDecodeError, TimeoutError):
        # Transient failure: stay sticky on the last good resolution for this endpoint;
        # only fall back to the static tag if we have never resolved one.
        return _DISCOVERED.get(endpoint, fallback)
    resolved = ids[0] if len(ids) == 1 else fallback
    if resolved is not None:
        _DISCOVERED[endpoint] = resolved
    return resolved


def heartbeat_once(conn: psycopg.Connection, args) -> dict:
    stats = gpu_stats(args.gpu_cmd) or {}
    gpu_err = stats.pop("_error", None)
    probe_err = None
    if (args.probe_model or args.served_model) == "ollama-ondemand":
        # Load-aware liveness for the on-demand ollama MoE that shares its card
        # with marker. Evaluated BEFORE the decode path so we never force a load
        # of a model that isn't already resident. served_model is the real tag.
        served = args.served_model
        alive, probe_ms, note0 = ollama_ondemand_liveness(
            args.endpoint, served, stats, gpu_err,
            getattr(args, "min_load_vram_mib", None), args.timeout)
        probe_err = note0
    elif (args.probe_model or args.served_model) in ("-", "none", "gpu-only"):
        # Non-LLM capability (e.g. marker): liveness is GPU reachability, not a
        # decode-probe (which would needlessly load a model / fight a running job).
        served = args.served_model
        alive, probe_ms, probe_err = (gpu_err is None and stats.get("gpu_model") is not None), None, None
    else:
        served = discover_served_model(args.endpoint, args.served_model)
        alive, probe_ms, probe_err = decode_probe(args.endpoint, served or args.probe_model, args.timeout)
    note = "; ".join(x for x in (gpu_err, probe_err) if x) or None
    # RFC 0002: only the PUSH / --node-self path stamps a boot_epoch (it has a boot
    # identity); a pull/proximal-driven write leaves it NULL (an HTTP probe carries no
    # boot identity, so the puller has nothing truthful to stamp -> ratchet inert).
    push = getattr(args, "push", False)
    if push:
        # Slice 3 Change A: a NON-GATING per-node lease CAS (coordination signal only).
        # A failure (no fleet_nodes row, pre-migration schema) must NEVER stop the
        # registering UPSERT, so swallow it and reset the txn before writing the slot.
        try:
            conn.execute(NODE_LEASE_CAS, {
                "me": _push_holder(), "node": args.node,
                "slot_id": args.slot_id, "node_ttl": NODE_LEASE_TTL})
        except Exception:
            conn.rollback()
    row = {
        "node": args.node, "endpoint": args.endpoint, "slot_id": args.slot_id,
        "gpu_model": stats.get("gpu_model"), "nvlink": args.nvlink_domain,
        "vram_total": stats.get("vram_total_mib"), "vram_free": stats.get("vram_free_mib"),
        "util": stats.get("gpu_util_pct"),
        "loaded_model": served if alive else None,
        "served_model": served, "max_context": args.max_context,
        "latency_class": args.latency_class, "free_slots": args.free_slots,
        "epoch": args.epoch, "alive": alive, "probe_ms": probe_ms, "note": note,
        "gpu_uuid": stats.get("gpu_uuid"),
        "boot_epoch": next_boot_epoch() if push else None,
    }
    conn.execute(UPSERT, row)
    conn.commit()
    return {"node": args.node, "alive": alive, "probe_ms": probe_ms,
            "vram_free_mib": stats.get("vram_free_mib"), "note": note}


def main() -> int:
    p = argparse.ArgumentParser(description="gpu-fleet node heartbeat")
    p.add_argument("--node", required=True)
    p.add_argument("--endpoint", required=True, help="OpenAI-compatible base URL")
    p.add_argument("--served-model", required=True, help="model tag consumers should request")
    p.add_argument("--probe-model", help="model to decode-probe (default: --served-model)")
    p.add_argument("--latency-class", choices=("interactive", "batch"), default="batch")
    p.add_argument("--gpu-cmd", default="nvidia-smi",
                   help="how to run nvidia-smi, e.g. 'ssh -o BatchMode=yes peecee nvidia-smi'")
    p.add_argument("--nvlink-domain", default=None)
    p.add_argument("--max-context", type=int, default=None)
    p.add_argument("--free-slots", type=int, default=1)
    p.add_argument("--slot-id", type=int, default=0)
    p.add_argument("--min-load-vram-mib", type=int, default=None,
                   help="for probe_model=ollama-ondemand: free VRAM needed to call "
                        "the model loadable (default: 23000 or 95%% of total)")
    p.add_argument("--epoch", type=int, default=0)
    p.add_argument("--push", action="store_true",
                   help="RFC 0002 push mode (trusted node self-reporting): stamp a "
                        "monotonic boot_epoch and best-effort hold the per-node "
                        "driver-lease. Off => pull/proximal-driven write (boot_epoch NULL)")
    p.add_argument("--timeout", type=float, default=30.0)
    p.add_argument("--db", default="dbname=gpu_fleet")
    p.add_argument("--interval", type=float, default=0,
                   help="loop every N seconds; 0 = run once")
    args = p.parse_args()
    args.probe_model = args.probe_model or args.served_model

    with psycopg.connect(args.db, autocommit=False) as conn:
        while True:
            result = heartbeat_once(conn, args)
            print(json.dumps(result))
            if not args.interval:
                return 0
            time.sleep(args.interval)


if __name__ == "__main__":
    raise SystemExit(main())
