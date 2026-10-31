import ctypes
import json
import os
import queue
import re
import subprocess
import sys
import threading
import time
import traceback
import tkinter as tk
import tkinter.font as tkfont
from ctypes import wintypes
from datetime import datetime
from functools import lru_cache
from pathlib import Path
from tkinter import filedialog, messagebox

import numpy as np
from PIL import Image, ImageDraw, ImageEnhance, ImageFilter, ImageFont, ImageGrab, ImageTk

import chat
import chatlog
import core

VOID = "#0a0a0a"
BLACK = "#000000"
ROW = "#15171b"
SLATE = "#1e2026"
MIST = "#2a2f39"
HAIR = "#202329"
LINE = "#454b57"
WHITE = "#f4f4f5"
SUB = "#a3a8b3"
ERR = "#ff7a70"

ICONS = {"images": "", "cut": "", "lines": "", "crop": "", "text": "", "copy": "", "folder": "",
         "up": "", "down": "", "close": ""}
CHROME = {"min": "", "max": "", "restore": "", "close": ""}
CHROME_TEXT = {"min": "–", "max": "□", "restore": "❐", "close": "×"}
FORMATS = {"square": "Квадрат", "full": "Экран", "16:9": "16:9", "4:3": "4:3", "4:5": "4:5"}
SIZES = {"native": "Как снято", "hd": "720", "fhd": "1080", "qhd": "1440", "4k": "2160"}
FILES = {"jpg": "JPG", "png": "PNG"}
NICKS = {"no": "Показывать", "yes": "Прятать"}
CLICKS = {"rows": "Убрать строку", "hide": "Скрыть слово", "drop": "Удалить слово"}
CROPS = {"free": "Свободно", "1:1": "Квадрат", "4:3": "4:3", "3:4": "3:4", "16:9": "16:9", "9:16": "9:16"}
HANDLES = ("l", "r", "t", "b", "lt", "rt", "lb", "rb")
OV_SIZES = {"0.25": "25%", "0.4": "40%", "0.6": "60%", "1": "100%"}
TOOLS = ("lines", "crop", "text", "images")
SCALES = {"1": "×1", "1.25": "×1.25", "1.5": "×1.5", "1.75": "×1.75", "2": "×2"}
OUTLINES = {"0": "Нет", "1": "1 px", "2": "2 px", "3": "3 px"}
ZOOMS = {"1": "1×", "1.25": "1.25×", "1.5": "1.5×", "2": "2×"}
POSITIONS = {"top-left": "Сверху слева", "top-right": "Сверху справа",
             "bottom-left": "Снизу слева", "bottom-right": "Снизу справа"}
DISCORD = "https://discord.com/users/320909791826280452"
SITE = "https://ls-project.com/"
MODES = {"yes": "Одна кнопка", "no": "Две кнопки"}
SOUND = {"yes": "Вкл", "no": "Выкл"}
KINDS = {chat.SPEECH: "Речь", chat.ACTION: "Действия", chat.AME: "Над головой",
         chat.SYSTEM: "Система", chat.OOC: "OOC и ЛС"}
MONTHS = ("января", "февраля", "марта", "апреля", "мая", "июня", "июля", "августа", "сентября",
          "октября", "ноября", "декабря")
TK_KEYS = {"Pause": "PAUSE", "Scroll_Lock": "SCROLLLOCK", "Insert": "INSERT", "Home": "HOME", "End": "END",
           "Prior": "PAGEUP", "Next": "PAGEDOWN"}
SIDE_W = 400
RAIL_W = 112
PAD = 36
K = 1.0
FONT = {}


def px(v):
    return max(1, round(v * K))


def init_metrics(root):
    global K, SIDE_W, RAIL_W, PAD
    K = max(1.0, root.winfo_fpixels("1i") / 96)
    SIDE_W, RAIL_W, PAD = px(400), px(112), px(36)


def init_fonts():
    have = set(tkfont.families())

    def pick(*names):
        return next((n for n in names if n in have), "Segoe UI")

    FONT["ui"] = pick("Segoe UI Variable Text", "Segoe UI")
    FONT["semi"] = pick("Segoe UI Variable Text Semibold", "Segoe UI Semibold")
    FONT["display"] = pick("Segoe UI Variable Display Semib", "Segoe UI Semibold")
    FONT["icon"] = next((n for n in ("Segoe Fluent Icons", "Segoe MDL2 Assets") if n in have), None)


def same(a, b):
    try:
        return float(a) == float(b)
    except (TypeError, ValueError):
        return str(a).strip().lower() == str(b).strip().lower()


def chatlog_worker(folder, stop):
    report = lambda msg: core.EVENTS.put(("chatlog", msg))
    try:
        chatlog.run(chatlog.PORT, f"cfx-nui-{chatlog.RESOURCE}", folder, stop, report)
    except Exception as e:
        with open(core.ERROR_LOG, "a", encoding="utf-8") as f:
            f.write(f"{datetime.now()}\n{traceback.format_exc()}\n")
        report(f"Чатлог остановился из-за ошибки: {e}. Подробности в {core.ERROR_LOG}")


def megabytes(size):
    return f"{size / 2 ** 20:.1f} МБ" if size >= 2 ** 20 else f"{size // 1024} КБ"


def when(name):
    try:
        t = datetime.strptime(name, "SS_%Y-%m-%d_%H-%M-%S")
    except ValueError:
        return name
    return f"{t.day} {MONTHS[t.month - 1]}, {t:%H:%M}"


@lru_cache(maxsize=256)
def rounded(w, h, r, fill=None, outline=None, width=1.0):
    k = 4
    img = Image.new("RGBA", (w * k, h * k), (0, 0, 0, 0))
    ImageDraw.Draw(img).rounded_rectangle((0, 0, w * k - 1, h * k - 1), radius=r * k, fill=fill,
                                          outline=outline, width=round(width * k))
    return img.resize((w, h), Image.LANCZOS)


@lru_cache(maxsize=8)
def tick(size, on):
    k = 4
    img = Image.new("RGBA", (size * k, size * k), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)
    s = size * k
    if on:
        d.rounded_rectangle((0, 0, s - 1, s - 1), radius=5 * k, fill=WHITE)
        d.line([(s * 0.26, s * 0.52), (s * 0.43, s * 0.68), (s * 0.75, s * 0.33)], fill=VOID, width=round(2.2 * k),
               joint="curve")
    else:
        d.rounded_rectangle((k, k, s - 1 - k, s - 1 - k), radius=5 * k, outline=LINE, width=round(1.5 * k))
    return img.resize((size, size), Image.LANCZOS)


def make_icon(size=256):
    k = 4
    s = size * k / 256
    img = Image.new("RGBA", (size * k, size * k), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)
    d.rounded_rectangle((8 * s, 8 * s, 248 * s, 248 * s), radius=56 * s, fill=VOID)
    d.rounded_rectangle((50 * s, 58 * s, 206 * s, 198 * s), radius=20 * s, outline=WHITE, width=round(12 * s))
    d.rounded_rectangle((76 * s, 140 * s, 156 * s, 154 * s), radius=7 * s, fill=WHITE)
    d.rounded_rectangle((76 * s, 166 * s, 128 * s, 180 * s), radius=7 * s, fill=WHITE)
    return img.resize((size, size), Image.LANCZOS)


def animations_on():
    flag = wintypes.BOOL(True)
    ctypes.windll.user32.SystemParametersInfoW(0x1042, 0, ctypes.byref(flag), 0)
    return bool(flag.value)


def rgb(color):
    return np.array([int(color[i:i + 2], 16) for i in (1, 3, 5)], np.float32)


class Wordmark(tk.Label):
    SILVER = rgb("#9ea5b1")
    PEAK = rgb("#ffffff")
    SWEEP_S = 1.3
    PAUSE_MS = 6000

    def __init__(self, parent, text, size=15):
        super().__init__(parent, bg=VOID, bd=0)
        px = round(size * parent.winfo_fpixels("1i") / 72)
        try:
            font = ImageFont.truetype(str(Path(os.environ.get("WINDIR", r"C:\Windows")) / "Fonts" / "segoeuib.ttf"), px)
        except OSError:
            self.config(text=text, fg=WHITE, font=(FONT["display"], size))
            return
        left, top, right, bottom = font.getbbox(text)
        w, h = right - left + 4, bottom - top + 4
        mask = Image.new("L", (w, h), 0)
        ImageDraw.Draw(mask).text((2 - left, 2 - top), text, font=font, fill=255)
        self.mask = np.asarray(mask, np.float32)[..., None] / 255
        ys, xs = np.mgrid[0:h, 0:w]
        self.coord = (xs + ys * 0.45).astype(np.float32)
        self.span = float(w)
        self.ground = rgb(VOID)
        self.photo = ImageTk.PhotoImage(self.frame(None))
        self.config(image=self.photo)
        if animations_on():
            self.after(1200, self.start)

    def frame(self, center):
        if center is None:
            color = self.PEAK
        else:
            u = (self.coord - center) / (self.span * 0.22)
            lum = 1 - 0.42 * np.exp(-u ** 2) + 0.42 * np.exp(-(u / 0.32) ** 2)
            t = np.clip((lum - 0.58) / 0.42, 0, 1)[..., None]
            color = self.SILVER + (self.PEAK - self.SILVER) * t
        out = self.ground * (1 - self.mask) + color * self.mask
        return Image.fromarray(out.round().astype(np.uint8))

    def start(self):
        self.t0 = time.monotonic()
        self.tick()

    def tick(self):
        p = (time.monotonic() - self.t0) / self.SWEEP_S
        if p >= 1:
            self.photo.paste(self.frame(None))
            self.after(self.PAUSE_MS, self.start)
            return
        eased = 1 - (1 - p) ** 3
        self.photo.paste(self.frame(-0.4 * self.span + eased * 1.9 * self.span))
        self.after(33, self.tick)


class CaptionButton(tk.Canvas):
    def __init__(self, parent, glyph, command, danger=False):
        self.w, self.h = px(44), px(32)
        super().__init__(parent, width=self.w, height=self.h, bg=parent["bg"], highlightthickness=0, bd=0)
        self.glyph, self.command, self.danger, self.hover = glyph, command, danger, False
        self.bind("<Enter>", lambda _: self.set_hover(True))
        self.bind("<Leave>", lambda _: self.set_hover(False))
        self.bind("<ButtonRelease-1>", self.release)
        self.draw()

    def set_glyph(self, glyph):
        if glyph != self.glyph:
            self.glyph = glyph
            self.draw()

    def set_hover(self, hover):
        self.hover = hover
        self.draw()

    def release(self, e):
        if 0 <= e.x < self.w and 0 <= e.y < self.h:
            self.command()

    def draw(self):
        self.delete("all")
        if self.hover:
            self.photo = ImageTk.PhotoImage(rounded(self.w, self.h, px(8), "#c42b1c" if self.danger else MIST))
            self.create_image(0, 0, anchor="nw", image=self.photo)
        icon = FONT["icon"]
        self.create_text(self.w / 2, self.h / 2, text=(CHROME if icon else CHROME_TEXT)[self.glyph],
                         font=(icon, 9) if icon else (FONT["ui"], 11), fill=WHITE if self.hover else "#c9ccd2")


class Pill(tk.Canvas):
    def __init__(self, parent, text, command, kind="chip", size=10, height=32, padx=13):
        height, padx = px(height), px(padx)
        super().__init__(parent, height=height, bg=parent["bg"], highlightthickness=0, bd=0, cursor="hand2",
                         takefocus=1)
        self.text, self.command, self.kind, self.size, self.h, self.padx = text, command, kind, size, height, padx
        self.hover = self.focused = False
        self.bind("<Button-1>", lambda _: self.command())
        self.bind("<Key-Return>", lambda _: self.command())
        self.bind("<Key-space>", lambda _: self.command())
        self.bind("<Enter>", lambda _: self.state_to(hover=True))
        self.bind("<Leave>", lambda _: self.state_to(hover=False))
        self.bind("<FocusIn>", lambda _: self.state_to(focused=True))
        self.bind("<FocusOut>", lambda _: self.state_to(focused=False))
        self.set_text(text)

    def set_text(self, text):
        self.text = text
        font = FONT["semi"] if self.kind in ("on", "primary") else FONT["ui"]
        self.font = (font, self.size)
        self.w = tkfont.Font(family=font, size=self.size).measure(text) + 2 * self.padx
        self.config(width=self.w)
        self.draw()

    def set_kind(self, kind):
        self.kind = kind
        self.set_text(self.text)

    def state_to(self, hover=None, focused=None):
        self.hover = self.hover if hover is None else hover
        self.focused = self.focused if focused is None else focused
        self.draw()

    def draw(self):
        fill, line, fg = {
            "chip": (MIST if self.hover else SLATE, None, WHITE if self.hover else "#d7d9de"),
            "on": (WHITE, None, VOID),
            "primary": ("#ffffff" if self.hover else WHITE, None, VOID),
            "ghost": (SLATE if self.hover else None, WHITE if self.hover else LINE, WHITE),
        }[self.kind]
        if self.focused:
            line = WHITE
        self.photo = ImageTk.PhotoImage(rounded(self.w, self.h, self.h // 2, fill, line, 1.2))
        self.delete("all")
        self.create_image(0, 0, anchor="nw", image=self.photo)
        self.create_text(self.w / 2, self.h / 2, text=self.text, fill=fg, font=self.font)


class Choice(tk.Frame):
    def __init__(self, parent, options, value, on_pick, cols=None, wrap=None):
        super().__init__(parent, bg=parent["bg"])
        self.pills = {}
        self.on_pick = on_pick
        measure = tkfont.Font(family=FONT["semi"], size=10).measure
        line, used = None, 0
        for i, (v, label) in enumerate(options.items()):
            if cols:
                pill = Pill(self, label, lambda v=v: self.pick(v))
                pill.grid(row=i // cols, column=i % cols, padx=(0, px(6)), pady=(0, px(6)), sticky="w")
            else:
                w = measure(label) + px(13) * 2 + px(6)
                if line is None or (wrap and used and used + w > wrap):
                    line = tk.Frame(self, bg=self["bg"])
                    line.pack(anchor="w", pady=(0, px(6) if wrap else 0))
                    used = 0
                pill = Pill(line, label, lambda v=v: self.pick(v))
                pill.pack(side="left", padx=(0, px(6)))
                used += w
            self.pills[v] = pill
        self.set(value)

    def set(self, value):
        for v, pill in self.pills.items():
            pill.set_kind("on" if same(v, value) else "chip")

    def pick(self, value):
        self.set(value)
        self.on_pick(value)


class FramePick(tk.Frame):
    def __init__(self, parent, value, on_pick, current, wrap, options=FORMATS, limits=core.FRAME_RANGE):
        super().__init__(parent, bg=parent["bg"])
        self.on_pick, self.current, self.job, self.limits = on_pick, current, None, limits
        custom = core.exact_of(value)
        self.choice = Choice(self, {**options, "custom": "Свой"}, "custom" if custom else value, self.pick, wrap=wrap)
        self.choice.pack(anchor="w")
        self.line = tk.Frame(self, bg=self["bg"])
        self.w = self.entry()
        tk.Label(self.line, text="×", bg=self["bg"], fg=SUB, font=(FONT["ui"], 10)).pack(side="left", padx=px(6))
        self.h = self.entry()
        tk.Label(self.line, text="px", bg=self["bg"], fg=SUB, font=(FONT["ui"], 10)).pack(side="left", padx=px(6))
        if custom:
            self.fill(custom)
            self.line.pack(anchor="w", pady=(px(2), 0))
        self.bind("<Destroy>", lambda e: e.widget is self and self.job and self.after_cancel(self.job))

    def entry(self):
        e = tk.Entry(self.line, width=6, bg=ROW, fg=WHITE, insertbackground=WHITE, relief="flat", justify="center",
                     font=(FONT["ui"], 10), highlightthickness=1, highlightbackground=LINE, highlightcolor=WHITE)
        e.pack(side="left", ipady=px(4))
        e.bind("<KeyRelease>", lambda _: self.typed())
        return e

    def fill(self, size):
        for e, v in zip((self.w, self.h), size):
            e.delete(0, "end")
            e.insert(0, str(v))

    def pick(self, value):
        if value == "custom":
            self.fill(self.current())
            self.line.pack(anchor="w", pady=(px(2), 0))
            self.apply()
        else:
            self.line.pack_forget()
            self.on_pick(value)

    def typed(self):
        if self.job:
            self.after_cancel(self.job)
        self.job = self.after(250, self.apply)

    def apply(self):
        self.job = None
        for e in (self.w, self.h):
            pasted = re.split(r"\s*[x×х*]\s*|\s+", e.get().strip().lower())
            if len(pasted) == 2 and all(pasted):
                self.fill(pasted)
                break
        lo, hi = self.limits
        values = [e.get().strip() for e in (self.w, self.h)]
        ok = [v.isdigit() and lo <= int(v) <= hi for v in values]
        for e, good in zip((self.w, self.h), ok):
            e.config(fg=WHITE if good else ERR, highlightbackground=LINE if good else ERR)
        if all(ok):
            self.on_pick(f"{int(values[0])}x{int(values[1])}")


class SizePick(tk.Frame):
    def __init__(self, parent, value, on_pick, wrap):
        super().__init__(parent, bg=parent["bg"])
        options = SIZES if value in SIZES else {**SIZES, value: value}
        self.choice = Choice(self, options, value, on_pick, wrap=wrap)
        self.note = tk.Label(self, text="Задан шириной и высотой кадра", bg=self["bg"], fg=SUB,
                             font=(FONT["ui"], 10), anchor="w")

    def show(self, fmt):
        self.choice.pack_forget()
        self.note.pack_forget()
        (self.note if core.exact_of(fmt) else self.choice).pack(anchor="w")


class Painter:
    def __init__(self, canvas):
        self.c = canvas
        self.key = None
        self.layer = None
        self.photos = []
        self.geo = None
        self.scaled = None
        self.small = {}
        self.layers = []
        self.pieces = {}

    def frame(self, bg, rect, size):
        x0, y0, x1, y1 = rect
        d = size[0] / (x1 - x0)
        if d >= 1:
            return Image.fromarray(bg[y0:y1, x0:x1]).resize(size, Image.BILINEAR)
        if self.scaled is None or self.scaled[0] is not bg or self.scaled[1] != d:
            H, W = bg.shape[:2]
            whole = Image.fromarray(bg).resize((max(1, round(W * d)), max(1, round(H * d))), Image.BILINEAR,
                                               reducing_gap=2.0)
            self.scaled = (bg, d, whole)
        part = self.scaled[2].crop((round(x0 * d), round(y0 * d), round(x1 * d), round(y1 * d)))
        return part if part.size == size else part.resize(size, Image.BILINEAR)

    def draw(self, shot, area, tag="shot"):
        bg, rows, edit = shot["bg"], shot["rows"], shot["edit"]
        p = core.plan(bg, edit)
        out_w, out_h = p["size"]
        ax, ay, aw, ah = area
        d = min(aw / out_w, ah / out_h)
        dw, dh = max(1, round(out_w * d)), max(1, round(out_h * d))
        ix, iy = ax + (aw - dw) // 2, ay + (ah - dh) // 2
        frame = self.frame(bg, p["rect"], (dw, dh))
        groups = core.parts(rows, edit)
        key = (id(shot), shot.get("name"), id(rows), len(rows), tuple(r["keep"] for r in rows),
               tuple((tuple(map(tuple, r.get("hide", []))), tuple(map(tuple, r.get("drop", [])))) for r in rows),
               tuple(core.cuts(rows, edit)), p["outline"], round(p["scale"], 4), out_h, p["margin"])
        if key != self.key:
            self.layers = [chat.chat_layer(part, p["outline"], p["scale"], out_h - 2 * p["margin"])
                           for part, _ in groups]
            self.key = key
            self.small = {}
        self.c.delete(tag)
        self.photos = [ImageTk.PhotoImage(frame)]
        self.c.create_image(ix, iy, anchor="nw", image=self.photos[0], tags=(tag,))
        pad = p["outline"] + 2
        geo = {"img": (ix, iy, dw, dh), "d": d, "out": (out_w, out_h), "plan": p, "pad": pad, "chats": [],
               "painted": sum(n for _, n, _ in self.layers), "overlays": []}
        self.draw_overlays(shot, geo, tag)
        for k, ((layer, _, _), (_, pos)) in enumerate(zip(self.layers, groups)):
            if layer is None:
                geo["chats"].append(None)
                continue
            lh, lw = layer.shape[:2]
            left, top = chat.place(out_w, out_h, lw, lh, pad, pos, p["margin"])
            size = (max(1, round(lw * d)), max(1, round(lh * d)))
            if k not in self.small or self.small[k][0] != size:
                small = Image.fromarray(layer, "RGBA").resize(size, Image.LANCZOS)
                self.small[k] = (size, ImageTk.PhotoImage(small))
            self.photos.append(self.small[k][1])
            cx, cy = ix + round(left * d), iy + round(top * d)
            self.c.create_image(cx, cy, anchor="nw", image=self.small[k][1], tags=(tag, tag + "-chat", f"{tag}-chat{k}"))
            geo["chats"].append({"x": cx, "y": cy, "w": size[0], "h": size[1], "lw": lw, "lh": lh})
        self.geo = geo
        return geo

    def draw_overlays(self, shot, geo, tag):
        out, overlays = shot.get("out"), shot["edit"].get("overlays", [])
        ix, iy, dw, dh = geo["img"]
        d, (out_w, out_h) = geo["d"], geo["out"]
        if len(self.pieces) > 12:
            self.pieces.clear()
        for k, ov in enumerate(overlays if out else []):
            try:
                source = core.overlay_image(out / "src" / ov["file"])
            except OSError:
                geo["overlays"].append(None)
                continue
            x, y, w, h = core.overlay_box(ov, (out_w, out_h), source.size)
            dx, dy = round(ix + x * d), round(iy + y * d)
            size = (max(1, round(w * d)), max(1, round(h * d)))
            key = (ov["file"], tuple(ov["crop"]), size)
            if key not in self.pieces:
                self.pieces[key] = core.overlay_piece(source, ov, size)
            l, t = max(ix, dx), max(iy, dy)
            r, b = min(ix + dw, dx + size[0]), min(iy + dh, dy + size[1])
            if r <= l or b <= t:
                geo["overlays"].append(None)
                continue
            photo = ImageTk.PhotoImage(self.pieces[key].crop((l - dx, t - dy, r - dx, b - dy)))
            self.photos.append(photo)
            self.c.create_image(l, t, anchor="nw", image=photo, tags=(tag, tag + "-ov", f"{tag}-ov{k}"))
            geo["overlays"].append({"x": dx, "y": dy, "w": size[0], "h": size[1], "box": (l, t, r, b)})


class Feed:
    def __init__(self, app, parent):
        self.app = app
        self.c = tk.Canvas(parent, bg=VOID, highlightthickness=0, bd=0)
        self.painter = Painter(self.c)
        self.names = []
        self.index = 0
        self.shot = None
        self.cache = {}
        self.tool = None
        self.drag = None
        self.busy = False
        self.message = None
        self.note = ""
        self.save_job = None
        self.save_target = None
        self.click_mode = "rows"
        self.active_ov = 0
        self.loading = set()
        self.offset = 0
        self.last_wheel = 0.0
        self.sheet = None
        self.media = None
        self.photos = []
        self.pending_media = False
        self.media_src = None
        self.resize_job = None
        self.c.bind("<Configure>", lambda _: self.settle())
        self.c.bind("<ButtonPress-1>", self.press)
        self.c.bind("<B1-Motion>", self.motion)
        self.c.bind("<ButtonRelease-1>", self.release)
        self.c.bind("<MouseWheel>", self.wheel)
        self.c.bind("<Motion>", self.hover)
        self.refresh_names()

    def refresh_names(self):
        self.names = core.list_shots(self.app.cfg["out"])
        self.media = None

    @property
    def name(self):
        return self.names[self.index - 1] if 0 < self.index <= len(self.names) else None

    def area(self):
        W, H = self.c.winfo_width(), self.c.winfo_height()
        return SIDE_W, px(12), W - SIDE_W - RAIL_W, H - px(24)

    def go(self, index):
        index = max(0, min(index, len(self.names)))
        if index == self.index and (index == 0 or self.shot is not None):
            return
        self.index, self.tool, self.offset, self.note = index, None, 0, ""
        self.open_current()

    def open_current(self):
        self.flush_save()
        name = self.name
        self.shot = None
        if name is None:
            self.redraw()
            return
        if name in self.cache:
            self.shot = self.cache[name] or None
            self.redraw()
            self.fetch_next()
            return
        self.redraw()
        self.fetch(name)

    def fetch(self, name):
        if name in self.cache or name in self.loading:
            return
        self.loading.add(name)
        cfg = self.app.cfg

        def work():
            try:
                shot = core.load_shot(cfg["out"], name, cfg)
            except Exception:
                shot = None
            self.app.inbox.put(("loaded", name, shot))

        threading.Thread(target=work, daemon=True).start()

    def fetch_next(self):
        if 0 < self.index < len(self.names):
            self.fetch(self.names[self.index])

    def loaded(self, name, shot):
        self.loading.discard(name)
        self.cache[name] = shot or False
        if len(self.cache) > 6:
            self.cache.pop(next(iter(self.cache)))
        if name == self.name:
            self.shot = shot
            self.redraw()
            self.fetch_next()

    def new_shot(self, name):
        if self.save_job and self.save_target and self.save_target.get("name") == name:
            self.c.after_cancel(self.save_job)
            self.save_job = None
        self.cache.pop(name, None)
        self.refresh_names()
        if self.drag is None:
            self.index, self.tool, self.offset = 1, None, 0
            self.note = "только что"
            self.open_current()

    def settle(self):
        if self.resize_job:
            self.c.after_cancel(self.resize_job)
        self.resize_job = self.c.after(110, self.settled)

    def settled(self):
        self.resize_job = None
        self.redraw()

    def redraw(self):
        W, H = self.c.winfo_width(), self.c.winfo_height()
        if W < 100 or H < 100:
            return
        self.c.delete("all")
        self.photos = []
        if self.sheet:
            self.sheet.destroy()
            self.sheet = None
        if self.index == 0:
            self.draw_ready(W, H)
        else:
            self.draw_item(W, H)

    def text(self, x, y, s, font, fill=WHITE, width=None, tags=("cap",)):
        item = self.c.create_text(x, y, text=s, font=font, fill=fill, anchor="nw", width=width, tags=tags)
        return self.c.bbox(item)[3]

    def lift_block(self, tag, bottom):
        box = self.c.bbox(tag)
        if box:
            self.c.move(tag, 0, bottom - box[3])

    def ready_media(self, W, H):
        if self.media and self.media[0] == (W, H):
            return self.media[1]
        photo = None
        if self.names:
            path = core.shot_image(self.app.cfg["out"], self.names[0])
            try:
                key = (path, path.stat().st_mtime)
                if self.media_src is None or self.media_src[0] != key:
                    with Image.open(path) as im:
                        im = im.convert("RGB")
                        im.thumbnail((360, 360), Image.BILINEAR)
                    self.media_src = (key, ImageEnhance.Brightness(im).enhance(0.3))
                small = self.media_src[1]
                k = max(W / small.width, H / small.height)
                sw, sh = max(1, round(W / k)), max(1, round(H / k))
                left, top = (small.width - sw) // 2, (small.height - sh) // 2
                im = small.crop((left, top, left + sw, top + sh)).filter(ImageFilter.GaussianBlur(22 / k))
                im = im.resize((W, H), Image.BICUBIC)
                scrim = Image.linear_gradient("L").resize((W, H)).point(lambda v: int(v * 0.85))
                photo = ImageTk.PhotoImage(Image.composite(Image.new("RGB", (W, H), VOID), im, scrim))
            except OSError:
                photo = None
        self.media = ((W, H), photo)
        return photo

    def draw_ready(self, W, H):
        cfg = self.app.cfg
        media = self.ready_media(W, H)
        if media:
            self.c.create_image(0, 0, anchor="nw", image=media)
        key, hud, dark = cfg["key"], cfg["hud_key"], cfg["dark_key"]
        x, width = PAD + px(12), SIDE_W + px(120)
        cap_h = px(54)
        cap = rounded(tkfont.Font(family=FONT["display"], size=20).measure(key) + px(44), cap_h, px(14), None, WHITE,
                      1.4 * K)
        self.photos.append(ImageTk.PhotoImage(cap))
        self.c.create_image(x, 0, anchor="nw", image=self.photos[-1], tags=("cap",))
        self.c.create_text(x + cap.width / 2, cap_h / 2, text=key, fill=WHITE, font=(FONT["display"], 20), tags=("cap",))
        y = cap_h + px(26)
        title, body, level = "Готово к съёмке", None, "info"
        if self.busy:
            title = "Снимаю…"
        elif self.message:
            level, body = self.message
            title = {"fail": "Не вышло", "step": "Половина есть"}.get(level, title)
        if body is None:
            if cfg["auto"]:
                body = (f"Нажми {key} в игре и программа сама спрячет интерфейс и затемнит экран, "
                        f"а готовая СС появится здесь или в папке скриншотов.")
            else:
                body = (f"В игре нажми {hud}, затем {key} — это фон. Потом {dark}, затем {key} — это чат. "
                        f"Готовая СС появится здесь или в папке скриншотов.")
        if level == "fail":
            dot = ImageTk.PhotoImage(rounded(px(10), px(10), px(5), ERR))
            self.photos.append(dot)
            self.c.create_image(x, y + px(16), anchor="nw", image=dot, tags=("cap",))
            y = self.text(x + px(22), y, title, (FONT["display"], 30)) + px(12)
        else:
            y = self.text(x, y, title, (FONT["display"], 30)) + px(12)
        y = self.text(x, y, body, (FONT["ui"], 13), SUB if level != "fail" else WHITE, width) + px(14)
        y = self.text(x, y, f"Памятка: если диалог длинный, то нажми {dark} и вновь {key}. "
                            f"Тогда в одной СС будет несколько чатбоксов.", (FONT["ui"], 10), SUB, width)
        if self.app.update:
            version, url = self.app.update
            self.c.create_text(x, y + px(10), text=f"Вышла Snapline {version} — скачать", fill=WHITE, anchor="nw",
                               font=(FONT["semi"], 10), tags=("cap", "update", "link"))
            self.c.tag_bind("update", "<Button-1>", lambda _: os.startfile(url))
            self.c.tag_bind("update", "<Enter>", lambda _: self.c.config(cursor="hand2"))
            self.c.tag_bind("update", "<Leave>", lambda _: self.c.config(cursor=""))
        self.lift_block("cap", H - PAD - px(12))
        if self.names:
            cx = (x + width + W - RAIL_W) / 2
            label = f"Прошлые СС · {len(self.names)}"
            self.c.create_text(cx, H - PAD - px(4), text=label, fill=SUB, font=(FONT["ui"], 10), anchor="s",
                               tags=("older", "link"))
            if FONT["icon"]:
                self.c.create_text(cx, H - PAD - px(26), text=ICONS["down"], fill=SUB, font=(FONT["icon"], 14),
                                   anchor="s", tags=("older", "link"))
            self.c.tag_bind("older", "<Button-1>", lambda _: self.go(1))
            self.hover_link("older")
        self.rail(W, H, [("folder", "Папка", self.open_folder, False)])

    def hover_link(self, tag):
        self.c.tag_bind(tag, "<Enter>", lambda _: (self.c.itemconfig(tag, fill=WHITE), self.c.config(cursor="hand2")))
        self.c.tag_bind(tag, "<Leave>", lambda _: (self.c.itemconfig(tag, fill=SUB), self.c.config(cursor="")))

    def draw_item(self, W, H):
        area = self.area()
        name = self.name
        view_only = self.cache.get(name) is False
        geo = None
        if self.shot is None:
            self.draw_saved(area, name)
        elif self.tool == "lines":
            self.draw_lines(area)
        else:
            geo = self.painter.draw(self.shot, area)
            if self.tool == "crop":
                ix, iy, dw, dh = geo["img"]
                self.c.create_rectangle(ix - 1, iy - 1, ix + dw, iy + dh, outline=WHITE, width=1, tags=("shot",))
            self.mark_overlay(geo)
        if self.tool:
            self.build_sheet(H)
        else:
            self.caption(H, name, view_only)
        tools = [] if self.shot is None else [
            ("lines", "Строки", lambda: self.toggle_tool("lines"), self.tool == "lines"),
            ("crop", "Кадр", lambda: self.toggle_tool("crop"), self.tool == "crop"),
            ("text", "Текст", lambda: self.toggle_tool("text"), self.tool == "text"),
            ("images", "Картинки", lambda: self.toggle_tool("images"), self.tool == "images"),
        ]
        if self.shot is not None or view_only:
            tools.append(("copy", "Копировать", self.copy, False))
        tools.append(("folder", "В папке", self.open_folder, False))
        self.rail(W, H, tools)

    def draw_saved(self, area, name):
        ax, ay, aw, ah = area
        try:
            with Image.open(core.shot_image(self.app.cfg["out"], name)) as im:
                im = im.convert("RGB")
                im.thumbnail((aw, ah), Image.BILINEAR)
                self.photos.append(ImageTk.PhotoImage(im))
                self.c.create_image(ax + aw // 2, ay + ah // 2, image=self.photos[-1], tags=("shot",))
        except OSError:
            self.c.create_text(ax + aw // 2, ay + ah // 2, text="Файл СС не найден", fill=SUB, font=(FONT["ui"], 12))

    def meta(self):
        if self.shot is None:
            return "загружаю…" if self.cache.get(self.name) is None else "только просмотр"
        w, h = core.plan(self.shot["bg"], self.shot["edit"])["size"]
        parts = [f"{w} × {h}"]
        geo = self.painter.geo
        kept = sum(r["keep"] for r in self.shot["rows"])
        if geo and self.tool != "lines" and geo["painted"] < kept:
            parts.append(f"влезло {geo['painted']} из {kept} строк")
        if self.note:
            parts.append(self.note)
        elif self.shot.get("legacy"):
            parts.append("старая СС, файл обновится после правки")
        return " · ".join(parts)

    def caption(self, H, name, view_only):
        x, width = PAD + px(12), SIDE_W - PAD - px(24)
        y = self.text(x, 0, when(name), (FONT["display"], 24)) + px(6)
        y = self.text(x, y, self.meta(), (FONT["ui"], 11), SUB, width, tags=("cap", "meta")) + px(18)
        if view_only:
            hint = "Исходные кадры этой СС не найдены, её можно только посмотреть и скопировать."
        else:
            hint = ("Чат можно перетащить мышью, у краёв он прилипает к углам. "
                    "Строки, кадр, текст и картинки — справа или клавишами 1–4. Колесо мыши листает СС.")
        self.text(x, y, hint, (FONT["ui"], 10), SUB, width)
        self.lift_block("cap", H - PAD - px(12))

    def rail(self, W, H, items):
        cx = W - RAIL_W / 2
        step = px(76)
        y = H / 2 - (len(items) * step) / 2 + px(20)
        for key, label, command, active in items:
            tag = f"rail-{key}"
            if active:
                self.photos.append(ImageTk.PhotoImage(rounded(px(46), px(46), px(23), WHITE)))
                self.c.create_image(cx, y, image=self.photos[-1], tags=(tag, "rail"))
            if FONT["icon"]:
                self.c.create_text(cx, y, text=ICONS[key], font=(FONT["icon"], 18), fill=VOID if active else WHITE,
                                   tags=(tag, "rail", tag + "-ink" if not active else tag + "-on"))
            self.c.create_text(cx, y + px(34), text=label, font=(FONT["ui"], 9), fill=WHITE if active else SUB,
                               tags=(tag, "rail", tag + "-label"))
            self.c.create_rectangle(cx - px(46), y - px(28), cx + px(46), y + px(46), outline="", fill="",
                                    tags=(tag, "rail"))
            self.c.tag_bind(tag, "<Button-1>", lambda _, f=command: f())
            if not active:
                self.c.tag_bind(tag, "<Enter>", lambda _, t=tag: (self.c.itemconfig(t + "-label", fill=WHITE),
                                                                  self.c.config(cursor="hand2")))
                self.c.tag_bind(tag, "<Leave>", lambda _, t=tag: (self.c.itemconfig(t + "-label", fill=SUB),
                                                                  self.c.config(cursor="")))
            y += step
        if self.names:
            total = len(self.names) + 1
            ny = H - PAD - px(40)
            pos = "съёмка" if self.index == 0 else f"{self.index} из {len(self.names)}"
            self.c.create_text(cx, ny, text=pos, font=(FONT["ui"], 9), fill=SUB, tags=("rail",))
            if FONT["icon"]:
                for key, dy, delta, enabled in (("up", -px(26), -1, self.index > 0),
                                                ("down", px(24), 1, self.index < total - 1)):
                    tag = f"nav-{key}"
                    self.c.create_text(cx, ny + dy, text=ICONS[key], font=(FONT["icon"], 13),
                                       fill=SUB if enabled else MIST, tags=(tag, "rail"))
                    if enabled:
                        self.c.tag_bind(tag, "<Button-1>", lambda _, d=delta: self.go(self.index + d))
                        self.hover_link(tag)

    def toggle_tool(self, tool):
        self.tool = None if self.tool == tool else tool
        self.offset = 0
        self.redraw()

    def build_sheet(self, H):
        sheet = tk.Frame(self.c, bg=VOID)
        self.sheet_w = SIDE_W - 2 * PAD - px(12)
        sheet.place(x=PAD + px(12), y=PAD, width=self.sheet_w, height=H - 2 * PAD)
        self.sheet = sheet
        head = tk.Frame(sheet, bg=VOID)
        head.pack(fill="x")
        title = {"lines": "Строки чата", "crop": "Кадр", "text": "Текст", "images": "Картинки"}[self.tool]
        tk.Label(head, text=title, bg=VOID, fg=WHITE, font=(FONT["display"], 20)).pack(side="left")
        close = tk.Label(head, text=ICONS["close"] if FONT["icon"] else "Закрыть", bg=VOID, fg=SUB, cursor="hand2",
                         font=(FONT["icon"], 12) if FONT["icon"] else (FONT["ui"], 10))
        close.pack(side="right", pady=(px(6), 0))
        close.bind("<Button-1>", lambda _: self.toggle_tool(self.tool))
        close.bind("<Enter>", lambda _: close.config(fg=WHITE))
        close.bind("<Leave>", lambda _: close.config(fg=SUB))
        body = tk.Frame(sheet, bg=VOID)
        body.pack(fill="both", expand=True, pady=(px(18), 0))
        getattr(self, "sheet_" + self.tool)(body)
        self.sheet_meta = tk.Label(sheet, text=self.meta(), bg=VOID, fg=SUB, font=(FONT["ui"], 10), anchor="w",
                                   justify="left", wraplength=self.sheet_w)
        self.sheet_meta.pack(fill="x")

    def label(self, parent, text, top=0):
        tk.Label(parent, text=text, bg=VOID, fg=SUB, font=(FONT["ui"], 10), anchor="w", justify="left",
                 wraplength=self.sheet_w).pack(fill="x", pady=(px(top), px(8)))

    def choice(self, body, options, value, on_pick, **kw):
        Choice(body, options, value, on_pick, wrap=self.sheet_w, **kw).pack(anchor="w")

    def sheet_lines(self, body):
        self.label(body, "Нажимай на строки справа: белая галочка — строка в СС, пустой квадрат — убрана. "
                         "Колесо мыши прокручивает список.")
        self.label(body, "Ножницы у строки делят чат на части, до трёх. Каждую часть можно поставить в свой угол "
                         "или перетащить на картинке.", 6)
        self.label(body, "Клик по строке", 6)
        self.choice(body, CLICKS, self.click_mode, self.set_click)
        self.label(body, "Скрытое слово закрывается плашкой под цвет реплики, удалённое пропадает вместе с "
                         "пробелом. Повторный клик возвращает слово.", 6)
        self.count = tk.Label(body, text=self.count_text(), bg=VOID, fg=WHITE, font=(FONT["semi"], 12), anchor="w")
        self.count.pack(fill="x", pady=(px(6), px(14)))
        Pill(body, "Как после съёмки", self.reset_lines, kind="ghost").pack(anchor="w")

    def sheet_crop(self, body):
        edit = self.shot["edit"]
        self.label(body, "Формат")
        FramePick(body, edit["format"], self.set_frame, lambda: core.plan(self.shot["bg"], self.shot["edit"])["size"],
                  self.sheet_w).pack(anchor="w")
        self.label(body, "Приближение", 12)
        self.choice(body, ZOOMS, edit["zoom"], lambda v: self.change(zoom=float(v)))
        self.label(body, "Размер файла", 12)
        self.size_pick = SizePick(body, edit["size"], lambda v: self.change(size=v), self.sheet_w)
        self.size_pick.pack(fill="x")
        self.size_pick.show(edit["format"])
        self.label(body, "Файл", 12)
        self.choice(body, FILES, edit["file"], lambda v: self.change(file=v))
        self.label(body, "Тяни картинку мышью, чтобы выбрать, что попадёт в кадр. Ctrl + колесо — приближение.", 12)
        Pill(body, "По центру", lambda: self.change(center=[0.5, 0.5]), kind="ghost").pack(anchor="w")

    def set_frame(self, value):
        self.change(format=value, center=[0.5, 0.5])
        self.size_pick.show(value)

    def sheet_text(self, body):
        edit = self.shot["edit"]
        self.label(body, "Размер текста")
        self.choice(body, SCALES, edit["text_scale"], lambda v: self.change(text_scale=float(v)))
        self.label(body, "Обводка", 12)
        self.choice(body, OUTLINES, edit["outline"], lambda v: self.change(outline=int(v)))
        spots = [pos for _, pos in core.parts(self.shot["rows"], edit)]
        for k, pos in enumerate(spots):
            self.label(body, "Угол" if len(spots) == 1 else f"Угол, часть {k + 1}", 12)
            self.choice(body, POSITIONS, pos if isinstance(pos, str) else None,
                        lambda v, k=k: self.pick_place(k, v), cols=2)
        self.label(body, "Или перетащи чат прямо на картинке.", 6)

    def change(self, **values):
        if self.shot is None:
            return
        self.shot["edit"].update(values)
        self.media_redraw()
        self.schedule_save()

    def media_redraw(self):
        if self.shot is None or self.index == 0:
            return
        if self.tool == "lines":
            self.draw_lines(self.area())
        else:
            self.c.delete("shot")
            geo = self.painter.draw(self.shot, self.area())
            if self.tool == "crop":
                ix, iy, dw, dh = geo["img"]
                self.c.create_rectangle(ix - 1, iy - 1, ix + dw, iy + dh, outline=WHITE, width=1, tags=("shot",))
            self.mark_overlay(geo)
            self.c.tag_lower("shot")
        self.update_meta()

    def update_meta(self):
        if self.sheet is not None:
            self.sheet_meta.config(text=self.meta())
        else:
            self.c.itemconfig("meta", text=self.meta())

    def draw_lines(self, area):
        self.c.delete("shot")
        ax, ay, aw, ah = area
        rows = self.shot["rows"]
        widest = max(r["glyphs"][-1][1] + 8 for r in rows)
        s = min(1.0, (aw - px(104)) / widest)
        breaks = core.cuts(rows, self.shot["edit"])
        self.lines_x0, self.lines_s = ax + px(48), s
        slot = max(px(28), round(rows[0]["pitch"] * s) + px(12))
        self.offset = max(0, min(self.offset, max(0, slot * len(rows) + px(24) - ah)))
        self.c.create_rectangle(ax, ay, ax + aw, ay + ah, fill=BLACK, outline="", tags=("shot",))
        y = ay + px(12) - self.offset
        self.row_photos = []
        on, off = ImageTk.PhotoImage(tick(px(18), True)), ImageTk.PhotoImage(tick(px(18), False))
        self.row_photos += [on, off]
        for i, r in enumerate(rows):
            if y + slot > ay and y < ay + ah:
                tag = f"row{i}"
                self.c.create_rectangle(ax, y, ax + aw, y + slot, fill=BLACK, outline="",
                                        tags=("shot", tag, tag + "-bg"))
                crop = chat.masked(r, preview=True)[:, :r["glyphs"][-1][1] + 8] * (1.0 if r["keep"] else 0.3)
                img = Image.fromarray(np.uint8(np.clip(crop, 0, 255)))
                if s < 1:
                    img = img.resize((max(1, round(img.width * s)), max(1, round(img.height * s))), Image.LANCZOS)
                photo = ImageTk.PhotoImage(img)
                self.row_photos.append(photo)
                self.c.create_image(ax + px(16), y + slot / 2, anchor="w", image=on if r["keep"] else off,
                                    tags=("shot", tag))
                self.c.create_image(ax + px(48), y + slot / 2, anchor="w", image=photo, tags=("shot", tag))
                if not r["keep"]:
                    self.c.create_line(ax + px(48), y + slot / 2, ax + px(48) + img.width, y + slot / 2, fill=LINE,
                                       tags=("shot", tag))
                for a, b in r.get("drop", []):
                    self.c.create_line(ax + px(48) + a * s, y + slot / 2, ax + px(48) + (b + 1) * s, y + slot / 2,
                                       fill=ERR, width=max(1, px(2)), tags=("shot", tag))
                if i in breaks:
                    self.c.create_line(ax + px(16), y, ax + aw - px(16), y, fill=SUB, dash=(4, 3), tags=("shot",))
                    self.c.create_text(ax + aw - px(52), y + px(2), text=f"часть {breaks.index(i) + 2}", fill=SUB,
                                       anchor="ne", font=(FONT["ui"], 9), tags=("shot",))
                if i:
                    cut = f"cut{i}"
                    glyph, face = (ICONS["cut"], (FONT["icon"], 12)) if FONT["icon"] else ("✂", (FONT["ui"], 12))
                    self.c.create_text(ax + aw - px(28), y + slot / 2, text=glyph, font=face, tags=("shot", cut),
                                       fill=WHITE if i in breaks else MIST)
                    self.c.tag_bind(cut, "<Enter>", lambda _, t=cut: (self.c.itemconfig(t, fill=WHITE),
                                                                      self.c.config(cursor="hand2")))
                    self.c.tag_bind(cut, "<Leave>", lambda _, t=cut, on=i in breaks: (
                        self.c.itemconfig(t, fill=WHITE if on else MIST), self.c.config(cursor="")))
                self.c.tag_bind(tag, "<Enter>", lambda _, t=tag: (self.c.itemconfig(t + "-bg", fill=ROW),
                                                                  self.c.config(cursor="hand2")))
                self.c.tag_bind(tag, "<Leave>", lambda _, t=tag: (self.c.itemconfig(t + "-bg", fill=BLACK),
                                                                  self.c.config(cursor="")))
            y += slot
        self.c.tag_lower("shot")

    def set_click(self, value):
        self.click_mode = value

    def toggle_word(self, i, x, key):
        r = self.shot["rows"][i]
        word = next(((a, b) for a, b in chat.words(r) if a - 3 <= x <= b + 3), None)
        if word is None:
            return
        other = "drop" if key == "hide" else "hide"
        mine = [tuple(span) for span in r.get(key, [])]
        r[other] = [tuple(span) for span in r.get(other, []) if tuple(span) != word]
        r[key] = [span for span in mine if span != word] if word in mine else mine + [word]
        for name, field in core.MARKS:
            self.shot["edit"][field] = core.spans_of(self.shot["rows"], name)
        self.draw_lines(self.area())
        self.schedule_save()

    def mark_overlay(self, geo):
        if self.tool != "images" or not geo or self.active_ov >= len(geo["overlays"]):
            return
        box = geo["overlays"][self.active_ov]
        if not box:
            return
        l, t, r, b = box["x"], box["y"], box["x"] + box["w"], box["y"] + box["h"]
        self.c.create_rectangle(l, t, r - 1, b - 1, outline=WHITE, width=1, dash=(4, 3), tags=("shot",))
        locked = core.lock_ratio(self.shot["edit"]["overlays"][self.active_ov].get("cut", "free")) is not None
        spots = {"l": (l, (t + b) / 2), "r": (r, (t + b) / 2), "t": ((l + r) / 2, t), "b": ((l + r) / 2, b),
                 "lt": (l, t), "rt": (r, t), "lb": (l, b), "rb": (r, b)}
        k = px(5)
        for name in HANDLES:
            if locked and len(name) == 1:
                continue
            x, y = spots[name]
            tag = f"handle-{name}"
            self.c.create_rectangle(x - k, y - k, x + k, y + k, fill=WHITE, outline=VOID, tags=("shot", tag))
            cursor = {"l": "sb_h_double_arrow", "r": "sb_h_double_arrow", "t": "sb_v_double_arrow",
                      "b": "sb_v_double_arrow"}.get(name, "sizing")
            self.c.tag_bind(tag, "<Enter>", lambda _, c=cursor: self.c.config(cursor=c))
            self.c.tag_bind(tag, "<Leave>", lambda _: self.c.config(cursor=""))

    def sheet_images(self, body):
        overlays = self.shot["edit"].setdefault("overlays", [])
        self.label(body, "Картинки поверх СС: коллажи, вставки, стикеры. Тяни картинку мышью, колесо меняет "
                         "размер. Белые метки по краям обрезают картинку, Shift + тяни внутри — сдвигает обрезку.")
        line = tk.Frame(body, bg=VOID)
        line.pack(anchor="w", pady=(px(4), 0))
        Pill(line, "Из файла", self.add_file, kind="ghost").pack(side="left", padx=(0, px(6)))
        Pill(line, "Из буфера", self.add_clipboard, kind="ghost").pack(side="left")
        if not overlays:
            return
        self.active_ov = min(self.active_ov, len(overlays) - 1)
        ov = overlays[self.active_ov]
        if len(overlays) > 1:
            self.label(body, "Картинка", 12)
            self.choice(body, {str(i): str(i + 1) for i in range(len(overlays))}, str(self.active_ov),
                        lambda v: self.select_ov(int(v)))
        self.label(body, "Обрезка", 12)
        FramePick(body, ov.get("cut", "free"), self.crop_ov, self.crop_size, self.sheet_w, CROPS, (16, 20000)).pack(
            anchor="w")
        Pill(body, "Сбросить обрезку", lambda: self.crop_ov("reset"), kind="ghost").pack(anchor="w", pady=(px(8), 0))
        self.label(body, "Размер по ширине кадра", 12)
        self.choice(body, OV_SIZES, ov["w"], lambda v: self.change_ov(w=float(v)))
        Pill(body, "Убрать картинку", self.remove_ov, kind="ghost").pack(anchor="w", pady=(px(16), 0))

    def add_file(self):
        path = filedialog.askopenfilename(title="Картинка поверх СС", filetypes=[
            ("Картинки", "*.png *.jpg *.jpeg *.webp *.bmp *.gif"), ("Все файлы", "*.*")])
        if path:
            try:
                with Image.open(path) as im:
                    self.add_image(im.copy())
            except OSError as e:
                self.note = f"картинка не открылась: {e}"
                self.update_meta()

    def add_clipboard(self):
        try:
            data = ImageGrab.grabclipboard()
            if isinstance(data, list):
                with Image.open(next(p for p in data if Path(p).is_file())) as im:
                    data = im.copy()
        except (OSError, StopIteration):
            data = None
        if not isinstance(data, Image.Image):
            self.note = "в буфере обмена нет картинки"
            self.update_meta()
            return
        self.add_image(data)

    def add_image(self, image):
        overlays = self.shot["edit"].setdefault("overlays", [])
        if len(overlays) >= core.MAX_OVERLAYS:
            self.note = f"больше {core.MAX_OVERLAYS} картинок не поместится"
            self.update_meta()
            return
        try:
            overlays.append(core.add_overlay(self.shot["out"], self.shot["name"], image))
        except OSError as e:
            self.note = f"картинка не сохранилась: {e}"
            self.update_meta()
            return
        self.active_ov = len(overlays) - 1
        self.redraw()
        self.schedule_save()

    def select_ov(self, k):
        self.active_ov = k
        self.redraw()

    def source_size(self, ov):
        try:
            return core.overlay_image(self.shot["out"] / "src" / ov["file"]).size
        except OSError:
            return None

    def crop_size(self):
        ov = self.shot["edit"]["overlays"][self.active_ov]
        W, H = self.source_size(ov) or (1, 1)
        l, t, r, b = ov["crop"]
        return round((r - l) * W), round((b - t) * H)

    def crop_ov(self, value):
        ov = self.shot["edit"]["overlays"][self.active_ov]
        size = self.source_size(ov)
        if size is None:
            return
        out_w = core.plan(self.shot["bg"], self.shot["edit"])["size"][0]
        before = ov["w"] * out_w / max(1e-6, ov["crop"][2] - ov["crop"][0])
        exact = core.exact_of(value)
        if value == "reset":
            ov["crop"], value = [0.0, 0.0, 1.0, 1.0], "free"
        elif exact:
            ov["crop"] = core.crop_exact(size, exact[0], exact[1], ov["crop"])
        elif value != "free":
            ov["crop"] = core.crop_for(size, core.lock_ratio(value), ov["crop"])
        ov["w"] = round(before * (ov["crop"][2] - ov["crop"][0]) / out_w, 4)
        changed, ov["cut"] = ov.get("cut") != value, value
        if changed:
            self.redraw()
        else:
            self.media_redraw()
        self.schedule_save()

    def change_ov(self, **values):
        self.shot["edit"]["overlays"][self.active_ov].update(values)
        self.media_redraw()
        self.schedule_save()

    def remove_ov(self):
        overlays = self.shot["edit"]["overlays"]
        overlays.pop(self.active_ov)
        self.active_ov = max(0, self.active_ov - 1)
        self.redraw()
        self.schedule_save()

    def toggle_cut(self, i):
        rows, edit = self.shot["rows"], self.shot["edit"]
        breaks = core.cuts(rows, edit)
        spots = core.places(edit, len(breaks) + 1)[1:]
        if i in breaks:
            k = breaks.index(i)
            breaks.pop(k)
            spots.pop(k)
        elif len(breaks) >= core.MAX_PARTS - 1:
            self.note = "больше трёх частей не бывает"
            self.update_meta()
            return
        else:
            k = sorted(breaks + [i]).index(i)
            used = [edit["pos"]] + spots
            order = list(core.SPARE_PLACES[core.corner_of(edit["pos"])]) + list(core.CHAT_POSITIONS)
            free = [c for c in order if c not in used]
            breaks.insert(k, i)
            spots.insert(k, free[0] if free else core.places(edit, len(breaks) + 1)[-1])
        edit["breaks"], edit["places"] = breaks, spots
        self.draw_lines(self.area())
        self.count.config(text=self.count_text())
        self.schedule_save()

    def count_text(self):
        rows = self.shot["rows"]
        n = len(core.parts(rows, self.shot["edit"]))
        return f"В СС {sum(r['keep'] for r in rows)} из {len(rows)}" + (f" · частей: {n}" if n > 1 else "")

    def set_place(self, part, pos):
        edit = self.shot["edit"]
        if part == 0:
            edit["pos"] = pos
            return
        spots = core.places(edit, len(core.parts(self.shot["rows"], edit)))[1:]
        spots[part - 1] = pos
        edit["places"] = spots

    def pick_place(self, part, pos):
        if self.shot is None:
            return
        self.set_place(part, pos)
        self.media_redraw()
        self.schedule_save()

    def toggle_row(self, i):
        rows = self.shot["rows"]
        rows[i]["keep"] = not rows[i]["keep"]
        self.shot["edit"]["keep"] = [r["keep"] for r in rows]
        self.draw_lines(self.area())
        self.count.config(text=self.count_text())
        self.schedule_save()

    def reset_lines(self):
        keep = self.app.cfg["keep"]
        for r in self.shot["rows"]:
            r["keep"] = r["kind"] in keep
        self.shot["edit"]["keep"] = [r["keep"] for r in self.shot["rows"]]
        self.redraw()
        self.schedule_save()

    def tags_here(self):
        return self.c.gettags("current")

    def press(self, e):
        tags = self.tags_here()
        if any(t.startswith(("rail", "nav", "older")) for t in tags) or self.shot is None or self.index == 0:
            return
        row = next((t for t in tags if re.fullmatch(r"row\d+", t)), None)
        cut = next((t for t in tags if re.fullmatch(r"cut\d+", t)), None)
        if self.tool == "lines":
            if cut:
                self.toggle_cut(int(cut[3:]))
            elif row and self.click_mode != "rows":
                self.toggle_word(int(row[3:]), (e.x - self.lines_x0) / self.lines_s, self.click_mode)
            elif row:
                self.toggle_row(int(row[3:]))
            return
        handle = next((t[7:] for t in tags if t.startswith("handle-")), None)
        if self.tool == "images" and handle and self.painter.geo:
            item = self.shot["edit"]["overlays"][self.active_ov]
            box = self.painter.geo["overlays"][self.active_ov]
            size = self.source_size(item)
            if box and size:
                self.drag = {"kind": "crop", "handle": handle, "part": self.active_ov, "x": e.x, "y": e.y,
                             "crop": list(item["crop"]), "box": dict(box), "size": size}
            return
        ov = next((int(t[7:]) for t in tags if re.fullmatch(r"shot-ov\d+", t)), None)
        if self.tool == "images" and ov is not None:
            self.active_ov = ov
            item = self.shot["edit"]["overlays"][ov]
            kind = "ovpan" if e.state & 0x1 else "ov"
            self.drag = {"kind": kind, "part": ov, "x": e.x, "y": e.y, "at": (item["x"], item["y"]),
                         "crop": list(item["crop"])}
            self.c.config(cursor="fleur")
            return
        geo = self.painter.geo
        part = next((int(t[9:]) for t in tags if re.fullmatch(r"shot-chat\d+", t)), None)
        if geo and part is not None and part < len(geo["chats"]) and geo["chats"][part]:
            self.drag = {"kind": "chat", "part": part, "x": e.x, "y": e.y, "at": self.c.coords(f"shot-chat{part}")}
        elif geo and self.tool == "crop" and self.inside(e, geo):
            self.drag = {"kind": "pan", "x": e.x, "y": e.y, "center": list(self.shot["edit"]["center"])}
            self.c.config(cursor="fleur")

    def inside(self, e, geo):
        ix, iy, dw, dh = geo["img"]
        return ix <= e.x <= ix + dw and iy <= e.y <= iy + dh

    def motion(self, e):
        if not self.drag:
            return
        geo = self.painter.geo
        if self.drag["kind"] == "chat":
            ix, iy, dw, dh = geo["img"]
            ch = geo["chats"][self.drag["part"]]
            slack = geo["pad"] * geo["d"]
            x = min(max(self.drag["at"][0] + e.x - self.drag["x"], ix - slack), ix + dw - ch["w"] + slack)
            y = min(max(self.drag["at"][1] + e.y - self.drag["y"], iy - slack), iy + dh - ch["h"] + slack)
            self.c.coords(f"shot-chat{self.drag['part']}", x, y)
        elif self.drag["kind"] == "crop":
            self.drag_crop(e, geo)
        elif self.drag["kind"] in ("ov", "ovpan"):
            ov = self.shot["edit"]["overlays"][self.drag["part"]]
            (out_w, out_h), d = geo["out"], geo["d"]
            if self.drag["kind"] == "ov":
                ov["x"] = round(min(max(self.drag["at"][0] + (e.x - self.drag["x"]) / d / out_w, 0.0), 1.0), 4)
                ov["y"] = round(min(max(self.drag["at"][1] + (e.y - self.drag["y"]) / d / out_h, 0.0), 1.0), 4)
            elif geo["overlays"][self.drag["part"]]:
                box = geo["overlays"][self.drag["part"]]
                l, t, r, b = self.drag["crop"]
                sx = min(max(-(e.x - self.drag["x"]) * (r - l) / box["w"], -l), 1 - r)
                sy = min(max(-(e.y - self.drag["y"]) * (b - t) / box["h"], -t), 1 - b)
                ov["crop"] = [round(l + sx, 4), round(t + sy, 4), round(r + sx, 4), round(b + sy, 4)]
                ov["cut"] = ov.get("cut", "free")
            if not self.pending_media:
                self.pending_media = True
                self.c.after(16, self.flush_media)
        else:
            bg = self.shot["bg"]
            H, W = bg.shape[:2]
            x0, y0, x1, y1 = geo["plan"]["rect"]
            k = (x1 - x0) / geo["img"][2]
            cx = self.drag["center"][0] - (e.x - self.drag["x"]) * k / W
            cy = self.drag["center"][1] - (e.y - self.drag["y"]) * k / H
            self.shot["edit"]["center"] = [cx, cy]
            if not self.pending_media:
                self.pending_media = True
                self.c.after(16, self.flush_media)

    def drag_crop(self, e, geo):
        drag = self.drag
        ov = self.shot["edit"]["overlays"][drag["part"]]
        (out_w, out_h), d = geo["out"], geo["d"]
        box, (SW, SH), (l, t, r, b) = drag["box"], drag["size"], drag["crop"]
        X, Y = (box["x"] - geo["img"][0]) / d, (box["y"] - geo["img"][1]) / d
        Wd, Hd = box["w"] / d, box["h"] / d
        k = Wd / max(1e-6, (r - l) * SW)
        L, T, R, B = X, Y, X + Wd, Y + Hd
        bounds = (X - l * SW * k, Y - t * SH * k, R + (1 - r) * SW * k, B + (1 - b) * SH * k)
        dx, dy, h = (e.x - drag["x"]) / d, (e.y - drag["y"]) / d, drag["handle"]
        least = 12 / d
        if "l" in h:
            L = min(max(L + dx, bounds[0]), R - least)
        if "r" in h:
            R = max(min(R + dx, bounds[2]), L + least)
        if "t" in h:
            T = min(max(T + dy, bounds[1]), B - least)
        if "b" in h:
            B = max(min(B + dy, bounds[3]), T + least)
        ratio = core.lock_ratio(ov.get("cut", "free"))
        if ratio and len(h) == 2:
            w, hh = R - L, B - T
            if abs(dx) >= abs(dy) * ratio:
                hh = w / ratio
            else:
                w = hh * ratio
            room_w = (R - bounds[0]) if "l" in h else (bounds[2] - L)
            room_h = (B - bounds[1]) if "t" in h else (bounds[3] - T)
            scale = min(1.0, room_w / w, room_h / hh)
            w, hh = w * scale, hh * scale
            L, R = (R - w, R) if "l" in h else (L, L + w)
            T, B = (B - hh, B) if "t" in h else (T, T + hh)
        span_x, span_y = SW * k, SH * k
        ov["crop"] = [round(min(max(l + (L - X) / span_x, 0.0), 1.0), 5), round(min(max(t + (T - Y) / span_y, 0.0), 1.0), 5),
                      round(min(max(r + (R - X - Wd) / span_x, 0.0), 1.0), 5),
                      round(min(max(b + (B - Y - Hd) / span_y, 0.0), 1.0), 5)]
        ov["w"] = round((R - L) / out_w, 5)
        ov["x"], ov["y"] = round((L + R) / 2 / out_w, 5), round((T + B) / 2 / out_h, 5)
        if not self.pending_media:
            self.pending_media = True
            self.c.after(16, self.flush_media)

    def flush_media(self):
        self.pending_media = False
        self.media_redraw()

    def release(self, e):
        drag, self.drag = self.drag, None
        self.c.config(cursor="")
        if not drag or self.shot is None:
            return
        geo = self.painter.geo
        edit = self.shot["edit"]
        if drag["kind"] == "chat":
            x, y = self.c.coords(f"shot-chat{drag['part']}")
            ix, iy = geo["img"][:2]
            d, pad = geo["d"], geo["pad"]
            out_w, out_h = geo["out"]
            left, top = (x - ix) / d, (y - iy) / d
            ch = geo["chats"][drag["part"]]
            margin = geo["plan"]["margin"]
            pos = [round((left + pad) / out_w, 4), round((top + pad) / out_h, 4)]
            for corner in core.CHAT_POSITIONS:
                cl, ct = chat.place(out_w, out_h, ch["lw"], ch["lh"], pad, corner, margin)
                if ((cl - left) ** 2 + (ct - top) ** 2) ** 0.5 < 0.06 * min(out_w, out_h):
                    pos = corner
                    break
            self.set_place(drag["part"], pos)
        elif drag["kind"] in ("ov", "ovpan", "crop"):
            self.redraw()
            self.schedule_save()
            return
        else:
            H, W = self.shot["bg"].shape[:2]
            x0, y0, x1, y1 = chat.frame_rect(W, H, core.ratio_of(edit["format"]), edit["zoom"], edit["center"])
            edit["center"] = [round((x0 + x1) / 2 / W, 4), round((y0 + y1) / 2 / H, 4)]
        self.media_redraw()
        if self.tool == "text":
            self.redraw()
        self.schedule_save()

    def hover(self, e):
        if self.drag or self.index == 0 or self.shot is None or self.tool == "lines":
            return
        tags = self.tags_here()
        if "shot-chat" in tags or (self.tool == "images" and "shot-ov" in tags):
            self.c.config(cursor="fleur")
        elif self.tool == "crop" and self.painter.geo and self.inside(e, self.painter.geo):
            self.c.config(cursor="fleur")
        elif not any(t.startswith(("rail", "nav", "older")) for t in tags):
            self.c.config(cursor="")

    def wheel(self, e):
        step = -1 if e.delta > 0 else 1
        if self.tool == "lines" and self.shot is not None:
            self.offset += step * px(72)
            self.draw_lines(self.area())
            return
        ov = next((int(t[7:]) for t in self.tags_here() if re.fullmatch(r"shot-ov\d+", t)), None)
        if self.tool == "images" and self.shot is not None and ov is not None:
            item = self.shot["edit"]["overlays"][ov]
            item["w"] = round(min(max(item["w"] * (1.08 if step < 0 else 1 / 1.08), 0.05), 2.0), 4)
            self.active_ov = ov
            self.media_redraw()
            self.schedule_save()
            return
        if self.tool == "crop" and self.shot is not None and e.state & 0x4:
            zoom = min(3.0, max(1.0, round(self.shot["edit"]["zoom"] - step * 0.1, 2)))
            self.change(zoom=zoom)
            return
        now = time.monotonic()
        if now - self.last_wheel > 0.25:
            self.last_wheel = now
            self.go(self.index + step)

    def schedule_save(self):
        if self.shot is None:
            return
        self.note = "сохраняю…"
        self.update_meta()
        if self.save_job:
            self.c.after_cancel(self.save_job)
        self.save_target = self.shot
        self.save_job = self.c.after(450, self.save_now)

    def flush_save(self):
        if self.save_job:
            self.c.after_cancel(self.save_job)
            self.save_now()

    def save_sync(self):
        if self.save_job:
            self.c.after_cancel(self.save_job)
            self.save_job = None
            try:
                core.save_shot(self.snapshot(self.save_target))
            except Exception:
                pass

    def snapshot(self, shot=None):
        shot = shot or self.shot
        return {**shot, "rows": [dict(r) for r in shot["rows"]], "edit": json.loads(json.dumps(shot["edit"]))}

    def save_now(self):
        self.save_job = None
        snap = self.snapshot(self.save_target)
        name = snap["name"]

        def work():
            try:
                core.save_shot(snap)
                self.app.inbox.put(("saved", name, None))
            except Exception as e:
                self.app.inbox.put(("saved", name, str(e)))

        threading.Thread(target=work, daemon=True).start()

    def saved(self, name, error):
        if name == self.name:
            self.note = f"не сохранилось: {error}" if error else "сохранено"
            self.update_meta()
            self.media = None

    def copy(self):
        name = self.name
        snap = self.snapshot() if self.shot is not None else None
        path = core.shot_image(self.app.cfg["out"], name)
        self.note = "копирую…"
        self.update_meta()

        def work():
            try:
                img = (core.render(snap["bg"], snap["rows"], snap["edit"], snap["out"] / "src")[0] if snap
                       else core.read_image(path))
                core.copy_image(img)
                self.app.inbox.put(("copied", name, None))
            except Exception as e:
                self.app.inbox.put(("copied", name, str(e)))

        threading.Thread(target=work, daemon=True).start()

    def copied(self, name, error):
        if name == self.name:
            self.note = f"не скопировалось: {error}" if error else "скопировано, вставляй через Ctrl+V"
            self.update_meta()

    def open_folder(self):
        out = self.app.cfg["out"]
        out.mkdir(parents=True, exist_ok=True)
        path = core.shot_image(out, self.name) if self.name else None
        if path and path.exists():
            subprocess.Popen(["explorer", "/select,", str(path)])
        else:
            os.startfile(out)

    def key(self, e):
        if e.keysym in ("Up", "Prior"):
            self.go(self.index - 1)
        elif e.keysym in ("Down", "Next"):
            self.go(self.index + 1)
        elif e.keysym == "Escape" and self.tool:
            self.toggle_tool(self.tool)
        elif e.keycode == 67 and e.state & 0x4 and self.index > 0:
            self.copy()
        elif e.keycode in (49, 50, 51, 52) and self.shot is not None and self.index > 0:
            self.toggle_tool(TOOLS[e.keycode - 49])


class Settings:
    def __init__(self, app, parent):
        self.app = app
        self.f = tk.Frame(parent, bg=VOID)
        self.list_w = px(640)
        self.label_w = px(220)
        holder = tk.Frame(self.f, bg=VOID, width=self.list_w + px(14), height=parent.winfo_screenheight())
        holder.pack(side="left", anchor="n", padx=(PAD + px(12), px(24)), pady=(px(8), 0))
        holder.pack_propagate(False)
        self.f.bind("<Configure>", lambda _: self.relayout())
        self.view = tk.Frame(holder, bg=VOID)
        self.view.pack(side="left", fill="both", expand=True)
        self.thumb = tk.Canvas(holder, bg=VOID, highlightthickness=0, bd=0, width=px(4))
        self.thumb.pack(side="right", fill="y")
        left = tk.Frame(self.view, bg=VOID)
        left.place(x=0, y=0, width=self.list_w)
        self.list, self.offset = left, 0
        left.bind("<Configure>", lambda _: self.relayout())
        self.view.bind("<Configure>", lambda _: self.relayout())
        right = tk.Frame(self.f, bg=VOID)
        right.pack(side="left", fill="both", expand=True, padx=(0, PAD), pady=(px(8), PAD))
        self.credits(right)
        self.example = tk.Canvas(right, bg=VOID, highlightthickness=0, bd=0)
        self.example.pack(fill="both", expand=True)
        self.example_job = None
        self.example.bind("<Configure>", lambda _: self.settle())
        self.painter = Painter(self.example)
        self.sample = None
        self.sample_loading = False
        self.sample_missing = False
        self.capturing = False
        self.chatlog_stop = None
        self.chatlog_folder = None
        self.build(left)
        self.bind_wheel(holder)

    def credits(self, parent):
        box = tk.Frame(parent, bg=VOID)
        box.pack(side="bottom", fill="x")
        tk.Frame(box, bg=HAIR, height=1).pack(fill="x", pady=(0, px(14)))
        line = tk.Frame(box, bg=VOID)
        line.pack(fill="x")
        text = tk.Frame(line, bg=VOID)
        text.pack(side="left", anchor="w")
        tk.Label(text, text=f"Snapline {core.VERSION}", bg=VOID, fg=WHITE, font=(FONT["semi"], 11), bd=0, padx=0,
                 anchor="w").pack(fill="x")
        who = tk.Frame(text, bg=VOID)
        who.pack(fill="x", pady=(px(2), 0))
        self.discord = self.link(who, "Дохлый", lambda: os.startfile(DISCORD))
        tk.Label(who, text=" для ", bg=VOID, fg=SUB, font=(FONT["ui"], 9), bd=0, padx=0, pady=0).pack(side="left")
        self.site = self.link(who, "ls-project.com", lambda: os.startfile(SITE))
        self.update_link = tk.Label(text, bg=VOID, fg=WHITE, font=(FONT["semi"], 9), bd=0, padx=0, cursor="hand2",
                                    anchor="w")
        try:
            with Image.open(core.RES_DIR / "assets" / "ls_project.png") as im:
                im = im.convert("RGBA")
                h = px(44)
                im = im.resize((round(im.width * h / im.height), h), Image.LANCZOS)
                ground = Image.new("RGBA", im.size, VOID)
                ground.alpha_composite(im)
                self.logo = ImageTk.PhotoImage(ground.convert("RGB"))
            tk.Label(line, image=self.logo, bg=VOID, bd=0).pack(side="right", anchor="e")
        except OSError:
            self.logo = None

    def show_update(self):
        version, url = self.app.update
        self.update_link.config(text=f"Вышла версия {version} — скачать")
        self.update_link.bind("<Button-1>", lambda _: os.startfile(url))
        self.update_link.pack(fill="x", pady=(px(6), 0))

    def link(self, parent, text, action):
        label = tk.Label(parent, text=text, bg=VOID, fg=WHITE, font=(FONT["ui"], 9), bd=0, padx=0, pady=0,
                         cursor="hand2")
        label.pack(side="left")
        label.bind("<Enter>", lambda _: label.config(font=(FONT["ui"], 9, "underline")))
        label.bind("<Leave>", lambda _: label.config(font=(FONT["ui"], 9)))
        label.bind("<Button-1>", lambda _: action())
        return label

    def bind_wheel(self, widget):
        widget.bind("<MouseWheel>", self.wheel, add="+")
        for child in widget.winfo_children():
            self.bind_wheel(child)

    def wheel(self, e):
        self.scroll_to(self.offset + (-px(72) if e.delta > 0 else px(72)))

    def seen(self):
        return max(1, self.f.winfo_height() - px(8) - PAD)

    def scroll_to(self, offset):
        spare = max(0, self.list.winfo_reqheight() - self.seen())
        offset = max(0, min(offset, spare))
        if offset != self.offset:
            self.offset = offset
            self.list.place_configure(y=-offset)
        self.draw_thumb()

    def relayout(self):
        self.scroll_to(self.offset)

    def draw_thumb(self):
        self.thumb.delete("all")
        full, seen = self.list.winfo_reqheight(), self.seen()
        if full <= seen:
            return
        top, bottom = self.offset / full, (self.offset + seen) / full
        self.thumb.create_line(px(2), top * seen + px(2), px(2), bottom * seen - px(2), fill=LINE, width=px(3),
                               capstyle="round")

    def row(self, parent, title, sub=None):
        line = tk.Frame(parent, bg=VOID)
        line.pack(fill="x")
        line.columnconfigure(0, minsize=self.label_w)
        text = tk.Frame(line, bg=VOID)
        text.grid(row=0, column=0, sticky="nw", pady=px(12))
        tk.Label(text, text=title, bg=VOID, fg=WHITE, font=(FONT["semi"], 11), anchor="w").pack(fill="x")
        subl = None
        if sub is not None:
            subl = tk.Label(text, text=sub, bg=VOID, fg=SUB, font=(FONT["ui"], 9), anchor="w", justify="left",
                            wraplength=self.label_w - px(20))
            subl.pack(fill="x", pady=(px(2), 0))
        control = tk.Frame(line, bg=VOID)
        control.grid(row=0, column=1, sticky="w", pady=px(10))
        tk.Frame(parent, bg=HAIR, height=1).pack(fill="x")
        return control, subl, text

    def choice(self, control, options, value, on_pick, **kw):
        choice = Choice(control, options, value, on_pick, wrap=self.list_w - self.label_w, **kw)
        choice.pack(anchor="w")
        return choice

    def section(self, parent, title, first=False):
        tk.Label(parent, text=title.upper(), bg=VOID, fg=SUB, font=(FONT["semi"], 9), anchor="w").pack(
            fill="x", pady=(px(4) if first else px(30), px(6)))
        tk.Frame(parent, bg=HAIR, height=1).pack(fill="x")

    def build(self, f):
        cfg, raw = self.app.cfg, self.app.raw
        self.section(f, "Съёмка", first=True)
        control, self.key_sub, text = self.row(f, "Клавиша съёмки", "Нажми и выбери новую")
        self.key_pill = Pill(control, cfg["key"], self.capture_key, kind="ghost", size=12, height=36, padx=18)
        self.key_pill.pack(anchor="w")
        control, self.mode_sub, text = self.row(f, "Режим", self.mode_text())
        self.choice(control, MODES, "yes" if cfg["auto"] else "no", self.set_mode)
        control, _, _ = self.row(f, "Звук", "Сигнал, когда СС готова")
        self.choice(control, SOUND, "yes" if cfg["sound"] else "no", lambda v: self.app.set("sound", v))
        self.section(f, "Кадр и файл")
        control, _, _ = self.row(f, "Кадр", "Свой — ширина и высота в пикселях")
        FramePick(control, cfg["format"], self.set_frame, self.frame_now, self.list_w - self.label_w).pack(anchor="w")
        control, _, _ = self.row(f, "Размер файла", "По короткой стороне, в пикселях")
        self.size_pick = SizePick(control, cfg["size"], lambda v: self.app.set("size", v), self.list_w - self.label_w)
        self.size_pick.pack(anchor="w")
        self.size_pick.show(cfg["format"])
        control, _, _ = self.row(f, "Файл", "JPG весит примерно втрое меньше PNG, чат остаётся чётким")
        self.choice(control, FILES, cfg["file"], lambda v: self.app.set("file", v))
        self.section(f, "Чат на СС")
        control, _, _ = self.row(f, "Текст чата")
        self.choice(control, SCALES, raw["text_scale"], lambda v: self.app.set("text_scale", v))
        control, _, _ = self.row(f, "Обводка")
        self.choice(control, OUTLINES, raw["outline"], lambda v: self.app.set("outline", v))
        control, _, _ = self.row(f, "Угол чата")
        self.choice(control, POSITIONS, cfg["chat_pos"], lambda v: self.app.set("chat_pos", v), cols=2)
        control, _, _ = self.row(f, "Ники", "В новых СС. В редакторе — инструмент «Строки»")
        self.choice(control, NICKS, "yes" if cfg["hide_names"] else "no", lambda v: self.app.set("hide_names", v))
        control, _, _ = self.row(f, "Строки в СС", "Остальные можно вернуть в редакторе")
        self.kind_pills = {}
        for i, (kind, label) in enumerate(KINDS.items()):
            if i % 3 == 0:
                line = tk.Frame(control, bg=VOID)
                line.pack(anchor="w", pady=(0, px(6)))
            pill = Pill(line, label, lambda k=kind: self.toggle_kind(k))
            pill.pack(side="left", padx=(0, px(6)))
            pill.set_kind("on" if kind in cfg["keep"] else "chip")
            self.kind_pills[kind] = pill
        self.section(f, "Файлы")
        control, _, _ = self.row(f, "Папка")
        self.out_label = tk.Label(control, text=str(cfg["out"]), bg=VOID, fg=SUB, font=(FONT["ui"], 9), anchor="w",
                                  justify="left", wraplength=self.list_w - self.label_w - px(10))
        self.out_label.pack(fill="x")
        buttons = tk.Frame(control, bg=VOID)
        buttons.pack(anchor="w", pady=(px(8), 0))
        Pill(buttons, "Изменить", self.pick_folder, kind="ghost").pack(side="left", padx=(0, px(6)))
        Pill(buttons, "Открыть", self.app.feed.open_folder, kind="ghost").pack(side="left")
        control, _, _ = self.row(f, "Исходники", "Кадры, из которых собрана СС. Без них СС не поправить в редакторе")
        self.src_label = tk.Label(control, bg=VOID, fg=SUB, font=(FONT["ui"], 9), anchor="w")
        self.src_label.pack(fill="x")
        Pill(control, "Очистить", self.clear_src, kind="ghost").pack(anchor="w", pady=(px(8), 0))
        self.update_src()
        self.section(f, "Чатлог")
        control, _, _ = self.row(f, "Запись чата", "Каждая строка чата с временем, по файлу на день")
        self.choice(control, SOUND, "yes" if cfg["chatlog"] else "no",
                    lambda v: (self.app.set("chatlog", v), self.toggle_chatlog(v)))
        self.chatlog_state = tk.Label(control, text="Выключен", bg=VOID, fg=SUB, font=(FONT["ui"], 9), anchor="w",
                                      justify="left", wraplength=self.list_w - self.label_w - px(10))
        self.chatlog_state.pack(fill="x", pady=(px(4), 0))
        Pill(control, "Открыть", self.open_chatlog, kind="ghost").pack(anchor="w", pady=(px(8), 0))

    def toggle_chatlog(self, value):
        if value == "yes" and self.chatlog_stop is None:
            self.chatlog_stop = threading.Event()
            self.chatlog_folder = self.app.cfg["out"] / "chatlog"
            threading.Thread(target=chatlog_worker, args=(self.chatlog_folder, self.chatlog_stop), daemon=True).start()
            self.chatlog_note("Запускаю…")
        elif value == "no" and self.chatlog_stop is not None:
            self.chatlog_stop.set()
            self.chatlog_stop = None
            self.chatlog_state.config(text="Выключен", fg=SUB)

    def chatlog_note(self, msg):
        if self.chatlog_stop is not None:
            self.chatlog_state.config(text=msg, fg=WHITE)

    def open_chatlog(self):
        folder = self.chatlog_folder or self.app.cfg["out"] / "chatlog"
        try:
            folder.mkdir(parents=True, exist_ok=True)
            os.startfile(folder)
        except OSError as e:
            self.chatlog_state.config(text=f"Папка не открылась: {e}", fg=ERR)

    def set_frame(self, value):
        self.app.set("format", value)
        self.size_pick.show(value)

    def frame_now(self):
        shot = self.sample or core.sample_shot(self.app.cfg)
        return core.plan(shot["bg"], core.new_edit(self.app.cfg, shot["rows"]))["size"]

    def update_src(self):
        try:
            size, count = core.src_size(self.app.cfg["out"])
        except OSError:
            size, count = 0, 0
        self.src_label.config(text=f"{count} СС · {megabytes(size)}" if size else "Пусто")
        return size, count

    def clear_src(self):
        size, count = self.update_src()
        if not size:
            return
        question = (f"Удалить исходники {count} СС ({megabytes(size)})?\n\n"
                    "Готовые СС останутся в папке, но поправить их в редакторе будет нельзя.")
        if not messagebox.askyesno("Snapline", question, parent=self.app.root):
            return
        core.clear_src(self.app.cfg["out"])
        feed = self.app.feed
        feed.cache.clear()
        if feed.index:
            feed.open_current()
        self.sample = None
        self.update_src()
        self.draw_example()

    def mode_text(self):
        cfg = self.app.cfg
        if cfg["auto"]:
            return f"Программа сама жмёт {cfg['hud_key']} и {cfg['dark_key']}."
        return f"Сам жмёшь {cfg['hud_key']} и {cfg['dark_key']} перед {cfg['key']}."

    def set_mode(self, value):
        self.app.set("auto", value)
        self.mode_sub.config(text=self.mode_text())

    def toggle_kind(self, kind):
        pill = self.kind_pills[kind]
        pill.set_kind("chip" if pill.kind == "on" else "on")
        self.app.set("keep", ", ".join(k for k, p in self.kind_pills.items() if p.kind == "on"))

    def capture_key(self):
        self.capturing = True
        self.key_pill.set_text("Нажми клавишу…")
        self.key_sub.config(text="Esc — отмена", fg=SUB)
        self.app.root.focus_set()

    def on_key(self, e):
        if not self.capturing:
            return False
        if e.keysym == "Escape":
            self.capturing = False
            self.key_pill.set_text(self.app.cfg["key"])
            self.key_sub.config(text="Нажми и выбери новую", fg=SUB)
            return True
        key = e.keysym.upper() if re.fullmatch(r"F\d{1,2}", e.keysym) else TK_KEYS.get(e.keysym)
        if key not in core.KEYS:
            self.key_sub.config(text="Не подойдёт: нужна F1–F24, Pause, Insert, Home, End, PgUp или PgDn", fg=ERR)
            return True
        self.capturing = False
        if self.app.set("hotkey", key):
            self.key_sub.config(text="Нажми и выбери новую", fg=SUB)
        else:
            self.key_sub.config(text=f"{key} занята игрой, выбери другую", fg=ERR)
        self.key_pill.set_text(self.app.cfg["key"])
        return True

    def pick_folder(self):
        path = filedialog.askdirectory(initialdir=self.app.cfg["out"], title="Куда сохранять СС")
        if path:
            self.app.set("output", path)
            self.out_label.config(text=str(self.app.cfg["out"]))
            problem = core.check_out(self.app.cfg)
            self.app.feed.message = ("fail", problem) if problem else None
            self.update_src()
            self.app.feed.refresh_names()
            self.app.feed.index = 0
            self.sample = None
            self.draw_example()

    def settle(self):
        if self.example_job:
            self.example.after_cancel(self.example_job)
        self.example_job = self.example.after(110, self.settled)

    def settled(self):
        self.example_job = None
        self.draw_example()

    def load_sample(self):
        feed = self.app.feed
        cached = feed.cache.get(feed.names[0]) if feed.names else None
        if cached:
            self.sample = {**cached, "rows": [dict(r) for r in cached["rows"]]}
            return True
        if not self.sample_loading and not self.sample_missing:
            self.sample_loading = True
            cfg = self.app.cfg

            def work():
                try:
                    shot = core.sample_shot(cfg)
                except (OSError, ValueError):
                    shot = None
                self.app.inbox.put(("sample_loaded", None, shot))

            threading.Thread(target=work, daemon=True).start()
        return False

    def sample_loaded(self, _, shot):
        self.sample_loading = False
        self.sample_missing = shot is None
        if self.sample is None:
            self.sample = shot
        self.draw_example()

    def draw_example(self):
        W, H = self.example.winfo_width(), self.example.winfo_height()
        if W < 50 or H < 50:
            return
        cfg = self.app.cfg
        self.example.delete("all")
        if self.sample is None and not self.load_sample():
            text = ("Пример не загрузился: нет ни своих СС, ни встроенного кадра." if self.sample_missing
                    else "Загружаю пример…")
            self.example.create_text(0, 0, anchor="nw", fill=SUB, font=(FONT["ui"], 10), text=text)
            return
        shot = self.sample
        for r in shot["rows"]:
            r["keep"] = r["kind"] in cfg["keep"]
            r["hide"] = []
        if cfg["hide_names"]:
            core.auto_hide(shot["rows"])
        shot["edit"] = core.new_edit(cfg, shot["rows"])
        out_w, out_h = core.plan(shot["bg"], shot["edit"])["size"]
        d = min(W / out_w, (H - px(72)) / out_h)
        geo = self.painter.draw(shot, (0, 0, round(out_w * d), round(out_h * d)))
        ix, iy, dw, dh = geo["img"]
        source = f"твоя СС от {when(shot['name'])}" if shot["name"] else "встроенный кадр"
        self.example.create_text(ix, iy + dh + px(14), anchor="nw", fill=SUB, font=(FONT["ui"], 10), width=dw,
                                 text=f"Так будет выглядеть новая СС: {out_w} × {out_h}. Пример — {source}. "
                                      f"Каждую готовую СС можно поправить в редакторе.")


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
        root.bind("<Configure>", self.on_configure, add="+")
        root.after(100, self.pump)

    def build_bar(self):
        bar = tk.Frame(self.root, bg=VOID, height=px(64))
        bar.pack(fill="x")
        bar.pack_propagate(False)
        self.bar = bar
        self.mark = Wordmark(bar, "Snapline")
        self.mark.place(x=PAD + px(12), rely=0.5, anchor="w")
        self.chrome = tk.Frame(bar, bg=VOID)
        self.chrome.place(relx=1.0, x=-px(10), rely=0.5, anchor="e")
        self.btn_max = None
        for key, command in (("min", self.minimize), ("max", self.toggle_max), ("close", lambda: self.close())):
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
                if kind == "update":
                    self.update = (name, value)
                    self.settings.show_update()
                    if feed.index == 0:
                        feed.redraw()
                    continue
                getattr(self.settings if kind == "sample_loaded" else feed, kind)(name, value)
        except queue.Empty:
            pass
        self.root.after(100, self.pump)


LRESULT = ctypes.c_ssize_t
WNDPROC = ctypes.WINFUNCTYPE(LRESULT, wintypes.HWND, wintypes.UINT, wintypes.WPARAM, wintypes.LPARAM)
WM_NCCALCSIZE, WM_NCACTIVATE, WM_NCLBUTTONDOWN = 0x0083, 0x0086, 0x00A1
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


def selftest():
    root = tk.Tk()
    root.attributes("-toolwindow", True)
    root.attributes("-alpha", 0.0)
    errors = []
    root.report_callback_exception = lambda *a: errors.append(a[1])
    app = App(root)
    app.hwnd = dark_title(root)
    app.frame = Frameless(app, app.hwnd)
    result = {}

    calls = []
    app.frame.native = calls.append
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
        W, H = root.winfo_width(), root.winfo_height()
        grips = dict(zip((name for name, _, _ in GRIPS), (grip for grip, _ in app.frame.grips)))
        order = root.winfo_children()
        on_top = min(order.index(g) for g in grips.values()) > max(order.index(app.bar), order.index(app.views))
        boxes = {n: (g.winfo_x(), g.winfo_y(), g.winfo_width(), g.winfo_height()) for n, g in grips.items()}
        placed = (boxes["left"][0] == 0 and boxes["right"][0] + boxes["right"][2] == W
                  and boxes["bottom"][1] + boxes["bottom"][3] == H and boxes["topleft"][:2] == (0, 0)
                  and all(b[2] > 0 and b[3] > 0 for b in boxes.values()))
        wiring = calls == [HT_CAPTION, "max", HT_CAPTION, 10, 11, 12, 15, 13, 14, 16, 17]
        result["ok"] = ((sample / "example_bg.webp").exists() and any(r["keep"] for r in rows) and FONT["icon"] is not None
                        and app.settings.logo is not None
                        and not errors and app.feed.c.winfo_width() > 100 and wiring and on_top and placed)
        result["detail"] = (calls, on_top, boxes, (W, H))
        root.destroy()

    root.after(800, clicks)
    root.mainloop()
    if not result.get("ok"):
        print(result.get("detail"), errors)
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
        root = tk.Tk()
        root.withdraw()
        messagebox.showinfo("Snapline", "Snapline уже запущена — её окно на панели задач.")
        root.destroy()
        return 1
    root = tk.Tk()
    app = App(root)
    root.report_callback_exception = app.crash
    app.hwnd = dark_title(root)
    app.frame = Frameless(app, app.hwnd)
    stop = threading.Event()
    threading.Thread(target=core.run, args=(lambda: app.cfg, stop, app.foreground), daemon=True).start()

    def close():
        stop.set()
        app.feed.save_sync()
        root.destroy()

    app.close = close
    root.protocol("WM_DELETE_WINDOW", close)
    root.mainloop()
    return 0


if __name__ == "__main__":
    sys.exit(main())
