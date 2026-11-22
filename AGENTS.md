# Working on timeprobe-cli

- Keep one active session. Reaching a target must not stop elapsed-time tracking.
- Keep runtime dependencies empty and new filenames lowercase.
- Keep arithmetic in model.py, storage in store.py, process/audio effects in
  engine.py and sound.py, and command output in cli.py.
- Use monotonic time for durations and UTC timestamps for history.
- Run `make lint` and `make test` before reporting completion. On Windows pass
  `PY=.venv/Scripts/python.exe` to use the project environment.
- Isolate test state with TIMEPROBE_STATE_DIR and mock audio in automated tests.
- Never publish local state. Keep public docs and examples generic.
- Preserve the upstream MIT notice. Do not publish package releases without a request.
