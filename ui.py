import ctypes
import queue
import sys
import tempfile
import threading
import tkinter as tk
import traceback
from ctypes import wintypes
from datetime import datetime
from pathlib import Path

from PIL import ImageTk

import chat
import core
import theme
from feed import Feed
from settings import Settings
from theme import FONT, SUB, VOID, WHITE, init_fonts, init_metrics, make_icon, px
from widgets import CaptionButton, Wordmark
from winui import (
    Frameless, GRIPS, HT_CAPTION, SHOW_MSG, TASKBAR_CREATED, Tray, WM_LBUTTONDBLCLK, WM_LBUTTONUP, WM_RBUTTONUP,
    WM_TRAY, already_running, dark_title
)


class App:
    def __init__(self, root):
        self.root = root
        self.inbox = queue.Queue()
        init_fonts()
        init_metrics(root)
        try:
            self.raw, self.cfg = core.load_config()
        except ValueError as e:
            self.raw = dict(core.DEFAULTS)
            self.cfg = core.parse_config(self.raw)
            self.problem = f"config.ini не прочитан ({e}), взяты настройки по умолчанию"
        else:
            self.problem = None
        root.title("Snapline")
        root.configure(bg=VOID)
        sw, sh = root.winfo_screenwidth(), root.winfo_screenheight()
        w, h = min(px(1360), sw - px(40)), min(px(880), sh - px(110))
        root.geometry(f"{w}x{h}+{max(0, (sw - w) // 2)}+{max(0, (sh - h) // 3)}")
        root.minsize(min(px(1100), w), min(px(700), h))
        self.icon = ImageTk.PhotoImage(make_icon(64))
        root.iconphoto(True, self.icon)
        self.build_bar()
        self.views = tk.Frame(root, bg=VOID)
        self.views.pack(fill="both", expand=True)
        self.feed = Feed(self, self.views)
        self.settings = Settings(self, self.views)
        self.tab = None
        self.show("feed")
        root.bind_all("<Key>", self.key)
        problem = self.problem or core.check_out(self.cfg)
        if problem:
            self.feed.message = ("fail", problem)
        if self.cfg["chatlog"]:
            self.settings.toggle_chatlog("yes")
        self.update = None
        threading.Thread(target=self.check_update, daemon=True).start()
        self.close = root.destroy
        self.frame = None
        self.tray = None
        self.zoomed = False
        root.bind("<Configure>", self.on_configure, add="+")
        root.after(100, self.pump)

    def build_bar(self):
        bar = tk.Frame(self.root, bg=VOID, height=px(64))
        bar.pack(fill="x")
        bar.pack_propagate(False)
        self.bar = bar
        self.mark = Wordmark(bar, "Snapline")
        self.mark.place(x=theme.PAD + px(12), rely=0.5, anchor="w")
        self.chrome = tk.Frame(bar, bg=VOID)
        self.chrome.place(relx=1.0, x=-px(10), rely=0.5, anchor="e")
        self.btn_max = None
        for key, command in (("min", self.minimize), ("max", self.toggle_max), ("close", lambda: self.close_window())):
            button = CaptionButton(self.chrome, key, command, danger=key == "close")
            button.pack(side="left", padx=(px(2), 0))
            if key == "max":
                self.btn_max = button
        tabs = tk.Frame(bar, bg=VOID)
        tabs.place(relx=1.0, x=-(px(10) + 3 * (px(44) + px(2)) + px(28)), rely=0.5, anchor="e")
        self.tabs_frame = tabs
        self.tabs = {}
        for i, (key, text) in enumerate((("feed", "Съёмка"), ("settings", "Настройки"))):
            box = tk.Frame(tabs, bg=VOID)
            box.pack(side="left", padx=(px(32) if i else 0, 0))
            label = tk.Label(box, text=text, bg=VOID, fg=SUB, font=(FONT["semi"], 12), cursor="hand2")
            label.pack()
            line = tk.Frame(box, bg=VOID, height=px(2), width=px(22))
            line.pack(pady=(px(4), 0))
            label.bind("<Button-1>", lambda _, k=key: self.show(k))
            label.bind("<Enter>", lambda _, l=label, k=key: l.config(fg=WHITE))
            label.bind("<Leave>", lambda _, l=label, k=key: l.config(fg=WHITE if self.tab == k else SUB))
            self.tabs[key] = (label, line)

    def minimize(self):
        self.root.iconify()

    def close_window(self):
        if self.tray and self.tray.on and self.cfg["tray"]:
            self.to_tray()
        else:
            self.close()

    def to_tray(self):
        self.feed.flush_save()
        self.zoomed = self.root.state() == "zoomed"
        self.root.withdraw()
        if self.cfg["tray_hint"]:
            self.tray.tell("Snapline работает в трее", f"{self.cfg['key']} в игре снимает СС и так. "
                                                       "Открыть окно или выйти — через этот значок.")
            self.set("tray_hint", "no")

    def reveal(self):
        self.root.deiconify()
        if self.zoomed:
            self.root.state("zoomed")
        self.root.lift()
        self.root.focus_force()
        ctypes.windll.user32.SetForegroundWindow(self.hwnd)

    def tray_event(self, msg, lp):
        event = lp & 0xFFFF
        if msg == TASKBAR_CREATED:
            if self.tray and self.cfg["tray"]:
                self.tray.on = False
                self.tray.add()
        elif msg == SHOW_MSG or event in (WM_LBUTTONUP, WM_LBUTTONDBLCLK):
            self.reveal()
        elif event == WM_RBUTTONUP and self.tray:
            pick = self.tray.menu(("Открыть Snapline", "Папка со СС", None, "Выход"))
            if pick == 1:
                self.reveal()
            elif pick == 2:
                self.feed.open_folder()
            elif pick == 4:
                self.root.after_idle(self.close)

    def set_tray(self, value):
        self.set("tray", value)
        if self.tray:
            (self.tray.add if value == "yes" else self.tray.remove)()

    def toggle_max(self):
        self.root.state("normal" if self.root.state() == "zoomed" else "zoomed")

    def on_configure(self, e):
        if e.widget is self.root and self.btn_max is not None:
            self.btn_max.set_glyph("restore" if self.root.state() == "zoomed" else "max")
        if e.widget is self.root and self.frame is not None:
            self.frame.sync()

    def show(self, tab):
        if tab == self.tab:
            return
        self.tab = tab
        for key, (label, line) in self.tabs.items():
            label.config(fg=WHITE if key == tab else SUB)
            line.config(bg=WHITE if key == tab else VOID)
        if tab == "feed":
            self.root.focus_set()
            self.feed.c.place(x=0, y=0, relwidth=1, relheight=1)
            tk.Misc.tkraise(self.feed.c)
            self.feed.redraw()
        else:
            self.settings.f.place(x=0, y=0, relwidth=1, relheight=1)
            tk.Misc.tkraise(self.settings.f)
            self.settings.update_src()
            self.settings.draw_example()

    def set(self, key, value):
        raw = dict(self.raw, **{key: value})
        try:
            cfg = core.parse_config(raw)
        except ValueError:
            return False
        self.raw, self.cfg = raw, cfg
        try:
            core.write_raw(raw)
        except OSError as e:
            self.feed.message = ("fail", f"Не удалось сохранить настройки: {e}")
        self.settings.draw_example()
        return True

    def crash(self, kind, value, tb):
        try:
            with open(core.ERROR_LOG, "a", encoding="utf-8") as f:
                f.write(f"{datetime.now()}\n{''.join(traceback.format_exception(kind, value, tb))}\n")
        except OSError:
            pass
        self.feed.note = f"ошибка, подробности в {core.ERROR_LOG.name}"
        try:
            self.feed.update_meta()
        except tk.TclError:
            pass

    def check_update(self):
        found = core.latest_release()
        if found:
            self.inbox.put(("update", *found))

    def foreground(self):
        return ctypes.windll.user32.GetForegroundWindow() == self.hwnd

    def key(self, e):
        if isinstance(e.widget, tk.Entry):
            return
        if self.settings.on_key(e):
            return
        if self.tab == "feed":
            self.feed.key(e)

    def pump(self):
        feed = self.feed
        try:
            while True:
                event = core.EVENTS.get_nowait()
                if event[0] == "busy":
                    feed.busy = event[1]
                    if event[1]:
                        feed.flush_save()
                    if feed.index == 0:
                        feed.redraw()
                elif event[0] == "log":
                    level, msg = event[3], event[2]
                    if level in ("fail", "step"):
                        feed.message = (level, msg)
                        if feed.drag is None:
                            feed.go(0)
                    elif level == "ok":
                        feed.message = None
                elif event[0] == "ss":
                    feed.new_shot(event[1])
                    self.settings.sample = None
                elif event[0] == "chatlog":
                    self.settings.chatlog_note(event[1])
        except queue.Empty:
            pass
        try:
            while True:
                kind, name, value = self.inbox.get_nowait()
                if kind == "tray":
                    self.tray_event(name, value)
                    continue
                if kind == "update":
                    self.update = (name, value)
                    self.settings.show_update()
                    if feed.index == 0:
                        feed.redraw()
                    continue
                getattr(self.settings if kind in ("sample_loaded", "estimated") else feed, kind)(name, value)
        except queue.Empty:
            pass
        self.root.after(100, self.pump)


def selftest():
    root = tk.Tk()
    root.attributes("-toolwindow", True)
    root.attributes("-alpha", 0.0)
    errors = []
    root.report_callback_exception = lambda *a: errors.append("".join(traceback.format_exception(*a)))
    app = App(root)
    app.hwnd = dark_title(root)
    app.frame = Frameless(app, app.hwnd)
    result = {}

    calls, routed = [], []
    app.frame.native = calls.append
    app.tray_event = lambda msg, lp: routed.append((msg, lp))
    ctypes.windll.user32.PostMessageW(wintypes.HWND(app.hwnd), WM_TRAY, 0, 0x0200)
    app.toggle_max = lambda: calls.append("max")

    def press(widget, double=False):
        widget.event_generate("<ButtonPress-1>", x=4, y=4)
        widget.event_generate("<ButtonRelease-1>", x=4, y=4)
        if double:
            widget.event_generate("<ButtonPress-1>", x=4, y=4)
            widget.event_generate("<ButtonRelease-1>", x=4, y=4)

    def clicks():
        press(app.bar, double=True)
        root.after(700, lambda: (press(app.mark), [press(grip) for grip, _ in app.frame.grips],
                                 root.after(200, check)))

    def check():
        sample = core.RES_DIR / "samples"
        rows = chat.classify(chat.extract_rows(core.read_image(sample / "example_chat.png")))
        with tempfile.TemporaryDirectory() as tmp:
            cfg = dict(app.cfg, out=Path(tmp))
            core.save_src(core.read_image(sample / "example_bg.webp"), cfg, "SS_selftest_bg", core.SRC_BG)
            core.save_src(core.read_image(sample / "example_chat.png"), cfg, "SS_selftest_chat1", core.SRC_CHAT)
            shot = core.load_shot(Path(tmp), "SS_selftest", cfg)
            core.save_shot(shot)
            saved = core.shot_image(Path(tmp), "SS_selftest").exists() and any(r["keep"] for r in shot["rows"])
        W, H = root.winfo_width(), root.winfo_height()
        grips = dict(zip((name for name, _, _ in GRIPS), (grip for grip, _ in app.frame.grips)))
        order = root.winfo_children()
        on_top = min(order.index(g) for g in grips.values()) > max(order.index(app.bar), order.index(app.views))
        boxes = {n: (g.winfo_x(), g.winfo_y(), g.winfo_width(), g.winfo_height()) for n, g in grips.items()}
        placed = (boxes["left"][0] == 0 and boxes["right"][0] + boxes["right"][2] == W
                  and boxes["bottom"][1] + boxes["bottom"][3] == H and boxes["topleft"][:2] == (0, 0)
                  and all(b[2] > 0 and b[3] > 0 for b in boxes.values()))
        wiring = calls == [HT_CAPTION, "max", HT_CAPTION, 10, 11, 12, 15, 13, 14, 16, 17] and routed == [(WM_TRAY, 0x0200)]
        result["ok"] = ((sample / "example_bg.webp").exists() and any(r["keep"] for r in rows) and FONT["icon"] is not None
                        and saved
                        and app.settings.logo is not None
                        and not errors and app.feed.c.winfo_width() > 100 and wiring and on_top and placed)
        result["detail"] = (calls, routed, on_top, boxes, (W, H))
        root.destroy()

    root.after(800, clicks)
    root.mainloop()
    if not result.get("ok"):
        with open(core.ERROR_LOG, "a", encoding="utf-8") as f:
            f.write(f"{datetime.now()} selftest\n{result.get('detail')}\n{''.join(errors)}\n")
    return 0 if result.get("ok") else 2


def main():
    try:
        ctypes.windll.shcore.SetProcessDpiAwareness(2)
    except (AttributeError, OSError):
        ctypes.windll.user32.SetProcessDPIAware()
    if "--selftest" in sys.argv:
        return selftest()
    running, mutex = already_running()
    if running:
        ctypes.windll.user32.PostMessageW(wintypes.HWND(0xFFFF), SHOW_MSG, 0, 0)
        return 1
    root = tk.Tk()
    app = App(root)
    root.report_callback_exception = app.crash
    app.hwnd = dark_title(root)
    app.frame = Frameless(app, app.hwnd)
    app.tray = Tray(app.hwnd)
    if app.cfg["tray"]:
        app.tray.add()
    stop = threading.Event()
    threading.Thread(target=core.run, args=(lambda: app.cfg, stop, app.foreground), daemon=True).start()

    def close():
        stop.set()
        app.feed.save_sync()
        app.tray.close()
        root.destroy()

    app.close = close
    root.protocol("WM_DELETE_WINDOW", app.close_window)
    root.mainloop()
    return 0


if __name__ == "__main__":
    sys.exit(main())
