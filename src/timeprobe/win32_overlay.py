"""Small, non-activating Windows overlay with per-pixel alpha. No GUI dependencies."""

from __future__ import annotations

import ctypes as c
import time
from ctypes import wintypes as w
from pathlib import Path

from timeprobe import engine, store
from timeprobe.model import snapshot
from timeprobe.overlay import (
    PanelRenderer,
    center_ink,
    display_time,
    triangle_coverage,
)

LRESULT = c.c_ssize_t
WNDPROC = c.WINFUNCTYPE(LRESULT, w.HWND, w.UINT, w.WPARAM, w.LPARAM)


class WindowClass(c.Structure):
    _fields_ = [
        ("style", w.UINT),
        ("procedure", WNDPROC),
        ("class_extra", c.c_int),
        ("window_extra", c.c_int),
        ("instance", w.HINSTANCE),
        ("icon", w.HICON),
        ("cursor", w.HANDLE),
        ("background", w.HBRUSH),
        ("menu", w.LPCWSTR),
        ("name", w.LPCWSTR),
    ]


class BitmapHeader(c.Structure):
    _fields_ = [
        ("size", w.DWORD),
        ("width", w.LONG),
        ("height", w.LONG),
        ("planes", w.WORD),
        ("bits", w.WORD),
        ("compression", w.DWORD),
        ("image_size", w.DWORD),
        ("x_pixels", w.LONG),
        ("y_pixels", w.LONG),
        ("colors", w.DWORD),
        ("important", w.DWORD),
    ]


class BitmapInfo(c.Structure):
    _fields_ = [("header", BitmapHeader), ("colors", w.DWORD * 1)]


class Blend(c.Structure):
    _fields_ = [("operation", w.BYTE), ("flags", w.BYTE), ("alpha", w.BYTE), ("format", w.BYTE)]


class MouseTracking(c.Structure):
    _fields_ = [("size", w.DWORD), ("flags", w.DWORD), ("window", w.HWND), ("hover", w.DWORD)]


def api(library, name, result, *arguments):
    function = getattr(library, name)
    function.restype = result
    function.argtypes = list(arguments)
    return function


class Overlay:
    def __init__(self, directory: Path, session_id: str):
        self.directory, self.session_id = directory, session_id
        self.user = c.WinDLL("user32", use_last_error=True)
        self.gdi = c.WinDLL("gdi32", use_last_error=True)
        kernel = self.kernel = c.WinDLL("kernel32", use_last_error=True)
        self.instance = api(kernel, "GetModuleHandleW", w.HMODULE, w.LPCWSTR)(None)
        self.configure_api()
        # DPI awareness belongs to this worker process, not to the calling terminal.
        try:
            api(self.user, "SetProcessDpiAwarenessContext", w.BOOL, c.c_void_p)(c.c_void_p(-4))
        except AttributeError:
            self.user.SetProcessDPIAware()
        self.dpi_scale = api(self.user, "GetDpiForSystem", w.UINT)() / 96
        with store.locked(directory) as data:
            current = data["current"]
            if not current or current["id"] != session_id:
                raise ValueError("Session is no longer active")
            self.scale = self.dpi_scale * current.get("scale", 1.0)
            self.hidden = current.get("widget_hidden", True)
        self.font_path = str(Path(__file__).parent / "assets" / "tiny5.ttf")
        if not self.add_font(self.font_path, 0x10, None):
            raise OSError("Unable to load the bundled Tiny5 font")
        self.font = None
        self.window = None
        self.hovered = False
        self.wide = False
        self.previous = None
        self.failure = None
        self.position = None
        self.last_width = None
        self.pointer_start = None
        self.drag_origin = None
        self.drag_position = None
        self.last_drag_step = 0.0
        self.dragging = False
        self.pressed_handle = False
        self.pending_click = None
        self.handle_width = max(1, round(24 * self.scale))
        self.edge_gap = round(4 * self.scale)
        self.panel_offset = self.handle_width + round(4 * self.scale)
        self.reveal = 0.0 if self.hidden else 1.0
        self.animation = None
        self.image = None
        self.normal_frame = None
        self.tab_image = None
        self.renderer = None
        self.frame_cache = {}
        self.frame_key = None
        self.frame_timer = None
        self.next_frame = 0.0
        self.surface = None
        self.surface_image = None
        self.presented = None
        self.callback = WNDPROC(self.procedure)
        self.class_name = f"timeprobe-{session_id}"

    def configure_api(self):
        u, g = self.user, self.gdi
        ptr = c.c_void_p
        self.register = api(u, "RegisterClassW", w.ATOM, c.POINTER(WindowClass))
        self.unregister = api(u, "UnregisterClassW", w.BOOL, w.LPCWSTR, w.HINSTANCE)
        self.create = api(
            u,
            "CreateWindowExW",
            w.HWND,
            w.DWORD,
            w.LPCWSTR,
            w.LPCWSTR,
            w.DWORD,
            c.c_int,
            c.c_int,
            c.c_int,
            c.c_int,
            w.HWND,
            w.HMENU,
            w.HINSTANCE,
            ptr,
        )
        self.default = api(u, "DefWindowProcW", LRESULT, w.HWND, w.UINT, w.WPARAM, w.LPARAM)
        self.destroy = api(u, "DestroyWindow", w.BOOL, w.HWND)
        self.show = api(u, "ShowWindow", w.BOOL, w.HWND, c.c_int)
        self.timer = api(u, "SetTimer", c.c_size_t, w.HWND, c.c_size_t, w.UINT, ptr)
        self.kill_timer = api(u, "KillTimer", w.BOOL, w.HWND, c.c_size_t)
        self.double_click_time = api(u, "GetDoubleClickTime", w.UINT)
        self.native_get_message = api(
            u, "GetMessageW", w.BOOL, c.POINTER(w.MSG), w.HWND, w.UINT, w.UINT
        )
        self.get_message = self.next_message
        self.peek_message = api(
            u, "PeekMessageW", w.BOOL, c.POINTER(w.MSG), w.HWND, w.UINT, w.UINT, w.UINT
        )
        self.wait_messages = api(
            u,
            "MsgWaitForMultipleObjectsEx",
            w.DWORD,
            w.DWORD,
            c.POINTER(w.HANDLE),
            w.DWORD,
            w.DWORD,
            w.DWORD,
        )
        self.create_frame_timer = api(
            self.kernel, "CreateWaitableTimerExW", w.HANDLE, ptr, w.LPCWSTR, w.DWORD, w.DWORD
        )
        self.arm_frame_timer = api(
            self.kernel,
            "SetWaitableTimer",
            w.BOOL,
            w.HANDLE,
            c.POINTER(c.c_longlong),
            w.LONG,
            ptr,
            ptr,
            w.BOOL,
        )
        self.close_handle = api(self.kernel, "CloseHandle", w.BOOL, w.HANDLE)
        self.translate = api(u, "TranslateMessage", w.BOOL, c.POINTER(w.MSG))
        self.dispatch = api(u, "DispatchMessageW", LRESULT, c.POINTER(w.MSG))
        self.track = api(u, "TrackMouseEvent", w.BOOL, c.POINTER(MouseTracking))
        self.cursor_position = api(u, "GetCursorPos", w.BOOL, c.POINTER(w.POINT))
        self.capture = api(u, "SetCapture", w.HWND, w.HWND)
        self.release_capture = api(u, "ReleaseCapture", w.BOOL)
        self.move = api(
            u, "SetWindowPos", w.BOOL, w.HWND, w.HWND, c.c_int, c.c_int, c.c_int, c.c_int, w.UINT
        )
        self.work_area = api(u, "SystemParametersInfoW", w.BOOL, w.UINT, w.UINT, ptr, w.UINT)
        self.load_cursor = api(u, "LoadCursorW", w.HANDLE, w.HINSTANCE, ptr)
        self.layer = api(
            u,
            "UpdateLayeredWindow",
            w.BOOL,
            w.HWND,
            w.HDC,
            c.POINTER(w.POINT),
            c.POINTER(w.SIZE),
            w.HDC,
            c.POINTER(w.POINT),
            w.DWORD,
            c.POINTER(Blend),
            w.DWORD,
        )
        self.draw_text = api(
            u, "DrawTextW", c.c_int, w.HDC, w.LPCWSTR, c.c_int, c.POINTER(w.RECT), w.UINT
        )
        self.add_font = api(g, "AddFontResourceExW", c.c_int, w.LPCWSTR, w.DWORD, ptr)
        self.remove_font = api(g, "RemoveFontResourceExW", w.BOOL, w.LPCWSTR, w.DWORD, ptr)
        self.create_font = api(
            g,
            "CreateFontW",
            w.HFONT,
            c.c_int,
            c.c_int,
            c.c_int,
            c.c_int,
            c.c_int,
            w.DWORD,
            w.DWORD,
            w.DWORD,
            w.DWORD,
            w.DWORD,
            w.DWORD,
            w.DWORD,
            w.DWORD,
            w.LPCWSTR,
        )
        self.create_dc = api(g, "CreateCompatibleDC", w.HDC, w.HDC)
        self.delete_dc = api(g, "DeleteDC", w.BOOL, w.HDC)
        self.select = api(g, "SelectObject", w.HANDLE, w.HDC, w.HANDLE)
        self.delete_object = api(g, "DeleteObject", w.BOOL, w.HANDLE)
        self.dib = api(
            g,
            "CreateDIBSection",
            w.HBITMAP,
            w.HDC,
            c.POINTER(BitmapInfo),
            w.UINT,
            c.POINTER(ptr),
            w.HANDLE,
            w.DWORD,
        )
        self.text_color = api(g, "SetTextColor", w.DWORD, w.HDC, w.DWORD)
        self.background_mode = api(g, "SetBkMode", c.c_int, w.HDC, c.c_int)

    def start(self):
        wc = WindowClass()
        wc.style = 0x0008  # CS_DBLCLKS
        wc.procedure, wc.instance, wc.name = self.callback, self.instance, self.class_name
        wc.cursor = self.load_cursor(None, c.c_void_p(32649))  # IDC_HAND
        if not self.register(c.byref(wc)):
            raise c.WinError(c.get_last_error())
        try:
            # LAYERED | TOPMOST | TOOLWINDOW | NOACTIVATE, with no title bar or taskbar item.
            self.window = self.create(
                0x08080088,
                self.class_name,
                "timeprobe",
                0x80000000,
                0,
                0,
                124,
                48,
                None,
                None,
                self.instance,
                None,
            )
            if not self.window:
                raise c.WinError(c.get_last_error())
            self.font = self.create_font(
                -round(36 * self.scale), 0, 0, 0, 400, 0, 0, 0, 1, 0, 0, 4, 0, "Tiny5"
            )
            if not self.font:
                raise OSError("Unable to create the pixel font")
            if not self.refresh():
                return
            # A high-resolution waitable timer avoids WM_TIMER's ~30 ms cadence.
            # Older Windows versions retain the existing WM_TIMER fallback.
            self.frame_timer = self.create_frame_timer(None, None, 0x2, 0x1F0003)
            self.show(self.window, 4)  # SW_SHOWNOACTIVATE
            with store.locked(self.directory) as data:
                current = data["current"]
                if current and current["id"] == self.session_id:
                    current.update(widget_state="visible", widget_error=None)
            if not self.timer(self.window, 1, 100, None):
                raise c.WinError(c.get_last_error())
            message = w.MSG()
            while True:
                result = self.get_message(c.byref(message), None, 0, 0)
                if result == 0:
                    break
                if result == -1:
                    raise c.WinError(c.get_last_error())
                self.translate(c.byref(message))
                self.dispatch(c.byref(message))
            if self.failure:
                raise self.failure
        finally:
            self.release_surface()
            if self.frame_timer:
                self.close_handle(self.frame_timer)
                self.frame_timer = None
            if self.window:
                self.kill_timer(self.window, 1)
                self.kill_timer(self.window, 2)
                self.destroy(self.window)
                self.window = None
            if self.font:
                self.delete_object(self.font)
            self.unregister(self.class_name, self.instance)
            self.remove_font(self.font_path, 0x10, None)

    def next_message(self, message, window, first, last):
        while self.animation is not None and self.frame_timer:
            now = time.monotonic()
            if now >= self.next_frame:
                if not self.refresh():
                    self.destroy(self.window)
                self.next_frame = time.monotonic() + 1 / 120
                if self.animation is None:
                    break
            if self.peek_message(message, window, first, last, 1):
                return 0 if c.cast(message, c.POINTER(w.MSG)).contents.message == 0x12 else 1
            due = c.c_longlong(-max(1, round((self.next_frame - time.monotonic()) * 10_000_000)))
            if not self.arm_frame_timer(self.frame_timer, c.byref(due), 0, None, None, False):
                raise c.WinError(c.get_last_error())
            handles = (w.HANDLE * 1)(self.frame_timer)
            result = self.wait_messages(1, handles, 0xFFFFFFFF, 0x04FF, 0x4)
            if result == 0xFFFFFFFF:
                raise c.WinError(c.get_last_error())
        return self.native_get_message(message, window, first, last)

    def procedure(self, window, message, wp, lp):
        try:
            if message == 0x21:  # WM_MOUSEACTIVATE: accept click without taking keyboard focus.
                return 3
            if message == 0x113:  # WM_TIMER
                if wp == 2:
                    if self.pending_click is not None and time.monotonic() < self.click_deadline:
                        return 0
                    expected = self.pending_click
                    self.cancel_click()
                    with store.locked(self.directory) as data:
                        current = data["current"]
                        if (
                            not current
                            or current["id"] != self.session_id
                            or current["state"] != expected
                        ):
                            return 0
                    engine.execute("resume" if expected == "paused" else "pause", self.directory)
                    self.refresh()
                    return 0
                if self.animation is not None and getattr(self, "frame_timer", None):
                    return 0
                if not self.refresh():
                    self.destroy(window)
                return 0
            if message == 0x200:  # WM_MOUSEMOVE
                if self.pointer_start is not None:
                    point = w.POINT()
                    self.cursor_position(c.byref(point))
                    dx, dy = point.x - self.pointer_start[0], point.y - self.pointer_start[1]
                    if self.dragging or max(abs(dx), abs(dy)) >= round(4 * self.dpi_scale):
                        self.cancel_click()
                        self.animation = None
                        self.dragging = True
                        self.hovered = False
                        if self.normal_frame is not None and len(self.normal_frame) == len(
                            self.image
                        ):
                            self.image = self.normal_frame
                        self.drag_position = self.drag_origin[0] + dx, self.drag_origin[1] + dy
                        self.refresh()
                        return 0
                hovered = not self.hidden and c.c_short(lp & 0xFFFF).value >= self.panel_offset
                if hovered != self.hovered:
                    self.hovered = hovered
                    self.track(c.byref(MouseTracking(c.sizeof(MouseTracking), 2, window, 0)))
                    self.refresh()
                return 0
            if message == 0x2A3:  # WM_MOUSELEAVE
                self.hovered = False
                self.refresh()
                return 0
            if message == 0x201:  # WM_LBUTTONDOWN
                point = w.POINT()
                self.cursor_position(c.byref(point))
                self.pointer_start = point.x, point.y
                self.drag_origin = self.body_position()
                self.dragging = False
                self.pressed_handle = (
                    self.hidden or c.c_short(lp & 0xFFFF).value < self.panel_offset
                )
                self.capture(window)
                return 0
            if message == 0x203:  # WM_LBUTTONDBLCLK
                self.cancel_click()
                self.pointer_start = None
                self.dragging = False
                self.release_capture()
                if not self.hidden:
                    self.set_hidden(True)
                    self.refresh()
                return 0
            if message == 0x202:  # WM_LBUTTONUP
                if self.pointer_start is None:
                    return 0
                dragged = self.dragging
                handle = self.pressed_handle
                point = w.POINT()
                self.cursor_position(c.byref(point))
                dx = point.x - self.pointer_start[0]
                self.pointer_start = None
                self.dragging = False
                self.release_capture()
                if dragged:
                    self.finish_drag(dx, handle)
                    self.refresh()
                    return 0
                if handle:
                    self.cancel_click()
                    self.set_hidden(dx > 0 if dragged else not self.hidden)
                    self.refresh()
                    return 0
                with store.locked(self.directory) as data:
                    current = data["current"]
                    if not current or current["id"] != self.session_id:
                        return 0
                    self.pending_click = current["state"]
                interval = self.double_click_time()
                self.click_deadline = time.monotonic() + interval / 1000
                if not self.timer(window, 2, interval, None):
                    raise c.WinError(c.get_last_error())
                return 0
            if message == 0x215:  # WM_CAPTURECHANGED
                if self.dragging:
                    point = w.POINT()
                    self.cursor_position(c.byref(point))
                    dx = point.x - self.pointer_start[0]
                    self.dragging = False
                    self.finish_drag(dx, self.pressed_handle)
                self.pointer_start = None
                self.dragging = False
                return 0
            if message == 2:  # WM_DESTROY
                self.animation = None
                self.user.PostQuitMessage(0)
                return 0
        except Exception as error:
            # Never let Python exceptions escape a native window callback.
            self.failure = error
            self.destroy(window)
            return 0
        return self.default(window, message, wp, lp)

    def cancel_click(self):
        if self.pending_click is not None:
            self.kill_timer(self.window, 2)
            self.pending_click = None

    def set_hidden(self, hidden):
        if hidden == self.hidden and self.reveal == (0.0 if hidden else 1.0):
            return
        self.hidden = hidden
        self.hovered = False
        if self.normal_frame is not None and len(self.normal_frame) == len(self.image):
            self.image = self.normal_frame
        with store.locked(self.directory) as data:
            current = data["current"]
            if current and current["id"] == self.session_id:
                current["widget_hidden"] = hidden
        self.animation = time.monotonic(), self.reveal
        self.timer(self.window, 1, 16, None)

    def body_position(self):
        area = w.RECT()
        if not self.work_area(0x30, 0, c.byref(area), 0):
            raise c.WinError(c.get_last_error())
        hidden_x = area.right - self.panel_offset
        return round(hidden_x + (self.position[0] - hidden_x) * self.reveal), self.position[1]

    def finish_drag(self, dx, handle):
        x, y = self.drag_position
        self.drag_position = None
        area = w.RECT()
        if not self.work_area(0x30, 0, c.byref(area), 0):
            raise c.WinError(c.get_last_error())
        if not handle and x + self.full_width < area.right:
            self.position = x, y
            self.reveal = 1.0
            self.previous = None
            return
        self.position = min(self.position[0], x), y
        end = area.right - self.panel_offset
        travel = end - self.position[0]
        self.reveal = max(0.0, min(1.0, (end - x) / travel)) if travel > 0 else 0.0
        self.set_hidden(dx >= 0 if handle else True)

    def refresh(self):
        if self.dragging:
            tick = time.monotonic()
            if tick - self.last_drag_step >= 0.1:
                if not engine.step(self.directory, self.session_id):
                    return False
                self.last_drag_step = tick
            self.present()
            return True
        if self.animation is not None:
            started, origin = self.animation
            progress = min(1.0, (time.monotonic() - started) / 0.26)
            eased = 1 - (1 - progress) ** 3
            target = 0.0 if self.hidden else 1.0
            self.reveal = origin + (target - origin) * eased
            self.present()
            if progress == 1:
                self.animation = None
                self.previous = None
                self.timer(self.window, 1, 100, None)
            return True
        if not engine.step(self.directory, self.session_id):
            return False
        with store.locked(self.directory) as data:
            current = data["current"]
            if not current or current["id"] != self.session_id:
                return False
            session = snapshot(current, time.monotonic())
        text, self.wide = display_time(session, self.wide)
        key = text, session["state"], self.hovered
        if key != self.previous and (not self.hidden or self.image is None):
            self.paint(text, session["state"] == "paused")
            self.previous = key
        self.present()
        return True

    def paint(self, text, paused):
        scale = self.scale
        width = round((168 if self.wide else 124) * scale)
        # Allow very long sessions without compressing the normal MM:SS layout.
        width = max(width, round((len(text) * 18 + 16) * scale))
        height = round(48 * scale)
        full_width = width + self.panel_offset
        area = w.RECT()
        if not self.work_area(0x30, 0, c.byref(area), 0):
            raise c.WinError(c.get_last_error())
        if self.position is None:
            self.position = (
                area.right - full_width - round(9 * self.dpi_scale),
                area.top + round(44 * self.dpi_scale),
            )
        elif self.last_width is not None and self.last_width != width:
            self.position = self.position[0] + self.last_width - width, self.position[1]
        self.last_width = width
        frame_key = text, width
        if frame_key != self.frame_key:
            self.frame_cache.clear()
            self.frame_key = frame_key
        variant = self.hovered, paused if self.hovered else False
        if variant in self.frame_cache:
            self.image = self.frame_cache[variant]
            if not self.hovered:
                self.normal_frame = self.image
            return
        dc = self.create_dc(None)
        bitmap = None
        previous = None
        try:
            info = BitmapInfo()
            info.header = BitmapHeader(
                c.sizeof(BitmapHeader), width, -height, 1, 32, 0, 0, 0, 0, 0, 0
            )
            address = c.c_void_p()
            bitmap = self.dib(dc, c.byref(info), 0, c.byref(address), None, 0)
            if not bitmap or not address.value:
                raise c.WinError(c.get_last_error())
            previous = self.select(dc, bitmap)
            self.select(dc, self.font)
            c.memset(address, 0, width * height * 4)
            self.text_color(dc, 0xFFFFFF)
            self.background_mode(dc, 1)
            self.draw_text(dc, text, -1, c.byref(w.RECT(0, 0, width, height)), 0x25)
            self.gdi.GdiFlush()
            pixels = (c.c_ubyte * (width * height * 4)).from_address(address.value)
            mask = center_ink(bytes(pixels[::4]), width, height)
            if self.renderer is None or self.renderer.width != width:
                self.renderer = PanelRenderer(width, height, scale)
            panel = self.renderer.render(mask, self.hovered, paused)
            image = bytearray(full_width * height * 4)
            for y in range(height):
                offset = (y * full_width + self.panel_offset) * 4
                image[offset : offset + width * 4] = panel[y * width * 4 : (y + 1) * width * 4]
            self.image = bytes(image)
            self.frame_cache[variant] = self.image
            if not self.hovered:
                self.normal_frame = self.image
            if self.tab_image is None:
                tab = bytearray(self.handle_width * height * 4)
                for y in range(height):
                    for x in range(self.handle_width):
                        offset = (y * self.handle_width + x) * 4
                        # Near-transparent pixels keep the whole tab easy to grab.
                        tab[offset + 3] = 1
                        coverage = triangle_coverage(x, y, scale, True)
                        if coverage:
                            tab[offset : offset + 4] = bytes(
                                (
                                    round(25 * 0.89 * coverage),
                                    round(29 * 0.89 * coverage),
                                    round(22 * 0.89 * coverage),
                                    max(1, round(255 * 0.89 * coverage)),
                                )
                            )
                self.tab_image = bytes(tab)
            self.full_width, self.height = full_width, height
        finally:
            if previous:
                self.select(dc, previous)
            if bitmap:
                self.delete_object(bitmap)
            if dc:
                self.delete_dc(dc)

    def present(self):
        area = w.RECT()
        if not self.work_area(0x30, 0, c.byref(area), 0):
            raise c.WinError(c.get_last_error())
        tab_only = self.hidden and self.reveal == 0 and not self.dragging
        if tab_only:
            x, y = area.right - self.edge_gap - self.handle_width, self.position[1]
            width = self.handle_width
            empty = False
        else:
            x, y = self.drag_position if self.dragging else self.body_position()
            empty = x >= area.right
            x = min(x, area.right - 1)
            width = min(self.full_width, area.right - x)
        source = b"" if empty else self.tab_image if tab_only else self.image
        key = x, y, width, self.height, id(source)
        if self.presented == key and self.surface_image is source:
            return
        if self.surface is None or self.surface[0] != (self.full_width, self.height):
            self.release_surface()
            dc = self.create_dc(None)
            bitmap = previous = None
            try:
                info = BitmapInfo()
                info.header = BitmapHeader(
                    c.sizeof(BitmapHeader), self.full_width, -self.height, 1, 32, 0, 0, 0, 0, 0, 0
                )
                address = c.c_void_p()
                bitmap = self.dib(dc, c.byref(info), 0, c.byref(address), None, 0)
                if not bitmap or not address.value:
                    raise c.WinError(c.get_last_error())
                previous = self.select(dc, bitmap)
                self.surface = (self.full_width, self.height), dc, bitmap, previous, address
            except Exception:
                if bitmap:
                    self.delete_object(bitmap)
                self.delete_dc(dc)
                raise
        _, dc, _, _, address = self.surface
        # Keep a full-width source bitmap: Windows crops it to the visible window size.
        if self.surface_image is not source:
            if tab_only or empty:
                c.memset(address, 0, self.full_width * self.height * 4)
                if tab_only:
                    stride = self.handle_width * 4
                    for row in range(self.height):
                        c.memmove(
                            address.value + row * self.full_width * 4,
                            source[row * stride : (row + 1) * stride],
                            stride,
                        )
            else:
                c.memmove(address, source, len(source))
            self.surface_image = source
        if not self.layer(
            self.window,
            None,
            c.byref(w.POINT(x, y)),
            c.byref(w.SIZE(width, self.height)),
            dc,
            c.byref(w.POINT(0, 0)),
            0,
            c.byref(Blend(0, 0, 255, 1)),
            2,
        ):
            raise c.WinError(c.get_last_error())
        self.presented = key

    def release_surface(self):
        if self.surface is not None:
            _, dc, bitmap, previous, _ = self.surface
            self.select(dc, previous)
            self.delete_object(bitmap)
            self.delete_dc(dc)
            self.surface = None
        self.surface_image = None
        self.presented = None


def run(directory: Path, session_id: str):
    Overlay(directory, session_id).start()
