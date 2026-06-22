"""RFC 0001 Principle 2 — Postgres is the ONLY clock.

Source-inspection gate (no DB): every lease expiry/fence decision is evaluated by
Postgres `now()`, and the lease PREDICATE functions (claim / renew / release /
failover_transfer) read NO Python clock at all, so consumer/Postgres clock skew is
structurally impossible. The renew LOOP (run_leased_shard) may use a Python clock for
its sleep cadence — that is a poll interval, not a predicate — so we inspect the lease
functions specifically, by AST, rather than the whole module.
"""

import ast
import inspect

import di_fleet


LEASE_FUNCS = ("claim", "renew", "release", "failover_transfer")


def test_lease_sql_decides_expiry_and_fencing_with_postgres_now():
    # Expiry is server-stamped (now() + ttl); free/renew predicates compare against
    # now(); fencing is the lease_id identity match.
    assert "now() + make_interval" in di_fleet.LEASE_CLAIM_SQL
    assert "now() >= lease_expires" in di_fleet.LEASE_CLAIM_SQL  # free-or-expired
    assert "now() + make_interval" in di_fleet.LEASE_RENEW_SQL
    assert "now() < lease_expires" in di_fleet.LEASE_RENEW_SQL   # renew guard
    assert "lease_id = %(lease_id)s" in di_fleet.LEASE_RENEW_SQL  # fenced by identity
    assert "lease_id = %(lease_id)s" in di_fleet.LEASE_RELEASE_SQL


def test_lease_functions_read_no_python_clock():
    # None of the lease predicate functions may touch time.* / datetime.* — if they
    # never read a Python clock, they cannot leak one into an expiry/fence decision.
    for name in LEASE_FUNCS:
        fn = getattr(di_fleet, name)
        src = inspect.getsource(fn)
        tree = ast.parse(src)
        for node in ast.walk(tree):
            if isinstance(node, ast.Attribute) and isinstance(node.value, ast.Name):
                assert node.value.id not in ("time", "datetime"), (
                    f"{name} reads a Python clock: {node.value.id}.{node.attr}")
            if isinstance(node, ast.Name):
                assert node.id not in ("time", "datetime"), (
                    f"{name} references the Python clock module {node.id}")
