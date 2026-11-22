# timeprobe-cli

A Windows stopwatch CLI with a compact pixel overlay. One active session, an
optional time target, pause/resume, and a short local history. Reaching the target
plays one quiet chime; the measurement continues until stopped.

Derived from [chime-cli](https://github.com/MaVericKWareZ/chime) under the MIT license.
Duration parsing is adapted from the upstream project. Alarms, countdown commands,
Pomodoro, speech, desktop notifications, and process monitoring have been removed.

## Install

Windows only. Requires Python 3.10 or later. There are no runtime dependencies.
Desktop behavior tested on Windows 10 Pro 22H2, build 19045.6575, x64,
with Python 3.14.6.

```console
python -m pip install -e .
```

## Commands

```console
timeprobe start --target 30m --json
timeprobe status --json
timeprobe pause --json
timeprobe resume --json
timeprobe stop --json
timeprobe history --json
```

Omit `--target` for a plain stopwatch. Durations accept `90s`, `30m`, `1h30m`,
and fractional units. A bare number is minutes. Targets must be positive.

Only `start` creates a session. A second start fails with `already_running` and
returns the existing session unchanged. Stop it explicitly before starting again.
Pausing an already paused session and resuming an already running session are harmless.
Pauses do not count toward elapsed time or the target. Stopping a session also
cancels a pending sound. No target adjustment, reset, or automatic repetition is provided.

## Desktop widget

Starting a session automatically shows an always-on-top rectangle at the upper
right of the primary display, below the window close-button area. It contains only
Tiny5 pixel digits: sage `#d8e6c9` on a 76% opaque `#161d19` background.
No browser, internet connection, font installation, or taskbar item is needed.

Without a target it counts up. With a target it counts down, then shows overtime
with a plus sign. The normal size is 124 by 48 logical pixels. It expands for hours
and keeps that width until the session ends. Windows display scaling is respected.

Hover to reveal pause; click to pause. Hover again and click the play icon to
resume. Drag anywhere on the widget to move it; a drag does not toggle pause.
The position is retained for the current session. Visible digits are centered by
their actual pixel bounds rather than the font's line metrics.
The same session is controlled by the CLI and the widget. The widget does
not take keyboard focus. `stop` saves the result and closes the widget.
Its worker uses `pythonw.exe` when available and hidden process flags, without
opening a console window.

For automation without a desktop widget, set `TIMEPROBE_WIDGET=0` before starting.
If the widget cannot open, the session continues; `status --json` reports
`widget_state: "failed"` with `widget_error`. A visible widget reports
`widget_state: "visible"`.

## Agent output

Use `--json` before or after the command. Standard output contains one JSON object.
Success has `ok: true`; errors have `ok: false` and an `error.code`.
Exit codes: 0 for success, 1 for a session/storage error, 2 for invalid arguments.
Argument usage diagnostics go to standard error.

Session responses contain an `id`, `state`, UTC timestamps, `elapsed_seconds`,
`target_seconds`, `remaining_seconds`, `overtime_seconds`, `target_reached`, and
`signal_state`. Duration fields are numeric seconds; absent target fields are null.
Signal states are `disabled`, `pending`, `played`, or `failed`. Playback failure
does not stop the measurement and is reported in `signal_error`.

At a 30-minute target, a session stopped after 42 active minutes reports 2520
elapsed seconds and 720 overtime seconds. Stop returns the final result and
stores it, so a separate read immediately before stop is unnecessary.

With no active session, `status` returns `{"ok": true, "state": "idle"}`.
`history` returns `{"ok": true, "sessions": [...]}`, newest first.

## Process and storage

Each session starts a small detached worker, not an installed service. Commands
return immediately; the worker checkpoints the measurement and plays the optional
sound. Closing the invoking shell does not intentionally stop the session. Use
`stop` to finish it. Killing the worker or rebooting does not restore the session:
the next command archives it as interrupted at its last checkpoint.

Elapsed time uses a monotonic clock. System sleep is counted where the operating
system's monotonic clock includes it; no wake-from-sleep alarm is provided.
No sound can play while the computer is suspended or off.

State and completed sessions are stored in one local JSON file. History is kept
for the last 24 hours and pruned on command execution. On Windows the directory is
`%LOCALAPPDATA%\timeprobe`. Set `TIMEPROBE_STATE_DIR` to use an isolated directory,
including during tests. Files are locked across commands and replaced atomically.

The generated sound has low amplitude and plays once. Perceived volume still
depends on the system's audio settings. No notification or spoken message is shown.

## Development

```console
python -m pip install -e ".[dev]"
python -m ruff check .
python -m ruff format --check .
python -m pytest
python -m build
```

`make lint` and `make test` are equivalent shortcuts. The suite includes real CLI
subprocesses in temporary state directories. Automated sound tests use a fake
player; manually check actual audio with `timeprobe start --target 2s`, then
`timeprobe status` and `timeprobe stop`.

The bundled Tiny5 font is distributed under the SIL Open Font License; its notice
is included in `src/timeprobe/assets/ofl.txt`. Source: the Google Fonts repository,
`ofl/tiny5`. The upstream chime-cli MIT notice remains in `LICENSE`.
