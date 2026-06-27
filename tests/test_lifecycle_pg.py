"""RFC 0002 zero-touch lifecycle gate — properties only a REAL Postgres can prove:
the composed self-push register+graduate, the boot-epoch ratchet (BC2/BC6), the uuid
hot-swap re-quarantine (BC7), the puller-lease deadman failover with no age-out (BC3),
the per-node single-writer skip (BC4/C9), measured-not-declared routing, and identity
survival across a reboot. Every assertion runs the REAL SQL constants (heartbeat.UPSERT,
NODE_LEASE_CAS, heartbeat_all.FETCH/PRUNE/PULLER_LEASE_CAS, di_fleet.LEASE_CLAIM_SQL)
against the REAL migrations — so a column-name / predicate divergence fails the suite.

These also prove the real migrations apply cleanly: the fixture runs migrations/001,
002, 007, 008, 009 in order against an ephemeral cluster.

GUARDED exactly like test_leases_pg.py / test_epoch_pg.py so the default
`pytest tests/ -q` stays green and hermetic:
  * skips if psycopg is not importable;
  * skips unless GPU_FLEET_TEST_DB points at an EPHEMERAL throwaway cluster;
  * refuses to run against the live `gpu_fleet` database.

Provide an ephemeral DB to run, e.g.:
    GPU_FLEET_TEST_DB='dbname=gpu_fleet_test host=/tmp/pgtest' pytest tests/test_lifecycle_pg.py -q
"""

import glob
import os
import types

import pytest

psycopg = pytest.importorskip("psycopg")

TEST_DB = os.environ.get("GPU_FLEET_TEST_DB")
if not TEST_DB:
    pytest.skip("set GPU_FLEET_TEST_DB to an ephemeral throwaway cluster to run these",
                allow_module_level=True)
# Safety: never run the destructive DDL against the live registry.
_dbnames = {tok.split("=", 1)[1] for tok in TEST_DB.split() if tok.startswith("dbname=")}
if _dbnames and any(n == "gpu_fleet" or "test" not in n for n in _dbnames):
    pytest.skip("refusing to run lifecycle tests against a non-ephemeral DB "
                f"({_dbnames}); use a throwaway cluster whose dbname contains 'test'",
                allow_module_level=True)

import di_fleet as leases  # noqa: E402  lease lifecycle lives in di_fleet (CLAIM_LEDGER)
import heartbeat  # noqa: E402  the real UPSERT + push entry path + NODE_LEASE_CAS
import heartbeat_all  # noqa: E402  the real FETCH / PRUNE / puller-lease CAS

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
_MIGRATIONS = os.path.join(_ROOT, "migrations")
# Apply the FULL migration chain in order: the lifecycle gate runs the real driver FETCH,
# which selects fleet_nodes columns built up by 003-006 (e.g. min_load_vram_mib in 005),
# so the test schema must be the true cumulative result of every migration, not a subset.
_FILES = tuple(sorted(os.path.basename(p) for p in glob.glob(os.path.join(_MIGRATIONS, "0*.sql"))))

NODE, URL, SLOT_ID = "n", "http://n:8081/v1", 0
SLOT = {"node": NODE, "endpoint_url": URL, "slot_id": SLOT_ID}


def _apply_migrations(conn):
    conn.execute("DROP TABLE IF EXISTS gpu_slots CASCADE")   # drops live_slots + routable_slots
    conn.execute("DROP TABLE IF EXISTS fleet_nodes CASCADE")
    conn.execute("DROP TABLE IF EXISTS fleet_meta CASCADE")
    conn.execute("CREATE EXTENSION IF NOT EXISTS pgcrypto")
    for fname in _FILES:
        with open(os.path.join(_MIGRATIONS, fname), encoding="utf-8") as f:
            conn.execute(f.read())
    # clean slate: tests declare their own nodes / heartbeat their own slots.
    conn.execute("DELETE FROM fleet_nodes")
    conn.execute("DELETE FROM gpu_slots")


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


def _hb_row(*, node=NODE, endpoint=URL, slot_id=SLOT_ID, alive=True, gpu_uuid="U1",
            boot_epoch=None, served_model="m", vram_free=22000, max_context=8192,
            probe_ms=10, note=None):
    """A full heartbeat.UPSERT param row; boot_epoch=None => pull-style (ratchet inert)."""
    return {
        "node": node, "endpoint": endpoint, "slot_id": slot_id,
        "gpu_model": "RTX 3090", "nvlink": None, "vram_total": 24000,
        "vram_free": vram_free, "util": 5, "loaded_model": served_model if alive else None,
        "served_model": served_model, "max_context": max_context, "latency_class": "batch",
        "free_slots": 1, "epoch": 0, "alive": alive, "probe_ms": probe_ms, "note": note,
        # RFC 0005 (F-KEYS): the shared UPSERT now names mig_mode/ecc_mode.
        "gpu_uuid": gpu_uuid, "boot_epoch": boot_epoch, "mig_mode": None, "ecc_mode": None,
    }


def _upsert(conn, **over):
    conn.execute(heartbeat.UPSERT, _hb_row(**over))


def _row(conn, node=NODE):
    # Each test uses a single slot per node, so node alone is a unique key here.
    return conn.execute(
        "SELECT status, probe_streak, gpu_uuid, boot_epoch, served_model, alive,"
        " heartbeat_ts FROM gpu_slots WHERE node=%s", (node,)).fetchone()


def _status(conn, node=NODE):
    r = _row(conn, node)
    return r[0] if r else None


def _boot_epoch(conn, node=NODE):
    return _row(conn, node)[3]


def _in_routable(conn, node=NODE):
    return conn.execute("SELECT 1 FROM routable_slots WHERE node=%s", (node,)).fetchone() is not None


def _stub_probes(monkeypatch, *, alive=True, uuid="U1", vram_free=24000):
    monkeypatch.setattr(heartbeat, "gpu_stats",
                        lambda cmd, *a, **k: {"gpu_model": "RTX 3090",
                                              "vram_total_mib": 24000, "vram_free_mib": vram_free,
                                              "gpu_util_pct": 5, "gpu_uuid": uuid})
    monkeypatch.setattr(heartbeat, "discover_served_model", lambda *a, **k: "m")
    monkeypatch.setattr(heartbeat, "decode_probe", lambda *a, **k: (alive, 7 if alive else None, None))


def _push_args(node, endpoint, slot_id=0):
    return types.SimpleNamespace(
        node=node, endpoint=endpoint, slot_id=slot_id, gpu_cmd="nvidia-smi",
        served_model="m", probe_model="m", nvlink_domain=None, max_context=8192,
        latency_class="batch", free_slots=1, min_load_vram_mib=None, epoch=0,
        timeout=5.0, push=True)


# --------------------------------------------------------------------------- #
# Gate "Zero-touch register" (D / BC1) — the COMPOSED Slice-1+3 push entry path for a
# node ABSENT from fleet_nodes: the non-gating lease CAS matches zero rows, the UPSERT
# still creates the row 'unverified', N alive ticks graduate it, and the stale-only
# PRUNE never deletes it while fresh.
# --------------------------------------------------------------------------- #
def test_self_push_no_fleet_node_registers_and_graduates(db, monkeypatch):
    conn = db()
    assert conn.execute("SELECT 1 FROM fleet_nodes WHERE node='ghost'").fetchone() is None
    _stub_probes(monkeypatch, alive=True, uuid="GPU-GHOST")
    args = _push_args("ghost", "http://ghost:8081/v1")

    heartbeat.heartbeat_once(conn, args)            # first heartbeat = registration
    assert _status(conn, "ghost") == "unverified"
    assert _in_routable(conn, "ghost") is False
    # the registering row exists despite NO fleet_nodes row (CAS matched zero rows).
    assert _boot_epoch(conn, "ghost") is not None   # push stamped a boot identity

    for _ in range(heartbeat.GRADUATION_STREAK - 1):
        heartbeat.heartbeat_once(conn, args)
    assert _status(conn, "ghost") == "routable"
    assert _in_routable(conn, "ghost") is True

    # the stale-only PRUNE must NOT delete a FRESH self-push row absent from fleet_nodes.
    conn.execute(heartbeat_all.PRUNE)
    assert _row(conn, "ghost") is not None, "PRUNE deleted a fresh self-push row (C3-PRUNE)"


# --------------------------------------------------------------------------- #
# BC2 — a NULL (pull) write never erases a push-stamped ratchet; a strictly-stale push
# stays refused after any number of pull ticks.
# --------------------------------------------------------------------------- #
def test_boot_epoch_survives_null_pull_write(db):
    conn = db()
    _upsert(conn, boot_epoch=100, served_model="m")        # push-stamp K=100 (INSERT)
    assert _boot_epoch(conn) == 100
    _upsert(conn, boot_epoch=None, served_model="m-pull")  # pull tick: NULL boot_epoch
    assert _boot_epoch(conn) == 100, "NULL pull write must not erase the ratchet (BC2)"
    assert _row(conn)[4] == "m-pull"                       # the admitted pull tick DID land
    # a strictly-stale push (99 < 100) is still refused, even after the pull tick.
    _upsert(conn, boot_epoch=99, served_model="STALE", alive=False)
    assert _boot_epoch(conn) == 100
    assert _row(conn)[4] == "m-pull", "a strictly-stale replay must be refused (BC2/BC6)"


# --------------------------------------------------------------------------- #
# BC6 — an equal-epoch replay is a no-op: no mutable field moves and heartbeat_ts is NOT
# re-stamped; a strictly-greater epoch IS accepted.
# --------------------------------------------------------------------------- #
def test_equal_epoch_replay_is_noop(db):
    conn = db()
    _upsert(conn, boot_epoch=500, served_model="m1", probe_ms=10)
    hb0 = _row(conn)[6]
    _upsert(conn, boot_epoch=500, served_model="m2", alive=False, probe_ms=999, note="replay")
    r = _row(conn)
    assert r[4] == "m1" and r[5] is True, "equal-epoch replay moved a mutable field (BC6)"
    assert r[6] == hb0, "equal-epoch replay re-stamped heartbeat_ts (BC6)"
    _upsert(conn, boot_epoch=501, served_model="m3")       # strictly greater -> accepted
    assert _row(conn)[4] == "m3"


# --------------------------------------------------------------------------- #
# BC7 — a hot-swapped card (alive probe, KNOWN different uuid) resets the streak and
# re-quarantines to unverified; it leaves routable_slots until it re-graduates.
# --------------------------------------------------------------------------- #
def test_hot_swap_demotes_to_unverified(db):
    conn = db()
    for _ in range(heartbeat.GRADUATION_STREAK):
        _upsert(conn, gpu_uuid="U1", served_model="m")
    assert _status(conn) == "routable" and _in_routable(conn) is True
    _upsert(conn, gpu_uuid="U2", served_model="m")         # different KNOWN uuid
    r = _row(conn)
    assert r[0] == "unverified" and r[1] == 1 and r[2] == "U2"
    assert _in_routable(conn) is False


# --------------------------------------------------------------------------- #
# Gate "Identity survives churn" (J) — a rebooted node re-presents the SAME uuid and
# skips re-quarantine on its first passing probe (a fresh boot_epoch is admitted).
# --------------------------------------------------------------------------- #
def test_reboot_same_uuid_skips_requarantine(db):
    conn = db()
    for _ in range(heartbeat.GRADUATION_STREAK):
        _upsert(conn, gpu_uuid="U1", served_model="m")
    assert _status(conn) == "routable"
    _upsert(conn, gpu_uuid="U1", boot_epoch=700, served_model="m")  # reboot, same id
    assert _status(conn) == "routable", "a matching uuid must carry trust forward (J)"
    assert _in_routable(conn) is True


# --------------------------------------------------------------------------- #
# Gate "No SPOF" (B / BC3) — the real puller-lease CAS on real 009 fleet_meta: holder A
# wins, B idles; on A's deadman expiry B takes over within TTL, and no node leaves
# routable_slots/live_slots across the gap (15s TTL < 45s window).
# --------------------------------------------------------------------------- #
def test_puller_failover_no_ageout(db):
    conn = db()
    for _ in range(heartbeat.GRADUATION_STREAK):       # a live, routable slot
        _upsert(conn, gpu_uuid="U1", served_model="m")
    assert _in_routable(conn) is True

    assert heartbeat_all.acquire_puller_lease(conn, "A", heartbeat_all.PULLER_LEASE_TTL) is True
    assert heartbeat_all.acquire_puller_lease(conn, "B", heartbeat_all.PULLER_LEASE_TTL) is False
    # A dies: expire its lease. The slot is still fresh (< 45s) -> still routable.
    conn.execute("UPDATE fleet_meta SET lease_until = now() - interval '1 second' WHERE id=1")
    assert _in_routable(conn) is True
    # B acquires within TTL (15s < 45s), so the standby drives before any slot ages out.
    assert heartbeat_all.acquire_puller_lease(conn, "B", heartbeat_all.PULLER_LEASE_TTL) is True
    assert heartbeat_all.acquire_puller_lease(conn, "A", heartbeat_all.PULLER_LEASE_TTL) is False
    assert heartbeat_all.PULLER_LEASE_TTL < 45
    assert _in_routable(conn) is True                  # no node left the directory across the gap


# --------------------------------------------------------------------------- #
# Gate "Single writer" (H / BC4/C9) — the driver FETCH omits a node whose per-node
# driver-lease is fresh (a self-pusher owns it); lapse the lease and the puller resumes.
# --------------------------------------------------------------------------- #
def test_push_and_pull_never_both_write(db):
    conn = db()
    conn.execute("INSERT INTO fleet_nodes (node, slot_id, endpoint_url, served_model) "
                 "VALUES ('quad', 0, 'http://quad:8081/v1', 'm')")
    # a self-pusher holds the per-node lease, fresh by the DB clock.
    conn.execute("UPDATE fleet_nodes SET driven_by='push/quad', "
                 "lease_until = now() + make_interval(secs => %s) WHERE node='quad'",
                 (heartbeat.NODE_LEASE_TTL,))
    fetched = [r[0] for r in conn.execute(heartbeat_all.FETCH).fetchall()]
    assert "quad" not in fetched, "puller must SKIP a node whose driver-lease is fresh (C9)"
    # lapse the lease (DB clock) -> the puller resumes the node on the next FETCH.
    conn.execute("UPDATE fleet_nodes SET lease_until = now() - interval '1 second' WHERE node='quad'")
    fetched2 = [r[0] for r in conn.execute(heartbeat_all.FETCH).fetchall()]
    assert "quad" in fetched2, "puller must RESUME a node whose driver-lease lapsed"


# --------------------------------------------------------------------------- #
# Gate "Single writer" (H, the REAL race / C9) — the FETCH-time skip above is only HALF
# the guarantee. A self-pusher can lease a node AFTER the puller fetched it as eligible
# but BEFORE the puller writes its probed row (the concurrent probe phase is seconds
# long). TWO REAL transactions: the puller fetches 'quad' eligible and builds a probed
# row; a self-pusher then acquires the per-node lease and writes the slot in its own
# transaction; the puller's WRITE-time guard (pull_write) must YIELD -> write ZERO rows,
# so the registry row is the PUSHER's, never clobbered by the puller's stale fetch. Then,
# once the push-lease lapses, the puller RESUMES writing (the guard does not over-skip).
# --------------------------------------------------------------------------- #
def test_pull_yields_when_push_acquires_after_fetch(db):
    setup = db()
    setup.execute("INSERT INTO fleet_nodes (node, slot_id, endpoint_url, served_model) "
                  "VALUES ('quad', 0, 'http://quad:8081/v1', 'm')")
    # 1) Puller FETCHes 'quad' as eligible (driven_by NULL) and builds its probed row.
    assert "quad" in [r[0] for r in setup.execute(heartbeat_all.FETCH).fetchall()]
    stale_pull_row = _hb_row(node="quad", endpoint="http://quad:8081/v1",
                             served_model="m-PULL", boot_epoch=None, vram_free=10000)

    # 2) A self-pusher acquires the per-node lease and writes the slot, in its OWN txn.
    push = db()
    push.execute(heartbeat.NODE_LEASE_CAS,
                 {"me": "push/quad", "node": "quad", "slot_id": 0,
                  "node_ttl": heartbeat.NODE_LEASE_TTL})
    push.execute(heartbeat.UPSERT, _hb_row(node="quad", endpoint="http://quad:8081/v1",
                                           served_model="m-PUSH", boot_epoch=4242,
                                           vram_free=22000))

    # 3) The puller now writes its STALE fetched row through the write-time guard. The
    #    node is push-held now, so the guard YIELDS and the puller writes ZERO rows.
    puller = psycopg.connect(TEST_DB)          # non-autocommit: guard + upsert = one txn
    try:
        wrote = heartbeat_all.pull_write(puller, stale_pull_row)
    finally:
        puller.close()
    assert wrote is False, "the puller must YIELD a node a self-pusher leased after the FETCH (C9)"
    r = setup.execute("SELECT served_model, boot_epoch FROM gpu_slots "
                      "WHERE node='quad'").fetchone()
    assert r == ("m-PUSH", 4242), f"the puller's stale write must not land; got {r}"

    # 4) When the push-lease lapses, the puller RESUMES writing the node (no over-skip).
    setup.execute("UPDATE fleet_nodes SET lease_until = now() - interval '1 second' "
                  "WHERE node='quad'")
    puller2 = psycopg.connect(TEST_DB)
    try:
        wrote2 = heartbeat_all.pull_write(
            puller2, _hb_row(node="quad", endpoint="http://quad:8081/v1",
                             served_model="m-PULL2", boot_epoch=None))
    finally:
        puller2.close()
    assert wrote2 is True, "the puller must RESUME writing once the push-lease lapsed"
    assert setup.execute("SELECT served_model FROM gpu_slots WHERE node='quad'"
                         ).fetchone()[0] == "m-PULL2"


# --------------------------------------------------------------------------- #
# Gate "Anti-lie" — the RFC bullet has TWO halves, proven SEPARATELY so each is literal:
#   (a) NEVER GRADUATES: a node claiming a big GPU whose probe shows it cannot actually
#       serve (alive=False) never increments its streak, so it never reaches routable and
#       never enters routable_slots — no number of lying ticks promotes it.
#   (b) ROUTES ONLY MEASURED: a node with a REAL but small GPU DOES graduate on its live
#       ticks (Q2 — a working small card is legitimately routable), but routing reads only
#       the MEASURED columns, so it routes its measured throughput, never the big DECLARED
#       capability — a claim needing more VRAM than measured is rejected.
# --------------------------------------------------------------------------- #
def test_failed_probe_big_declared_never_graduates(db):
    conn = db()
    # Declares a huge context + an A100-80G served model, but the probe never passes
    # (alive=False every tick): the streak never increments, so it can never graduate.
    for _ in range(heartbeat.GRADUATION_STREAK + 2):
        _upsert(conn, max_context=200000, vram_free=80000, gpu_uuid="U1",
                served_model="A100-80G", alive=False)
    assert _status(conn) == "unverified", "a node that never serves must never graduate"
    assert _in_routable(conn) is False
    # It cannot lie itself into routing: even a zero-VRAM claim is refused (not routable).
    assert leases.claim(conn, SLOT, "consumer", model_mib=0) is None


def test_big_declared_small_measured_routes_only_measured(db):
    conn = db()
    _upsert(conn, max_context=200000, vram_free=512, gpu_uuid="U1", served_model="m")
    assert _status(conn) == "unverified"
    assert _in_routable(conn) is False                 # not instantly routable (quarantine)
    for _ in range(heartbeat.GRADUATION_STREAK - 1):
        _upsert(conn, max_context=200000, vram_free=512, gpu_uuid="U1", served_model="m")
    assert _status(conn) == "routable"                 # a REAL small GPU graduates (Q2)
    # routing reads MEASURED vram_free (512), not the DECLARED 200000-token context:
    assert leases.claim(conn, SLOT, "consumer", model_mib=20000) is None
    assert leases.claim(conn, SLOT, "consumer", model_mib=256) is not None
