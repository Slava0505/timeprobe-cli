from __future__ import annotations

import json
import os
import subprocess
import sys
import time
from concurrent.futures import ThreadPoolExecutor

import pytest

from timeprobe import store


@pytest.fixture
def cli(tmp_path):
    environment = {**os.environ, "TIMEPROBE_STATE_DIR": str(tmp_path)}

    def invoke(*arguments, code=0):
        result = subprocess.run(
            [sys.executable, "-m", "timeprobe", *arguments, "--json"],
            capture_output=True,
            text=True,
            env=environment,
            timeout=15,
        )
        assert result.returncode == code, result.stderr + result.stdout
        return json.loads(result.stdout)

    yield invoke
    # Always stop the worker, even after an assertion failure.
    subprocess.run(
        [sys.executable, "-m", "timeprobe", "stop"],
        capture_output=True,
        env=environment,
        timeout=15,
    )
    # Let the worker notice stop before pytest removes its temporary directory.
    time.sleep(0.2)


def test_real_cli_session_lifecycle(cli):
    assert cli("status")["state"] == "idle"
    started = cli("start")
    assert started["ok"] is True
    time.sleep(0.2)
    assert cli("status")["elapsed_seconds"] >= 0.2
    duplicate = cli("start", code=1)
    assert duplicate["error"]["code"] == "already_running"
    assert duplicate["session"]["id"] == started["id"]
    paused = cli("pause")
    time.sleep(0.2)
    assert cli("status")["elapsed_seconds"] == paused["elapsed_seconds"]
    cli("resume")
    time.sleep(0.2)
    stopped = cli("stop")
    assert stopped["elapsed_seconds"] >= paused["elapsed_seconds"] + 0.2
    assert cli("history")["sessions"][0] == {k: v for k, v in stopped.items() if k != "ok"}
    assert cli("status")["state"] == "idle"
    assert cli("start")["id"] != started["id"]


def test_real_cli_early_stop_with_target(cli):
    cli("start", "--target", "1h")
    stopped = cli("stop")
    assert stopped["target_seconds"] == 3600
    assert stopped["elapsed_seconds"] < 30
    assert stopped["target_reached"] is False
    assert stopped["signal_state"] == "pending"


def test_parallel_start_only_one_session(cli, tmp_path):
    def launch(_):
        environment = {**os.environ, "TIMEPROBE_STATE_DIR": str(tmp_path)}
        return subprocess.run(
            [sys.executable, "-m", "timeprobe", "start", "--json"],
            capture_output=True,
            text=True,
            env=environment,
            timeout=15,
        )

    with ThreadPoolExecutor(max_workers=4) as pool:
        results = list(pool.map(launch, range(4)))
    assert sorted(result.returncode for result in results) == [0, 1, 1, 1]
    assert (
        len({json.loads(result.stdout).get("id") for result in results if result.returncode == 0})
        == 1
    )
    assert cli("status")["state"] == "running"


def test_worker_death_leaves_interrupted_history(cli, tmp_path):
    cli("start")
    time.sleep(0.3)
    with store.locked(tmp_path) as data:
        pid = data["current"]["worker_pid"]
    os.kill(pid, 15)
    deadline = time.monotonic() + 5
    while store.alive(pid) and time.monotonic() < deadline:
        time.sleep(0.05)
    assert cli("status")["state"] == "idle"
    assert cli("history")["sessions"][0]["state"] == "interrupted"
    cli("start")


@pytest.mark.parametrize(
    "args", [("start", "--target", "0s"), ("start", "--target", "bad"), ("pomodoro",)]
)
def test_bad_arguments_are_json(cli, args):
    assert cli(*args, code=2)["error"]["code"] == "invalid_arguments"


def test_missing_session_is_json(cli):
    assert cli("stop", code=1)["error"]["code"] == "no_session"
