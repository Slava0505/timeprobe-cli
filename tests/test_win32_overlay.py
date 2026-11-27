"""Exercise the real native window, including its dimensions and corner anchor."""

from __future__ import annotations

import ctypes as c
import json
import os
import subprocess
import sys
import time
from ctypes import wintypes as w

import pytest

from timeprobe import engine, store

pytestmark = pytest.mark.skipif(sys.platform != "win32", reason="Native Windows widget")


def test_drag_reuses_native_surface_and_skips_unchanged_frames(tmp_path, monkeypatch):
    from timeprobe.win32_overlay import Overlay

    monkeypatch.setattr(engine, "spawn", lambda *_: os.getpid())
    session = engine.execute("start", tmp_path, visible=True)
    overlay = Overlay(tmp_path, session["id"])
    overlay.show = lambda *_: True

    def inspect(*_):
        surface = overlay.surface
        layer = overlay.layer
        calls = []
        overlay.layer = lambda *args: calls.append(args) or layer(*args)
        overlay.dib = lambda *_: pytest.fail("Dragging must reuse the existing bitmap")
        overlay.present()
        assert not calls
        overlay.dragging = True
        for dx in range(1, 80):
            overlay.drag_position = overlay.position[0] + dx, overlay.position[1]
            overlay.present()
            assert overlay.surface is surface
            assert overlay.surface_image is overlay.image
        assert len(calls) == 79
        assert c.string_at(surface[4], len(overlay.image)) == overlay.image
        overlay.dragging = False
        return 0

    overlay.get_message = inspect
    overlay.start()
    assert overlay.surface is None
    assert overlay.frame_timer is None


@pytest.mark.parametrize("close_during_animation", [False, True])
def test_high_resolution_message_pump_animates_and_still_dispatches_input(
    tmp_path, monkeypatch, close_during_animation
):
    from timeprobe.win32_overlay import Overlay, api

    monkeypatch.setattr(engine, "spawn", lambda *_: os.getpid())
    session = engine.execute("start", tmp_path, visible=True)
    overlay = Overlay(tmp_path, session["id"])
    overlay.show = lambda *_: True
    get_message = overlay.get_message
    dispatched = []
    dispatch = overlay.dispatch
    post = api(overlay.user, "PostMessageW", w.BOOL, w.HWND, w.UINT, w.WPARAM, w.LPARAM)
    started = False

    def get(*args):
        nonlocal started
        if not started:
            started = True
            overlay.set_hidden(True)
            assert post(overlay.window, 0x8001, 0, 0)
            if close_during_animation:
                assert post(overlay.window, 0x10, 0, 0)
        elif overlay.animation is None and not close_during_animation:
            assert overlay.reveal == 0
            assert 0x8001 in dispatched
            return 0
        return get_message(*args)

    def record(message):
        dispatched.append(c.cast(message, c.POINTER(w.MSG)).contents.message)
        return dispatch(message)

    # Other native tests can leave WM_QUIT in this thread's queue.
    message = w.MSG()
    while overlay.peek_message(c.byref(message), None, 0x12, 0x12, 1):
        pass
    overlay.get_message = get
    overlay.dispatch = record
    overlay.start()
    assert overlay.failure is None
    assert overlay.animation is None
    assert 0x8001 in dispatched
    assert overlay.frame_timer is None


def test_paused_and_running_digits_have_the_same_brightness(tmp_path, monkeypatch):
    from timeprobe.win32_overlay import Overlay

    monkeypatch.setattr(engine, "spawn", lambda *_: os.getpid())
    session = engine.execute("start", tmp_path, visible=True)
    overlay = Overlay(tmp_path, session["id"])
    overlay.show = lambda *_: True

    def compare(*_):
        overlay.hovered = False
        overlay.paint("00:42", False)
        running = overlay.image
        overlay.paint("00:42", True)
        assert overlay.image == running
        overlay.hovered = True
        overlay.paint("00:42", True)
        assert overlay.image != running
        return 0

    overlay.get_message = compare
    overlay.start()


@pytest.mark.parametrize("paused", [False, True])
def test_double_click_cancels_single_click_and_ignores_trailing_events(
    tmp_path, monkeypatch, paused
):
    from timeprobe.win32_overlay import Overlay

    monkeypatch.setattr(engine, "spawn", lambda *_: os.getpid())
    session = engine.execute("start", tmp_path, visible=True)
    if paused:
        engine.execute("pause", tmp_path)
    expected = "paused" if paused else "running"
    overlay = Overlay.__new__(Overlay)
    overlay.directory, overlay.session_id = tmp_path, session["id"]
    overlay.window = 1
    overlay.hidden = False
    overlay.pending_click = expected
    overlay.click_deadline = time.monotonic() - 1
    overlay.normal_frame = None
    overlay.reveal = 1
    overlay.dragging = False
    killed = []
    overlay.kill_timer = lambda *args: killed.append(args)
    overlay.timer = lambda *_: 1
    overlay.release_capture = lambda: None
    overlay.refresh = lambda: True
    overlay.destroy = lambda *_: pytest.fail(f"Window callback failed: {overlay.failure}")
    overlay.procedure(1, 0x203, 1, 70)
    overlay.procedure(1, 0x202, 0, 70)
    overlay.procedure(1, 0x113, 2, 0)
    result = engine.execute("status", tmp_path)
    assert result["state"] == expected
    assert result["widget_hidden"] is True
    assert overlay.pending_click is None
    assert killed == [(1, 2)]


def test_animation_uses_cached_frames_without_session_io(monkeypatch):
    from timeprobe import win32_overlay as native

    overlay = native.Overlay.__new__(native.Overlay)
    overlay.animation = (100.0, 0.0)
    overlay.hidden = False
    overlay.dragging = False
    overlay.reveal = 0
    overlay.window = 1
    overlay.previous = "old frame"
    frames = []
    timers = []
    overlay.present = lambda: frames.append(overlay.reveal)
    overlay.timer = lambda *args: timers.append(args)
    overlay.paint = lambda *_: pytest.fail("Animation must not rasterize the panel")
    monkeypatch.setattr(
        engine, "step", lambda *_: pytest.fail("Animation must not write session state")
    )
    clock = [100.0]
    monkeypatch.setattr(native.time, "monotonic", lambda: clock[0])
    for index in range(18):
        clock[0] = 100 + index * 0.016
        assert overlay.refresh() is True
        if overlay.animation is None:
            break
    assert len(frames) >= 16
    assert frames == sorted(frames)
    assert frames[0] == 0 and frames[-1] == 1
    assert overlay.animation is None
    assert timers[-1] == (1, 1, 100, None)


@pytest.mark.parametrize("hidden,delta,expected", [(True, -40, False), (False, 40, True)])
def test_dragging_tab_changes_visibility_without_pausing(
    tmp_path, monkeypatch, hidden, delta, expected
):
    from timeprobe.win32_overlay import Overlay

    monkeypatch.setattr(engine, "spawn", lambda *_: os.getpid())
    session = engine.execute("start", tmp_path, visible=not hidden)
    overlay = Overlay.__new__(Overlay)
    overlay.directory, overlay.session_id = tmp_path, session["id"]
    overlay.window = 1
    overlay.scale = overlay.dpi_scale = 1
    overlay.hidden = hidden
    overlay.reveal = 0 if hidden else 1
    overlay.normal_frame = None
    overlay.pending_click = None
    overlay.position = (839, 44)
    overlay.full_width = 152
    overlay.handle_width = 24
    overlay.drag_position = None
    overlay.panel_offset = 28
    overlay.dragging = overlay.hovered = False
    overlay.capture = overlay.release_capture = lambda *_: None
    overlay.timer = lambda *_: 1
    overlay.refresh = lambda: True
    overlay.destroy = lambda *_: pytest.fail(f"Window callback failed: {overlay.failure}")
    pointer = [100]

    def cursor(destination):
        point = c.cast(destination, c.POINTER(w.POINT)).contents
        point.x, point.y = pointer[0], 100

    overlay.cursor_position = cursor

    def work_area(_, __, destination, ___):
        area = c.cast(destination, c.POINTER(w.RECT)).contents
        area.left, area.top, area.right, area.bottom = 0, 0, 1000, 800
        return True

    overlay.work_area = work_area
    location = 10 if hidden else 70
    overlay.procedure(1, 0x201, 1, location)
    pointer[0] += delta
    overlay.procedure(1, 0x200, 1, location)
    expected_x = (972 if hidden else 839) + delta
    assert overlay.drag_position == (expected_x, 44)
    assert overlay.animation is None
    overlay.procedure(1, 0x202, 0, location)
    assert overlay.drag_position is None
    assert overlay.hidden is expected
    status = engine.execute("status", tmp_path)
    assert status["widget_hidden"] is expected
    assert status["state"] == "running"


def test_dragged_window_follows_pointer_and_clips_only_at_screen_edge(tmp_path, monkeypatch):
    from timeprobe.win32_overlay import Overlay, api

    monkeypatch.setattr(engine, "spawn", lambda *_: os.getpid())
    session = engine.execute("start", tmp_path, visible=True)
    overlay = Overlay(tmp_path, session["id"])
    overlay.show = lambda *_: True
    get_rect = api(overlay.user, "GetWindowRect", w.BOOL, w.HWND, c.POINTER(w.RECT))

    def inspect(*_):
        area = w.RECT()
        assert overlay.work_area(0x30, 0, c.byref(area), 0)
        overlay.dragging = True
        start_x = area.right - overlay.panel_offset - 60
        for dx, dy in [(0, 0), (17, 9), (-11, -7), (80, 13)]:
            overlay.drag_position = start_x + dx, overlay.position[1] + dy
            overlay.present()
            bounds = w.RECT()
            assert get_rect(overlay.window, c.byref(bounds))
            assert bounds.left == start_x + dx
            assert bounds.top == overlay.position[1] + dy
            assert bounds.right == area.right
        overlay.drag_position = area.right + 10, overlay.position[1]
        overlay.present()
        bounds = w.RECT()
        assert get_rect(overlay.window, c.byref(bounds))
        assert bounds.left == area.right - 1 and bounds.right == area.right
        overlay.dragging = False
        return 0

    overlay.get_message = inspect
    overlay.start()


@pytest.mark.parametrize("scale", [1, 4, 1.5])
@pytest.mark.parametrize("visible", [False, True])
def test_native_window_scale_and_top_right_anchor(tmp_path, scale, visible):
    from timeprobe.win32_overlay import api

    user = c.WinDLL("user32", use_last_error=True)
    awareness = api(user, "SetThreadDpiAwarenessContext", c.c_void_p, c.c_void_p)
    previous_awareness = awareness(c.c_void_p(-4))
    find = api(user, "FindWindowW", w.HWND, w.LPCWSTR, w.LPCWSTR)
    rect = api(user, "GetWindowRect", w.BOOL, w.HWND, c.POINTER(w.RECT))
    send = api(user, "SendMessageW", c.c_ssize_t, w.HWND, w.UINT, w.WPARAM, w.LPARAM)
    environment = {**os.environ, "TIMEPROBE_STATE_DIR": str(tmp_path), "TIMEPROBE_WIDGET": "1"}

    def invoke(*args):
        result = subprocess.run(
            [sys.executable, "-m", "timeprobe", *args, "--json"],
            env=environment,
            capture_output=True,
            text=True,
            timeout=15,
        )
        assert result.returncode == 0, result.stdout + result.stderr
        return json.loads(result.stdout)

    pid = None
    try:
        session = invoke("start", "--scale", str(scale), *(["--visible"] if visible else []))
        with store.locked(tmp_path) as data:
            pid = data["current"]["worker_pid"]
        deadline = time.monotonic() + 15
        while time.monotonic() < deadline:
            status = invoke("status")
            assert status.get("widget_state") != "failed", status
            if status.get("widget_state") == "visible":
                break
            time.sleep(0.1)
        else:
            pytest.fail(f"Widget did not become visible: {status}")

        window = find(f"timeprobe-{session['id']}", None)
        assert window
        assert api(user, "GetClassLongW", w.DWORD, w.HWND, c.c_int)(window, -26) & 0x0008
        bounds, area = w.RECT(), w.RECT()
        assert rect(window, c.byref(bounds))
        assert api(user, "SystemParametersInfoW", w.BOOL, w.UINT, w.UINT, c.c_void_p, w.UINT)(
            0x30, 0, c.byref(area), 0
        )
        dpi = api(user, "GetDpiForSystem", w.UINT)() / 96
        full_width = round(124 * dpi * scale) + round(24 * dpi * scale) + round(4 * dpi * scale)
        handle_width = round(24 * dpi * scale)
        hidden_right = area.right - round(4 * dpi * scale)
        assert bounds.right - bounds.left == (full_width if visible else handle_width)
        assert bounds.bottom - bounds.top == round(48 * dpi * scale)
        assert bounds.right == (area.right - round(9 * dpi) if visible else hidden_right)
        assert bounds.top == area.top + round(44 * dpi)

        def click(x):
            location = x | (round(24 * dpi * scale) << 16)
            send(window, 0x201, 1, location)
            send(window, 0x202, 0, location)

        def double_click():
            location = round(70 * dpi * scale) | (round(24 * dpi * scale) << 16)
            send(window, 0x201, 1, location)
            send(window, 0x202, 0, location)
            send(window, 0x203, 1, location)
            send(window, 0x202, 0, location)

        def wait_width(expected):
            deadline = time.monotonic() + 10
            expected_right = (
                hidden_right if expected == handle_width else area.right - round(9 * dpi)
            )
            while time.monotonic() < deadline:
                assert rect(window, c.byref(bounds))
                if bounds.right - bounds.left == expected and bounds.right == expected_right:
                    return
                time.sleep(0.05)
            pytest.fail(f"Expected width {expected}, got {bounds.right - bounds.left}")

        if visible:
            double_click()
            wait_width(handle_width)
        hidden_status = invoke("status")
        assert hidden_status["widget_hidden"] is True
        assert hidden_status["state"] == "running"
        assert bounds.right == hidden_right
        click(round(10 * dpi * scale))
        wait_width(full_width)
        shown = invoke("status")
        assert shown["widget_hidden"] is False
        assert shown["id"] == session["id"]
        assert shown["elapsed_seconds"] > hidden_status["elapsed_seconds"]
        assert bounds.right == area.right - round(9 * dpi)
        double_click()
        wait_width(handle_width)
        assert invoke("status")["state"] == "running"
        click(round(10 * dpi * scale))
        wait_width(full_width)
        assert invoke("status")["state"] == "running"
        click(round(70 * dpi * scale))
        deadline = time.monotonic() + 10
        while invoke("status")["state"] != "paused":
            assert time.monotonic() < deadline, "Single click did not pause"
            time.sleep(0.05)
        send(window, 0x200, 0, round(70 * dpi * scale) | (round(24 * dpi * scale) << 16))
        assert invoke("status")["widget_state"] == "visible"
        double_click()
        wait_width(handle_width)
        assert invoke("status")["state"] == "paused"
        assert invoke("resume")["state"] == "running"
    finally:
        try:
            invoke("stop")
            deadline = time.monotonic() + 10
            while pid and store.alive(pid) and time.monotonic() < deadline:
                time.sleep(0.1)
            assert not pid or not store.alive(pid), "Widget worker did not stop"
            assert not find(f"timeprobe-{session['id']}", None), "Widget window did not close"
        finally:
            awareness(previous_awareness)
