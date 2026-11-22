from __future__ import annotations

import io
import wave
from datetime import datetime, timedelta, timezone

import pytest

from timeprobe import engine, sound, store
from timeprobe.model import SessionError
from timeprobe.parsers import parse_duration


@pytest.fixture
def session(tmp_path, monkeypatch):
    clock = [1000.0]
    monkeypatch.setattr(engine.time, "monotonic", lambda: clock[0])
    monkeypatch.setattr(engine, "spawn", lambda *_: 12345)
    monkeypatch.setattr(store, "alive", lambda _: True)
    return tmp_path, clock


def test_pause_resume_and_final_history(session):
    directory, clock = session
    started = engine.execute("start", directory)
    clock[0] += 10
    paused = engine.execute("pause", directory)
    assert paused["elapsed_seconds"] == 10
    clock[0] += 500
    assert engine.execute("status", directory)["elapsed_seconds"] == 10
    assert engine.execute("pause", directory)["elapsed_seconds"] == 10
    engine.execute("resume", directory)
    clock[0] += 4
    engine.execute("resume", directory)
    clock[0] += 1
    stopped = engine.execute("stop", directory)
    assert stopped["elapsed_seconds"] == 15
    assert stopped["state"] == "stopped"
    assert stopped["id"] == started["id"]
    assert engine.execute("status", directory) == {"state": "idle"}
    assert engine.execute("history", directory)["sessions"] == [stopped]


def test_duplicate_start_preserves_original(session):
    directory, clock = session
    first = engine.execute("start", directory, 1800)
    clock[0] += 42
    with pytest.raises(SessionError, match="already active") as caught:
        engine.execute("start", directory, 60)
    assert caught.value.code == "already_running"
    assert caught.value.session["id"] == first["id"]
    assert caught.value.session["elapsed_seconds"] == 42
    assert caught.value.session["target_seconds"] == 1800


def test_target_sound_once_pause_delays_it_and_overtime_continues(session, monkeypatch):
    directory, clock = session
    plays = []
    monkeypatch.setattr(sound, "play", lambda: plays.append(clock[0]))
    started = engine.execute("start", directory, 1800)
    clock[0] += 1200
    engine.execute("pause", directory)
    clock[0] += 600
    engine.step(directory, started["id"])
    assert plays == []
    engine.execute("resume", directory)
    clock[0] += 600
    engine.step(directory, started["id"])
    assert plays == [3400]
    clock[0] += 720
    engine.step(directory, started["id"])
    assert len(plays) == 1
    stopped = engine.execute("stop", directory)
    assert stopped["elapsed_seconds"] == 2520
    assert stopped["overtime_seconds"] == 720
    assert stopped["remaining_seconds"] == 0
    assert stopped["target_reached"] is True
    assert stopped["signal_state"] == "played"


def test_stop_cancels_pending_sound_and_old_worker_cannot_touch_new_session(session, monkeypatch):
    directory, clock = session
    plays = []
    monkeypatch.setattr(sound, "play", lambda: plays.append(True))
    first = engine.execute("start", directory, 30)
    clock[0] += 5
    assert engine.execute("stop", directory)["elapsed_seconds"] == 5
    second = engine.execute("start", directory)
    clock[0] += 100
    assert engine.step(directory, first["id"]) is False
    assert engine.execute("status", directory)["id"] == second["id"]
    assert plays == []


def test_sound_failure_does_not_stop_measurement(session, monkeypatch):
    directory, clock = session

    def fail():
        raise OSError("no audio device")

    monkeypatch.setattr(sound, "play", fail)
    started = engine.execute("start", directory, 1)
    clock[0] += 2
    engine.step(directory, started["id"])
    current = engine.execute("status", directory)
    assert current["state"] == "running"
    assert current["signal_state"] == "failed"
    assert current["signal_error"] == "no audio device"


def test_interrupted_worker_is_archived_without_counting_downtime(session, monkeypatch):
    directory, clock = session
    started = engine.execute("start", directory)
    clock[0] += 7
    engine.step(directory, started["id"])
    monkeypatch.setattr(store, "alive", lambda _: False)
    clock[0] += 500
    assert engine.execute("status", directory) == {"state": "idle"}
    old = engine.execute("history", directory)["sessions"][0]
    assert old["state"] == "interrupted"
    assert old["elapsed_seconds"] == 7


def test_history_prunes_old_results(session):
    directory, _ = session
    engine.execute("start", directory)
    engine.execute("stop", directory)
    with store.locked(directory) as data:
        data["history"][0]["ended_at"] = (
            datetime.now(timezone.utc) - timedelta(days=2)
        ).isoformat()
    assert engine.execute("history", directory) == {"sessions": []}


@pytest.mark.parametrize("action", ["pause", "resume", "stop"])
def test_no_session_error(session, action):
    with pytest.raises(SessionError) as caught:
        engine.execute(action, session[0])
    assert caught.value.code == "no_session"


@pytest.mark.parametrize(
    "value,expected", [("30m", 1800), ("1h30m", 5400), ("0.5m", 30), ("2", 120)]
)
def test_duration(value, expected):
    assert parse_duration(value) == expected


@pytest.mark.parametrize("value", ["0", "0s", "-1m", "nan", "inf", "1mfoo", "", "9" * 400])
def test_invalid_duration(value):
    with pytest.raises(ValueError):
        parse_duration(value)


def test_quiet_sound_is_short_mono_wav():
    with wave.open(io.BytesIO(sound.chime_bytes()), "rb") as audio:
        assert audio.getnchannels() == 1
        assert audio.getsampwidth() == 2
        assert audio.getnframes() / audio.getframerate() < 1
