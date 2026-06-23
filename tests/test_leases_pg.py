"""RFC 0001 lease gate — properties only a REAL Postgres can prove: atomic claim
under true concurrency, autonomous self-expiry, zombie fencing, and atomic failover
transfer (release + claim commit-or-rollback together).

GUARDED so the default `pytest tests/ -q` stays green and hermetic:
  * skips if psycopg is not importable;
  * skips unless GPU_FLEET_TEST_DB points at an EPHEMERAL throwaway cluster;
  * refuses to run against the live `gpu_fleet` database.

Provide an ephemeral DB to run, e.g. a disposable `CREATE DATABASE`:
    GPU_FLEET_TEST_DB='dbname=gpu_fleet_test host=/tmp/pgtest' pytest tests/test_leases_pg.py -q
"""

import os
import threading

import pytest

psycopg = pytest.importorskip("psycopg")

TEST_DB = os.environ.get("GPU_FLEET_TEST_DB")
if not TEST_DB:
    pytest.skip("set GPU_FLEET_TEST_DB to an ephemeral throwaway cluster to run these",
                allow_module_level=True)
# Safety: never run the destructive DDL against the live registry. The ephemeral DB
# must be a throwaway whose name contains 'test' and is not the bare 'gpu_fleet'.
_dbnames = {tok.split("=", 1)[1] for tok in TEST_DB.split() if tok.startswith("dbname=")}
if _dbnames and any(n == "gpu_fleet" or "test" not in n for n in _dbnames):
    pytest.skip("refusing to run lease tests against a non-ephemeral DB "
                f"({_dbnames}); use a throwaway cluster whose dbname contains 'test'",
                allow_module_level=True)

import di_fleet as leases  # noqa: E402  lease lifecycle lives in di_fleet (CLAIM_LEDGER)

SLOT = {"node": "t", "endpoint_url": "http://t:8081/v1", "slot_id": 0}
SLOT2 = {"node": "t", "endpoint_url": "http://t2:8081/v1", "slot_id": 1}

_DDL = """
CREATE EXTENSION IF NOT EXISTS pgcrypto;
DROP TABLE IF EXISTS gpu_slots;
CREATE TABLE gpu_slots (
    node          TEXT NOT NULL,
    endpoint_url  TEXT NOT NULL,
    slot_id       INT  NOT NULL DEFAULT 0,
    vram_free_mib INT,
    capacity      INT  NOT NULL DEFAULT 1 CHECK (capacity >= 1),
    lease_id      UUID,
    lease_holder  TEXT,
    lease_expires TIMESTAMPTZ,
    -- RFC 0003: Slice D modifies the shared LEASE_CLAIM_SQL/LEASE_RENEW_SQL these
    -- tests exercise (it stamps/compares epoch and lease_epoch), so this temp DDL
    -- must carry both columns or the lease PG suite would error under GPU_FLEET_TEST_DB.
    epoch         BIGINT NOT NULL DEFAULT 0,
    lease_epoch   BIGINT,
    -- RFC 0002: the Slice-4 claim gate adds `AND status = 'routable'` to LEASE_CLAIM_SQL,
    -- so this temp DDL must carry the column or the lease PG suite would error. Default
    -- 'routable' so the seeded live slots are claimable exactly as before this RFC.
    status        TEXT NOT NULL DEFAULT 'routable'
        CHECK (status IN ('unverified','probationary','routable','demoted')),
    alive         BOOLEAN NOT NULL DEFAULT true,
    heartbeat_ts  TIMESTAMPTZ NOT NULL DEFAULT now(),
    PRIMARY KEY (node, endpoint_url, slot_id)
);
"""


def _seed(conn, *slots):
    conn.execute("DELETE FROM gpu_slots")
    for s in slots:
        conn.execute(
            "INSERT INTO gpu_slots (node, endpoint_url, slot_id, vram_free_mib,"
            " alive, heartbeat_ts) VALUES (%s,%s,%s,24000,true, now())",
            (s["node"], s["endpoint_url"], s["slot_id"]))


@pytest.fixture()
def db():
    with psycopg.connect(TEST_DB, autocommit=True) as setup:
        setup.execute(_DDL)
        _seed(setup, SLOT, SLOT2)

    def connect():
        return psycopg.connect(TEST_DB, autocommit=True)

    yield connect
    with psycopg.connect(TEST_DB, autocommit=True) as teardown:
        teardown.execute("DROP TABLE IF EXISTS gpu_slots")


def test_two_concurrent_claims_exactly_one_wins(db):
    # Two real connections race the conditional CLAIM on one capacity-1 slot. Row-level
    # locking serializes them; exactly one RETURNs a lease, the loser gets zero rows.
    results = []
    barrier = threading.Barrier(2)

    def race(holder):
        conn = db()
        barrier.wait()
        results.append(leases.claim(conn, SLOT, holder))
        conn.close()

    threads = [threading.Thread(target=race, args=(f"c{i}",)) for i in range(2)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()

    assert sum(1 for r in results if r is not None) == 1, results


def test_unrenewed_lease_self_expires(db):
    # A consumer that stops renewing (simulated crash) frees the slot within <= TTL,
    # with NO reaper running — only the two test connections exist.
    conn = db()
    assert leases.claim(conn, SLOT, "crasher", ttl_seconds=1) is not None
    # Do not renew. After the TTL passes, a fresh claim succeeds (autonomous expiry).
    other = db()
    assert leases.claim(other, SLOT, "successor", ttl_seconds=1) is None  # still held
    import time
    time.sleep(1.2)  # wall-clock only; expiry is decided by Postgres now(), not this
    assert leases.claim(other, SLOT, "successor", ttl_seconds=45) is not None


def test_zombie_renew_after_reclaim_is_fenced(db):
    conn = db()
    lease1 = leases.claim(conn, SLOT, "a", ttl_seconds=1)
    assert lease1 is not None
    import time
    time.sleep(1.2)
    lease2 = leases.claim(conn, SLOT, "b", ttl_seconds=45)
    assert lease2 is not None and lease2 != lease1
    # The zombie (lease1) renews -> fenced by lease_id -> zero rows -> False.
    assert leases.renew(conn, lease1, ttl_seconds=45) is False
    assert leases.renew(conn, lease2, ttl_seconds=45) is True


def test_failover_transfer_is_atomic(db):
    # The transfer's release(dead) + claim(survivor) must commit together or roll back
    # together. Force a mid-transfer failure (rollback) and assert NEITHER side stuck:
    # the dead lease is NOT released and the survivor is NOT claimed.
    setup = db()
    dead = leases.claim(setup, SLOT, "dead-shard")  # SLOT held, SLOT2 free
    assert dead is not None

    conn = psycopg.connect(TEST_DB)  # NOT autocommit: one explicit transaction
    try:
        out = leases.failover_transfer(conn, dead, [SLOT2], "survivor")
        assert out is not None and out["slot"] is SLOT2  # both ops applied in-tx
        conn.rollback()  # the "mid-transfer failure"
    finally:
        conn.close()

    check = db()
    row1 = check.execute(
        "SELECT lease_id FROM gpu_slots WHERE endpoint_url=%s",
        (SLOT["endpoint_url"],)).fetchone()
    row2 = check.execute(
        "SELECT lease_id FROM gpu_slots WHERE endpoint_url=%s",
        (SLOT2["endpoint_url"],)).fetchone()
    assert str(row1[0]) == str(dead), "rollback must restore the dead lease"
    assert row2[0] is None, "rollback must un-claim the survivor"
