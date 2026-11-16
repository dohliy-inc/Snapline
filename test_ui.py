import ctypes
import json
import sys
import tempfile
import tkinter as tk
import traceback
from pathlib import Path

import numpy as np
from PIL import Image

import capture
import chat
import compose
import config
import ui
import winui

FIXTURES = Path(__file__).resolve().parent / "tests" / "fixtures"
NAMES = ("SS_2026-01-01_12-00-00", "SS_2026-01-01_12-05-00")
DOOMED = "SS_2026-01-01_11-00-00"
LOG = [("11:58:10", "* Malachy Doyle стоит возле своего автомобиля.", "#c2a2da"),
       ("11:59:02", "Mia Lopez говорит: Ты видел, кто к нам заехал?", "#e6e6e6"),
       ("12:01:30", "Victor Hale говорит (тихо): Видел. Не смотри туда.", "#e6e6e6"),
       ("12:04:12", "(( Victor Hale: щас вернусь ))", "#afafaf")]


def load(name):
    return np.asarray(Image.open(FIXTURES / name).convert("RGB"))


def prepare(work):
    shots = work / "out"
    (shots / "chatlog").mkdir(parents=True)
    config.CONFIG_PATH = work / "config.ini"
    config.write_raw(dict(config.DEFAULTS, output=str(shots), sound="no", chatlog="no", source="screen", file="jpg",
                        tray="no", tour="no"))
    cfg = config.load_config()[1]
    for name in NAMES + (DOOMED,):
        state = {"session": capture.Session()}
        state["session"].name = name
        capture.handle(load("real_bg.webp"), state, cfg)
        capture.handle(load("real_chat_ic.png"), state, cfg)
    (shots / "chatlog" / "2026-01-01.jsonl").write_text(
        "".join(json.dumps({"time": t, "parts": [[text, color]]}, ensure_ascii=False) + "\n" for t, text, color in LOG),
        encoding="utf-8")
    while not config.EVENTS.empty():
        config.EVENTS.get()
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


def tilted_pan(feed):
    cx, cy = feed.shot["edit"]["center"]
    drag(feed, (0.5, 0.5), (0.6, 0.5))
    nx, ny = feed.shot["edit"]["center"]
    expect(nx < cx - 0.01 and ny > cy + 0.005, f"pan under tilt went the wrong way: {(cx, cy)} -> {(nx, ny)}")


def crop_turned(feed):
    ov, box = feed.shot["edit"]["overlays"][0], feed.painter.geo["overlays"][0]
    x0, y0 = ov["x"], ov["y"]
    feed.drag = {"kind": "crop", "handle": "r", "part": 0, "x": 500, "y": 500, "crop": list(ov["crop"]),
                 "box": dict(box), "size": feed.source_size(ov)}
    point = type("Point", (), {"x": 500, "y": 500 - box["w"] / 4})()
    feed.drag_crop(point, feed.painter.geo)
    feed.drag = None
    expect(ov["crop"][2] < 0.9 and ov["y"] < y0 - 0.01 and abs(ov["x"] - x0) < 0.002,
           f"cropping a turned picture went the wrong way: {ov}")


def grab_picture(feed):
    ov, box = feed.shot["edit"]["overlays"][0], feed.painter.geo["overlays"][0]
    x, y, x0 = box["x"] + box["w"] // 2, box["y"] + box["h"] // 2, ov["x"]
    feed.c.event_generate("<Motion>", x=x, y=y)
    feed.c.event_generate("<ButtonPress-1>", x=x, y=y)
    feed.c.event_generate("<Motion>", x=x + 40, y=y, state=0x100)
    feed.c.event_generate("<ButtonRelease-1>", x=x + 40, y=y, state=0x100)
    expect(ov["x"] > x0 + 0.01, f"the picture did not follow the mouse: {x0} -> {ov['x']}")


def scene(feed):
    feed.set_scene(list(reversed(NAMES)), [dict(compose.SEAM)])
    feed.toggle_tool("scene")


def main():
    ctypes.windll.shcore.SetProcessDpiAwareness(2)
    work = Path(tempfile.mkdtemp(prefix="snapline_ui_"))
    shots = prepare(work)
    ui.App.check_update = lambda self: None
    winui.recycle = lambda paths: [p.unlink() for p in paths]
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
        (lambda: feed.mirror_frame(), 1000),
        (lambda: expect(feed.shot["edit"]["mirror"], "mirror did not turn on"), 100),
        (lambda: feed.mirror_frame(), 800),
        (lambda: feed.change(zoom=1.5, tilt=30), 1000),
        (lambda: tilted_pan(feed), 1200),
        (lambda: feed.mirror_frame(), 800),
        (lambda: expect(feed.shot["edit"]["tilt"] == -30 and feed.shot["edit"]["mirror"], "mirror kept the tilt sign"), 100),
        (lambda: feed.mirror_frame(), 600),
        (lambda: feed.change(zoom=1.0, tilt=0, center=[0.5, 0.5]), 800),
        (lambda: feed.toggle_tool("text"), 1000),
        (lambda: [feed.change_text(text_scale=v) for v in (1.1, 1.2, 1.3)], 800),
        (lambda: feed.undo(), 800),
        (lambda: expect(feed.shot["edit"]["text_scale"] not in (1.1, 1.2, 1.3), "slider burst is not one undo step"), 100),
        (lambda: feed.undo(back=False), 800),
        (lambda: feed.toggle_tool("images"), 1000),
        (lambda: feed.add_image(Image.new("RGB", (400, 300), (40, 120, 200))), 1200),
        (lambda: feed.change_ov(alpha=0.8), 800),
        (lambda: (feed.flip_ov(), feed.turn_ov()), 1000),
        (lambda: expect(feed.shot["edit"]["overlays"][0]["flip"] and feed.shot["edit"]["overlays"][0]["angle"] == 90,
                        "flip or turn did not apply to the picture"), 100),
        (lambda: crop_turned(feed), 1000),
        (lambda: feed.change_ov(angle=30), 800),
        (lambda: grab_picture(feed), 800),
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
        (lambda: app.start_tour(), 1500),
        (lambda: expect(feed.tour is not None and feed.tour.k == 0 and feed.c.find_withtag("tour"), "tour did not start"), 100),
        (lambda: feed.tour.next(), 600),
        (lambda: feed.toggle_tool("lines"), 1200),
        (lambda: expect(feed.tour.k == 2, f"tour did not move on after opening Lines: step {feed.tour.k}"), 100),
        (lambda: [feed.tour.next() for _ in range(4)], 800),
        (lambda: expect(feed.tour.k == 6 and feed.c.find_withtag("tour-next"), "tour did not reach the last step"), 100),
        (lambda: feed.tour.next(), 600),
        (lambda: expect(feed.tour is None and not app.cfg["tour"], "finishing the tour did not save it as done"), 100),
        (lambda: app.start_tour(), 1200),
        (lambda: feed.key(Key(27, 0, "Escape")), 600),
        (lambda: expect(feed.tour is None and not feed.c.find_withtag("tour"), "Escape did not close the tour"), 100),
        (lambda: feed.toggle_tool("lines"), 800),
        (lambda: app.show("feed"), 800),
        (lambda: feed.go(2), 1500),
        (lambda: feed.go(3), 1500),
        (lambda: (feed.delete(), expect(feed.doomed == DOOMED and feed.name == DOOMED, "first click deleted at once")), 600),
        (lambda: feed.delete(), 2500),
        (lambda: expect(DOOMED not in feed.names and feed.index == 2 and not (shots / f"{DOOMED}.jpg").exists()
                        and not list((shots / "src").glob(f"{DOOMED}*")), "delete left the shot behind"), 100),
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
    assert edit["hidden"] and edit["text_scale"] == 1.3 and not edit["overlays"] and not edit["mirror"], edit
    assert edit["blurs"] and edit["blurs"][0]["mode"] == "pixel" and edit["blurs"][0]["power"] == 0.9, edit["blurs"]
    assert edit["scene"] and edit["scene"]["shots"] == list(reversed(NAMES)), edit["scene"]
    print("ui ok")


if __name__ == "__main__":
    sys.exit(main())
