"""Behavior of the heartbeat tick's probe phase.

The registry's correctness guarantee is: one slow or black-hole node must not
delay the heartbeat of the healthy ones (else they age out of `live_slots`
past the 45s TTL and falsely disappear). These tests pin that down through the
public `probe_all` surface, independent of how the probe itself is implemented.
"""

import time

import heartbeat_all as ha


def test_probe_all_runs_concurrently():
    # Five nodes, each probe takes 0.3s. Serial = 1.5s; concurrent ~= 0.3s.
    # A black-hole node is just the worst case of "one slow probe".
    nodes = [{"node": f"n{i}"} for i in range(5)]

    def slow_probe(n):
        time.sleep(0.3)
        return {"node": n["node"], "alive": True, "probe_ms": 300}

    t0 = time.monotonic()
    results = ha.probe_all(nodes, probe_fn=slow_probe)
    elapsed = time.monotonic() - t0

    assert {r["node"] for r in results} == {f"n{i}" for i in range(5)}
    assert all(r["alive"] for r in results)
    assert elapsed < 0.9, f"probe_all serialized the tick: {elapsed:.2f}s for 5x0.3s"


def test_probe_all_isolates_a_failing_probe():
    # A probe that raises (ssh down, unexpected error) must not sink the others;
    # the directory should record that node as not-alive, the rest as alive.
    nodes = [{"node": "good"}, {"node": "bad"}, {"node": "good2"}]

    def flaky_probe(n):
        if n["node"] == "bad":
            raise RuntimeError("boom: ssh unreachable")
        return {"node": n["node"], "alive": True, "probe_ms": 10}

    results = ha.probe_all(nodes, probe_fn=flaky_probe)
    by_node = {r["node"]: r for r in results}

    assert by_node["good"]["alive"] is True
    assert by_node["good2"]["alive"] is True
    assert by_node["bad"]["alive"] is False
    assert "boom" in (by_node["bad"].get("note") or "")


def test_probe_each_yields_fast_node_before_slow_node():
    # The slow node is listed first, but its row must NOT gate the fast node's —
    # `probe_each` yields by completion, so the tick writes (and refreshes the
    # heartbeat of) the fast node without waiting on the slow one.
    nodes = [{"node": "slow"}, {"node": "fast"}]

    def probe(n):
        time.sleep(0.5 if n["node"] == "slow" else 0.0)
        return {"node": n["node"], "alive": True, "probe_ms": 0}

    order = [r["node"] for r in ha.probe_each(nodes, probe_fn=probe)]
    assert order[0] == "fast", f"a slow probe delayed the fast node's write: {order}"
