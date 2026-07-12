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

# uuid stays at index 5 so the existing parse is index-stable; it is the MEASURED GPU
# identity used by the RFC-0002 quarantine ratchet (BC7: a hot-swapped card differs).
# RFC 0005 (Slice 2, F-KEYS): mig.mode.current / ecc.mode.current are appended AFTER uuid
# (indices 6,7) — the SLOW capability bands that bump epoch (C-EPOCH). An older nvidia-smi
# that omits them yields fewer fields => mig/ecc parse to None (ratchet inert), exactly as
# uuid is already tolerated.
GPU_QUERY = ("--query-gpu=name,memory.total,memory.used,memory.free,utilization.gpu,uuid,"
             "mig.mode.current,ecc.mode.current")
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
    status, probe_streak, gpu_uuid, boot_epoch, mig_mode, ecc_mode, heartbeat_ts)
VALUES (
    %(node)s, %(endpoint)s, %(slot_id)s, %(gpu_model)s, %(nvlink)s, %(vram_total)s,
    %(vram_free)s, %(util)s, %(loaded_model)s, %(served_model)s, %(max_context)s,
    %(latency_class)s, %(free_slots)s, %(epoch)s, %(alive)s, %(probe_ms)s, %(note)s,
    -- RFC 0002 Slice-1 Change B: a brand-new self-reporting row appears 'unverified'
    -- (zero-touch register), with probe_streak seeded 1 on a passing first probe.
    -- RFC 0005 (F-KEYS): mig_mode/ecc_mode are named in EVERY writer's row dict so the
    -- shared UPSERT never KeyErrors a writer (heartbeat_once, probe_node, _failed_row).
    'unverified', CASE WHEN %(alive)s THEN 1 ELSE 0 END, %(gpu_uuid)s, %(boot_epoch)s,
    %(mig_mode)s, %(ecc_mode)s, now())
ON CONFLICT (node, endpoint_url, slot_id) DO UPDATE SET
    gpu_model=EXCLUDED.gpu_model, nvlink_domain=EXCLUDED.nvlink_domain,
    vram_total_mib=EXCLUDED.vram_total_mib, vram_free_mib=EXCLUDED.vram_free_mib,
    gpu_util_pct=EXCLUDED.gpu_util_pct,
    loaded_model=CASE WHEN %(probe_verified)s OR NOT EXCLUDED.alive
                      THEN EXCLUDED.loaded_model ELSE gpu_slots.loaded_model END,
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
    -- RFC 0005 C-EPOCH: extend the routing-relevant diff with the SLOW CAPABILITY bands
    -- mig_mode/ecc_mode (the card's compute partitioning changed => a holder's routing
    -- assumption is invalidated => fence held leases). These come from the node's OWN
    -- local nvidia-smi (measured, trusted), NOT the exporter, so epoch stays decoupled
    -- from the untrusted exporter. The FAST capacity bands (probe-floor/util/contention/
    -- phantom) live ONLY in the companion table and never appear here, so within-band
    -- VRAM/util churn never bumps epoch or self-aborts a running job.
    epoch = gpu_slots.epoch + CASE
        WHEN gpu_slots.served_model   IS DISTINCT FROM EXCLUDED.served_model
          OR gpu_slots.nvlink_domain  IS DISTINCT FROM EXCLUDED.nvlink_domain
          OR gpu_slots.max_context    IS DISTINCT FROM EXCLUDED.max_context
          OR gpu_slots.mig_mode       IS DISTINCT FROM EXCLUDED.mig_mode
          OR gpu_slots.ecc_mode       IS DISTINCT FROM EXCLUDED.ecc_mode
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
        -- A lease-time GPU check is weaker than a decode. Demote a previously
        -- routable row to one-decode-away and never let weak checks promote it.
        WHEN NOT %(probe_verified)s THEN
            CASE WHEN gpu_slots.status = 'routable' THEN {GRADUATION_STREAK} - 1
                 ELSE gpu_slots.probe_streak END
        WHEN gpu_slots.gpu_uuid IS NOT NULL AND EXCLUDED.gpu_uuid IS NOT NULL
             AND gpu_slots.gpu_uuid <> EXCLUDED.gpu_uuid THEN 1
        ELSE gpu_slots.probe_streak + 1 END,
    status = CASE
        WHEN NOT EXCLUDED.alive THEN 'unverified'
        WHEN NOT %(probe_verified)s THEN
            CASE WHEN gpu_slots.status = 'routable' THEN 'probationary'
                 ELSE gpu_slots.status END
        WHEN gpu_slots.gpu_uuid IS NOT NULL AND EXCLUDED.gpu_uuid IS NOT NULL
             AND gpu_slots.gpu_uuid <> EXCLUDED.gpu_uuid THEN 'unverified'
        WHEN gpu_slots.status = 'routable' THEN 'routable'
        WHEN gpu_slots.probe_streak + 1 >= {GRADUATION_STREAK} THEN 'routable'
        ELSE 'probationary' END,
    alive=EXCLUDED.alive,
    probe_ms=CASE WHEN %(probe_verified)s OR NOT EXCLUDED.alive THEN EXCLUDED.probe_ms
                  ELSE gpu_slots.probe_ms END,
    -- RFC 0005: persist the measured slow capability bands (their change drove the epoch
    -- CASE above). COALESCE-free: a NULL report (older nvidia-smi) overwrites with NULL,
    -- and NULL IS DISTINCT FROM NULL is false, so it never spuriously bumps epoch.
    mig_mode=EXCLUDED.mig_mode, ecc_mode=EXCLUDED.ecc_mode,
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


# =========================================================================== #
# RFC 0005 — exporter-fed capacity signal (probe-anchored). The companion table
# gpu_slots_capacity is written by a SEPARATE, savepoint-guarded statement AFTER the
# liveness UPSERT (C3 fault isolation), in BOTH the push (heartbeat_once) and pull
# (heartbeat_all.pull_write) paths (BC4). Every routing-relevant number is
# probe-anchored, banded for hysteresis, and carries single-clock freshness (BC2).
# =========================================================================== #

# Hysteresis band widths. The authoritative tuning lives in capacity_policy (band edges
# AS DATA), read by the freshness-decaying VIEW / inline pick; the writer mirrors the
# defaults here so a within-band tick writes an IDENTICAL companion row (a no-op) without
# a per-tick policy SELECT. Keep in lockstep with capacity_policy's defaults.
VRAM_BAND_MIB = 1000
UTIL_BAND_PCT = 10


def _band_mib(x: int | None) -> int | None:
    """Quantize a MiB value DOWN to a coarse VRAM band so raw VRAM churn within a band
    writes an identical companion row (C-EPOCH / gate bullet 2). None stays None."""
    if x is None:
        return None
    return (int(x) // VRAM_BAND_MIB) * VRAM_BAND_MIB


def _least_present(*vals: int | None) -> int | None:
    """SQL LEAST() semantics for the probe-anchoring rule (C4): the smallest NON-NULL
    value, or None if all are None. effective_free = LEAST(probe_floor, exporter_free):
    a lying/stale exporter can never claim headroom the probe could not allocate."""
    present = [v for v in vals if v is not None]
    return min(present) if present else None


def phantom_from_pids(per_pid, recognized_pids):
    """OQ-P / Principle 3 — measured phantom. `per_pid` is a list of (pid, vram_mib) the
    node physically reads off ITS OWN card. PIDs the fleet recognizes (its own lease-bound
    inference servers) are ours; ALL unrecognized-PID VRAM is a phantom occupant (marker),
    a DIRECT measurement, not a declared-footprint estimate. Returns (phantom_mib,
    phantom_pids). Only the card-owning node ever calls this for its own card."""
    recognized = set(recognized_pids or ())
    unknown = [(p, m) for (p, m) in (per_pid or []) if p not in recognized]
    return sum(m for _, m in unknown), len(unknown)


def probe_floor(served_model, stats, *, scratch_floor_fn=None, residency_floor_fn=None):
    """Probe-measured allocatable floor, gated PER-BACKEND (OQ-B / observer effect). The
    peecee 'ollama-ondemand' slot uses a RESIDENCY-ONLY floor (a pure read; it can NEVER
    force a load or allocate scratch); every other backend may use a scratch-allocation
    floor. The shipped defaults read only the already-measured nvidia-smi free VRAM (NO
    scratch allocation), so the build is live-infra-inert; tests inject a scratch_floor_fn
    spy to prove the ollama-ondemand path never invokes it."""
    if served_model == "ollama-ondemand":
        rf = residency_floor_fn or (lambda s: s.get("vram_free_mib"))
        return rf(stats)
    sf = scratch_floor_fn or (lambda s: s.get("vram_free_mib"))
    return sf(stats)


def capacity_telemetry(served_model, stats, probe_ms, *,
                       exporter_fn=None, per_pid_fn=None, recognized_pids=(),
                       scratch_floor_fn=None, residency_floor_fn=None,
                       fast_source_age_s=0.0, slow_source_age_s=0.0):
    """Compute one slot's companion (capacity) fields from already-measured inputs. The
    exporter / per-PID / scratch-floor readers are INJECTED seams (a node reads only its
    OWN localhost exporter; default is inert => probe-anchored only, phantom 0), so units
    use fakes and the build never reads real hardware. Returns a dict of the companion
    columns the CAPACITY_UPSERT names (PK keys are merged in by the caller). All MiB
    numbers are BANDED so within-band churn is a no-op; live_slowdown_factor is NOT here —
    it is computed in SQL (BC3)."""
    exporter = (exporter_fn() if exporter_fn else {}) or {}
    floor_b = _band_mib(probe_floor(served_model, stats,
                                    scratch_floor_fn=scratch_floor_fn,
                                    residency_floor_fn=residency_floor_fn))
    exporter_free_b = _band_mib(exporter.get("free_mib"))
    eff = _least_present(floor_b, exporter_free_b)            # C4: trust the lower
    phantom_mib, phantom_pids = phantom_from_pids(
        per_pid_fn() if per_pid_fn else [], recognized_pids)
    if eff is not None and phantom_mib:
        eff = max(0, eff - phantom_mib)                      # OQ-P: phantom shrinks free
    util = stats.get("gpu_util_pct")
    return {
        "cold_probe_ms": probe_ms,        # this tick's probe (numerator); SQL keeps the sticky baseline
        "probe_floor_mib": floor_b,
        "exporter_free_mib": exporter_free_b,
        "effective_free_mib": _band_mib(eff),
        "util_band": (util // UTIL_BAND_PCT) if util is not None else None,
        "power_w": exporter.get("power_w"),
        "temp_c": exporter.get("temp_c"),
        "phantom_mib": phantom_mib,
        "phantom_pids": phantom_pids,
        # 'measured' whenever the card was reachable (a residency-only / failed-probe slot
        # still yields a well-formed measured row; capacity_source is never 'absent' merely
        # because live_slowdown_factor is NULL, BC3). 'absent' only when the GPU is unread.
        "capacity_source": "measured" if stats.get("gpu_model") is not None else "absent",
        "fast_source_age_s": fast_source_age_s,
        "slow_source_age_s": slow_source_age_s,
    }


def absent_capacity_fields():
    """A well-formed, fully-NULL companion field set for a crashed/unreachable probe, so a
    _failed_row never KeyErrors the CAPACITY_UPSERT and writes a benign 'absent' row that
    the reader COALESCEs straight through to today's vram_free_mib."""
    return {
        "cold_probe_ms": None, "probe_floor_mib": None, "exporter_free_mib": None,
        "effective_free_mib": None, "util_band": None, "power_w": None, "temp_c": None,
        "phantom_mib": 0, "phantom_pids": 0, "capacity_source": "absent",
        "fast_source_age_s": None, "slow_source_age_s": None,
    }


# CAPACITY_UPSERT — the SEPARATE companion write (Slice 1 + 2). Runs AFTER the liveness
# UPSERT under a savepoint (write_capacity), so a malformed/failed capacity write rolls
# back ONLY itself and never sinks liveness (C3). live_slowdown_factor is computed IN SQL
# (BC3): a None probe or a 0/None baseline yields NULL, never a TypeError/ZeroDivisionError.
# The cold baseline is STICKY in the DB (F-BASE): once a baseline exists it is read back
# and kept, so a heartbeat-process restart never recaptures a HOT baseline. EXCLUDED's
# cold_probe_ms carries THIS tick's probe latency (the numerator); the persisted row's
# cold_probe_ms is the sticky denominator.
CAPACITY_UPSERT = """
INSERT INTO gpu_slots_capacity (
    node, endpoint_url, slot_id,
    cold_probe_ms, live_slowdown_factor, probe_floor_mib, exporter_free_mib,
    effective_free_mib, util_band, power_w, temp_c, phantom_mib, phantom_pids,
    capacity_source, fast_source_age_s, slow_source_age_s, updated_ts)
VALUES (
    %(node)s, %(endpoint)s, %(slot_id)s,
    %(cold_probe_ms)s,
    -- First baseline => slowdown 1.0; a NULL or 0 baseline => NULL (BC3, no division). The
    -- ::int casts type the bound param so a NULL probe_ms is not an AmbiguousParameter.
    CASE WHEN %(cold_probe_ms)s::int IS NULL OR %(cold_probe_ms)s::int = 0
         THEN NULL ELSE 1.0 END,
    %(probe_floor_mib)s, %(exporter_free_mib)s, %(effective_free_mib)s,
    %(util_band)s, %(power_w)s, %(temp_c)s,
    COALESCE(%(phantom_mib)s, 0), COALESCE(%(phantom_pids)s, 0),
    %(capacity_source)s, %(fast_source_age_s)s, %(slow_source_age_s)s, now())
ON CONFLICT (node, endpoint_url, slot_id) DO UPDATE SET
    -- F-BASE: STICKY cold baseline. COALESCE keeps the persisted (cold) baseline, so the
    -- first passing probe (captured at registration, idle) stays the baseline forever and
    -- a process restart never recaptures a hot one.
    cold_probe_ms = COALESCE(gpu_slots_capacity.cold_probe_ms, EXCLUDED.cold_probe_ms),
    -- BC3: live_slowdown_factor computed in SQL via CASE/NULLIF — NEVER a Python division.
    -- A None probe (failed decode; every ollama-ondemand tick) or a 0/None baseline => NULL.
    live_slowdown_factor = CASE
        WHEN EXCLUDED.cold_probe_ms IS NULL
          OR COALESCE(gpu_slots_capacity.cold_probe_ms, EXCLUDED.cold_probe_ms) IS NULL
        THEN NULL
        ELSE EXCLUDED.cold_probe_ms::numeric
             / NULLIF(COALESCE(gpu_slots_capacity.cold_probe_ms, EXCLUDED.cold_probe_ms), 0)
    END,
    probe_floor_mib    = EXCLUDED.probe_floor_mib,
    exporter_free_mib  = EXCLUDED.exporter_free_mib,
    effective_free_mib = EXCLUDED.effective_free_mib,
    util_band          = EXCLUDED.util_band,
    power_w            = EXCLUDED.power_w,
    temp_c             = EXCLUDED.temp_c,
    phantom_mib        = EXCLUDED.phantom_mib,
    phantom_pids       = EXCLUDED.phantom_pids,
    capacity_source    = EXCLUDED.capacity_source,
    fast_source_age_s  = EXCLUDED.fast_source_age_s,
    slow_source_age_s  = EXCLUDED.slow_source_age_s,
    updated_ts         = now()
-- The companion row is re-stamped on EVERY tick (no within-band WHERE guard). updated_ts and
-- the source-age fields ARE the freshness / liveness clock the reader decays against
-- (capacity_staleness_s = fast_source_age_s + now()-updated_ts), so a live writer measuring
-- stable, within-band values MUST keep advancing them — otherwise a healthy steady-state slot
-- self-decays to 'stale' every k*half_life and the headroom signal silently erases (the reader
-- COALESCEs back to vram_free). Re-writing a within-band-identical row is intentional and
-- cheap: the companion carries NO epoch column, so it can never bump gpu_slots.epoch or fence a
-- lease — C-EPOCH and the IS-DISTINCT-FROM churn exclusion live ENTIRELY in the gpu_slots
-- liveness UPSERT (mig/ecc), not here. Frozen-source decay stays exact: a writer that STOPS
-- ticking freezes updated_ts (now()-updated_ts grows past the threshold), and a writer that
-- ticks against a frozen exporter carries a growing fast_source_age_s — both still decay.
"""


def write_capacity(conn, row) -> bool:
    """Best-effort companion write under a SAVEPOINT (C3), AFTER the liveness UPSERT and
    inside the SAME transaction, in both the push and pull paths (BC4). A malformed/failed
    capacity write ROLLBACKs to the savepoint — undoing ONLY itself — and returns False,
    so it can NEVER sink or roll back the liveness UPSERT. Capacity is best-effort
    enrichment; liveness is the load-bearing fact."""
    try:
        conn.execute("SAVEPOINT cap")
        conn.execute(CAPACITY_UPSERT, row)
        conn.execute("RELEASE SAVEPOINT cap")
        return True
    except Exception:
        try:
            conn.execute("ROLLBACK TO SAVEPOINT cap")
        except Exception:
            pass
        return False


def capacity_staleness_s(fast_source_age_s, updated_age_s) -> float:
    """BC2 single-clock staleness used by the hermetic decay tests, mirroring the SQL
    `fast_source_age_s + GREATEST(0, now()-updated_ts)`. BOTH inputs are SAME-clock
    DIFFERENCES (a node-clock age + a DB-clock age), so an absolute node<->DB NTP skew
    cancels in each and is never load-bearing; a frozen source (age grows) or an unwritten
    row (now()-updated_ts grows) still accrues staleness."""
    return (fast_source_age_s or 0.0) + max(0.0, updated_age_s or 0.0)


def is_fast_stale(staleness_s, *, decay_k, half_life_s) -> bool:
    """Decay predicate: a fast capacity field is stale once its single-clock staleness
    exceeds k * half_life (the same threshold the VIEW and inline pick use)."""
    return staleness_s > decay_k * half_life_s


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
    # RFC 0005 (Slice 2): mig/ecc are the SLOW capability bands (indices 6,7). Same
    # tolerance as uuid: an older nvidia-smi without them -> None (no spurious epoch bump,
    # since NULL IS DISTINCT FROM NULL is false).
    mig_mode = _norm_smi(parts[6] if len(parts) > 6 else None)
    ecc_mode = _norm_smi(parts[7] if len(parts) > 7 else None)
    return {
        "gpu_model": name,
        "vram_total_mib": int(total),
        "vram_free_mib": int(free),
        "gpu_util_pct": int(float(util)) if util not in ("[N/A]", "") else None,
        "gpu_uuid": uuid or None,
        "mig_mode": mig_mode,
        "ecc_mode": ecc_mode,
    }


def _norm_smi(val: str | None) -> str | None:
    """Normalize an nvidia-smi capability field: an unsupported card reports '[N/A]'
    (or empty), which we map to NULL so it never reads as a real, epoch-bumping band."""
    if val is None:
        return None
    v = val.strip()
    return v if v and v not in ("[N/A]", "N/A") else None


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
        "probe_verified": True,
        "gpu_uuid": stats.get("gpu_uuid"),
        # RFC 0005 (F-KEYS): the shared UPSERT now names mig_mode/ecc_mode, so EVERY row
        # dict must carry them or conn.execute(UPSERT, row) KeyErrors. gpu_stats parses
        # them from local nvidia-smi (None on a card/driver that omits them).
        "mig_mode": stats.get("mig_mode"), "ecc_mode": stats.get("ecc_mode"),
        "boot_epoch": next_boot_epoch() if push else None,
    }
    conn.execute(UPSERT, row)
    # RFC 0005 (Slice 1+2): write the companion capacity row AFTER the liveness UPSERT,
    # under the savepoint guard (C3), BEFORE the commit — so a malformed capacity write
    # never sinks liveness. Best-effort enrichment; the return value is intentionally
    # ignored (a False just means this tick has no fresh companion row).
    cap = capacity_telemetry(served, stats, probe_ms)
    write_capacity(conn, {**row, **cap})
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
