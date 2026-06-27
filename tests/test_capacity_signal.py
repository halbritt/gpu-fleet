"""RFC 0005 — exporter-fed capacity signal, HERMETIC gate proofs.

Maps to the RFC's Falsifiable gate, the half each bullet can prove with NO real DB /
nvidia-smi / HTTP — every per-PID source, exporter, and probe-floor is an INJECTED fake,
mirroring tests/test_probe_all.py and tests/test_load_aware_liveness.py. The matching
end-to-end Postgres proofs (the SQL actually decays / the companion is actually written /
the headroom predicate actually refuses a 32k request) are the GPU_FLEET_TEST_DB-guarded
tests in tests/test_capacity_pg.py.

Gate bullets covered here:
  1  freshness decay is single-clock; a node<->DB skew never decays a fresh slot   (A1, A2)
  2  within-band churn is a no-op; the shared UPSERT never KeyErrors a writer        (C, C-KEYS)
  3  effective_free routes on LEAST(probe_floor, exporter)                           (F)
  4  an unrecognized PID becomes a measured phantom and clears; puller writes it     (H, M2)
  6  ollama-ondemand is residency-only; a None/0 baseline never crashes the tick     (K, K2)
"""

import types

import heartbeat as hb
import heartbeat_all as ha


# --------------------------------------------------------------------------- #
# Recording fakes (no real DB).
# --------------------------------------------------------------------------- #
class _Cur:
    def __init__(self, rows=()):
        self._rows = list(rows)

    def fetchone(self):
        return self._rows[0] if self._rows else None

    def fetchall(self):
        return list(self._rows)


class RecordingConn:
    """Captures (sql, params); the PULL_WRITE_GUARD returns no row (node not push-held)."""

    def __init__(self):
        self.calls = []

    def execute(self, sql, params=None):
        self.calls.append((sql, params or {}))
        return _Cur([])           # guard: empty -> pull_write proceeds; UPSERTs: no rows

    def commit(self):
        pass

    def rollback(self):
        pass


class CallSpy:
    """A floor-adapter stand-in that records its call count (asserts a path is NEVER taken)."""

    def __init__(self, ret=99999):
        self.ret = ret
        self.calls = 0

    def __call__(self, stats):
        self.calls += 1
        return self.ret


def _stats(free=22000, util=5, model="RTX 3090", **extra):
    s = {"gpu_model": model, "vram_total_mib": 24000, "vram_free_mib": free,
         "gpu_util_pct": util, "gpu_uuid": "U1"}
    s.update(extra)
    return s


# =========================================================================== #
# Gate bullet 1 — BC2 single-clock freshness decay (A1 frozen, A2 skew).
# =========================================================================== #
def test_decay_marks_stale_by_single_clock():
    # "A1" — staleness is a SAME-clock node age + a SAME-clock DB age. A frozen source (its
    # age grows) OR an un-written row (now()-updated_ts grows) decays past k*half_life; a
    # genuinely fresh slot does not.
    k, hl = 3, 30                                  # threshold = 90s
    assert hb.is_fast_stale(hb.capacity_staleness_s(0, 200), decay_k=k, half_life_s=hl)
    assert hb.is_fast_stale(hb.capacity_staleness_s(200, 0), decay_k=k, half_life_s=hl)
    assert not hb.is_fast_stale(hb.capacity_staleness_s(5, 5), decay_k=k, half_life_s=hl)


def test_skew_does_not_decay_fresh_slot():
    # "A2" — a several-x-half_life node<->DB clock skew does NOT spuriously decay a fresh
    # slot, because each summand is a WITHIN-clock difference, so the absolute offset cancels.
    k, hl = 3, 30
    skew = 100000.0                                # node and DB clocks differ by >> k*half_life
    node_source_t, node_now = 1000.0, 1002.0       # node measured the source 2s ago (node clock)
    fast_age = node_now - node_source_t            # 2.0
    db_updated_t = node_now + skew                 # DB stamped updated_ts on ITS own clock
    db_now = (node_now + 1.0) + skew               # 1s later on the DB clock
    updated_age = db_now - db_updated_t            # 1.0
    staleness = hb.capacity_staleness_s(fast_age, updated_age)
    assert staleness == 3.0, "the absolute node<->DB skew must cancel in each difference"
    assert not hb.is_fast_stale(staleness, decay_k=k, half_life_s=hl)


# =========================================================================== #
# Gate bullet 2 — within-band no-op + the epoch CASE; F-KEYS row-dict keys.
# =========================================================================== #
def test_capacity_upsert_stores_only_banded_values():
    cap = hb.CAPACITY_UPSERT
    # BC3: live_slowdown_factor is computed in SQL (CASE/NULLIF), never a Python division.
    assert "live_slowdown_factor = CASE" in cap and "NULLIF(" in cap
    # F-BASE: the cold baseline is sticky (COALESCE keeps the persisted cold one).
    assert "COALESCE(gpu_slots_capacity.cold_probe_ms, EXCLUDED.cold_probe_ms)" in cap
    # Freshness is UNCONDITIONAL: the companion has no within-band WHERE guard, so updated_ts
    # (the liveness clock the reader decays against) re-stamps every tick and a stable,
    # within-band slot never self-decays. C-EPOCH churn exclusion lives in the gpu_slots epoch
    # CASE below, NOT on the companion (which carries no epoch).
    assert "updated_ts" in cap and "= now()" in cap
    assert "IS DISTINCT FROM EXCLUDED" not in cap, \
        "the companion DO UPDATE must NOT be gated by a within-band guard (it would freeze freshness)"

    # The gpu_slots epoch CASE references the SLOW capability bands (+ the existing trio)
    # but NOT the fast capacity bands (C-EPOCH: fast churn never bumps epoch).
    case = hb.UPSERT.split("gpu_slots.epoch + CASE", 1)[1].split("END", 1)[0]
    for col in ("served_model", "nvlink_domain", "max_context", "mig_mode", "ecc_mode"):
        assert f"gpu_slots.{col}" in case and f"EXCLUDED.{col}" in case, col
    assert "effective_free_mib" not in case and "util_band" not in case
    assert "vram_free_mib" not in case and "gpu_util_pct" not in case


def test_all_upsert_row_builders_have_mig_ecc_keys(monkeypatch):
    # F-KEYS: adding mig_mode/ecc_mode to the SHARED UPSERT means EVERY row dict must carry
    # them or conn.execute(UPSERT, row) KeyErrors. Assert all THREE row-builders do.
    monkeypatch.setattr(ha, "gpu_stats", lambda cmd, *a, **k: _stats(
        mig_mode="Disabled", ecc_mode="Enabled"))
    monkeypatch.setattr(ha, "discover_served_model", lambda *a, **k: "m")
    monkeypatch.setattr(ha, "decode_probe", lambda *a, **k: (True, 7, None))
    node = {"node": "n", "slot_id": 0, "endpoint_url": "http://n:8081/v1",
            "served_model": "m", "probe_model": "m", "latency_class": "batch",
            "gpu_cmd": "nvidia-smi", "nvlink_domain": None, "max_context": 8192,
            "free_slots": 1, "epoch": 0, "min_load_vram_mib": None}
    pn = ha.probe_node(node)
    assert "mig_mode" in pn and "ecc_mode" in pn
    assert pn["mig_mode"] == "Disabled" and pn["ecc_mode"] == "Enabled"

    fr = ha._failed_row(node, RuntimeError("boom"))
    assert "mig_mode" in fr and "ecc_mode" in fr
    assert fr["mig_mode"] is None and fr["ecc_mode"] is None     # crashed probe knows none
    assert fr["capacity_source"] == "absent"                     # well-formed absent companion

    # heartbeat_once's row dict (push path), captured off a recording conn.
    monkeypatch.setattr(hb, "gpu_stats", lambda cmd, *a, **k: _stats(
        mig_mode="Enabled", ecc_mode="Disabled"))
    monkeypatch.setattr(hb, "discover_served_model", lambda *a, **k: "m")
    monkeypatch.setattr(hb, "decode_probe", lambda *a, **k: (True, 7, None))
    args = types.SimpleNamespace(
        node="n", endpoint="http://n:8081/v1", slot_id=0, gpu_cmd="nvidia-smi",
        served_model="m", probe_model="m", nvlink_domain=None, max_context=8192,
        latency_class="batch", free_slots=1, min_load_vram_mib=None, epoch=0,
        timeout=5.0, push=False)
    conn = RecordingConn()
    hb.heartbeat_once(conn, args)
    up_row = next(p for s, p in conn.calls if s == hb.UPSERT)
    assert "mig_mode" in up_row and "ecc_mode" in up_row
    assert up_row["mig_mode"] == "Enabled" and up_row["ecc_mode"] == "Disabled"


# =========================================================================== #
# Gate bullet 3 — effective_free = LEAST(probe_floor, exporter_free) (C4).
# =========================================================================== #
def test_effective_free_is_least_of_floor_and_exporter():
    # A fake exporter OVER-REPORTING free VRAM (22000) with a probe floor of 8000 must route
    # on the LOWER (probe) number: a lying exporter can't claim headroom the probe can't allocate.
    cap = hb.capacity_telemetry(
        "llama-3", _stats(free=8000), probe_ms=12,
        scratch_floor_fn=lambda s: 8000, exporter_fn=lambda: {"free_mib": 22000})
    assert cap["probe_floor_mib"] == 8000
    assert cap["exporter_free_mib"] == 22000
    assert cap["effective_free_mib"] == 8000, "must trust the lower (probe) floor, not the exporter"
    assert cap["capacity_source"] == "measured"


# =========================================================================== #
# Gate bullet 4 — unrecognized PID -> measured phantom -> shrinks effective_free (OQ-P).
# =========================================================================== #
def test_unrecognized_pid_becomes_phantom_and_clears():
    stats = _stats(free=12000)
    recognized = {111}                              # the fleet's own lease-bound server PID
    with_phantom = hb.capacity_telemetry(
        "llama-3", stats, 12, scratch_floor_fn=lambda s: 12000,
        per_pid_fn=lambda: [(111, 3000), (999, 5000)], recognized_pids=recognized)
    assert with_phantom["phantom_mib"] == 5000 and with_phantom["phantom_pids"] == 1
    assert with_phantom["effective_free_mib"] == 7000   # 12000 floor - 5000 unknown-PID phantom

    cleared = hb.capacity_telemetry(
        "llama-3", stats, 12, scratch_floor_fn=lambda s: 12000,
        per_pid_fn=lambda: [(111, 3000)], recognized_pids=recognized)
    assert cleared["phantom_mib"] == 0
    assert cleared["effective_free_mib"] == 12000       # restored when the unknown PID exits
    assert cleared["effective_free_mib"] > with_phantom["effective_free_mib"]


def test_pull_write_invokes_capacity_upsert_inside_savepoint():
    # M2 (BC4, hermetic): a RecordingConn shows pull_write issues CAPACITY_UPSERT AFTER the
    # liveness UPSERT and INSIDE the savepoint (so a companion failure can't sink liveness).
    cap = hb.capacity_telemetry("m", _stats(), probe_ms=10)
    row = {"node": "peecee", "endpoint": "http://peecee:11434/v1", "slot_id": 0,
           "gpu_model": "RTX 3090", "nvlink": None, "vram_total": 24000, "vram_free": 22000,
           "util": 5, "loaded_model": "m", "served_model": "m", "max_context": 8192,
           "latency_class": "batch", "free_slots": 1, "epoch": 0, "alive": True,
           "probe_ms": 10, "note": None, "gpu_uuid": "U1", "boot_epoch": None,
           "mig_mode": None, "ecc_mode": None, **cap}
    conn = RecordingConn()
    assert ha.pull_write(conn, row) is True
    sqls = [s for s, _ in conn.calls]
    assert hb.UPSERT in sqls and hb.CAPACITY_UPSERT in sqls
    assert (sqls.index(hb.UPSERT)
            < sqls.index("SAVEPOINT cap")
            < sqls.index(hb.CAPACITY_UPSERT)
            < sqls.index("RELEASE SAVEPOINT cap")), \
        "companion write must run AFTER liveness UPSERT, inside the savepoint"


# =========================================================================== #
# Gate bullet 6 — ollama-ondemand residency-only floor (K); None/0 baseline (K2, BC3).
# =========================================================================== #
def test_ollama_ondemand_floor_is_residency_only():
    # The peecee ollama-ondemand slot uses the RESIDENCY-ONLY floor; the aggressive
    # scratch-allocation floor (which could force a load) is NEVER invoked (GATE 2 / OQ-B).
    scratch = CallSpy()
    cap = hb.capacity_telemetry(
        "ollama-ondemand", _stats(free=21690, util=0), probe_ms=None,
        scratch_floor_fn=scratch, residency_floor_fn=lambda s: s["vram_free_mib"])
    assert scratch.calls == 0, "ollama-ondemand must NOT invoke the scratch-allocation floor"
    assert cap["probe_floor_mib"] == 21000              # residency-only floor (21690 banded)
    # measured even though there is NO probe/baseline (BC3: not 'absent' just because slowdown NULL).
    assert cap["capacity_source"] == "measured"
    assert cap["cold_probe_ms"] is None


def test_none_probe_yields_well_formed_row(monkeypatch):
    # K2 (BC3): a failed probe (probe_ms=None) and a cold ollama-ondemand slot (probe_ms=None,
    # no baseline) each produce a WELL-FORMED companion row with the tick completing — no
    # TypeError/ZeroDivisionError. live_slowdown_factor is NOT a Python field (computed in SQL).
    for served in ("llama-3", "ollama-ondemand"):
        cap = hb.capacity_telemetry(served, _stats(free=22000), probe_ms=None)
        assert {"cold_probe_ms", "probe_floor_mib", "effective_free_mib",
                "capacity_source"} <= set(cap)
        assert cap["cold_probe_ms"] is None
        assert "live_slowdown_factor" not in cap, "slowdown must be computed in SQL, not Python"
        assert cap["capacity_source"] == "measured"

    # And the FULL push tick completes with a None probe (the savepoint companion write runs).
    monkeypatch.setattr(hb, "gpu_stats", lambda cmd, *a, **k: _stats())
    monkeypatch.setattr(hb, "discover_served_model", lambda *a, **k: "m")
    monkeypatch.setattr(hb, "decode_probe", lambda *a, **k: (False, None, "probe timed out"))
    args = types.SimpleNamespace(
        node="n", endpoint="http://n:8081/v1", slot_id=0, gpu_cmd="nvidia-smi",
        served_model="m", probe_model="m", nvlink_domain=None, max_context=8192,
        latency_class="batch", free_slots=1, min_load_vram_mib=None, epoch=0,
        timeout=5.0, push=False)
    conn = RecordingConn()
    out = hb.heartbeat_once(conn, args)         # must NOT raise
    assert out["alive"] is False and out["probe_ms"] is None
    assert hb.CAPACITY_UPSERT in [s for s, _ in conn.calls]
