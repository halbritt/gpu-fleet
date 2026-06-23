"""RFC 0002 writer-side, hermetic: the quarantine->graduate state machine, the
boot-epoch ratchet, and the gpu_uuid identity rules — proven by driving the REAL
`heartbeat.UPSERT` constant through `FakeRegistryDB`, plus source/substring inspection
of the SQL. No DB, no HTTP, no nvidia-smi.

`FakeRegistryDB` recognizes the EXACT production `heartbeat.UPSERT` string and applies
its INSERT ... ON CONFLICT DO UPDATE ... WHERE semantics against a controllable clock —
the same pattern `tests/lease_fakes.FakeSlotDB` uses for the lease SQL. The matching
end-to-end proofs against real Postgres live in the guarded `test_lifecycle_pg.py`
(which also confirms this model agrees with the real DDL).
"""

import heartbeat


GRAD = heartbeat.GRADUATION_STREAK  # 3


# --------------------------------------------------------------------------- #
# A faithful in-memory model of the REAL heartbeat.UPSERT.
# --------------------------------------------------------------------------- #
class _Cur:
    def __init__(self, rows):
        self._rows = rows

    def fetchone(self):
        return self._rows[0] if self._rows else None

    def fetchall(self):
        return list(self._rows)


class FakeRegistryDB:
    """Models `heartbeat.UPSERT` (INSERT ... ON CONFLICT DO UPDATE ... WHERE ratchet)
    with a controllable now(). The test exercises the REAL SQL string; this model
    applies its semantics so the quarantine/ratchet/uuid logic is checkable hermetically.
    epoch movement is modeled by test_heartbeat_epoch / test_epoch_pg, not here."""

    def __init__(self, *, now=1000.0, n=GRAD):
        self.now = float(now)
        self.n = n
        self.rows = {}  # (node, endpoint, slot_id) -> row dict

    def advance(self, seconds):
        self.now += float(seconds)

    def commit(self):
        pass

    def execute(self, sql, params=None):
        assert sql == heartbeat.UPSERT, "FakeRegistryDB only models heartbeat.UPSERT"
        self._upsert(params or {})
        return _Cur([])

    def row_for(self, node, endpoint, slot_id=0):
        return self.rows.get((node, endpoint, slot_id))

    def _upsert(self, p):
        key = (p["node"], p["endpoint"], p["slot_id"])
        old = self.rows.get(key)
        if old is None:
            # INSERT path: seed quarantine (Slice-1 Change B).
            self.rows[key] = {
                "status": "unverified",
                "probe_streak": 1 if p["alive"] else 0,
                "gpu_uuid": p.get("gpu_uuid"),
                "boot_epoch": p.get("boot_epoch"),
                "alive": p["alive"],
                "probe_ms": p.get("probe_ms"),
                "served_model": p.get("served_model"),
                "vram_free_mib": p.get("vram_free"),
                "note": p.get("note"),
                "heartbeat_ts": self.now,
            }
            return
        # CONFLICT path: the BC6 ratchet WHERE decides admission.
        ex_be, old_be = p.get("boot_epoch"), old["boot_epoch"]
        admit = (ex_be is None) or (old_be is None) or (ex_be > old_be)
        if not admit:
            return  # refused: NO field moves, heartbeat_ts NOT re-stamped (BC6)
        old_uuid, ex_uuid = old["gpu_uuid"], p.get("gpu_uuid")
        uuid_changed = (old_uuid is not None and ex_uuid is not None
                        and old_uuid != ex_uuid)
        # probe_streak CASE (reads the OLD streak, exactly like the SQL RHS).
        if not p["alive"]:
            streak = 0
        elif uuid_changed:
            streak = 1
        else:
            streak = old["probe_streak"] + 1
        # status CASE (also reads the OLD streak/status).
        if not p["alive"]:
            status = "unverified"
        elif uuid_changed:
            status = "unverified"
        elif old["status"] == "routable":
            status = "routable"
        elif old["probe_streak"] + 1 >= self.n:
            status = "routable"
        else:
            status = "probationary"
        old["boot_epoch"] = ex_be if ex_be is not None else old_be          # COALESCE
        old["gpu_uuid"] = ex_uuid if ex_uuid is not None else old_uuid       # COALESCE
        old["probe_streak"] = streak
        old["status"] = status
        old["alive"] = p["alive"]
        old["probe_ms"] = p.get("probe_ms")
        old["served_model"] = p.get("served_model")
        old["vram_free_mib"] = p.get("vram_free")
        old["note"] = p.get("note")
        old["heartbeat_ts"] = self.now


NODE, URL = "n", "http://n:8081/v1"


def _row(alive=True, *, gpu_uuid="U1", boot_epoch=None, served_model="m",
         vram_free=24000, probe_ms=10, note=None):
    """A full heartbeat.UPSERT param row (every %(...)s key the SQL names)."""
    return {
        "node": NODE, "endpoint": URL, "slot_id": 0,
        "gpu_model": "RTX 3090", "nvlink": None, "vram_total": 24000,
        "vram_free": vram_free, "util": 5, "loaded_model": served_model if alive else None,
        "served_model": served_model, "max_context": 8192, "latency_class": "batch",
        "free_slots": 1, "epoch": 0, "alive": alive, "probe_ms": probe_ms, "note": note,
        "gpu_uuid": gpu_uuid, "boot_epoch": boot_epoch,
    }


def _tick(db, **over):
    db.execute(heartbeat.UPSERT, _row(**over))
    return db.row_for(NODE, URL)


# --------------------------------------------------------------------------- #
# Gate "Zero-touch register" (C) — graduate unverified -> probationary -> routable
# after N passing probes, and demote on a broken streak.
# --------------------------------------------------------------------------- #
def test_streak_promotes_after_N_and_demotes_on_break():
    db = FakeRegistryDB()
    r = _tick(db)                                  # first heartbeat = registration
    assert r["status"] == "unverified" and r["probe_streak"] == 1
    r = _tick(db)
    assert r["status"] == "probationary" and r["probe_streak"] == 2
    r = _tick(db)                                  # Nth passing probe (N=3)
    assert r["status"] == "routable" and r["probe_streak"] == GRAD
    # A broken streak demotes back to unverified the instant a probe fails.
    r = _tick(db, alive=False)
    assert r["status"] == "unverified" and r["probe_streak"] == 0


# --------------------------------------------------------------------------- #
# Gate "Anti-lie" (E) — a failing/not-ready probe never increments the streak, so a
# node that never actually serves can never graduate itself into routing. (A cold-
# LOADABLE *alive* tick still counts — Q2 — but a failed probe, alive=False, does not.)
# --------------------------------------------------------------------------- #
def test_failing_or_cold_probe_never_increments_streak():
    db = FakeRegistryDB()
    _tick(db)                                      # streak 1
    _tick(db)                                      # streak 2
    r = _tick(db, alive=False)                     # probe fails -> reset, NOT +1
    assert r["probe_streak"] == 0 and r["status"] == "unverified"
    # Repeated failures never accumulate; a single recovery is back at streak 1, not N.
    r = _tick(db, alive=False)
    assert r["probe_streak"] == 0
    r = _tick(db, alive=True)
    assert r["probe_streak"] == 1 and r["status"] != "routable"


# --------------------------------------------------------------------------- #
# Gate "Identity survives churn" (I) — a matching uuid carries routable forward, and a
# NULL incoming uuid (pull) preserves the stored identity and stays routable.
# --------------------------------------------------------------------------- #
def test_matching_uuid_carries_routable_forward():
    db = FakeRegistryDB()
    for _ in range(GRAD):
        _tick(db, gpu_uuid="U1")
    assert db.row_for(NODE, URL)["status"] == "routable"
    # same uuid on a later probe -> stays routable, identity unchanged.
    r = _tick(db, gpu_uuid="U1")
    assert r["status"] == "routable" and r["gpu_uuid"] == "U1"
    # a NULL (pull) uuid report COALESCE-preserves the known identity and stays routable.
    r = _tick(db, gpu_uuid=None)
    assert r["status"] == "routable" and r["gpu_uuid"] == "U1"


# --------------------------------------------------------------------------- #
# BC7 (hermetic state machine) — a change to a KNOWN, different uuid (hot-swapped card)
# resets the streak and re-quarantines to unverified.
# --------------------------------------------------------------------------- #
def test_uuid_mismatch_resets_streak_and_demotes():
    db = FakeRegistryDB()
    for _ in range(GRAD):
        _tick(db, gpu_uuid="U1")
    assert db.row_for(NODE, URL)["status"] == "routable"
    r = _tick(db, gpu_uuid="U2")                   # both known and DIFFERENT
    assert r["status"] == "unverified"
    assert r["probe_streak"] == 1
    assert r["gpu_uuid"] == "U2"                    # COALESCE takes the new measured id


# --------------------------------------------------------------------------- #
# BC6 (substring) — the ratchet predicate is a STRICT '>' (never '>=') so an equal-epoch
# replay is refused. Guards against silently weakening it back to '>='.
# --------------------------------------------------------------------------- #
def test_ratchet_predicate_is_strict_gt():
    where = heartbeat.UPSERT.rsplit("WHERE", 1)[1]   # the DO UPDATE ... WHERE ratchet
    assert "EXCLUDED.boot_epoch > gpu_slots.boot_epoch" in where
    assert ">=" not in where, "the boot_epoch ratchet must be STRICT '>' (BC6)"
    # COALESCE-preservation lives in the SET, so a NULL pull write never erases the stamp.
    assert "boot_epoch = COALESCE(EXCLUDED.boot_epoch, gpu_slots.boot_epoch)" in heartbeat.UPSERT


# --------------------------------------------------------------------------- #
# BC6 (behavioral, hermetic) — drive the real UPSERT: an equal-epoch replay moves no
# field and does not re-stamp heartbeat_ts; a strictly-greater epoch is accepted.
# --------------------------------------------------------------------------- #
def test_equal_epoch_replay_is_a_noop_then_greater_is_accepted():
    db = FakeRegistryDB()
    _tick(db, boot_epoch=500, served_model="m1", probe_ms=10)
    hb0 = db.row_for(NODE, URL)["heartbeat_ts"]
    db.advance(30)                                 # time passes...
    _tick(db, boot_epoch=500, alive=False, served_model="m2", probe_ms=999, note="replay")
    r = db.row_for(NODE, URL)
    assert r["served_model"] == "m1" and r["alive"] is True and r["probe_ms"] == 10
    assert r["note"] != "replay"
    assert r["heartbeat_ts"] == hb0, "equal-epoch replay must NOT re-stamp heartbeat_ts"
    _tick(db, boot_epoch=501, served_model="m3")   # strictly greater -> accepted
    assert db.row_for(NODE, URL)["served_model"] == "m3"


# --------------------------------------------------------------------------- #
# Gate "No node wall-clock" (L) — the UPSERT stamps heartbeat_ts from the DB clock on
# both paths, and the production row dict carries NO heartbeat_ts.
# --------------------------------------------------------------------------- #
class _RecordingConn:
    def __init__(self):
        self.calls = []

    def execute(self, sql, params=None):
        self.calls.append((sql, params or {}))
        return _Cur([])

    def commit(self):
        pass

    def rollback(self):
        pass


def test_upsert_stamps_heartbeat_ts_from_db_clock(monkeypatch):
    # (i) both write paths stamp now(): the VALUES list ends in `now())` (INSERT) and the
    # conflict SET writes `heartbeat_ts=now()`.
    assert "heartbeat_ts=now()" in heartbeat.UPSERT          # conflict path
    assert "now())" in heartbeat.UPSERT                       # INSERT VALUES stamps now()
    # (ii) the production row dict carries NO heartbeat_ts (the node never supplies a
    # timestamp) — drive the REAL heartbeat_once with stubbed probes and inspect the row.
    monkeypatch.setattr(heartbeat, "gpu_stats",
                        lambda cmd, *a, **k: {"gpu_model": "RTX 3090",
                                              "vram_total_mib": 24000, "vram_free_mib": 22000,
                                              "gpu_util_pct": 5, "gpu_uuid": "U1"})
    monkeypatch.setattr(heartbeat, "discover_served_model", lambda *a, **k: "m")
    monkeypatch.setattr(heartbeat, "decode_probe", lambda *a, **k: (True, 7, None))
    import types
    args = types.SimpleNamespace(
        node=NODE, endpoint=URL, slot_id=0, gpu_cmd="nvidia-smi", served_model="m",
        probe_model="m", nvlink_domain=None, max_context=8192, latency_class="batch",
        free_slots=1, min_load_vram_mib=None, epoch=0, timeout=5.0, push=False)
    conn = _RecordingConn()
    heartbeat.heartbeat_once(conn, args)
    sql, row = conn.calls[-1]
    assert sql == heartbeat.UPSERT
    assert "heartbeat_ts" not in row, "the node must not supply heartbeat_ts"
