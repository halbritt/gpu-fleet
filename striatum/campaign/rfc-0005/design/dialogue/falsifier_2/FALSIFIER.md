# FALSIFIER - RFC 0005 build plan challenge (Attempt 3)

author: falsifier-antigravity-gemini-003

## Challenge 1: KeyError/TypeMismatch in `heartbeat_all.py` on Column Updates (Refutes C8)

### Claim challenged
The plan claims under **C8** that *"One UPSERT edit covers both writers"* because `heartbeat_all.py` imports `UPSERT` from `heartbeat.py` at line 24.

### Counterexample
While it is true that `heartbeat_all.py` imports `UPSERT`, it defines its own functions to construct the record dictionary representing the row to be upserted: `probe_node(n: dict) -> dict` (lines 90–130) and `_failed_row(n: dict, exc: Exception) -> dict` (lines 133–148). 
When Slice 2 modifies `UPSERT` in `heartbeat.py` to include the slow capability columns `mig_mode` and `ecc_mode` (e.g. `%(mig_mode)s`, `%(ecc_mode)s`), any dictionary passed to `conn.execute(UPSERT, row)` must contain these keys. 
Since `heartbeat_all.py`'s functions do not return these keys, when the global puller executes `pull_write` (line 219: `conn.execute(UPSERT, row)`), it will crash with a KeyError (or psycopg parameter binding mismatch). This will crash the global puller's heartbeat loop on the next tick, violating the fault-isolation guarantee.

---

## Challenge 2: Non-updatable `FOR UPDATE` on join view `capacity_slots` (Refutes C1/C7)

### Claim challenged
The plan claims under **C1** and **C7** that the view and reader swap are backward-compatible and behavior-neutral, and that `pick` will query the new `capacity_slots` view (which LEFT JOINs `gpu_slots` to `gpu_slots_capacity` and `capacity_policy`) and continue using `FOR UPDATE SKIP LOCKED` to lock rows.

### Counterexample
In PostgreSQL, a view containing a `LEFT JOIN` is not automatically updatable. Attempting to execute `FOR UPDATE` on such a join view will result in a database error:
`ERROR: cannot lock rows in view "capacity_slots"`
To lock rows when querying a view with joins, one must specify `FOR UPDATE OF gpu_slots` to target the base table explicitly. Querying `capacity_slots` directly with `FOR UPDATE` will cause the picker (`pick_slot.py`) to crash immediately upon deployment.

---

## Challenge 3: Decay logic flaw in OQ-C (Conceptual & Correctness)

### Claim challenged
The plan claims under **OQ-C** that freshness is judged relative to the slot's own `heartbeat_ts` (and written `heartbeat_ts` column), not wall-clock `now()`, to avoid clock-skew issues.

### Counterexample
Both `heartbeat_ts` and `fast_source_ts` are database columns written by the heartbeat process in the same tick. When a node stops heartbeating (e.g. because the node goes offline), both timestamps remain frozen in the database.
If the view only compares `fast_source_ts` to `heartbeat_ts`, their difference will remain fixed (close to 0) forever. The view will never observe that wall-clock time has advanced, and a stale slot will never decay to `stale` or `unknown` in the view, rendering the decay logic ineffective for offline nodes.

---

## Challenge 4: ZeroDivisionError and Stateless Baseline Capturing in `heartbeat.py`

### Claim challenged
The plan claims under Slice 1 that the baseline `cold_probe_ms` is captured at registration (first passing probe) and subsequent ticks compute `live_slowdown_factor = probe_ms / cold_probe_ms`.

### Counterexample
- **ZeroDivisionError:** If a probe is very fast or mock tests report `probe_ms` as 0, `cold_probe_ms` will be captured as 0. This results in a `ZeroDivisionError` in Python on subsequent ticks, crashing the heartbeat loop.
- **Stateless baseline capturing:** The `heartbeat_once` function is stateless across restarts. To avoid capturing a baseline while the card is already hot (under load), it must query the existing baseline from the database. The plan does not specify any database SELECT query to initialize `cold_probe_ms` upon process startup.

---

## Challenge 5: Missing `kv_bytes` SQL Function & Call Threading in `di_fleet` (Refutes C7)

### Claim challenged
The plan claims under **C7** that Slice 3 makes `di_fleet` route on probe-anchored headroom using:
`AND COALESCE(c.effective_free_mib, gpu_slots.vram_free_mib) >= %(model_mib)s + kv_bytes(%(max_context)s)`

### Counterexample
- **No SQL Function:** `kv_bytes` is a SQL function call in the query. However, Migration `010` (Slice 0) does not define any `kv_bytes` SQL function. Executing the claim query will fail with `UndefinedFunction: function kv_bytes(...) does not exist`.
- **No Parameter Threading:** The production `di_fleet` caller chain (`main` -> `leased_shard` -> `run_leased_shard` -> `claim`) never parses or passes `model_mib` or `max_context` from the command-line arguments. In production, they will always default to 0/None, rendering the headroom check completely useless.

---

## Challenge 6: Contradiction/Gap in per-PID Phantom on Pull-Only peecee

### Claim challenged
The plan claims under Slice 2 (Change C) that unrecognized-PID VRAM will be treated as a phantom occupant, but states that "Only the node that physically owns the card writes its phantom" to avoid a SPOF.

### Counterexample
- Peecee is a pull-only slot (the global puller probes it).
- The puller is not the card-owning node (it runs on another host).
- Since peecee is pull-only and does not run its own local heartbeat process, and since the puller runs on a separate host and cannot access peecee's local per-PID VRAM stats (as the `gpu_cmd` command `nvidia-smi` only queries global GPU stats), the phantom VRAM for peecee can never be measured or written.
- This directly contradicts the core goal of detecting the co-tenant (marker) on peecee.
