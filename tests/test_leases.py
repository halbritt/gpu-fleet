"""Hermetic behavior of the lease lifecycle (leases.py) — the companions to the
ephemeral-Postgres tests in test_leases_pg.py.

These drive the REAL claim/renew/release/failover_transfer functions and the REAL
SQL constants through FakeSlotDB, a tiny in-memory Postgres model with a controllable
clock. They prove the lease LOGIC; the DB-only atomicity/concurrency properties (two
transactions racing, true rollback) are what the guarded PG tests add on top.
"""

import di_fleet as leases  # the lease lifecycle lives in di_fleet (see CLAIM_LEDGER)
from lease_fakes import FakeSlotDB

SLOT = {"node": "proximal", "endpoint_url": "http://proximal:8081/v1", "slot_id": 0}


def _db(**row):
    return FakeSlotDB([{**SLOT, **row}])


# --------------------------------------------------------------------------- #
# claim
# --------------------------------------------------------------------------- #
def test_claim_succeeds_on_free_slot_and_stamps_expiry():
    db = _db()
    lease = leases.claim(db, SLOT, "consumer-A", ttl_seconds=45)
    assert lease is not None
    row = db.row_for(SLOT)
    assert row["lease_id"] == lease
    assert row["lease_holder"] == "consumer-A"
    assert row["lease_expires"] == db.now + 45  # server-stamped now() + ttl


def test_claim_returns_none_when_predicate_unmet():
    # Slot already held by a live, unexpired lease -> a second claim matches 0 rows.
    db = _db(lease_id="other", lease_holder="consumer-B",
             lease_expires=2000.0)  # well in the future relative to now=1000
    assert leases.claim(db, SLOT, "consumer-A") is None


def test_claim_rejected_when_vram_below_model_need():
    db = _db(vram_free_mib=4000)
    assert leases.claim(db, SLOT, "consumer-A", model_mib=20000) is None
    assert leases.claim(db, SLOT, "consumer-A", model_mib=2000) is not None


def test_claim_succeeds_once_lease_has_expired():
    db = _db(lease_id="old", lease_holder="ghost", lease_expires=1005.0)
    assert leases.claim(db, SLOT, "consumer-A") is None  # now=1000 < 1005, still held
    db.advance(10)                                        # now=1010 >= 1005, expired
    assert leases.claim(db, SLOT, "consumer-A") is not None


# --------------------------------------------------------------------------- #
# renew  (zero rows == "lease lost, stop touching the GPU")
# --------------------------------------------------------------------------- #
def test_renew_extends_a_held_lease():
    db = _db()
    lease = leases.claim(db, SLOT, "consumer-A", ttl_seconds=45)
    db.advance(15)
    assert leases.renew(db, lease, ttl_seconds=45) is True
    assert db.row_for(SLOT)["lease_expires"] == db.now + 45


def test_renew_false_after_autonomous_expiry():
    db = _db()
    lease = leases.claim(db, SLOT, "consumer-A", ttl_seconds=45)
    db.advance(50)  # past expiry; consumer never renewed (simulated stall/crash)
    assert leases.renew(db, lease, ttl_seconds=45) is False


def test_zombie_renew_after_reclaim_is_fenced():
    # claim (lease1) -> expire -> re-claim (lease2) -> renew WHERE lease_id=lease1
    # matches 0 rows. The zombie is fenced by identity, not by a clock it controls.
    db = _db()
    lease1 = leases.claim(db, SLOT, "consumer-A", ttl_seconds=45)
    db.advance(50)
    lease2 = leases.claim(db, SLOT, "consumer-B", ttl_seconds=45)
    assert lease2 is not None and lease2 != lease1
    assert leases.renew(db, lease1, ttl_seconds=45) is False  # zombie fenced
    assert leases.renew(db, lease2, ttl_seconds=45) is True   # the live holder is fine


# --------------------------------------------------------------------------- #
# release  (fenced — never clobbers a successor)
# --------------------------------------------------------------------------- #
def test_release_frees_the_slot():
    db = _db()
    lease = leases.claim(db, SLOT, "consumer-A")
    leases.release(db, lease)
    row = db.row_for(SLOT)
    assert row["lease_id"] is None and row["lease_holder"] is None
    assert leases.claim(db, SLOT, "consumer-B") is not None  # immediately re-claimable


def test_release_is_fenced_and_does_not_clobber_a_successor():
    db = _db()
    lease1 = leases.claim(db, SLOT, "consumer-A", ttl_seconds=45)
    db.advance(50)
    lease2 = leases.claim(db, SLOT, "consumer-B", ttl_seconds=45)
    leases.release(db, lease1)  # the zombie tries to release; fenced -> no-op
    assert db.row_for(SLOT)["lease_id"] == lease2  # successor still holds it


# --------------------------------------------------------------------------- #
# failover_transfer  (BC4 — release dead + atomically claim survivor)
# --------------------------------------------------------------------------- #
def _two_slot_db():
    s0 = {"node": "n", "endpoint_url": "http://s0:8081/v1", "slot_id": 0}
    s1 = {"node": "n", "endpoint_url": "http://s1:8081/v1", "slot_id": 1}
    return FakeSlotDB([s0, s1]), s0, s1


def test_failover_transfer_releases_dead_and_claims_survivor():
    db, s0, s1 = _two_slot_db()
    dead = leases.claim(db, s0, "consumer-A")  # the shard that just died holds s0
    out = leases.failover_transfer(db, dead, [s1], "consumer-A")
    assert out is not None and out["slot"] is s1
    assert db.row_for(s0)["lease_id"] is None        # dead lease released
    assert db.row_for(s1)["lease_id"] == out["lease_id"]  # survivor claimed


def test_failover_transfer_no_survivor_releases_dead_lease_immediately():
    # BC4 no-survivor branch: no claimable candidate -> the dead lease is STILL freed
    # right now (not after the TTL), and None is returned so the caller can degrade.
    db, s0, s1 = _two_slot_db()
    dead = leases.claim(db, s0, "consumer-A")
    leases.claim(db, s1, "consumer-B")  # s1 is busy -> not a claimable candidate
    out = leases.failover_transfer(db, dead, [s1], "consumer-A")
    assert out is None
    assert db.row_for(s0)["lease_id"] is None  # freed immediately, no TTL wait
