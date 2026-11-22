"""Small, non-activating Windows overlay with per-pixel alpha. No GUI dependencies."""

from __future__ import annotations

import ctypes as c
import math
import time
from ctypes import wintypes as w
from pathlib import Path

from timeprobe import engine, store
from timeprobe.model import snapshot
from timeprobe.overlay import display_time

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
        kernel = c.WinDLL("kernel32", use_last_error=True)
        self.instance = api(kernel, "GetModuleHandleW", w.HMODULE, w.LPCWSTR)(None)
        self.configure_api()
        # DPI awareness belongs to this worker process, not to the calling terminal.
        try:
            api(self.user, "SetProcessDpiAwarenessContext", w.BOOL, c.c_void_p)(c.c_void_p(-4))
        except AttributeError:
            self.user.SetProcessDPIAware()
        self.scale = api(self.user, "GetDpiForSystem", w.UINT)() / 96
        self.font_path = str(Path(__file__).parent / "assets" / "tiny5.ttf")
        if not self.add_font(self.font_path, 0x10, None):
            raise OSError("Unable to load the bundled Tiny5 font")
        self.font = None
        self.window = None
        self.hovered = False
        self.wide = False
        self.previous = None
        self.failure = None
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
        self.get_message = api(u, "GetMessageW", w.BOOL, c.POINTER(w.MSG), w.HWND, w.UINT, w.UINT)
        self.translate = api(u, "TranslateMessage", w.BOOL, c.POINTER(w.MSG))
        self.dispatch = api(u, "DispatchMessageW", LRESULT, c.POINTER(w.MSG))
        self.track = api(u, "TrackMouseEvent", w.BOOL, c.POINTER(MouseTracking))
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
            if self.window:
                self.kill_timer(self.window, 1)
                self.destroy(self.window)
                self.window = None
            if self.font:
                self.delete_object(self.font)
            self.unregister(self.class_name, self.instance)
            self.remove_font(self.font_path, 0x10, None)

    def procedure(self, window, message, wp, lp):
        try:
            if message == 0x21:  # WM_MOUSEACTIVATE: accept click without taking keyboard focus.
                return 3
            if message == 0x113:  # WM_TIMER
                if not self.refresh():
                    self.destroy(window)
                return 0
            if message == 0x200:  # WM_MOUSEMOVE
                if not self.hovered:
                    self.hovered = True
                    self.track(c.byref(MouseTracking(c.sizeof(MouseTracking), 2, window, 0)))
                    self.refresh()
                return 0
            if message == 0x2A3:  # WM_MOUSELEAVE
                self.hovered = False
                self.refresh()
                return 0
            if message == 0x202:  # WM_LBUTTONUP
                with store.locked(self.directory) as data:
                    current = data["current"]
                    if not current or current["id"] != self.session_id:
                        return 0
                    action = "resume" if current["state"] == "paused" else "pause"
                engine.execute(action, self.directory)
                self.refresh()
                return 0
            if message == 2:  # WM_DESTROY
                self.user.PostQuitMessage(0)
                return 0
        except Exception as error:
            # Never let Python exceptions escape a native window callback.
            self.failure = error
            self.destroy(window)
            return 0
        return self.default(window, message, wp, lp)

    def refresh(self):
        if not engine.step(self.directory, self.session_id):
            return False
        with store.locked(self.directory) as data:
            current = data["current"]
            if not current or current["id"] != self.session_id:
                return False
            session = snapshot(current, time.monotonic())
        text, self.wide = display_time(session, self.wide)
        key = text, session["state"], self.hovered
        if key != self.previous:
            self.paint(text, session["state"] == "paused")
            self.previous = key
        return True

    def paint(self, text, paused):
        scale = self.scale
        width = round((168 if self.wide else 124) * scale)
        # Allow very long sessions without compressing the normal MM:SS layout.
        width = max(width, round((len(text) * 18 + 16) * scale))
        height = round(48 * scale)
        area = w.RECT()
        if not self.work_area(0x30, 0, c.byref(area), 0):
            raise c.WinError(c.get_last_error())
        destination = w.POINT(area.right - width - round(9 * scale), area.top + round(44 * scale))
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
            # Composite opaque sage digits over the exact approved translucent background.
            foreground = (216, 230, 201)
            background = (22, 29, 25)
            radius = 6 * scale
            for y in range(height):
                for x in range(width):
                    offset = (y * width + x) * 4
                    distance = math.hypot(
                        max(radius - x - 0.5, x + 0.5 - width + radius, 0),
                        max(radius - y - 0.5, y + 0.5 - height + radius, 0),
                    )
                    coverage = max(0.0, min(1.0, radius + 0.5 - distance))
                    text_alpha = (
                        pixels[offset] / 255 * (0.16 if self.hovered else 0.65 if paused else 1)
                    )
                    if self.hovered:
                        px, py = (x - width / 2) / scale, (y - height / 2) / scale
                        icon = (-5 <= px <= -2 or 2 <= px <= 5) and abs(py) <= 8.5
                        if paused:
                            icon = -4 <= px <= 7 and abs(py) <= (7 - px) * 0.72
                        if icon:
                            text_alpha = 1
                    bg_alpha = 0.76
                    alpha = (text_alpha + bg_alpha * (1 - text_alpha)) * coverage
                    for channel, index in ((0, 2), (1, 1), (2, 0)):
                        value = foreground[channel] * text_alpha + background[
                            channel
                        ] * bg_alpha * (1 - text_alpha)
                        pixels[offset + index] = round(value * coverage)
                    pixels[offset + 3] = round(alpha * 255)
            if not self.layer(
                self.window,
                None,
                c.byref(destination),
                c.byref(w.SIZE(width, height)),
                dc,
                c.byref(w.POINT(0, 0)),
                0,
                c.byref(Blend(0, 0, 255, 1)),
                2,
            ):
                raise c.WinError(c.get_last_error())
        finally:
            if previous:
                self.select(dc, previous)
            if bitmap:
                self.delete_object(bitmap)
            if dc:
                self.delete_dc(dc)


def run(directory: Path, session_id: str):
    Overlay(directory, session_id).start()
