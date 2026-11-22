"""Small, locked JSON store shared by CLI invocations and session workers."""

from __future__ import annotations

import contextlib
import ctypes
import json
import os
import tempfile
from collections.abc import Iterator
from pathlib import Path
from typing import Any


def state_dir() -> Path:
    override = os.environ.get("TIMEPROBE_STATE_DIR")
    if override:
        return Path(override).expanduser().resolve()
    return Path(os.environ.get("LOCALAPPDATA", Path.home() / "AppData/Local")) / "timeprobe"


def alive(pid: int | None) -> bool:
    if not pid:
        return False
    from ctypes import wintypes

    kernel = ctypes.WinDLL("kernel32", use_last_error=True)
    kernel.OpenProcess.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.DWORD]
    kernel.OpenProcess.restype = wintypes.HANDLE
    kernel.GetExitCodeProcess.argtypes = [wintypes.HANDLE, ctypes.POINTER(wintypes.DWORD)]
    kernel.CloseHandle.argtypes = [wintypes.HANDLE]
    handle = kernel.OpenProcess(0x1000, False, pid)
    if not handle:
        return False
    try:
        code = wintypes.DWORD()
        return bool(kernel.GetExitCodeProcess(handle, ctypes.byref(code))) and code.value == 259
    finally:
        kernel.CloseHandle(handle)


@contextlib.contextmanager
def locked(directory: Path) -> Iterator[dict[str, Any]]:
    import msvcrt

    directory.mkdir(parents=True, exist_ok=True)
    with (directory / "state.lock").open("a+b") as lock:
        lock.seek(0, os.SEEK_END)
        if lock.tell() == 0:
            lock.write(b"\0")
            lock.flush()
        lock.seek(0)
        msvcrt.locking(lock.fileno(), msvcrt.LK_LOCK, 1)
        try:
            path = directory / "state.json"
            data = (
                json.loads(path.read_text(encoding="utf-8"))
                if path.exists()
                else {"current": None, "history": []}
            )
            yield data
            fd, temporary = tempfile.mkstemp(prefix="state-", suffix=".json", dir=directory)
            try:
                with os.fdopen(fd, "w", encoding="utf-8") as stream:
                    json.dump(data, stream, indent=2)
                    stream.write("\n")
                os.replace(temporary, path)
            finally:
                Path(temporary).unlink(missing_ok=True)
        finally:
            lock.seek(0)
            msvcrt.locking(lock.fileno(), msvcrt.LK_UNLCK, 1)
