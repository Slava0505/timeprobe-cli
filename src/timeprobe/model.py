"""Session arithmetic. Calendar timestamps never determine elapsed time."""

from __future__ import annotations

from typing import Any


class SessionError(Exception):
    def __init__(self, code: str, message: str):
        super().__init__(message)
        self.code = code


def elapsed(session: dict[str, Any], tick: float) -> float:
    value = session["elapsed_seconds"]
    if session["state"] == "running":
        value += max(0.0, tick - session["running_since"])
    return value


def checkpoint(session: dict[str, Any], tick: float) -> None:
    session["elapsed_seconds"] = elapsed(session, tick)
    if session["state"] == "running":
        session["running_since"] = tick


def snapshot(session: dict[str, Any], tick: float) -> dict[str, Any]:
    result = {k: v for k, v in session.items() if k not in {"running_since", "worker_pid"}}
    actual = elapsed(session, tick)
    target = session["target_seconds"]
    result.update(
        elapsed_seconds=round(actual, 3),
        remaining_seconds=None if target is None else round(max(0.0, target - actual), 3),
        overtime_seconds=None if target is None else round(max(0.0, actual - target), 3),
        target_reached=target is not None and actual >= target,
    )
    return result


def transition(session: dict[str, Any], action: str, tick: float, stamp: str) -> None:
    if action == "pause":
        if session["state"] == "running":
            checkpoint(session, tick)
            session["state"] = "paused"
    elif action == "resume":
        if session["state"] == "paused":
            session["running_since"] = tick
            session["state"] = "running"
    elif action == "stop":
        checkpoint(session, tick)
        session.update(state="stopped", ended_at=stamp)
