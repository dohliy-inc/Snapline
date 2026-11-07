import ctypes
import os
import tempfile
import time
from pathlib import Path

import numpy as np
from PIL import Image

import chat
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
           "margin": 24, "text_scale": 1.5, "outline": 2, "keep": (SP, AC), "sound": False, "chatlog": False, "hide_names": False}
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
            framed = core.parse_config(dict(raw, format="1200 X 0800"))
            assert framed["format"] == "1200x800" and framed["ratio"] == 1.5
            for bad in (dict(raw, hotkey="F7"), dict(raw, size="8k"), dict(raw, size="100"), dict(raw, size="9000"),
                        dict(raw, format="wide"), dict(raw, format="100x800"), dict(raw, format="1200x0"),
                        dict(raw, file="gif"), dict(raw, text_scale="9"),
                        dict(raw, keep="крики"), dict(raw, sound="maybe")):
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
    assert core.cuts(rows, dict(edit, breaks=[0, 99, 9, 5, 5, 7])) == [5, 7]
    bg = load("real_bg.webp")
    one, n1 = core.render(bg, rows, edit)
    two, n2 = core.render(bg, rows, dict(edit, breaks=[9]))
    assert n1 == n2 == len(rows), (n1, n2, len(rows))
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
    print("ok")
