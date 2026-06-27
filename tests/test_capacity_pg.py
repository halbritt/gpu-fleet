"""RFC 0005 — exporter-fed capacity signal, the gate proofs only a REAL Postgres can give:
the freshness decay actually fires in SQL, within-band churn is a byte-identical no-op, a
MIG/ECC crossing bumps epoch and fences a held lease, the headroom predicate routes on the
LOWER (probe) number and refuses an oversized context, the puller actually writes a
companion row, migration 010 re-applies idempotently with a singleton policy, and the
policy/model joins never multiply a slot row.

These also prove the REAL migrations apply cleanly: the fixture runs migrations/001, 002,
007, 008, 009, 010 in order against the ephemeral cluster (so it also proves 010 lands on
the real schema the revised UPSERT targets).

GUARDED exactly like test_epoch_pg.py so the default `pytest tests/ -q` stays green and
hermetic:
  * skips if psycopg is not importable;
  * skips unless GPU_FLEET_TEST_DB points at an EPHEMERAL throwaway cluster;
  * refuses to run against the live `gpu_fleet` database.

    GPU_FLEET_TEST_DB='dbname=gpu_fleet_test host=/tmp/pgtest' pytest tests/test_capacity_pg.py -q
"""

import os

import pytest

psycopg = pytest.importorskip("psycopg")

TEST_DB = os.environ.get("GPU_FLEET_TEST_DB")
if not TEST_DB:
    pytest.skip("set GPU_FLEET_TEST_DB to an ephemeral throwaway cluster to run these",
                allow_module_level=True)
_dbnames = {tok.split("=", 1)[1] for tok in TEST_DB.split() if tok.startswith("dbname=")}
if _dbnames and any(n == "gpu_fleet" or "test" not in n for n in _dbnames):
    pytest.skip("refusing to run capacity tests against a non-ephemeral DB "
                f"({_dbnames}); use a throwaway cluster whose dbname contains 'test'",
                allow_module_level=True)

import di_fleet as leases  # noqa: E402  lease lifecycle lives in di_fleet (CLAIM_LEDGER)
import heartbeat  # noqa: E402  the real UPSERT + CAPACITY_UPSERT
import pick_slot  # noqa: E402  the real headroom PICK

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
_MIGRATIONS = os.path.join(_ROOT, "migrations")
_FILES = ("001_gpu_slots.sql", "002_fleet_nodes.sql", "007_exclusive_slot_leases.sql",
          "008_lease_epoch.sql", "009_zero_touch_lifecycle.sql",
          "010_exporter_capacity_signal.sql")

NODE, URL, SLOT_ID = "t", "http://t:8081/v1", 0
SLOT = {"node": NODE, "endpoint_url": URL, "slot_id": SLOT_ID}


def _apply_migrations(conn):
    # gpu_slots CASCADE also drops live_slots/routable_slots/capacity_slots (the view
    # depends on gpu_slots); the tables/columns are recreated by the chain below.
    conn.execute("DROP TABLE IF EXISTS gpu_slots CASCADE")
    conn.execute("DROP TABLE IF EXISTS fleet_nodes CASCADE")
    conn.execute("DROP TABLE IF EXISTS fleet_meta CASCADE")
    conn.execute("DROP TABLE IF EXISTS gpu_slots_capacity CASCADE")
    conn.execute("DROP TABLE IF EXISTS capacity_policy CASCADE")
    conn.execute("DROP TABLE IF EXISTS model_capacity CASCADE")
    conn.execute("CREATE EXTENSION IF NOT EXISTS pgcrypto")
    for fname in _FILES:
        with open(os.path.join(_MIGRATIONS, fname), encoding="utf-8") as f:
            conn.execute(f.read())


def _apply_010(conn):
    with open(os.path.join(_MIGRATIONS, "010_exporter_capacity_signal.sql"),
              encoding="utf-8") as f:
        conn.execute(f.read())


def _hb_row(**over):
    """A full heartbeat.UPSERT param row with safe defaults; override per test."""
    row = {
        "node": NODE, "endpoint": URL, "slot_id": SLOT_ID,
        "gpu_model": "RTX 3090", "nvlink": None,
        "vram_total": 24000, "vram_free": 22000, "util": 5,
        "loaded_model": "m", "served_model": "m", "max_context": 8192,
        "latency_class": "batch", "free_slots": 1, "epoch": 0,
        "alive": True, "probe_ms": 12, "note": None,
        "gpu_uuid": None, "boot_epoch": None, "mig_mode": None, "ecc_mode": None,
    }
    row.update(over)
    return row


def _seed_routable(conn, **over):
    conn.execute(heartbeat.UPSERT, _hb_row(**over))
    conn.execute("UPDATE gpu_slots SET status = 'routable'")


def _cap_params(*, node=NODE, endpoint=URL, slot_id=SLOT_ID, cold_probe_ms=10,
                probe_floor_mib=8000, exporter_free_mib=None, effective_free_mib=8000,
                util_band=0, power_w=None, temp_c=None, phantom_mib=0, phantom_pids=0,
                capacity_source="measured", fast_source_age_s=0, slow_source_age_s=0):
    return {"node": node, "endpoint": endpoint, "slot_id": slot_id,
            "cold_probe_ms": cold_probe_ms, "probe_floor_mib": probe_floor_mib,
            "exporter_free_mib": exporter_free_mib, "effective_free_mib": effective_free_mib,
            "util_band": util_band, "power_w": power_w, "temp_c": temp_c,
            "phantom_mib": phantom_mib, "phantom_pids": phantom_pids,
            "capacity_source": capacity_source, "fast_source_age_s": fast_source_age_s,
            "slow_source_age_s": slow_source_age_s}


def _insert_companion(conn, *, effective=8000, source="measured", fast_age=0,
                      updated_secs_ago=0, exporter=None, node=NODE, endpoint=URL,
                      slot_id=SLOT_ID):
    conn.execute(
        "INSERT INTO gpu_slots_capacity (node, endpoint_url, slot_id, effective_free_mib, "
        "exporter_free_mib, probe_floor_mib, capacity_source, fast_source_age_s, updated_ts) "
        "VALUES (%s, %s, %s, %s, %s, %s, %s, %s, now() - make_interval(secs => %s))",
        (node, endpoint, slot_id, effective, exporter, effective, source, fast_age,
         updated_secs_ago))


def _epoch(conn):
    return conn.execute("SELECT epoch FROM gpu_slots WHERE endpoint_url=%s",
                        (URL,)).fetchone()[0]


def _companion(conn, col):
    return conn.execute(f"SELECT {col} FROM gpu_slots_capacity WHERE endpoint_url=%s",
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
        teardown.execute("DROP TABLE IF EXISTS gpu_slots_capacity CASCADE")
        teardown.execute("DROP TABLE IF EXISTS capacity_policy CASCADE")
        teardown.execute("DROP TABLE IF EXISTS model_capacity CASCADE")


# =========================================================================== #
# Gate bullet 1 — BC2 single-clock decay actually fires in SQL (A3 frozen, A4 fresh).
# =========================================================================== #
def test_frozen_source_decays_out_of_pick(db):
    conn = db()
    _seed_routable(conn)
    # A companion row with NO writer touching it for > k*half_life (default 3*30 = 90s):
    # now()-updated_ts crosses the threshold, so the decayed capacity_source is 'stale' and
    # the decayed effective_free is NULL (the reader COALESCEs through to vram_free_mib).
    _insert_companion(conn, effective=8000, source="measured", fast_age=0,
                      updated_secs_ago=120)
    picked = pick_slot.pick(conn, model="m", k=5)
    assert len(picked) == 1
    assert picked[0]["capacity_source"] == "stale"
    assert picked[0]["effective_free_mib"] is None
    assert picked[0]["degraded"] is True


def test_db_skew_keeps_fresh_slot_measured(db):
    conn = db()
    _seed_routable(conn)
    # A fresh write (updated_ts = now(), a node-clock fast_source_age_s of a few seconds)
    # stays 'measured'. updated_ts is stamped by the DB clock and fast_source_age_s by the
    # node clock — the two are NEVER subtracted from each other, so a node<->DB NTP skew is
    # not load-bearing and cannot spuriously decay this fresh slot.
    _insert_companion(conn, effective=8000, source="measured", fast_age=3,
                      updated_secs_ago=0)
    picked = pick_slot.pick(conn, model="m", k=5)
    assert len(picked) == 1
    assert picked[0]["capacity_source"] == "measured"
    assert picked[0]["effective_free_mib"] == 8000
    assert picked[0]["degraded"] is False


# =========================================================================== #
# Gate bullet 2 — within-band churn no-op (D); MIG/ECC crossing fences (E).
# =========================================================================== #
def test_within_band_churn_noop_and_no_epoch_bump(db):
    conn = db()
    _seed_routable(conn, vram_free=8000)
    lease = leases.claim(conn, SLOT, "consumer-A")
    assert lease is not None and _epoch(conn) == 0

    # Two ticks whose RAW vram differs (8000 vs 8400) but lands in the SAME 1000-MiB band.
    cap1 = {**_cap_params(), **heartbeat.capacity_telemetry(
        "m", {"gpu_model": "x", "vram_free_mib": 8000, "gpu_util_pct": 5}, 10)}
    conn.execute(heartbeat.CAPACITY_UPSERT, cap1)
    ts1 = _companion(conn, "updated_ts")

    cap2 = {**_cap_params(), **heartbeat.capacity_telemetry(
        "m", {"gpu_model": "x", "vram_free_mib": 8400, "gpu_util_pct": 5}, 10)}
    conn.execute(heartbeat.CAPACITY_UPSERT, cap2)
    ts2 = _companion(conn, "updated_ts")

    assert ts2 == ts1, "within-band churn must be a byte-identical no-op (updated_ts unchanged)"
    assert _epoch(conn) == 0, "a fast-band move must NOT touch gpu_slots.epoch"
    assert leases.renew(conn, lease) is True, "a held lease survives a fast-band move (no self-abort)"

    # A genuine band CROSSING (8000 -> 16000) rewrites the companion row.
    cap3 = {**_cap_params(), **heartbeat.capacity_telemetry(
        "m", {"gpu_model": "x", "vram_free_mib": 16000, "gpu_util_pct": 5}, 10)}
    conn.execute(heartbeat.CAPACITY_UPSERT, cap3)
    assert _companion(conn, "updated_ts") != ts2, "a band crossing must rewrite the row"


def test_mig_ecc_crossing_bumps_epoch_and_fences(db):
    conn = db()
    _seed_routable(conn, mig_mode=None, ecc_mode="Enabled")
    lease = leases.claim(conn, SLOT, "consumer-A")
    assert lease is not None and _epoch(conn) == 0
    # The card's MIG partitioning changes (a SLOW capability band) -> epoch bumps -> the
    # holder's stamped lease_epoch no longer matches -> its renew returns zero rows.
    conn.execute(heartbeat.UPSERT, _hb_row(mig_mode="Enabled", ecc_mode="Enabled"))
    assert _epoch(conn) == 1, "a MIG/ECC change must bump epoch"
    assert leases.renew(conn, lease) is False, "the capability change must fence the held lease"


# =========================================================================== #
# Gate bullet 3 — pick/claim route on the LOWER (probe) number (G).
# =========================================================================== #
def test_pick_routes_on_probe_floor_not_exporter(db):
    conn = db()
    _seed_routable(conn, vram_free=24000)   # nvidia-smi free is high...
    # ...but the probe-measured floor is 8000 while a lying exporter over-reports 22000.
    # effective_free_mib stores the LEAST (8000); the claim must gate on 8000, not 22000.
    _insert_companion(conn, effective=8000, exporter=22000, source="measured",
                      fast_age=0, updated_secs_ago=0)
    # A request needing 10000 MiB: allowed under the exporter's 22000, REFUSED under the
    # probe floor 8000 -> claim matches zero rows.
    assert leases.claim(conn, SLOT, "A", model_mib=10000) is None
    # A request within the probe floor is claimable on the same slot.
    lease = leases.claim(conn, SLOT, "A", model_mib=8000)
    assert lease is not None


# =========================================================================== #
# Gate bullet 4 — phantom shrinks effective_free so pick routes around it (I).
# =========================================================================== #
def test_phantom_drops_slot_from_pick(db):
    conn = db()
    _seed_routable(conn, vram_free=24000)
    # An unrecognized PID holds VRAM -> phantom shrinks effective_free to 7000 (below the
    # 8000 the request needs) -> the slot is NOT claimable.
    _insert_companion(conn, effective=7000, source="measured", fast_age=0, updated_secs_ago=0)
    assert leases.claim(conn, SLOT, "A", model_mib=8000) is None
    # The PID exits -> effective_free restored to 12000 -> the slot is claimable again.
    conn.execute("UPDATE gpu_slots_capacity SET effective_free_mib = 12000, phantom_mib = 0 "
                 "WHERE endpoint_url = %s", (URL,))
    assert leases.claim(conn, SLOT, "A", model_mib=8000) is not None


# =========================================================================== #
# Gate bullet 6 — None/0 baseline never crashes; cold baseline is sticky (K3, BC3/F-BASE).
# =========================================================================== #
def test_capacity_upsert_null_and_sticky_baseline(db):
    conn = db()
    _seed_routable(conn)
    # (i) a None probe (cold_probe_ms NULL) -> live_slowdown_factor IS NULL, no crash.
    conn.execute(heartbeat.CAPACITY_UPSERT, _cap_params(cold_probe_ms=None))
    assert _companion(conn, "live_slowdown_factor") is None

    # (ii) a 0 baseline -> live_slowdown_factor IS NULL (NULLIF guards the division).
    conn.execute("DELETE FROM gpu_slots_capacity")
    conn.execute(heartbeat.CAPACITY_UPSERT, _cap_params(cold_probe_ms=0))
    assert _companion(conn, "live_slowdown_factor") is None

    # (iii) STICKY baseline (F-BASE): tick1 captures a cold baseline of 10; a later tick with
    # a HOT reprobe of 99 (and a band crossing so the UPDATE fires) keeps cold_probe_ms = 10,
    # and the slowdown is computed against the COLD baseline (99 / 10).
    conn.execute("DELETE FROM gpu_slots_capacity")
    conn.execute(heartbeat.CAPACITY_UPSERT,
                 _cap_params(cold_probe_ms=10, effective_free_mib=8000, util_band=0))
    assert _companion(conn, "cold_probe_ms") == 10
    conn.execute(heartbeat.CAPACITY_UPSERT,
                 _cap_params(cold_probe_ms=99, effective_free_mib=16000, util_band=9))
    assert _companion(conn, "cold_probe_ms") == 10, "a hot reprobe must NOT overwrite the cold baseline"
    assert float(_companion(conn, "live_slowdown_factor")) == pytest.approx(99 / 10)


# =========================================================================== #
# Gate bullet 4 (BC4) — the puller writes a companion row for a pulled node (M).
# =========================================================================== #
def test_puller_writes_companion_row(db):
    import heartbeat_all as ha
    # Build a probed PULL row (with capacity telemetry) for a node with NO fleet_nodes
    # entry (so the single-writer guard never trips), and write it through pull_write, which
    # issues the savepoint-guarded CAPACITY_UPSERT after the liveness UPSERT. A non-autocommit
    # connection so the SAVEPOINT is valid (mirrors the real heartbeat's autocommit=False).
    cap = heartbeat.capacity_telemetry(
        "m", {"gpu_model": "RTX 3090", "vram_total_mib": 24000, "vram_free_mib": 22000,
              "gpu_util_pct": 5, "gpu_uuid": "U"}, 10)
    row = {"node": "peecee", "endpoint": "http://peecee:11434/v1", "slot_id": 0,
           "gpu_model": "RTX 3090", "nvlink": None, "vram_total": 24000, "vram_free": 22000,
           "util": 5, "loaded_model": "m", "served_model": "m", "max_context": 8192,
           "latency_class": "batch", "free_slots": 1, "epoch": 0, "alive": True,
           "probe_ms": 10, "note": None, "gpu_uuid": "U", "boot_epoch": None,
           "mig_mode": None, "ecc_mode": None, **cap}
    wconn = psycopg.connect(TEST_DB)            # autocommit OFF -> savepoint valid
    try:
        assert ha.pull_write(wconn, row) is True
    finally:
        wconn.close()

    conn = db()
    got = conn.execute(
        "SELECT capacity_source, effective_free_mib FROM gpu_slots_capacity "
        "WHERE node = 'peecee'").fetchone()
    assert got is not None, "the puller must write a companion row for the pulled node"
    assert got[0] == "measured"


# =========================================================================== #
# Gate bullet 8 (BC1) — the headroom predicate refuses an oversized context (N2).
# =========================================================================== #
def test_headroom_predicate_refuses_oversized_context(db):
    conn = db()
    _seed_routable(conn, vram_free=8000, served_model="m")
    # Operator-seeded request-capacity policy: footprint 1000 MiB + 500 MiB/1k-token KV.
    conn.execute("INSERT INTO model_capacity (model, footprint_mib, kv_mib_per_1k_tokens) "
                 "VALUES ('m', 1000, 500)")
    # 4k need = 1000 + CEIL(500*4096/1000) = 3048 <= 8000 -> claimable.
    lease = leases.claim(conn, SLOT, "A", max_context=4096)
    assert lease is not None
    leases.release(conn, lease)
    # 32k need = 1000 + CEIL(500*32768/1000) = 17384 > 8000 -> the SAME slot is REFUSED.
    assert leases.claim(conn, SLOT, "A", max_context=32768) is None
    # And the reader PICK agrees: the 32k request sees the slot as NOT routable, the 4k does.
    assert pick_slot.pick(conn, model="m", max_context=32768, k=5) == []
    picked4k = pick_slot.pick(conn, model="m", max_context=4096, k=5)
    assert len(picked4k) == 1 and picked4k[0]["endpoint_url"] == URL


# =========================================================================== #
# Gate bullet 5b / 9 (F-LOCK / F-CARD) — one-row-per-slot, unique PK, fenced re-claim (P2).
# =========================================================================== #
def test_pick_k2_one_slot_returns_unique_pk(db):
    conn = db()
    _seed_routable(conn)                         # ONE routable slot, NO companion row
    picked = pick_slot.pick(conn, k=2)           # k=2 on a one-slot fleet...
    assert len(picked) == 1, "the policy/model joins must not multiply a slot row (F-CARD)"
    pk = (picked[0]["node"], picked[0]["endpoint_url"], picked[0]["slot_id"])
    assert pk == (NODE, URL, SLOT_ID)
    # a real claim of that PK works, and a second claim of the held slot is a fenced no-op.
    lease = leases.claim(conn, SLOT, "A")
    assert lease is not None
    assert leases.claim(conn, SLOT, "B") is None


# =========================================================================== #
# Gate bullet 9 (F-CARD / C1) — 010 re-applies idempotently; policy is a singleton (Q).
# =========================================================================== #
def test_010_reapply_singleton_and_view_cardinality(db):
    conn = db()
    # Re-apply 010 (it ran once in the fixture) -> still exactly ONE policy row, no error.
    _apply_010(conn)
    assert conn.execute("SELECT count(*) FROM capacity_policy").fetchone()[0] == 1
    # The CHECK (id = 1) + PK make a second policy row impossible.
    with pytest.raises(Exception):
        conn.execute("INSERT INTO capacity_policy (id) VALUES (2)")
    # One routable slot, NO companion row -> the diagnostic view is exactly one row per slot.
    _seed_routable(conn)
    n = conn.execute(
        "SELECT count(*) FROM capacity_slots WHERE (node, endpoint_url, slot_id) = (%s,%s,%s)",
        (NODE, URL, SLOT_ID)).fetchone()[0]
    assert n == 1, "capacity_slots must be one row per slot even with the companion empty"
