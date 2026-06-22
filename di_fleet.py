#!/usr/bin/env python3
"""di-fleet: fan a divergent-ideation run's K branches across N live fleet slots.

`di` (divergent-ideation) already runs its divergence branches concurrently, but
against a single `-np 1` llama-server those POSTs serialize in one queue, so the
wall-clock is N_branches * decode, not parallel. The fleet has *several* live LLM
slots; this tool shards di's `--frames F` across them and runs ONE `di` subprocess
per slot (each pinned to its own endpoint via per-process env), so the F branches
truly run in parallel and wall-clock drops ~linearly with the number of slots.

Three load-bearing guarantees, mirrored from the registry's own discipline:

  * Linear speedup  — F frames are split into N balanced integer shards summing to
    F (round-robin), each shard is one `di` process, all N run concurrently.
  * No branch lost  — if a shard's `di` dies mid-run (non-zero exit / timeout /
    unparseable JSON = its slot died), its frames are reassigned to a surviving
    endpoint and retried ONCE. A shard's frames are abandoned only if NO endpoint
    can serve them, and that is said explicitly on stderr.
  * Exclusive use  — RFC 0001: each shard CLAIMS its slot's lease before running
    and RELEASES it on completion, so two consumers never fight over one GPU. A
    per-shard renew loop OWNS the `di --json` child handle; when a renew returns
    zero rows (lease lost: expiry, zombie re-claim, or epoch change) it terminates
    that child SYNCHRONOUSLY, in the same control path that observed the loss
    (BC1-A) — it does not wait for a later independent poll. See run_leased_shard
    for the abort mechanism and its documented irreducible residual. When a shard
    dies while still holding its lease, failover is an ATOMIC transfer (BC4): the
    dead lease is released AND a survivor claimed in ONE Postgres transaction
    (run_failover_shard -> failover_transfer), so the freed capacity never hits the
    open pool between the two ops and the dead lease is never released before the
    replacement claim is secured.

The boundary to `di` is a subprocess (RFC 0078/0087): we NEVER import the Node
engine — the lease monitor aborts by acting on the `Popen` HANDLE
(terminate()/kill()), never by reaching into the engine. The "run one shard" call,
the lease ops (`lease_ops`), and the child launcher (`child_factory`) are all
injectable, exactly like `probe_fn` in heartbeat_all, so sharding / concurrency /
failover / lease lifecycle / in-flight abort are unit-testable with fakes and zero
real subprocess, DB, or HTTP.
"""

from __future__ import annotations

import argparse
import json
import os
import socket
import subprocess
import sys
import tempfile
import time
from concurrent.futures import ThreadPoolExecutor, as_completed

DI_CLI = os.environ.get(
    "DI_CLI", "/home/halbritt/git/divergent-ideation/dist/cli.js"
)
# Per-shard di subprocess budget. di's own LLM timeout is 180s and it makes
# several round-trips per branch, so a shard with a handful of frames can take a
# while; this just stops a black-hole slot from hanging the whole run forever.
SHARD_TIMEOUT = float(os.environ.get("DI_FLEET_SHARD_TIMEOUT", "1200"))


# =========================================================================== #
# RFC 0001 — slot-lease lifecycle (claim / renew / release / failover transfer).
#
# A slot is held by exactly ONE consumer for a bounded, self-renewing TTL. Three
# load-bearing properties, all enforced by Postgres, never by a Python clock:
#   * Exclusivity is the conditional WHERE of CLAIM, not a row lock — a second
#     consumer's CLAIM on a held slot matches zero rows.
#   * Expiry is autonomous wall-clock (`lease_expires = now() + ttl`), evaluated
#     server-side, so a frozen consumer is reaped by a clock it cannot stall. No
#     reaper job exists.
#   * Fencing is identity (`lease_id` UUID) — a zombie's RENEW `WHERE lease_id =
#     $old` matches zero rows after the slot is re-claimed under a new id.
#
# Every function takes an injected `conn` (psycopg-style: conn.execute(sql, params)
# -> cursor with .fetchone()). These functions read NO Python clock for any expiry
# or fence decision, so clock skew is structurally impossible (the renew LOOP's
# sleep cadence in run_leased_shard may use a Python clock — that is a poll
# interval, not a predicate). Conceptually a standalone module; kept here in
# di_fleet (its only consumer) because the build's write scope admits di_fleet.py
# but not a new top-level leases.py — see CLAIM_LEDGER.
# =========================================================================== #

# TTL aligned with the heartbeat TTL (gpu_slots live window is 45s) so the two
# timers fold into one liveness fact; renew at TTL/3 so two missed renewals still
# leave margin before expiry.
TTL_SECONDS = 45
RENEW_SECONDS = 15  # TTL/3

# CLAIM — atomic conditional UPDATE. Inherits #2's load-aware liveness (alive +
# fresh heartbeat + vram_free) as a precondition, so a lease is never offered on a
# dead node or a marker-owned (load-starved) GPU.
LEASE_CLAIM_SQL = """
UPDATE gpu_slots
   SET lease_id      = gen_random_uuid(),
       lease_holder  = %(holder)s,
       lease_expires = now() + make_interval(secs => %(ttl)s)
 WHERE (node, endpoint_url, slot_id) = (%(node)s, %(endpoint_url)s, %(slot_id)s)
   AND alive
   AND heartbeat_ts > now() - interval '45 seconds'
   AND vram_free_mib >= %(model_mib)s
   AND (lease_id IS NULL OR now() >= lease_expires)
RETURNING lease_id
"""

# RENEW — every TTL/3. Zero rows = "lease lost (expired or re-claimed) — stop
# touching the GPU immediately." The now() < lease_expires guard means a lapsed
# lease cannot be silently resurrected by its old holder.
LEASE_RENEW_SQL = """
UPDATE gpu_slots
   SET lease_expires = now() + make_interval(secs => %(ttl)s)
 WHERE lease_id = %(lease_id)s
   AND now() < lease_expires
RETURNING lease_id
"""

# RELEASE — fenced on lease_id, so releasing a lease we no longer hold (a successor
# already re-claimed) matches zero rows and never clobbers the successor.
LEASE_RELEASE_SQL = """
UPDATE gpu_slots
   SET lease_id = NULL, lease_holder = NULL, lease_expires = NULL
 WHERE lease_id = %(lease_id)s
"""


def claim(conn, slot, holder, *, ttl_seconds=TTL_SECONDS, model_mib=0):
    """Atomically claim `slot` for `holder` for `ttl_seconds`. Returns the new
    lease_id, or None if the slot was not claimable (held, stale, load-starved, or
    gone). `slot` is a dict carrying at least node / endpoint_url / slot_id."""
    row = conn.execute(
        LEASE_CLAIM_SQL,
        {
            "holder": holder,
            "ttl": ttl_seconds,
            "node": slot["node"],
            "endpoint_url": slot["endpoint_url"],
            "slot_id": slot.get("slot_id", 0),
            "model_mib": model_mib or 0,
        },
    ).fetchone()
    return row[0] if row else None


def renew(conn, lease_id, *, ttl_seconds=TTL_SECONDS):
    """Extend a held lease's expiry. Returns True if the lease is still ours and
    live, False if it was lost (expired or re-claimed) — caller MUST stop using the
    GPU on False."""
    row = conn.execute(
        LEASE_RENEW_SQL, {"lease_id": lease_id, "ttl": ttl_seconds}
    ).fetchone()
    return row is not None


def release(conn, lease_id):
    """Free a slot we hold. Fenced on lease_id (a no-op if a successor already
    re-claimed). Idempotent."""
    conn.execute(LEASE_RELEASE_SQL, {"lease_id": lease_id})


def failover_transfer(conn, dead_lease_id, candidate_slots, holder,
                      *, ttl_seconds=TTL_SECONDS, model_mib=0):
    """RFC 0001 failover = atomic transfer, not return-to-pool.

    In ONE transaction (the caller commits/rolls back), RELEASE the dead shard's
    lease and CLAIM the first claimable candidate. Returns {"slot", "lease_id"} for
    the survivor, or None if no candidate was claimable.

      * Survivor path — freed capacity is handed directly to the re-pinned shard and
        never hits the open pool, so failover can't spawn its own thundering herd.
      * No-survivor path — the dead lease is STILL released (released first,
        unconditionally), so the slot frees IMMEDIATELY rather than waiting up to the
        TTL; the caller then degrades (frames abandoned). BC4.

    Atomicity (release + claim commit-or-rollback together) is the caller's
    transaction: pass a non-autocommit conn and commit once on a non-None result."""
    release(conn, dead_lease_id)
    for slot in candidate_slots:
        lease_id = claim(conn, slot, holder,
                         ttl_seconds=ttl_seconds, model_mib=model_mib)
        if lease_id is not None:
            return {"slot": slot, "lease_id": lease_id}
    return None


class _Leases:
    """Default `lease_ops` for run_leased_shard: this module's real claim / renew /
    release / failover_transfer. Tests inject a fake with the same surface."""

    claim = staticmethod(claim)
    renew = staticmethod(renew)
    release = staticmethod(release)
    failover_transfer = staticmethod(failover_transfer)


leases = _Leases()


# --------------------------------------------------------------------------- #
# Routing: which live http LLM slots to spread across.
# --------------------------------------------------------------------------- #
def route_slots(k, db="dbname=gpu_fleet", latency_class=None, pick_fn=None):
    """Up to `k` live http(s) LLM slots, warm-first. di needs an OpenAI-compatible
    HTTP endpoint, never a non-LLM capability (marker's ssh://), so we filter to
    http(s); and we prefer decode-verified WARM slots (real `probe_ms`) over
    cold/loadable ones so di lands on a ready MoE instead of cold-loading 23 GiB.

    latency_class is None (span EVERY live MoE slot) on purpose: the point of the
    fan-out is to use all live MoE capacity, and in this fleet the MoE slots sit in
    DIFFERENT classes (proximal is 'interactive', peecee is 'batch'), so a class
    filter would pin di to one of them and defeat the fan-out. warm-first naturally
    keeps proximal primary; #2's load-aware liveness ages peecee out when marker
    owns its card, so di only fans out to peecee when it can actually serve.

    `pick_slot` returns ALL live capabilities, INCLUDING non-LLM ones (marker's
    ssh:// row), and its SQL LIMIT is applied BEFORE we drop those. A non-LLM row
    can sort AHEAD of a real LLM slot (marker shares peecee's high free-VRAM, which
    outranks proximal's near-full card), so a small `k` LIMIT could come back as
    [marker, one-LLM] and collapse to a single endpoint after filtering — silently
    killing the fan-out. So fetch a generous margin and trim to `k` AFTER filtering.

    `pick_fn(fetch_k) -> rows` is injectable so the routing policy is unit-testable
    without a DB. Any failure to reach the registry degrades to "no slots" (di's own
    default), never an exception."""
    fetch_k = max(k + 8, 16)  # margin so non-LLM rows can't crowd out real LLM slots
    if pick_fn is None:
        def pick_fn(n):
            import pick_slot  # local module; only http(s) rows are LLMs
            import psycopg
            with psycopg.connect(db) as conn:
                return pick_slot.pick(conn, latency_class=latency_class, k=n)
    try:
        picks = pick_fn(fetch_k)
    except Exception as exc:  # no DB, no psycopg, query error -> degrade to di default
        print(f"di-fleet: registry unreachable ({exc}); using di default", file=sys.stderr)
        return []
    return _filter_llm_slots(picks)[:k]


def _is_http(url):
    return isinstance(url, str) and (url.startswith("http://") or url.startswith("https://"))


def _filter_llm_slots(picks):
    """http(s) only, warm slots (probe_ms != null) first, cold ones after."""
    llm = [p for p in picks if _is_http(p.get("endpoint_url"))]
    warm = [p for p in llm if p.get("probe_ms") is not None]
    cold = [p for p in llm if p.get("probe_ms") is None]
    return warm + cold


# --------------------------------------------------------------------------- #
# Sharding: split F frames across N endpoints, balanced, summing to F.
# --------------------------------------------------------------------------- #
def shard_frames(total, n):
    """Round-robin split of `total` frames into `n` balanced integer shards that
    sum to `total`. Each shard differs from any other by at most 1. n is capped at
    total so no endpoint ever gets a 0-frame (pointless) shard; a total of 0 or a
    non-positive n yields no shards."""
    if total <= 0 or n <= 0:
        return []
    n = min(n, total)
    base, extra = divmod(total, n)
    # The first `extra` shards get one more frame than the rest.
    return [base + 1 if i < extra else base for i in range(n)]


# --------------------------------------------------------------------------- #
# Running one shard: the injectable boundary to `di`, under a slot lease.
# --------------------------------------------------------------------------- #
class LeaseLost(RuntimeError):
    """The slot lease was lost (could not be claimed, expired, or was re-claimed by
    a successor). The owning shard's `di --json` child has been aborted; `dispatch`
    treats this like any other dead shard and fails its frames over to a survivor.
    There is NO lease left to hand off (it was never held, or a successor holds it
    now), so the dead-lease release is a fenced no-op done inline."""


class ShardDied(RuntimeError):
    """The `di --json` child died mid-run (non-zero exit, unparseable JSON, or
    timeout) while THIS consumer still holds the slot lease. Unlike LeaseLost the
    lease is still ours, so run_leased_shard does NOT release it inline — it surfaces
    the held lease (`.lease_id`) so `dispatch` disposes of it through the RFC 0001
    failover TRANSFER: release this dead lease AND claim a survivor in ONE Postgres
    transaction (BC4), so the freed capacity never hits the open pool between the two
    operations and the dead lease is never released before the replacement claim is
    secured."""

    def __init__(self, message, *, lease_id):
        super().__init__(message)
        self.lease_id = lease_id


class _DiChild:
    """Thin wrapper over a real `di --json` Popen so the renew monitor can poll /
    wait / terminate / kill it and read its output WITHOUT a pipe-buffer deadlock:
    stdout/stderr are redirected to temp files, so a chatty child never blocks while
    the monitor sleeps between renews."""

    def __init__(self, proc, out_file, err_file):
        self._proc = proc
        self._out = out_file
        self._err = err_file

    def poll(self):
        return self._proc.poll()

    def wait(self, timeout=None):
        return self._proc.wait(timeout=timeout)

    def terminate(self):
        self._proc.terminate()

    def kill(self):
        self._proc.kill()

    @property
    def returncode(self):
        return self._proc.returncode

    def read_stdout(self):
        self._out.seek(0)
        return self._out.read().decode("utf-8", "replace")

    def read_stderr(self):
        self._err.seek(0)
        return self._err.read().decode("utf-8", "replace")


def _popen_child(slot, frames, flags):
    """Launch ONE `di --json` subprocess for `frames` branches against `slot`, pinned
    via per-process env, and return a handle the renew monitor owns. This is the only
    place a real di runs and the ONLY thing the lease abort touches — we act on the
    process HANDLE (terminate/kill), never importing the Node engine (RFC 0078/0087).
    Tests inject a fake `child_factory` in its stead."""
    env = dict(os.environ)
    env["DIVERGENT_LLM_BASE_URL"] = slot["endpoint_url"]
    if slot.get("served_model"):
        env["DIVERGENT_LLM_MODEL"] = slot["served_model"]
    cmd = ["node", DI_CLI, *flags, "--frames", str(frames), "--json", "--quiet"]
    out, err = tempfile.TemporaryFile(), tempfile.TemporaryFile()
    proc = subprocess.Popen(cmd, env=env, stdout=out, stderr=err)
    return _DiChild(proc, out, err)


def _collect_child_result(child, slot):
    """Parse a finished child's RunResult. Raises on non-zero exit or unparseable
    JSON — i.e. "this slot died mid-run" — the signal `dispatch` uses for failover."""
    rc = child.poll()
    if rc != 0:
        raise RuntimeError(
            f"di shard exit {rc} on {slot.get('endpoint_url')}: "
            f"{child.read_stderr().strip()[:400]}"
        )
    out = child.read_stdout()
    try:
        return json.loads(out)
    except (json.JSONDecodeError, ValueError) as exc:
        raise RuntimeError(
            f"di shard on {slot.get('endpoint_url')} emitted unparseable JSON: {exc}"
        )


def _terminate(child, *, grace=5):
    """Stop a child: ask politely (terminate), then kill if it won't go."""
    child.terminate()
    try:
        child.wait(timeout=grace)
    except Exception:
        child.kill()


def _monitor(conn, slot, child, lease_id, *, lease_ops, ttl_seconds, renew_seconds,
             timeout, sleep, clock):
    """Run the per-shard renew monitor over an ALREADY-CLAIMED `lease_id` and the
    `child` it owns. Returns the parsed RunResult on clean completion; raises
    LeaseLost if a renew returns zero rows (lease lost mid-run), or ShardDied if the
    child itself died (non-zero exit, unparseable JSON, or timeout) while we still
    hold the lease. Reads NO Python clock for any lease predicate (the loop's sleep
    cadence is a poll interval, not a fence).

    BC1-A (responsive abort, the gated guarantee): the renew check and the child
    KILL live in the SAME control path. When a renew returns zero rows — the lease
    was lost to expiry, a zombie re-claim, or an epoch change — this loop terminates
    the child SYNCHRONOUSLY right here, not on a later independent poll. Renewing at
    TTL/3 means a healthy consumer that loses its lease kills its `di --json` child
    within one renew interval, well inside the TTL margin.

    BC1-residual (irreducible, documented, accepted for v1): this is a client-side
    deadman. A FULLY frozen consumer (its renew loop itself stalled) or a zombie-
    reclaim race can let a child physically outlive its lease until the OS / monitor
    reaps it, bounded by the renew interval / TTL — exactly the case the RFC's own
    failure table accepts ("frozen-but-TCP-alive consumer ... reaped by autonomous
    expiry"). Eliminating ALL overlap needs a server-side / OS-level fence (a GPU
    cgroup kill, or a claim handshake that waits for the predecessor's confirmed
    termination); that is OUT OF SCOPE for v1. This code does NOT claim to terminate
    the child before any second consumer can claim — only to abort promptly once the
    loss is observed."""
    start = clock()
    while child.poll() is None:
        if clock() - start >= timeout:
            child.kill()
            raise ShardDied(
                f"di shard timed out after {timeout}s on {slot.get('endpoint_url')}",
                lease_id=lease_id)
        sleep(renew_seconds)
        if child.poll() is not None:
            break  # child finished during the renew interval
        if not lease_ops.renew(conn, lease_id, ttl_seconds=ttl_seconds):
            # BC1-A: lease lost — abort the child HERE, synchronously, in the same
            # path that observed the failed renew. No later poll, no flag.
            _terminate(child)
            raise LeaseLost(
                f"lease {lease_id} lost mid-shard on {slot.get('endpoint_url')}; "
                "di --json child terminated")
    try:
        return _collect_child_result(child, slot)
    except RuntimeError as exc:
        # The child died but the lease is still OURS — surface it held so the caller
        # (dispatch's failover) can release+claim a survivor in one transaction.
        raise ShardDied(str(exc), lease_id=lease_id) from exc


def _run_and_settle(conn, slot, lease_id, frames, flags, *, holder, lease_ops,
                    child_factory, release_on_death, ttl_seconds, renew_seconds,
                    timeout, sleep, clock):
    """Launch the child for an already-held `lease_id`, drive the renew monitor, and
    settle the lease according to the outcome:

      * clean completion -> release (fenced) and return the RunResult;
      * lost renew (LeaseLost) -> release (fenced no-op — a successor holds it now)
        and re-raise, so OUR slot frees immediately rather than at the TTL;
      * child died (ShardDied) -> if `release_on_death` (a failover RETRY that has no
        further fallback) release the transferred slot now; otherwise LEAVE the lease
        held and re-raise, so dispatch can dispose it via the atomic failover transfer
        (the dead lease must NOT be released before the replacement claim is secured).
    """
    child = child_factory(slot, frames, flags)
    try:
        result = _monitor(conn, slot, child, lease_id, lease_ops=lease_ops,
                          ttl_seconds=ttl_seconds, renew_seconds=renew_seconds,
                          timeout=timeout, sleep=sleep, clock=clock)
    except ShardDied:
        if release_on_death:
            lease_ops.release(conn, lease_id)
        raise
    except BaseException:
        lease_ops.release(conn, lease_id)
        raise
    else:
        lease_ops.release(conn, lease_id)
        return result


def run_leased_shard(slot, frames, flags, *, holder, conn_factory,
                     lease_ops=leases, child_factory=_popen_child, model_mib=0,
                     ttl_seconds=TTL_SECONDS, renew_seconds=RENEW_SECONDS,
                     timeout=SHARD_TIMEOUT, sleep=time.sleep, clock=time.monotonic):
    """First-attempt shard: claim `slot`'s lease, run ONE `di --json` child against it
    under a per-shard renew monitor that OWNS the child handle, and settle the lease.
    Returns the parsed RunResult; raises LeaseLost if the slot could not be claimed or
    the lease was lost mid-run (BC1-A abort), or ShardDied if the child itself died
    while we still hold the lease. The lease ops, child launcher, sleep, and clock are
    injectable so the whole lifecycle is hermetically testable with no real DB or
    subprocess.

    On a clean run or a lost renew the lease is released here. On ShardDied the lease
    is LEFT HELD and surfaced via the exception, so `dispatch` can fail it over with an
    ATOMIC release-plus-claim transfer (RFC 0001 failover / BC4) rather than a
    release-now, claim-later sequence that would expose the freed slot to the open
    pool."""
    conn = conn_factory()
    lease_id = lease_ops.claim(conn, slot, holder,
                               ttl_seconds=ttl_seconds, model_mib=model_mib)
    if lease_id is None:
        _close(conn)
        raise LeaseLost(f"could not claim a lease on {slot.get('endpoint_url')}")
    try:
        return _run_and_settle(
            conn, slot, lease_id, frames, flags, holder=holder, lease_ops=lease_ops,
            child_factory=child_factory, release_on_death=False,
            ttl_seconds=ttl_seconds, renew_seconds=renew_seconds, timeout=timeout,
            sleep=sleep, clock=clock)
    finally:
        _close(conn)


def run_failover_shard(dead_lease_id, survivor_slot, frames, flags, *, holder,
                       conn_factory, transfer_conn_factory, lease_ops=leases,
                       child_factory=_popen_child, model_mib=0,
                       ttl_seconds=TTL_SECONDS, renew_seconds=RENEW_SECONDS,
                       timeout=SHARD_TIMEOUT, sleep=time.sleep, clock=time.monotonic):
    """RFC 0001 failover = ATOMIC transfer, not return-to-pool (BC4). In ONE Postgres
    transaction (a non-autocommit `transfer_conn_factory` conn, committed once) RELEASE
    the dead shard's still-held lease AND CLAIM a survivor slot via
    `lease_ops.failover_transfer`, so the freed capacity never hits the open pool
    between the two ops and the dead lease is never released before the replacement
    claim is secured. Then run the retry `di --json` child on the survivor under the
    transferred lease, with the same renew monitor + release as a first-attempt shard
    (here `release_on_death=True`: a retry has no further fallback, so its own death
    frees the transferred slot immediately). Raises LeaseLost if no survivor was
    claimable — the dead lease is still freed in that same committed transaction.

    `dead_lease_id` may be None (the first attempt lost its lease with nothing held);
    failover_transfer's release is then a no-op and it simply claims a survivor."""
    tconn = transfer_conn_factory()
    try:
        candidates = [survivor_slot] if survivor_slot else []
        transferred = lease_ops.failover_transfer(
            tconn, dead_lease_id, candidates, holder,
            ttl_seconds=ttl_seconds, model_mib=model_mib)
        _commit(tconn)
    except BaseException:
        _rollback(tconn)
        _close(tconn)
        raise
    _close(tconn)
    if transferred is None:
        # The dead lease was released in the (committed) transfer; there was no
        # claimable survivor, so these frames cannot be re-run — dispatch records them
        # lost. The slot is freed immediately, not held to the TTL.
        raise LeaseLost(
            f"failover: no claimable survivor; dead lease {dead_lease_id} released")
    conn = conn_factory()
    try:
        return _run_and_settle(
            conn, transferred["slot"], transferred["lease_id"], frames, flags,
            holder=holder, lease_ops=lease_ops, child_factory=child_factory,
            release_on_death=True, ttl_seconds=ttl_seconds, renew_seconds=renew_seconds,
            timeout=timeout, sleep=sleep, clock=clock)
    finally:
        _close(conn)


def _close(conn):
    close = getattr(conn, "close", None)
    if callable(close):
        close()


def _commit(conn):
    commit = getattr(conn, "commit", None)
    if callable(commit):
        commit()


def _rollback(conn):
    rollback = getattr(conn, "rollback", None)
    if callable(rollback):
        rollback()


# --------------------------------------------------------------------------- #
# Dispatch: run all shards concurrently, fail a dead shard over to a survivor.
# --------------------------------------------------------------------------- #
def dispatch(slots, total_frames, flags, *, shard_fn, failover_fn=None,
             max_workers=None):
    """Shard `total_frames` across `slots`, run one shard per slot concurrently,
    and fail any dead shard over once to a surviving endpoint.

    Returns (results, lost) where `results` is a list of {shard, endpoint, frames,
    result} for shards that produced a RunResult, and `lost` is a list of
    {endpoint, frames, error} for frames no endpoint could serve. "No branch lost"
    means: as long as ANY endpoint survives, every frame ends up in some result;
    only a total fleet wipe leaves `lost` non-empty.

    shard_fn(endpoint, frames, flags) is the injectable di boundary. In production
    it is `run_leased_shard` bound to a holder + conn_factory (see main), so every
    shard runs under an exclusive slot lease; tests inject a plain fake.

    failover_fn(dead_lease_id, survivor_endpoint, frames, flags) is the RFC 0001
    ATOMIC failover transfer (BC4): in ONE transaction it releases the dead shard's
    still-held lease AND claims the survivor, then runs the retry child there. When it
    is supplied (the production leased path), the dead lease is disposed ONLY through
    this single-transaction transfer — never released by the first-attempt path before
    the replacement claim is secured. When it is None (a plain injected shard_fn with
    no lease context) failover degrades to re-running shard_fn on a survivor."""
    if not slots:
        return [], []
    counts = shard_frames(total_frames, len(slots))
    # counts may be shorter than slots when F < N (capped); use only that many.
    active = [
        {"shard": i, "endpoint": slots[i], "frames": counts[i]}
        for i in range(len(counts))
    ]
    workers = max_workers or len(active)

    results = []
    failed = []  # shards whose first attempt died, awaiting a survivor
    with ThreadPoolExecutor(max_workers=workers) as ex:
        futs = {
            ex.submit(shard_fn, s["endpoint"], s["frames"], flags): s for s in active
        }
        for fut in as_completed(futs):
            s = futs[fut]
            try:
                results.append({**s, "result": fut.result()})
            except Exception as exc:  # slot died mid-run; queue its frames for failover
                # A leased shard that died while still holding its lease (ShardDied)
                # carries that lease so failover can transfer it atomically; a plain
                # fake (or a lost-lease LeaseLost) carries nothing.
                failed.append({**s, "error": str(exc),
                               "dead_lease_id": getattr(exc, "lease_id", None)})

    # Failover: an endpoint that already returned a result is alive; reassign each
    # dead shard's frames to one such survivor and retry ONCE. Round-robin the
    # survivors so a burst of failures doesn't all pile onto a single slot.
    survivors = [r["endpoint"] for r in results]
    lost = []
    if failed and failover_fn is not None:
        # Production leased path: dispose every dead lease through the atomic transfer.
        # No survivor -> failover_fn still releases the dead lease (in that same commit)
        # and raises, so the slot frees immediately rather than waiting for the TTL.
        with ThreadPoolExecutor(max_workers=len(failed)) as ex:
            retry_futs = {}
            for j, s in enumerate(failed):
                target = survivors[j % len(survivors)] if survivors else None
                retry_futs[ex.submit(failover_fn, s.get("dead_lease_id"), target,
                                     s["frames"], flags)] = (s, target)
            for fut in as_completed(retry_futs):
                s, target = retry_futs[fut]
                try:
                    results.append(
                        {"shard": s["shard"], "endpoint": target or s["endpoint"],
                         "frames": s["frames"], "result": fut.result(),
                         "failed_over_from": s["endpoint"].get("endpoint_url")}
                    )
                except Exception as exc:
                    lost.append({"endpoint": target or s["endpoint"],
                                 "frames": s["frames"],
                                 "error": f"failover transfer failed: {exc}"})
    elif failed and survivors:
        # Plain (non-leased) path: reassign the dead shard's frames and retry once.
        with ThreadPoolExecutor(max_workers=len(failed)) as ex:
            retry_futs = {}
            for j, s in enumerate(failed):
                target = survivors[j % len(survivors)]
                retry_futs[ex.submit(shard_fn, target, s["frames"], flags)] = (s, target)
            for fut in as_completed(retry_futs):
                s, target = retry_futs[fut]
                try:
                    results.append(
                        {"shard": s["shard"], "endpoint": target,
                         "frames": s["frames"], "result": fut.result(),
                         "failed_over_from": s["endpoint"].get("endpoint_url")}
                    )
                except Exception as exc:
                    lost.append({"endpoint": target, "frames": s["frames"],
                                 "error": f"failover retry also failed: {exc}"})
    else:
        # No survivor and no leased failover (total fleet wipe) -> frames are lost.
        lost = [{"endpoint": s["endpoint"], "frames": s["frames"], "error": s["error"]}
                for s in failed]

    for item in lost:
        ep = item["endpoint"].get("endpoint_url", "?")
        print(f"di-fleet: ABANDONED {item['frames']} frame(s) — no endpoint could "
              f"serve them (last={ep}): {item['error']}", file=sys.stderr)
    return results, lost


# --------------------------------------------------------------------------- #
# Merge: N RunResults -> one drop-in-compatible RunResult.
# --------------------------------------------------------------------------- #
def _idea_total(idea):
    return ((idea or {}).get("score") or {}).get("total", 0) or 0


def _idea_novelty(idea):
    return ((idea or {}).get("score") or {}).get("novelty", 0) or 0


def _is_trap(idea):
    return bool(((idea or {}).get("score") or {}).get("trap"))


def merge_results(results, *, top=None):
    """Merge per-shard RunResults (each item {shard, endpoint, frames, result})
    into ONE RunResult, byte-for-byte drop-in compatible with `di --json`:

      branches   : concat all shards', frameIds namespaced by shard index so they
                   stay globally unique (and each idea's frameId rewritten to match).
      shortlist  : union of all shards', globally re-sorted by score.total desc,
                   capped at `top` (default = the largest shard shortlist length).
      deepened   : concat.
      traps      : concat, deduped by `text`.
      nonObviousPick: single highest score.novelty non-trap idea across all shards.
      clusters   : concat (labels namespaced by shard so collisions don't merge).
      reframe/provocation: from the highest-scored shard (best single idea), else
                   first shard. `problem`: unchanged (all shards share it)."""
    payloads = [r["result"] for r in results if r.get("result")]
    if not payloads:
        return {}
    if len(payloads) == 1:
        return payloads[0]

    merged = {"problem": payloads[0].get("problem")}

    branches = []
    for r in results:
        res = r.get("result")
        if not res:
            continue
        sidx = r["shard"]
        for b in res.get("branches") or []:
            fid = f"s{sidx}:{b.get('frameId')}"
            ideas = [{**idea, "frameId": fid} for idea in (b.get("ideas") or [])]
            branches.append({**b, "frameId": fid, "ideas": ideas})
    merged["branches"] = branches

    # shortlist: global union, re-sorted by score.total desc.
    shortlist = []
    for res in payloads:
        shortlist.extend(res.get("shortlist") or [])
    shortlist.sort(key=_idea_total, reverse=True)
    if top is None:
        # No explicit cap: keep at most the biggest single shard's shortlist size,
        # so the merged view stays the same "shape" a single di run would emit.
        top = max((len(res.get("shortlist") or []) for res in payloads), default=0)
    merged["shortlist"] = shortlist[:top] if top else shortlist

    deepened = []
    for res in payloads:
        deepened.extend(res.get("deepened") or [])
    merged["deepened"] = deepened

    # traps: concat then dedup by text, preserving first-seen order.
    traps, seen = [], set()
    for res in payloads:
        for t in res.get("traps") or []:
            key = (t or {}).get("text")
            if key in seen:
                continue
            seen.add(key)
            traps.append(t)
    merged["traps"] = traps

    # nonObviousPick: highest novelty non-trap idea across every idea in every shard.
    best = None
    for r in results:
        res = r.get("result")
        if not res:
            continue
        sidx = r["shard"]
        for b in res.get("branches") or []:
            for idea in b.get("ideas") or []:
                if _is_trap(idea):
                    continue
                if best is None or _idea_novelty(idea) > _idea_novelty(best):
                    best = {**idea, "frameId": f"s{sidx}:{idea.get('frameId')}"}
    merged["nonObviousPick"] = best

    # clusters: concat; namespace labels/ideaIds so equal labels from two shards
    # are not silently conflated.
    clusters = []
    for r in results:
        res = r.get("result")
        if not res:
            continue
        sidx = r["shard"]
        for c in res.get("clusters") or []:
            clusters.append({**c, "label": f"s{sidx}:{c.get('label')}"})
    merged["clusters"] = clusters

    # reframe + provocation: take from the shard with the single best-scored idea
    # (the strongest run), falling back to the first shard.
    best_shard = max(
        payloads,
        key=lambda res: max(
            (_idea_total(i) for b in (res.get("branches") or [])
             for i in (b.get("ideas") or [])),
            default=0,
        ),
    )
    if best_shard.get("reframe") is not None:
        merged["reframe"] = best_shard.get("reframe")
    merged["provocation"] = best_shard.get("provocation")

    return merged


# --------------------------------------------------------------------------- #
# Human summary for non --json N>1 runs.
# --------------------------------------------------------------------------- #
def render_summary(merged):
    """Short human summary for non-`--json` multi-slot runs: shortlist + the
    non-obvious pick + the provocation. The machine path is --json; this is the
    'what did the fleet come up with' glance for a person."""
    lines = [f"problem: {merged.get('problem')}", ""]
    if merged.get("reframe"):
        lines += [f"reframe: {merged['reframe']}", ""]
    lines.append("shortlist (global, by score.total):")
    for i, idea in enumerate(merged.get("shortlist") or [], 1):
        total = _idea_total(idea)
        lines.append(f"  {i}. [{total:>5}] {(idea or {}).get('text', '')}")
    pick = merged.get("nonObviousPick")
    if pick:
        lines += ["", f"non-obvious pick: {pick.get('text', '')}"]
    if merged.get("provocation"):
        lines += ["", f"provocation: {merged['provocation']}"]
    return "\n".join(lines)


# --------------------------------------------------------------------------- #
# CLI: parse, route, shard+dispatch+merge, emit.
# --------------------------------------------------------------------------- #
# Flags that di-fleet OWNS (it sets --frames per shard, forces --json/--quiet on
# the subprocesses, and consumes --top to cap the merged shortlist). Everything
# else (problem text, --ideas, --context, --concurrency, --no-code-mode, --model)
# passes straight through to each shard.
def _split_argv(argv):
    """Pull out di-fleet-owned flags (--frames, --top, --json) and the K override;
    return (frames, top, want_json, k, passthrough_flags). The problem text and
    every other di flag stay in passthrough verbatim."""
    frames, top, want_json, k = None, None, False, None
    rest = []
    i = 0
    while i < len(argv):
        a = argv[i]
        if a == "--frames":
            frames = int(argv[i + 1]); i += 2
        elif a == "--top":
            top = int(argv[i + 1])
            rest += [a, argv[i + 1]]  # --top still passes through to each shard
            i += 2
        elif a == "--json":
            want_json = True; i += 1
        elif a == "-k" or a == "--slots":
            k = int(argv[i + 1]); i += 2  # di-fleet-only: fan-out width override
        else:
            rest.append(a); i += 1
    return frames, top, want_json, k, rest


def _holder_id():
    """Human-readable lease holder for observability (lease_holder column)."""
    return f"di-fleet/{socket.gethostname()}/{os.getpid()}"


def _pg_conn_factory(db):
    """A fresh autocommit psycopg connection per shard. Autocommit so each
    claim/renew/release is its own committed transaction, immediately visible to
    every other consumer — which is what makes the lease exclusive across processes.
    Lazily imported so importing di_fleet (for tests) needs no driver."""
    def factory():
        import psycopg
        return psycopg.connect(db, autocommit=True)
    return factory


def _pg_transfer_conn_factory(db):
    """A fresh NON-autocommit psycopg connection for one atomic failover transfer.
    The transfer's release(dead) + claim(survivor) must commit or roll back TOGETHER
    (RFC 0001 / BC4), so unlike the per-shard autocommit conns this one wraps both
    statements in a single explicit transaction that run_failover_shard commits once."""
    def factory():
        import psycopg
        return psycopg.connect(db)  # autocommit defaults off -> one explicit txn
    return factory


def main(argv=None):
    argv = list(sys.argv[1:] if argv is None else argv)
    frames, top, want_json, k_override, passthrough = _split_argv(argv)
    total_frames = frames if frames is not None else 5  # di's --frames default

    db = os.environ.get("GPU_FLEET_DB", "dbname=gpu_fleet")
    k = k_override or total_frames  # never route more slots than there are frames
    slots = route_slots(k, db=db)

    # No live fleet slot -> single di on its own localhost default (today's
    # behavior). Nothing to lease, so we exec and pass frames through unchanged.
    if not slots:
        print("di-fleet: no live fleet slot; using di defaults (localhost:8081)",
              file=sys.stderr)
        cmd = ["node", DI_CLI, *passthrough, "--frames", str(total_frames)]
        if want_json:
            cmd.append("--json")
        os.execvp("node", cmd)  # replace process; preserves exit code / streaming
        return 0  # unreachable

    # One or more live slots -> CLAIM a lease per slot, shard, run concurrently under
    # the per-shard renew monitor (BC1-A in-flight abort), fail over, merge. Leasing
    # makes di-fleet's K-fan-out EXCLUSIVE (RFC 0001): two consumers never share a
    # GPU. We buffer (rather than exec) even for a single slot, because the lease
    # needs an in-process renew monitor + release that an exec'd process can't run.
    eps = ", ".join(f"{s['endpoint_url']}" for s in slots)
    print(f"di-fleet -> {len(slots)} slot(s): {eps}", file=sys.stderr)
    holder = _holder_id()
    conn_factory = _pg_conn_factory(db)
    transfer_conn_factory = _pg_transfer_conn_factory(db)

    def leased_shard(endpoint, frames, flags):
        return run_leased_shard(endpoint, frames, flags,
                                holder=holder, conn_factory=conn_factory)

    def leased_failover(dead_lease_id, survivor, frames, flags):
        # RFC 0001 failover transfer: release the dead lease + claim the survivor in
        # ONE transaction (BC4), then run the retry child under the transferred lease.
        return run_failover_shard(dead_lease_id, survivor, frames, flags,
                                  holder=holder, conn_factory=conn_factory,
                                  transfer_conn_factory=transfer_conn_factory)

    results, lost = dispatch(slots, total_frames, passthrough,
                             shard_fn=leased_shard, failover_fn=leased_failover)
    if not results:
        print("di-fleet: every shard failed; no result", file=sys.stderr)
        return 1
    merged = merge_results(results, top=top)
    if lost:
        merged = {**merged, "_lost_frames": sum(x["frames"] for x in lost)}

    if want_json:
        print(json.dumps(merged, indent=2))
    else:
        print(render_summary(merged))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
