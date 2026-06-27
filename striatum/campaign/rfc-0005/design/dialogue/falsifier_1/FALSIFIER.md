# FALSIFIER - RFC 0005 build plan challenge

author: falsifier-openai-codex-gpt-5.5-003

## Challenge: Slice 3 has no production source for request-specific KV headroom

### Claim challenged

The holder plan claims the reader slice will replace flat VRAM routing with request-aware headroom:

- `pick_slot` falls back to today's `vram_free_mib` when the companion is absent or stale.
- `di_fleet.LEASE_CLAIM_SQL` changes from `vram_free_mib >= %(model_mib)s` to `COALESCE(c.effective_free_mib, gpu_slots.vram_free_mib) >= %(model_mib)s + kv_bytes(%(max_context)s)`.
- This is supposed to make a 32k-context request and a 4k-context request see different routable slots, while preserving the `di --json` subprocess boundary.

That is the RFC's core reader-side correctness claim: capacity is not just "some richer number"; it is headroom for the actual request.

### Counterexample from the plan and live code

The plan never defines a production source for `max_context`, `kv_bytes`, or the model footprint at the point where `di_fleet` claims a lease.

In the live code, `di_fleet` deliberately treats the Node CLI as opaque. `_split_argv` only consumes `--frames`, `--top`, `--json`, and `-k/--slots`; everything else, including `--context`, `--concurrency`, problem text, and `--model`, is passed through verbatim to the `di --json` child. `main()` then calls `route_slots(k, db=db)` with no model size, no requested context, and no minimum VRAM. The production `leased_shard` closure calls `run_leased_shard(..., holder=holder, conn_factory=conn_factory)` without `model_mib` or any `max_context` argument, so the existing claim path uses its default `model_mib=0` all the way down to `claim()`.

The build plan says `claim()` will gain a defaulted `max_context` kwarg, but it does not say where the non-default value comes from. Passing `--context 32768` through to Node does not feed the SQL predicate. Parsing the Node CLI's full configuration, prompt, tokenization, or model context inside `gpu-fleet` would be a new cross-boundary contract and risks violating the plan's own "di-fleet consumers shell out to `di --json` and never import the Node engine" boundary. Leaving the kwarg defaulted makes `kv_bytes(NULL/0) == 0`, which preserves byte-equivalence only by failing the RFC claim: 32k and 4k requests route identically.

There is a second concrete compile-time version of the same gap. Slice 0 enumerates the entire migration surface: a companion table, policy table, capacity view, and `mig_mode`/`ecc_mode` columns. It does not create a `kv_bytes(...)` SQL function, a model-footprint table, or any deterministic policy row that maps `(model, max_context)` to bytes. The repository currently has no `kv_bytes` symbol. If Slice 3 literally implements the planned SQL, `LEASE_CLAIM_SQL` will fail in Postgres with an undefined function unless the build silently widens the migration beyond the plan.

### Why the planned tests would not catch it

The test map proves useful primitives, but not the production reader contract:

- gate test F proves a helper can compute `effective_free = LEAST(floor, exporter)`;
- gate test G proves an over-reporting exporter can be rejected by `pick` or claim;
- the hermetic-default guarantee says `kv_bytes(NULL/0)` is 0 and existing tests stay green;
- no test drives `di_fleet.main()` or the production `leased_shard` closure with a large context flag and asserts the claim receives that context;
- no test asserts the real `LEASE_CLAIM_SQL` compiles after applying only the stated migration `010`;
- no test constructs two otherwise-identical slots where one can serve 4k but not 32k and proves the production `di-fleet` path chooses differently.

A build can therefore pass every listed test while the user-facing `di-fleet --context 32768 ...` path still claims with `model_mib=0` and default context. That would satisfy backward compatibility by not changing behavior, but it would not satisfy RFC 0005's headroom routing gate.

### Required plan fix

Slice 3 needs an explicit request-headroom contract before it is buildable:

- Define a gpu-fleet-owned input for request context and model footprint, or explicitly state that request-specific KV headroom is deferred and this build only routes on slot-level capacity.
- If the value is supplied by CLI flags, update `_split_argv`, `route_slots`, `run_leased_shard`, `run_failover_shard`, `failover_transfer`, and `claim` so `max_context` and model footprint reach every first-attempt and failover claim without importing or parsing the Node engine internals.
- If `kv_bytes` is SQL-level, migration `010` must create the function/table it depends on, and `test_capacity_pg.py` must compile and execute the real claim SQL after applying the real migrations.
- Add a hermetic test that `di_fleet.main([... "--context", "32768" ...])` threads the value into the fake lease claim, and a PG test where 4k and 32k requests produce different claim outcomes against the same companion capacity row.

Until that contract is specified and tested, claims C4, C6, and C7 are not falsifiably covered: the plan can either break at SQL execution time or silently preserve today's context-blind routing while claiming to have shipped request-aware headroom.
