import ctypes
import json
import os
import re
import sys
import tempfile
import time
from collections import deque
from datetime import datetime, timedelta
from pathlib import Path

FROZEN_OUT = tuple(re.findall(r"--exclude-module (\S+)", (Path(__file__).resolve().parent / "build.bat").read_text()))


class FrozenOut:
    def find_spec(self, name, path=None, target=None):
        if any(name == m or name.startswith(m + ".") for m in FROZEN_OUT):
            raise ModuleNotFoundError(f"{name} is excluded from the exe by build.bat")


sys.meta_path.insert(0, FrozenOut())

import numpy as np
from PIL import Image

import chat
import chatlog
import core

SAMPLES = Path(__file__).resolve().parent / "tests" / "fixtures"
A, S, O, SP, AC = chat.AME, chat.SYSTEM, chat.OOC, chat.SPEECH, chat.ACTION


def load(name):
    return np.asarray(Image.open(SAMPLES / name).convert("RGB"))


def scaled(img, w, h):
    return np.asarray(Image.fromarray(img).resize((w, h), Image.LANCZOS))


def make_cfg(out, **kw):
    cfg = {"key": "F11", "auto": True, "hud_key": "F7", "dark_key": "F2", "hud_delay": 0, "out": Path(out),
           "format": "square", "ratio": 1.0, "size": "native", "file": "png", "quality": 92, "chat_pos": "top-left",
           "margin": 24, "text_scale": 1.5, "outline": 2, "keep": (SP, AC), "sound": False, "chatlog": False, "hide_names": False,
           "source": "screen"}
    cfg.update(kw)
    return cfg


def kinds_of(img):
    return [r["kind"] for r in chat.classify(chat.extract_rows(img))]


def check_rows():
    shots = [chat.classify(chat.extract_rows(load(f"chat{i}.webp"))) for i in (1, 2, 3)]
    assert [len(s) for s in shots] == [20, 20, 20], [len(s) for s in shots]
    kinds = [[r["kind"] for r in s] for s in shots]
    assert kinds[0] == [A, S] + [A] * 12 + [S, S, O, S, S, S], kinds[0]
    assert kinds[1] == [S] + [A] * 12 + [S, S, O, S, S, S, SP], kinds[1]
    assert kinds[2] == [A] * 11 + [S, S, O, S, S, S, SP, AC, AC], kinds[2]

    for order in (shots, shots[::-1]):
        merged = []
        for rows in order:
            merged = chat.merge(merged, rows)
        assert len(merged) == 23 and sum(r["keep"] for r in merged) == 3, (len(merged), sum(r["keep"] for r in merged))
    assert chat.merge(merged, shots[1]) is merged

    sys_rows = chat.classify(chat.extract_rows(load("real_chat_sys.png")))
    assert len(sys_rows) == 20 and not any(r["keep"] for r in sys_rows), [r["kind"] for r in sys_rows]
    assert kinds_of(load("real_chat_ic.png")) == [AC, AC, SP]
    wide = load("real_chat_ic.png").copy()
    band = wide[20:100, 20:646].copy()
    for x in (656, 1292):
        np.maximum(wide[20:100, x:x + 626], band, out=wide[20:100, x:x + 626])
    wide_rows = chat.classify(chat.extract_rows(wide))
    ends = [r["glyphs"][-1][1] for r in wide_rows]
    assert [r["kind"] for r in wide_rows] == [AC, AC, SP] and 1900 < max(ends) < 2369, ends
    pm = kinds_of(load("real_chat_pm.png"))
    assert pm == [AC, AC, SP, A, S, A, S] + [S] * 8 + [O, A, A], pm


def check_format():
    assert chat.frame_rect(2560, 1440) == (0, 0, 2560, 1440)
    assert chat.frame_rect(2560, 1440, 1.0) == (560, 0, 2000, 1440)
    assert chat.frame_rect(2560, 1440, 4 / 3) == (320, 0, 2240, 1440)
    assert chat.frame_rect(1080, 1920, 1.0) == (0, 420, 1080, 1500)

    bg = load("real_bg.webp")
    rows = chat.classify(chat.extract_rows(load("real_chat_ic.png")))
    crop = bg[:, 560:2000]
    inked = {}
    for pos in core.CHAT_POSITIONS:
        for scale in (1.0, 1.5):
            img, n, box = chat.compose(crop, rows, 2, pos, 24, scale)
            assert img.shape == (1440, 1440, 3) and n == 3
            ys, xs = np.nonzero((img != crop).any(axis=2))
            inked[pos, scale] = (ys.min(), ys.max(), xs.min(), xs.max())
    t, b, l, r = inked["top-left", 1.5]
    assert t < 40 and l < 40 and b < 200, inked["top-left", 1.5]
    t, b, l, r = inked["bottom-right", 1.5]
    assert b > 1400 and r > 1400, inked["bottom-right", 1.5]
    width = lambda k: inked[k][3] - inked[k][2]
    assert 1.35 < width(("top-left", 1.5)) / width(("top-left", 1.0)) < 1.65


def check_editing():
    assert chat.frame_rect(2560, 1440, 1.0, 2.0) == (920, 360, 1640, 1080)
    assert chat.frame_rect(2560, 1440, 1.0, 2.0, (0, 0)) == (0, 0, 720, 720)
    assert chat.frame_rect(2560, 1440, 1.0, 2.0, (1, 1)) == (1840, 720, 2560, 1440)
    assert chat.place(1440, 1440, 300, 100, 4, (0.5, 0.5), 24) == (716, 716)
    assert chat.place(1440, 1440, 300, 100, 4, [2.0, 2.0], 24) == (1144, 1344)
    assert chat.place(1440, 1440, 300, 100, 4, "bottom-right", 24) == (1120, 1320)

    with tempfile.TemporaryDirectory() as tmp:
        cfg = make_cfg(tmp)
        state = {"session": core.Session()}
        core.handle(load("real_bg.webp"), state, cfg)
        assert core.handle(load("real_chat_pm.png"), state, cfg) is core.TONE_SS
        name = state["session"].name
        assert core.list_shots(Path(tmp)) == [name]

        shot = core.load_shot(Path(tmp), name, cfg)
        assert len(shot["rows"]) == 18 and shot["edit"]["keep"] == [r["keep"] for r in shot["rows"]]
        assert sum(shot["edit"]["keep"]) == 3
        pm = [i for i, r in enumerate(shot["rows"]) if r["kind"] == O][0]
        shot["edit"]["keep"][pm] = True
        shot["edit"].update(pos=[0.3, 0.6], zoom=1.5, format="4:5", center=[0.4, 0.5])
        core.apply_keep(shot["rows"], shot["edit"])
        img, painted = core.save_shot(shot)
        assert img.shape == (960, 768, 3) and painted == 4, (img.shape, painted)

        again = core.load_shot(Path(tmp), name, cfg)
        assert again["edit"]["pos"] == [0.3, 0.6] and again["edit"]["zoom"] == 1.5
        assert again["rows"][pm]["keep"] and sum(r["keep"] for r in again["rows"]) == 4
        with Image.open(Path(tmp) / f"{name}.png") as im:
            assert im.size == (768, 960)

        p = core.plan(again["bg"], again["edit"])
        layer, n, pad = chat.chat_layer(again["rows"], p["outline"], p["scale"], p["size"][1] - 2 * p["margin"])
        left, top = chat.place(*p["size"], layer.shape[1], layer.shape[0], pad, again["edit"]["pos"], p["margin"])
        assert (left + pad, top + pad) == (round(0.3 * 768), round(0.6 * 960))

        assert core.load_shot(Path(tmp), "SS_missing", cfg) is None

        again["edit"].update(format="1000x500", size="4k")
        img, painted = core.save_shot(again)
        assert img.shape == (500, 1000, 3) and painted == 4, (img.shape, painted)
        again["edit"].update(format="4:5", file="jpg", size="900")
        img, _ = core.save_shot(again)
        assert img.shape == (1125, 900, 3) and core.list_shots(Path(tmp)) == [name]
        assert core.shot_image(Path(tmp), name).suffix == ".jpg" and not (Path(tmp) / f"{name}.png").exists()

        src = Path(tmp) / "src"
        for path in [*src.glob("*.jpg"), *src.glob("*.webp")]:
            Image.open(path).save(path.with_suffix(".png"))
            path.unlink()
        legacy = core.load_shot(Path(tmp), name, cfg)
        assert len(legacy["rows"]) == 18 and legacy["edit"]["size"] == "900"
        size, count = core.src_size(Path(tmp))
        assert count == 1 and size > 0
        core.clear_src(Path(tmp))
        assert core.src_size(Path(tmp)) == (0, 0) and core.load_shot(Path(tmp), name, cfg) is None
        assert core.list_shots(Path(tmp)) == [name]


def check_resolutions():
    bg = load("real_bg.webp")
    names = ("real_chat_ic.png", "real_chat_pm.png", "real_chat_sys.png")
    native = {n: kinds_of(load(n)) for n in names}
    for w, h in ((1920, 1080), (3840, 2160)):
        for n in names:
            got = kinds_of(scaled(load(n), w, h))
            assert got == native[n], (w, n, got)
        screen_bg, chat_ic = scaled(bg, w, h), scaled(load("real_chat_ic.png"), w, h)
        for size, side in (("native", h), ("hd", 720), ("fhd", 1080), ("qhd", 1440), ("4k", 2160), ("900", 900)):
            with tempfile.TemporaryDirectory() as tmp:
                cfg = make_cfg(tmp, size=size)
                state = {"session": core.Session()}
                core.handle(screen_bg, state, cfg)
                assert core.handle(chat_ic, state, cfg) is core.TONE_SS
                with Image.open(Path(tmp) / f"{state['session'].name}.png") as im:
                    out = np.asarray(im.convert("RGB"))
                assert out.shape[:2] == (side, side), (w, size, out.shape)
                if size == "native":
                    x0, _, x1, _ = chat.frame_rect(w, h, 1.0)
                    ys, xs = np.nonzero((out != screen_bg[:, x0:x1]).any(axis=2))
                    margin = 24 * h / core.REFERENCE_SIDE
                    assert abs(xs.min() - margin) < 6 and abs(ys.min() - margin) < 6, (w, xs.min(), ys.min())


def check_config():
    saved = core.CONFIG_PATH
    try:
        with tempfile.TemporaryDirectory() as tmp:
            core.CONFIG_PATH = Path(tmp) / "config.ini"
            raw, cfg = core.load_config()
            assert raw == core.DEFAULTS and core.CONFIG_PATH.read_text(encoding="utf-8").startswith("[snapline]")
            raw = dict(raw, size="4k", format="4:5", chat_pos="bottom-right", keep="речь, ooc")
            core.write_raw(raw)
            raw2, cfg2 = core.load_config()
            assert raw2 == raw and cfg2["ratio"] == 0.8 and cfg2["keep"] == (SP, O) and cfg2["size"] == "4k"
            assert core.parse_config(dict(raw, size=" 0900 "))["size"] == "900"
            assert cfg["source"] == "screen" and core.parse_config(dict(raw, source=" Log "))["source"] == "log"
            framed = core.parse_config(dict(raw, format="1200 X 0800"))
            assert framed["format"] == "1200x800" and framed["ratio"] == 1.5
            for bad in (dict(raw, hotkey="F7"), dict(raw, size="8k"), dict(raw, size="100"), dict(raw, size="9000"),
                        dict(raw, format="wide"), dict(raw, format="100x800"), dict(raw, format="1200x0"),
                        dict(raw, file="gif"), dict(raw, text_scale="9"),
                        dict(raw, keep="крики"), dict(raw, sound="maybe"), dict(raw, source="ocr")):
                try:
                    core.parse_config(bad)
                except ValueError:
                    continue
                raise AssertionError(bad)
            core.CONFIG_PATH.write_text("﻿[lspscreen]\nhotkey = F10\n", encoding="utf-8")
            assert core.load_config()[1]["key"] == "F10"
            out = Path(tmp) / "out"
            blocked = FileNotFoundError(2, "not found", str(out / "src"))
            assert "Контролируемый доступ" in core.explain(blocked, {"out": out})
            assert core.explain(OSError("x"), {"out": out}) == "Не получилось: x"
            assert core.check_out({"out": out}) is None and not list((out / "src").iterdir())
    finally:
        core.CONFIG_PATH = saved


def check_session():
    with tempfile.TemporaryDirectory() as tmp:
        cfg = make_cfg(tmp, format="full", ratio=None, text_scale=1.0, outline=1)
        state = {"session": core.Session()}
        bg = load("bg.webp")
        assert not chat.is_chat_shot(bg)

        assert core.handle(load("chat1.webp"), state, cfg) is core.TONE_STEP
        assert core.handle(bg, state, cfg) is core.TONE_FAIL
        t = time.perf_counter()
        assert core.handle(load("chat2.webp"), state, cfg) is core.TONE_SS
        print(f"chat shot -> SS in {time.perf_counter() - t:.2f}s")
        assert core.handle(load("chat3.webp"), state, cfg) is core.TONE_SS

        s = state["session"]
        assert len(s.rows) == 23 and s.chats == 3
        with Image.open(Path(tmp) / f"{s.name}.png") as im:
            out = np.asarray(im.convert("RGB"))
        colw = int(bg.shape[1] * chat.CHAT_COLUMN)
        H, W = bg.shape[:2]
        assert out.shape == bg.shape
        ys, xs = np.nonzero((out[:, colw:] != bg[:, colw:]).any(axis=2))
        assert len(ys) == 0 or (ys.max() < 0.08 * H and xs.min() + colw > 0.88 * W), (ys.max(), xs.min() + colw)
        assert not np.array_equal(out[:, :colw], bg[:, :colw])
        assert sorted(p.suffix for p in (Path(tmp) / "src").iterdir()) == [".jpg", ".json", ".webp", ".webp", ".webp"]


class FakeGame:
    def __init__(self, dark_works=True):
        self.hud_hidden = self.dark = False
        self.dark_works = dark_works
        self.taps = []
        self.bg, self.chat = load("bg.webp"), load("chat3.webp")
        self.with_hud = self.bg.copy()
        self.with_hud[-60:, :300] = 255

    def tap(self, key):
        self.taps.append(key)
        if key == "F7":
            self.hud_hidden = not self.hud_hidden
        elif key == "F2" and self.dark_works:
            self.dark = not self.dark

    def grab(self):
        return self.chat if self.dark else self.bg if self.hud_hidden else self.with_hud


def check_auto():
    assert ctypes.sizeof(core.INPUT) == (40 if ctypes.sizeof(ctypes.c_void_p) == 8 else 28)
    core.DARK_TIMEOUT_S = 0.3
    tap, grab = core.tap, core.grab
    try:
        with tempfile.TemporaryDirectory() as tmp:
            cfg = make_cfg(tmp)
            state = {"session": core.Session()}

            game = FakeGame()
            core.tap, core.grab = game.tap, game.grab
            assert core.on_hotkey(state, cfg) is core.TONE_SS
            assert game.taps == ["F7", "F7", "F2", "F2"], game.taps
            assert not game.hud_hidden and not game.dark
            assert np.array_equal(state["session"].bg, game.bg)
            with Image.open(Path(tmp) / f"{state['session'].name}.png") as out:
                assert out.size == (1125, 1125), out.size

            game.taps, game.dark = [], True
            name = state["session"].name
            assert core.on_hotkey(state, cfg) is core.TONE_SS
            assert game.taps == [] and state["session"].name == name and state["session"].chats == 2

            game = FakeGame(dark_works=False)
            core.tap, core.grab = game.tap, game.grab
            assert core.on_hotkey(state, cfg) is core.TONE_FAIL
            assert game.taps == ["F7", "F7", "F2"], game.taps
    finally:
        core.tap, core.grab = tap, grab


def check_parts():
    rows = chat.classify(chat.extract_rows(load("real_chat_pm.png")))
    for r in rows:
        r["keep"] = True
    edit = core.new_edit(make_cfg("."), rows)
    edit["keep"] = [True] * len(rows)
    assert core.places(edit, 3) == ["top-left", "bottom-left", "top-right"]
    assert core.corner_of([0.22, 0.84]) == "bottom-left"
    assert core.places(dict(edit, pos=[0.8, 0.1]), 2) == [[0.8, 0.1], "bottom-right"]
    assert core.cuts(rows, dict(edit, breaks=[0, 99, 9, 5, 5, 7])) == [5, 7, 9]
    assert core.places(edit, 6) == ["top-left", "bottom-left", "top-right", "bottom-right", "top-left", "bottom-left"]
    assert core.corner_of(["right", 0.1]) == "top-right" and core.corner_of([0.1, "bottom"]) == "bottom-left"
    assert chat.place(1440, 1440, 300, 100, 4, ["left", 0.5], 24) == (20, 716)
    assert chat.place(1440, 1440, 300, 100, 4, [0.3, "bottom"], 24) == (428, 1320)
    layers = [np.zeros((100, 300, 4), np.uint8), np.zeros((80, 200, 4), np.uint8), None, np.zeros((50, 50, 4), np.uint8)]
    spots = core.chat_spots((1440, 1440), layers, ["top-left", "top-left", "top-right", ["right", 0.5]], 4, 24)
    assert spots == [(20, 20), (20, 136), None, (1370, 716)], spots
    wide = [np.zeros((100, 900, 4), np.uint8), np.zeros((60, 900, 4), np.uint8)]
    assert core.chat_spots((1440, 1440), wide, ["bottom-left", "bottom-right"], 4, 24) == [(20, 1320), (520, 1244)]
    bg = load("real_bg.webp")
    one, n1 = core.render(bg, rows, edit)
    two, n2 = core.render(bg, rows, dict(edit, breaks=[9]))
    assert n1 == n2 == len(rows), (n1, n2, len(rows))
    many = list(range(2, len(rows), 2))
    assert len(many) > 3 and core.render(bg, rows, dict(edit, breaks=many))[1] == len(rows)
    assert not (one != core.render(bg, [], edit)[0]).any(axis=2)[2 * one.shape[0] // 3:].any()
    H = two.shape[0]
    frame = core.render(bg, [], edit)[0]
    changed = (two != frame).any(axis=2)
    assert changed[: H // 3].any() and changed[2 * H // 3:].any() and not changed[H // 3:2 * H // 3, : H // 3].any()

    with tempfile.TemporaryDirectory() as tmp:
        cfg = make_cfg(tmp)
        state = {"session": core.Session()}
        core.handle(load("bg.webp"), state, cfg)
        core.handle(load("chat2.webp"), state, cfg)
        name = state["session"].name
        shot = core.load_shot(Path(tmp), name, cfg)
        gone = [i for i, r in enumerate(shot["rows"]) if r["keep"]][0]
        shot["rows"][gone]["keep"] = False
        shot["edit"].update(keep=[r["keep"] for r in shot["rows"]], breaks=[5], places=["bottom-right"])
        core.save_shot(shot)
        core.handle(load("chat3.webp"), state, cfg)
        again = core.load_shot(Path(tmp), name, cfg)
        assert not again["rows"][gone]["keep"] and again["edit"]["breaks"] == [5]
        assert again["edit"]["places"] == ["bottom-right"] and len(again["rows"]) == 22


def check_nicks_overlays():
    rows = chat.classify(chat.extract_rows(load("real_chat_ic.png")))
    assert [len(s) for s in chat.nick_spans(rows)] == [2, 0, 2] and len(chat.words(rows[2])) == 6
    speech = dict(rows[2])
    w = chat.words(speech)
    speech["drop"] = w[:3]
    cols = np.flatnonzero((chat.masked(speech) > chat.INK).any(axis=(0, 2)))
    assert cols[0] == w[0][0] and cols[-1] == w[5][1] - (w[3][0] - w[0][0]), (cols[0], cols[-1], w)
    action = dict(rows[0])
    w = chat.words(action)
    action["drop"] = w[1:3]
    cols = np.flatnonzero((chat.masked(action) > chat.INK).any(axis=(0, 2)))
    assert cols[-1] == w[-1][1] - (w[3][0] - w[1][0])
    assert (chat.masked(action, preview=True).shape == action["rgb"].shape)
    with tempfile.TemporaryDirectory() as tmp:
        cfg = make_cfg(tmp, hide_names=True)
        state = {"session": core.Session()}
        core.handle(load("real_bg.webp"), state, cfg)
        core.handle(load("real_chat_ic.png"), state, cfg)
        name = state["session"].name
        shot = core.load_shot(Path(tmp), name, cfg)
        assert [len(r["hide"]) for r in shot["rows"]] == [2, 0, 2], [r["hide"] for r in shot["rows"]]
        plain = core.render(shot["bg"], [dict(r, hide=[]) for r in shot["rows"]], shot["edit"])[0]
        assert (plain != core.render(shot["bg"], shot["rows"], shot["edit"])[0]).any()
        shot["rows"][2]["hide"], shot["rows"][2]["drop"] = [], chat.words(shot["rows"][2])[:3]
        shot["edit"]["hidden"], shot["edit"]["dropped"] = core.spans_of(shot["rows"], "hide"), core.spans_of(shot["rows"], "drop")
        core.save_shot(shot)
        core.handle(load("real_chat_ic.png"), state, cfg)
        again = core.load_shot(Path(tmp), name, cfg)
        assert again["rows"][2]["drop"] == [tuple(s) for s in chat.words(again["rows"][2])[:3]], again["rows"][2]
        assert again["rows"][2]["hide"] == [] and len(again["rows"][0]["hide"]) == 2

        ov = core.add_overlay(Path(tmp), name, Image.new("RGB", (400, 200), (255, 0, 0)))
        assert ov["file"] == f"{name}_ov1.jpg" and "frame" not in ov
        assert core.crop_for((400, 200), 1.0, (0.5, 0.0, 1.0, 1.0)) == [0.5, 0.0, 1.0, 1.0]
        assert core.crop_exact((400, 200), 100, 100, (0.0, 0.0, 1.0, 1.0)) == [0.375, 0.25, 0.625, 0.75]
        assert core.crop_exact((400, 200), 100, 100, (0.9, 0.0, 1.0, 1.0))[2] == 1.0
        assert core.lock_ratio("4:3") == 4 / 3 and core.lock_ratio("800x600") == 4 / 3 and core.lock_ratio("free") is None
        ov["crop"] = core.crop_for((400, 200), 1.0)
        shot["edit"]["overlays"] = [ov]
        img, _ = core.save_shot(shot)
        x, y, w, h = core.overlay_box(ov, (img.shape[1], img.shape[0]), (400, 200))
        assert w == h and img[y + h // 2, x + w // 2][0] > 200 and img[y + h // 2, x + w // 2][1] < 60
        assert core.load_shot(Path(tmp), name, cfg)["edit"]["overlays"] == [ov]
        sticker = core.add_overlay(Path(tmp), name, Image.new("RGBA", (10, 10), (0, 0, 0, 0)))
        assert sticker["file"] == f"{name}_ov2.png"


def check_reflow():
    rows = chat.classify(chat.extract_rows(load("real_chat_ic.png")))
    first, tail = dict(rows[0]), dict(rows[1])
    assert tail["cont"] and not first["cont"]
    pitch = first["pitch"]
    whole, n, _ = chat.chat_layer([first, tail])
    first["drop"] = chat.words(first)[1:3]
    flowed, n2, _ = chat.chat_layer([first, tail])
    assert n == n2 == 2 and whole.shape[0] - flowed.shape[0] > 0.7 * pitch, (whole.shape, flowed.shape, n2)
    assert flowed.shape[1] <= whole.shape[1]
    first["drop"] = [chat.words(first)[-1]]
    kept, n3, _ = chat.chat_layer([first, tail])
    assert n3 == 2 and abs(kept.shape[0] - whole.shape[0]) < 2, (kept.shape, whole.shape)
    first["drop"] = chat.words(first)
    tail["drop"] = chat.words(tail)
    assert chat.chat_layer([first, tail])[0] is None
    speech = dict(rows[2], drop=chat.words(rows[2])[:1])
    assert np.array_equal(chat._flow([speech], 9999)[0][0], chat.masked(speech))
    first["drop"], tail["drop"] = [chat.words(first)[-1]], []
    wide = dict(rows[2], glyphs=rows[2]["glyphs"] + [(1400, 1410)], keep=False)
    assert chat.chat_layer([first, tail, wide])[0].shape[0] < whole.shape[0] - 0.7 * pitch


def check_carry():
    with tempfile.TemporaryDirectory() as tmp:
        out = Path(tmp)
        cfg = make_cfg(tmp)
        names = []
        for i, (bg, shot) in enumerate((("real_bg.webp", "real_chat_ic.png"), ("real_bg.webp", "real_chat_pm.png"))):
            state = {"session": core.Session()}
            state["session"].name = f"SS_2026-01-01_00-00-0{i}"
            core.handle(load(bg), state, cfg)
            core.handle(load(shot), state, cfg)
            names.append(state["session"].name)
        mine, donor = names
        theirs = core.load_shot(out, donor, cfg)
        theirs["rows"][4]["keep"] = True
        theirs["rows"][5]["hide"] = [chat.words(theirs["rows"][5])[0]]
        theirs["edit"]["keep"] = [r["keep"] for r in theirs["rows"]]
        theirs["edit"]["hidden"] = core.spans_of(theirs["rows"], "hide")
        core.save_shot(theirs)

        shot = core.load_shot(out, mine, cfg)
        shot["edit"]["breaks"] = [1]
        core.apply_keep(shot["rows"], shot["edit"])
        assert core.carry_chat(shot, donor, cfg) == 15
        rows = shot["rows"]
        assert len(rows) == 18 and rows[4]["keep"] and rows[5]["hide"] and shot["edit"]["breaks"] == [1]
        core.save_shot(shot)
        again = core.load_shot(out, mine, cfg)
        assert [r["keep"] for r in again["rows"]] == [r["keep"] for r in rows] and again["rows"][5]["hide"]
        assert again["edit"]["breaks"] == [1]
        assert sorted(p.name for p in (out / "src").glob(f"{mine}_chat*")) == [f"{mine}_chat1.webp",
                                                                               f"{mine}_chat2.webp"]
        assert core.carry_chat(again, donor, cfg) == 0

        state = {"session": core.Session()}
        state["session"].name, state["session"].bg = mine, again["bg"]
        state["session"].rows = [dict(r) for r in again["rows"][:3]]
        assert core.handle(load("real_chat_ic.png"), state, cfg) is core.TONE_SS
        assert (out / "src" / f"{mine}_chat3.webp").exists() and len(state["session"].rows) == 18
        assert [r["keep"] for r in core.load_shot(out, mine, cfg)["rows"]] == [r["keep"] for r in rows]

        state = {"session": core.Session()}
        state["session"].name = "SS_2026-01-01_00-00-09"
        core.handle(scaled(load("real_bg.webp"), 1920, 1080), state, cfg)
        core.handle(scaled(load("real_chat_ic.png"), 1920, 1080), state, cfg)
        try:
            core.carry_chat(core.load_shot(out, mine, cfg), state["session"].name, cfg)
        except ValueError:
            pass
        else:
            raise AssertionError("carried a chat from another resolution")
        listed = core.list_shots(out)
        assert mine not in core.donors(out, mine, listed) and set(core.donors(out, mine, listed)) == set(listed) - {mine}


def check_order():
    with tempfile.TemporaryDirectory() as tmp:
        out = Path(tmp)
        names = ["SS_2026-01-01_00-00-00", "SS_2026-01-01_00-00-05", "SS_2026-01-02_10-00-00"]
        for name in names:
            Image.new("RGB", (4, 4)).save(out / f"{name}.png")
        odd = out / "SS_моя.jpg"
        Image.new("RGB", (4, 4)).save(odd)
        future = time.time() + 3600
        os.utime(out / f"{names[0]}.png", (future, future))
        os.utime(odd, (0, 0))
        assert core.list_shots(out) == names[::-1] + ["SS_моя"], core.list_shots(out)


def check_join():
    with tempfile.TemporaryDirectory() as tmp:
        out = Path(tmp)
        cfg = make_cfg(out)
        bg, shot = load("real_bg.webp"), load("real_chat_ic.png")
        rows = chat.classify(chat.extract_rows(shot), cfg["keep"])
        plain = core.render(bg, [], core.new_edit(cfg, rows))[0]
        for side in core.JOIN_SIDES:
            edit = core.new_edit(cfg, rows)
            edit["join"] = {"side": side, "size": 0.5, "fade": 0.3}
            p = core.plan(bg, edit)
            img = core.render(bg, [], edit)[0]
            assert (img.shape[1], img.shape[0]) == p["size"] and p["base"] == (1440, 1440), (side, p["size"])
            ax, ay = p["at"]
            keep = img[ay:ay + 1440, ax:ax + 1440]
            inner = slice(0, 1000) if side in ("right", "bottom") else slice(440, 1440)
            part = (keep[:, inner], plain[:, inner]) if side in ("left", "right") else (keep[inner], plain[inner])
            assert np.array_equal(*part), side
        assert core.render(bg, rows, edit)[1] == sum(r["keep"] for r in rows)
        edit["join"].update(side="none")
        assert core.plan(bg, edit)["size"] == (1440, 1440) and np.array_equal(core.render(bg, [], edit)[0], plain)
        ov = core.add_overlay(out, "SS_j", Image.new("RGB", (800, 600), (200, 30, 30)))
        sticker = core.add_overlay(out, "SS_j", Image.new("RGBA", (80, 60), (0, 0, 0, 0)))
        assert ov["file"].endswith(".jpg") and ov["soft"] > 0 and sticker["file"].endswith(".png") and not sticker["soft"]
        edit = core.new_edit(cfg, rows)
        edit["overlays"] = [dict(ov, x=0.25, y=0.5, w=0.5, soft=0.5, alpha=1.0)]
        img = core.render(bg, [], edit, out / "src")[0].astype(int)
        red = lambda px: abs(px - (200, 30, 30)).max() <= 3
        assert red(img[720, 2]) and red(img[720, 360]) and not red(img[720, 715]), (img[720, 2], img[720, 715])
        edit["join"] = {"side": "bottom", "size": 0.5, "fade": 0.3}
        p = core.plan(bg, edit)
        fit = core.fit_field(dict(ov), p, (800, 600))
        x, y, w, h = core.overlay_box(fit, p["size"], (800, 600))
        assert (x, y + h, w) == (0, 2160, 1440) and abs(y - 1080) <= 2, (x, y, w, h)
        assert core.soft_edges((x, y, w, h), p["size"]) == (False, True, False, False)
        edit["join"] = None
        edit["overlays"][0].update(soft=0.0, alpha=0.5)
        img = core.render(bg, [], edit, out / "src")[0].astype(int)
        assert abs(img[720, 360] - (plain[720, 360] + np.array((200, 30, 30))) / 2).max() <= 2


def check_quality():
    with tempfile.TemporaryDirectory() as tmp:
        out = Path(tmp)
        cfg = make_cfg(out, file="jpg")
        bg, shot = load("real_bg.webp"), load("real_chat_ic.png")
        rows = chat.classify(chat.extract_rows(shot), cfg["keep"])
        edit = core.new_edit(cfg, rows)
        clean = core.render(bg, rows, edit)[0]
        text = (clean != core.render(bg, [], edit)[0]).any(axis=2)
        sizes, text_err, bg_err = [], [], []
        for quality in (92, 40, 10):
            edit["quality"] = quality
            data = core.encoded({"bg": bg, "rows": rows, "edit": edit, "out": out})[2]
            diff = np.abs(core.decoded(data).astype(int) - clean.astype(int))
            sizes.append(len(data))
            text_err.append(diff[text].mean())
            bg_err.append(diff[~text].mean())
        assert sizes[0] > sizes[1] > sizes[2] and sizes[2] < sizes[0] * 0.75, sizes
        assert max(text_err) < text_err[0] + 1.5 and bg_err[2] > bg_err[0] * 1.5, (text_err, bg_err)


def check_grain():
    clean = load("real_bg.webp")
    size = (clean.shape[1] * 9 // 16, clean.shape[0] * 9 // 16)
    assert np.array_equal(core.shrink(clean, size), scaled(clean, *size))
    noise = (np.asarray(Image.effect_noise(clean.shape[1::-1], 40), np.float32)[..., None] - 127.5) / 16
    noisy = np.clip((clean + noise).round(), 0, 255).astype(np.uint8)
    plain, kept = scaled(noisy, *size), core.shrink(noisy, size)
    native = core.grain(noisy)
    assert core.grain(plain) < native * 0.8, (core.grain(plain), native)
    assert abs(core.grain(kept) - native) < native * 0.2, (core.grain(kept), native)
    assert np.abs(kept.mean((0, 1)) - plain.mean((0, 1))).max() < 0.5


def check_watermark():
    bg, shot = load("real_bg.webp"), load("real_chat_ic.png")
    mark = core.watermark(shot)
    assert mark is not None and mark["t"].shape[1] > 120, None if mark is None else mark["t"].shape
    clean = core.clean_bg(bg, mark)
    ys, xs = np.nonzero((clean != bg).any(axis=2))
    assert ys.min() > 1300 and xs.min() > 2300, (ys.min(), xs.min())
    assert np.array_equal(core.clean_bg(clean, mark), clean)
    assert core.clean_bg(bg, None) is bg
    assert core.watermark(np.zeros((1440, 2560, 3), np.uint8)) is None
    example = Path(__file__).resolve().parent / "samples"
    rows = chat.classify(chat.extract_rows(core.read_image(example / "example_chat.png")))
    assert [r["kind"] for r in rows if r["keep"]] and core.read_image(example / "example_bg.webp").shape == (1440, 2560, 3)


def check_scene():
    with tempfile.TemporaryDirectory() as tmp:
        out = Path(tmp)
        cfg = make_cfg(out)
        names = []
        for i, size in enumerate((None, None, (1920, 1080))):
            state = {"session": core.Session()}
            state["session"].name = f"SS_2026-01-01_00-00-0{i}"
            bg, shot = load("real_bg.webp"), load("real_chat_ic.png")
            if size:
                bg, shot = scaled(bg, *size), scaled(shot, *size)
            core.handle(bg, state, cfg)
            core.handle(shot, state, cfg)
            names.append(state["session"].name)
        first, head, last = names
        trio = [core.load_shot(out, n, cfg) for n in names]
        kept = [i for i, r in enumerate(trio[1]["rows"]) if r["keep"]]
        assert kept and core.repeats(trio) == [[], kept, []], core.repeats(trio)
        whole = core.load_shot(out, head, cfg)
        single, painted = core.render_shot(whole)
        seams = [dict(core.SEAM, dark=0.0), dict(core.SEAM, dark=0.0), dict(core.SEAM, dark=0.0)]
        whole["edit"]["scene"] = {"shots": [first, "SS_2026-01-01_09-09-09", head, last], "seams": seams}
        layout = {}
        img, n = core.render_shot(whole, layout=layout)
        assert img.shape == (3 * 1440 - 2 * 288, 1440, 3) and n == painted, (img.shape, n, painted)
        assert {k: layout[k] for k in ("tops", "heights", "laps")} == {
            "tops": [0, 1152, 2304], "heights": [1440] * 3, "laps": [288, 288]}, layout
        assert layout["spans"] == [(0, 1296), (1296, 2448), (2448, 3744)] and len(layout["chats"]) == 3
        mine = [c for c in layout["chats"] if c[0] == 1][0]
        assert 1296 <= mine[3] < 1500, mine
        moved, there = dict(whole, edit=dict(whole["edit"], home=last)), {}
        core.render_shot(moved, layout=there)
        box = [c for c in there["chats"] if c[0] == 1][0]
        theirs = [c for c in there["chats"] if c[0] == 2][0]
        assert theirs[3] >= box[3] + box[5] - 2 * there["pads"][1] and box[3] + there["pads"][1] > 2448, (box, theirs)
        cut = len(whole["rows"]) // 2
        split, apart = dict(whole, edit=dict(whole["edit"], breaks=[cut], home=[None, last])), {}
        core.render_shot(split, layout=apart)
        mine = sorted((c for c in apart["chats"] if c[0] == 1), key=lambda c: c[1])
        assert cut and len(mine) == 2 and 1296 <= mine[0][3] < 2448 <= mine[1][3] + apart["pads"][1], mine
        assert core.homes_of(whole["rows"], {"breaks": [cut], "home": [None]}) == [None, None]
        assert core.homes_of(whole["rows"], {"breaks": [cut], "home": last}) == [last, last]
        seam, where = dict(whole, edit=dict(whole["edit"], pos=[0.1, 1.02])), {}
        core.render_shot(seam, layout=where)
        box = [c for c in where["chats"] if c[0] == 1][0]
        assert 2448 < box[3] + where["pads"][1] < 2448 + 60, box
        assert core.inset([288, 288], 0) == (0, 144) and core.inset([288, 288], 1) == (144, 144)
        assert core.inset([288, 288], 2) == (144, 0)
        bare = dict(whole, rows=[], members={n: dict(core.frame_shot(out, n, cfg), rows=[]) for n in (first, last)})
        plain = core.render_shot(bare)[0]
        assert np.array_equal(plain[1440:2304], core.render(whole["bg"], [], whole["edit"])[0][288:1152])
        changed = (img != plain).any(axis=2)
        assert changed[:200].any() and not changed[1152:1152 + 144].any() and changed[1152 + 144:1152 + 400].any()
        mid = img[1152 + 144].astype(float).mean(), img[2304 + 144].astype(float).mean()
        seams[2]["dark"] = 0.5
        img = core.render_shot(whole)[0]
        assert img[1152 + 144].astype(float).mean() == mid[0] and img[2304 + 144].astype(float).mean() < mid[1] * 0.7
        whole["edit"]["scene"]["shots"] = [head, last, first]
        img = core.render_shot(whole)[0]
        assert np.array_equal(img[:1152], single[:1152])
        for s in seams:
            s["fade"] = 0.0
        assert core.render_shot(whole)[0].shape[0] == 3 * 1440
        whole["edit"]["format"] = "800x800"
        assert core.render_shot(whole)[0].shape == (3 * 800, 800, 3)
        assert core.load_shot(out, last, cfg)["edit"]["format"] == "square"
        whole["edit"]["format"] = "square"
        core.save_shot(whole)
        assert Image.open(core.shot_image(out, head)).size == (1440, 3 * 1440)
        assert core.scenes_with(out, last) == [head] and core.scenes_with(out, head) == []
        before = core.read_image(core.shot_image(out, head))
        other = core.load_shot(out, last, cfg)
        other["edit"]["zoom"] = 2.0
        core.save_shot(other)
        after = core.read_image(core.shot_image(out, head))
        assert np.array_equal(after[:1440], before[:1440]) and np.array_equal(after[2880:], before[2880:])
        assert not np.array_equal(after[1440:2880], before[1440:2880])
        whole["edit"]["scene"]["shots"] = [head, "SS_2026-01-01_09-09-09"]
        assert core.scene_of(whole) is None and core.render_shot(whole)[0].shape == single.shape

ME, TALK, SYS, GREY = "#c2a2da", "#e6e6e6", "#ffffff", "#a0a0a0"


def check_log():
    assert core.hex_color("rgb(194, 162, 218)") == ME and core.hex_color("#FFFF90") == "#FFFF90"
    assert core.hex_color("transparent") == TALK
    assert core.log_entry("[19:10:00] * Malachy Doyle курит.", True) == ("19:10:00", [["* Malachy Doyle курит.", ME]])
    assert core.log_entry("[19:10:00]  ", True) is None and core.log_entry("{broken", False) is None
    line = {"text": "Malachy Doyle говорит: Ну и срань, - *щёлкает каналы*",
            "parts": [[" Malachy Doyle говорит: Ну и срань, - ", "rgb(230, 230, 230)"], ["*щёлкает каналы* ", "rgb(194, 162, 218)"]]}
    assert chatlog.parts(line) == [["Malachy Doyle говорит: Ну и срань, - ", TALK], ["*щёлкает каналы*", ME]]
    assert chatlog.parts({"text": "* кто-то", "parts": [["другое", "rgb(1, 2, 3)"]]}) == [["* кто-то", ME]]
    assert chatlog.fresh(["a", "b", "c", "d"], deque(["x", "a", "b"])) == ["c", "d"]
    assert chatlog.fresh(["b", "c", "d"], deque(["a", "b", "c"])) == ["d"] and chatlog.fresh(["a"], deque(["a"])) == []
    assert chatlog.fresh(["a", "b"], deque()) == ["a", "b"] and chatlog.fresh(["c"], deque(["a", "b"])) == ["c"]

    talk = [["Malachy Doyle говорит: Ну и срань, - ", TALK], ["*продолжает щелкать каналы один за другим, пепелит "
                                                              "прямо на диван.*", ME]]
    me = [["* Malachy Doyle сидит напротив телевизора у себя в пабе, без энтузиазма переключает каналы.", ME]]
    script = [("19:00:00", [["* Malachy Doyle выходит из дома.", ME]]),
              ("19:08:00", [["> Ваш транспорт Vigero '68 заспавнен.", "#4caf50"]]),
              ("19:09:00", [["* Malachy Doyle паркуется у паба.", ME]]),
              ("19:12:00", [["(( [5] Malachy Doyle: sps ))", GREY]]),
              ("19:17:00", me), ("19:18:00", [[">", "#ffd040"], [" Телепортация на вход бизнеса.", SYS]]),
              ("19:20:10", talk), ("19:21:00", [["* Malachy Doyle встаёт.", ME]]),
              ("20:30:00", [["* Malachy Doyle уходит.", ME]])]
    with tempfile.TemporaryDirectory() as tmp:
        out = Path(tmp)
        cfg = make_cfg(tmp, file="png")
        folder = out / "chatlog"
        folder.mkdir()
        (folder / "2026-11-08.jsonl").write_text(
            "".join(json.dumps({"time": t, "parts": p}, ensure_ascii=False) + "\n" for t, p in script) + "oops\n",
            encoding="utf-8")
        (folder / "2026-11-07.txt").write_text("[23:59:30] * Malachy Doyle зевает.\n", encoding="utf-8")
        when = datetime(2026, 11, 8, 19, 20, 24)
        lines = core.read_log(out, when)
        assert [l[0].strftime("%H:%M") for l in lines] == ["19:00", "19:08", "19:09", "19:12", "19:17", "19:18",
                                                           "19:20", "19:21"]
        assert len(core.read_log(out, datetime(2026, 11, 8, 0, 5))) == 1
        assert core.log_chunks(lines) == [0, 1, 4] and core.log_chunks([]) == []

        rows = chat.classify(chat.extract_rows(core.log_frame(lines[1:7], (2560, 1440))))
        assert [r["kind"] for r in rows] == [S, AC, O, AC, AC, S, AC, AC], [r["kind"] for r in rows]
        assert rows[4]["cont"]

        name = "SS_2026-11-08_19-20-24"
        bg = load("bg.webp")
        core.save_src(bg, cfg, f"{name}_bg", core.SRC_BG)
        shot = {"name": name, "out": out, "bg": bg, "rows": [], "edit": core.new_edit(cfg, []), "cfg": cfg}
        picked = lines[3:7]
        assert core.use_log(shot, cfg, picked) == 6 and all(r["keep"] for r in shot["rows"])
        assert core.shot_files(out, name)[1] == [core.log_path(out, name)]
        assert core.picked_log(shot["edit"]) == picked
        assert {core.log_key(*l) for l in core.picked_log(shot["edit"])} == {core.log_key(*l) for l in picked}
        assert core.picked_log({"log": [{"at": "вчера", "parts": []}]}) == [] and core.picked_log({}) == []
        assert core.save_shot(shot)[1] == 6
        again = core.load_shot(out, name, cfg)
        assert all(again["edit"]["keep"]) and len(again["rows"]) == 6 and core.picked_log(again["edit"]) == picked
        try:
            core.carry_chat(again, name, cfg)
            raise AssertionError("carry into a chatlog shot")
        except ValueError:
            pass
        (out / "src" / f"{name}_chat1.webp").write_bytes((SAMPLES / "chat1.webp").read_bytes())
        assert core.use_screen(again, cfg) > 0 and not core.log_path(out, name).exists()
        assert again["edit"]["breaks"] == [] and core.picked_log(again["edit"]) == picked
        core.save_shot(again)
        assert core.load_shot(out, name, cfg)["edit"]["keep"] == again["edit"]["keep"] != shot["edit"]["keep"]

        empty = dict(shot, name="SS_2026-11-08_23-50-00", rows=[], edit=core.new_edit(cfg, []))
        core.save_src(bg, cfg, f"{empty['name']}_bg", core.SRC_BG)
        assert core.use_log(empty, cfg, []) == 0 and empty["rows"] == []
        assert core.save_shot(empty)[1] == 0 and core.load_shot(out, empty["name"], cfg)["rows"] == []
        assert core.log_path(out, empty["name"]).exists()

    t = datetime(2026, 11, 8, 19, 0)
    tagged = [[["[Информация] ", "#ffff90"], ["Лавка пожертвования ветеранам боевых действий.", SYS]],
              [["[REPORT]: ", "#fcc419"], ["Ваша жалоба доставлена администрации сервера. Пожалуйста, ожидайте ответа "
                                           "от администрации.", SYS]],
              [["[!] ", "#9e5cb6"], ["Zeke Garthie говорит (к Malachy Doyle): А то ты не знаешь, как это бывает? "
                                     "Забухаешь где-то, потом только через дня два домой.", TALK]],
              [["Joshua Norman говорит: Давай его.. Светлое.", TALK]]]
    rows = chat.classify(chat.extract_rows(core.log_frame([(t, p) for p in tagged], (2560, 1440))))
    assert [r["kind"] for r in rows] == [S, S, S, SP, SP, SP], [r["kind"] for r in rows]
    assert [r["mark"] for r in rows][:4] == ["[", "[", None, "["] and rows[2]["cont"]

    tap, grab = core.tap, core.grab
    try:
        with tempfile.TemporaryDirectory() as tmp:
            cfg = make_cfg(tmp, source="log")
            log = chatlog.Log(Path(tmp) / "chatlog")
            log.write([{"text": me[0][0], "parts": [[me[0][0], "rgb(194, 162, 218)"]]}])
            assert (Path(tmp) / "chatlog" / f"{datetime.now():%Y-%m-%d}.txt").exists()
            log.status("Чат найден")
            assert chatlog.Log(Path(tmp) / "chatlog").tail(5) == [me[0][0]]
            assert "Чат найден" in (Path(tmp) / "chatlog" / "status.log").read_text(encoding="utf-8")
            game = FakeGame()
            core.tap, core.grab = game.tap, game.grab
            state = {"session": core.Session()}
            assert core.on_hotkey(state, cfg) is core.TONE_SS
            assert game.taps == ["F7", "F7"], game.taps
            shot = core.load_shot(Path(tmp), state["session"].name, cfg)
            assert shot["rows"] == [] and core.log_path(Path(tmp), shot["name"]).exists()
            game.taps = []
            state = {"session": core.Session()}
            time.sleep(1.1)
            assert core.on_hotkey(state, dict(cfg, auto=False)) is core.TONE_SS and game.taps == []
            assert core.load_shot(Path(tmp), state["session"].name, cfg)["rows"] == []
    finally:
        core.tap, core.grab = tap, grab


if __name__ == "__main__":
    check_rows()
    check_format()
    check_watermark()
    check_editing()
    check_resolutions()
    check_config()
    check_session()
    check_auto()
    check_parts()
    check_nicks_overlays()
    check_reflow()
    check_carry()
    check_order()
    check_join()
    check_quality()
    check_grain()
    check_scene()
    check_log()
    print("ok")
