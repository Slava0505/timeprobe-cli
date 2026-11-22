"""Duration helpers adapted from chime-cli (MIT)."""

from __future__ import annotations

import math
import re

_DURATION_UNITS = {"s": 1, "m": 60, "h": 3600, "d": 86400}
_DURATION_PATTERN = re.compile(r"(\d+(?:\.\d+)?)([smhd])")
_BARE_NUMBER = re.compile(r"\d+(\.\d+)?")


def parse_duration(s: str) -> float:
    """Parse '10m', '1h30m', '90s', '0.5h'. Bare number = minutes."""
    s = s.strip().lower().replace(" ", "")
    if not s:
        raise ValueError("empty duration")
    if _BARE_NUMBER.fullmatch(s):
        return _positive(float(s) * 60)
    total = 0.0
    pos = 0
    matched = False
    for m in _DURATION_PATTERN.finditer(s):
        if m.start() != pos:
            raise ValueError(f"can't parse duration: {s}")
        total += float(m.group(1)) * _DURATION_UNITS[m.group(2)]
        pos = m.end()
        matched = True
    if not matched or pos != len(s):
        raise ValueError(f"can't parse duration: {s}")
    return _positive(total)


def fmt_clock(sec: float) -> str:
    sec = max(0, round(sec))
    h, rem = divmod(sec, 3600)
    m, s = divmod(rem, 60)
    return f"{h:02d}:{m:02d}:{s:02d}" if h else f"{m:02d}:{s:02d}"


def _positive(value: float) -> float:
    if not math.isfinite(value) or value <= 0:
        raise ValueError("duration must be positive and finite")
    return value
