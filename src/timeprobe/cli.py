"""Short commands and JSON responses for agent-controlled measurements."""

from __future__ import annotations

import argparse
import json
import math
import sys
from typing import Any

from timeprobe import __version__, engine, store
from timeprobe.model import SessionError
from timeprobe.parsers import fmt_clock, parse_duration


def positive_duration(value: str) -> float:
    try:
        return parse_duration(value)
    except ValueError as error:
        raise argparse.ArgumentTypeError(str(error)) from error


def positive_scale(value: str) -> float:
    scale = float(value)
    if not math.isfinite(scale) or scale <= 0:
        raise argparse.ArgumentTypeError("scale must be a finite number greater than zero")
    return scale


def parser() -> argparse.ArgumentParser:
    root = argparse.ArgumentParser(prog="timeprobe", description="Measure one session at a time.")
    root.add_argument("--version", action="version", version=f"timeprobe {__version__}")
    root.add_argument("--json", action="store_true", help="return structured output")
    commands = root.add_subparsers(dest="command", required=True)
    for name in ("start", "status", "pause", "resume", "stop", "history"):
        command = commands.add_parser(name)
        command.add_argument("--json", action="store_true", default=argparse.SUPPRESS)
        if name == "start":
            command.add_argument(
                "--visible",
                action="store_true",
                help="show the timer immediately instead of its edge tab",
            )
            command.add_argument(
                "--scale",
                type=positive_scale,
                default=1.0,
                help="widget size multiplier (default: 1)",
            )
            command.add_argument(
                "--target", type=positive_duration, help="planned duration, e.g. 30m"
            )
    return root


def render(result: dict[str, Any]) -> str:
    if "sessions" in result:
        return "\n".join(render(s) for s in result["sessions"]) or "No recent sessions."
    if result["state"] == "idle":
        return "No active session."
    text = f"{result['state']}: {fmt_clock(result['elapsed_seconds'])} elapsed"
    if result["target_seconds"] is not None:
        text += f"; target {fmt_clock(result['target_seconds'])}"
        if result["target_reached"]:
            text += f"; overtime {fmt_clock(result['overtime_seconds'])}"
        else:
            text += f"; remaining {fmt_clock(result['remaining_seconds'])}"
    if result["signal_state"] == "failed":
        text += f"; sound failed: {result['signal_error']}"
    return text


def main(argv: list[str] | None = None) -> int:
    arguments = list(sys.argv[1:] if argv is None else argv)
    if sys.platform != "win32":
        error = {"ok": False, "error": {"code": "unsupported_platform", "message": "Windows only."}}
        print(json.dumps(error) if "--json" in arguments else "Windows only.")
        return 1
    if len(arguments) == 2 and arguments[0] == "_worker":
        engine.worker(store.state_dir(), arguments[1])
        return 0
    wants_json = "--json" in arguments
    try:
        args = parser().parse_args(arguments)
    except SystemExit as error:
        if error.code and wants_json:
            print(json.dumps({"ok": False, "error": {"code": "invalid_arguments"}}))
        return int(error.code or 0)
    try:
        directory = store.state_dir()
        result = engine.execute(
            args.command,
            directory,
            getattr(args, "target", None),
            getattr(args, "scale", 1.0),
            getattr(args, "visible", False),
        )
        if args.json:
            print(json.dumps({"ok": True, **result}))
        else:
            print(render(result))
        return 0
    except SessionError as error:
        payload = {"ok": False, "error": {"code": error.code, "message": str(error)}}
        if hasattr(error, "session"):
            payload["session"] = error.session
        print(json.dumps(payload) if args.json else str(error))
        return 1
    except (OSError, ValueError) as error:
        payload = {"ok": False, "error": {"code": "storage_error", "message": str(error)}}
        print(json.dumps(payload) if args.json else str(error))
        return 1
