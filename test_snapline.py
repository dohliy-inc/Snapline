import ctypes
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
           "format": "square", "ratio": 1.0, "size": "native", "file": "png", "chat_pos": "top-left", "margin": 24,
           "text_scale": 1.5, "outline": 2, "keep": (SP, AC), "sound": False, "chatlog": False}
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
    print("ok")
