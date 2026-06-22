"""Behavior of di-fleet's K-fan-out: spread di's divergence branches across N live
fleet slots so wall-clock drops ~linearly with N, and lose no branch when a slot
dies mid-run.

These pin the two load-bearing guarantees through the public surface — sharding,
concurrency, failover, merge — with an INJECTED fake shard-runner (like `probe_fn`
in test_probe_all). No real subprocess, DB, or HTTP touches these tests.
"""

import time

import di_fleet as df


# --------------------------------------------------------------------------- #
# Helpers: fake slots + a fake RunResult shaped like `di --json`.
# --------------------------------------------------------------------------- #
def _slots(n):
    return [{"endpoint_url": f"http://node{i}:8081/v1", "served_model": "m",
             "probe_ms": 1.0} for i in range(n)]


def _idea(id_, total, novelty=0, trap=False, text=None):
    return {"id": id_, "frameId": "f0", "text": text or id_,
            "score": {"novelty": novelty, "viability": 0, "fit": 0,
                      "total": total, "trap": trap},
            "depth": 0}


def _runresult(problem="p", ideas=None, shortlist=None, traps=None,
               provocation="prov", reframe=None):
    ideas = ideas or []
    return {
        "problem": problem,
        "reframe": reframe,
        "branches": [{"frameId": "f0", "ideas": ideas}],
        "clusters": [{"label": "c", "ideaIds": [i["id"] for i in ideas]}],
        "shortlist": shortlist if shortlist is not None else ideas,
        "nonObviousPick": ideas[0] if ideas else None,
        "traps": traps or [],
        "deepened": [{"ideaId": ideas[0]["id"], "sketch": "s", "childIdeas": []}]
        if ideas else [],
        "provocation": provocation,
    }


# --------------------------------------------------------------------------- #
# 1. Sharding: F frames split across N endpoints is balanced and sums to F.
# --------------------------------------------------------------------------- #
def test_shard_frames_is_balanced_and_sums_to_F():
    for total, n in [(12, 4), (10, 3), (5, 5), (7, 2), (1, 4), (5, 8)]:
        shards = df.shard_frames(total, n)
        assert sum(shards) == total, f"{total}/{n} did not sum: {shards}"
        # balanced: any two shards differ by at most 1
        assert max(shards) - min(shards) <= 1, f"{total}/{n} unbalanced: {shards}"
        # never more shards than frames (no 0-frame, pointless shard)
        assert all(s >= 1 for s in shards), f"{total}/{n} has empty shard: {shards}"
        assert len(shards) == min(n, total)


# --------------------------------------------------------------------------- #
# 2. Concurrency: N shards each sleeping 0.3s finish in <0.9s, not N*0.3s.
# --------------------------------------------------------------------------- #
def test_dispatch_runs_shards_concurrently():
    slots = _slots(5)

    def slow(endpoint, frames, flags):
        time.sleep(0.3)
        return _runresult(ideas=[_idea(endpoint["endpoint_url"], total=1)])

    t0 = time.monotonic()
    results, lost = df.dispatch(slots, total_frames=10, flags=[], shard_fn=slow)
    elapsed = time.monotonic() - t0

    assert not lost
    assert len(results) == 5
    assert elapsed < 0.9, f"dispatch serialized: {elapsed:.2f}s for 5x0.3s"


# --------------------------------------------------------------------------- #
# 3. Failover: a runner that raises for endpoint X reassigns X's frames to a
#    survivor; no branch lost — every frame is accounted for in the results.
# --------------------------------------------------------------------------- #
def test_failover_reassigns_dead_shard_to_survivor_no_branch_lost():
    slots = _slots(3)
    dead = slots[1]["endpoint_url"]
    calls = []

    def flaky(endpoint, frames, flags):
        calls.append((endpoint["endpoint_url"], frames))
        # The dead slot fails ONLY on its first (own) attempt; on the failover
        # retry it is a *different, surviving* endpoint, which succeeds.
        if endpoint["endpoint_url"] == dead:
            raise RuntimeError("boom: slot died mid-run")
        return _runresult(ideas=[_idea(endpoint["endpoint_url"], total=1)])

    results, lost = df.dispatch(slots, total_frames=9, flags=[], shard_fn=flaky)

    assert lost == [], f"a branch was lost despite a live survivor: {lost}"
    # All 9 frames are accounted for across the surviving results.
    assert sum(r["frames"] for r in results) == 9
    # The dead shard was retried on a survivor (failed_over_from recorded).
    assert any(r.get("failed_over_from") == dead for r in results)
    # The dead endpoint was attempted exactly once (no infinite retry on itself).
    assert sum(1 for ep, _ in calls if ep == dead) == 1


def test_total_fleet_wipe_abandons_frames_explicitly(capsys):
    # If EVERY shard dies, there is no survivor to fail over to: those frames are
    # abandoned and said so on stderr (the only time "no branch lost" cannot hold).
    slots = _slots(2)

    def all_dead(endpoint, frames, flags):
        raise RuntimeError("slot died")

    results, lost = df.dispatch(slots, total_frames=6, flags=[], shard_fn=all_dead)
    assert results == []
    assert sum(x["frames"] for x in lost) == 6
    err = capsys.readouterr().err
    assert "ABANDONED" in err


# --------------------------------------------------------------------------- #
# 4. Merge: 2 RunResults -> shortlist globally re-sorted by score.total; branches
#    concatenated with unique frameIds; traps deduped.
# --------------------------------------------------------------------------- #
def test_merge_resorts_shortlist_globally_and_dedups_traps():
    trap = _idea("dup-trap", total=1, trap=True, text="same trap text")
    a = _runresult(
        ideas=[_idea("a1", total=5, novelty=9), _idea("a2", total=3)],
        shortlist=[_idea("a1", total=5), _idea("a2", total=3)],
        traps=[trap],
        provocation="prov-A",
    )
    b = _runresult(
        ideas=[_idea("b1", total=8, novelty=2), _idea("b2", total=1)],
        shortlist=[_idea("b1", total=8), _idea("b2", total=1)],
        traps=[dict(trap)],  # same text -> must dedup to one
        provocation="prov-B",
    )
    results = [
        {"shard": 0, "endpoint": _slots(1)[0], "frames": 3, "result": a},
        {"shard": 1, "endpoint": _slots(1)[0], "frames": 3, "result": b},
    ]
    merged = df.merge_results(results, top=10)

    # shortlist globally re-sorted by score.total desc: 8, 5, 3, 1
    totals = [df._idea_total(i) for i in merged["shortlist"]]
    assert totals == sorted(totals, reverse=True)
    assert totals == [8, 5, 3, 1]

    # branches concatenated with frameIds namespaced per shard -> globally unique
    fids = [b["frameId"] for b in merged["branches"]]
    assert fids == ["s0:f0", "s1:f0"]
    assert len(fids) == len(set(fids))

    # traps deduped by text
    assert len(merged["traps"]) == 1

    # nonObviousPick = highest-novelty non-trap idea across all shards (a1, nov=9)
    assert merged["nonObviousPick"]["id"] == "a1"

    # problem unchanged; provocation from the strongest shard (b has the top idea)
    assert merged["problem"] == "p"
    assert merged["provocation"] == "prov-B"

    # clusters concatenated (one per shard, labels namespaced)
    assert len(merged["clusters"]) == 2


def test_merge_caps_shortlist_at_top():
    a = _runresult(shortlist=[_idea(f"a{i}", total=10 - i) for i in range(5)])
    b = _runresult(shortlist=[_idea(f"b{i}", total=20 - i) for i in range(5)])
    results = [
        {"shard": 0, "endpoint": _slots(1)[0], "frames": 1, "result": a},
        {"shard": 1, "endpoint": _slots(1)[0], "frames": 1, "result": b},
    ]
    merged = df.merge_results(results, top=3)
    assert len(merged["shortlist"]) == 3
    # the global top-3 by total are b0(20), b1(19), b2(18)
    assert [i["id"] for i in merged["shortlist"]] == ["b0", "b1", "b2"]


# --------------------------------------------------------------------------- #
# 5. N==1 degenerate: pass-through unchanged.
# --------------------------------------------------------------------------- #
def test_merge_single_result_passes_through_unchanged():
    only = _runresult(ideas=[_idea("x1", total=4)], provocation="solo")
    results = [{"shard": 0, "endpoint": _slots(1)[0], "frames": 5, "result": only}]
    merged = df.merge_results(results)
    assert merged is only  # byte-for-byte the same object, untouched


def test_dispatch_single_slot_returns_one_unmerged_result():
    slots = _slots(1)

    def one(endpoint, frames, flags):
        assert frames == 5  # the whole F goes to the single slot
        return _runresult(ideas=[_idea("x", total=1)])

    results, lost = df.dispatch(slots, total_frames=5, flags=[], shard_fn=one)
    assert lost == []
    assert len(results) == 1
    # merge of a single result is the result itself (pass-through)
    assert df.merge_results(results) is results[0]["result"]


# --------------------------------------------------------------------------- #
# Routing filter: http(s)-only, warm-first (never marker's ssh://).
# --------------------------------------------------------------------------- #
def test_filter_llm_slots_drops_non_http_and_orders_warm_first():
    picks = [
        {"endpoint_url": "ssh://peecee", "served_model": "marker", "probe_ms": None},
        {"endpoint_url": "http://cold:8081/v1", "served_model": "m", "probe_ms": None},
        {"endpoint_url": "http://warm:8081/v1", "served_model": "m", "probe_ms": 12.0},
    ]
    out = df._filter_llm_slots(picks)
    urls = [s["endpoint_url"] for s in out]
    assert "ssh://peecee" not in urls          # marker dropped
    assert urls == ["http://warm:8081/v1", "http://cold:8081/v1"]  # warm before cold


def test_route_slots_not_starved_by_non_llm_rows_when_k_is_small():
    # Regression: a non-LLM capability (marker's ssh://) can sort AHEAD of a real
    # LLM slot, so applying k as the SQL LIMIT before filtering could return
    # [marker, one-LLM] and collapse to a single endpoint -> no fan-out. route_slots
    # must fetch a margin beyond k and trim to k AFTER dropping non-LLM rows.
    rows = [
        {"endpoint_url": "ssh://peecee", "served_model": "marker", "probe_ms": None},
        {"endpoint_url": "http://peecee:11434/v1", "served_model": "m", "probe_ms": None},
        {"endpoint_url": "http://localhost:8081/v1", "served_model": "m", "probe_ms": 40},
    ]
    seen = {}

    def fake_pick(fetch_k):
        seen["fetch_k"] = fetch_k
        return rows

    out = df.route_slots(2, pick_fn=fake_pick)
    assert seen["fetch_k"] > 2                       # fetched a margin beyond k
    urls = [s["endpoint_url"] for s in out]
    assert "ssh://peecee" not in urls                # marker dropped
    assert urls == ["http://localhost:8081/v1", "http://peecee:11434/v1"]  # both LLMs, warm first


def test_route_slots_trims_to_k_after_filtering():
    # More live LLM slots than k -> trim to exactly k (warm-first preserved).
    rows = [{"endpoint_url": f"http://n{i}:8081/v1", "served_model": "m",
             "probe_ms": (1.0 if i == 0 else None)} for i in range(5)]
    out = df.route_slots(3, pick_fn=lambda n: rows)
    assert len(out) == 3
    assert out[0]["endpoint_url"] == "http://n0:8081/v1"   # the warm one leads
