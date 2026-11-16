import ctypes
import hashlib
import json
import os
import re
import sys
import tempfile
import time
from collections import deque
from datetime import datetime
from pathlib import Path

FROZEN_OUT = tuple(re.findall(r"--exclude-module (\S+)", (Path(__file__).resolve().parent / "build.bat").read_text()))


class FrozenOut:
    def find_spec(self, name, path=None, target=None):
        if any(name == m or name.startswith(m + ".") for m in FROZEN_OUT):
            raise ModuleNotFoundError(f"{name} is excluded from the exe by build.bat")


sys.meta_path.insert(0, FrozenOut())

import numpy as np
from PIL import Image

import capture
import chat
import chatlog
import compose
import config
import store
import styles

SAMPLES = Path(__file__).resolve().parent / "tests" / "fixtures"
GOLDEN = SAMPLES.parent / "golden.json"
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
    for pos in config.CHAT_POSITIONS:
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
        state = {"session": capture.Session()}
        capture.handle(load("real_bg.webp"), state, cfg)
        assert capture.handle(load("real_chat_pm.png"), state, cfg) is capture.TONE_SS
        name = state["session"].name
        assert store.list_shots(Path(tmp)) == [name]

        shot = store.load_shot(Path(tmp), name, cfg)
        assert len(shot["rows"]) == 18 and shot["edit"]["keep"] == [r["keep"] for r in shot["rows"]]
        assert sum(shot["edit"]["keep"]) == 3
        pm = [i for i, r in enumerate(shot["rows"]) if r["kind"] == O][0]
        shot["edit"]["keep"][pm] = True
        shot["edit"].update(pos=[0.3, 0.6], zoom=1.5, format="4:5", center=[0.4, 0.5])
        compose.apply_keep(shot["rows"], shot["edit"])
        img, painted = store.save_shot(shot)
        assert img.shape == (960, 768, 3) and painted == 4, (img.shape, painted)

        again = store.load_shot(Path(tmp), name, cfg)
        assert again["edit"]["pos"] == [0.3, 0.6] and again["edit"]["zoom"] == 1.5
        assert again["rows"][pm]["keep"] and sum(r["keep"] for r in again["rows"]) == 4
        with Image.open(Path(tmp) / f"{name}.png") as im:
            assert im.size == (768, 960)

        p = compose.plan(again["bg"], again["edit"])
        layer, n, pad = chat.chat_layer(again["rows"], p["outline"], p["scale"], p["size"][1] - 2 * p["margin"])
        left, top = chat.place(*p["size"], layer.shape[1], layer.shape[0], pad, again["edit"]["pos"], p["margin"])
        assert (left + pad, top + pad) == (round(0.3 * 768), round(0.6 * 960))

        assert store.load_shot(Path(tmp), "SS_missing", cfg) is None

        again["edit"].update(format="1000x500", size="4k")
        img, painted = store.save_shot(again)
        assert img.shape == (500, 1000, 3) and painted == 4, (img.shape, painted)
        again["edit"].update(format="4:5", file="jpg", size="900")
        img, _ = store.save_shot(again)
        assert img.shape == (1125, 900, 3) and store.list_shots(Path(tmp)) == [name]
        assert store.shot_image(Path(tmp), name).suffix == ".jpg" and not (Path(tmp) / f"{name}.png").exists()

        src = Path(tmp) / "src"
        for path in [*src.glob("*.jpg"), *src.glob("*.webp")]:
            Image.open(path).save(path.with_suffix(".png"))
            path.unlink()
        legacy = store.load_shot(Path(tmp), name, cfg)
        assert len(legacy["rows"]) == 18 and legacy["edit"]["size"] == "900"
        size, count = store.src_size(Path(tmp))
        assert count == 1 and size > 0
        store.clear_src(Path(tmp))
        assert store.src_size(Path(tmp)) == (0, 0) and store.load_shot(Path(tmp), name, cfg) is None
        assert store.list_shots(Path(tmp)) == [name]


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
                state = {"session": capture.Session()}
                capture.handle(screen_bg, state, cfg)
                assert capture.handle(chat_ic, state, cfg) is capture.TONE_SS
                with Image.open(Path(tmp) / f"{state['session'].name}.png") as im:
                    out = np.asarray(im.convert("RGB"))
                assert out.shape[:2] == (side, side), (w, size, out.shape)
                if size == "native":
                    x0, _, x1, _ = chat.frame_rect(w, h, 1.0)
                    ys, xs = np.nonzero((out != screen_bg[:, x0:x1]).any(axis=2))
                    margin = 24 * h / compose.REFERENCE_SIDE
                    assert abs(xs.min() - margin) < 6 and abs(ys.min() - margin) < 6, (w, xs.min(), ys.min())


def check_config():
    saved = config.CONFIG_PATH
    try:
        with tempfile.TemporaryDirectory() as tmp:
            config.CONFIG_PATH = Path(tmp) / "config.ini"
            raw, cfg = config.load_config()
            assert raw == config.DEFAULTS and config.CONFIG_PATH.read_text(encoding="utf-8").startswith("[snapline]")
            raw = dict(raw, size="4k", format="4:5", chat_pos="bottom-right", keep="речь, ooc")
            config.write_raw(raw)
            raw2, cfg2 = config.load_config()
            assert raw2 == raw and cfg2["ratio"] == 0.8 and cfg2["keep"] == (SP, O) and cfg2["size"] == "4k"
            assert config.parse_config(dict(raw, size=" 0900 "))["size"] == "900"
            assert cfg["source"] == "screen" and config.parse_config(dict(raw, source=" Log "))["source"] == "log"
            framed = config.parse_config(dict(raw, format="1200 X 0800"))
            assert framed["format"] == "1200x800" and framed["ratio"] == 1.5
            for bad in (dict(raw, hotkey="F7"), dict(raw, size="8k"), dict(raw, size="100"), dict(raw, size="9000"),
                        dict(raw, format="wide"), dict(raw, format="100x800"), dict(raw, format="1200x0"),
                        dict(raw, file="gif"), dict(raw, text_scale="9"),
                        dict(raw, keep="крики"), dict(raw, sound="maybe"), dict(raw, source="ocr")):
                try:
                    config.parse_config(bad)
                except ValueError:
                    continue
                raise AssertionError(bad)
            config.CONFIG_PATH.write_text("﻿[lspscreen]\nhotkey = F10\n", encoding="utf-8")
            assert config.load_config()[1]["key"] == "F10"
            out = Path(tmp) / "out"
            blocked = FileNotFoundError(2, "not found", str(out / "src"))
            assert "Контролируемый доступ" in store.explain(blocked, {"out": out})
            assert store.explain(OSError("x"), {"out": out}) == "Не получилось: x"
            assert store.check_out({"out": out}) is None and not list((out / "src").iterdir())
    finally:
        config.CONFIG_PATH = saved


def check_session():
    with tempfile.TemporaryDirectory() as tmp:
        cfg = make_cfg(tmp, format="full", ratio=None, text_scale=1.0, outline=1)
        state = {"session": capture.Session()}
        bg = load("bg.webp")
        assert not chat.is_chat_shot(bg)

        assert capture.handle(load("chat1.webp"), state, cfg) is capture.TONE_STEP
        assert capture.handle(bg, state, cfg) is capture.TONE_FAIL
        t = time.perf_counter()
        assert capture.handle(load("chat2.webp"), state, cfg) is capture.TONE_SS
        print(f"chat shot -> SS in {time.perf_counter() - t:.2f}s")
        assert capture.handle(load("chat3.webp"), state, cfg) is capture.TONE_SS

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
    assert ctypes.sizeof(capture.INPUT) == (40 if ctypes.sizeof(ctypes.c_void_p) == 8 else 28)
    capture.DARK_TIMEOUT_S = 0.3
    tap, grab = capture.tap, capture.grab
    try:
        with tempfile.TemporaryDirectory() as tmp:
            cfg = make_cfg(tmp)
            state = {"session": capture.Session()}

            game = FakeGame()
            capture.tap, capture.grab = game.tap, game.grab
            assert capture.on_hotkey(state, cfg) is capture.TONE_SS
            assert game.taps == ["F7", "F7", "F2", "F2"], game.taps
            assert not game.hud_hidden and not game.dark
            assert np.array_equal(state["session"].bg, game.bg)
            with Image.open(Path(tmp) / f"{state['session'].name}.png") as out:
                assert out.size == (1125, 1125), out.size

            game.taps, game.dark = [], True
            name = state["session"].name
            assert capture.on_hotkey(state, cfg) is capture.TONE_SS
            assert game.taps == [] and state["session"].name == name and state["session"].chats == 2

            game = FakeGame(dark_works=False)
            capture.tap, capture.grab = game.tap, game.grab
            assert capture.on_hotkey(state, cfg) is capture.TONE_FAIL
            assert game.taps == ["F7", "F7", "F2"], game.taps
    finally:
        capture.tap, capture.grab = tap, grab


def check_parts():
    rows = chat.classify(chat.extract_rows(load("real_chat_pm.png")))
    for r in rows:
        r["keep"] = True
    edit = compose.new_edit(make_cfg("."), rows)
    edit["keep"] = [True] * len(rows)
    assert compose.places(edit, 3) == ["top-left", "bottom-left", "top-right"]
    assert compose.corner_of([0.22, 0.84]) == "bottom-left"
    assert compose.places(dict(edit, pos=[0.8, 0.1]), 2) == [[0.8, 0.1], "bottom-right"]
    assert compose.cuts(rows, dict(edit, breaks=[0, 99, 9, 5, 5, 7])) == [5, 7, 9]
    assert compose.places(edit, 6) == ["top-left", "bottom-left", "top-right", "bottom-right", "top-left",
                                       "bottom-left"]
    assert compose.corner_of(["right", 0.1]) == "top-right" and compose.corner_of([0.1, "bottom"]) == "bottom-left"
    assert chat.place(1440, 1440, 300, 100, 4, ["left", 0.5], 24) == (20, 716)
    assert chat.place(1440, 1440, 300, 100, 4, [0.3, "bottom"], 24) == (428, 1320)
    layers = [np.zeros((100, 300, 4), np.uint8), np.zeros((80, 200, 4), np.uint8), None, np.zeros((50, 50, 4), np.uint8)]
    spots = compose.chat_spots((1440, 1440), layers, ["top-left", "top-left", "top-right", ["right", 0.5]], 4, 24)
    assert spots == [(20, 20), (20, 136), None, (1370, 716)], spots
    wide = [np.zeros((100, 900, 4), np.uint8), np.zeros((60, 900, 4), np.uint8)]
    assert compose.chat_spots((1440, 1440), wide, ["bottom-left", "bottom-right"], 4, 24) == [(20, 1320), (520, 1244)]
    bg = load("real_bg.webp")
    one, n1 = compose.render(bg, rows, edit)
    two, n2 = compose.render(bg, rows, dict(edit, breaks=[9]))
    assert n1 == n2 == len(rows), (n1, n2, len(rows))
    many = list(range(2, len(rows), 2))
    assert len(many) > 3 and compose.render(bg, rows, dict(edit, breaks=many))[1] == len(rows)
    assert not (one != compose.render(bg, [], edit)[0]).any(axis=2)[2 * one.shape[0] // 3:].any()
    H = two.shape[0]
    frame = compose.render(bg, [], edit)[0]
    changed = (two != frame).any(axis=2)
    assert changed[: H // 3].any() and changed[2 * H // 3:].any() and not changed[H // 3:2 * H // 3, : H // 3].any()

    with tempfile.TemporaryDirectory() as tmp:
        cfg = make_cfg(tmp)
        state = {"session": capture.Session()}
        capture.handle(load("bg.webp"), state, cfg)
        capture.handle(load("chat2.webp"), state, cfg)
        name = state["session"].name
        shot = store.load_shot(Path(tmp), name, cfg)
        gone = [i for i, r in enumerate(shot["rows"]) if r["keep"]][0]
        shot["rows"][gone]["keep"] = False
        shot["edit"].update(keep=[r["keep"] for r in shot["rows"]], breaks=[5], places=["bottom-right"])
        store.save_shot(shot)
        capture.handle(load("chat3.webp"), state, cfg)
        again = store.load_shot(Path(tmp), name, cfg)
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
        state = {"session": capture.Session()}
        capture.handle(load("real_bg.webp"), state, cfg)
        capture.handle(load("real_chat_ic.png"), state, cfg)
        name = state["session"].name
        shot = store.load_shot(Path(tmp), name, cfg)
        assert [len(r["hide"]) for r in shot["rows"]] == [2, 0, 2], [r["hide"] for r in shot["rows"]]
        plain = compose.render(shot["bg"], [dict(r, hide=[]) for r in shot["rows"]], shot["edit"])[0]
        assert (plain != compose.render(shot["bg"], shot["rows"], shot["edit"])[0]).any()
        shot["rows"][2]["hide"], shot["rows"][2]["drop"] = [], chat.words(shot["rows"][2])[:3]
        shot["edit"]["hidden"] = compose.spans_of(shot["rows"], "hide")
        shot["edit"]["dropped"] = compose.spans_of(shot["rows"], "drop")
        store.save_shot(shot)
        capture.handle(load("real_chat_ic.png"), state, cfg)
        again = store.load_shot(Path(tmp), name, cfg)
        assert again["rows"][2]["drop"] == [tuple(s) for s in chat.words(again["rows"][2])[:3]], again["rows"][2]
        assert again["rows"][2]["hide"] == [] and len(again["rows"][0]["hide"]) == 2

        ov = compose.add_overlay(Path(tmp), name, Image.new("RGB", (400, 200), (255, 0, 0)))
        assert ov["file"] == f"{name}_ov1.jpg" and "frame" not in ov
        assert compose.crop_for((400, 200), 1.0, (0.5, 0.0, 1.0, 1.0)) == [0.5, 0.0, 1.0, 1.0]
        assert compose.crop_exact((400, 200), 100, 100, (0.0, 0.0, 1.0, 1.0)) == [0.375, 0.25, 0.625, 0.75]
        assert compose.crop_exact((400, 200), 100, 100, (0.9, 0.0, 1.0, 1.0))[2] == 1.0
        assert compose.lock_ratio("4:3") == 4 / 3 and compose.lock_ratio("800x600") == 4 / 3
        assert compose.lock_ratio("free") is None
        ov["crop"] = compose.crop_for((400, 200), 1.0)
        shot["edit"]["overlays"] = [ov]
        img, _ = store.save_shot(shot)
        x, y, w, h = compose.overlay_box(ov, (img.shape[1], img.shape[0]), (400, 200))
        assert w == h and img[y + h // 2, x + w // 2][0] > 200 and img[y + h // 2, x + w // 2][1] < 60
        assert store.load_shot(Path(tmp), name, cfg)["edit"]["overlays"] == [ov]
        sticker = compose.add_overlay(Path(tmp), name, Image.new("RGBA", (10, 10), (0, 0, 0, 0)))
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
            state = {"session": capture.Session()}
            state["session"].name = f"SS_2026-01-01_00-00-0{i}"
            capture.handle(load(bg), state, cfg)
            capture.handle(load(shot), state, cfg)
            names.append(state["session"].name)
        mine, donor = names
        theirs = store.load_shot(out, donor, cfg)
        theirs["rows"][4]["keep"] = True
        theirs["rows"][5]["hide"] = [chat.words(theirs["rows"][5])[0]]
        theirs["edit"]["keep"] = [r["keep"] for r in theirs["rows"]]
        theirs["edit"]["hidden"] = compose.spans_of(theirs["rows"], "hide")
        store.save_shot(theirs)

        shot = store.load_shot(out, mine, cfg)
        shot["edit"]["breaks"] = [1]
        compose.apply_keep(shot["rows"], shot["edit"])
        assert store.carry_chat(shot, donor, cfg) == 15
        rows = shot["rows"]
        assert len(rows) == 18 and rows[4]["keep"] and rows[5]["hide"] and shot["edit"]["breaks"] == [1]
        store.save_shot(shot)
        again = store.load_shot(out, mine, cfg)
        assert [r["keep"] for r in again["rows"]] == [r["keep"] for r in rows] and again["rows"][5]["hide"]
        assert again["edit"]["breaks"] == [1]
        assert sorted(p.name for p in (out / "src").glob(f"{mine}_chat*")) == [f"{mine}_chat1.webp",
                                                                               f"{mine}_chat2.webp"]
        assert store.carry_chat(again, donor, cfg) == 0

        state = {"session": capture.Session()}
        state["session"].name, state["session"].bg = mine, again["bg"]
        state["session"].rows = [dict(r) for r in again["rows"][:3]]
        assert capture.handle(load("real_chat_ic.png"), state, cfg) is capture.TONE_SS
        assert (out / "src" / f"{mine}_chat3.webp").exists() and len(state["session"].rows) == 18
        assert [r["keep"] for r in store.load_shot(out, mine, cfg)["rows"]] == [r["keep"] for r in rows]

        state = {"session": capture.Session()}
        state["session"].name = "SS_2026-01-01_00-00-09"
        capture.handle(scaled(load("real_bg.webp"), 1920, 1080), state, cfg)
        capture.handle(scaled(load("real_chat_ic.png"), 1920, 1080), state, cfg)
        try:
            store.carry_chat(store.load_shot(out, mine, cfg), state["session"].name, cfg)
        except ValueError:
            pass
        else:
            raise AssertionError("carried a chat from another resolution")
        listed = store.list_shots(out)
        near = store.donors(out, mine, listed)
        assert mine not in near and set(near) == set(listed) - {mine}


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
        assert store.list_shots(out) == names[::-1] + ["SS_моя"], store.list_shots(out)


def check_mirror_delete():
    with tempfile.TemporaryDirectory() as tmp:
        out = Path(tmp)
        cfg = make_cfg(out)
        bg = load("real_bg.webp")
        edit = compose.new_edit(cfg, [])
        plain = compose.render(bg, [], edit)[0]
        assert np.array_equal(compose.render(bg, [], dict(edit, mirror=True))[0], plain[:, ::-1])
        assert compose.mirror_blurs([{"x": 0.1, "y": 0.2, "w": 0.3, "h": 0.1}], compose.plan(bg, edit))[0]["x"] == 0.6
        assert compose.tilt_zoom((100, 100), 45) > 1.414 and compose.tilt_zoom((160, 90), 0) == 1.0
        band = np.zeros((400, 400, 3), np.uint8)
        band[195:205] = 255
        bent = np.asarray(compose.tilt_image(Image.fromarray(band), 20, (400, 400)))
        assert bent[236, 300].min() > 200 and bent[164, 100].min() > 200 and bent[200, 300].max() < 50
        white = np.asarray(compose.tilt_image(Image.new("RGB", (160, 90), (255, 255, 255)), 25, (160, 90)))
        assert white.min() > 250, white.min()
        steep = compose.render(bg, [], dict(edit, tilt=10))[0]
        assert steep.shape == plain.shape and not np.array_equal(steep, plain)
        half = np.zeros((20, 40, 4), np.uint8)
        half[..., 3] = 255
        half[:, :20, 0] = half[:, 20:, 2] = 255
        ov = dict(compose.add_overlay(out, "SS_m", Image.fromarray(half)), crop=[0.0, 0.0, 0.5, 1.0], w=0.2)
        src = out / "src" / ov["file"]
        compose.flip_overlay(ov)
        assert ov["crop"] == [0.5, 0.0, 1.0, 1.0] and compose.overlay_image(src, ov=ov).getpixel((0, 0))[2] > 200
        compose.flip_overlay(ov)
        assert ov["crop"] == [0.0, 0.0, 0.5, 1.0] and not ov["flip"] and ov["angle"] == 0
        whole = compose.overlay_image(src, ov=ov)
        up = np.asarray(compose.spin(whole, 90)).astype(int)
        assert up.shape[:2] == (40, 20) and up[3, 10, 0] > 200 and up[-4, 10, 2] > 200, up[[3, -4], 10]
        tilt = np.asarray(compose.spin(whole, 30))
        assert tilt.shape[1] > 44 and tilt[0, 0, 3] == 0 and tilt[tilt.shape[0] // 2, tilt.shape[1] // 2, 3] == 255
        ov["angle"] = 30
        compose.flip_overlay(ov)
        assert ov["angle"] == -30 and compose.wrap_angle(180) == -180 and compose.wrap_angle(-190) == 170
        assert np.allclose(compose.turned(1, 0, 90), (0, 1))
        flat = dict(ov, crop=[0.0, 0.0, 1.0, 1.0], flip=False, soft=0.0, angle=45)
        steep = compose.render(bg, [], dict(edit, overlays=[flat]), out / "src")[0].astype(int)
        x, y, w, h = compose.overlay_box(flat, plain.shape[1::-1], whole.size)
        cx, cy = x + w / 2, y + h / 2
        vx, vy = compose.turned(-w / 4, 0, 45)
        rx, ry = round(cx + vx), round(cy + vy)
        assert steep[ry, rx, 0] > 200 and steep[ry, rx, 2] < 80, steep[ry, rx]
        assert np.array_equal(steep[y + 2, x + 2], plain[y + 2, x + 2]), (steep[y + 2, x + 2], plain[y + 2, x + 2])
        scene = {"shots": ["a", "b", "c"], "seams": [{"k": 0}, {"k": 1}]}
        drop = lambda name: store.drop_member({"scene": json.loads(json.dumps(scene))}, name)["scene"]
        assert drop("b") == {"shots": ["a", "c"], "seams": [{"k": 0}]}
        assert drop("a")["seams"] == [{"k": 1}] and drop("c")["seams"] == [{"k": 0}]
        for name in ("SS_a.jpg", "SS_ab.jpg"):
            Image.new("RGB", (4, 4)).save(out / name)
        for name in ("SS_a_bg.jpg", "SS_a_chat1.webp", "SS_a_ov1.png", "SS_a_log.png", "SS_a.json", "SS_ab_bg.jpg"):
            (out / "src" / name).write_bytes(b"{}")
        (out / "src" / "SS_b.json").write_text(json.dumps({"scene": {"shots": ["SS_b", "SS_a"], "seams": [{}]}}),
                                               encoding="utf-8")
        mine = ["SS_a.jpg", "SS_a.json", "SS_a_bg.jpg", "SS_a_chat1.webp", "SS_a_log.png", "SS_a_ov1.png"]
        assert sorted(p.name for p in store.shot_paths(out, "SS_a")) == mine
        gone = []
        trash = lambda paths: [(gone.append(p.name), p.unlink()) for p in paths]
        assert store.delete_shot(out, "SS_a", cfg, trash) == ["SS_b"]
        assert sorted(gone) == mine and store.saved_edit(out, "SS_b")["scene"] is None
        assert (out / "SS_ab.jpg").exists() and (out / "src" / "SS_ab_bg.jpg").exists()


def check_join():
    with tempfile.TemporaryDirectory() as tmp:
        out = Path(tmp)
        cfg = make_cfg(out)
        bg, shot = load("real_bg.webp"), load("real_chat_ic.png")
        rows = chat.classify(chat.extract_rows(shot), cfg["keep"])
        plain = compose.render(bg, [], compose.new_edit(cfg, rows))[0]
        for side in compose.JOIN_SIDES:
            edit = compose.new_edit(cfg, rows)
            edit["join"] = {"side": side, "size": 0.5, "fade": 0.3}
            p = compose.plan(bg, edit)
            img = compose.render(bg, [], edit)[0]
            assert (img.shape[1], img.shape[0]) == p["size"] and p["base"] == (1440, 1440), (side, p["size"])
            ax, ay = p["at"]
            keep = img[ay:ay + 1440, ax:ax + 1440]
            inner = slice(0, 1000) if side in ("right", "bottom") else slice(440, 1440)
            part = (keep[:, inner], plain[:, inner]) if side in ("left", "right") else (keep[inner], plain[inner])
            assert np.array_equal(*part), side
        assert compose.render(bg, rows, edit)[1] == sum(r["keep"] for r in rows)
        edit["join"].update(side="none")
        assert compose.plan(bg, edit)["size"] == (1440, 1440) and np.array_equal(compose.render(bg, [], edit)[0], plain)
        ov = compose.add_overlay(out, "SS_j", Image.new("RGB", (800, 600), (200, 30, 30)))
        sticker = compose.add_overlay(out, "SS_j", Image.new("RGBA", (80, 60), (0, 0, 0, 0)))
        assert ov["file"].endswith(".jpg") and ov["soft"] > 0 and sticker["file"].endswith(".png") and not sticker["soft"]
        edit = compose.new_edit(cfg, rows)
        edit["overlays"] = [dict(ov, x=0.25, y=0.5, w=0.5, soft=0.5, alpha=1.0)]
        img = compose.render(bg, [], edit, out / "src")[0].astype(int)
        red = lambda px: abs(px - (200, 30, 30)).max() <= 3
        assert red(img[720, 2]) and red(img[720, 360]) and not red(img[720, 715]), (img[720, 2], img[720, 715])
        edit["join"] = {"side": "bottom", "size": 0.5, "fade": 0.3}
        p = compose.plan(bg, edit)
        fit = compose.fit_field(dict(ov), p, (800, 600))
        x, y, w, h = compose.overlay_box(fit, p["size"], (800, 600))
        assert (x, y + h, w) == (0, 2160, 1440) and abs(y - 1080) <= 2, (x, y, w, h)
        assert compose.soft_edges((x, y, w, h), p["size"]) == (False, True, False, False)
        edit["join"] = None
        edit["overlays"][0].update(soft=0.0, alpha=0.5)
        img = compose.render(bg, [], edit, out / "src")[0].astype(int)
        assert abs(img[720, 360] - (plain[720, 360] + np.array((200, 30, 30))) / 2).max() <= 2
        dots = np.repeat(((np.indices((300, 300)) // 10).sum(0) % 2 * 255).astype(np.uint8)[..., None], 3, 2)
        edit["overlays"] = [dict(compose.add_overlay(out, "SS_j", Image.fromarray(dots)), x=0.5, y=0.5, w=1.0, soft=0.0)]
        sharp = compose.render(bg, [], edit, out / "src")[0].astype(int)
        hid = compose.render(bg, [], dict(edit, blurs=[{"x": 0.4, "y": 0.4, "w": 0.2, "h": 0.2, "mode": "blur",
                                                        "power": 0.8}]), out / "src")[0].astype(int)
        assert np.abs(hid[600:840, 600:840] - sharp[600:840, 600:840]).mean() > 10
        assert np.array_equal(hid[:500], sharp[:500])


def check_quality():
    with tempfile.TemporaryDirectory() as tmp:
        out = Path(tmp)
        cfg = make_cfg(out, file="jpg")
        bg, shot = load("real_bg.webp"), load("real_chat_ic.png")
        rows = chat.classify(chat.extract_rows(shot), cfg["keep"])
        edit = compose.new_edit(cfg, rows)
        clean = compose.render(bg, rows, edit)[0]
        text = (clean != compose.render(bg, [], edit)[0]).any(axis=2)
        sizes, text_err, bg_err = [], [], []
        for quality in (92, 40, 10):
            edit["quality"] = quality
            data = store.encoded({"bg": bg, "rows": rows, "edit": edit, "out": out})[2]
            diff = np.abs(store.decoded(data).astype(int) - clean.astype(int))
            sizes.append(len(data))
            text_err.append(diff[text].mean())
            bg_err.append(diff[~text].mean())
        assert sizes[0] > sizes[1] > sizes[2] and sizes[2] < sizes[0] * 0.75, sizes
        assert max(text_err) < text_err[0] + 1.5 and bg_err[2] > bg_err[0] * 1.5, (text_err, bg_err)


def check_grain():
    clean = load("real_bg.webp")
    size = (clean.shape[1] * 9 // 16, clean.shape[0] * 9 // 16)
    assert np.array_equal(compose.shrink(clean, size), scaled(clean, *size))
    noise = (np.asarray(Image.effect_noise(clean.shape[1::-1], 40), np.float32)[..., None] - 127.5) / 16
    noisy = np.clip((clean + noise).round(), 0, 255).astype(np.uint8)
    plain, kept = scaled(noisy, *size), compose.shrink(noisy, size)
    native = compose.grain(noisy)
    assert compose.grain(plain) < native * 0.8, (compose.grain(plain), native)
    assert abs(compose.grain(kept) - native) < native * 0.2, (compose.grain(kept), native)
    assert np.abs(kept.mean((0, 1)) - plain.mean((0, 1))).max() < 0.5


def check_styles():
    cfg = make_cfg(".")
    bg, shot = load("real_bg.webp"), load("real_chat_ic.png")
    rows = chat.classify(chat.extract_rows(shot), cfg["keep"])
    edit = compose.new_edit(cfg, rows)
    plain = compose.render(bg, rows, edit)[0]
    when = datetime(2026, 11, 13, 2, 16, 56)
    for style in ("cctv", "body"):
        frame, p = compose.backdrop(bg, edit)
        styled, marks = styles.apply(frame, style, when, None)
        assert styled.shape == frame.shape and styled.dtype == np.uint8 and len(marks) == 3, (style, marks)
        found = []
        compose.paint_chat(styled, rows, edit, p, boxes=list(marks), found=found)
        _, x, y, w, h = found[0]
        pad = p["outline"] + 2
        assert not any(b[0] < x + w - pad and x + pad < b[2] and b[1] < y + h - pad and y + pad < b[3]
                       for b in marks), (style, found, marks)
        out = compose.render(bg, rows, dict(edit, style=style, style_text="CAM 7"), when=when)[0]
        assert out.shape == plain.shape and np.abs(out.astype(int) - plain.astype(int)).mean() > 5
    assert styles.apply(plain, "none", when, None)[0] is plain
    assert styles.grade(plain, "none", {"temp": 0}) is plain
    size, table = styles.read_cube(cube(3, lambda r, g, b: (r, g, b)))
    assert size == 3 and table[:6] == [0.0, 0.0, 0.0, 0.5, 0.0, 0.0]
    same = styles.grade(plain, "none", {}, styles.ImageFilter.Color3DLUT(size, table))
    assert np.abs(same.astype(int) - plain.astype(int)).max() <= 1
    for bad in ("LUT_1D_SIZE 4\n", "LUT_3D_SIZE 2\n0 0 0\n"):
        try:
            styles.read_cube(bad)
        except ValueError:
            continue
        raise AssertionError(bad)
    pic = Image.fromarray(plain)
    assert styles.obscure(pic, []) is pic
    for mode in styles.BLUR_MODES:
        hid = np.asarray(styles.obscure(pic, [{"x": 0.5, "y": 0.5, "w": 0.25, "h": 0.25, "mode": mode, "power": 0.8}]))
        inside, outside = (slice(720, 1080), slice(720, 1080)), (slice(0, 700), slice(0, 1440))
        assert np.abs(hid[inside].astype(int) - plain[inside].astype(int)).mean() > 3, mode
        assert np.array_equal(hid[outside], plain[outside]), mode
    warm = styles.grade(plain, "warm", {"bright": 30})
    assert warm.shape == plain.shape and warm[..., 0].mean() > plain[..., 0].mean() + 3
    assert len(styles.apply(plain, "cctv", None, "")[1]) == 1


def cube(n, f):
    rows = [f(r / (n - 1), g / (n - 1), b / (n - 1)) for b in range(n) for g in range(n) for r in range(n)]
    return f"LUT_3D_SIZE {n}\n" + "".join(f"{r:.4f} {g:.4f} {b:.4f}\n" for r, g, b in rows)


def golden_cases(out):
    cfg = make_cfg(out)
    names = []
    for i in range(2):
        state = {"session": capture.Session()}
        state["session"].name = f"SS_2026-01-01_00-00-0{i}"
        capture.handle(load("real_bg.webp"), state, cfg)
        capture.handle(load("real_chat_ic.png"), state, cfg)
        names.append(state["session"].name)
    shot = store.load_shot(out, names[0], cfg)
    bg, rows, base = shot["bg"], shot["rows"], shot["edit"]
    pm = chat.classify(chat.extract_rows(load("real_chat_pm.png")))
    for r in pm:
        r["keep"] = True
    words = [dict(r, hide=list(chat.words(r)[:2]) if i == 2 else [], drop=list(chat.words(r)[1:3]) if i == 0 else [])
             for i, r in enumerate(rows)]
    gradient = np.dstack([*np.meshgrid(np.linspace(0, 255, 600), np.linspace(255, 0, 400)), np.full((400, 600), 90.0)])
    ov = compose.add_overlay(out, names[0], Image.fromarray(gradient.astype(np.uint8)))
    ov.update(x=0.62, y=0.6, w=0.3, soft=0.3, crop=compose.crop_for((600, 400), 1.0))
    when = datetime(2026, 1, 1, 0, 0, 0)
    scene = store.load_shot(out, names[1], cfg)
    scene["edit"]["scene"] = {"shots": names, "seams": [dict(compose.SEAM)]}
    scene["edit"]["home"] = names[0]
    yield "square", lambda: compose.render(bg, rows, base)[0]
    yield "frame_800", lambda: compose.render(bg, rows, dict(base, format="800x800"))[0]
    yield "wide_zoom", lambda: compose.render(bg, rows, dict(base, format="16:9", zoom=1.6, center=[0.3, 0.6],
                                                             size="hd"))[0]
    yield "parts", lambda: compose.render(load("real_bg.webp"), pm, dict(compose.new_edit(cfg, pm), breaks=[2, 4],
                                                                         pos="bottom-right", text_scale=1.2))[0]
    yield "words", lambda: compose.render(bg, words, base)[0]
    yield "join", lambda: compose.render(bg, rows, dict(base, join={"side": "bottom", "size": 0.4, "fade": 0.3}))[0]
    yield "overlay", lambda: compose.render(bg, rows, dict(base, overlays=[ov]), out / "src")[0]
    yield "rough", lambda: compose.render(bg, rows, base, rough=40)[0]
    yield "cctv", lambda: compose.render(bg, rows, dict(base, style="cctv", style_text="CAM 7"), when=when)[0]
    yield "body", lambda: compose.render(bg, rows, dict(base, format="16:9", style="body"), when=when)[0]
    yield "scene", lambda: store.render_shot(scene)[0]
    lut = out / "teal.cube"
    lut.write_text(cube(5, lambda r, g, b: (r * 0.9, g, min(1.0, b * 1.1 + 0.05))), encoding="utf-8")
    graded = dict(base, preset="film", look={"contrast": 20, "temp": -30, "shadows": 25}, lut=compose.add_lut(out, lut))
    yield "graded", lambda: compose.render(bg, rows, graded, out / "src")[0]
    blurs = [{"x": 0.55, "y": 0.55, "w": 0.3, "h": 0.2, "mode": "blur", "power": 0.7},
             {"x": 0.1, "y": 0.6, "w": 0.2, "h": 0.15, "mode": "pixel", "power": 0.5}]
    yield "blurred", lambda: compose.render(bg, rows, dict(base, blurs=blurs, join={"side": "right", "size": 0.3,
                                                                                   "fade": 0.3}))[0]


def digest(img):
    return f"{img.shape[1]}x{img.shape[0]}:" + hashlib.sha256(np.ascontiguousarray(img).tobytes()).hexdigest()[:20]


def check_golden(write=False):
    with tempfile.TemporaryDirectory() as tmp:
        got = {name: render() for name, render in golden_cases(Path(tmp))}
    sums = {name: digest(img) for name, img in got.items()}
    if write:
        GOLDEN.write_text(json.dumps(sums, indent=1) + chr(10), encoding="utf-8")
        return
    want = json.loads(GOLDEN.read_text(encoding="utf-8"))
    bad = sorted(n for n in want.keys() | sums.keys() if want.get(n) != sums.get(n))
    if bad:
        dump = Path(tempfile.mkdtemp(prefix="snapline_golden_"))
        for n in bad:
            if n in got:
                Image.fromarray(got[n]).save(dump / f"{n}.png")
        raise AssertionError(f"golden renders changed: {bad}; actual images in {dump}; "
                             f"after checking them run: python test_snapline.py --golden")


def check_watermark():
    bg, shot = load("real_bg.webp"), load("real_chat_ic.png")
    mark = chat.watermark(shot)
    assert mark is not None and mark["t"].shape[1] > 120, None if mark is None else mark["t"].shape
    clean = chat.clean_bg(bg, mark)
    ys, xs = np.nonzero((clean != bg).any(axis=2))
    assert ys.min() > 1300 and xs.min() > 2300, (ys.min(), xs.min())
    assert np.array_equal(chat.clean_bg(clean, mark), clean)
    assert chat.clean_bg(bg, None) is bg
    assert chat.watermark(np.zeros((1440, 2560, 3), np.uint8)) is None
    example = Path(__file__).resolve().parent / "samples"
    rows = chat.classify(chat.extract_rows(store.read_image(example / "example_chat.png")))
    assert [r["kind"] for r in rows if r["keep"]]
    assert store.read_image(example / "example_bg.webp").shape == (1440, 2560, 3)


def check_scene():
    with tempfile.TemporaryDirectory() as tmp:
        out = Path(tmp)
        cfg = make_cfg(out)
        names = []
        for i, size in enumerate((None, None, (1920, 1080))):
            state = {"session": capture.Session()}
            state["session"].name = f"SS_2026-01-01_00-00-0{i}"
            bg, shot = load("real_bg.webp"), load("real_chat_ic.png")
            if size:
                bg, shot = scaled(bg, *size), scaled(shot, *size)
            capture.handle(bg, state, cfg)
            capture.handle(shot, state, cfg)
            names.append(state["session"].name)
        first, head, last = names
        trio = [store.load_shot(out, n, cfg) for n in names]
        kept = [i for i, r in enumerate(trio[1]["rows"]) if r["keep"]]
        assert kept and store.repeats(trio) == [[], kept, []], store.repeats(trio)
        whole = store.load_shot(out, head, cfg)
        single, painted = store.render_shot(whole)
        seams = [dict(compose.SEAM, dark=0.0), dict(compose.SEAM, dark=0.0), dict(compose.SEAM, dark=0.0)]
        whole["edit"]["scene"] = {"shots": [first, "SS_2026-01-01_09-09-09", head, last], "seams": seams}
        layout = {}
        img, n = store.render_shot(whole, layout=layout)
        assert img.shape == (3 * 1440 - 2 * 288, 1440, 3) and n == painted, (img.shape, n, painted)
        assert {k: layout[k] for k in ("tops", "heights", "laps")} == {
            "tops": [0, 1152, 2304], "heights": [1440] * 3, "laps": [288, 288]}, layout
        assert layout["spans"] == [(0, 1296), (1296, 2448), (2448, 3744)] and len(layout["chats"]) == 3
        mine = [c for c in layout["chats"] if c[0] == 1][0]
        assert 1296 <= mine[3] < 1500, mine
        moved, there = dict(whole, edit=dict(whole["edit"], home=last)), {}
        store.render_shot(moved, layout=there)
        box = [c for c in there["chats"] if c[0] == 1][0]
        theirs = [c for c in there["chats"] if c[0] == 2][0]
        assert theirs[3] >= box[3] + box[5] - 2 * there["pads"][1] and box[3] + there["pads"][1] > 2448, (box, theirs)
        cut = len(whole["rows"]) // 2
        split, apart = dict(whole, edit=dict(whole["edit"], breaks=[cut], home=[None, last])), {}
        store.render_shot(split, layout=apart)
        mine = sorted((c for c in apart["chats"] if c[0] == 1), key=lambda c: c[1])
        assert cut and len(mine) == 2 and 1296 <= mine[0][3] < 2448 <= mine[1][3] + apart["pads"][1], mine
        assert compose.homes_of(whole["rows"], {"breaks": [cut], "home": [None]}) == [None, None]
        assert compose.homes_of(whole["rows"], {"breaks": [cut], "home": last}) == [last, last]
        seam, where = dict(whole, edit=dict(whole["edit"], pos=[0.1, 1.02])), {}
        store.render_shot(seam, layout=where)
        box = [c for c in where["chats"] if c[0] == 1][0]
        assert 2448 < box[3] + where["pads"][1] < 2448 + 60, box
        assert compose.inset([288, 288], 0) == (0, 144) and compose.inset([288, 288], 1) == (144, 144)
        assert compose.inset([288, 288], 2) == (144, 0)
        bare = dict(whole, rows=[], members={n: dict(store.frame_shot(out, n, cfg), rows=[]) for n in (first, last)})
        plain = store.render_shot(bare)[0]
        assert np.array_equal(plain[1440:2304], compose.render(whole["bg"], [], whole["edit"])[0][288:1152])
        changed = (img != plain).any(axis=2)
        assert changed[:200].any() and not changed[1152:1152 + 144].any() and changed[1152 + 144:1152 + 400].any()
        mid = img[1152 + 144].astype(float).mean(), img[2304 + 144].astype(float).mean()
        seams[2]["dark"] = 0.5
        img = store.render_shot(whole)[0]
        assert img[1152 + 144].astype(float).mean() == mid[0] and img[2304 + 144].astype(float).mean() < mid[1] * 0.7
        whole["edit"]["scene"]["shots"] = [head, last, first]
        img = store.render_shot(whole)[0]
        assert np.array_equal(img[:1152], single[:1152])
        for s in seams:
            s["fade"] = 0.0
        assert store.render_shot(whole)[0].shape[0] == 3 * 1440
        whole["edit"]["format"] = "800x800"
        assert store.render_shot(whole)[0].shape == (3 * 800, 800, 3)
        assert store.load_shot(out, last, cfg)["edit"]["format"] == "square"
        whole["edit"]["format"] = "square"
        store.save_shot(whole)
        assert Image.open(store.shot_image(out, head)).size == (1440, 3 * 1440)
        assert store.scenes_with(out, last) == [head] and store.scenes_with(out, head) == []
        before = store.read_image(store.shot_image(out, head))
        other = store.load_shot(out, last, cfg)
        other["edit"]["zoom"] = 2.0
        store.save_shot(other)
        after = store.read_image(store.shot_image(out, head))
        assert np.array_equal(after[:1440], before[:1440]) and np.array_equal(after[2880:], before[2880:])
        assert not np.array_equal(after[1440:2880], before[1440:2880])
        whole["edit"]["scene"]["shots"] = [head, "SS_2026-01-01_09-09-09"]
        assert store.scene_of(whole) is None and store.render_shot(whole)[0].shape == single.shape

ME, TALK, SYS, GREY = "#c2a2da", "#e6e6e6", "#ffffff", "#a0a0a0"


def check_log():
    assert chatlog.hex_color("rgb(194, 162, 218)") == ME and chatlog.hex_color("#FFFF90") == "#FFFF90"
    assert chatlog.hex_color("transparent") == TALK
    entry = chatlog.log_entry("[19:10:00] * Malachy Doyle курит.", True)
    assert entry == ("19:10:00", [["* Malachy Doyle курит.", ME]])
    assert chatlog.log_entry("[19:10:00]  ", True) is None and chatlog.log_entry("{broken", False) is None
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
        lines = chatlog.read_log(out, when)
        assert [l[0].strftime("%H:%M") for l in lines] == ["19:00", "19:08", "19:09", "19:12", "19:17", "19:18",
                                                           "19:20", "19:21"]
        assert len(chatlog.read_log(out, datetime(2026, 11, 8, 0, 5))) == 1
        assert chatlog.log_chunks(lines) == [0, 1, 4] and chatlog.log_chunks([]) == []

        rows = chat.classify(chat.extract_rows(chatlog.log_frame(lines[1:7], (2560, 1440))))
        assert [r["kind"] for r in rows] == [S, AC, O, AC, AC, S, AC, AC], [r["kind"] for r in rows]
        assert rows[4]["cont"]

        name = "SS_2026-11-08_19-20-24"
        bg = load("bg.webp")
        store.save_src(bg, cfg, f"{name}_bg", store.SRC_BG)
        shot = {"name": name, "out": out, "bg": bg, "rows": [], "edit": compose.new_edit(cfg, []), "cfg": cfg}
        picked = lines[3:7]
        assert store.use_log(shot, cfg, picked) == 6 and all(r["keep"] for r in shot["rows"])
        assert store.shot_files(out, name)[1] == [store.log_path(out, name)]
        assert chatlog.picked_log(shot["edit"]) == picked
        assert {chatlog.log_key(*l) for l in chatlog.picked_log(shot["edit"])} == {chatlog.log_key(*l) for l in picked}
        assert chatlog.picked_log({"log": [{"at": "вчера", "parts": []}]}) == [] and chatlog.picked_log({}) == []
        assert store.save_shot(shot)[1] == 6
        again = store.load_shot(out, name, cfg)
        assert all(again["edit"]["keep"]) and len(again["rows"]) == 6 and chatlog.picked_log(again["edit"]) == picked
        try:
            store.carry_chat(again, name, cfg)
            raise AssertionError("carry into a chatlog shot")
        except ValueError:
            pass
        (out / "src" / f"{name}_chat1.webp").write_bytes((SAMPLES / "chat1.webp").read_bytes())
        assert store.use_screen(again, cfg) > 0 and not store.log_path(out, name).exists()
        assert again["edit"]["breaks"] == [] and chatlog.picked_log(again["edit"]) == picked
        store.save_shot(again)
        assert store.load_shot(out, name, cfg)["edit"]["keep"] == again["edit"]["keep"] != shot["edit"]["keep"]

        empty = dict(shot, name="SS_2026-11-08_23-50-00", rows=[], edit=compose.new_edit(cfg, []))
        store.save_src(bg, cfg, f"{empty['name']}_bg", store.SRC_BG)
        assert store.use_log(empty, cfg, []) == 0 and empty["rows"] == []
        assert store.save_shot(empty)[1] == 0 and store.load_shot(out, empty["name"], cfg)["rows"] == []
        assert store.log_path(out, empty["name"]).exists()

    t = datetime(2026, 11, 8, 19, 0)
    tagged = [[["[Информация] ", "#ffff90"], ["Лавка пожертвования ветеранам боевых действий.", SYS]],
              [["[REPORT]: ", "#fcc419"], ["Ваша жалоба доставлена администрации сервера. Пожалуйста, ожидайте ответа "
                                           "от администрации.", SYS]],
              [["[!] ", "#9e5cb6"], ["Zeke Garthie говорит (к Malachy Doyle): А то ты не знаешь, как это бывает? "
                                     "Забухаешь где-то, потом только через дня два домой.", TALK]],
              [["Joshua Norman говорит: Давай его.. Светлое.", TALK]]]
    rows = chat.classify(chat.extract_rows(chatlog.log_frame([(t, p) for p in tagged], (2560, 1440))))
    assert [r["kind"] for r in rows] == [S, S, S, SP, SP, SP], [r["kind"] for r in rows]
    assert [r["mark"] for r in rows][:4] == ["[", "[", None, "["] and rows[2]["cont"]

    tap, grab = capture.tap, capture.grab
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
            capture.tap, capture.grab = game.tap, game.grab
            state = {"session": capture.Session()}
            assert capture.on_hotkey(state, cfg) is capture.TONE_SS
            assert game.taps == ["F7", "F7"], game.taps
            shot = store.load_shot(Path(tmp), state["session"].name, cfg)
            assert shot["rows"] == [] and store.log_path(Path(tmp), shot["name"]).exists()
            game.taps = []
            state = {"session": capture.Session()}
            time.sleep(1.1)
            assert capture.on_hotkey(state, dict(cfg, auto=False)) is capture.TONE_SS and game.taps == []
            assert store.load_shot(Path(tmp), state["session"].name, cfg)["rows"] == []
    finally:
        capture.tap, capture.grab = tap, grab


if __name__ == "__main__":
    if "--golden" in sys.argv:
        check_golden(write=True)
        print("golden renders written to", GOLDEN)
        sys.exit(0)
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
    check_mirror_delete()
    check_join()
    check_quality()
    check_grain()
    check_styles()
    check_golden()
    check_scene()
    check_log()
    print("ok")
