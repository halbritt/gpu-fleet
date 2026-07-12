"""RFC 0003 epoch-fencing gate — properties only a REAL Postgres can prove: the
heartbeat UPSERT's epoch CASE actually moves (or holds) the BIGINT, the lease renew
self-compare fences a bumped slot, a re-pick stamps the NEW epoch, and the BC2
endpoint-turnover freshness term fences a held lease whose row stopped being the live
heartbeated endpoint.

These also prove the REAL migrations apply cleanly: the fixture builds gpu_slots by
running migrations/001, 007, 008 in order against the ephemeral cluster.

GUARDED exactly like test_leases_pg.py so the default `pytest tests/ -q` stays green
and hermetic:
  * skips if psycopg is not importable;
  * skips unless GPU_FLEET_TEST_DB points at an EPHEMERAL throwaway cluster;
  * refuses to run against the live `gpu_fleet` database.

Provide an ephemeral DB to run, e.g.:
    GPU_FLEET_TEST_DB='dbname=gpu_fleet_test host=/tmp/pgtest' pytest tests/test_epoch_pg.py -q
"""

import json
import os
import urllib.error

import pytest

psycopg = pytest.importorskip("psycopg")

TEST_DB = os.environ.get("GPU_FLEET_TEST_DB")
if not TEST_DB:
    pytest.skip("set GPU_FLEET_TEST_DB to an ephemeral throwaway cluster to run these",
                allow_module_level=True)
# Safety: never run the destructive DDL against the live registry.
_dbnames = {tok.split("=", 1)[1] for tok in TEST_DB.split() if tok.startswith("dbname=")}
if _dbnames and any(n == "gpu_fleet" or "test" not in n for n in _dbnames):
    pytest.skip("refusing to run epoch tests against a non-ephemeral DB "
                f"({_dbnames}); use a throwaway cluster whose dbname contains 'test'",
                allow_module_level=True)

import di_fleet as leases  # noqa: E402  lease lifecycle lives in di_fleet (CLAIM_LEDGER)
import heartbeat  # noqa: E402  the real UPSERT + sticky discover_served_model

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
_MIGRATIONS = os.path.join(_ROOT, "migrations")
# The real migrations that shape gpu_slots: 001 creates it (with epoch), 002 creates
# fleet_nodes (009 alters it), 007 adds the lease columns + capacity, 008 adds
# lease_epoch, 009 adds the RFC-0002 status/probe_streak/gpu_uuid/boot_epoch columns the
# revised UPSERT writes + fleet_meta + routable_slots. Applying them proves they apply
# cleanly AND that the SQL under test runs against the real schema.
_FILES = ("001_gpu_slots.sql", "002_fleet_nodes.sql", "007_exclusive_slot_leases.sql",
          "008_lease_epoch.sql", "009_zero_touch_lifecycle.sql",
          # RFC 0005: 010 adds mig_mode/ecc_mode (the revised UPSERT writes them) +
          # the companion/policy/model tables + capacity_slots view. Applying it proves
          # 010 lands cleanly on the real schema the UPSERT now targets.
          "010_exporter_capacity_signal.sql")

NODE, URL, SLOT_ID = "t", "http://t:8081/v1", 0
SLOT = {"node": NODE, "endpoint_url": URL, "slot_id": SLOT_ID}


def _apply_migrations(conn):
    # gpu_slots CASCADE also drops live_slots + routable_slots (009); fleet_nodes /
    # fleet_meta are dropped explicitly so re-applying 002/009 (CREATE TABLE without
    # IF NOT EXISTS for fleet_nodes) is idempotent across the function-scoped fixture.
    conn.execute("DROP TABLE IF EXISTS gpu_slots CASCADE")
    conn.execute("DROP TABLE IF EXISTS fleet_nodes CASCADE")
    conn.execute("DROP TABLE IF EXISTS fleet_meta CASCADE")
    conn.execute("CREATE EXTENSION IF NOT EXISTS pgcrypto")  # gen_random_uuid on < PG13
    for fname in _FILES:
        with open(os.path.join(_MIGRATIONS, fname), encoding="utf-8") as f:
            conn.execute(f.read())


def _hb_row(**over):
    """A full heartbeat.UPSERT param row with safe defaults; override per test."""
    row = {
        "node": NODE, "endpoint": URL, "slot_id": SLOT_ID,
        "gpu_model": "RTX 3090", "nvlink": None,
        "vram_total": 24000, "vram_free": 22000, "util": 5,
        "loaded_model": "llama-3", "served_model": "llama-3", "max_context": 8192,
        "latency_class": "batch", "free_slots": 1, "epoch": 0,
        "alive": True, "probe_ms": 12, "note": None,
        "probe_verified": True,
        # RFC 0002 columns the revised UPSERT writes; pull-style defaults (boot_epoch
        # NULL => ratchet inert, gpu_uuid NULL => identity unknown) keep these epoch
        # tests focused on `epoch`, not the quarantine ratchet.
        # RFC 0005: mig_mode/ecc_mode default NULL => the new epoch-CASE terms are inert
        # (NULL IS DISTINCT FROM NULL is false), so these tests stay focused on the
        # served_model/nvlink/max_context bumps unless a test sets them explicitly.
        "gpu_uuid": None, "boot_epoch": None, "mig_mode": None, "ecc_mode": None,
    }
    row.update(over)
    return row


def _seed_routable(conn, **over):
    """Seed a slot via the REAL UPSERT, then graduate it. A fresh UPSERT correctly
    enters status='unverified' (RFC 0002), but the Slice-4 claim gate requires
    'routable'; these epoch tests exercise the lease lifecycle, not graduation, so we
    mark it routable once. Later same-uuid alive ticks keep it routable (the CASE)."""
    conn.execute(heartbeat.UPSERT, _hb_row(**over))
    conn.execute("UPDATE gpu_slots SET status = 'routable'")


def _epoch(conn):
    return conn.execute("SELECT epoch FROM gpu_slots WHERE endpoint_url=%s",
                        (URL,)).fetchone()[0]


def _lease_epoch(conn):
    return conn.execute("SELECT lease_epoch FROM gpu_slots WHERE endpoint_url=%s",
                        (URL,)).fetchone()[0]


@pytest.fixture()
def db():
    with psycopg.connect(TEST_DB, autocommit=True) as setup:
        _apply_migrations(setup)

    def connect():
        return psycopg.connect(TEST_DB, autocommit=True)

    yield connect
    with psycopg.connect(TEST_DB, autocommit=True) as teardown:
        teardown.execute("DROP TABLE IF EXISTS gpu_slots CASCADE")
        teardown.execute("DROP TABLE IF EXISTS fleet_nodes CASCADE")
        teardown.execute("DROP TABLE IF EXISTS fleet_meta CASCADE")


# --------------------------------------------------------------------------- #
# Gate bullet 1 — a served_model bump makes the holder's next renew return zero
# rows, proven by driving the REAL UPSERT mid-lease.  ("B")
# --------------------------------------------------------------------------- #
def test_served_model_bump_fences_renew(db):
    conn = db()
    _seed_routable(conn, served_model="llama-3")  # seed via real UPSERT, then graduate
    assert _epoch(conn) == 0
    lease = leases.claim(conn, SLOT, "consumer-A")  # routes against epoch 0
    assert lease is not None
    # The node swaps served_model -> the conflict path bumps epoch by 1.
    conn.execute(heartbeat.UPSERT, _hb_row(served_model="mistral"))
    assert _epoch(conn) == 1, "served_model change must bump epoch"
    # The holder's stamped lease_epoch (0) no longer matches epoch (1) -> zero rows.
    assert leases.renew(conn, lease) is False


# --------------------------------------------------------------------------- #
# Gate bullet 2 — a VRAM/util-only change does NOT bump epoch and does NOT
# invalidate a lease, proven against real Postgres.  ("C")
# --------------------------------------------------------------------------- #
def test_vram_util_only_change_keeps_epoch_and_lease(db):
    conn = db()
    _seed_routable(conn, vram_free=22000, util=5)
    lease = leases.claim(conn, SLOT, "consumer-A")
    assert lease is not None
    # Only VRAM/util churn — NOT a routing-relevant field.
    conn.execute(heartbeat.UPSERT, _hb_row(vram_free=9000, util=97))
    assert _epoch(conn) == 0, "VRAM/util churn must NOT bump epoch"
    assert leases.renew(conn, lease) is True, "a non-bump tick must not fence the lease"


# --------------------------------------------------------------------------- #
# Gate bullet 3 — a re-pick after a bump stamps and renews against the NEW epoch,
# never the stale one.  ("F")
# --------------------------------------------------------------------------- #
def test_repick_after_bump_stamps_new_epoch(db):
    conn = db()
    _seed_routable(conn, served_model="llama-3")
    lease1 = leases.claim(conn, SLOT, "consumer-A")
    conn.execute(heartbeat.UPSERT, _hb_row(served_model="mistral"))  # capability changed
    assert _epoch(conn) == 1
    assert leases.renew(conn, lease1) is False  # old lease fenced
    # The consumer re-picks: release the dead lease and claim afresh. The new claim
    # stamps lease_epoch = the NEW epoch (1), so its renew succeeds against the new
    # capability — never the stale epoch 0.
    leases.release(conn, lease1)
    lease2 = leases.claim(conn, SLOT, "consumer-A")
    assert lease2 is not None and lease2 != lease1
    assert _lease_epoch(conn) == 1, "re-pick must stamp the NEW epoch"
    assert leases.renew(conn, lease2) is True


# --------------------------------------------------------------------------- #
# BC2 — endpoint-turnover fence: a held lease whose leased PK row stops being the
# live, fresh heartbeated endpoint for (node, slot_id) fails renew.  ("H")
# --------------------------------------------------------------------------- #
def test_endpoint_turnover_fences_old_lease(db):
    conn = db()
    old_url, new_url = "http://peecee:11434/v1", "http://peecee:11435/v1"
    old = {"node": "peecee", "endpoint_url": old_url, "slot_id": 0}
    _seed_routable(conn, node="peecee", endpoint=old_url)
    lease = leases.claim(conn, old, "consumer-A", ttl_seconds=600)  # long TTL: not expiry
    assert lease is not None
    assert leases.renew(conn, lease, ttl_seconds=600) is True  # still fresh -> renews

    # The node turns over to a NEW endpoint_url (a new PK row, freshly heartbeated) and
    # STOPS heartbeating the old PK row. Backdate the old row's heartbeat_ts past the
    # 45s live window (it is no longer refreshed) while its lease is still unexpired.
    conn.execute(heartbeat.UPSERT, _hb_row(node="peecee", endpoint=new_url))
    conn.execute(
        "UPDATE gpu_slots SET heartbeat_ts = now() - interval '60 seconds' "
        "WHERE node='peecee' AND endpoint_url=%s", (old_url,))
    # Unexpired lease, but the leased row is no longer the live/fresh endpoint -> the
    # BC2 freshness term fails -> zero rows.
    assert leases.renew(conn, lease, ttl_seconds=600) is False


# --------------------------------------------------------------------------- #
# BC1 (optional PG companion) — sticky discovery keeps epoch stable across a
# good -> transient-fail -> good tick sequence driven through the REAL UPSERT.
# --------------------------------------------------------------------------- #
class _Resp:
    def __init__(self, payload):
        self._data = json.dumps(payload).encode()

    def read(self):
        return self._data

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False


def test_sticky_discovery_keeps_epoch_stable(db, monkeypatch):
    heartbeat.reset_discovery_cache()
    conn = db()
    ep = SLOT["endpoint_url"]
    seq = {"n": 0}

    def fake_urlopen(url, timeout=None):
        seq["n"] += 1
        if seq["n"] == 2:  # the MIDDLE tick's /models transiently fails
            raise urllib.error.URLError("blip")
        return _Resp({"data": [{"id": "llama-3"}]})

    monkeypatch.setattr(heartbeat.urllib.request, "urlopen", fake_urlopen)

    # good -> transient-fail -> good. Each tick resolves served_model via the REAL
    # sticky discovery and writes it through the REAL UPSERT. A NON-sticky discovery
    # would flap served_model to the static fallback on tick 2 and bump epoch twice;
    # stickiness holds served_model — and thus epoch — constant.
    for _ in range(3):
        served = heartbeat.discover_served_model(ep, "cfg-fallback")
        conn.execute(heartbeat.UPSERT, _hb_row(served_model=served))
    assert _epoch(conn) == 0, "sticky discovery must keep epoch stable across a blip"
