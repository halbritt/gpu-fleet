"""Hermetic fakes for the RFC 0001 lease tests — no real DB, subprocess, or clock.

`FakeSlotDB` is a tiny in-memory Postgres stand-in that recognizes the EXACT SQL
constants in leases.py and applies their semantics against an explicit, controllable
clock (`self.now`, seconds). Tests therefore drive the REAL claim/renew/release seam
(the production `leases.*` functions, the production SQL) with zero database, and
model autonomous wall-clock expiry by advancing the clock. `lease_id` values are
deterministic counter tokens (L1, L2, …) so distinctness assertions are stable.

`FakeChild` stands in for a `di --json` Popen so a renew monitor can poll / wait /
terminate / kill it without launching a process.

Not a `test_*` module, so pytest does not collect it.
"""

import threading

import di_fleet as leases  # the lease lifecycle lives in di_fleet (see CLAIM_LEDGER)


class _Cursor:
    def __init__(self, rows):
        self._rows = rows

    def fetchone(self):
        return self._rows[0] if self._rows else None

    def fetchall(self):
        return list(self._rows)


class FakeSlotDB:
    def __init__(self, slots, *, now=1000.0):
        self.now = float(now)
        self._lock = threading.Lock()
        self._seq = 0
        self.issued = []  # every lease_id ever handed out, in order
        self.rows = {}    # (node, endpoint_url, slot_id) -> row dict
        for s in slots:
            key = (s["node"], s["endpoint_url"], s.get("slot_id", 0))
            self.rows[key] = {
                "node": s["node"],
                "endpoint_url": s["endpoint_url"],
                "slot_id": s.get("slot_id", 0),
                "alive": s.get("alive", True),
                "heartbeat_ts": self.now,
                "vram_free_mib": s.get("vram_free_mib", 24000),
                # RFC 0002: the consumer claim gate requires a GRADUATED slot. Default
                # 'routable' so existing lease tests (which build live slots) claim as
                # before; a test can seed 'unverified' to prove the gate excludes it.
                "status": s.get("status", "routable"),
                # RFC 0003: epoch is the change-counter; lease_epoch is what the
                # holder routed against (stamped at claim, cleared at release).
                "epoch": s.get("epoch", 0),
                "lease_id": s.get("lease_id"),
                "lease_holder": s.get("lease_holder"),
                "lease_expires": s.get("lease_expires"),
                "lease_epoch": s.get("lease_epoch"),
                # Whether this PK row is still being heartbeated. advance() refreshes
                # only heartbeating rows, so a turned-over endpoint (BC2) can AGE out
                # of the 45s live window while the rest of the fleet stays fresh.
                "_heartbeating": s.get("_heartbeating", True),
            }

    # ---- test controls ----------------------------------------------------- #
    def advance(self, seconds):
        """Wall-clock passes. A node that is still heartbeating keeps its row fresh
        (stays alive); only a consumer's lease can lapse — models the RFC's
        autonomous-deadman clock. A row marked `_heartbeating=False` (an endpoint that
        turned over, BC2) is NOT refreshed, so it ages out of the 45s live window."""
        with self._lock:
            self.now += float(seconds)
            for r in self.rows.values():
                if r["_heartbeating"]:
                    r["heartbeat_ts"] = self.now

    def turnover_endpoint(self, node, slot_id, old_url, new_url, *, epoch=0):
        """Model BC2 endpoint turnover: the node moves (node, slot_id) to a NEW
        endpoint_url — a new, freshly-heartbeated PK row — and STOPS heartbeating the
        OLD PK row (which still holds its lease). After a subsequent advance() past the
        45s window, the old row ages out of `live_slots` while its lease is unexpired,
        so its renew is fenced by the freshness term."""
        with self._lock:
            old = self.rows[(node, old_url, slot_id)]
            old["_heartbeating"] = False  # no longer refreshed -> heartbeat_ts ages out
            key = (node, new_url, slot_id)
            self.rows[key] = {
                "node": node, "endpoint_url": new_url, "slot_id": slot_id,
                "alive": True, "heartbeat_ts": self.now, "vram_free_mib": 24000,
                "status": "routable", "epoch": epoch, "lease_id": None,
                "lease_holder": None, "lease_expires": None, "lease_epoch": None,
                "_heartbeating": True,
            }

    def close(self):
        # run_leased_shard's finally calls conn.close(); the shared fake survives it.
        pass

    def commit(self):
        # The transfer conn commits once; this in-memory model applies writes eagerly,
        # so commit is a no-op. True commit/rollback atomicity is proven against a real
        # Postgres in test_leases_pg.py::test_failover_transfer_is_atomic.
        pass

    def rollback(self):
        pass

    def row_for(self, slot):
        return self.rows[(slot["node"], slot["endpoint_url"], slot.get("slot_id", 0))]

    # ---- the psycopg-ish surface leases.* calls ---------------------------- #
    def execute(self, sql, params=None):
        params = params or {}
        with self._lock:
            if sql == leases.LEASE_CLAIM_SQL:
                return _Cursor(self._claim(params))
            if sql == leases.LEASE_RENEW_SQL:
                return _Cursor(self._renew(params))
            if sql == leases.LEASE_RELEASE_SQL:
                return _Cursor(self._release(params))
            raise AssertionError(f"FakeSlotDB got SQL it does not model:\n{sql}")

    def _fresh(self, row):
        return row["alive"] and (self.now - row["heartbeat_ts"]) < 45

    def _is_free(self, row):
        return row["lease_id"] is None or (
            row["lease_expires"] is not None and self.now >= row["lease_expires"]
        )

    def _claim(self, p):
        row = self.rows.get((p["node"], p["endpoint_url"], p["slot_id"]))
        if row is None:
            return []
        if not (self._fresh(row)
                and row["status"] == "routable"  # RFC 0002 Slice-4 quarantine gate
                and row["vram_free_mib"] >= p["model_mib"]
                and self._is_free(row)):
            return []
        self._seq += 1
        lid = f"L{self._seq}"
        row["lease_id"] = lid
        row["lease_holder"] = p["holder"]
        row["lease_expires"] = self.now + p["ttl"]
        row["lease_epoch"] = row["epoch"]  # RFC 0003 D.1: stamp the epoch routed against
        self.issued.append(lid)
        return [(lid,)]

    def _renew(self, p):
        for row in self.rows.values():
            # RFC 0003 D.2: the renew predicate now also requires the slot's epoch to
            # still match what was stamped (NULL arm = pre-Slice-D in-flight lease, BC3)
            # AND the leased row to still be the live, fresh heartbeated endpoint (BC2).
            if (row["lease_id"] == p["lease_id"]
                    and row["lease_expires"] is not None
                    and self.now < row["lease_expires"]
                    and (row["lease_epoch"] is None
                         or row["epoch"] == row["lease_epoch"])
                    and self._fresh(row)):
                row["lease_expires"] = self.now + p["ttl"]
                return [(row["lease_id"],)]
        return []

    def _release(self, p):
        for row in self.rows.values():
            if row["lease_id"] == p["lease_id"]:
                row["lease_id"] = None
                row["lease_holder"] = None
                row["lease_expires"] = None
                row["lease_epoch"] = None  # RFC 0003 D.3/BC3: cleared WITH lease_id
        return []


class FakeChild:
    """Stand-in for a `di --json` child. runs_forever=True -> poll() returns None
    (still running) until terminate()/kill(); otherwise already finished."""

    def __init__(self, *, returncode=0, stdout="{}", stderr="", runs_forever=False):
        self._stdout = stdout
        self._stderr = stderr
        self.returncode = None if runs_forever else returncode
        self.terminated = False
        self.killed = False

    def poll(self):
        return self.returncode

    def wait(self, timeout=None):
        return self.returncode

    def terminate(self):
        self.terminated = True
        if self.returncode is None:
            self.returncode = -15  # SIGTERM

    def kill(self):
        self.killed = True
        if self.returncode is None:
            self.returncode = -9  # SIGKILL

    def read_stdout(self):
        return self._stdout

    def read_stderr(self):
        return self._stderr
