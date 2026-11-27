"""A single session and a small background worker; no system service."""

from __future__ import annotations

import os
import subprocess
import sys
import time
import uuid
import warnings
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

from timeprobe import sound, store
from timeprobe.model import SessionError, checkpoint, elapsed, snapshot, transition


def stamp() -> str:
    return datetime.now(timezone.utc).isoformat()


def maintain(data: dict[str, Any]) -> None:
    cutoff = (datetime.now(timezone.utc) - timedelta(days=1)).isoformat()
    data["history"] = [s for s in data["history"] if s["ended_at"] >= cutoff]
    current = data["current"]
    if current and not store.alive(current["worker_pid"]):
        # Freeze at the last checkpoint. Do not count downtime or restore a worker.
        current.update(state="interrupted", ended_at=current["updated_at"])
        data["history"].append(current)
        data["current"] = None


def spawn(directory: Path, session_id: str) -> int:
    pythonw = Path(sys.executable).with_name("pythonw.exe")
    interpreter = str(pythonw) if pythonw.exists() else sys.executable
    startup = subprocess.STARTUPINFO()
    startup.dwFlags |= subprocess.STARTF_USESHOWWINDOW
    startup.wShowWindow = subprocess.SW_HIDE
    process = subprocess.Popen(
        [interpreter, "-m", "timeprobe", "_worker", session_id],
        stdin=subprocess.DEVNULL,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        env={**os.environ, "TIMEPROBE_STATE_DIR": str(directory)},
        creationflags=subprocess.CREATE_NO_WINDOW | subprocess.CREATE_NEW_PROCESS_GROUP,
        startupinfo=startup,
    )
    pid = process.pid
    # This CLI intentionally exits before its detached child. No wait is intended.
    with warnings.catch_warnings():
        warnings.simplefilter("ignore", ResourceWarning)
        del process
    return pid


def execute(
    action: str,
    directory: Path,
    target: float | None = None,
    scale: float = 1.0,
    visible: bool = False,
) -> dict[str, Any]:
    failure = None
    with store.locked(directory) as data:
        maintain(data)
        current = data["current"]
        tick = time.monotonic()
        if action == "history":
            result = {"sessions": [snapshot(s, tick) for s in reversed(data["history"])]}
        elif action == "start":
            if current:
                failure = SessionError(
                    "already_running", "A session is already active; stop it first."
                )
                result = snapshot(current, tick)
            else:
                current = {
                    "id": uuid.uuid4().hex,
                    "state": "running",
                    "started_at": stamp(),
                    "ended_at": None,
                    "updated_at": stamp(),
                    "elapsed_seconds": 0.0,
                    "running_since": tick,
                    "target_seconds": target,
                    "scale": scale,
                    "widget_hidden": not visible,
                    "signal_state": "pending" if target is not None else "disabled",
                    "signal_error": None,
                    "worker_pid": None,
                }
                current["worker_pid"] = spawn(directory, current["id"])
                data["current"] = current
                result = snapshot(current, tick)
        elif not current:
            if action == "status":
                result = {"state": "idle"}
            else:
                failure = SessionError("no_session", "No active session.")
                result = {"state": "idle"}
        else:
            transition(current, action, tick, stamp())
            current["updated_at"] = stamp()
            result = snapshot(current, tick)
            if action == "stop":
                data["history"].append(current)
                data["current"] = None
    if failure:
        failure.session = result
        raise failure
    return result


def step(directory: Path, session_id: str) -> bool:
    with store.locked(directory) as data:
        current = data["current"]
        if not current or current["id"] != session_id:
            return False
        tick = time.monotonic()
        checkpoint(current, tick)
        current["updated_at"] = stamp()
        target = current["target_seconds"]
        if (
            current["state"] == "running"
            and target is not None
            and elapsed(current, tick) >= target
            and current["signal_state"] == "pending"
        ):
            # Serialize sound with stop/pause so a completed stop cannot emit a late chime.
            current["signal_state"] = "played"
            try:
                sound.play()
            except (OSError, RuntimeError, subprocess.SubprocessError) as error:
                current["signal_state"] = "failed"
                current["signal_error"] = str(error)
    return True


def worker(directory: Path, session_id: str) -> None:
    if sys.platform == "win32" and os.environ.get("TIMEPROBE_WIDGET") != "0":
        try:
            from timeprobe.win32_overlay import run

            run(directory, session_id)
            return
        except Exception as error:
            # A display failure must not discard the underlying measurement.
            with store.locked(directory) as data:
                current = data["current"]
                if current and current["id"] == session_id:
                    current.update(widget_state="failed", widget_error=str(error))
    while step(directory, session_id):
        time.sleep(0.1)
