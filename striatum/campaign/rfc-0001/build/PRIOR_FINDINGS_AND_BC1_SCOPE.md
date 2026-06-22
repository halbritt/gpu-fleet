# RFC 0001 build — prior verifier finding + operator BC1 scope (READ THIS FIRST)

A prior build attempt (`run_0702a0d1…`, canceled) was correctly rejected by the
independent verifier (codex gpt-5.5) on **BC1**. This document carries that finding
forward and records the operator's **achievable, testable scope** for BC1 so this
build can discharge it honestly. Read it together with `COMMITTED_PLAN.md`; where
this doc refines BC1's wording, **this doc wins**.

## What the prior verifier found (valid, unrebutted)

1. **The BC1 mechanism only polled.** The per-shard renew monitor woke every renew
   interval (~15s) and detected lease loss only on its next wake. A second consumer
   can claim the instant the DB lease expires (`LEASE_CLAIM_SQL` only requires
   `lease_id IS NULL OR now() >= lease_expires`) and launch its own child — so a
   physical GPU overlap window remained.
2. **The BC1 test cheated.** The modeled second consumer voluntarily spun on a
   synthetic `gpu_busy` flag (which has **no counterpart** in the production
   `claim`/`dispatch`/`run_shard` path) before "using" the GPU, so the test only
   proved "if the successor politely waits, it won't overlap" — not the real
   guarantee. A test must never manufacture the happens-before it claims to verify.

Everything else verified clean (migration additive & correctly numbered, BC2/BC3/BC4
discharged, `di --json` boundary intact, no live infra touched, hermetic suite green).
**Keep all of that.** Only BC1's mechanism and test need to be done right.

## Operator scope for BC1 (the achievable, testable guarantee — supersedes the literal wording)

The literal BC1 phrasing ("terminate the child before **any** second consumer can use
the GPU") is **not fully achievable client-side** given the RFC's autonomous-deadman
design: deadman recovery *requires* that a second consumer can claim on lease expiry
(a frozen consumer can't release), so a frozen consumer's child can physically outlive
its lease until something reaps it. The RFC itself accepts this at the lease layer
(its failure table: a "frozen-but-TCP-alive consumer" is "reaped by autonomous
expiry"). BC1 is therefore scoped into three parts the build MUST satisfy:

- **BC1-A (responsive abort — REQUIRED, code).** When a renew returns zero rows
  (lease lost: expiry, zombie re-claim, or epoch change), the owning consumer MUST
  terminate its `di --json` child **synchronously, in the same control path that
  observes the lost renew** — not merely on a later independent poll. Renew at TTL/3
  so a healthy consumer that loses its lease kills its child within one renew interval,
  well inside the TTL margin before the slot becomes claimable by others in the
  expiry case. Operate on the `Popen` handle (`terminate()`/`kill()`); never import
  the Node engine.
- **BC1-test (honest falsifier — REQUIRED, no-live-infra).** The BC1 test MUST drive
  the **production** path: the abort is triggered by a real lease-loss event (a
  fake/clock-advanced `conn` that makes `renew` return zero rows, or a real
  re-`claim`), and the second consumer claims via the real `claim`/`LEASE_CLAIM_SQL`
  seam — **no test-only `gpu_busy`/sleep handshake** that production doesn't have.
  Assert that the predecessor child is terminated *as a consequence of* the lost
  renew. State the timing honestly; do not assert a happens-before the code does not
  enforce.
- **BC1-residual (documented & accepted — REQUIRED, prose).** A *fully frozen*
  consumer (its renew loop itself stalled) or a zombie-reclaim race can physically
  overlap on the GPU until the OS/monitor reaps, bounded by the renew interval / TTL.
  This is the **irreducible client-side deadman residual the RFC already accepts.**
  The hard guarantee against frozen-consumer overlap needs a server-side / OS-level
  fence (a GPU cgroup kill, or a claim handshake that waits for the predecessor's
  confirmed termination) — **explicitly OUT OF SCOPE for v1**, recorded as the
  follow-up. The final report MUST state this residual plainly and MUST NOT claim the
  build eliminates all physical overlap.

**Acceptance for this build:** the verifier confirms BC1-A is implemented in the
production path, the BC1 test is honest (no synthetic wait) and green, and the
residual is documented. The DB-only two-transaction concurrency test remains
necessary but not sufficient — BC1-A's test is the one that gates accept.
