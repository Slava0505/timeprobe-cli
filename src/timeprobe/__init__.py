"""A stopwatch CLI with an optional time target."""

from __future__ import annotations

from importlib.metadata import PackageNotFoundError, version

try:
    __version__ = version("timeprobe-cli")
except PackageNotFoundError:
    __version__ = "0.0.0+source"
