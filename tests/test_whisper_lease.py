"""whisper-stt as a standing lease-holder: acquire / renew-loop / release.

Hermetic: FakeSlotDB drives the REAL RFC 0001 claim/renew/release SQL semantics;
the classification row reader is injected to read the fake's rows directly (the
production reader is one SELECT against the same columns). No DB, no clock, no
subprocess.
"""

import json

import whisper_lease as wl
from lease_fakes import FakeSlotDB

SLOT = {"node": "proximal", "endpoint_url": "http://localhost:8081/v1", "slot_id": 0}
HOLDER = "whisper-stt/proximal"
MIB = 973


def _read_row(db):
    """Classification reader over FakeSlotDB rows — same shape as read_slot_row."""
    def read(_conn, slot):
        row = db.rows.get((slot["node"], slot["endpoint_url"], slot.get("slot_id", 0)))
        if row is None:
            return None
        return {
            "alive": row["alive"],
            "fresh": row["alive"] and (db.now - row["heartbeat_ts"]) < 45,
            "status": row["status"],
            "vram_free_mib": row["vram_free_mib"],
            "lease_id": row["lease_id"],
            "lease_holder": row["lease_holder"],
            "lease_active": not db._is_free(row),
        }
    return read


def _acquire(db, state_path, slot=SLOT, holder=HOLDER, mib=MIB):
    return wl.acquire(slot, holder, mib=mib, state_path=str(state_path),
                      conn_factory=lambda: db, read_row_fn=_read_row(db))


def _tick(db, state_path, slot=SLOT, holder=HOLDER, mib=MIB):
    return wl.renew_tick(slot, holder, mib=mib, state_path=str(state_path),
                         conn_factory=lambda: db, read_row_fn=_read_row(db))


def _state(state_path):
    with open(state_path) as f:
        return json.load(f)


# --------------------------------------------------------------------------- #
# acquire
# --------------------------------------------------------------------------- #
def test_acquire_claims_free_slot_and_persists_lease(tmp_path):
    db = FakeSlotDB([{**SLOT, "vram_free_mib": 2400}])
    state_path = tmp_path / "lease.json"

    assert _acquire(db, state_path) == wl.EX_OK
    row = db.row_for(SLOT)
    assert row["lease_holder"] == HOLDER
    assert row["lease_id"] == "L1"
    assert _state(state_path)["lease_id"] == "L1"


def test_acquire_skips_when_another_consumer_holds_the_slot(tmp_path):
    db = FakeSlotDB([{**SLOT, "vram_free_mib": 2400, "lease_id": "other",
                      "lease_holder": "di-fleet/x", "lease_expires": 1030.0}])
    state_path = tmp_path / "lease.json"

    assert _acquire(db, state_path) == wl.TEMPFAIL          # the scheduling skip
    assert db.row_for(SLOT)["lease_id"] == "other"           # untouched
    assert not state_path.exists()


def test_acquire_skips_on_insufficient_headroom(tmp_path):
    db = FakeSlotDB([{**SLOT, "vram_free_mib": MIB - 1}])
    state_path = tmp_path / "lease.json"

    assert _acquire(db, state_path) == wl.TEMPFAIL           # OOM caught pre-launch
    assert db.row_for(SLOT)["lease_id"] is None
    assert not state_path.exists()


def test_acquire_degrades_open_when_slot_not_registry_reachable(tmp_path):
    # An unroutable slot cannot be offered to any fleet consumer, so starting
    # unleased is collision-safe by construction. Same for a missing row.
    db = FakeSlotDB([{**SLOT, "vram_free_mib": 2400, "status": "unverified"}])
    state_path = tmp_path / "lease.json"

    assert _acquire(db, state_path) == wl.EX_OK
    assert db.row_for(SLOT)["lease_id"] is None
    assert not state_path.exists()

    empty = FakeSlotDB([])
    assert _acquire(empty, state_path) == wl.EX_OK
    assert not state_path.exists()


def test_acquire_degrades_open_when_registry_unreachable(tmp_path):
    def down():
        raise ConnectionError("connection refused")

    state_path = tmp_path / "lease.json"
    rc = wl.acquire(SLOT, HOLDER, mib=MIB, state_path=str(state_path),
                    conn_factory=down)
    assert rc == wl.EX_OK
    assert not state_path.exists()


def test_acquire_takes_over_own_stale_lease(tmp_path):
    # A crash where ExecStopPost never ran can leave OUR holder id on a live
    # lease (a still-running renew loop keeps it alive). acquire must not
    # deadlock against its own ghost: fenced release + re-claim.
    db = FakeSlotDB([{**SLOT, "vram_free_mib": 2400, "lease_id": "ghost",
                      "lease_holder": HOLDER, "lease_expires": 1030.0}])
    state_path = tmp_path / "lease.json"

    assert _acquire(db, state_path) == wl.EX_OK
    row = db.row_for(SLOT)
    assert row["lease_id"] == "L1"                           # fresh lease, not the ghost
    assert row["lease_holder"] == HOLDER
    assert _state(state_path)["lease_id"] == "L1"


# --------------------------------------------------------------------------- #
# renew-loop
# --------------------------------------------------------------------------- #
def test_renew_tick_extends_a_held_lease(tmp_path):
    db = FakeSlotDB([{**SLOT, "vram_free_mib": 2400}])
    state_path = tmp_path / "lease.json"
    _acquire(db, state_path)

    db.advance(30)  # past one renew interval, inside the TTL
    assert _tick(db, state_path) == "renewed"
    assert db.row_for(SLOT)["lease_expires"] == db.now + wl.lease_module.TTL_SECONDS


def test_renew_tick_reacquires_after_expiry(tmp_path):
    db = FakeSlotDB([{**SLOT, "vram_free_mib": 2400}])
    state_path = tmp_path / "lease.json"
    _acquire(db, state_path)

    db.advance(60)  # TTL lapsed with no renew (loop was down): lease lost
    assert _tick(db, state_path) == "reacquired"
    assert db.row_for(SLOT)["lease_id"] == "L2"
    assert _state(state_path)["lease_id"] == "L2"


def test_renew_tick_reports_uncovered_when_a_consumer_holds_the_slot(tmp_path):
    db = FakeSlotDB([{**SLOT, "vram_free_mib": 2400}])
    state_path = tmp_path / "lease.json"
    _acquire(db, state_path)

    # Lease lapses; a fleet consumer claims the slot before the loop wakes.
    db.advance(60)
    import di_fleet
    di_fleet.claim(db, SLOT, "di-fleet/other")
    assert _tick(db, state_path) == "uncovered:busy"
    assert db.row_for(SLOT)["lease_holder"] == "di-fleet/other"  # never stolen
    assert not (tmp_path / "lease.json").exists()                # state cleared

    # The consumer's lease drains -> the next tick restores coverage.
    db.advance(60)
    assert _tick(db, state_path) == "reacquired"
    assert db.row_for(SLOT)["lease_holder"] == HOLDER


def test_renew_tick_acquires_coverage_after_degrade_open_start(tmp_path):
    # acquire degraded open (no state file); the loop restores the skip signal
    # once the slot becomes claimable.
    db = FakeSlotDB([{**SLOT, "vram_free_mib": 2400}])
    state_path = tmp_path / "lease.json"

    assert _tick(db, state_path) == "reacquired"
    assert db.row_for(SLOT)["lease_holder"] == HOLDER


def test_renew_tick_survives_registry_outage(tmp_path):
    def down():
        raise ConnectionError("connection refused")

    assert wl.renew_tick(SLOT, HOLDER, mib=MIB, state_path=str(tmp_path / "x"),
                         conn_factory=down) == "registry-down"


def test_renew_loop_runs_bounded_iterations_and_sleeps_between(tmp_path):
    db = FakeSlotDB([{**SLOT, "vram_free_mib": 2400}])
    state_path = tmp_path / "lease.json"
    _acquire(db, state_path)
    naps = []

    rc = wl.renew_loop(SLOT, HOLDER, mib=MIB, state_path=str(state_path),
                       conn_factory=lambda: db, read_row_fn=_read_row(db),
                       sleep=naps.append, iterations=3)
    assert rc == wl.EX_OK
    assert naps == [wl.lease_module.RENEW_SECONDS] * 2  # no trailing sleep


# --------------------------------------------------------------------------- #
# release
# --------------------------------------------------------------------------- #
def test_release_frees_slot_and_clears_state(tmp_path):
    db = FakeSlotDB([{**SLOT, "vram_free_mib": 2400}])
    state_path = tmp_path / "lease.json"
    _acquire(db, state_path)

    rc = wl.release(state_path=str(state_path), conn_factory=lambda: db)
    assert rc == wl.EX_OK
    assert db.row_for(SLOT)["lease_id"] is None
    assert not state_path.exists()


def test_release_is_fenced_against_a_successor(tmp_path):
    db = FakeSlotDB([{**SLOT, "vram_free_mib": 2400}])
    state_path = tmp_path / "lease.json"
    _acquire(db, state_path)

    # Our lease lapses and a successor claims; releasing OUR old lease_id must
    # not clobber the successor (fenced no-op).
    db.advance(60)
    import di_fleet
    di_fleet.claim(db, SLOT, "di-fleet/successor")
    wl.release(state_path=str(state_path), conn_factory=lambda: db)
    assert db.row_for(SLOT)["lease_holder"] == "di-fleet/successor"
    assert not state_path.exists()


def test_release_is_idempotent_and_never_blocks_the_stop_path(tmp_path):
    state_path = tmp_path / "lease.json"
    assert wl.release(state_path=str(state_path),
                      conn_factory=lambda: None) == wl.EX_OK  # no state: no conn use

    # State present but registry down: exit 0 anyway (TTL expiry covers it).
    state_path.write_text(json.dumps({"lease_id": "L9"}))

    def down():
        raise ConnectionError("connection refused")

    assert wl.release(state_path=str(state_path), conn_factory=down) == wl.EX_OK
    assert not state_path.exists()
