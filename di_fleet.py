#!/usr/bin/env python3
"""di-fleet: fan a divergent-ideation run's K branches across N live fleet slots.

`di` (divergent-ideation) already runs its divergence branches concurrently, but
against a single `-np 1` llama-server those POSTs serialize in one queue, so the
wall-clock is N_branches * decode, not parallel. The fleet has *several* live LLM
slots; this tool shards di's `--frames F` across them and runs ONE `di` subprocess
per slot (each pinned to its own endpoint via per-process env), so the F branches
truly run in parallel and wall-clock drops ~linearly with the number of slots.

Two load-bearing guarantees, mirrored from the registry's own discipline:

  * Linear speedup  — F frames are split into N balanced integer shards summing to
    F (round-robin), each shard is one `di` process, all N run concurrently.
  * No branch lost  — if a shard's `di` dies mid-run (non-zero exit / timeout /
    unparseable JSON = its slot died), its frames are reassigned to a surviving
    endpoint and retried ONCE. A shard's frames are abandoned only if NO endpoint
    can serve them, and that is said explicitly on stderr.

The boundary to `di` is a subprocess (RFC 0078/0087): we NEVER import the Node
engine. The "run one shard" call is an injectable function (`shard_fn`) exactly
like `probe_fn` in heartbeat_all, so sharding / concurrency / failover are unit-
testable with fakes and zero real subprocess, DB, or HTTP.
"""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
from concurrent.futures import ThreadPoolExecutor, as_completed

DI_CLI = os.environ.get(
    "DI_CLI", "/home/halbritt/git/divergent-ideation/dist/cli.js"
)
# Per-shard di subprocess budget. di's own LLM timeout is 180s and it makes
# several round-trips per branch, so a shard with a handful of frames can take a
# while; this just stops a black-hole slot from hanging the whole run forever.
SHARD_TIMEOUT = float(os.environ.get("DI_FLEET_SHARD_TIMEOUT", "1200"))


# --------------------------------------------------------------------------- #
# Routing: which live http LLM slots to spread across.
# --------------------------------------------------------------------------- #
def route_slots(k, db="dbname=gpu_fleet", latency_class=None, pick_fn=None):
    """Up to `k` live http(s) LLM slots, warm-first. di needs an OpenAI-compatible
    HTTP endpoint, never a non-LLM capability (marker's ssh://), so we filter to
    http(s); and we prefer decode-verified WARM slots (real `probe_ms`) over
    cold/loadable ones so di lands on a ready MoE instead of cold-loading 23 GiB.

    latency_class is None (span EVERY live MoE slot) on purpose: the point of the
    fan-out is to use all live MoE capacity, and in this fleet the MoE slots sit in
    DIFFERENT classes (proximal is 'interactive', peecee is 'batch'), so a class
    filter would pin di to one of them and defeat the fan-out. warm-first naturally
    keeps proximal primary; #2's load-aware liveness ages peecee out when marker
    owns its card, so di only fans out to peecee when it can actually serve.

    `pick_slot` returns ALL live capabilities, INCLUDING non-LLM ones (marker's
    ssh:// row), and its SQL LIMIT is applied BEFORE we drop those. A non-LLM row
    can sort AHEAD of a real LLM slot (marker shares peecee's high free-VRAM, which
    outranks proximal's near-full card), so a small `k` LIMIT could come back as
    [marker, one-LLM] and collapse to a single endpoint after filtering — silently
    killing the fan-out. So fetch a generous margin and trim to `k` AFTER filtering.

    `pick_fn(fetch_k) -> rows` is injectable so the routing policy is unit-testable
    without a DB. Any failure to reach the registry degrades to "no slots" (di's own
    default), never an exception."""
    fetch_k = max(k + 8, 16)  # margin so non-LLM rows can't crowd out real LLM slots
    if pick_fn is None:
        def pick_fn(n):
            import pick_slot  # local module; only http(s) rows are LLMs
            import psycopg
            with psycopg.connect(db) as conn:
                return pick_slot.pick(conn, latency_class=latency_class, k=n)
    try:
        picks = pick_fn(fetch_k)
    except Exception as exc:  # no DB, no psycopg, query error -> degrade to di default
        print(f"di-fleet: registry unreachable ({exc}); using di default", file=sys.stderr)
        return []
    return _filter_llm_slots(picks)[:k]


def _is_http(url):
    return isinstance(url, str) and (url.startswith("http://") or url.startswith("https://"))


def _filter_llm_slots(picks):
    """http(s) only, warm slots (probe_ms != null) first, cold ones after."""
    llm = [p for p in picks if _is_http(p.get("endpoint_url"))]
    warm = [p for p in llm if p.get("probe_ms") is not None]
    cold = [p for p in llm if p.get("probe_ms") is None]
    return warm + cold


# --------------------------------------------------------------------------- #
# Sharding: split F frames across N endpoints, balanced, summing to F.
# --------------------------------------------------------------------------- #
def shard_frames(total, n):
    """Round-robin split of `total` frames into `n` balanced integer shards that
    sum to `total`. Each shard differs from any other by at most 1. n is capped at
    total so no endpoint ever gets a 0-frame (pointless) shard; a total of 0 or a
    non-positive n yields no shards."""
    if total <= 0 or n <= 0:
        return []
    n = min(n, total)
    base, extra = divmod(total, n)
    # The first `extra` shards get one more frame than the rest.
    return [base + 1 if i < extra else base for i in range(n)]


# --------------------------------------------------------------------------- #
# Running one shard: the injectable boundary to `di`.
# --------------------------------------------------------------------------- #
def run_shard(endpoint, frames, flags, *, timeout=SHARD_TIMEOUT):
    """Run ONE `di` subprocess for `frames` branches against `endpoint`, pinned via
    per-process env, and return its parsed RunResult dict. Raises on non-zero exit,
    timeout, or unparseable JSON — i.e. "this slot died mid-run" — which is the
    signal `dispatch` uses to fail the shard over to a survivor.

    `endpoint` is a slot dict (endpoint_url, served_model). `flags` is the passed-
    through di flag list (--ideas/--top/--context/--concurrency/--no-code-mode/…),
    minus --frames/--json which we own. This is the only place a real di runs, so
    tests inject a fake in its stead."""
    env = dict(os.environ)
    env["DIVERGENT_LLM_BASE_URL"] = endpoint["endpoint_url"]
    if endpoint.get("served_model"):
        env["DIVERGENT_LLM_MODEL"] = endpoint["served_model"]
    cmd = ["node", DI_CLI, *flags, "--frames", str(frames), "--json", "--quiet"]
    proc = subprocess.run(
        cmd, env=env, capture_output=True, text=True, timeout=timeout
    )
    if proc.returncode != 0:
        raise RuntimeError(
            f"di shard exit {proc.returncode} on {endpoint['endpoint_url']}: "
            f"{proc.stderr.strip()[:400]}"
        )
    try:
        return json.loads(proc.stdout)
    except (json.JSONDecodeError, ValueError) as exc:
        raise RuntimeError(
            f"di shard on {endpoint['endpoint_url']} emitted unparseable JSON: {exc}"
        )


# --------------------------------------------------------------------------- #
# Dispatch: run all shards concurrently, fail a dead shard over to a survivor.
# --------------------------------------------------------------------------- #
def dispatch(slots, total_frames, flags, *, shard_fn=run_shard, max_workers=None):
    """Shard `total_frames` across `slots`, run one shard per slot concurrently,
    and fail any dead shard over once to a surviving endpoint.

    Returns (results, lost) where `results` is a list of {shard, endpoint, frames,
    result} for shards that produced a RunResult, and `lost` is a list of
    {endpoint, frames, error} for frames no endpoint could serve. "No branch lost"
    means: as long as ANY endpoint survives, every frame ends up in some result;
    only a total fleet wipe leaves `lost` non-empty.

    shard_fn(endpoint, frames, flags) is the injectable di boundary."""
    if not slots:
        return [], []
    counts = shard_frames(total_frames, len(slots))
    # counts may be shorter than slots when F < N (capped); use only that many.
    active = [
        {"shard": i, "endpoint": slots[i], "frames": counts[i]}
        for i in range(len(counts))
    ]
    workers = max_workers or len(active)

    results = []
    failed = []  # shards whose first attempt died, awaiting a survivor
    with ThreadPoolExecutor(max_workers=workers) as ex:
        futs = {
            ex.submit(shard_fn, s["endpoint"], s["frames"], flags): s for s in active
        }
        for fut in as_completed(futs):
            s = futs[fut]
            try:
                results.append({**s, "result": fut.result()})
            except Exception as exc:  # slot died mid-run; queue its frames for failover
                failed.append({**s, "error": str(exc)})

    # Failover: an endpoint that already returned a result is alive; reassign each
    # dead shard's frames to one such survivor and retry ONCE. Round-robin the
    # survivors so a burst of failures doesn't all pile onto a single slot.
    survivors = [r["endpoint"] for r in results]
    lost = []
    if failed and survivors:
        with ThreadPoolExecutor(max_workers=len(failed)) as ex:
            retry_futs = {}
            for j, s in enumerate(failed):
                target = survivors[j % len(survivors)]
                retry_futs[ex.submit(shard_fn, target, s["frames"], flags)] = (s, target)
            for fut in as_completed(retry_futs):
                s, target = retry_futs[fut]
                try:
                    results.append(
                        {"shard": s["shard"], "endpoint": target,
                         "frames": s["frames"], "result": fut.result(),
                         "failed_over_from": s["endpoint"].get("endpoint_url")}
                    )
                except Exception as exc:
                    lost.append({"endpoint": target, "frames": s["frames"],
                                 "error": f"failover retry also failed: {exc}"})
    else:
        # No survivor to fail over to (total fleet wipe) -> these frames are lost.
        lost = [{"endpoint": s["endpoint"], "frames": s["frames"], "error": s["error"]}
                for s in failed]

    for item in lost:
        ep = item["endpoint"].get("endpoint_url", "?")
        print(f"di-fleet: ABANDONED {item['frames']} frame(s) — no endpoint could "
              f"serve them (last={ep}): {item['error']}", file=sys.stderr)
    return results, lost


# --------------------------------------------------------------------------- #
# Merge: N RunResults -> one drop-in-compatible RunResult.
# --------------------------------------------------------------------------- #
def _idea_total(idea):
    return ((idea or {}).get("score") or {}).get("total", 0) or 0


def _idea_novelty(idea):
    return ((idea or {}).get("score") or {}).get("novelty", 0) or 0


def _is_trap(idea):
    return bool(((idea or {}).get("score") or {}).get("trap"))


def merge_results(results, *, top=None):
    """Merge per-shard RunResults (each item {shard, endpoint, frames, result})
    into ONE RunResult, byte-for-byte drop-in compatible with `di --json`:

      branches   : concat all shards', frameIds namespaced by shard index so they
                   stay globally unique (and each idea's frameId rewritten to match).
      shortlist  : union of all shards', globally re-sorted by score.total desc,
                   capped at `top` (default = the largest shard shortlist length).
      deepened   : concat.
      traps      : concat, deduped by `text`.
      nonObviousPick: single highest score.novelty non-trap idea across all shards.
      clusters   : concat (labels namespaced by shard so collisions don't merge).
      reframe/provocation: from the highest-scored shard (best single idea), else
                   first shard. `problem`: unchanged (all shards share it)."""
    payloads = [r["result"] for r in results if r.get("result")]
    if not payloads:
        return {}
    if len(payloads) == 1:
        return payloads[0]

    merged = {"problem": payloads[0].get("problem")}

    branches = []
    for r in results:
        res = r.get("result")
        if not res:
            continue
        sidx = r["shard"]
        for b in res.get("branches") or []:
            fid = f"s{sidx}:{b.get('frameId')}"
            ideas = [{**idea, "frameId": fid} for idea in (b.get("ideas") or [])]
            branches.append({**b, "frameId": fid, "ideas": ideas})
    merged["branches"] = branches

    # shortlist: global union, re-sorted by score.total desc.
    shortlist = []
    for res in payloads:
        shortlist.extend(res.get("shortlist") or [])
    shortlist.sort(key=_idea_total, reverse=True)
    if top is None:
        # No explicit cap: keep at most the biggest single shard's shortlist size,
        # so the merged view stays the same "shape" a single di run would emit.
        top = max((len(res.get("shortlist") or []) for res in payloads), default=0)
    merged["shortlist"] = shortlist[:top] if top else shortlist

    deepened = []
    for res in payloads:
        deepened.extend(res.get("deepened") or [])
    merged["deepened"] = deepened

    # traps: concat then dedup by text, preserving first-seen order.
    traps, seen = [], set()
    for res in payloads:
        for t in res.get("traps") or []:
            key = (t or {}).get("text")
            if key in seen:
                continue
            seen.add(key)
            traps.append(t)
    merged["traps"] = traps

    # nonObviousPick: highest novelty non-trap idea across every idea in every shard.
    best = None
    for r in results:
        res = r.get("result")
        if not res:
            continue
        sidx = r["shard"]
        for b in res.get("branches") or []:
            for idea in b.get("ideas") or []:
                if _is_trap(idea):
                    continue
                if best is None or _idea_novelty(idea) > _idea_novelty(best):
                    best = {**idea, "frameId": f"s{sidx}:{idea.get('frameId')}"}
    merged["nonObviousPick"] = best

    # clusters: concat; namespace labels/ideaIds so equal labels from two shards
    # are not silently conflated.
    clusters = []
    for r in results:
        res = r.get("result")
        if not res:
            continue
        sidx = r["shard"]
        for c in res.get("clusters") or []:
            clusters.append({**c, "label": f"s{sidx}:{c.get('label')}"})
    merged["clusters"] = clusters

    # reframe + provocation: take from the shard with the single best-scored idea
    # (the strongest run), falling back to the first shard.
    best_shard = max(
        payloads,
        key=lambda res: max(
            (_idea_total(i) for b in (res.get("branches") or [])
             for i in (b.get("ideas") or [])),
            default=0,
        ),
    )
    if best_shard.get("reframe") is not None:
        merged["reframe"] = best_shard.get("reframe")
    merged["provocation"] = best_shard.get("provocation")

    return merged


# --------------------------------------------------------------------------- #
# Human summary for non --json N>1 runs.
# --------------------------------------------------------------------------- #
def render_summary(merged):
    """Short human summary for non-`--json` multi-slot runs: shortlist + the
    non-obvious pick + the provocation. The machine path is --json; this is the
    'what did the fleet come up with' glance for a person."""
    lines = [f"problem: {merged.get('problem')}", ""]
    if merged.get("reframe"):
        lines += [f"reframe: {merged['reframe']}", ""]
    lines.append("shortlist (global, by score.total):")
    for i, idea in enumerate(merged.get("shortlist") or [], 1):
        total = _idea_total(idea)
        lines.append(f"  {i}. [{total:>5}] {(idea or {}).get('text', '')}")
    pick = merged.get("nonObviousPick")
    if pick:
        lines += ["", f"non-obvious pick: {pick.get('text', '')}"]
    if merged.get("provocation"):
        lines += ["", f"provocation: {merged['provocation']}"]
    return "\n".join(lines)


# --------------------------------------------------------------------------- #
# CLI: parse, route, shard+dispatch+merge, emit.
# --------------------------------------------------------------------------- #
# Flags that di-fleet OWNS (it sets --frames per shard, forces --json/--quiet on
# the subprocesses, and consumes --top to cap the merged shortlist). Everything
# else (problem text, --ideas, --context, --concurrency, --no-code-mode, --model)
# passes straight through to each shard.
def _split_argv(argv):
    """Pull out di-fleet-owned flags (--frames, --top, --json) and the K override;
    return (frames, top, want_json, k, passthrough_flags). The problem text and
    every other di flag stay in passthrough verbatim."""
    frames, top, want_json, k = None, None, False, None
    rest = []
    i = 0
    while i < len(argv):
        a = argv[i]
        if a == "--frames":
            frames = int(argv[i + 1]); i += 2
        elif a == "--top":
            top = int(argv[i + 1])
            rest += [a, argv[i + 1]]  # --top still passes through to each shard
            i += 2
        elif a == "--json":
            want_json = True; i += 1
        elif a == "-k" or a == "--slots":
            k = int(argv[i + 1]); i += 2  # di-fleet-only: fan-out width override
        else:
            rest.append(a); i += 1
    return frames, top, want_json, k, rest


def main(argv=None):
    argv = list(sys.argv[1:] if argv is None else argv)
    frames, top, want_json, k_override, passthrough = _split_argv(argv)
    total_frames = frames if frames is not None else 5  # di's --frames default

    db = os.environ.get("GPU_FLEET_DB", "dbname=gpu_fleet")
    k = k_override or total_frames  # never route more slots than there are frames
    slots = route_slots(k, db=db)

    # Case 1: no live slot -> single di on its own localhost default (today's
    # behavior). We pass the original frames through unchanged.
    if not slots:
        print("di-fleet: no live fleet slot; using di defaults (localhost:8081)",
              file=sys.stderr)
        cmd = ["node", DI_CLI, *passthrough, "--frames", str(total_frames)]
        if want_json:
            cmd.append("--json")
        os.execvp("node", cmd)  # replace process; preserves exit code / streaming
        return 0  # unreachable

    # Case 2: exactly one live slot -> single di pinned to it, RunResult unchanged.
    if len(slots) == 1:
        ep = slots[0]
        print(f"di-fleet -> {ep['endpoint_url']} ({ep.get('served_model')})",
              file=sys.stderr)
        env = dict(os.environ)
        env["DIVERGENT_LLM_BASE_URL"] = ep["endpoint_url"]
        if ep.get("served_model"):
            env["DIVERGENT_LLM_MODEL"] = ep["served_model"]
        cmd = ["node", DI_CLI, *passthrough, "--frames", str(total_frames)]
        if want_json:
            cmd.append("--json")
        os.execvpe("node", cmd, env)
        return 0  # unreachable

    # Case 3: N>1 live slots -> shard, run concurrently, fail over, merge.
    eps = ", ".join(f"{s['endpoint_url']}" for s in slots)
    print(f"di-fleet -> {len(slots)} slots: {eps}", file=sys.stderr)
    results, lost = dispatch(slots, total_frames, passthrough)
    if not results:
        print("di-fleet: every shard failed; no result", file=sys.stderr)
        return 1
    merged = merge_results(results, top=top)
    if lost:
        merged = {**merged, "_lost_frames": sum(x["frames"] for x in lost)}

    if want_json:
        print(json.dumps(merged, indent=2))
    else:
        print(render_summary(merged))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
