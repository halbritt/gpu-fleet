"""RFC 0003 writer-side, hermetic: the heartbeat UPSERT bumps epoch ONLY on a
routing-relevant change, and discovery is STICKY so a transient /models blip cannot
flap served_model (BC1).

No DB, no real HTTP: the UPSERT bump diff is asserted by inspecting the real SQL
constant; the sticky-discovery behavior drives the real `discover_served_model` with
a monkeypatched urlopen (mirroring test_load_aware_liveness's ollama_resident tests).
The matching end-to-end PG proofs (epoch actually moves / stays put in Postgres) are
the guarded tests in test_epoch_pg.py.
"""

import json
import urllib.error

import heartbeat


# --------------------------------------------------------------------------- #
# Gate bullet 2 (writer side) — the epoch bump diff covers routing-relevant fields
# and EXCLUDES VRAM/util churn, so an expected fluctuation never bumps epoch.  ("D")
# --------------------------------------------------------------------------- #
def test_bump_diff_excludes_churn_fields():
    sql = heartbeat.UPSERT
    # The conflict path PRESERVES the existing epoch and bumps it via a CASE — it no
    # longer clobbers it with the static config value.
    assert "gpu_slots.epoch + CASE" in sql
    assert "epoch=EXCLUDED.epoch" not in sql

    # Isolate the bump CASE and check exactly which columns drive it.
    case = sql.split("gpu_slots.epoch + CASE", 1)[1].split("END", 1)[0]
    assert "IS DISTINCT FROM" in case  # NULL-safe diff
    for col in ("served_model", "nvlink_domain", "max_context"):
        assert f"gpu_slots.{col}" in case and f"EXCLUDED.{col}" in case, col
    # VRAM / util are expected churn -> they must NOT be in the bump diff (no re-pick
    # storms). They are still UPSERTed; they simply never trigger an epoch bump.
    assert "vram_free_mib" not in case
    assert "gpu_util_pct" not in case


# --------------------------------------------------------------------------- #
# BC1 — sticky discovery: a transient /models failure must not flap served_model
# (and therefore cannot bump epoch).  ("G")
# --------------------------------------------------------------------------- #
class _Resp:
    """Minimal urlopen() context-manager stand-in returning a canned /models body."""

    def __init__(self, payload):
        self._data = json.dumps(payload).encode()

    def read(self):
        return self._data

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False


def test_transient_discovery_failure_does_not_flap_or_bump(monkeypatch):
    heartbeat.reset_discovery_cache()
    ep = "http://node:8081/v1"
    calls = {"n": 0}

    def fake_urlopen(url, timeout=None):
        calls["n"] += 1
        if calls["n"] == 1:
            return _Resp({"data": [{"id": "llama-3"}]})  # one model -> discovered
        raise urllib.error.URLError("transient /models blip")  # next tick fails

    monkeypatch.setattr(heartbeat.urllib.request, "urlopen", fake_urlopen)

    first = heartbeat.discover_served_model(ep, "fallback-model")
    second = heartbeat.discover_served_model(ep, "fallback-model")

    assert first == "llama-3"          # discovered from /models on the good tick
    assert second == "llama-3"         # (i) sticky: held across the transient blip
    assert second != "fallback-model"  #     NOT overwritten by the differing static tag
    # (ii) served_model is identical tick-over-tick, so the UPSERT epoch CASE — which
    # bumps only when served_model/nvlink_domain/max_context change (test above) —
    # bumps +0. (The real epoch-stays-put proof against Postgres is in test_epoch_pg.)
    assert first == second


def test_transient_failure_before_any_discovery_uses_static_fallback(monkeypatch):
    # Stickiness only PROTECTS a value already learned: before any successful
    # discovery, a transient failure still degrades to the static fallback (exactly
    # today's behavior — the cache adds no new failure mode on a cold endpoint).
    heartbeat.reset_discovery_cache()

    def always_fail(url, timeout=None):
        raise urllib.error.URLError("endpoint down")

    monkeypatch.setattr(heartbeat.urllib.request, "urlopen", always_fail)
    assert heartbeat.discover_served_model("http://fresh:8081/v1", "cfg-tag") == "cfg-tag"


def test_successful_rediscovery_updates_the_sticky_value(monkeypatch):
    # A GENUINE (non-transient) capability change still flows through: a later
    # successful /models read replaces the cached value, so a real model swap is NOT
    # masked by stickiness (and IS allowed to bump epoch).
    heartbeat.reset_discovery_cache()
    ep = "http://node:8081/v1"
    state = {"id": "llama-3"}

    def fake_urlopen(url, timeout=None):
        return _Resp({"data": [{"id": state["id"]}]})

    monkeypatch.setattr(heartbeat.urllib.request, "urlopen", fake_urlopen)
    assert heartbeat.discover_served_model(ep, "fallback") == "llama-3"
    state["id"] = "mistral"  # the node really swapped models
    assert heartbeat.discover_served_model(ep, "fallback") == "mistral"
