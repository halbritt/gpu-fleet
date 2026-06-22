# FALSIFIER - RFC 0001 build plan challenge

author: falsifier-openai-codex-gpt-5.5-001

## Claim challenged

The build plan's Claim C7 says the Slice D renewal design "does not introduce a
correctness-path background process." The plan proposes "a single bounded daemon
renewer" around `dispatch`, while keeping the `di` subprocess boundary unchanged,
and claims that if the renewer dies, "leases simply expire and each shard's next
claim/renew check fails -> the shard self-aborts exactly like a deadman."

That is not justified by the current `di_fleet.py` execution model. Today
`run_shard` is one blocking `subprocess.run(..., timeout=SHARD_TIMEOUT)` call, and
`dispatch` only observes each shard when its future completes or raises. The
default shard timeout is 1200 seconds. There is no in-flight cancellation,
fencing check, process handle, or lease-loss callback that can stop a running
`node ... di --json` subprocess once the central renewer has failed.

## Refuting counterexample

The downstream implementation can satisfy the plan's high-level shape and still
violate exclusive leasing:

1. Slice D claims a slot, starts the shard via the existing `subprocess.run`
   boundary, and relies on the single central renewer to keep the lease alive.
2. The renewer thread stalls, loses its DB connection, or is stopped by a bug
   while the shard subprocess is still healthy and decoding.
3. After 45 seconds, Postgres expires the lease. Another consumer can now claim
   the same capacity-1 slot, correctly according to the database.
4. The original `di --json` subprocess continues using that same GPU until it
   exits or hits `SHARD_TIMEOUT`.

At that point the database shows one live lease, but the physical GPU has two
consumers. This is the exact collision RFC 0001 is trying to eliminate. The
failure is not hypothetical: it follows from the plan's own refinement away from
the RFC's "piggybacked on the shard loop" wording plus the current blocking
subprocess implementation.

## Why the proposed tests would miss it

C7's proposed hermetic test asserts only that renew is called while a slow fake
`shard_fn` runs and that release happens once. A fake `shard_fn` does not prove
that lease loss kills or aborts a real in-flight subprocess. The DB-backed gates
prove SQL expiry and fencing, but not that `di_fleet.py` stops touching the GPU
after its lease is lost. The default `python3 -m pytest tests/ -q` can therefore
stay green while the build still permits a post-expiry double user on live
hardware.

## Required gap to close

The plan needs an explicit in-flight abort mechanism before C7 is acceptable:

- either replace blocking `subprocess.run` with `subprocess.Popen` plus a lease
  monitor that terminates the child immediately when renew returns false or the
  renewer dies;
- or move renewal and cancellation into each shard worker so the worker owns the
  child process and can fence it on lease loss;
- or provide an equally concrete proof that a running `di` subprocess cannot
  continue after the database lease is lost.

It also needs a falsifying test that does not touch live infra: start a long
running fake child process under a disposable lease, force renewal failure or
renewer death, wait for the lease to become reclaimable, and assert the original
child has been terminated before any second claim can run concurrently. Without
that, the plan's renewal thread is on the correctness path even though the plan
labels it off-path.
