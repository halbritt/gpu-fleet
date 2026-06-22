# FALSIFIER - RFC 0001 build plan challenge

author: falsifier-openai-codex-gpt-5.5-002

## Claim challenged

C7 says Slice D's single bounded daemon renewer is off the correctness path: it renews active leases around `dispatch`, and if it dies, leases expire and shards "self-abort on the next failed renew" just like the deadman path. Slice D also commits to preserving the `di` subprocess boundary: `run_shard` remains a blocking `di --json` subprocess, and lease work lives around that subprocess in Python.

Those two claims do not compose. In the current execution model, a running shard has no in-flight lease check. `run_shard` is one blocking `subprocess.run(..., timeout=SHARD_TIMEOUT)` call, and `dispatch` only sees the shard again after the future completes or raises. The proposed central renewer is the only actor that can observe renew failure while the child is still running. If that renewer dies, there is no "next failed renew" inside the shard worker and no process handle to terminate.

## Refuting counterexample

A downstream build can follow the plan literally and still violate RFC 0001's physical exclusivity goal:

1. Slice D claims a capacity-1 slot, starts a shard via the preserved blocking `node ... di --json` subprocess, and registers that lease with the single renewer.
2. The renewer thread stalls, loses its DB connection, or exits while the shard subprocess is healthy and decoding.
3. After the 45 second TTL, Postgres expires the lease. A second consumer can now claim the same slot correctly according to the database.
4. The original `di --json` child keeps using the GPU until it exits or reaches the existing shard timeout.

The database invariant now says exactly one lease is live, but the hardware has two consumers. That is the live-infra collision the RFC is meant to eliminate. The failure is caused by the plan's engineering refinement, not by the settled RFC design: the RFC's "piggybacked on the shard loop" wording would put the renew/abort observation in the worker that owns the child, while the plan moves renewal into a separate background actor and simultaneously preserves the blocking subprocess boundary.

## Why the proposed tests would miss it

C7's support test uses injected `lease_ops` plus a slow fake `shard_fn` and asserts renew is called several times and release happens once. That proves the happy-path renewer loop can run beside a fake function; it does not prove a real in-flight child is killed when renewal stops.

The DB-backed tests prove SQL expiry, zombie fencing, and transaction atomicity. They also do not prove that `di_fleet.py` stops touching the GPU after its lease is lost. The default hermetic gate can therefore pass while the implementation still allows a post-expiry double user on live hardware.

## Required gap to close

The plan needs an explicit in-flight abort mechanism before C7 is acceptable:

- replace blocking `subprocess.run` with `subprocess.Popen` plus a lease monitor that terminates the child immediately when renew fails or the renewer dies;
- or move renewal and cancellation into each shard worker so the worker that owns the child also owns the fence decision;
- or provide an equivalent concrete mechanism proving a running `di --json` child cannot continue after its database lease is lost.

It also needs a falsifying test that stays off live infra: run a long-lived fake child under a disposable lease, force renewal failure or renewer death, wait until the lease is reclaimable, and assert the original child has been terminated before another claimant can run concurrently. Without that, the renewer is on the correctness path even though the plan labels it off-path.