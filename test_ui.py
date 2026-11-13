import ctypes
import json
import sys
import tempfile
import tkinter as tk
import traceback
from pathlib import Path

import numpy as np
from PIL import Image

import chat
import core
import ui

FIXTURES = Path(__file__).resolve().parent / "tests" / "fixtures"
NAMES = ("SS_2026-01-01_12-00-00", "SS_2026-01-01_12-05-00")
LOG = [("11:58:10", "* Malachy Doyle стоит возле своего автомобиля.", "#c2a2da"),
       ("11:59:02", "Mia Lopez говорит: Ты видел, кто к нам заехал?", "#e6e6e6"),
       ("12:01:30", "Victor Hale говорит (тихо): Видел. Не смотри туда.", "#e6e6e6"),
       ("12:04:12", "(( Victor Hale: щас вернусь ))", "#afafaf")]


def load(name):
    return np.asarray(Image.open(FIXTURES / name).convert("RGB"))


def prepare(work):
    shots = work / "out"
    (shots / "chatlog").mkdir(parents=True)
    core.CONFIG_PATH = work / "config.ini"
    core.write_raw(dict(core.DEFAULTS, output=str(shots), sound="no", chatlog="no", source="screen", file="jpg",
                        tray="no"))
    cfg = core.load_config()[1]
    for name in NAMES:
        state = {"session": core.Session()}
        state["session"].name = name
        core.handle(load("real_bg.webp"), state, cfg)
        core.handle(load("real_chat_ic.png"), state, cfg)
    (shots / "chatlog" / "2026-01-01.jsonl").write_text(
        "".join(json.dumps({"time": t, "parts": [[text, color]]}, ensure_ascii=False) + "\n" for t, text, color in LOG),
        encoding="utf-8")
    while not core.EVENTS.empty():
        core.EVENTS.get()
    return shots


def popup_hide(feed):
    feed.draw_lines(feed.area())
    j = next(j for j, it in enumerate(feed.items)
             if it[1] is not None and it[0]["rows"][it[1]]["kind"] == chat.SPEECH)
    row = feed.items[j][0]["rows"][feed.items[j][1]]
    feed.open_popup(j, tuple(chat.words(row)[0]))
    feed.popup_pick("hide")


class Key:
    def __init__(self, keycode, state, keysym=""):
        self.keycode, self.state, self.keysym, self.widget = keycode, state, keysym, None


class Mouse:
    def __init__(self, feed, fx, fy):
        ix, iy, dw, dh = feed.painter.geo["img"]
        self.x, self.y, self.state = ix + fx * dw, iy + fy * dh, 0


def drag(feed, a, b):
    feed.press(Mouse(feed, *a))
    feed.motion(Mouse(feed, (a[0] + b[0]) / 2, (a[1] + b[1]) / 2))
    feed.motion(Mouse(feed, *b))
    feed.release(Mouse(feed, *b))


def expect(ok, what):
    if not ok:
        raise AssertionError(what)


def scene(feed):
    feed.set_scene(list(reversed(NAMES)), [dict(core.SEAM)])
    feed.toggle_tool("scene")


def main():
    ctypes.windll.shcore.SetProcessDpiAwareness(2)
    work = Path(tempfile.mkdtemp(prefix="snapline_ui_"))
    shots = prepare(work)
    ui.App.check_update = lambda self: None
    root = tk.Tk()
    root.attributes("-toolwindow", True)
    root.attributes("-alpha", 0.0)
    errors = []
    root.report_callback_exception = lambda *a: (errors.append(a[1]), traceback.print_exception(*a))
    app = ui.App(root)
    root.geometry("1360x860+0+0")
    app.hwnd = ui.dark_title(root)
    app.frame = ui.Frameless(app, app.hwnd)
    feed = app.feed
    steps = [
        (lambda: (app.show("feed"), feed.go(1)), 2000),
        (lambda: feed.toggle_tool("lines"), 1200),
        (lambda: popup_hide(feed), 800),
        (lambda: feed.toggle_tool("logpick"), 1200),
        (lambda: feed.log_show("all"), 600),
        (lambda: feed.toggle_tool("crop"), 1000),
        (lambda: feed.set_frame("800x800"), 1500),
        (lambda: feed.key(Key(90, 0x4)), 1200),
        (lambda: expect(feed.shot["edit"]["format"] != "800x800", "Ctrl+Z did not undo the frame"), 100),
        (lambda: feed.key(Key(89, 0x4)), 1200),
        (lambda: expect(feed.shot["edit"]["format"] == "800x800", "Ctrl+Y did not redo the frame"), 100),
        (lambda: feed.set_frame("square"), 1000),
        (lambda: feed.toggle_tool("text"), 1000),
        (lambda: [feed.change_text(text_scale=v) for v in (1.1, 1.2, 1.3)], 800),
        (lambda: feed.undo(), 800),
        (lambda: expect(feed.shot["edit"]["text_scale"] not in (1.1, 1.2, 1.3), "slider burst is not one undo step"), 100),
        (lambda: feed.undo(back=False), 800),
        (lambda: feed.toggle_tool("images"), 1000),
        (lambda: feed.add_image(Image.new("RGB", (400, 300), (40, 120, 200))), 1200),
        (lambda: feed.change_ov(alpha=0.8), 800),
        (lambda: feed.remove_ov(), 800),
        (lambda: feed.toggle_tool("style"), 1500),
        (lambda: feed.change(preset="film"), 1200),
        (lambda: [feed.change_look("contrast", v) for v in (10, 20)], 1200),
        (lambda: feed.set_style("cctv"), 1500),
        (lambda: feed.set_style("none"), 1000),
        (lambda: feed.change(look={}, preset="none"), 1000),
        (lambda: feed.toggle_tool("blur"), 1200),
        (lambda: drag(feed, (0.3, 0.3), (0.6, 0.5)), 800),
        (lambda: expect(len(feed.shot["edit"].get("blurs", [])) == 1, "drag did not add a blur area"), 100),
        (lambda: drag(feed, (0.45, 0.4), (0.5, 0.45)), 800),
        (lambda: expect(abs(feed.shot["edit"]["blurs"][0]["x"] - 0.35) < 0.02, "drag did not move the area"), 100),
        (lambda: feed.set_blur(mode="pixel", power=0.9), 1000),
        (lambda: drag(feed, (0.1, 0.1), (0.102, 0.102)), 600),
        (lambda: expect(len(feed.shot["edit"]["blurs"]) == 1, "a tiny drag left an area"), 100),
        (lambda: feed.key(Key(46, 0, "Delete")), 800),
        (lambda: expect(not feed.shot["edit"]["blurs"], "Delete did not remove the area"), 100),
        (lambda: feed.undo(), 800),
        (lambda: expect(feed.shot["edit"]["blurs"][0]["mode"] == "pixel", "undo did not bring the area back"), 100),
        (lambda: feed.toggle_tool("file"), 1500),
        (lambda: feed.set_file("png"), 1000),
        (lambda: feed.set_file("jpg"), 1000),
        (lambda: scene(feed), 2500),
        (lambda: feed.toggle_tool("text"), 1000),
        (lambda: feed.set_whole("all"), 2500),
        (lambda: feed.set_whole("one"), 1000),
        (lambda: feed.toggle_tool("text"), 800),
        (lambda: app.show("settings"), 1000),
        (lambda: app.show("feed"), 800),
        (lambda: feed.go(2), 1500),
    ]
    state = {"name": None}

    def run(i=0):
        if i == 1:
            state["name"] = feed.name
        if i >= len(steps):
            feed.save_sync()
            root.after(300, root.destroy)
            return
        try:
            steps[i][0]()
        except Exception as e:
            errors.append(e)
            traceback.print_exc()
        root.after(steps[i][1], lambda: run(i + 1))

    root.after(800, run)
    root.after(120000, root.destroy)
    root.mainloop()
    assert not errors, errors
    assert app.settings.chatlog_stop is None, "chatlog started during the UI test"
    edit = json.loads((shots / "src" / f"{state['name']}.json").read_text(encoding="utf-8"))
    assert edit["format"] == "square" and edit["file"] == "jpg" and edit.get("style") == "none", edit
    assert edit["hidden"] and edit["text_scale"] == 1.3 and not edit["overlays"], edit
    assert edit["blurs"] and edit["blurs"][0]["mode"] == "pixel" and edit["blurs"][0]["power"] == 0.9, edit["blurs"]
    assert edit["scene"] and edit["scene"]["shots"] == list(reversed(NAMES)), edit["scene"]
    print("ui ok")


if __name__ == "__main__":
    sys.exit(main())
