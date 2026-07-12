#!/usr/bin/env python3
"""Run one arbitrary command while holding an exclusive gpu-fleet slot lease.

The command is launched only after an exact capability pick and atomic claim.  A
renew failure stops the command's process group before the fenced lease release.
There is deliberately no endpoint fallback or automatic retry: callers such as
evaluation harnesses must not silently replay work after losing their route.
"""

from __future__ import annotations

import argparse
import os
import signal
import socket
import subprocess
import sys
import time
from contextlib import contextmanager
from dataclasses import dataclass

import di_fleet as lease_module
import pick_slot

ENDPOINT_TOKEN = "@@GPU_FLEET_ENDPOINT_URL@@"
MODEL_TOKEN = "@@GPU_FLEET_SERVED_MODEL@@"
TEMPFAIL = 75


class NoSlotAvailable(RuntimeError):
    """No matching slot could be picked and claimed."""


class FleetUnavailable(RuntimeError):
    """The registry could not be reached or could not settle acquisition."""


class LeaseLost(RuntimeError):
    """The registry could not prove that this process still owns its slot."""


class CommandTimedOut(RuntimeError):
    """The child exceeded its caller-supplied wall-clock budget."""


class SignalReceived(RuntimeError):
    """A termination signal received by the runner."""

    def __init__(self, signum: int):
        super().__init__(f"received signal {signum}")
        self.signum = signum


@dataclass(frozen=True)
class LeaseRequest:
    model: str
    command: tuple[str, ...]
    holder: str
    job: str = ""
    max_context: int | None = None
    min_vram: int | None = None
    latency_class: str | None = None
    timeout: float | None = None


class _ProcessGroup:
    """Popen facade whose stop operations target the child's whole session."""

    def __init__(self, proc: subprocess.Popen):
        self._proc = proc

    def poll(self):
        return self._proc.poll()

    def wait(self, timeout=None):
        return self._proc.wait(timeout=timeout)

    def terminate(self):
        try:
            os.killpg(self._proc.pid, signal.SIGTERM)
        except ProcessLookupError:
            pass

    def kill(self):
        try:
            os.killpg(self._proc.pid, signal.SIGKILL)
        except ProcessLookupError:
            pass


def _launch(command, env):
    proc = subprocess.Popen(command, env=env, start_new_session=True)
    return _ProcessGroup(proc)


@dataclass(frozen=True)
class LeaseRuntime:
    conn_factory: object
    pick_fn: object = pick_slot.pick
    lease_ops: object = lease_module.leases
    child_factory: object = _launch
    ttl_seconds: float = lease_module.TTL_SECONDS
    renew_seconds: float = lease_module.RENEW_SECONDS
    clock: object = time.monotonic
    sleep: object = None


@dataclass(frozen=True)
class _HeldCommand:
    conn: object
    child: object
    lease_id: object
    request: LeaseRequest
    runtime: LeaseRuntime


def _close(conn):
    close = getattr(conn, "close", None)
    if close:
        close()


@contextmanager
def _acquisition_transaction(conn):
    """Keep PICK's row lock through CLAIM, including on autocommit connections."""
    transaction = getattr(conn, "transaction", None)
    if transaction:
        with transaction():
            yield
        return
    try:
        yield
        commit = getattr(conn, "commit", None)
        if commit:
            commit()
    except BaseException:
        rollback = getattr(conn, "rollback", None)
        if rollback:
            rollback()
        raise


def _acquire(conn, request, runtime):
    try:
        with _acquisition_transaction(conn):
            candidates = runtime.pick_fn(
                conn,
                latency_class=request.latency_class,
                model=request.model,
                min_vram=request.min_vram,
                max_context=request.max_context,
                k=1,
                job=request.job,
            )
            if not candidates:
                raise NoSlotAvailable(f"no routable slot serves {request.model}")
            slot = candidates[0]
            lease_id = runtime.lease_ops.claim(
                conn,
                slot,
                request.holder,
                ttl_seconds=runtime.ttl_seconds,
                model_mib=request.min_vram or 0,
                max_context=request.max_context,
            )
            if lease_id is None:
                raise NoSlotAvailable(f"slot for {request.model} was not claimable")
    except NoSlotAvailable:
        raise
    except Exception as exc:
        raise FleetUnavailable(f"registry acquisition failed: {exc}") from exc
    return slot, lease_id


def _resolve_command(command, slot):
    return tuple(
        part.replace(ENDPOINT_TOKEN, slot["endpoint_url"]).replace(
            MODEL_TOKEN, slot["served_model"]
        )
        for part in command
    )


def _child_env(slot, lease_id):
    env = dict(os.environ)
    env.update(
        {
            "GPU_FLEET_ENDPOINT_URL": slot["endpoint_url"],
            "GPU_FLEET_SERVED_MODEL": slot["served_model"],
            "GPU_FLEET_NODE": slot["node"],
            "GPU_FLEET_SLOT_ID": str(slot.get("slot_id", 0)),
            "GPU_FLEET_LEASE_ID": str(lease_id),
        }
    )
    return env


def _terminate(child, grace_seconds=5):
    if child.poll() is not None:
        return
    child.terminate()
    try:
        child.wait(timeout=grace_seconds)
    except subprocess.TimeoutExpired:
        child.kill()
        child.wait(timeout=grace_seconds)


def _shell_status(returncode):
    return 128 + abs(returncode) if returncode < 0 else returncode


def _wait_interval(child, seconds, sleep):
    if sleep is not None:
        sleep(seconds)
        return child.poll()
    try:
        return child.wait(timeout=seconds)
    except subprocess.TimeoutExpired:
        return None


def _monitor(held):
    child = held.child
    request = held.request
    runtime = held.runtime
    started = runtime.clock()
    while True:
        returncode = child.poll()
        if returncode is not None:
            return _shell_status(returncode)

        interval = runtime.renew_seconds
        if request.timeout is not None:
            remaining = request.timeout - (runtime.clock() - started)
            if remaining <= 0:
                _terminate(child)
                raise CommandTimedOut(f"command timed out after {request.timeout}s")
            interval = min(interval, remaining)

        returncode = _wait_interval(child, interval, runtime.sleep)
        if returncode is not None:
            return _shell_status(returncode)

        try:
            lease_is_held = runtime.lease_ops.renew(
                held.conn, held.lease_id, ttl_seconds=runtime.ttl_seconds
            )
        except Exception as exc:
            _terminate(child)
            raise LeaseLost(f"lease {held.lease_id} renew failed: {exc}") from exc
        if not lease_is_held:
            _terminate(child)
            raise LeaseLost(
                f"lease {held.lease_id} was lost; child process group stopped"
            )


def _validate(request, runtime):
    if not request.model:
        raise ValueError("model is required")
    if not request.command:
        raise ValueError("a command is required after --")
    if (
        runtime.ttl_seconds <= 0
        or runtime.renew_seconds <= 0
        or runtime.renew_seconds >= runtime.ttl_seconds
    ):
        raise ValueError("require 0 < renew-seconds < ttl-seconds")
    if request.timeout is not None and request.timeout <= 0:
        raise ValueError("timeout must be positive")


def _cleanup(conn, lease_id, runtime, primary_error):
    cleanup_errors = []
    try:
        runtime.lease_ops.release(conn, lease_id)
    except Exception as exc:
        cleanup_errors.append(f"release failed: {exc}")
    try:
        _close(conn)
    except Exception as exc:
        cleanup_errors.append(f"connection close failed: {exc}")
    if not cleanup_errors:
        return
    message = "; ".join(cleanup_errors)
    if primary_error is None:
        raise RuntimeError(message)
    print(f"gpu-fleet-run: cleanup after error: {message}", file=sys.stderr)


def run_leased_command(request, runtime):
    """Claim one exact-model route, run the command, and always settle the lease."""
    _validate(request, runtime)
    try:
        conn = runtime.conn_factory()
    except Exception as exc:
        raise FleetUnavailable(f"registry connection failed: {exc}") from exc
    lease_id = None
    child = None
    primary_error = None
    try:
        slot, lease_id = _acquire(conn, request, runtime)
        command = _resolve_command(request.command, slot)
        env = _child_env(slot, lease_id)
        print(
            f"gpu-fleet-run: acquired model={slot['served_model']} "
            f"node={slot['node']} slot={slot.get('slot_id', 0)} "
            f"endpoint={slot['endpoint_url']} lease={lease_id}",
            file=sys.stderr,
        )
        child = runtime.child_factory(command, env)
        return _monitor(_HeldCommand(conn, child, lease_id, request, runtime))
    except BaseException as exc:
        primary_error = exc
        if child is not None:
            _terminate(child)
        raise
    finally:
        if lease_id is not None:
            _cleanup(conn, lease_id, runtime, primary_error)
        else:
            _close(conn)


def _connection_factory(db):
    def connect():
        import psycopg

        return psycopg.connect(
            db,
            autocommit=True,
            options="-c statement_timeout=5000 -c lock_timeout=5000",
        )

    return connect


def _parse_args(argv=None):
    parser = argparse.ArgumentParser(
        description="run a command under one exact-model gpu-fleet lease"
    )
    parser.add_argument("--model", required=True)
    parser.add_argument("--max-context", type=int)
    parser.add_argument("--min-vram", type=int)
    parser.add_argument("--latency-class", choices=("interactive", "batch"))
    parser.add_argument("--job", default="")
    parser.add_argument("--holder")
    parser.add_argument("--db", default="dbname=gpu_fleet")
    parser.add_argument("--timeout", type=float)
    parser.add_argument("--ttl-seconds", type=float, default=lease_module.TTL_SECONDS)
    parser.add_argument(
        "--renew-seconds", type=float, default=lease_module.RENEW_SECONDS
    )
    parser.add_argument("command", nargs=argparse.REMAINDER)
    args = parser.parse_args(argv)
    if args.command[:1] == ["--"]:
        args.command = args.command[1:]
    return args


def main(argv=None):
    args = _parse_args(argv)
    holder = args.holder or f"{socket.gethostname()}:{os.getpid()}"
    request = LeaseRequest(
        model=args.model,
        command=tuple(args.command),
        holder=holder,
        job=args.job,
        max_context=args.max_context,
        min_vram=args.min_vram,
        latency_class=args.latency_class,
        timeout=args.timeout,
    )

    old_handler = signal.getsignal(signal.SIGTERM)

    def on_sigterm(signum, _frame):
        raise SignalReceived(signum)

    signal.signal(signal.SIGTERM, on_sigterm)
    try:
        return run_leased_command(
            request,
            LeaseRuntime(
                conn_factory=_connection_factory(args.db),
                ttl_seconds=args.ttl_seconds,
                renew_seconds=args.renew_seconds,
            ),
        )
    except CommandTimedOut as exc:
        print(f"gpu-fleet-run: {exc}", file=sys.stderr)
        return 124
    except (NoSlotAvailable, FleetUnavailable, LeaseLost) as exc:
        print(f"gpu-fleet-run: {exc}", file=sys.stderr)
        return TEMPFAIL
    except SignalReceived as exc:
        print(f"gpu-fleet-run: {exc}", file=sys.stderr)
        return 128 + exc.signum
    except KeyboardInterrupt:
        return 130
    except Exception as exc:
        print(f"gpu-fleet-run: internal error: {exc}", file=sys.stderr)
        return 70
    finally:
        signal.signal(signal.SIGTERM, old_handler)


if __name__ == "__main__":
    raise SystemExit(main())
