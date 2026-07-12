"""Generic command execution under an exclusive gpu-fleet slot lease."""

import os
import subprocess
import sys
import time

import pytest

import lease_run as lr
from lease_fakes import FakeChild, FakeSlotDB


SLOT = {
    "node": "peecee",
    "endpoint_url": "http://peecee:11434/v1",
    "slot_id": 0,
    "served_model": "qwen3.6:27b",
}


def _request(*command):
    return lr.LeaseRequest(
        model="qwen3.6:27b",
        command=command or ("true",),
        holder="test-holder",
        job="trial-01",
        max_context=32768,
    )


def _pick(_conn, **_filters):
    return [SLOT]


def _runtime(conn_factory, **changes):
    return lr.LeaseRuntime(conn_factory=conn_factory, **changes)


def test_clean_child_receives_resolved_route_and_releases_lease():
    db = FakeSlotDB([SLOT])
    launched = {}

    def child_factory(command, env):
        launched["command"] = command
        launched["env"] = env
        return FakeChild(returncode=7)

    result = lr.run_leased_command(
        _request(
            "client",
            "--base=@@GPU_FLEET_ENDPOINT_URL@@",
            "--model=@@GPU_FLEET_SERVED_MODEL@@",
        ),
        _runtime(
            lambda: db,
            pick_fn=_pick,
            child_factory=child_factory,
            sleep=lambda _seconds: None,
        ),
    )

    assert result == 7
    assert launched["command"] == (
        "client",
        "--base=http://peecee:11434/v1",
        "--model=qwen3.6:27b",
    )
    assert launched["env"]["GPU_FLEET_ENDPOINT_URL"] == SLOT["endpoint_url"]
    assert launched["env"]["GPU_FLEET_SERVED_MODEL"] == SLOT["served_model"]
    assert launched["env"]["GPU_FLEET_NODE"] == SLOT["node"]
    assert launched["env"]["GPU_FLEET_SLOT_ID"] == "0"
    assert launched["env"]["GPU_FLEET_LEASE_ID"] == "L1"
    assert db.row_for(SLOT)["lease_id"] is None


def test_no_matching_slot_never_launches_child():
    launched = []

    with pytest.raises(lr.NoSlotAvailable):
        lr.run_leased_command(
            _request(),
            _runtime(
                lambda: object(),
                pick_fn=lambda _conn, **_filters: [],
                child_factory=lambda *_args: launched.append(True),
            ),
        )

    assert launched == []


def test_registry_connection_error_never_launches_child():
    launched = []

    def unavailable():
        raise OSError("database unavailable")

    with pytest.raises(lr.FleetUnavailable, match="connection failed"):
        lr.run_leased_command(
            _request(),
            _runtime(
                unavailable,
                child_factory=lambda *_args: launched.append(True),
            ),
        )

    assert launched == []


def test_claim_race_never_launches_child():
    launched = []

    class CannotClaim:
        @staticmethod
        def claim(*_args, **_kwargs):
            return None

        @staticmethod
        def renew(*_args, **_kwargs):
            raise AssertionError("an unclaimed lease cannot renew")

        @staticmethod
        def release(*_args, **_kwargs):
            raise AssertionError("an unclaimed lease cannot release")

    with pytest.raises(lr.NoSlotAvailable):
        lr.run_leased_command(
            _request(),
            _runtime(
                lambda: object(),
                pick_fn=_pick,
                lease_ops=CannotClaim,
                child_factory=lambda *_args: launched.append(True),
            ),
        )

    assert launched == []


def test_failed_renew_terminates_child_in_same_control_path_and_releases():
    child = FakeChild(runs_forever=True)

    class LostLease:
        released = []

        @staticmethod
        def claim(*_args, **_kwargs):
            return "lease-1"

        @staticmethod
        def renew(*_args, **_kwargs):
            return False

        @classmethod
        def release(cls, _conn, lease_id):
            cls.released.append(lease_id)

    with pytest.raises(lr.LeaseLost):
        lr.run_leased_command(
            _request(),
            _runtime(
                lambda: object(),
                pick_fn=_pick,
                lease_ops=LostLease,
                child_factory=lambda *_args: child,
                renew_seconds=1,
                sleep=lambda _seconds: None,
            ),
        )

    assert child.terminated is True
    assert LostLease.released == ["lease-1"]


def test_renew_error_is_fail_closed_and_terminates_child():
    child = FakeChild(runs_forever=True)

    class RegistryDown:
        @staticmethod
        def claim(*_args, **_kwargs):
            return "lease-1"

        @staticmethod
        def renew(*_args, **_kwargs):
            raise OSError("database unavailable")

        @staticmethod
        def release(*_args, **_kwargs):
            pass

    with pytest.raises(lr.LeaseLost, match="renew failed"):
        lr.run_leased_command(
            _request(),
            _runtime(
                lambda: object(),
                pick_fn=_pick,
                lease_ops=RegistryDown,
                child_factory=lambda *_args: child,
                renew_seconds=1,
                sleep=lambda _seconds: None,
            ),
        )

    assert child.terminated is True


def test_exception_while_monitoring_terminates_child_and_releases():
    db = FakeSlotDB([SLOT])
    child = FakeChild(runs_forever=True)

    def interrupted(_seconds):
        raise KeyboardInterrupt

    with pytest.raises(KeyboardInterrupt):
        lr.run_leased_command(
            _request(),
            _runtime(
                lambda: db,
                pick_fn=_pick,
                child_factory=lambda *_args: child,
                sleep=interrupted,
            ),
        )

    assert child.terminated is True
    assert db.row_for(SLOT)["lease_id"] is None


def test_pick_and_claim_commit_before_child_launch():
    events = []

    class Conn:
        def commit(self):
            events.append("commit")

        def close(self):
            events.append("close")

    class Ops:
        @staticmethod
        def claim(*_args, **_kwargs):
            events.append("claim")
            return "lease-1"

        @staticmethod
        def renew(*_args, **_kwargs):
            raise AssertionError("finished child must not renew")

        @staticmethod
        def release(*_args, **_kwargs):
            events.append("release")

    def pick(*_args, **_kwargs):
        events.append("pick")
        return [SLOT]

    def launch(*_args):
        events.append("launch")
        return FakeChild(returncode=0)

    assert (
        lr.run_leased_command(
            _request(),
            _runtime(
                Conn,
                pick_fn=pick,
                lease_ops=Ops,
                child_factory=launch,
            ),
        )
        == 0
    )
    assert events == ["pick", "claim", "commit", "launch", "release", "close"]


def test_running_child_renews_then_releases_on_zero_exit():
    child = FakeChild(runs_forever=True)
    events = []

    class Ops:
        @staticmethod
        def claim(*_args, **_kwargs):
            return "lease-1"

        @staticmethod
        def renew(*_args, **_kwargs):
            events.append("renew")
            return True

        @staticmethod
        def release(*_args, **_kwargs):
            events.append("release")

    def finish_after_one_interval(_seconds):
        if events == ["renew"]:
            child.returncode = 0

    assert (
        lr.run_leased_command(
            _request(),
            _runtime(
                lambda: object(),
                pick_fn=_pick,
                lease_ops=Ops,
                child_factory=lambda *_args: child,
                renew_seconds=1,
                sleep=finish_after_one_interval,
            ),
        )
        == 0
    )
    assert events == ["renew", "release"]


def test_child_launch_error_releases_claim():
    db = FakeSlotDB([SLOT])

    def fail_launch(*_args):
        raise OSError("exec failed")

    with pytest.raises(OSError, match="exec failed"):
        lr.run_leased_command(
            _request(),
            _runtime(
                lambda: db,
                pick_fn=_pick,
                child_factory=fail_launch,
            ),
        )

    assert db.row_for(SLOT)["lease_id"] is None


def test_timeout_terminates_then_releases():
    child = FakeChild(runs_forever=True)
    now = [0.0]
    events = []

    class Ops:
        @staticmethod
        def claim(*_args, **_kwargs):
            return "lease-1"

        @staticmethod
        def renew(*_args, **_kwargs):
            events.append("renew")
            return True

        @staticmethod
        def release(*_args, **_kwargs):
            events.append("release")

    def advance(seconds):
        now[0] += seconds

    request = lr.LeaseRequest(
        model="qwen3.6:27b",
        command=("sleep", "forever"),
        holder="test-holder",
        timeout=2,
    )
    with pytest.raises(lr.CommandTimedOut):
        lr.run_leased_command(
            request,
            _runtime(
                lambda: object(),
                pick_fn=_pick,
                lease_ops=Ops,
                child_factory=lambda *_args: child,
                renew_seconds=1,
                clock=lambda: now[0],
                sleep=advance,
            ),
        )

    assert child.terminated is True
    assert events[-1] == "release"


def test_term_ignoring_child_is_killed_before_release():
    events = []

    class IgnoringChild:
        returncode = None

        def poll(self):
            return self.returncode

        def terminate(self):
            events.append("terminate")

        def wait(self, timeout=None):
            if self.returncode is None:
                raise subprocess.TimeoutExpired("child", timeout)
            return self.returncode

        def kill(self):
            events.append("kill")
            self.returncode = -9

    class Ops:
        @staticmethod
        def claim(*_args, **_kwargs):
            return "lease-1"

        @staticmethod
        def renew(*_args, **_kwargs):
            return False

        @staticmethod
        def release(*_args, **_kwargs):
            events.append("release")

    with pytest.raises(lr.LeaseLost):
        lr.run_leased_command(
            _request(),
            _runtime(
                lambda: object(),
                pick_fn=_pick,
                lease_ops=Ops,
                child_factory=lambda *_args: IgnoringChild(),
                renew_seconds=1,
                sleep=lambda _seconds: None,
            ),
        )

    assert events == ["terminate", "kill", "release"]


def test_token_replacement_does_not_interpolate_json_braces():
    db = FakeSlotDB([SLOT])
    launched = []

    lr.run_leased_command(
        _request(
            "client",
            '--json={"temperature":0.6}',
            "@@GPU_FLEET_ENDPOINT_URL@@",
        ),
        _runtime(
            lambda: db,
            pick_fn=_pick,
            child_factory=lambda command, _env: (
                launched.append(command) or FakeChild(returncode=0)
            ),
        ),
    )

    assert launched == [("client", '--json={"temperature":0.6}', SLOT["endpoint_url"])]


def test_real_process_group_termination_reaps_parent_and_grandchild(tmp_path):
    pid_file = tmp_path / "pids"
    command = (
        sys.executable,
        "-c",
        "import pathlib,subprocess,time,os; "
        "p=subprocess.Popen(['sleep','60']); "
        f"pathlib.Path({str(pid_file)!r}).write_text(f'{{os.getpid()}} {{p.pid}}'); "
        "time.sleep(60)",
    )

    class Lost:
        @staticmethod
        def claim(*_args, **_kwargs):
            return "lease-1"

        @staticmethod
        def renew(*_args, **_kwargs):
            return False

        @staticmethod
        def release(*_args, **_kwargs):
            pass

    with pytest.raises(lr.LeaseLost):
        lr.run_leased_command(
            lr.LeaseRequest("qwen3.6:27b", command, "test-holder"),
            _runtime(
                lambda: object(),
                pick_fn=_pick,
                lease_ops=Lost,
                renew_seconds=0.1,
                ttl_seconds=1,
            ),
        )

    parent, grandchild = map(int, pid_file.read_text().split())
    for pid in (parent, grandchild):
        deadline = time.monotonic() + 2
        while time.monotonic() < deadline and os.path.exists(f"/proc/{pid}"):
            stat = open(f"/proc/{pid}/stat").read().split()[2]
            if stat == "Z":
                break
            time.sleep(0.02)
        assert not os.path.exists(f"/proc/{pid}") or stat == "Z"
