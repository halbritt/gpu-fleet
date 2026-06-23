"""RFC 0002 Slice 2, hermetic: the global puller-lease CAS grants exactly one holder
and deadman-fails-over to a standby — proven by driving the REAL
`heartbeat_all.acquire_puller_lease` + `PULLER_LEASE_CAS` through `FakeMetaDB`, a tiny
in-memory model of the single fleet_meta row with a controllable clock. No DB.

The matching real-Postgres proof (the CAS on the real `009` fleet_meta DDL, and that no
node ages out of routable_slots across the failover gap) is the guarded
`test_lifecycle_pg.py::test_puller_failover_no_ageout`.
"""

import heartbeat_all as ha


class _Cur:
    def __init__(self, rows):
        self._rows = rows

    def fetchone(self):
        return self._rows[0] if self._rows else None


class FakeMetaDB:
    """Models the single-row `fleet_meta` CAS (`heartbeat_all.PULLER_LEASE_CAS`) against
    an explicit clock. `holder`/`lease_until` are the row; advance() is wall-clock."""

    def __init__(self, *, now=1000.0):
        self.now = float(now)
        self.holder = None
        self.lease_until = None

    def advance(self, seconds):
        self.now += float(seconds)

    def commit(self):
        pass

    def execute(self, sql, params=None):
        assert sql == ha.PULLER_LEASE_CAS, "FakeMetaDB only models PULLER_LEASE_CAS"
        p = params or {}
        free = (self.holder is None
                or (self.lease_until is not None and self.now >= self.lease_until)
                or self.holder == p["me"])
        if not free:
            return _Cur([])
        self.holder = p["me"]
        self.lease_until = self.now + p["ttl"]
        return _Cur([(self.holder,)])


# --------------------------------------------------------------------------- #
# Gate "No SPOF" (A) — CAS grants ONE holder; a standby idles; on the holder's deadman
# expiry the standby acquires within <= TTL.
# --------------------------------------------------------------------------- #
def test_cas_grants_one_then_deadman_failover():
    db = FakeMetaDB()
    assert ha.acquire_puller_lease(db, "A", 15) is True    # A wins the CAS
    assert ha.acquire_puller_lease(db, "B", 15) is False   # B idles (A holds, fresh)
    db.advance(16)                                         # A's 15s lease expires (deadman)
    assert ha.acquire_puller_lease(db, "B", 15) is True    # B takes over within TTL
    assert ha.acquire_puller_lease(db, "A", 15) is False   # now B holds; A idles


def test_holder_renews_its_own_lease_each_tick():
    # The `holder = me` arm lets the current holder renew every tick without losing it.
    db = FakeMetaDB()
    assert ha.acquire_puller_lease(db, "A", 15) is True
    db.advance(5)                                          # within the TTL
    assert ha.acquire_puller_lease(db, "A", 15) is True    # renew, not a takeover
    assert ha.acquire_puller_lease(db, "B", 15) is False   # B still locked out


# --------------------------------------------------------------------------- #
# BC3 — the puller-lease TTL is pinned strictly below the 45s live window, so a killed
# holder's standby refreshes heartbeats before any live slot ages out.
# --------------------------------------------------------------------------- #
def test_puller_lease_ttl_is_below_the_ageout_window():
    assert ha.PULLER_LEASE_TTL < 45
