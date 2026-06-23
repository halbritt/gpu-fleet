"""Load-aware liveness for the shared on-demand ollama node (peecee slot 0).

peecee time-shares its single 24.5 GiB card between an on-demand MoE
(probe_model='ollama-ondemand') and marker (slot 1). The guarantees these tests
pin down:

  GATE 1 -- di never routes to a peecee that can't serve: when the model is not
            resident and free VRAM is below the loadable threshold (marker owns
            the card), liveness is alive=False, so the row ages out of live_slots
            and di won't route to it.
  GATE 2 -- the heartbeat never forces a model load: we decode-probe ONLY when the
            model is already resident (a no-op load). In both not-resident cases
            (loadable and not-loadable) the decode-probe fake is never called.

The decision lives in the pure helper `heartbeat.ollama_ondemand_liveness`, so it
is unit-testable with injected fakes -- no real DB, no real HTTP, no nvidia-smi.
The marker '-' sentinel is checked end-to-end through `heartbeat_all.probe_node`
(mirroring test_probe_all.py) to prove it is untouched by this change.
"""

import heartbeat as hb
import heartbeat_all as ha


class CallSpy:
    """A decode_probe stand-in that records its call count and returns a fixed
    (alive, probe_ms, err). Lets a test assert decode was NEVER called (the
    'never forces a load' gate) or was called exactly once (the warm path)."""

    def __init__(self, ret=(True, 7, None)):
        self.ret = ret
        self.calls = 0

    def __call__(self, endpoint, model, timeout):
        self.calls += 1
        return self.ret


def _stats(free=24000, total=24500, model="NVIDIA GeForce RTX 3090 Ti"):
    return {"gpu_model": model, "vram_total_mib": total, "vram_free_mib": free,
            "gpu_util_pct": 0}


# --- 1. resident => decode-probe runs => WARM (alive, probe_ms set) -----------

def test_resident_runs_decode_probe_and_is_warm():
    decode = CallSpy(ret=(True, 7, None))
    alive, probe_ms, note = hb.ollama_ondemand_liveness(
        "http://peecee:11434/v1", "qwen3.6:35b-a3b",
        _stats(free=500), gpu_err=None, min_load_vram_mib=23000, timeout=10,
        resident_fn=lambda *a: True, decode_fn=decode,
    )
    assert alive is True
    assert probe_ms == 7                  # warm => probe_ms set
    assert decode.calls == 1              # resident => we DO probe (no-op load)
    assert note == "resident"


# --- 2. not resident, free >= threshold => COLD/LOADABLE, NO decode -----------

def test_not_resident_with_headroom_is_loadable_without_probing():
    decode = CallSpy()
    alive, probe_ms, note = hb.ollama_ondemand_liveness(
        "http://peecee:11434/v1", "qwen3.6:35b-a3b",
        _stats(free=24000), gpu_err=None, min_load_vram_mib=23000, timeout=10,
        resident_fn=lambda *a: False, decode_fn=decode,
    )
    assert alive is True                  # the card is free enough to load on demand
    assert probe_ms is None               # cold => probe_ms NULL
    assert decode.calls == 0              # GATE 2: never force a load
    assert note == "loadable: free=24000MiB"


# --- 3. not resident, free < threshold => NOT LOADABLE, NO decode ------------

def test_not_resident_without_headroom_is_not_loadable_without_probing():
    decode = CallSpy()
    alive, probe_ms, note = hb.ollama_ondemand_liveness(
        "http://peecee:11434/v1", "qwen3.6:35b-a3b",
        _stats(free=400), gpu_err=None, min_load_vram_mib=23000, timeout=10,
        resident_fn=lambda *a: False, decode_fn=decode,
    )
    assert alive is False                 # GATE 1: marker owns the card => not serveable
    assert probe_ms is None
    assert decode.calls == 0              # GATE 2: never force a load
    assert "not loadable" in note and "400" in note and "23000" in note


# --- 4. gpu_stats error => alive False ---------------------------------------

def test_gpu_error_is_not_alive():
    decode = CallSpy()
    alive, probe_ms, note = hb.ollama_ondemand_liveness(
        "http://peecee:11434/v1", "qwen3.6:35b-a3b",
        {}, gpu_err="gpu_stats: ssh unreachable", min_load_vram_mib=23000,
        timeout=10, resident_fn=lambda *a: True, decode_fn=decode,
    )
    assert alive is False
    assert probe_ms is None
    assert decode.calls == 0              # GPU down => don't even talk to ollama


# --- 5. GATE proof: decode_probe call count is 0 in the two not-resident cases.
#        (Asserted inline in tests 2 and 3 via `decode.calls == 0`; restated here
#        as a single explicit proof that the heartbeat never forces a load.) ----

def test_gate_heartbeat_never_forces_a_load():
    for free in (24000, 400):            # loadable and not-loadable
        decode = CallSpy()
        hb.ollama_ondemand_liveness(
            "http://peecee:11434/v1", "qwen3.6:35b-a3b",
            _stats(free=free), gpu_err=None, min_load_vram_mib=23000, timeout=10,
            resident_fn=lambda *a: False, decode_fn=decode,
        )
        assert decode.calls == 0, f"heartbeat forced a load at free={free}MiB"


# --- threshold fallback: min_load_vram_mib NULL => default / 95% of total -----

def test_null_threshold_falls_back_to_default():
    # NULL threshold => flat DEFAULT_MIN_LOAD_VRAM_MIB (21000); no card-fraction
    # heuristic (that misfires on a card with irreducible desktop overhead). free
    # well above the default => loadable; free well below => not loadable.
    decode = CallSpy()
    alive, probe_ms, note = hb.ollama_ondemand_liveness(
        "http://peecee:11434/v1", "qwen3.6:35b-a3b",
        _stats(free=24000, total=24500), gpu_err=None, min_load_vram_mib=None,
        timeout=10, resident_fn=lambda *a: False, decode_fn=decode,
    )
    assert alive is True and probe_ms is None and decode.calls == 0

    # And below both floors with NULL threshold => not loadable.
    decode2 = CallSpy()
    alive2, _, _ = hb.ollama_ondemand_liveness(
        "http://peecee:11434/v1", "qwen3.6:35b-a3b",
        _stats(free=10000, total=24500), gpu_err=None, min_load_vram_mib=None,
        timeout=10, resident_fn=lambda *a: False, decode_fn=decode2,
    )
    assert alive2 is False and decode2.calls == 0


# --- ollama_resident parsing (with a fake urlopen) ---------------------------

def test_ollama_resident_strips_v1_and_matches_name(monkeypatch):
    import io
    seen = {}

    class FakeResp:
        def __init__(self, payload):
            self._b = payload.encode()

        def read(self):
            return self._b

        def __enter__(self):
            return io.BytesIO(self._b)

        def __exit__(self, *a):
            return False

    def fake_urlopen(url, timeout=None):
        seen["url"] = url
        return FakeResp('{"models":[{"name":"qwen3.6:35b-a3b","size_vram":1}]}')

    monkeypatch.setattr(hb.urllib.request, "urlopen", fake_urlopen)
    assert hb.ollama_resident("http://peecee:11434/v1", "qwen3.6:35b-a3b", 5) is True
    # /v1 stripped, /api/ps reached -- NOT /v1/api/ps
    assert seen["url"] == "http://peecee:11434/api/ps"


def test_ollama_resident_false_when_empty(monkeypatch):
    import io

    class FakeResp:
        def __enter__(self):
            return io.BytesIO(b'{"models":[]}')

        def __exit__(self, *a):
            return False

    monkeypatch.setattr(hb.urllib.request, "urlopen",
                        lambda url, timeout=None: FakeResp())
    assert hb.ollama_resident("http://peecee:11434/v1", "qwen3.6:35b-a3b", 5) is False


def test_ollama_resident_false_on_error(monkeypatch):
    def boom(url, timeout=None):
        raise OSError("connection refused")

    monkeypatch.setattr(hb.urllib.request, "urlopen", boom)
    assert hb.ollama_resident("http://peecee:11434/v1", "qwen3.6:35b-a3b", 5) is False


# --- 6. marker '-' sentinel still = GPU-reachability liveness (unchanged) -----

def test_marker_dash_sentinel_is_gpu_reachability(monkeypatch):
    # Drive the real probe_node with a node whose probe_model is the marker
    # sentinel '-'. It must be alive purely from nvidia-smi (no decode-probe, no
    # ollama_resident), exactly as before this change.
    def fake_gpu_stats(cmd, timeout):
        return {"gpu_model": "RTX 3090 Ti", "vram_total_mib": 24500,
                "vram_free_mib": 400, "gpu_util_pct": 90}

    def boom_decode(*a, **k):
        raise AssertionError("marker slot must NOT decode-probe")

    def boom_resident(*a, **k):
        raise AssertionError("marker slot must NOT touch ollama /api/ps")

    monkeypatch.setattr(ha, "gpu_stats", fake_gpu_stats)
    monkeypatch.setattr(ha, "decode_probe", boom_decode)
    monkeypatch.setattr(ha, "ollama_ondemand_liveness", boom_resident)

    node = {
        "node": "peecee", "slot_id": 1, "endpoint_url": "ssh://peecee",
        "served_model": "marker", "probe_model": "-", "latency_class": "batch",
        "gpu_cmd": "ssh peecee nvidia-smi", "nvlink_domain": None,
        "max_context": None, "free_slots": 1, "epoch": 0,
        "min_load_vram_mib": None,   # marker row: column is NULL, must be ignored
    }
    row = ha.probe_node(node)
    assert row["alive"] is True          # GPU reachable => alive, regardless of VRAM
    assert row["probe_ms"] is None
    assert row["served_model"] == "marker"


def test_marker_dash_sentinel_dead_when_gpu_unreachable(monkeypatch):
    def gpu_down(cmd, timeout):
        return {"_error": "gpu_stats: ssh unreachable"}

    monkeypatch.setattr(ha, "gpu_stats", gpu_down)
    node = {
        "node": "peecee", "slot_id": 1, "endpoint_url": "ssh://peecee",
        "served_model": "marker", "probe_model": "-", "latency_class": "batch",
        "gpu_cmd": "ssh peecee nvidia-smi", "nvlink_domain": None,
        "max_context": None, "free_slots": 1, "epoch": 0, "min_load_vram_mib": None,
    }
    row = ha.probe_node(node)
    assert row["alive"] is False


# --- probe_node end-to-end for the ollama-ondemand branch (not-loadable) ------

def test_probe_node_ollama_ondemand_not_loadable_does_not_probe(monkeypatch):
    # Full probe_node path: model not resident, marker owns the card => alive=False
    # and decode_probe is never reached (GATE 2 end-to-end through probe_node).
    def fake_gpu_stats(cmd, timeout):
        return {"gpu_model": "RTX 3090 Ti", "vram_total_mib": 24500,
                "vram_free_mib": 400, "gpu_util_pct": 95}

    def boom_decode(*a, **k):
        raise AssertionError("not-loadable slot must NOT decode-probe")

    monkeypatch.setattr(ha, "gpu_stats", fake_gpu_stats)
    monkeypatch.setattr(ha, "decode_probe", boom_decode)
    # not resident
    monkeypatch.setattr(hb, "ollama_resident", lambda *a, **k: False)

    node = {
        "node": "peecee", "slot_id": 0, "endpoint_url": "http://peecee:11434/v1",
        "served_model": "qwen3.6:35b-a3b", "probe_model": "ollama-ondemand",
        "latency_class": "batch", "gpu_cmd": "ssh peecee nvidia-smi",
        "nvlink_domain": None, "max_context": 32768, "free_slots": 1, "epoch": 0,
        "min_load_vram_mib": 23000,
    }
    row = ha.probe_node(node)
    assert row["alive"] is False
    assert row["probe_ms"] is None
    assert "not loadable" in (row["note"] or "")


# --- BC8 / gate "peecee runs zero fleet code/creds, still monitored via pull" ------
# Companion to the de-list proof above (which v1 keeps under peecee's existing SSH-via-
# pull liveness — option (a)): the pull path is PURE I/O. probe_node takes no DB
# connection, returns an UPSERT-ready row written through the DRIVER's connection only,
# and stamps boot_epoch NULL (an HTTP/SSH probe carries no boot identity, so no node
# credential or boot token is asserted on peecee's behalf). The MEASURED gpu_uuid from
# the puller's cross-host nvidia-smi is still carried (identity survives churn).

def test_pull_only_node_has_no_db_path(monkeypatch):
    import inspect

    # probe_node is pure I/O: it accepts only a node dict (no conn parameter), so a
    # pull-only node never has a database path of its own. (The caller owns the single
    # DB connection — its docstring says so — so we assert on the CODE: no DB calls.)
    sig = inspect.signature(ha.probe_node)
    assert list(sig.parameters) == ["n"], "probe_node must take no DB connection"
    src = inspect.getsource(ha.probe_node)
    assert ".execute(" not in src and ".commit(" not in src and "psycopg" not in src

    def fake_gpu_stats(cmd, timeout):
        return {"gpu_model": "RTX 3090 Ti", "vram_total_mib": 24500,
                "vram_free_mib": 24000, "gpu_util_pct": 0, "gpu_uuid": "GPU-PEECEE"}

    monkeypatch.setattr(ha, "gpu_stats", fake_gpu_stats)
    monkeypatch.setattr(hb, "ollama_resident", lambda *a, **k: False)  # cold-loadable

    node = {
        "node": "peecee", "slot_id": 0, "endpoint_url": "http://peecee:11434/v1",
        "served_model": "qwen3.6:35b-a3b", "probe_model": "ollama-ondemand",
        "latency_class": "batch", "gpu_cmd": "ssh peecee nvidia-smi",
        "nvlink_domain": None, "max_context": 32768, "free_slots": 1, "epoch": 0,
        "min_load_vram_mib": 23000,
    }
    row = ha.probe_node(node)
    assert row["alive"] is True                  # loadable -> still monitored via pull
    assert row["boot_epoch"] is None             # pull asserts NO boot identity (ratchet inert)
    assert row["gpu_uuid"] == "GPU-PEECEE"       # measured identity still carried (BC7/J)
