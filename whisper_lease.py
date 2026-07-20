#!/usr/bin/env python3
"""whisper-stt as a STANDING exclusive lease-holder on this box's llama slot row.

RFC 0001 gave the fleet exclusive slot leases; every holder so far is a bounded
JOB (a di-fleet shard, a gpu-fleet-run command). whisper-stt is the other kind of
co-tenant: a long-running SERVICE sharing the 3090 with the llama slot the
registry routes to. Until now its ~0.95 GiB VRAM claim was invisible to `pick` —
a fleet consumer could claim proximal's slot and grow llama's KV under whisper,
and the collision surfaced as a CUDA OOM. Onboarding whisper as a lease-holder
turns that OOM class into a scheduling SKIP: while STT is hot the slot row is
leased, `pick`/CLAIM's lease-free predicate derives the slot's capacity below
routable, and fleet consumers route elsewhere (or shrink K) instead of colliding.

Three subcommands wire into whisper-stt.service (units in systemd/):

  acquire     ExecStartPre. Claim THIS node's OWN slot row — deliberately no
              `pick`: whisper is not choosing fleet capacity, it is annotating
              its own GPU. Outcomes:
                * claimed         -> exit 0, lease_id persisted to the state file.
                * held by another -> exit 75 (TEMPFAIL): the scheduling skip.
                  systemd Restart=on-failure retries every RestartSec, so STT
                  starts as soon as the fleet consumer's bounded lease drains.
                * headroom short  -> exit 75: the old OOM class, caught before
                  whisper-server ever maps VRAM.
                * registry dark / slot not registry-reachable (row missing, not
                  alive, stale heartbeat, not routable) -> exit 0 WITHOUT a lease
                  (degrade OPEN, loudly). Fleet consumers can only be scheduled
                  THROUGH the registry, so a slot the registry cannot offer
                  cannot collide via the fleet — and praxis's live voice intake
                  must not be hostage to a dark registry.
              A lease already held under OUR OWN holder id (a crash where
              ExecStopPost never ran, its ghost kept alive by a still-running
              renew loop) is released (fenced) and re-claimed inline, so a
              crash-looping whisper never deadlocks against itself.

  renew-loop  Companion unit (BindsTo=whisper-stt.service). Re-reads the state
              file EVERY tick (so an acquire re-writing it after a restart is
              picked up without coordination), renews the held lease, and on any
              coverage gap (lease lost, degrade-open start, registry outage)
              keeps trying to restore it. It never kills whisper: the loop
              restores the SKIP signal, it does not enforce it with a gun.
              Residual (documented, accepted): between a lease lapse and the
              next successful re-claim a fleet consumer may claim the slot while
              STT is live — exactly the pre-onboarding status quo, now bounded
              by one renew tick instead of standing.

  release     ExecStopPost. Fenced release by the persisted lease_id (a no-op if
              a successor already holds the slot) + state-file removal.
              Idempotent, and it NEVER fails the stop path — if the registry is
              unreachable the lease simply expires autonomously within the TTL.

All lease semantics are the shipped RFC 0001 primitives (di_fleet.claim / renew /
release); this module adds no lease SQL of its own, only one classification
SELECT used to decide skip-vs-degrade AFTER an atomic claim already said no. The
lease ops, row reader, conn factory, and sleep are injectable, so the whole
lifecycle is hermetically testable against tests/lease_fakes.FakeSlotDB.
"""

from __future__ import annotations

import argparse
import json
import os
import socket
import sys
import time

import di_fleet as lease_module

EX_OK = 0
TEMPFAIL = 75  # matches lease_run.py: "try again later", for Restart=on-failure

DEFAULT_ENDPOINT = "http://localhost:8081/v1"
DEFAULT_SLOT_ID = 0
# ggml-small.en resident footprint on the 3090 (~0.95 GiB measured; see
# proximal/whisper/README.md). The claim's headroom predicate must see at least
# this much free before whisper-server is allowed to map it.
DEFAULT_MIB = 973
DEFAULT_STATE = os.path.expanduser("~/.local/state/gpu-fleet/whisper-stt-lease.json")

# Classification read — consulted only AFTER an atomic claim returned no rows, to
# decide whether the refusal is a scheduling skip (someone holds it / no headroom:
# exit 75 and let systemd retry) or a registry-unreachable slot (degrade open).
# The claim itself remains the only arbiter of exclusivity.
SLOT_ROW_SQL = """
SELECT alive,
       heartbeat_ts > now() - interval '45 seconds' AS fresh,
       status,
       vram_free_mib,
       lease_id,
       lease_holder,
       (lease_id IS NOT NULL AND now() < lease_expires) AS lease_active
  FROM gpu_slots
 WHERE (node, endpoint_url, slot_id) = (%(node)s, %(endpoint_url)s, %(slot_id)s)
"""
_ROW_COLS = ("alive", "fresh", "status", "vram_free_mib",
             "lease_id", "lease_holder", "lease_active")


def read_slot_row(conn, slot):
    """The slot row's claim-relevant state as a dict, or None if unregistered."""
    row = conn.execute(SLOT_ROW_SQL, {
        "node": slot["node"],
        "endpoint_url": slot["endpoint_url"],
        "slot_id": slot.get("slot_id", 0),
    }).fetchone()
    return dict(zip(_ROW_COLS, row)) if row else None


def _log(msg):
    print(f"whisper-stt-lease: {msg}", file=sys.stderr)


def _close(conn):
    close = getattr(conn, "close", None)
    if callable(close):
        close()


# --------------------------------------------------------------------------- #
# State file: the lease_id handoff between acquire (ExecStartPre), the renew
# loop (companion unit), and release (ExecStopPost). Re-read every use — never
# cached — so the three processes need no other coordination.
# --------------------------------------------------------------------------- #
def load_state(path):
    try:
        with open(path) as f:
            state = json.load(f)
    except (OSError, ValueError):
        return None
    return state if isinstance(state, dict) and state.get("lease_id") else None


def save_state(path, state):
    os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
    tmp = f"{path}.tmp"
    with open(tmp, "w") as f:
        json.dump(state, f)
    os.replace(tmp, path)  # atomic: the renew loop never reads a torn file


def clear_state(path):
    try:
        os.remove(path)
    except OSError:
        pass


# --------------------------------------------------------------------------- #
# Claim with self-takeover.
# --------------------------------------------------------------------------- #
# Verdicts for a claim that returned no rows (see _classify).
BUSY = "busy"            # actively leased by another holder -> skip (75)
NO_HEADROOM = "no-headroom"  # vram_free below whisper's footprint -> skip (75)
OFFLINE = "offline"      # not offerable via the registry -> degrade open (0)


def _classify(row, mib):
    """Why did an atomic claim match zero rows? Registry-unreachable slots map to
    OFFLINE (nobody can be scheduled onto them, so degrading open is collision-
    safe by construction); a live-but-refused slot is a genuine scheduling skip.
    A row that NOW looks claimable lost a race between claim and this read —
    treated as BUSY so systemd simply retries."""
    if row is None or not (row["alive"] and row["fresh"]
                           and row["status"] == "routable"):
        return OFFLINE
    if row["lease_active"]:
        return BUSY
    if row["vram_free_mib"] < mib:
        return NO_HEADROOM
    return BUSY


def claim_with_self_takeover(conn, slot, holder, *, mib, ttl_seconds,
                             lease_ops=lease_module.leases,
                             read_row_fn=read_slot_row):
    """One atomic claim; if refused because OUR OWN holder id already holds the
    row (a crashed instance's ghost), release that lease (fenced) and re-claim
    once. Returns (lease_id, verdict) — verdict is None on success, else one of
    BUSY / NO_HEADROOM / OFFLINE. Only ever takes over a lease whose holder
    string is exactly ours: one whisper-stt exists per host, so that lease can
    only be a dead predecessor's."""
    lease_id = lease_ops.claim(conn, slot, holder, ttl_seconds=ttl_seconds,
                               model_mib=mib)
    if lease_id is not None:
        return lease_id, None
    row = read_row_fn(conn, slot)
    if row and row["lease_active"] and row["lease_holder"] == holder:
        _log(f"stale self-lease {row['lease_id']} found (holder {holder}); "
             "releasing and re-claiming")
        lease_ops.release(conn, row["lease_id"])
        lease_id = lease_ops.claim(conn, slot, holder, ttl_seconds=ttl_seconds,
                                   model_mib=mib)
        if lease_id is not None:
            return lease_id, None
        row = read_row_fn(conn, slot)
    return None, _classify(row, mib)


# --------------------------------------------------------------------------- #
# acquire — ExecStartPre.
# --------------------------------------------------------------------------- #
def acquire(slot, holder, *, mib, state_path, conn_factory,
            ttl_seconds=lease_module.TTL_SECONDS,
            lease_ops=lease_module.leases, read_row_fn=read_slot_row):
    """Claim the slot before whisper-server starts. Exit codes are the contract:
    0 = start (leased, or degrade-open), 75 = scheduling skip (systemd retries)."""
    try:
        conn = conn_factory()
    except Exception as exc:
        _log(f"registry unreachable ({exc}); starting WITHOUT a lease "
             "(degrade open — fleet consumers cannot be scheduled through a "
             "dark registry either)")
        return EX_OK
    try:
        lease_id, verdict = claim_with_self_takeover(
            conn, slot, holder, mib=mib, ttl_seconds=ttl_seconds,
            lease_ops=lease_ops, read_row_fn=read_row_fn)
        if lease_id is not None:
            save_state(state_path, {"lease_id": str(lease_id), "holder": holder,
                                    "node": slot["node"],
                                    "endpoint_url": slot["endpoint_url"],
                                    "slot_id": slot.get("slot_id", 0)})
            _log(f"lease {lease_id} acquired on {slot['node']}/"
                 f"{slot['endpoint_url']}#{slot.get('slot_id', 0)} "
                 f"(holder {holder}, {mib} MiB)")
            return EX_OK
        if verdict == OFFLINE:
            _log("slot is not offerable via the registry (unregistered, dead, "
                 "stale, or unroutable); starting WITHOUT a lease (degrade open)")
            return EX_OK
        if verdict == NO_HEADROOM:
            _log(f"slot has less than {mib} MiB free — the OOM collision caught "
                 "as a scheduling skip; start deferred (exit 75)")
        else:
            _log("slot is exclusively leased by another consumer; start "
                 "deferred (exit 75) until that lease drains")
        return TEMPFAIL
    except Exception as exc:
        _log(f"registry error during acquire ({exc}); starting WITHOUT a lease "
             "(degrade open)")
        return EX_OK
    finally:
        _close(conn)


# --------------------------------------------------------------------------- #
# renew-loop — companion unit, BindsTo=whisper-stt.service.
# --------------------------------------------------------------------------- #
def renew_tick(slot, holder, *, mib, state_path, conn_factory,
               ttl_seconds=lease_module.TTL_SECONDS,
               lease_ops=lease_module.leases, read_row_fn=read_slot_row):
    """One coverage pass. Returns a short outcome string (for transition-logging
    and tests): 'renewed', 'reacquired', 'uncovered:<verdict>', or 'registry-down'.
    A fresh connection per tick, so a Postgres restart never wedges the loop."""
    try:
        conn = conn_factory()
    except Exception:
        return "registry-down"
    try:
        state = load_state(state_path)
        if state is not None:
            if lease_ops.renew(conn, state["lease_id"], ttl_seconds=ttl_seconds):
                return "renewed"
            _log(f"lease {state['lease_id']} lost (expired, fenced, or "
                 "re-claimed); attempting re-acquire")
            clear_state(state_path)
        lease_id, verdict = claim_with_self_takeover(
            conn, slot, holder, mib=mib, ttl_seconds=ttl_seconds,
            lease_ops=lease_ops, read_row_fn=read_row_fn)
        if lease_id is not None:
            save_state(state_path, {"lease_id": str(lease_id), "holder": holder,
                                    "node": slot["node"],
                                    "endpoint_url": slot["endpoint_url"],
                                    "slot_id": slot.get("slot_id", 0)})
            return "reacquired"
        return f"uncovered:{verdict}"
    except Exception:
        return "registry-down"
    finally:
        _close(conn)


def renew_loop(slot, holder, *, mib, state_path, conn_factory,
               ttl_seconds=lease_module.TTL_SECONDS,
               renew_seconds=lease_module.RENEW_SECONDS,
               lease_ops=lease_module.leases, read_row_fn=read_slot_row,
               sleep=time.sleep, iterations=None):
    """Drive renew_tick forever (or `iterations` times, for tests), logging only
    OUTCOME TRANSITIONS so a standing gap is one journal line, not four a minute."""
    last = None
    n = 0
    while iterations is None or n < iterations:
        outcome = renew_tick(slot, holder, mib=mib, state_path=state_path,
                             conn_factory=conn_factory, ttl_seconds=ttl_seconds,
                             lease_ops=lease_ops, read_row_fn=read_row_fn)
        if outcome != last:
            _log(f"coverage: {outcome}")
            last = outcome
        n += 1
        if iterations is None or n < iterations:
            sleep(renew_seconds)
    return EX_OK


# --------------------------------------------------------------------------- #
# release — ExecStopPost.
# --------------------------------------------------------------------------- #
def release(*, state_path, conn_factory, lease_ops=lease_module.leases):
    """Fenced release of whatever lease the state file records. Always exits 0:
    the stop path must never block, and an unreleased lease self-expires within
    the TTL anyway (RFC 0001 autonomous expiry)."""
    state = load_state(state_path)
    if state is None:
        return EX_OK
    try:
        conn = conn_factory()
        try:
            lease_ops.release(conn, state["lease_id"])
            _log(f"lease {state['lease_id']} released")
        finally:
            _close(conn)
    except Exception as exc:
        _log(f"registry unreachable during release ({exc}); lease "
             f"{state['lease_id']} will expire autonomously within the TTL")
    clear_state(state_path)
    return EX_OK


# --------------------------------------------------------------------------- #
# CLI.
# --------------------------------------------------------------------------- #
def _connection_factory(db):
    def connect():
        import psycopg  # lazy: importing whisper_lease (tests) needs no driver
        return psycopg.connect(
            db,
            autocommit=True,
            options="-c statement_timeout=5000 -c lock_timeout=5000",
        )
    return connect


def _parse_args(argv=None):
    p = argparse.ArgumentParser(
        description="hold a standing exclusive gpu-fleet lease for whisper-stt")
    p.add_argument("action", choices=("acquire", "renew-loop", "release"))
    p.add_argument("--node", default=socket.gethostname())
    p.add_argument("--endpoint-url", default=DEFAULT_ENDPOINT)
    p.add_argument("--slot-id", type=int, default=DEFAULT_SLOT_ID)
    p.add_argument("--mib", type=int, default=DEFAULT_MIB,
                   help="whisper's resident VRAM footprint (headroom the claim requires)")
    p.add_argument("--holder", default=f"whisper-stt/{socket.gethostname()}")
    p.add_argument("--db", default=os.environ.get("GPU_FLEET_DB", "dbname=gpu_fleet"))
    p.add_argument("--state-file", default=DEFAULT_STATE)
    p.add_argument("--ttl-seconds", type=float, default=lease_module.TTL_SECONDS)
    p.add_argument("--renew-seconds", type=float, default=lease_module.RENEW_SECONDS)
    return p.parse_args(argv)


def main(argv=None):
    a = _parse_args(argv)
    slot = {"node": a.node, "endpoint_url": a.endpoint_url, "slot_id": a.slot_id}
    conn_factory = _connection_factory(a.db)
    if a.action == "acquire":
        return acquire(slot, a.holder, mib=a.mib, state_path=a.state_file,
                       conn_factory=conn_factory, ttl_seconds=a.ttl_seconds)
    if a.action == "renew-loop":
        return renew_loop(slot, a.holder, mib=a.mib, state_path=a.state_file,
                          conn_factory=conn_factory, ttl_seconds=a.ttl_seconds,
                          renew_seconds=a.renew_seconds)
    return release(state_path=a.state_file, conn_factory=conn_factory)


if __name__ == "__main__":
    raise SystemExit(main())
