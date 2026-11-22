---
name: time-tracking
description: Use when the user asks to set a timer, start a stopwatch, check elapsed time, or finish and record a session.
version: 0.1.1
---

1. Use only timeprobe for timers and stopwatches. Read the [timeprobe-cli](../timeprobe-cli/SKILL.md) skill first; get commands and limitations from it.
2. Start a stopwatch without a target, or a timer with the requested planned duration. Reaching the target doesn't end the activity.
3. The user can pause and resume the widget directly. Take actual duration from the session state or its history entry, not message timestamps, calendar differences, or the planned duration.
4. When asked to finish, pause the session and record its actual duration where the current task requires; if no destination is specified, report it in chat. Preserve precision when converting seconds. If the session has already ended, use the history entry for that activity. Don't invent the missing part of an interrupted measurement.
5. Finish the active session and close the widget at the end, whether recording succeeds or fails. Report a recording failure.
