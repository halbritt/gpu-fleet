"""A heartbeat must not contend with the workload holding a slot lease."""

import heartbeat_all as ha


NODE = {
    "node": "proximal",
    "slot_id": 0,
    "endpoint_url": "http://localhost:8081/v1",
    "served_model": "qwen3.6-35b-a3b",
    "probe_model": "qwen3.6-35b-a3b",
    "latency_class": "interactive",
    "gpu_cmd": "nvidia-smi",
    "nvlink_domain": None,
    "max_context": 262144,
    "free_slots": 1,
    "epoch": 0,
    "min_load_vram_mib": None,
    "lease_active": True,
}


def _gpu_stats(*_args, **_kwargs):
    return {
        "gpu_model": "NVIDIA RTX 5090",
        "vram_total_mib": 32768,
        "vram_free_mib": 2000,
        "gpu_util_pct": 100,
        "gpu_uuid": "GPU-1",
        "mig_mode": None,
        "ecc_mode": None,
    }


def test_fetch_derives_active_consumer_lease_with_database_clock():
    assert "AS lease_active" in ha.FETCH
    assert "now() < gpu_slots.lease_expires" in ha.FETCH
    assert "(gpu_slots.node, gpu_slots.endpoint_url, gpu_slots.slot_id)" in ha.FETCH
    assert (
        "(fleet_nodes.node, fleet_nodes.endpoint_url, fleet_nodes.slot_id)" in ha.FETCH
    )
    assert "%(" not in ha.FETCH


def test_active_lease_uses_gpu_reachability_without_decode_probe(monkeypatch):
    monkeypatch.setattr(ha, "gpu_stats", _gpu_stats)
    monkeypatch.setattr(
        ha,
        "decode_probe",
        lambda *_args: (_ for _ in ()).throw(AssertionError("decode probe contended")),
    )
    monkeypatch.setattr(
        ha,
        "discover_served_model",
        lambda *_args: (_ for _ in ()).throw(AssertionError("discovery contended")),
    )

    row = ha.probe_node(NODE)

    assert row["alive"] is True
    assert row["served_model"] == NODE["served_model"]
    assert row["loaded_model"] == NODE["served_model"]
    assert row["probe_ms"] is None
    assert row["probe_verified"] is False
    assert row["note"] == "lease active: decode probe suppressed"


def test_active_lease_still_fences_when_gpu_is_unreachable(monkeypatch):
    monkeypatch.setattr(
        ha, "gpu_stats", lambda *_args: {"_error": "gpu_stats: unreachable"}
    )
    monkeypatch.setattr(
        ha,
        "decode_probe",
        lambda *_args: (_ for _ in ()).throw(AssertionError("decode probe contended")),
    )

    row = ha.probe_node(NODE)

    assert row["alive"] is False
    assert row["loaded_model"] is None
    assert row["probe_verified"] is False
    assert "gpu_stats: unreachable" in row["note"]


def test_unleased_slot_still_requires_decode_probe(monkeypatch):
    monkeypatch.setattr(ha, "gpu_stats", _gpu_stats)
    monkeypatch.setattr(
        ha, "discover_served_model", lambda *_args: NODE["served_model"]
    )
    monkeypatch.setattr(
        ha, "decode_probe", lambda *_args: (False, None, "probe: timed out")
    )

    row = ha.probe_node({**NODE, "lease_active": False})

    assert row["alive"] is False
    assert row["loaded_model"] is None
    assert row["probe_verified"] is True
    assert row["note"] == "probe: timed out"
