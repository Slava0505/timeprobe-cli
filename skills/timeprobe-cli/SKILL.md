---
name: timeprobe-cli
description: Command reference for the timeprobe stopwatch, optional time target, desktop widget, and session history.
version: 0.2.1
---

# timeprobe CLI

## Setup

App repository: [Slava0505/timeprobe-cli](https://github.com/Slava0505/timeprobe-cli). Requires Windows, Python 3.10+, and Git.

If the bare `timeprobe` command isn't found, locate the existing clone and invoke its `.venv\Scripts\timeprobe.exe` by full path; don't assume the app is missing just because it isn't on `PATH`. If no clone exists, clone this repository into a permanent tools directory. In the clone, run `python -m venv .venv`, then `.venv\Scripts\python.exe -m pip install -e .`. Invoke `.venv\Scripts\timeprobe.exe` by path afterward; don't reinstall it for each session.

## Commands

Run commands without opening a visible console. Request structured output with `--json`.

| Command | Action |
| --- | --- |
| `timeprobe start --json` | Start a stopwatch |
| `timeprobe start --target 30m --json` | Start a session with a planned duration |
| `timeprobe status --json` | Read the current session |
| `timeprobe pause --json` | Freeze elapsed time |
| `timeprobe resume --json` | Continue the session |
| `timeprobe stop --json` | Finish, save the result, and close the widget |
| `timeprobe history --json` | Read completed and interrupted sessions from the last 24 hours, newest first |

Durations accept `90s`, `30m`, and `1h30m`; bare numbers mean minutes. A target plays one chime when reached, then the session keeps counting. Pauses are excluded from elapsed time and delay the chime. The widget opens automatically; its pause button controls the same session.

Only one session can be active. A second start returns `already_running` without replacing it. With no active session, `status` returns `state: idle`; control commands return `no_session`. Target changes, reset, and crash recovery aren't available.

JSON fields: `id`, `state`, `elapsed_seconds` (actual time excluding pauses), `target_seconds` (plan), `remaining_seconds`, and `overtime_seconds`. Durations are numeric seconds. Target fields are `null` for a plain stopwatch. History is returned in `sessions`; an `interrupted` entry contains the last checkpoint, not a complete measurement.

`ok: true` means success. On `ok: false`, read `error.code`. Exit code 1 means a session or storage error; 2 means invalid arguments. Input uses CLI arguments; `--json` selects the response format. Use `--help` for further options.
