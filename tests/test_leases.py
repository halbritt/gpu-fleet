"""Hermetic behavior of the lease lifecycle (leases.py) — the companions to the
ephemeral-Postgres tests in test_leases_pg.py.

These drive the REAL claim/renew/release/failover_transfer functions and the REAL
SQL constants through FakeSlotDB, a tiny in-memory Postgres model with a controllable
clock. They prove the lease LOGIC; the DB-only atomicity/concurrency properties (two
transactions racing, true rollback) are what the guarded PG tests add on top.
"""

import pytest

import di_fleet as leases  # the lease lifecycle lives in di_fleet (see CLAIM_LEDGER)
from lease_fakes import FakeChild, FakeSlotDB

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


# =========================================================================== #
# RFC 0003 — stale-router epoch fencing (Slice D). The lease renew gains the epoch
# self-compare (gate-bullet-1) + the BC2 endpoint-turnover freshness term, and the
# BC3 NULL-arm invariants. These drive the REAL LEASE_*_SQL through FakeSlotDB.
# =========================================================================== #

# --------------------------------------------------------------------------- #
# Gate bullet 1 — a served_model bump fences the holder's next renew (forced
# re-pick), proven by mutating the row mid-lease.  (RFC test "A")
# --------------------------------------------------------------------------- #
def test_epoch_change_fences_renew():
    # The claim stamps lease_epoch = the slot's epoch (what the holder routed
    # against). A heartbeat then bumps the slot's epoch (capability changed); the
    # holder's next renew self-compares epoch != lease_epoch -> zero rows -> False.
    db = _db()
    lease = leases.claim(db, SLOT, "consumer-A", ttl_seconds=45)
    row = db.row_for(SLOT)
    assert row["lease_epoch"] == row["epoch"]        # stamped at claim
    row["epoch"] += 1                                 # heartbeat bumps mid-lease
    assert leases.renew(db, lease, ttl_seconds=45) is False  # fenced -> re-pick


def test_epoch_bump_aborts_di_child_in_renew_path():
    # The same fence end-to-end through the renew MONITOR: when the bump makes renew
    # return zero rows, run_leased_shard terminates its di --json child in the SAME
    # control path and raises LeaseLost (the inherited BC1-A abort — RFC 0003 only
    # adds a new REASON renew returns zero rows; it never builds a second renewer).
    db = _db()
    child = FakeChild(runs_forever=True)

    def bumping_sleep(_seconds):
        # One renew interval passes; the node heartbeats a routing-relevant change,
        # bumping epoch. The clock does NOT advance, so the lease is still unexpired
        # and the row still fresh — the epoch mismatch is the ONLY cause of the loss.
        db.row_for(SLOT)["epoch"] += 1

    with pytest.raises(leases.LeaseLost):
        leases.run_leased_shard(
            SLOT, frames=3, flags=[], holder="consumer-A",
            conn_factory=lambda: db, lease_ops=leases.leases,
            child_factory=lambda *a: child,
            ttl_seconds=45, renew_seconds=5, sleep=bumping_sleep)
    assert child.terminated is True  # BC1-A: child killed in the renew path


# --------------------------------------------------------------------------- #
# BC2 — endpoint-turnover fence (hermetic companion of the PG test "H"). A held
# lease is fenced once its leased PK row stops being the live, fresh heartbeated
# endpoint for (node, slot_id), even though the lease itself is unexpired.
# --------------------------------------------------------------------------- #
def test_endpoint_turnover_fences_old_lease():
    old = {"node": "peecee", "endpoint_url": "http://peecee:11434/v1", "slot_id": 0}
    db = FakeSlotDB([old])
    lease = leases.claim(db, old, "consumer-A", ttl_seconds=600)  # long TTL: not expiry
    assert leases.renew(db, lease, ttl_seconds=600) is True       # fresh -> renews fine
    # The node moves (peecee, slot 0) to a NEW endpoint_url (a new PK row); the old PK
    # row stops being heartbeated. Time passes past the 45s window but well within the
    # 600s lease, so the only thing that changed is the old row's freshness.
    db.turnover_endpoint("peecee", 0, "http://peecee:11434/v1", "http://peecee:11435/v1")
    db.advance(60)
    assert leases.renew(db, lease, ttl_seconds=600) is False      # BC2 freshness fence


# --------------------------------------------------------------------------- #
# BC3 — keep the (lease_epoch IS NULL) rollout-drain arm and prove the bypass is
# steady-state-unreachable.  (RFC tests "I", "J", "K")
# --------------------------------------------------------------------------- #
def test_post_rollout_claim_stamps_non_null_lease_epoch():
    # (i) Every post-Slice-D claim stamps a NON-NULL lease_epoch, because epoch is
    # NOT NULL DEFAULT 0 -> the NULL arm is unreachable for any newly-claimed lease.
    db = _db()
    leases.claim(db, SLOT, "consumer-A")
    row = db.row_for(SLOT)
    assert row["lease_epoch"] is not None
    assert row["lease_epoch"] == row["epoch"]


def test_null_lease_epoch_still_renews():
    # (ii) A pre-Slice-D in-flight lease (lease_epoch never stamped -> NULL) still
    # renews — the rollout-drain arm keeps it un-fenced for its one remaining TTL even
    # if the slot's epoch churned, so deploying Slice D evicts no in-flight lease.
    db = _db()
    lease = leases.claim(db, SLOT, "consumer-A", ttl_seconds=45)
    db.row_for(SLOT)["lease_epoch"] = None  # as if stamped by pre-upgrade code (unset)
    db.row_for(SLOT)["epoch"] += 5          # capability churned underneath it
    assert leases.renew(db, lease, ttl_seconds=45) is True


def test_release_clears_lease_epoch_with_lease_id():
    # (ii) release clears lease_epoch TOGETHER with lease_id, so no row ever carries a
    # renewable lease_id alongside a stale lease_epoch (and no NULL-lease_epoch row
    # carries a live lease).
    db = _db()
    lease = leases.claim(db, SLOT, "consumer-A")
    assert db.row_for(SLOT)["lease_epoch"] is not None
    leases.release(db, lease)
    row = db.row_for(SLOT)
    assert row["lease_id"] is None and row["lease_epoch"] is None
