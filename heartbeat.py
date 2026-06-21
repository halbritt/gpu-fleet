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
import shlex
import subprocess
import time
import urllib.error
import urllib.request

import psycopg

GPU_QUERY = "--query-gpu=name,memory.total,memory.used,memory.free,utilization.gpu"
GPU_FORMAT = "--format=csv,noheader,nounits"

UPSERT = """
INSERT INTO gpu_slots (
    node, endpoint_url, slot_id, gpu_model, nvlink_domain, vram_total_mib,
    vram_free_mib, gpu_util_pct, loaded_model, served_model, max_context,
    latency_class, free_slots, epoch, alive, probe_ms, note, heartbeat_ts)
VALUES (
    %(node)s, %(endpoint)s, %(slot_id)s, %(gpu_model)s, %(nvlink)s, %(vram_total)s,
    %(vram_free)s, %(util)s, %(loaded_model)s, %(served_model)s, %(max_context)s,
    %(latency_class)s, %(free_slots)s, %(epoch)s, %(alive)s, %(probe_ms)s, %(note)s, now())
ON CONFLICT (node, endpoint_url, slot_id) DO UPDATE SET
    gpu_model=EXCLUDED.gpu_model, nvlink_domain=EXCLUDED.nvlink_domain,
    vram_total_mib=EXCLUDED.vram_total_mib, vram_free_mib=EXCLUDED.vram_free_mib,
    gpu_util_pct=EXCLUDED.gpu_util_pct, loaded_model=EXCLUDED.loaded_model,
    served_model=EXCLUDED.served_model, max_context=EXCLUDED.max_context,
    latency_class=EXCLUDED.latency_class, free_slots=EXCLUDED.free_slots,
    epoch=EXCLUDED.epoch, alive=EXCLUDED.alive, probe_ms=EXCLUDED.probe_ms,
    note=EXCLUDED.note, heartbeat_ts=now()
"""


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
    name, total, used, free, util = (x.strip() for x in line[0].split(","))
    return {
        "gpu_model": name,
        "vram_total_mib": int(total),
        "vram_free_mib": int(free),
        "gpu_util_pct": int(float(util)) if util not in ("[N/A]", "") else None,
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


def discover_served_model(endpoint: str, fallback: str | None, timeout: float = 6.0) -> str | None:
    """Self-correct the served model from the endpoint.

    If the endpoint serves exactly ONE model (the llama-server case), report it —
    so a node swapped from ollama to llama-server auto-updates with no reconfig.
    If it lists many (the ollama case), keep the configured tag and don't disrupt
    by probe-loading some arbitrary big model.
    """
    url = endpoint.rstrip("/") + "/models"
    try:
        with urllib.request.urlopen(url, timeout=timeout) as r:
            ids = [m.get("id") for m in json.load(r).get("data", []) if m.get("id")]
    except (urllib.error.URLError, OSError, json.JSONDecodeError, TimeoutError):
        return fallback
    return ids[0] if len(ids) == 1 else fallback


def heartbeat_once(conn: psycopg.Connection, args) -> dict:
    stats = gpu_stats(args.gpu_cmd) or {}
    gpu_err = stats.pop("_error", None)
    if (args.probe_model or args.served_model) in ("-", "none", "gpu-only"):
        # Non-LLM capability (e.g. marker): liveness is GPU reachability, not a
        # decode-probe (which would needlessly load a model / fight a running job).
        served = args.served_model
        alive, probe_ms, probe_err = (gpu_err is None and stats.get("gpu_model") is not None), None, None
    else:
        served = discover_served_model(args.endpoint, args.served_model)
        alive, probe_ms, probe_err = decode_probe(args.endpoint, served or args.probe_model, args.timeout)
    note = "; ".join(x for x in (gpu_err, probe_err) if x) or None
    row = {
        "node": args.node, "endpoint": args.endpoint, "slot_id": args.slot_id,
        "gpu_model": stats.get("gpu_model"), "nvlink": args.nvlink_domain,
        "vram_total": stats.get("vram_total_mib"), "vram_free": stats.get("vram_free_mib"),
        "util": stats.get("gpu_util_pct"),
        "loaded_model": served if alive else None,
        "served_model": served, "max_context": args.max_context,
        "latency_class": args.latency_class, "free_slots": args.free_slots,
        "epoch": args.epoch, "alive": alive, "probe_ms": probe_ms, "note": note,
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
    p.add_argument("--epoch", type=int, default=0)
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
