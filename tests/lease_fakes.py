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
                "lease_id": s.get("lease_id"),
                "lease_holder": s.get("lease_holder"),
                "lease_expires": s.get("lease_expires"),
            }

    # ---- test controls ----------------------------------------------------- #
    def advance(self, seconds):
        """Wall-clock passes. The node keeps heartbeating (stays alive); only a
        consumer's lease can lapse — models the RFC's autonomous-deadman clock."""
        with self._lock:
            self.now += float(seconds)
            for r in self.rows.values():
                r["heartbeat_ts"] = self.now

    def close(self):
        # run_leased_shard's finally calls conn.close(); the shared fake survives it.
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
                and row["vram_free_mib"] >= p["model_mib"]
                and self._is_free(row)):
            return []
        self._seq += 1
        lid = f"L{self._seq}"
        row["lease_id"] = lid
        row["lease_holder"] = p["holder"]
        row["lease_expires"] = self.now + p["ttl"]
        self.issued.append(lid)
        return [(lid,)]

    def _renew(self, p):
        for row in self.rows.values():
            if (row["lease_id"] == p["lease_id"]
                    and row["lease_expires"] is not None
                    and self.now < row["lease_expires"]):
                row["lease_expires"] = self.now + p["ttl"]
                return [(row["lease_id"],)]
        return []

    def _release(self, p):
        for row in self.rows.values():
            if row["lease_id"] == p["lease_id"]:
                row["lease_id"] = None
                row["lease_holder"] = None
                row["lease_expires"] = None
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
