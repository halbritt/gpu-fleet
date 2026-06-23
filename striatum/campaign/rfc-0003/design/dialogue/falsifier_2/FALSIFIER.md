author: falsifier-antigravity-gemini-005

# FALSIFIER - RFC 0003 Build Plan Challenge (Falsifier 2)

This challenge attacks the holder's build plan (`BUILD_PLAN.md`) on four major fronts:
1. **Correctness/Stability flaw of the capability-based fence (transient-failure flap - BC1 blocker)**: A transient network discovery timeout or error causes the heartbeat writer to write the fallback `served_model`, triggering a spurious epoch bump and lease invalidation.
2. **Correctness/Safety flaw of held-lease endpoint-turnover (BC2 gap)**: Because `endpoint_url` is part of the primary key, an endpoint change creates a new row and freezes the old row's epoch, allowing the consumer to renew against the stale endpoint indefinitely.
3. **Independent-Committability Flaw: Broken test schema helper in Slice 3**: The plan omits updates to `tests/test_leases_pg.py`'s hardcoded schema helper, breaking the database-backed test suite under Slice 3.
4. **Operational regression of manual epoch bumps**: The proposal completely ignores `EXCLUDED.epoch` on conflicts, breaking the operator's ability to trigger administrative lease fencing.

---

## 1. Correctness Flaw: Transient Discovery Failure Flaps Epoch (BC1 Blocker)

### Evidence from Source and Plan
- In [heartbeat.py](file:///home/halbritt/git/gpu-fleet/heartbeat.py), if the endpoint's `/models` call encounters a transient network issue, DNS glitch, or temporary timeout, `discover_served_model` catches the error and returns the `fallback` value (which defaults to the node's configured `served_model` or `probe_model`):
  ```python
  def discover_served_model(endpoint: str, fallback: str | None, timeout: float = 6.0) -> str | None:
      ...
      except (urllib.error.URLError, OSError, json.JSONDecodeError, TimeoutError):
          return fallback
  ```
- If the node was successfully online in the prior tick, and auto-discovered a model name that differs from the configured fallback (which is common, e.g. alias vs full model name), the `served_model` in the DB was set to the discovered name (e.g. `'llama-3-8b'`).
- Under the proposed Slice 2 `ON CONFLICT` clause, the slot's `epoch` is incremented if the incoming `EXCLUDED.served_model` differs from the existing value.

### Counterexample/Refutation
1. A node is running with a mismatch between configured `served_model` fallback (e.g., `'fallback-model'`) and auto-discovered model (e.g., `'llama-3'`).
2. **Tick 1 (Success)**: Auto-discovery succeeds. `served_model = 'llama-3'` is written. `epoch` is 0.
3. **Tick 2 (Glitch)**: The node experiences a transient network delay or high-load timeout (e.g., discovery takes >6s). `discover_served_model` returns fallback (`'fallback-model'`). The update compares `'fallback-model'` with `'llama-3'`, detects a change, and increments `epoch` to 1.
4. **Tick 3 (Success)**: Discovery succeeds again. `discover_served_model` returns `'llama-3'`. The update detects a change from `'fallback-model'` back to `'llama-3'`, incrementing `epoch` to 2.
5. In-flight jobs renewing their leases are aborted due to the epoch changing from 0 to 1, then to 2, despite the node serving the same model.

This violates the design gate requirement that only *real* capability changes bump the epoch, and that transient liveness glitches must not cause lease invalidation (re-pick storms). The build plan lacks any mechanism to make discovery sticky or cache the last successfully discovered model.

---

## 2. Correctness/Safety Flaw: Held-Lease Endpoint-Turnover (BC2 Gap)

### Evidence from Source and Plan
- Under the proposed renew predicate (Slice 3), the query is:
  ```sql
  UPDATE gpu_slots SET lease_expires = now() + make_interval(secs => %(ttl)s)
   WHERE lease_id = %(lease_id)s
     AND now() < lease_expires
     AND (lease_epoch IS NULL OR epoch = lease_epoch)
  ```
- The PK of the table is `(node, endpoint_url, slot_id)`.
- The plan states (Open Q1) that `endpoint_url` changes are handled by row-turnover: when `endpoint_url` changes, a new row is inserted, and the old row ages out of `live_slots`.

### Counterexample/Refutation
1. A consumer claims a slot with `(node='peecee', endpoint_url='old-url', slot_id=0)`. `lease_epoch` is stamped to the current epoch of that row.
2. The node reconfigures to use `new-url`. Heartbeat inserts `(node='peecee', endpoint_url='new-url', slot_id=0)` as a new row.
3. The old row `(node='peecee', endpoint_url='old-url', slot_id=0)` is no longer heartbeated, so its `epoch` freezes and never bumps.
4. When the consumer's lease renews, it continues to query the old row `(node='peecee', endpoint_url='old-url', slot_id=0)`. Since the old row's epoch is frozen, `epoch = lease_epoch` remains true. The lease renews successfully, and the consumer continues to route to `old-url` indefinitely.
5. Future picks will not see the old row, but the existing consumer is trapped routing to a stale or dead endpoint, bypassing the epoch fence.

The holder's plan relies on child-process failure to break this loop, but this is an external symptom rather than a database invariant. If the old endpoint remains partially reachable (e.g., returning errors or serving an old model during a rolling restart), the lease continues to renew, violating the fence guarantee.

---

## 3. Independent-Committability Flaw: Broken test schema helper in Slice 3

### Evidence from Source and Plan
- The proposed Slice 3 modifies the `CLAIM` and `RENEW` SQL constants (`LEASE_CLAIM_SQL` and `LEASE_RENEW_SQL`) in `di_fleet.py` to stamp and query `lease_epoch` and `epoch`.
- The real PostgreSQL-backed tests in [tests/test_leases_pg.py](file:///home/halbritt/git/gpu-fleet/tests/test_leases_pg.py) construct a temporary test table using a hardcoded `_DDL` statement:
  ```python
  _DDL = """
  CREATE EXTENSION IF NOT EXISTS pgcrypto;
  DROP TABLE IF EXISTS gpu_slots;
  CREATE TABLE gpu_slots (
      node          TEXT NOT NULL,
      endpoint_url  TEXT NOT NULL,
      slot_id       INT  NOT NULL DEFAULT 0,
      vram_free_mib INT,
      capacity      INT  NOT NULL DEFAULT 1 CHECK (capacity >= 1),
      lease_id      UUID,
      lease_holder  TEXT,
      lease_expires TIMESTAMPTZ,
      alive         BOOLEAN NOT NULL DEFAULT true,
      heartbeat_ts  TIMESTAMPTZ NOT NULL DEFAULT now(),
      PRIMARY KEY (node, endpoint_url, slot_id)
  );
  """
  ```
- The proposed changes for Slice 3 do **not** touch `tests/test_leases_pg.py`.

### Counterexample/Refutation
If Slice 3 is committed without updating `_DDL` in `tests/test_leases_pg.py`, running the test suite with `GPU_FLEET_TEST_DB` enabled will crash. The `UPDATE` query inside `leases.claim(...)` will attempt to write to `lease_epoch = epoch`, raising a database error: `column "lease_epoch" does not exist` (or `column "epoch" does not exist`).
Thus, Slice 3 is not independently committable or test-green without modifying `tests/test_leases_pg.py`.

---

## 4. Operational Regression: Manual Epoch Bumps Are Ignored

### Evidence from Source and Plan
- The registry heartbeat driver (`heartbeat_all.py`) fetches `epoch` from the `fleet_nodes` config table on each tick and passes it to the heartbeat upsert row.
- The `heartbeat.py` CLI supports a `--epoch <int>` argument to seed the epoch value.
- In the proposed Slice 2 `ON CONFLICT` clause, `epoch` is updated purely based on changes to the capability columns:
  ```sql
  epoch = gpu_slots.epoch + CASE
      WHEN gpu_slots.served_model  IS DISTINCT FROM EXCLUDED.served_model
        OR gpu_slots.nvlink_domain IS DISTINCT FROM EXCLUDED.nvlink_domain
        OR gpu_slots.max_context   IS DISTINCT FROM EXCLUDED.max_context
      THEN 1 ELSE 0 END
  ```

### Counterexample/Refutation
An operator wants to force-fence the entire fleet or a specific slot to reject stale routing manually (e.g., after an administrative override). They perform `UPDATE fleet_nodes SET epoch = epoch + 1;` or run `heartbeat.py` with an elevated `--epoch` argument.
However, because the `ON CONFLICT` update clause completely ignores `EXCLUDED.epoch` (which contains the new value), the database's `gpu_slots.epoch` remains unchanged. The manual administrative fence has zero effect, representing a regression in operator capability.

To fix this, the update clause must allow `EXCLUDED.epoch` to override the server-side value if it is explicitly bumped higher, for example:
```sql
epoch = GREATEST(gpu_slots.epoch, EXCLUDED.epoch) + CASE
    WHEN gpu_slots.served_model   IS DISTINCT FROM EXCLUDED.served_model
      OR gpu_slots.max_context    IS DISTINCT FROM EXCLUDED.max_context
      OR gpu_slots.nvlink_domain  IS DISTINCT FROM EXCLUDED.nvlink_domain
    THEN 1
    ELSE 0
END
```

---

## Refutation Tests the Plan is Missing

1. **Test transient discovery timeout immunity**:
   Seed a slot with discovered model `A` and fallback `B`. Simulate a transient discovery timeout (which writes `B` and sets `alive = False`), followed by a successful probe (which writes `A` and sets `alive = True`). Assert that `epoch` did not increment and active leases survived the temporary offline flap.
2. **Test endpoint-turnover lease fencing**:
   Seed a slot with endpoint `old`, claim it to stamp `lease_epoch`. Simulate heartbeat moving the same `(node, slot_id)` to endpoint `new` (a new row). Advance time past the `live_slots` freshness window but before `lease_expires`. Assert that renew on the old lease returns zero rows.
3. **Test pg_leases_test independent-committability**:
   Add an assertion in a build validation script that verifying psycopg tests in `tests/test_leases_pg.py` can execute without schema failures in Slice 3.
4. **Test manual epoch propagation**:
   Perform an upsert with an incoming `epoch = 5`. Re-upsert with `epoch = 10` but no capability change. Assert that `epoch` is updated to 10 in the DB.
