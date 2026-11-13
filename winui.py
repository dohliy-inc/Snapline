import ctypes
import io
import tkinter as tk
from ctypes import wintypes

from theme import VOID, make_icon, px


LRESULT = ctypes.c_ssize_t


WNDPROC = ctypes.WINFUNCTYPE(LRESULT, wintypes.HWND, wintypes.UINT, wintypes.WPARAM, wintypes.LPARAM)


WM_NCCALCSIZE, WM_NCACTIVATE, WM_NCLBUTTONDOWN = 0x0083, 0x0086, 0x00A1


WM_TRAY, WM_LBUTTONUP, WM_LBUTTONDBLCLK, WM_RBUTTONUP = 0x8001, 0x0202, 0x0203, 0x0205


SHOW_MSG = ctypes.windll.user32.RegisterWindowMessageW("Snapline.Show")


TASKBAR_CREATED = ctypes.windll.user32.RegisterWindowMessageW("TaskbarCreated")


HT_CAPTION = 2


GRIPS = (
    ("left", 10, "size_we"), ("right", 11, "size_we"), ("top", 12, "size_ns"), ("bottom", 15, "size_ns"),
    ("topleft", 13, "size_nw_se"), ("topright", 14, "size_ne_sw"), ("bottomleft", 16, "size_ne_sw"),
    ("bottomright", 17, "size_nw_se"),
)


class NCCALCSIZE_PARAMS(ctypes.Structure):
    _fields_ = [("rgrc", wintypes.RECT * 3), ("lppos", ctypes.c_void_p)]


class MARGINS(ctypes.Structure):
    _fields_ = [("left", ctypes.c_int), ("right", ctypes.c_int), ("top", ctypes.c_int), ("bottom", ctypes.c_int)]


class NOTIFYICONDATAW(ctypes.Structure):
    _fields_ = [("cbSize", wintypes.DWORD), ("hWnd", wintypes.HWND), ("uID", wintypes.UINT),
                ("uFlags", wintypes.UINT), ("uCallbackMessage", wintypes.UINT), ("hIcon", wintypes.HICON),
                ("szTip", wintypes.WCHAR * 128), ("dwState", wintypes.DWORD), ("dwStateMask", wintypes.DWORD),
                ("szInfo", wintypes.WCHAR * 256), ("uVersion", wintypes.UINT), ("szInfoTitle", wintypes.WCHAR * 64),
                ("dwInfoFlags", wintypes.DWORD), ("guidItem", ctypes.c_byte * 16), ("hBalloonIcon", wintypes.HICON)]


class Tray:
    def __init__(self, hwnd):
        self.hwnd, self.on = hwnd, False
        u = ctypes.WinDLL("user32", use_last_error=True)
        u.CreateIconFromResourceEx.argtypes = [ctypes.c_char_p, wintypes.DWORD, wintypes.BOOL, wintypes.DWORD,
                                               ctypes.c_int, ctypes.c_int, wintypes.UINT]
        u.CreateIconFromResourceEx.restype = wintypes.HICON
        u.DestroyIcon.argtypes = [wintypes.HICON]
        u.CreatePopupMenu.restype = wintypes.HMENU
        u.AppendMenuW.argtypes = [wintypes.HMENU, wintypes.UINT, ctypes.c_size_t, wintypes.LPCWSTR]
        u.TrackPopupMenu.argtypes = [wintypes.HMENU, wintypes.UINT, ctypes.c_int, ctypes.c_int, ctypes.c_int,
                                     wintypes.HWND, ctypes.c_void_p]
        u.DestroyMenu.argtypes = [wintypes.HMENU]
        u.SetForegroundWindow.argtypes = [wintypes.HWND]
        u.PostMessageW.argtypes = [wintypes.HWND, wintypes.UINT, wintypes.WPARAM, wintypes.LPARAM]
        self.u = u
        self.shell = ctypes.WinDLL("shell32", use_last_error=True)
        self.shell.Shell_NotifyIconW.argtypes = [wintypes.DWORD, ctypes.POINTER(NOTIFYICONDATAW)]
        size = u.GetSystemMetrics(49)
        buf = io.BytesIO()
        make_icon(size).save(buf, "PNG")
        data = buf.getvalue()
        self.icon = u.CreateIconFromResourceEx(data, len(data), True, 0x00030000, size, size, 0)
        for msg in (SHOW_MSG, TASKBAR_CREATED):
            try:
                u.ChangeWindowMessageFilterEx(wintypes.HWND(hwnd), msg, 1, None)
            except AttributeError:
                pass

    def notify(self, message, flags=0, info=None):
        data = NOTIFYICONDATAW(cbSize=ctypes.sizeof(NOTIFYICONDATAW), hWnd=self.hwnd, uID=1, uFlags=0x7 | flags,
                               uCallbackMessage=WM_TRAY, hIcon=self.icon, szTip="Snapline")
        if info:
            data.szInfoTitle, data.szInfo = info
        return bool(self.shell.Shell_NotifyIconW(message, ctypes.byref(data)))

    def add(self):
        if not self.on:
            self.on = self.notify(0)

    def remove(self):
        if self.on:
            self.notify(2)
            self.on = False

    def tell(self, title, text):
        if self.on:
            self.notify(1, 0x10, (title, text))

    def menu(self, items):
        handle = self.u.CreatePopupMenu()
        for k, label in enumerate(items, 1):
            self.u.AppendMenuW(handle, 0x800 if label is None else 0, k, label)
        point = wintypes.POINT()
        self.u.GetCursorPos(ctypes.byref(point))
        self.u.SetForegroundWindow(self.hwnd)
        pick = self.u.TrackPopupMenu(handle, 0x0182, point.x, point.y, 0, self.hwnd, None)
        self.u.PostMessageW(self.hwnd, 0, 0, 0)
        self.u.DestroyMenu(handle)
        return pick

    def close(self):
        self.remove()
        if self.icon:
            self.u.DestroyIcon(self.icon)
            self.icon = None


class Frameless:
    def __init__(self, app, hwnd):
        self.app, self.hwnd = app, hwnd
        u = ctypes.WinDLL("user32", use_last_error=True)
        u.SetWindowLongPtrW.argtypes = [wintypes.HWND, ctypes.c_int, ctypes.c_void_p]
        u.SetWindowLongPtrW.restype = ctypes.c_void_p
        u.CallWindowProcW.argtypes = [ctypes.c_void_p, wintypes.HWND, wintypes.UINT, wintypes.WPARAM, wintypes.LPARAM]
        u.CallWindowProcW.restype = LRESULT
        u.IsZoomed.argtypes = [wintypes.HWND]
        u.PostMessageW.argtypes = [wintypes.HWND, wintypes.UINT, wintypes.WPARAM, wintypes.LPARAM]
        u.GetClassLongPtrW.argtypes = [wintypes.HWND, ctypes.c_int]
        u.GetClassLongPtrW.restype = ctypes.c_size_t
        u.SetClassLongPtrW.argtypes = [wintypes.HWND, ctypes.c_int, ctypes.c_size_t]
        u.SetClassLongPtrW.restype = ctypes.c_size_t
        for window in (hwnd, app.root.winfo_id()):
            u.SetClassLongPtrW(window, -26, u.GetClassLongPtrW(window, -26) & ~0x3)
        u.SetWindowPos.argtypes = [wintypes.HWND, wintypes.HWND, ctypes.c_int, ctypes.c_int, ctypes.c_int,
                                   ctypes.c_int, wintypes.UINT]
        self.u = u
        try:
            dpi = u.GetDpiForWindow(wintypes.HWND(hwnd))
            self.border = u.GetSystemMetricsForDpi(32, dpi) + u.GetSystemMetricsForDpi(92, dpi)
        except AttributeError:
            self.border = u.GetSystemMetrics(32) + u.GetSystemMetrics(92)
        self.edge = px(6)
        dwm = ctypes.windll.dwmapi
        for attr, value in ((33, 2), (34, 0x0026201E)):
            v = ctypes.c_int(value)
            dwm.DwmSetWindowAttribute(wintypes.HWND(hwnd), attr, ctypes.byref(v), ctypes.sizeof(v))
        dwm.DwmExtendFrameIntoClientArea(wintypes.HWND(hwnd), ctypes.byref(MARGINS(0, 0, 1, 0)))
        self.proc = WNDPROC(self.wndproc)
        self.prev = u.SetWindowLongPtrW(hwnd, -4, ctypes.cast(self.proc, ctypes.c_void_p))
        u.SetWindowPos(hwnd, None, 0, 0, 0, 0, 0x0027)
        for widget in (app.bar, app.mark):
            widget.bind("<ButtonPress-1>", lambda _: self.native(HT_CAPTION))
            widget.bind("<Double-Button-1>", lambda _: app.toggle_max())
        corner = self.edge * 2
        spots = {
            "left": dict(x=0, y=corner, width=self.edge, relheight=1, height=-2 * corner),
            "right": dict(relx=1, x=-self.edge, y=corner, width=self.edge, relheight=1, height=-2 * corner),
            "top": dict(x=corner, y=0, relwidth=1, width=-2 * corner, height=self.edge),
            "bottom": dict(x=corner, rely=1, y=-self.edge, relwidth=1, width=-2 * corner, height=self.edge),
            "topleft": dict(x=0, y=0, width=corner, height=corner),
            "topright": dict(relx=1, x=-corner, y=0, width=corner, height=corner),
            "bottomleft": dict(x=0, rely=1, y=-corner, width=corner, height=corner),
            "bottomright": dict(relx=1, x=-corner, rely=1, y=-corner, width=corner, height=corner),
        }
        self.grips = []
        for name, code, cursor in GRIPS:
            grip = tk.Frame(app.root, bg=VOID, cursor=cursor, bd=0, highlightthickness=0)
            grip.bind("<ButtonPress-1>", lambda _, c=code: self.native(c))
            self.grips.append((grip, spots[name]))
        self.zoomed = None
        self.sync()

    def native(self, code):
        if code != HT_CAPTION and self.u.IsZoomed(self.hwnd):
            return
        self.u.ReleaseCapture()
        self.u.PostMessageW(self.hwnd, WM_NCLBUTTONDOWN, code, 0)

    def sync(self):
        zoomed = bool(self.u.IsZoomed(self.hwnd))
        if zoomed == self.zoomed:
            return
        self.zoomed = zoomed
        for grip, spot in self.grips:
            if zoomed:
                grip.place_forget()
            else:
                grip.place(**spot)
                grip.lift()

    def wndproc(self, hwnd, msg, wp, lp):
        try:
            if msg in (WM_TRAY, SHOW_MSG, TASKBAR_CREATED):
                self.app.inbox.put(("tray", msg, lp))
                if msg != TASKBAR_CREATED:
                    return 0
            if msg == WM_NCCALCSIZE and wp:
                if self.u.IsZoomed(hwnd):
                    rect = ctypes.cast(lp, ctypes.POINTER(NCCALCSIZE_PARAMS)).contents.rgrc[0]
                    rect.left += self.border
                    rect.top += self.border
                    rect.right -= self.border
                    rect.bottom -= self.border
                return 0
            if msg == WM_NCACTIVATE:
                return self.u.CallWindowProcW(self.prev, hwnd, msg, wp, -1)
        except Exception:
            pass
        return self.u.CallWindowProcW(self.prev, hwnd, msg, wp, lp)


def dark_title(root):
    root.update_idletasks()
    hwnd = ctypes.windll.user32.GetParent(root.winfo_id())
    on = ctypes.c_int(1)
    ctypes.windll.dwmapi.DwmSetWindowAttribute(hwnd, 20, ctypes.byref(on), ctypes.sizeof(on))
    return hwnd


def already_running():
    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    kernel32.CreateMutexW.argtypes = [ctypes.c_void_p, wintypes.BOOL, wintypes.LPCWSTR]
    kernel32.CreateMutexW.restype = wintypes.HANDLE
    handle = kernel32.CreateMutexW(None, False, "Local\\Snapline.SingleInstance")
    return ctypes.get_last_error() == 183, handle
