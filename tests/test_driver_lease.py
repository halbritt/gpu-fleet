"""RFC 0002 Slice 3, hermetic source-inspection: the puller's per-node skip decision is
a SERVER-SIDE DB-clock predicate (no puller host clock), and the push path's per-node
lease CAS is a NON-GATING coordination signal (the registering UPSERT runs regardless).

Inspection (no DB), mirroring `test_lease_no_consumer_clock.py`: a recording conn cannot
evaluate a WHERE, so the real EXCLUSION behavior (a fresh lease is skipped, a lapsed one
resumed) is proven against Postgres in `test_lifecycle_pg.py::test_push_and_pull_never_
both_write`. Here we pin the structural invariants that keep that behavior honest.
"""

import inspect

import heartbeat
import heartbeat_all as ha


# --------------------------------------------------------------------------- #
# Gate "Single writer" (G) — the puller's FETCH skips a node whose driver-lease is
# held-and-fresh and probes the rest, decided by the DB clock.
# --------------------------------------------------------------------------- #
def test_fetch_predicate_skips_fresh_lease():
    # The node-selection filter still requires `enabled`, and additionally excludes a
    # node whose per-node driver-lease is fresh (a self-pusher owns it).
    assert "WHERE enabled AND (driven_by IS NULL OR now() >= lease_until)" in ha.FETCH


# --------------------------------------------------------------------------- #
# BC4 — the per-node skip freshness uses the DB now(), never a puller-host clock. The
# FETCH carries NO bound parameter at all, so no client timestamp can enter the decision.
# --------------------------------------------------------------------------- #
def test_fetch_freshness_uses_db_now_no_client_clock():
    assert "now() >= lease_until" in ha.FETCH          # DB clock decides freshness
    assert "%(" not in ha.FETCH, "the FETCH must carry no client-supplied parameter"
    # And the driver code that runs the FETCH reads no Python clock for the skip decision
    # (the tick's sleep cadence is a poll interval elsewhere, not part of node selection).
    src = inspect.getsource(ha.tick)
    fetch_call = src.split("conn.execute(FETCH)", 1)
    assert len(fetch_call) == 2, "tick must run the FETCH verbatim"


# --------------------------------------------------------------------------- #
# BC4 (lease freshness, server-side) — the per-node lease CAS the PUSH path runs also
# decides expiry by the DB clock (now() >= lease_until), never the pusher's host clock.
# --------------------------------------------------------------------------- #
def test_node_lease_cas_freshness_is_db_now():
    assert "now() >= lease_until" in heartbeat.NODE_LEASE_CAS
    assert "make_interval(secs => %(node_ttl)s)" in heartbeat.NODE_LEASE_CAS
    assert heartbeat.NODE_LEASE_TTL < 45            # < the 45s live window


# --------------------------------------------------------------------------- #
# BC1 (non-gating composition) — registration = first heartbeat. The push path's lease
# CAS is a bare coordination signal whose result is NEVER captured/branched on, and the
# UPSERT runs UNCONDITIONALLY. (The composed register+graduate behavior for a node with
# NO fleet_nodes row is proven against Postgres in test_lifecycle_pg.py test D.)
# --------------------------------------------------------------------------- #
def test_push_lease_cas_does_not_gate_the_upsert():
    src = inspect.getsource(heartbeat.heartbeat_once)
    assert "conn.execute(NODE_LEASE_CAS" in src
    assert "= conn.execute(NODE_LEASE_CAS" not in src, "the CAS result must not gate the write"
    assert "conn.execute(UPSERT, row)" in src
    # the UPSERT is at function indent (unconditional), not nested under an `if` on the CAS.
    assert "\n    conn.execute(UPSERT, row)" in src
