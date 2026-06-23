"""Behavior of the RFC 0001 pick query: it selects only LEASE-FREE slots, disperses
the herd with a stable NULL-safe jitter, and keeps surfacing `free_slots` so the
readers-before-writers rollout never breaks an un-upgraded reader.

Hermetic: a recording fake `conn` captures the SQL + params and returns canned rows
(like `probe_fn` in test_probe_all). No real DB; `import pick_slot` needs no driver
(psycopg is imported lazily inside main()).
"""

import pick_slot


class RecordingConn:
    """Captures (sql, params) and returns canned rows shaped like the PICK SELECT."""

    def __init__(self, rows):
        self._rows = rows
        self.calls = []

    def execute(self, sql, params=None):
        self.calls.append((sql, params or {}))
        return self

    def fetchall(self):
        return list(self._rows)


# A row tuple in PICK's exact column order (pick_slot.COLS).
def _row(node="proximal", url="http://proximal:8081/v1", slot_id=0, model="m",
         lclass="interactive", vram=24000, capacity=1, nvlink=None, probe=12,
         lease_id=None, lease_expires=None, epoch=0):
    return (node, url, slot_id, model, lclass, vram, capacity, nvlink, probe,
            lease_id, lease_expires, epoch)


# --------------------------------------------------------------------------- #
# Lease-free predicate is in the WHERE.
# --------------------------------------------------------------------------- #
def test_pick_query_filters_to_lease_free_slots():
    conn = RecordingConn([_row()])
    pick_slot.pick(conn, k=3)
    sql, _ = conn.calls[0]
    assert "lease_id IS NULL OR now() >= lease_expires" in sql
    # availability is derived from the lease, not from a free_slots counter:
    assert "free_slots" not in sql  # neither SELECT nor ORDER BY references it anymore


def test_pick_returns_lease_columns_so_consumer_can_claim_what_it_picked():
    conn = RecordingConn([_row(lease_id=None, lease_expires=None)])
    out = pick_slot.pick(conn)
    assert "lease_id" in out[0] and "lease_expires" in out[0]
    assert "slot_id" in out[0]  # needed to target the claim's WHERE by PK


# --------------------------------------------------------------------------- #
# BC2 — backward-compat: the returned dict / --json still carries `free_slots`.
# --------------------------------------------------------------------------- #
def test_output_still_contains_free_slots():
    # An un-upgraded reader (old di_fleet, a fleet tool) does result["free_slots"];
    # it must not KeyError during the mixed-version window. free_slots aliases capacity.
    conn = RecordingConn([_row(capacity=1)])
    out = pick_slot.pick(conn)
    assert out[0]["free_slots"] == out[0]["capacity"] == 1
    assert "free_slots" in out[0]


# --------------------------------------------------------------------------- #
# BC3 — the jitter tie-breaker is NULL-safe and stays active for ''/None job.
# --------------------------------------------------------------------------- #
def test_jitter_active_for_empty_and_none_job():
    # The tie-breaker must be present and COALESCE-wrapped so an explicit job=None
    # (SQL NULL) degrades to '' instead of collapsing every row's hash to NULL — and
    # both job='' and job=None thread the value through to the query without error.
    for job in ("", None):
        conn = RecordingConn([_row(), _row(slot_id=1)])
        out = pick_slot.pick(conn, job=job)
        sql, params = conn.calls[0]
        assert "hashtext(COALESCE(%(job)s::text, '')" in sql, "jitter not NULL-safe"
        assert params["job"] == job              # value threaded through verbatim
        assert len(out) == 2                      # tie-breaker did not drop rows


def test_pick_defaults_job_to_empty_string():
    # A no-arg call still works and seeds a stable (non-NULL) jitter.
    conn = RecordingConn([_row()])
    pick_slot.pick(conn)
    _, params = conn.calls[0]
    assert params["job"] == ""


# --------------------------------------------------------------------------- #
# RFC 0003 gate-bullet-3 (reader side) — pick() surfaces the slot's CURRENT epoch
# and served_model, so a re-pick after a bump lands on the NEW capability.
# --------------------------------------------------------------------------- #
def test_pick_surfaces_current_epoch_and_model():
    # After an epoch bump the slot row carries the NEW epoch + served_model. pick()
    # must surface both (it already returns the row; epoch is now in the SELECT/COLS),
    # so a consumer claims/stamps against what pick reported — never a stale view.
    conn = RecordingConn([_row(model="mistral-new", epoch=7)])
    out = pick_slot.pick(conn)
    sql, _ = conn.calls[0]
    assert "epoch" in sql                       # epoch is in the PICK SELECT
    assert out[0]["epoch"] == 7                  # surfaced verbatim from the row
    assert out[0]["served_model"] == "mistral-new"
