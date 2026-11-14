import bisect
import ctypes
import io
import json
import os
import queue
import re
import subprocess
import sys
import tempfile
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
DIM = "#6b7180"
WHITE = "#f4f4f5"
SUB = "#a3a8b3"
ERR = "#ff7a70"

ICONS = {"file": "", "scene": "", "images": "", "cut": "", "lines": "", "crop": "", "text": "", "copy": "", "folder": "",
         "up": "", "down": "", "close": ""}
CHROME = {"min": "", "max": "", "restore": "", "close": ""}
CHROME_TEXT = {"min": "–", "max": "□", "restore": "❐", "close": "×"}
FORMATS = {"square": "Квадрат", "full": "Экран", "16:9": "16:9", "4:3": "4:3", "4:5": "4:5"}
SIZES = {"native": "Как снято", "hd": "720", "fhd": "1080", "qhd": "1440", "4k": "2160"}
FILES = {"jpg": "JPG", "png": "PNG"}
NICKS = {"no": "Показывать", "yes": "Прятать"}
CROPS = {"free": "Свободно", "1:1": "Квадрат", "4:3": "4:3", "3:4": "3:4", "16:9": "16:9", "9:16": "9:16"}
HANDLES = ("l", "r", "t", "b", "lt", "rt", "lb", "rb")
TOOLS = ("lines", "crop", "text", "images", "scene", "file")
PREVIEWS = ("scene", "file")
DONORS = ("carry", "photopick", "scenepick")
EDITS = ("lines", "carry", "logpick", "crop", "text", "images", "photopick")
FRAMED = ("crop", "text", "images")
SIDES = {"none": "Нет", "left": "Слева", "right": "Справа", "top": "Сверху", "bottom": "Снизу"}
FIELD_DEFAULT = {"size": 0.5, "fade": 0.3}
RAIL_HINTS = {"lines": "Какие строки чата попадут в СС · клавиша 1",
              "crop": "Что попадёт в кадр и какого он размера · клавиша 2",
              "text": "Размер текста, обводка и где стоит чат · клавиша 3",
              "images": "Второй ракурс или стикер поверх СС · клавиша 4",
              "scene": "Несколько СС одна под другой · клавиша 5",
              "file": "JPG или PNG, качество и вес файла · клавиша 6",
              "copy": "Скопировать СС в буфер (Ctrl+C), вставлять через Ctrl+V",
              "folder": "Показать файл в папке"}
EDGES = {"left": "у левого края", "right": "у правого края", "top": "у верхнего края", "bottom": "у нижнего края"}
SCALES = {"1": "×1", "1.25": "×1.25", "1.5": "×1.5", "1.75": "×1.75", "2": "×2"}
OUTLINES = {"0": "Нет", "1": "1 px", "2": "2 px", "3": "3 px"}
POSITIONS = {"top-left": "Сверху слева", "top-right": "Сверху справа",
             "bottom-left": "Снизу слева", "bottom-right": "Снизу справа"}
DISCORD = "https://discord.com/users/320909791826280452"
SITE = "https://ls-project.com/"
MODES = {"yes": "Одна кнопка", "no": "Две кнопки"}
SOURCES = {"screen": "С экрана", "log": "Из чатлога"}
VIEWS = {"one": "Эту СС", "all": "Всю сцену"}
LOG_SHOW = {"rp": "Отыгровка", "all": "Все строки"}
LOG_NAMES = 14
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


def place_name(pos):
    if isinstance(pos, str):
        return POSITIONS[core.corner_of(pos)].lower()
    return next((EDGES[v] for v in pos if isinstance(v, str) and v in EDGES), "своё место")


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
        d.rounded_rectangle((k, k, s - 1 - k, s - 1 - k), radius=5 * k, outline=DIM, width=round(1.5 * k))
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


def shade(frame, bands):
    arr = np.asarray(frame, np.float32)
    h = arr.shape[0]
    k = np.ones(h, np.float32)
    top, bottom = (min(h, round(b)) for b in bands)
    if top:
        k[:top] = 0.3 + 0.7 * core.ramp(top)
    if bottom:
        k[h - bottom:] = np.minimum(k[h - bottom:], 0.3 + 0.7 * core.ramp(bottom)[::-1])
    return Image.fromarray((arr * k[:, None, None]).round().astype(np.uint8))


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


class Corners(tk.Canvas):
    def __init__(self, parent, value, on_pick):
        self.w, self.h, self.value = px(48), px(32), value
        super().__init__(parent, width=self.w, height=self.h, bg=parent["bg"], highlightthickness=0, bd=0,
                         cursor="hand2")
        self.frame = ImageTk.PhotoImage(rounded(self.w, self.h, px(6), None, LINE, 1.2))
        self.create_image(0, 0, anchor="nw", image=self.frame)
        r, inset, self.dots = px(4), px(9), {}
        for corner in core.CHAT_POSITIONS:
            v, side = corner.split("-")
            x, y = inset if side == "left" else self.w - inset, inset if v == "top" else self.h - inset
            on = corner == value
            self.dots[corner] = self.create_oval(x - r, y - r, x + r, y + r, fill=WHITE if on else "",
                                                 outline=WHITE if on else DIM)
        self.bind("<Button-1>", lambda e: on_pick(self.spot(e)))
        self.bind("<Motion>", lambda e: self.lit(self.spot(e)))
        self.bind("<Leave>", lambda _: self.lit(None))

    def spot(self, e):
        return ("top" if e.y < self.h / 2 else "bottom") + "-" + ("left" if e.x < self.w / 2 else "right")

    def lit(self, near):
        for corner, dot in self.dots.items():
            if corner != self.value:
                self.itemconfig(dot, outline=WHITE if corner == near else DIM)


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


class Slider(tk.Canvas):
    def __init__(self, parent, lo, hi, value, on_move, on_done=None, width=None, step=1, fmt=None):
        self.w, self.h = width or px(260), px(30)
        super().__init__(parent, width=self.w, height=self.h, bg=parent["bg"], highlightthickness=0, bd=0,
                         cursor="hand2", takefocus=1)
        self.lo, self.hi, self.step = lo, hi, step
        self.fmt = fmt or (lambda v: f"{v:g}")
        self.on_move, self.on_done = on_move, on_done or on_move
        self.value = self.snap(value)
        self.focused = False
        self.bind("<ButtonPress-1>", self.press)
        self.bind("<B1-Motion>", self.press)
        self.bind("<ButtonRelease-1>", lambda _: self.on_done(self.value))
        self.bind("<MouseWheel>", lambda e: self.nudge(1 if e.delta > 0 else -1))
        self.bind("<Key-Left>", lambda _: self.nudge(-1))
        self.bind("<Key-Right>", lambda _: self.nudge(1))
        self.bind("<FocusIn>", lambda _: self.focus_to(True))
        self.bind("<FocusOut>", lambda _: self.focus_to(False))
        self.draw()

    def snap(self, v):
        v = round(round((v - self.lo) / self.step) * self.step + self.lo, 4)
        return min(max(v, self.lo), self.hi)

    def track(self):
        return px(9), self.w - px(64)

    def press(self, e):
        self.focus_set()
        a, b = self.track()
        self.move_to(self.lo + (e.x - a) / (b - a) * (self.hi - self.lo), self.on_move)

    def nudge(self, k):
        self.move_to(self.value + k * self.step, self.on_done)

    def move_to(self, v, notify):
        v = self.snap(v)
        if v != self.value:
            self.value = v
            self.draw()
            notify(v)

    def set(self, v):
        v = self.snap(v)
        if v != self.value:
            self.value = v
            self.draw()

    def focus_to(self, on):
        self.focused = on
        self.draw()

    def draw(self):
        a, b = self.track()
        y, r = self.h // 2, px(8)
        x = a + (self.value - self.lo) / (self.hi - self.lo) * (b - a)
        self.delete("all")
        self.create_line(a, y, b, y, fill=MIST, width=px(4), capstyle="round")
        self.create_line(a, y, x, y, fill=WHITE, width=px(4), capstyle="round")
        self.knob = ImageTk.PhotoImage(rounded(2 * r, 2 * r, r, WHITE, SUB if self.focused else VOID, 2.0))
        self.create_image(x, y, image=self.knob)
        self.create_text(self.w, y, anchor="e", text=self.fmt(self.value), fill=WHITE, font=(FONT["semi"], 10))


class Loupe:
    def __init__(self, canvas):
        self.c = canvas
        self.photo = None

    def show(self, x, y, rect, arr):
        ix, iy, dw, dh = rect
        H, W = arr.shape[:2]
        side = px(240)
        cx, cy = (x - ix) * W / dw, (y - iy) * H / dh
        x0 = int(min(max(cx - side / 2, 0), max(W - side, 0)))
        y0 = int(min(max(cy - side / 2, 0), max(H - side, 0)))
        crop = arr[y0:y0 + side, x0:x0 + side]
        h, w = crop.shape[:2]
        self.photo = ImageTk.PhotoImage(Image.fromarray(crop))
        gap = px(28)
        lx = x + gap if x + gap + w < self.c.winfo_width() else x - gap - w
        ly = min(max(y - h / 2, px(4)), self.c.winfo_height() - h - px(4))
        self.c.delete("loupe")
        self.c.create_rectangle(lx - 2, ly - 2, lx + w + 1, ly + h + 1, outline=WHITE, fill=VOID, tags=("loupe",))
        self.c.create_image(lx, ly, anchor="nw", image=self.photo, tags=("loupe",))
        self.c.create_rectangle(lx, ly, lx + px(34), ly + px(20), outline="", fill=VOID, tags=("loupe",))
        self.c.create_text(lx + px(17), ly + px(10), text="1:1", fill=WHITE, font=(FONT["semi"], 9), tags=("loupe",))

    def hide(self):
        self.c.delete("loupe")
        self.photo = None


class Painter:
    def __init__(self, canvas):
        self.c = canvas
        self.join_key = None
        self.join_img = None
        self.key = None
        self.layer = None
        self.photos = []
        self.geo = None
        self.scaled = None
        self.small = {}
        self.layers = []
        self.pieces = {}
        self.soft = {}

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

    def draw(self, shot, area, tag="shot", edit=None, laps=(0, 0)):
        bg, rows, edit = shot["bg"], shot["rows"], edit or shot["edit"]
        p = core.plan(bg, edit)
        out_w, out_h = p["size"]
        ax, ay, aw, ah = area
        d = min(aw / out_w, ah / out_h)
        dw, dh = max(1, round(out_w * d)), max(1, round(out_h * d))
        ix, iy = ax + (aw - dw) // 2, ay + (ah - dh) // 2
        if p["size"] == p["base"]:
            frame = self.frame(bg, p["rect"], (dw, dh))
        else:
            frame = self.joined(shot, p, d, (dw, dh))
        if any(laps):
            frame = shade(frame, [lap * d for lap in laps])
        it, ib = laps[0] // 2, laps[1] // 2
        inner = out_h - it - ib
        groups = core.parts(rows, edit)
        key = (id(shot), shot.get("name"), id(rows), len(rows), tuple(r["keep"] for r in rows),
               tuple((tuple(map(tuple, r.get("hide", []))), tuple(map(tuple, r.get("drop", [])))) for r in rows),
               tuple(core.cuts(rows, edit)), p["outline"], round(p["scale"], 4), inner, p["margin"])
        if key != self.key:
            self.layers = [chat.chat_layer(part, p["outline"], p["scale"], inner - 2 * p["margin"])
                           for part, _ in groups]
            self.key = key
            self.small = {}
        self.c.delete(tag)
        self.photos = [ImageTk.PhotoImage(frame)]
        self.c.create_image(ix, iy, anchor="nw", image=self.photos[0], tags=(tag,))
        pad = p["outline"] + 2
        geo = {"img": (ix, iy, dw, dh), "d": d, "out": (out_w, out_h), "plan": p, "pad": pad, "chats": [],
               "painted": sum(n for _, n, _ in self.layers), "overlays": [], "join": None, "inset": (it, ib)}
        if p["ext_box"]:
            l, t, r, b = p["ext_box"]
            geo["join"] = (ix + l * d, iy + t * d, ix + r * d, iy + b * d)
        self.draw_overlays(shot, geo, tag)
        spots = core.chat_spots((out_w, inner), [layer for layer, _, _ in self.layers], [pos for _, pos in groups],
                                pad, p["margin"])
        for k, ((layer, _, _), spot) in enumerate(zip(self.layers, spots)):
            if layer is None:
                geo["chats"].append(None)
                continue
            lh, lw = layer.shape[:2]
            left, top = spot[0], spot[1] + it
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

    def joined(self, shot, p, d, size):
        join = shot["edit"]["join"]
        key = (id(shot["bg"]), p["rect"], size, json.dumps(join, sort_keys=True))
        if key != self.join_key:
            bw, bh = p["base"]
            base = self.frame(shot["bg"], p["rect"], (max(1, round(bw * d)), max(1, round(bh * d))))
            img = core.join_canvas(base, join)
            self.join_key, self.join_img = key, img if img.size == size else img.resize(size, Image.BILINEAR)
        return self.join_img

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
            edges = core.soft_edges((x, y, w, h), (out_w, out_h))
            base = (ov["file"], tuple(ov["crop"]), size)
            key = base + (ov.get("soft", 0.0), ov.get("alpha", 1.0), edges)
            if base not in self.pieces:
                self.pieces[base] = core.overlay_piece(source, ov, size)
            if key not in self.soft:
                if len(self.soft) > 24:
                    self.soft.clear()
                self.soft[key] = core.soften(self.pieces[base], ov, edges)
            l, t = max(ix, dx), max(iy, dy)
            r, b = min(ix + dw, dx + size[0]), min(iy + dh, dy + size[1])
            if r <= l or b <= t:
                geo["overlays"].append(None)
                continue
            photo = ImageTk.PhotoImage(self.soft[key].crop((l - dx, t - dy, r - dx, b - dy)))
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
        self.saves = {}
        self.whole = False
        self.save_queue = queue.Queue()
        threading.Thread(target=self.save_loop, daemon=True).start()
        self.part = None
        self.items = []
        self.added = set()
        self.popup = None
        self.hint_text = None
        self.hint_photo = None
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
        self.thumbs = {}
        self.sliders = {}
        self.sheet_tool = None
        self.sheet_offset = 0
        self.preview = None
        self.preview_info = None
        self.preview_rev = 0
        self.preview_job = None
        self.preview_photo = None
        self.preview_rect = None
        self.preview_view = None
        self.preview_img = None
        self.view_box = None
        self.view = {"zoom": 1.0, "cx": 0.5, "cy": 0.5}
        self.seam = "all"
        self.layout = None
        self.logview = None
        self.log_font = None
        self.loupe = Loupe(self.c)
        self.c.bind("<Leave>", lambda _: (self.loupe.hide(), self.hint(None)))
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
        self.preview = self.preview_info = self.layout = self.part = None
        self.view, self.seam = {"zoom": 1.0, "cx": 0.5, "cy": 0.5}, "all"
        self.loupe.hide()
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
        if self.cache.get(name):
            return
        self.cache[name] = shot or False
        keep = set(self.scene_names()) | {self.name}
        while len(self.cache) > 6 + len(keep):
            old = next((n for n in self.cache if n not in keep), None)
            if old is None:
                break
            self.cache.pop(old)
        if name == self.name:
            self.shot = shot
            self.redraw()
            self.fetch_next()
        elif self.shot is not None and self.drag is None and name in self.scene_names() and self.tool in EDITS:
            if self.tool == "lines" or name == self.part:
                self.redraw()

    def new_shot(self, name):
        if self.saves.pop(name, None) and not self.saves and self.save_job:
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
        self.preview_rect = self.view_box = self.popup = self.hint_text = None
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
        log = cfg["source"] == "log"
        if body is None:
            if log:
                first = (f"Нажми {key} в игре и программа сама спрячет интерфейс" if cfg["auto"]
                         else f"В игре нажми {hud}, затем {key}")
                body = (f"{first}: снимется только сцена, без затемнения. Строки потом отметишь в «Строках» "
                        f"из чатлога. Готовая СС появится здесь или в папке скриншотов.")
            elif cfg["auto"]:
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
        tip = ("Памятка: в чатлоге видны строки за час до и после СС, так что отыграть сцену можно и после "
               "снимка." if log else
               f"Памятка: если диалог длинный, то нажми {dark} и вновь {key}. "
               f"Тогда в одной СС будет несколько чатбоксов.")
        y = self.text(x, y, tip, (FONT["ui"], 10), SUB, width)
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
        else:
            self.draw_media(area)
        if self.tool:
            self.build_sheet(H)
        else:
            self.caption(H, name, view_only)
        tools = [] if self.shot is None else [
            ("lines", "Строки", lambda: self.toggle_tool("lines"), self.tool in ("lines", "carry", "logpick")),
            ("crop", "Кадр", lambda: self.toggle_tool("crop"), self.tool == "crop"),
            ("text", "Текст", lambda: self.toggle_tool("text"), self.tool == "text"),
            ("images", "Картинки", lambda: self.toggle_tool("images"), self.tool in ("images", "photopick")),
            ("scene", "Сцена", lambda: self.toggle_tool("scene"), self.tool in ("scene", "scenepick")),
            ("file", "Файл", lambda: self.toggle_tool("file"), self.tool == "file"),
        ]
        tools.append(None)
        if self.shot is not None or view_only:
            tools.append(("copy", "Копировать", self.copy, False))
        tools.append(("folder", "В папке", self.open_folder, False))
        self.rail(W, H, tools)

    def draw_media(self, area):
        self.preview_rect = self.view_box = None
        if self.tool == "lines":
            self.draw_lines(area)
        elif self.tool == "logpick":
            self.draw_log(area)
        elif self.tool in DONORS:
            self.draw_donors(area)
        elif (self.tool is None or self.previewing()) and self.scene_names():
            self.draw_scene(area)
        elif self.target is None:
            ax, ay, aw, ah = area
            self.painter.geo = None
            text = "Исходники этой СС не найдены" if self.cache.get(self.part) is False else "Загружаю СС…"
            self.c.create_text(ax + aw // 2, ay + ah // 2, text=text, fill=SUB, font=(FONT["ui"], 12), tags=("shot",))
        else:
            edit, laps = self.look(self.target)
            self.decorate(self.painter.draw(self.target, area, edit=edit, laps=laps))

    def scene_names(self):
        scene = self.shot["edit"].get("scene") if self.shot else None
        return list(scene["shots"]) if scene and self.shot["name"] in scene["shots"] else []

    @property
    def target(self):
        if self.shot is None or self.tool not in EDITS or self.part in (None, self.name):
            return self.shot
        if self.part not in self.scene_names():
            return self.shot
        return self.cache.get(self.part) or None

    def members(self):
        return [(n, self.shot if n == self.name else self.cache.get(n) or None) for n in self.scene_names()]

    def previewing(self):
        return self.tool in PREVIEWS or self.tool == "text" and self.whole and bool(self.scene_names())

    def member(self, name):
        if name == self.name:
            return self.shot
        shot = self.cache.get(name)
        if not shot:
            try:
                shot = core.load_shot(self.shot["out"], name, self.app.cfg)
            except (OSError, ValueError):
                shot = None
            if shot:
                self.cache[name] = shot
        return shot or None

    def fetch_scene(self):
        for name in self.scene_names():
            self.fetch(name)

    def seams(self):
        given = self.shot["edit"]["scene"].get("seams") or []
        return [dict(core.SEAM, **(given[k] if k < len(given) else {})) for k in range(len(self.scene_names()) - 1)]

    def scene_plan(self):
        head = self.shot["edit"]
        width = core.plan(self.shot["bg"], core.framed(head, head))["size"][0]
        hs = [core.plan(s["bg"], core.framed(s["edit"], head), width)["size"][1] if s else None
              for _, s in self.members()]
        mine = hs[self.scene_names().index(self.name)]
        hs = [h or mine for h in hs]
        return width, hs, core.laps_of(hs, self.seams())

    def scene_size(self):
        width, hs, laps = self.scene_plan()
        return width, sum(hs) - sum(laps)

    def look(self, shot):
        names = self.scene_names()
        if not names or shot.get("name") not in names:
            return shot["edit"], (0, 0)
        edit = core.framed(shot["edit"], self.shot["edit"])
        width, _, laps = self.scene_plan()
        k = names.index(shot["name"])
        f = core.plan(shot["bg"], edit)["size"][0] / width
        return edit, (round(laps[k - 1] * f) if k else 0, round(laps[k] * f) if k < len(laps) else 0)

    def current(self):
        names = self.scene_names()
        return self.part if self.part in names else self.name

    def pick_part(self, name):
        self.part = None if name == self.name else name
        self.fetch(name)
        self.active_ov = 0
        self.redraw()

    def frame_strip(self, body):
        names, current = self.scene_names(), self.current()
        self.field(body, "СС в сцене", 0)
        box = tk.Frame(body, bg=VOID)
        box.pack(anchor="w", pady=(0, px(10)))
        per = max(1, self.sheet_w // (px(54) + px(12)))
        for k, name in enumerate(names):
            on = name == current
            cell = tk.Frame(box, bg=VOID, cursor="hand2")
            cell.grid(row=k // per, column=k % per, padx=(0, px(8)), pady=(0, px(6)), sticky="nw")
            photo = self.frame_thumb(name)
            pic = tk.Label(cell, image=photo, bg=VOID, bd=0, highlightthickness=px(2),
                           highlightbackground=WHITE if on else VOID) if photo else None
            if pic:
                pic.pack(anchor="w")
            text = f"{k + 1}" + (" · эта" if name == self.name else "")
            tag = tk.Label(cell, text=text, bg=VOID, fg=WHITE if on else SUB, font=(FONT["ui"], 9), anchor="w")
            tag.pack(anchor="w")
            for w in (cell, pic, tag):
                if w:
                    w.bind("<Button-1>", lambda _, n=name: self.pick_part(n))

    def draw_scene(self, area):
        ax, ay, aw, ah = area
        if self.tool is None:
            self.draw_saved(area, self.name)
            return
        if self.preview is None:
            self.c.create_text(ax + aw // 2, ay + ah // 2, text="Собираю сцену…", fill=SUB, font=(FONT["ui"], 12),
                               tags=("shot",))
            return
        arr, view = self.preview, self.view
        H, W = arr.shape[:2]
        fit = min(aw / W, ah / H)
        view["zoom"] = min(max(view["zoom"], 1.0), max(1.0, 4 / fit))
        d = fit * view["zoom"]
        vw, vh = max(1, min(aw, round(W * d))), max(1, min(ah, round(H * d)))
        sw, sh = min(W, vw / d), min(H, vh / d)
        x0 = max(0.0, min(view["cx"] * W - sw / 2, W - sw))
        y0 = max(0.0, min(view["cy"] * H - sh / 2, H - sh))
        view["cx"], view["cy"] = (x0 + sw / 2) / W, (y0 + sh / 2) / H
        rect = (ax + (aw - vw) // 2, ay + (ah - vh) // 2, vw, vh)
        self.view_box, self.preview_rect = (x0, y0, d), rect
        self.preview_view = arr[int(y0):int(y0 + sh), int(x0):int(x0 + sw)]
        key = (id(arr), rect, round(x0, 2), round(y0, 2))
        if self.preview_photo is None or self.preview_photo[0] != key:
            if self.preview_img is None or self.preview_img[0] is not arr:
                self.preview_img = (arr, Image.fromarray(arr))
            img = self.preview_img[1].resize((vw, vh), Image.NEAREST if d >= 2 else Image.BILINEAR,
                                             box=(x0, y0, x0 + sw, y0 + sh), reducing_gap=None if d >= 1 else 2.0)
            self.preview_photo = (key, ImageTk.PhotoImage(img))
        self.c.create_image(rect[0], rect[1], anchor="nw", image=self.preview_photo[1], tags=("shot",))
        if self.seam == "all" or not self.layout or int(self.seam) >= len(self.layout["laps"]):
            return
        k = int(self.seam)
        top = self.layout["tops"][k + 1]
        edges = sorted({top, top + self.layout["laps"][k]})
        ix, iy = rect[:2]
        if iy + (edges[-1] - y0) * d < iy or iy + (edges[0] - y0) * d > iy + vh:
            return
        for y in edges:
            sy = iy + (y - y0) * d
            if iy <= sy <= iy + vh:
                self.c.create_line(ix, sy + 1, ix + vw, sy + 1, fill=VOID, width=2, tags=("shot",))
                self.c.create_line(ix, sy, ix + vw, sy, fill=WHITE, width=2, dash=(6, 4), tags=("shot",))
        label = f"переход {k + 1}–{k + 2}"
        ly = min(max(iy + (edges[0] - y0) * d - px(24), iy + px(4)), iy + vh - px(24))
        tw = tkfont.Font(family=FONT["semi"], size=9).measure(label) + px(16)
        self.c.create_rectangle(ix + px(6), ly, ix + px(6) + tw, ly + px(20), fill=VOID, outline="", tags=("shot",))
        self.c.create_text(ix + px(6) + tw / 2, ly + px(10), text=label, fill=WHITE, font=(FONT["semi"], 9),
                           tags=("shot",))

    def seam_at(self, y):
        if not self.view_box or not self.layout:
            return None
        x0, y0, d = self.view_box
        sy = y0 + (y - self.preview_rect[1]) / d
        near = px(8) / d
        for k, lap in enumerate(self.layout["laps"]):
            top = self.layout["tops"][k + 1]
            if top - near <= sy <= top + lap + near:
                return k
        return None

    def zoom_view(self, zoom, at=None):
        if self.preview is None or not self.view_box:
            return
        ax, ay, aw, ah = self.area()
        x0, y0, d = self.view_box
        H, W = self.preview.shape[:2]
        fit = min(aw / W, ah / H)
        zoom = min(max(zoom, 1.0), max(1.0, 4 / fit))
        if at is not None:
            rx, ry = self.preview_rect[:2]
            sx, sy = x0 + (at[0] - rx) / d, y0 + (at[1] - ry) / d
            nd = fit * zoom
            self.view["cx"] = (sx - (at[0] - ax - aw / 2) / nd) / W
            self.view["cy"] = (sy - (at[1] - ay - ah / 2) / nd) / H
        self.view["zoom"] = zoom
        self.media_redraw()

    def view_fit(self, kind):
        if self.preview is None:
            return
        ax, ay, aw, ah = self.area()
        H, W = self.preview.shape[:2]
        fit = min(aw / W, ah / H)
        self.zoom_view({"all": 1.0, "width": aw / W / fit, "real": 1 / fit}[kind])

    def focus_frame(self, k):
        if self.preview is None or not self.layout or k >= len(self.layout["tops"]):
            return
        ax, ay, aw, ah = self.area()
        H, W = self.preview.shape[:2]
        top, h = self.layout["tops"][k], self.layout["heights"][k]
        self.view.update(cx=0.5, cy=(top + h / 2) / H)
        self.zoom_view(min(aw / W, ah / h) / min(aw / W, ah / H))

    def decorate(self, geo):
        ix, iy, dw, dh = geo["img"]
        if self.tool == "crop":
            self.c.create_rectangle(ix - 1, iy - 1, ix + dw, iy + dh, outline=WHITE, width=1, tags=("shot",))
            if geo["join"]:
                l, t, r, b = geo["join"]
                self.c.create_rectangle(l, t, r - 1, b - 1, outline=WHITE, width=1, dash=(4, 3), tags=("shot",))
        elif self.tool == "file":
            self.draw_preview(geo["img"])
        self.mark_overlay(geo)

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
        shot, scene = self.target, self.scene_names()
        if not scene:
            w, h = core.plan(self.shot["bg"], self.shot["edit"])["size"]
            parts = [f"{w} × {h}"]
        elif self.tool in FRAMED and shot is not None and not self.previewing():
            w, h = core.plan(shot["bg"], self.look(shot)[0])["size"]
            parts = [f"СС {scene.index(shot['name']) + 1} из {len(scene)}", f"кадр {w} × {h}",
                     "сцена {} × {}".format(*self.scene_size())]
        else:
            parts = [f"сцена из {len(scene)} СС"]
            if self.preview is not None and self.previewing():
                parts.append(f"{self.preview.shape[1]} × {self.preview.shape[0]}")
            if self.view_box:
                parts.append(f"масштаб {round(self.view_box[2] * 100)}%")
        geo = self.painter.geo
        kept = sum(r["keep"] for r in shot["rows"]) if shot else 0
        drawn = self.tool in FRAMED or not scene and self.tool in (None, "file")
        if geo and shot and drawn and geo["painted"] < kept:
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
        elif self.empty_log():
            hint = "Чат пока пустой: открой «Строки» клавишей 1 и отметь нужные строки чатлога."
        elif self.scene_names():
            hint = "Это сцена из нескольких СС. Инструменты — справа или клавишами 1–6, колесо листает СС."
        else:
            hint = "Инструменты — справа или клавишами 1–6. Колесо листает СС."
        self.text(x, y, hint, (FONT["ui"], 10), SUB, width)
        self.lift_block("cap", H - PAD - px(12))

    def rail(self, W, H, items):
        cx = W - RAIL_W / 2
        top, bottom = PAD, H - PAD - (px(86) if self.names else 0)
        slots = sum(0.5 if item is None else 1 for item in items)
        step = min(px(76), (bottom - top) / max(1, slots))
        ring, drop = min(px(46), round(step * 0.6)), min(px(34), round(step * 0.5))
        y = (top + bottom) / 2 - step * (slots - 1) / 2 - px(9)
        for item in items:
            if item is None:
                line = y - step + (drop + px(6) + step * 1.5 - ring / 2) / 2
                self.c.create_line(cx - px(16), line, cx + px(16), line, fill=LINE, tags=("rail",))
                y += step * 0.5
                continue
            key, label, command, active = item
            tag, idle = f"rail-{key}", WHITE if key == "copy" else SUB
            if active or key == "copy":
                image = rounded(ring, ring, ring / 2, WHITE) if active else rounded(ring, ring, ring / 2, None, WHITE,
                                                                                    1.4 * K)
                self.photos.append(ImageTk.PhotoImage(image))
                self.c.create_image(cx, y, image=self.photos[-1], tags=(tag, "rail"))
            if FONT["icon"]:
                self.c.create_text(cx, y, text=ICONS[key], font=(FONT["icon"], 18), fill=VOID if active else WHITE,
                                   tags=(tag, "rail", tag + "-ink" if not active else tag + "-on"))
            self.c.create_text(cx, y + drop, text=label, font=(FONT["ui"], 9), fill=WHITE if active else idle,
                               tags=(tag, "rail", tag + "-label"))
            self.c.create_rectangle(cx - px(46), y - step * 0.4, cx + px(46), y + step * 0.6, outline="", fill="",
                                    tags=(tag, "rail"))
            self.c.tag_bind(tag, "<Button-1>", lambda _, f=command: f())
            if not active:
                self.c.tag_bind(tag, "<Enter>", lambda _, t=tag: (self.c.itemconfig(t + "-label", fill=WHITE),
                                                                  self.c.config(cursor="hand2")))
                self.c.tag_bind(tag, "<Leave>", lambda _, t=tag, c=idle: (self.c.itemconfig(t + "-label", fill=c),
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
        if tool == "scene" and self.tool != "scene" and self.shot is not None and not self.scene_names():
            tool = "scenepick"
        if tool == "lines" and self.tool not in ("lines", "logpick") and self.empty_log():
            tool = "logpick"
        was = self.previewing()
        old, self.tool = self.tool, None if self.tool == tool else tool
        self.offset = 0
        self.loupe.hide()
        if old == "scenepick" and self.added and self.scene_names():
            self.drop_repeats()
        self.added = set()
        if self.tool in EDITS:
            self.fetch_scene()
        if self.previewing():
            if not was:
                self.preview = self.preview_info = None
            self.want_preview()
        if self.tool == "logpick":
            self.open_log()
        self.redraw()

    def empty_log(self):
        shot = self.shot
        return (shot is not None and not shot["rows"] and not self.scene_names()
                and core.log_path(shot["out"], shot["name"]).exists())

    def build_sheet(self, H):
        sheet = tk.Frame(self.c, bg=VOID)
        self.sheet_w = SIDE_W - 2 * PAD - px(12)
        sheet.place(x=PAD + px(12), y=PAD, width=self.sheet_w + px(12), height=H - 2 * PAD)
        self.sheet = sheet
        head = tk.Frame(sheet, bg=VOID)
        head.pack(fill="x", padx=(0, px(12)))
        title = {"lines": "Строки чата", "crop": "Кадр", "text": "Текст", "images": "Картинки", "file": "Файл",
                 "carry": "Чат из другой СС", "logpick": "Чатлог", "photopick": "Фото из другой СС", "scene": "Сцена",
                 "scenepick": "СС для сцены"}[self.tool]
        tk.Label(head, text=title, bg=VOID, fg=WHITE, font=(FONT["display"], 20)).pack(side="left")
        close = tk.Label(head, text=ICONS["close"] if FONT["icon"] else "Закрыть", bg=VOID, fg=SUB, cursor="hand2",
                         font=(FONT["icon"], 12) if FONT["icon"] else (FONT["ui"], 10))
        close.pack(side="right", pady=(px(6), 0))
        close.bind("<Button-1>", lambda _: self.toggle_tool(self.tool))
        close.bind("<Enter>", lambda _: close.config(fg=WHITE))
        close.bind("<Leave>", lambda _: close.config(fg=SUB))
        scope = self.scope()
        if scope:
            tk.Label(sheet, text=scope, bg=VOID, fg=SUB, font=(FONT["ui"], 10), anchor="w").pack(fill="x")
        holder = tk.Frame(sheet, bg=VOID)
        holder.pack(fill="both", expand=True, pady=(px(14) if scope else px(18), px(8)))
        body = tk.Frame(holder, bg=VOID)
        body.place(x=0, y=0, width=self.sheet_w)
        self.sheet_holder, self.sheet_body = holder, body
        self.sheet_thumb = tk.Frame(holder, bg=LINE)
        if self.tool != self.sheet_tool:
            self.sheet_tool, self.sheet_offset = self.tool, 0
        self.sliders = {}
        if self.tool in FRAMED and self.scene_names():
            self.frame_strip(body)
        if self.target is None:
            self.label(body, "Загружаю эту СС…" if self.cache.get(self.part) is None else
                       "Исходники этой СС не найдены, её не поправить.")
        else:
            getattr(self, "sheet_" + self.tool)(body)
        self.sheet_meta = tk.Label(sheet, text=self.meta(), bg=VOID, fg=SUB, font=(FONT["ui"], 10), anchor="w",
                                   justify="left", wraplength=self.sheet_w)
        self.sheet_meta.pack(fill="x", padx=(0, px(12)))
        self.bind_sheet_wheel(holder)
        holder.bind("<Configure>", lambda _: self.scroll_sheet(0))
        body.bind("<Configure>", lambda _: self.scroll_sheet(0))

    def scope(self):
        names = self.scene_names()
        if self.tool == "scenepick" or not names and self.tool in ("scene", "carry", "logpick", "photopick"):
            return None
        if not names:
            return "только эта СС"
        if self.previewing():
            return "вся сцена"
        if self.tool == "lines":
            return "все СС сцены"
        return f"СС {names.index(self.current()) + 1} из {len(names)} сцены"

    def hint(self, text):
        if text == self.hint_text:
            return
        self.hint_text = text
        self.c.delete("hint")
        if not text or self.index == 0:
            return
        ax, ay, aw, ah = self.area()
        w = min(aw - px(20), tkfont.Font(family=FONT["ui"], size=10).measure(text) + px(32))
        h = px(32)
        x, y = ax + (aw - w) // 2, ay + ah - h - px(12)
        self.hint_photo = ImageTk.PhotoImage(rounded(w, h, h // 2, (10, 10, 10, 228), (69, 75, 87, 255)))
        self.c.create_image(x, y, anchor="nw", image=self.hint_photo, state="disabled", tags=("hint",))
        self.c.create_text(x + w / 2, y + h / 2, text=text, fill=WHITE, font=(FONT["ui"], 10), state="disabled",
                           tags=("hint",))

    def bind_sheet_wheel(self, widget):
        if not isinstance(widget, Slider):
            widget.bind("<MouseWheel>", lambda e: self.scroll_sheet(-px(60) if e.delta > 0 else px(60)), add="+")
        for child in widget.winfo_children():
            self.bind_sheet_wheel(child)

    def scroll_sheet(self, delta):
        holder, body = self.sheet_holder, self.sheet_body
        if not holder.winfo_exists():
            return
        seen, full = holder.winfo_height(), body.winfo_reqheight()
        self.sheet_offset = max(0, min(self.sheet_offset + delta, full - seen))
        body.place_configure(y=-self.sheet_offset)
        if full > seen > 1:
            h = max(px(24), seen * seen / full)
            self.sheet_thumb.place(x=self.sheet_w + px(6), y=(seen - h) * self.sheet_offset / (full - seen),
                                   width=px(3), height=h)
        else:
            self.sheet_thumb.place_forget()

    def label(self, parent, text, top=0):
        tk.Label(parent, text=text, bg=VOID, fg=SUB, font=(FONT["ui"], 10), anchor="w", justify="left",
                 wraplength=self.sheet_w).pack(fill="x", pady=(px(top), px(8)))

    def field(self, parent, text, top=14):
        tk.Label(parent, text=text, bg=VOID, fg=WHITE, font=(FONT["semi"], 10), anchor="w").pack(
            fill="x", pady=(px(top), px(6)))

    def choice(self, body, options, value, on_pick, **kw):
        Choice(body, options, value, on_pick, wrap=self.sheet_w, **kw).pack(anchor="w")

    def slider(self, body, lo, hi, value, on_change, **kw):
        bar = Slider(body, lo, hi, value, on_change, width=self.sheet_w, **kw)
        bar.pack(anchor="w")
        return bar

    def buttons(self, body, items, top=0):
        line = tk.Frame(body, bg=VOID)
        line.pack(anchor="w", pady=(px(top), 0))
        for text, command in items:
            Pill(line, text, command, kind="ghost").pack(side="left", padx=(0, px(6)))

    def sheet_lines(self, body):
        names, shot = self.scene_names(), self.target
        log = core.log_path(shot["out"], shot["name"]).exists()
        self.count = tk.Label(body, text=self.count_text(), bg=VOID, fg=WHITE, font=(FONT["semi"], 12), anchor="w")
        self.count.pack(fill="x", pady=(0, px(10)))
        self.buttons(body, (("Как после съёмки", self.reset_lines),) +
                     ((("Чат из другой СС", lambda: self.toggle_tool("carry")),) if not log else ()))
        source = (("С экрана", self.from_screen),) if log and core.screen_chats(shot["out"], shot["name"]) else ()
        self.buttons(body, (("Из чатлога", lambda: self.toggle_tool("logpick")),) + source +
                     ((("Убрать повторы", self.drop_repeats),) if names else ()), 6)
        self.label(body, ("Чат этой СС собран из чатлога. " if log else "") +
                   "Галочка — строка в СС, мышью можно провести по нескольким. Клик по слову — закрыть его "
                   "плашкой или удалить. Ножницы делят чат на части." +
                   (" Здесь строки всех СС сцены, повторы из СС выше убираются сами." if names else ""), 16)

    def sheet_logpick(self, body):
        shot = self.target
        self.log_count = tk.Label(body, text=self.log_count_text(), bg=VOID, fg=WHITE, font=(FONT["semi"], 12),
                                  anchor="w")
        self.log_count.pack(fill="x", pady=(0, px(10)))
        line = tk.Frame(body, bg=VOID)
        line.pack(anchor="w")
        Pill(line, "На СС", self.apply_log, kind="primary").pack(side="left", padx=(0, px(6)))
        Pill(line, "Назад к строкам", lambda: self.toggle_tool("lines"), kind="ghost").pack(side="left")
        v = self.logview
        if v and v["lines"]:
            self.field(body, "Показывать")
            self.choice(body, LOG_SHOW, "all" if v["all"] else "rp", self.log_show)
            names = self.log_names()
            if names:
                self.field(body, "Чьи строки")
                self.label(body, "Нажми на участников своей сцены — останется только их диалог. Ближе к моменту "
                                 "съёмки — выше.")
                measure = tkfont.Font(family=FONT["ui"], size=10).measure
                line, used = None, 0
                for name, count in names:
                    text = f"{name} · {count}"
                    w = measure(text) + px(13) * 2 + px(6)
                    if line is None or used + w > self.sheet_w:
                        line = tk.Frame(body, bg=VOID)
                        line.pack(anchor="w", pady=(0, px(6)))
                        used = 0
                    pill = Pill(line, text, lambda n=name: self.log_name(n))
                    pill.set_kind("on" if name in v["names"] else "chip")
                    pill.pack(side="left", padx=(0, px(6)))
                    used += w
                if v["names"]:
                    Pill(body, "Показать всех", lambda: self.log_name(None), kind="ghost").pack(anchor="w")
        screen = not core.log_path(shot["out"], shot["name"]).exists()
        self.label(body, "Строки чатлога за час до и после СС, пунктир — момент съёмки. Отметь нужные и нажми "
                         "«На СС»: они встанут в чат тем же шрифтом и цветом, что в игре. Клик по заголовку куска "
                         "отмечает его целиком." +
                   (" Снятый с экрана чат заменится, вернуть его можно кнопкой «С экрана» в «Строках»."
                    if screen else ""), 16)

    def log_names(self):
        v = self.logview
        near, total = {}, {}
        for (when, _), (kind, who, _) in zip(v["lines"], v["who"]):
            if who and kind in (chat.SPEECH, chat.ACTION):
                total[who] = total.get(who, 0) + 1
                if abs((when - v["at"]).total_seconds()) <= core.LOG_NEAR_S:
                    near[who] = near.get(who, 0) + 1
        ranked = sorted(total, key=lambda n: (-near.get(n, 0), -total[n], n))
        keep = [n for n in ranked[:LOG_NAMES]] + [n for n in ranked[LOG_NAMES:] if n in v["names"]]
        return [(n, total[n]) for n in keep]

    def log_show(self, value):
        self.logview["all"] = value == "all"
        self.log_refilter()
        self.log_changed()

    def log_name(self, name):
        names = self.logview["names"]
        if name is None:
            names.clear()
        else:
            names.symmetric_difference_update({name})
        self.log_refilter()
        self.redraw()

    def log_refilter(self):
        v = self.logview
        lines, at, keep = v["lines"], v["at"], self.app.cfg["keep"]
        seen = [k for k, (kind, who, _) in enumerate(v["who"])
                if (v["all"] or kind in keep) and (not v["names"] or who in v["names"])]
        starts = set(core.log_chunks([lines[k] for k in seen]))
        items, mark, bounds, chunk = [], None, {}, None
        for n, k in enumerate(seen):
            if mark is None and lines[k][0] > at:
                mark = len(items)
                items.append(("mark", k))
            if n in starts:
                chunk = k
                bounds[k] = []
                items.append(("head", k))
            bounds[chunk].append(k)
            items.append(("line", k))
        if mark is None:
            mark = len(items)
            items.append(("mark", len(lines)))
        v.update(items=items, mark=mark, bounds=bounds, width=None, offset=None)

    def open_log(self):
        shot, self.logview = self.target, None
        if shot is None:
            return
        at = core.shot_time(shot["name"]) or datetime.now()
        self.c.config(cursor="watch")
        self.c.update_idletasks()
        lines = core.read_log(shot["out"], at)
        self.c.config(cursor="")
        saved = {core.log_key(*line) for line in core.picked_log(shot["edit"])}
        self.logview = {"name": shot["name"], "at": at, "lines": lines, "who": [core.log_who(p) for _, p in lines],
                        "on": {k for k, line in enumerate(lines) if core.log_key(*line) in saved},
                        "all": False, "names": set()}
        self.log_refilter()

    def log_count_text(self):
        v = self.logview
        return f"Отмечено {len(v['on'])} из {len(v['lines'])}" if v and v["lines"] else "Строк нет"

    def chat_font(self):
        if self.log_font is None:
            self.log_font = tkfont.Font(family="Arial", size=-px(15), weight="bold")
        return self.log_font

    def log_layout(self, width):
        v = self.logview
        if v["width"] == width:
            return
        font = self.chat_font()
        measure = lru_cache(maxsize=None)(font.measure)
        lh = font.metrics("linespace") + px(1)
        tops, wraps, y = [], {}, px(10)
        for kind, k in v["items"]:
            tops.append(y)
            if kind == "line":
                wraps[k] = [row for _, row in core.log_rows([v["lines"][k]], measure, width)] or [[]]
                y += len(wraps[k]) * lh + px(10)
            else:
                y += px(40)
        v.update(width=width, tops=tops, wraps=wraps, lh=lh, full=y + px(10))

    def draw_log(self, area):
        self.c.delete("shot")
        ax, ay, aw, ah = area
        self.c.create_rectangle(ax, ay, ax + aw, ay + ah, fill=BLACK, outline="", tags=("shot",))
        v = self.logview
        if v is None or not v["lines"]:
            self.c.create_text(ax + aw // 2, ay + ah // 2, text="В чатлоге нет строк за час до и после этой СС. "
                               "Строки пишутся, пока в настройках включён чатлог.", width=aw - px(80),
                               justify="center", fill=SUB, font=(FONT["ui"], 12), tags=("shot",))
            return
        x0 = ax + px(120)
        self.log_layout(max(px(200), aw - px(148)))
        tops, items, lines, lh = v["tops"], v["items"], v["lines"], v["lh"]
        if v["offset"] is None:
            v["offset"] = tops[v["mark"]] - ah // 2
        v["offset"] = max(0, min(v["offset"], v["full"] - ah))
        v["top"] = top = ay - v["offset"]
        font = self.chat_font()
        ticks = self.row_photos = [ImageTk.PhotoImage(tick(px(18), on)) for on in (False, True)]
        ends = tops[1:] + [v["full"] - px(10)]
        for j in range(max(0, bisect.bisect_right(tops, v["offset"]) - 1), len(items)):
            y, bottom = top + tops[j], top + ends[j]
            if y > ay + ah:
                break
            kind, k = items[j]
            if kind == "mark":
                mid, label = (y + bottom) / 2, f"СС снята · {v['at']:%H:%M:%S}"
                wide = tkfont.Font(family=FONT["semi"], size=9).measure(label) + px(16)
                self.c.create_line(ax + px(16), mid, ax + aw - px(16), mid, fill=SUB, dash=(4, 3), tags=("shot",))
                self.c.create_rectangle(x0 - px(8), mid - px(10), x0 - px(8) + wide, mid + px(10), fill=BLACK,
                                        outline="", tags=("shot",))
                self.c.create_text(x0, mid, text=label, anchor="w", fill=WHITE, font=(FONT["semi"], 9), tags=("shot",))
                continue
            on = k in v["on"]
            if kind == "head":
                span, tag = v["bounds"][k], f"lhead{j}"
                picked = sum(i in v["on"] for i in span)
                on = picked == len(span)
                text = (f"{lines[k][0]:%H:%M}–{lines[span[-1]][0]:%H:%M} · строк: {len(span)}" +
                        (f" · отмечено: {picked}" if picked else ""))
                self.c.create_rectangle(ax, y, ax + aw, bottom, fill=BLACK, outline="", tags=("shot", tag, tag + "-bg"))
                self.c.create_image(ax + px(16), y + px(24), anchor="w", image=ticks[on], tags=("shot", tag))
                self.c.create_text(ax + px(48), y + px(24), text=text, anchor="w", fill=WHITE if picked else SUB,
                                   font=(FONT["semi"], 10), tags=("shot", tag))
                idle, hot = BLACK, ROW
            else:
                tag, first = f"lrow{j}", y + px(5) + lh / 2
                self.c.create_rectangle(ax, y, ax + aw, bottom, fill=SLATE if on else BLACK, outline="",
                                        tags=("shot", tag, tag + "-bg"))
                self.c.create_image(ax + px(16), first, anchor="w", image=ticks[on], tags=("shot", tag))
                self.c.create_text(ax + px(48), first, text=f"{lines[k][0]:%H:%M:%S}", anchor="w", fill=SUB,
                                   font=(FONT["ui"], 9), tags=("shot", tag))
                for n, row in enumerate(v["wraps"][k]):
                    for x, text, color in row:
                        self.c.create_text(x0 + x, y + px(5) + n * lh, text=text.rstrip(), anchor="nw", fill=color,
                                           font=font, tags=("shot", tag))
                idle, hot = (SLATE, MIST) if on else (BLACK, ROW)
            self.c.tag_bind(tag, "<Enter>", lambda _, t=tag, c=hot: (self.c.itemconfig(t + "-bg", fill=c),
                                                                  self.c.config(cursor="hand2")))
            self.c.tag_bind(tag, "<Leave>", lambda _, t=tag, c=idle: (self.c.itemconfig(t + "-bg", fill=c),
                                                                   self.c.config(cursor="")))
        self.c.tag_lower("shot")

    def log_item_at(self, y):
        v = self.logview
        return min(max(bisect.bisect_right(v["tops"], y - v["top"]) - 1, 0), len(v["items"]) - 1)

    def mark_log(self, a, b, on):
        v = self.logview
        for kind, k in v["items"][min(a, b):max(a, b) + 1]:
            if kind == "line":
                (v["on"].add if on else v["on"].discard)(k)
        self.log_changed()

    def toggle_chunk(self, j):
        v = self.logview
        k = v["items"][j][1]
        span = set(v["bounds"][k])
        v["on"] = v["on"] - span if span <= v["on"] else v["on"] | span
        self.log_changed()

    def log_changed(self):
        self.draw_log(self.area())
        if self.sheet is not None and self.log_count.winfo_exists():
            self.log_count.config(text=self.log_count_text())

    def apply_log(self):
        v, shot = self.logview, self.target
        if shot is None or v is None or v["name"] != shot["name"]:
            return
        if not v["on"]:
            self.note = "отметь хотя бы одну строку"
            self.update_meta()
            return
        picked = [v["lines"][k] for k in sorted(v["on"])]
        try:
            core.use_log(shot, self.app.cfg, picked)
        except (OSError, ValueError) as e:
            self.note = f"строки не встали: {e}"
            self.update_meta()
            return
        self.tool, self.offset = "lines", 0
        self.switched(shot, f"строк из чатлога: {len(picked)}")

    def from_screen(self):
        shot = self.target
        try:
            core.use_screen(shot, self.app.cfg)
        except (OSError, ValueError) as e:
            self.note = f"кадры чата не открылись: {e}"
            self.update_meta()
            return
        self.switched(shot, "чат снова с экрана")

    def switched(self, shot, note):
        self.schedule_save(shot)
        self.redraw()
        self.note = note
        self.update_meta()

    def sheet_carry(self, body):
        names = self.scene_names()
        mine = f"к СС {names.index(self.current()) + 1} сцены" if names else "к этой"
        self.label(body, f"Нажми на СС справа — её строки добавятся {mine}, повторы склеятся сами.")
        Pill(body, "Назад к строкам", lambda: self.toggle_tool("lines"), kind="ghost").pack(anchor="w", pady=(px(8), 0))

    def sheet_crop(self, body):
        shot, names = self.target, self.scene_names()
        edit, look = shot["edit"], self.look(shot)[0]
        whole = " · вся сцена" if names else ""
        self.field(body, "Формат" + whole, 0)
        FramePick(body, look["format"], self.set_frame, lambda: core.plan(shot["bg"], self.look(shot)[0])["base"],
                  self.sheet_w).pack(anchor="w")
        self.field(body, "Размер" + whole)
        self.size_pick = SizePick(body, look["size"], self.set_size, self.sheet_w)
        self.size_pick.pack(fill="x")
        self.size_pick.show(look["format"])
        self.field(body, "Приближение")
        zoom = self.slider(body, 1.0, 3.0, edit["zoom"], lambda v: self.change(zoom=v), step=0.05,
                           fmt=lambda v: f"{v:.2f}×")
        self.sliders["zoom"] = (zoom, lambda: shot["edit"]["zoom"])
        self.buttons(body, (("По центру", lambda: self.change(center=[0.5, 0.5])),), 12)
        if names:
            self.label(body, "Тёмные полосы сверху и снизу — переходы между СС, чат на них не заходит.", 12)
            return
        join = edit.get("join") or {}
        side = join.get("side") if join.get("side") in core.JOIN_SIDES else "none"
        self.field(body, "Расширить поле кадра", 18)
        self.choice(body, SIDES, side, self.set_field_side)
        if side == "none":
            self.label(body, "Место сбоку для второго ракурса или чата, СС остаётся своего размера.", 4)
            return
        pct = lambda v: f"{v:.0f}%"
        self.field(body, "Насколько")
        self.slider(body, 10, 100, round(join["size"] * 100), lambda v: self.change_field(size=v / 100), fmt=pct)
        self.field(body, "Мягкий край СС")
        self.slider(body, 0, 100, round(join["fade"] * 100), lambda v: self.change_field(fade=v / 100), fmt=pct)
        self.label(body, "Новое место заполнено размытым продолжением СС.", 10)

    def set_field_side(self, side):
        edit = self.shot["edit"]
        edit["join"] = dict(edit.get("join") or FIELD_DEFAULT, side=side)
        self.redraw()
        self.schedule_save()

    def change_field(self, **values):
        self.shot["edit"]["join"].update(values)
        self.media_redraw()
        self.schedule_save()

    def set_frame(self, value):
        if self.tool == "crop":
            self.size_pick.show(value)
        if not self.scene_names():
            self.change(format=value, center=[0.5, 0.5])
            return
        self.shot["edit"]["format"] = value
        self.schedule_save(self.shot)
        self.media_redraw()

    def set_size(self, value):
        if not self.scene_names():
            self.change(size=value)
            return
        self.shot["edit"]["size"] = value
        self.schedule_save(self.shot)
        self.media_redraw()

    def sheet_text(self, body):
        shot, names = self.target, self.scene_names()
        edit = shot["edit"]
        whole = " · вся сцена" if names else ""
        if names:
            self.field(body, "Показывать", 0)
            self.choice(body, VIEWS, "all" if self.whole else "one", self.set_whole)
            if self.whole:
                self.label(body, "Тяни чат любой СС мышью прямо по сцене: на переход, на соседнюю СС или в её угол. "
                                 "Колесо — прокрутка, Ctrl + колесо — масштаб.", 8)
        self.field(body, "Размер текста" + whole, 14 if names else 0)
        self.choice(body, SCALES, edit["text_scale"], lambda v: self.change_text(text_scale=float(v)))
        self.field(body, "Обводка" + whole)
        self.choice(body, OUTLINES, edit["outline"], lambda v: self.change_text(outline=int(v)))
        self.field(body, "Отступ от края" + whole)
        margin = self.slider(body, 0, 96, edit["margin"], lambda v: self.change_text(margin=int(v)), step=2,
                             fmt=lambda v: f"{v:.0f} px")
        self.sliders["margin"] = (margin, lambda: shot["edit"]["margin"])
        spots = [pos for _, pos in core.parts(shot["rows"], edit)]
        self.field(body, "Где чат" if len(spots) == 1 else "Где части чата")
        for k, pos in enumerate(spots):
            row = tk.Frame(body, bg=VOID)
            row.pack(anchor="w", pady=(0, px(6)))
            Corners(row, pos if isinstance(pos, str) else None, lambda v, k=k: self.pick_place(k, v)).pack(side="left")
            text = ("" if len(spots) == 1 else f"Часть {k + 1} · ") + place_name(pos)
            tk.Label(row, text=text, bg=VOID, fg=WHITE, font=(FONT["ui"], 10)).pack(side="left", padx=(px(10), 0))
        self.label(body, "Клик по углу ставит туда чат. Его можно и тянуть мышью по картинке.", 6)

    def change_text(self, **values):
        shots = [s for _, s in self.members() if s] if self.scene_names() else [self.target]
        for shot in shots:
            shot["edit"].update(values)
            self.schedule_save(shot)
        self.media_redraw()
        if self.previewing():
            self.want_preview()

    def set_whole(self, value):
        self.whole = value == "all"
        if self.whole:
            self.fetch_scene()
            self.preview = self.preview_info = None
            self.want_preview()
        self.redraw()

    def sheet_file(self, body):
        edit = self.shot["edit"]
        self.field(body, "Формат", 0)
        self.choice(body, FILES, edit["file"], self.set_file)
        if edit["file"] == "jpg":
            self.field(body, "Качество фона")
            quality = self.slider(body, 10, 100, edit.get("quality", core.TEXT_QUALITY),
                                  lambda v: self.change(quality=int(v)), fmt=lambda v: f"{v:.0f}")
            self.sliders["quality"] = (quality, lambda: self.shot["edit"].get("quality", core.TEXT_QUALITY))
            self.label(body, "Сжимается только фон, текст чата всегда остаётся чётким.", 4)
        self.file_info = tk.Label(body, text=self.preview_info or "считаю размер…", bg=VOID, fg=WHITE,
                                  font=(FONT["semi"], 12), anchor="w")
        self.file_info.pack(fill="x", pady=(px(18), px(2)))
        self.label(body, "Размер кадра — в «Кадре».")

    def set_file(self, value):
        self.change(file=value)
        self.redraw()

    def sheet_scene(self, body):
        scene, names = self.shot["edit"].get("scene"), self.scene_names()
        self.label(body, "Несколько СС одна под другой с плавными переходами — раскадровка для форума. Чат можно "
                         "тянуть мышью прямо здесь: на переход или на другую СС.")
        self.buttons(body, (("Выбрать СС", lambda: self.toggle_tool("scenepick")),) +
                     ((("Разобрать", self.drop_scene),) if names else ()))
        self.file_info = tk.Label(body, text=self.preview_info or "собираю…", bg=VOID, fg=WHITE,
                                  font=(FONT["semi"], 12), anchor="w")
        if not names:
            return
        self.field(body, "Порядок", 18)
        for k, name in enumerate(names):
            self.frame_row(body, k, name, len(names))
        seams = {"all": "Все"} | {str(k): f"{k + 1}–{k + 2}" for k in range(len(names) - 1)}
        self.seam = self.seam if self.seam in seams else "all"
        look = scene["seams"][0 if self.seam == "all" else int(self.seam)]
        pct = lambda v: f"{v:.0f}%"
        self.field(body, "Переход", 10)
        self.choice(body, seams, self.seam, self.pick_seam)
        self.field(body, "Плавность")
        self.slider(body, 0, 50, round(look["fade"] * 100), lambda v: self.change_seam(fade=v / 100), fmt=pct)
        self.field(body, "Размытие")
        self.slider(body, 0, 100, round(look["blur"] * 100), lambda v: self.change_seam(blur=v / 100), fmt=pct)
        self.field(body, "Затемнение")
        self.slider(body, 0, 100, round(look["dark"] * 100), lambda v: self.change_seam(dark=v / 100), fmt=pct)
        self.field(body, "Просмотр", 10)
        self.buttons(body, (("Целиком", lambda: self.view_fit("all")), ("По ширине", lambda: self.view_fit("width")),
                            ("1:1", lambda: self.view_fit("real"))))
        self.file_info.pack(fill="x", pady=(px(14), px(2)))

    def frame_row(self, body, k, name, count):
        mine = name == self.name
        row = tk.Frame(body, bg=VOID)
        row.pack(fill="x", pady=(0, px(4)))
        photo = self.frame_thumb(name)
        pick = []
        if photo:
            pick.append(tk.Label(row, image=photo, bg=VOID, cursor="hand2"))
            pick[-1].pack(side="left", padx=(0, px(8)))
        pick.append(tk.Label(row, text=f"{k + 1}. {when(name)}" + (" · эта" if mine else ""), bg=VOID,
                             fg=WHITE if mine else SUB, font=(FONT["ui"], 10), cursor="hand2"))
        pick[-1].pack(side="left")
        for w in pick:
            w.bind("<Button-1>", lambda _, k=k: self.focus_frame(k))
            w.bind("<Enter>", lambda _: self.hint("Показать эту СС в сцене крупно"))
            w.bind("<Leave>", lambda _: self.hint(None))
        for key, text, on, command, tip in (
                ("close", "×", not mine, lambda: self.drop_frame(k), "Убрать из сцены"),
                ("down", "↓", k < count - 1, lambda: self.move_frame(k, 1), "Ниже"),
                ("up", "↑", k > 0, lambda: self.move_frame(k, -1), "Выше"),
                ("crop", "▭", True, lambda: self.edit_frame(name), "Поправить эту СС: кадр, текст, картинки")):
            glyph, face = (ICONS[key], (FONT["icon"], 11)) if FONT["icon"] else (text, (FONT["ui"], 11))
            button = tk.Label(row, text=glyph, font=face, bg=VOID, fg=SUB if on else VOID, width=2,
                              cursor="hand2" if on else "")
            button.pack(side="right")
            if on:
                button.bind("<Button-1>", lambda _, f=command: f())
                button.bind("<Enter>", lambda _, b=button, t=tip: (b.config(fg=WHITE), self.hint(t)))
                button.bind("<Leave>", lambda _, b=button: (b.config(fg=SUB), self.hint(None)))

    def edit_frame(self, name):
        self.part = None if name == self.name else name
        self.toggle_tool("crop")

    def frame_thumb(self, name):
        size = (px(54), px(32))
        if name != self.name:
            return self.thumb(self.shot["out"], name, size)
        bg = self.shot["bg"]
        key = ("bg", id(bg), size)
        if key not in self.thumbs:
            x0, y0, x1, y1 = core.plan(bg, self.shot["edit"])["rect"]
            im = Image.fromarray(bg[y0:y1, x0:x1])
            im.thumbnail(size, Image.BILINEAR, reducing_gap=2.0)
            self.thumbs[key] = ImageTk.PhotoImage(im)
        return self.thumbs[key]

    def sheet_scenepick(self, body):
        self.label(body, "Отметь СС и нажми «Готово». Они встанут по времени съёмки и получат формат кадра этой СС, "
                         f"а строки, которые уже были выше, уберутся сами. До {core.SCENE_MAX} СС.")
        Pill(body, "Готово", lambda: self.toggle_tool("scene"), kind="ghost").pack(anchor="w", pady=(px(8), 0))

    def scene_lists(self):
        scene = self.shot["edit"].get("scene") or {"shots": [self.name], "seams": []}
        return list(scene["shots"]), [dict(s) for s in scene["seams"]]

    def set_scene(self, shots, seams):
        self.shot["edit"]["scene"] = {"shots": shots, "seams": seams} if len(shots) > 1 else None
        self.schedule_save()

    def toggle_scene(self, name):
        shots, seams = self.scene_lists()
        if name in shots:
            k = shots.index(name)
            shots.pop(k)
            seams.pop(max(k - 1, 0))
        elif len(shots) >= core.SCENE_MAX:
            self.note = f"в сцену помещается до {core.SCENE_MAX} СС"
            self.update_meta()
            return
        else:
            k = next((i for i, n in enumerate(shots) if n > name), len(shots))
            shots.insert(k, name)
            self.fetch(name)
            self.added.add(name)
            near = max(k - 1, 0)
            seams.insert(near, dict(seams[min(near, len(seams) - 1)] if seams else core.SEAM))
        self.set_scene(shots, seams)
        self.draw_donors(self.area())
        self.update_meta()

    def move_frame(self, k, delta):
        shots, seams = self.scene_lists()
        shots[k], shots[k + delta] = shots[k + delta], shots[k]
        self.set_scene(shots, seams)
        self.want_preview()
        self.redraw()

    def drop_frame(self, k):
        shots, seams = self.scene_lists()
        shots.pop(k)
        seams.pop(max(k - 1, 0))
        self.set_scene(shots, seams)
        self.want_preview()
        self.redraw()

    def pick_seam(self, value):
        self.seam = value
        self.redraw()

    def change_seam(self, **values):
        seams = self.shot["edit"]["scene"]["seams"]
        for k in range(len(seams)) if self.seam == "all" else (int(self.seam),):
            seams[k].update(values)
        self.want_preview()
        self.schedule_save()

    def drop_scene(self):
        self.shot["edit"]["scene"] = None
        self.preview = self.preview_info = None
        self.want_preview()
        self.redraw()
        self.schedule_save()

    def change(self, **values):
        shot = self.target
        if shot is None:
            return
        shot["edit"].update(values)
        self.media_redraw()
        if self.previewing():
            self.want_preview()
        self.schedule_save(shot)

    def media_redraw(self):
        if self.shot is None or self.index == 0:
            return
        if self.tool not in DONORS:
            self.c.delete("shot")
            self.draw_media(self.area())
            self.c.tag_lower("shot")
        for bar, value in self.sliders.values():
            if bar.winfo_exists():
                bar.set(value())
        self.update_meta()

    def want_preview(self):
        self.preview_rev += 1
        if self.preview_job:
            self.c.after_cancel(self.preview_job)
        self.preview_job = self.c.after(150, self.encode_preview)

    def encode_preview(self):
        self.preview_job = None
        if self.shot is None or not self.previewing():
            return
        snap, key = self.snapshot(), (self.name, self.preview_rev)

        def work():
            try:
                layout = {}
                img, _, data = core.encoded(snap, layout)
                arr = core.decoded(data) if snap["edit"]["file"] == "jpg" else img
                self.app.inbox.put(("previewed", key, (arr, len(data), layout or None)))
            except Exception as e:
                self.app.inbox.put(("previewed", key, str(e)))

        threading.Thread(target=work, daemon=True).start()

    def previewed(self, key, value):
        if key != (self.name, self.preview_rev) or not self.previewing():
            return
        if isinstance(value, str):
            self.preview_info = f"размер не посчитался: {value}"
        else:
            self.preview, size, self.layout = value
            self.preview_info = f"≈ {megabytes(size)} · {self.preview.shape[1]} × {self.preview.shape[0]}"
            self.media_redraw()
        info = getattr(self, "file_info", None)
        if self.sheet is not None and info is not None and info.winfo_exists():
            info.config(text=self.preview_info)

    def draw_preview(self, rect):
        if self.preview is None:
            return
        self.preview_rect, self.preview_view = rect, self.preview
        ix, iy, dw, dh = rect
        key = (id(self.preview), dw, dh)
        if self.preview_photo is None or self.preview_photo[0] != key:
            img = Image.fromarray(self.preview).resize((dw, dh), Image.BILINEAR, reducing_gap=2.0)
            self.preview_photo = (key, ImageTk.PhotoImage(img))
        self.c.create_image(ix, iy, anchor="nw", image=self.preview_photo[1], tags=("shot",))

    def update_meta(self):
        if self.sheet is not None:
            self.sheet_meta.config(text=self.meta())
        else:
            self.c.itemconfig("meta", text=self.meta())

    def line_items(self):
        if not self.scene_names():
            return [(self.shot, i, 0, self.name) for i in range(len(self.shot["rows"]))]
        items = []
        for k, (name, shot) in enumerate(self.members()):
            items.append((shot, None, k, name))
            items += [(shot, i, k, name) for i in range(len(shot["rows"]))] if shot else []
        return items

    def draw_lines(self, area):
        self.c.delete("shot")
        ax, ay, aw, ah = area
        items = self.items = self.line_items()
        rows = [shot["rows"][i] for shot, i, _, _ in items if i is not None]
        widest = max((r["glyphs"][-1][1] + 8 for r in rows), default=1)
        s = min(1.0, (aw - px(104)) / widest)
        self.lines_x0, self.lines_s = ax + px(48), s
        slot = max(px(28), round(max((r["pitch"] for r in rows), default=0) * s) + px(12))
        self.offset = max(0, min(self.offset, max(0, slot * len(items) + px(24) - ah)))
        self.c.create_rectangle(ax, ay, ax + aw, ay + ah, fill=BLACK, outline="", tags=("shot",))
        if not items:
            self.c.create_text(ax + aw // 2, ay + ah // 2, text="Строк нет. Выбери их в чатлоге: кнопка «Из чатлога» "
                               "слева.", fill=SUB, font=(FONT["ui"], 12), tags=("shot",))
        y = ay + px(12) - self.offset
        self.lines_top, self.lines_slot = y, slot
        self.row_photos = []
        on, off = ImageTk.PhotoImage(tick(px(18), True)), ImageTk.PhotoImage(tick(px(18), False))
        self.row_photos += [on, off]
        current, breaks = self.current(), {}
        for j, (shot, i, k, name) in enumerate(items):
            if y + slot > ay and y < ay + ah and i is None:
                tag = f"head{j}"
                state = "" if shot else " · не открылась" if self.cache.get(name) is False else " · загружаю…"
                text = f"СС {k + 1} · {when(name)}" + (" · эта" if name == self.name else "") + state
                if j:
                    self.c.create_line(ax + px(16), y + px(4), ax + aw - px(16), y + px(4), fill=MIST, tags=("shot",))
                self.c.create_rectangle(ax, y + px(5), ax + aw, y + slot, fill=BLACK, outline="", tags=("shot", tag))
                self.c.create_text(ax + px(16), y + slot / 2 + px(2), text=text, anchor="w", font=(FONT["semi"], 10),
                                   fill=WHITE if name == current else SUB, tags=("shot", tag))
                if shot and shot["rows"]:
                    names, home = self.scene_names(), f"home{j}"
                    at = sorted({names.index(h) + 1 if h in names else k + 1
                                 for h in core.homes_of(shot["rows"], shot["edit"])})
                    moved = at != [k + 1]
                    self.c.create_text(ax + aw - px(16), y + slot / 2 + px(2),
                                       text="чат на СС " + ", ".join(map(str, at)), anchor="e",
                                       font=(FONT["semi"], 9), fill=WHITE if moved else SUB, tags=("shot", home))
                    self.c.tag_bind(home, "<Enter>", lambda _, t=home: (self.c.itemconfig(t, fill=WHITE),
                                                                        self.c.config(cursor="hand2")))
                    self.c.tag_bind(home, "<Leave>", lambda _, t=home, c=WHITE if moved else SUB: (
                        self.c.itemconfig(t, fill=c), self.c.config(cursor="")))
                self.c.tag_bind(tag, "<Enter>", lambda _: self.c.config(cursor="hand2"))
                self.c.tag_bind(tag, "<Leave>", lambda _: self.c.config(cursor=""))
            elif y + slot > ay and y < ay + ah:
                r = shot["rows"][i]
                if id(shot) not in breaks:
                    breaks[id(shot)] = core.cuts(shot["rows"], shot["edit"])
                cuts = breaks[id(shot)]
                tag = f"row{j}"
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
                cut, idle = f"cut{j}", WHITE if i in cuts else DIM
                if i in cuts:
                    self.c.create_line(ax + px(16), y, ax + aw - px(16), y, fill=SUB, dash=(4, 3), tags=("shot",))
                    self.c.create_text(ax + aw - px(52), y + px(3), text=f"часть {cuts.index(i) + 2}", fill=WHITE,
                                       anchor="ne", font=(FONT["semi"], 9), tags=("shot",))
                if i:
                    glyph, face = (ICONS["cut"], (FONT["icon"], 12)) if FONT["icon"] else ("✂", (FONT["ui"], 12))
                    self.c.create_text(ax + aw - px(28), y + slot / 2, text=glyph, font=face, tags=("shot", cut),
                                       fill=idle)
                    self.c.tag_bind(cut, "<Enter>", lambda _, t=cut: (self.c.itemconfig(t, fill=WHITE),
                                                                      self.c.config(cursor="hand2")))
                    self.c.tag_bind(cut, "<Leave>", lambda _, t=cut, c=idle: (self.c.itemconfig(t, fill=c),
                                                                              self.c.config(cursor="")))
                self.c.tag_bind(tag, "<Enter>", lambda _, t=tag, c=cut, on=i in cuts: (
                    self.c.itemconfig(t + "-bg", fill=ROW), self.c.itemconfig(c, fill=WHITE if on else SUB),
                    self.c.config(cursor="hand2")))
                self.c.tag_bind(tag, "<Leave>", lambda _, t=tag, c=cut, d=idle: (
                    self.c.itemconfig(t + "-bg", fill=BLACK), self.c.itemconfig(c, fill=d),
                    self.c.config(cursor="")))
            y += slot
        self.c.tag_lower("shot")

    def toggle_word(self, j, word, key):
        shot, i = self.items[j][:2]
        r = shot["rows"][i]
        other = "drop" if key == "hide" else "hide"
        mine = [tuple(span) for span in r.get(key, [])]
        r[other] = [tuple(span) for span in r.get(other, []) if tuple(span) != word]
        r[key] = [span for span in mine if span != word] if word in mine else mine + [word]
        for name, field in core.MARKS:
            shot["edit"][field] = core.spans_of(shot["rows"], name)
        self.draw_lines(self.area())
        self.schedule_save(shot)

    def open_popup(self, j, word):
        shot, i = self.items[j][:2]
        r = shot["rows"][i]
        hidden = word in [tuple(span) for span in r.get("hide", [])]
        gone = word in [tuple(span) for span in r.get("drop", [])]
        picks = (("hide", "Убрать плашку" if hidden else "Закрыть плашкой"),
                 ("drop", "Вернуть слово" if gone else "Удалить слово"), ("row", "Убрать строку"))
        s, top = self.lines_s, self.lines_top + j * self.lines_slot
        left, right = self.lines_x0 + word[0] * s, self.lines_x0 + (word[1] + 1) * s
        self.c.create_rectangle(left - px(3), top + px(3), right + px(3), top + self.lines_slot - px(3), outline=WHITE,
                                tags=("popup",))
        font = (FONT["ui"], 10)
        item = px(34)
        w, h = max(tkfont.Font(family=FONT["ui"], size=10).measure(t) for _, t in picks) + px(40), item * 3 + px(8)
        ax, ay, aw, ah = self.area()
        x = min(max(left, ax + px(8)), ax + aw - w - px(8))
        y = top + self.lines_slot if top + self.lines_slot + h < ay + ah - px(8) else top - h
        self.popup_photo = ImageTk.PhotoImage(rounded(w, h, px(10), SLATE, LINE, 1.2))
        self.c.create_image(x, y, anchor="nw", image=self.popup_photo, tags=("popup",))
        for k, (key, text) in enumerate(picks):
            tag, row = f"pop-{key}", y + px(4) + k * item
            self.c.create_rectangle(x + px(4), row, x + w - px(4), row + item, fill=SLATE, outline="",
                                    tags=("popup", tag, tag + "-bg"))
            self.c.create_text(x + px(18), row + item / 2, text=text, anchor="w", fill=WHITE, font=font,
                               tags=("popup", tag))
            self.c.tag_bind(tag, "<Enter>", lambda _, t=tag: (self.c.itemconfig(t + "-bg", fill=MIST),
                                                              self.c.config(cursor="hand2")))
            self.c.tag_bind(tag, "<Leave>", lambda _, t=tag: (self.c.itemconfig(t + "-bg", fill=SLATE),
                                                              self.c.config(cursor="")))
        self.popup = {"j": j, "word": word}

    def close_popup(self):
        self.c.delete("popup")
        self.popup = None

    def popup_pick(self, key):
        j, word = self.popup["j"], self.popup["word"]
        self.close_popup()
        shot, i = self.items[j][:2]
        if key != "row":
            self.toggle_word(j, word, key)
            return
        shot["rows"][i]["keep"] = False
        shot["edit"]["keep"] = [r["keep"] for r in shot["rows"]]
        self.draw_lines(self.area())
        self.count.config(text=self.count_text())
        self.schedule_save(shot)

    def mark_overlay(self, geo):
        if self.tool != "images" or not geo or self.active_ov >= len(geo["overlays"]):
            return
        box = geo["overlays"][self.active_ov]
        if not box:
            return
        l, t, r, b = box["x"], box["y"], box["x"] + box["w"], box["y"] + box["h"]
        self.c.create_rectangle(l, t, r - 1, b - 1, outline=WHITE, width=1, dash=(4, 3), tags=("shot",))
        locked = core.lock_ratio(self.target["edit"]["overlays"][self.active_ov].get("cut", "free")) is not None
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
        overlays = self.target["edit"].setdefault("overlays", [])
        self.label(body, "Второй ракурс, коллаж или стикер поверх СС. С мягкими краями фото растворяется в ней.")
        self.buttons(body, (("Из файла", self.add_file), ("Из буфера", self.add_clipboard)))
        self.buttons(body, (("Из другой СС", lambda: self.toggle_tool("photopick")),), 6)
        if overlays:
            self.active_ov = min(self.active_ov, len(overlays) - 1)
            ov = overlays[self.active_ov]
            pct = lambda v: f"{v:.0f}%"
            if len(overlays) > 1:
                self.field(body, "Картинка")
                self.choice(body, {str(i): str(i + 1) for i in range(len(overlays))}, str(self.active_ov),
                            lambda v: self.select_ov(int(v)))
            self.field(body, "Размер по ширине кадра")
            size = self.slider(body, 5, 200, round(ov["w"] * 100), lambda v: self.change_ov(w=round(v / 100, 4)),
                               fmt=pct)
            self.sliders["ov"] = (size, lambda: round(self.target["edit"]["overlays"][self.active_ov]["w"] * 100))
            self.field(body, "Мягкие края")
            self.slider(body, 0, 100, round(ov.get("soft", 0.0) * 100), lambda v: self.change_ov(soft=v / 100),
                        fmt=pct)
            self.field(body, "Прозрачность")
            self.slider(body, 0, 90, round((1 - ov.get("alpha", 1.0)) * 100),
                        lambda v: self.change_ov(alpha=round(1 - v / 100, 2)), fmt=pct)
            self.field(body, "Обрезка")
            FramePick(body, ov.get("cut", "free"), self.crop_ov, self.crop_size, self.sheet_w, CROPS,
                      (16, 20000)).pack(anchor="w")
            self.buttons(body, (("Сбросить обрезку", lambda: self.crop_ov("reset")), ("Убрать", self.remove_ov)), 8)

    def sheet_photopick(self, body):
        self.label(body, "Нажми на СС справа — её фон ляжет поверх этой с мягкими краями.")
        Pill(body, "Назад", lambda: self.toggle_tool("images"), kind="ghost").pack(anchor="w", pady=(px(8), 0))

    def pick_file(self, title):
        path = filedialog.askopenfilename(title=title, filetypes=[
            ("Картинки", "*.png *.jpg *.jpeg *.webp *.bmp *.gif"), ("Все файлы", "*.*")])
        if not path:
            return None
        try:
            with Image.open(path) as im:
                return im.copy()
        except OSError as e:
            self.note = f"картинка не открылась: {e}"
            self.update_meta()
            return None

    def clipboard_image(self):
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
            return None
        return data

    def add_file(self):
        image = self.pick_file("Картинка поверх СС")
        if image is not None:
            self.add_image(image)

    def add_clipboard(self):
        image = self.clipboard_image()
        if image is not None:
            self.add_image(image)

    def add_image(self, image):
        overlays = self.target["edit"].setdefault("overlays", [])
        if len(overlays) >= core.MAX_OVERLAYS:
            self.note = f"больше {core.MAX_OVERLAYS} картинок не поместится"
            self.update_meta()
            return
        try:
            ov = core.add_overlay(self.target["out"], self.target["name"], image)
        except OSError as e:
            self.note = f"картинка не сохранилась: {e}"
            self.update_meta()
            return
        p = core.plan(self.target["bg"], self.look(self.target)[0])
        if p["ext_box"] and ov["soft"]:
            core.fit_field(ov, p, image.size)
        overlays.append(ov)
        self.active_ov = len(overlays) - 1
        self.redraw()
        self.schedule_save()

    def select_ov(self, k):
        self.active_ov = k
        self.redraw()

    def source_size(self, ov):
        try:
            return core.overlay_image(self.target["out"] / "src" / ov["file"]).size
        except OSError:
            return None

    def crop_size(self):
        ov = self.target["edit"]["overlays"][self.active_ov]
        W, H = self.source_size(ov) or (1, 1)
        l, t, r, b = ov["crop"]
        return round((r - l) * W), round((b - t) * H)

    def crop_ov(self, value):
        ov = self.target["edit"]["overlays"][self.active_ov]
        size = self.source_size(ov)
        if size is None:
            return
        out_w = core.plan(self.target["bg"], self.look(self.target)[0])["size"][0]
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
        self.target["edit"]["overlays"][self.active_ov].update(values)
        self.media_redraw()
        self.schedule_save()

    def remove_ov(self):
        overlays = self.target["edit"]["overlays"]
        overlays.pop(self.active_ov)
        self.active_ov = max(0, self.active_ov - 1)
        self.redraw()
        self.schedule_save()

    def toggle_cut(self, j):
        shot, i = self.items[j][:2]
        rows, edit = shot["rows"], shot["edit"]
        breaks = core.cuts(rows, edit)
        spots = core.places(edit, len(breaks) + 1)[1:]
        homes = core.homes_of(rows, edit)
        if i in breaks:
            k = breaks.index(i)
            breaks.pop(k)
            spots.pop(k)
            homes.pop(k + 1)
        else:
            k = sorted(breaks + [i]).index(i)
            used = [edit["pos"]] + spots
            order = list(core.SPARE_PLACES[core.corner_of(edit["pos"])]) + list(core.CHAT_POSITIONS)
            free = [c for c in order if c not in used]
            breaks.insert(k, i)
            spots.insert(k, free[0] if free else core.corner_of(used[k]))
            homes.insert(k + 1, homes[k])
        edit["breaks"], edit["places"] = breaks, spots
        if isinstance(edit.get("home"), list):
            edit["home"] = homes
        self.draw_lines(self.area())
        self.count.config(text=self.count_text())
        self.schedule_save(shot)

    def count_text(self):
        shots = [s for _, s in self.members() if s] if self.scene_names() else [self.shot]
        kept, total = sum(r["keep"] for s in shots for r in s["rows"]), sum(len(s["rows"]) for s in shots)
        if len(shots) > 1:
            return f"В сцене {kept} из {total}"
        n = len(core.parts(self.shot["rows"], self.shot["edit"]))
        return f"В СС {kept} из {total}" + (f" · частей: {n}" if n > 1 else "")

    def set_place(self, part, pos):
        shot = self.target
        edit = shot["edit"]
        if part == 0:
            edit["pos"] = pos
            return
        spots = core.places(edit, len(core.parts(shot["rows"], edit)))[1:]
        spots[part - 1] = pos
        edit["places"] = spots

    def pick_place(self, part, pos):
        if self.target is None:
            return
        self.set_place(part, pos)
        self.redraw()
        self.schedule_save()

    def row_at(self, y):
        return min(max(int((y - self.lines_top) // self.lines_slot), 0), len(self.items) - 1)

    def mark_rows(self, a, b, drag):
        touched = drag["shots"]
        for shot, i, _, name in self.items[min(a, b):max(a, b) + 1]:
            if i is not None:
                shot["rows"][i]["keep"] = drag["keep"]
                touched[name] = shot
        for shot in touched.values():
            shot["edit"]["keep"] = [r["keep"] for r in shot["rows"]]
        self.draw_lines(self.area())
        self.count.config(text=self.count_text())

    def draw_donors(self, area):
        self.c.delete("shot")
        ax, ay, aw, ah = area
        out = self.shot["out"]
        names = core.donors(out, self.name if self.tool == "scenepick" else self.current(), self.names)
        if not names:
            self.c.create_text(ax + aw // 2, ay + ah // 2, text="Других СС с исходными кадрами нет", fill=SUB,
                               font=(FONT["ui"], 12), tags=("shot",))
            return
        picking = self.tool == "scenepick"
        chosen = set(self.scene_names()) | {self.name}
        if picking:
            names = [n for n in reversed(self.names) if n in chosen or n in names]
            ticks = [ImageTk.PhotoImage(tick(px(20), on)) for on in (False, True)]
            self.photos += ticks
        cols = 2 if len(names) <= 4 else 3 if len(names) <= 9 else 4
        lines = -(-len(names) // cols)
        gap, cap = px(16), px(28)
        cw = (aw - gap * (cols - 1)) / cols
        ch = min(cw * 0.75, (ah - gap * (lines - 1)) / lines - cap)
        top = ay + (ah - lines * (ch + cap) - gap * (lines - 1)) / 2
        for k, name in enumerate(names):
            x, y = ax + (k % cols) * (cw + gap), top + (k // cols) * (ch + cap + gap)
            tag = f"donor{k}"
            photo = self.thumb(out, name, (max(1, round(cw)), max(1, round(ch))))
            w, h = (photo.width(), photo.height()) if photo else (round(cw), round(ch))
            left, up = x + (cw - w) / 2, y + (ch - h) / 2
            on = picking and name in chosen
            idle = WHITE if on else HAIR
            if photo:
                self.c.create_image(left, up, anchor="nw", image=photo, tags=("shot", tag))
            self.c.create_rectangle(left - 1, up - 1, left + w, up + h, outline=idle, width=2 if on else 1,
                                    fill="" if photo else ROW, tags=("shot", tag, tag + "-box"))
            if picking:
                self.c.create_image(left + px(8), up + px(8), anchor="nw", image=ticks[on], tags=("shot", tag))
            mine = picking and name == self.name
            self.c.create_text(left, up + h + px(8), text=when(name) + (" · эта СС" if mine else ""), anchor="nw",
                               fill=WHITE if on else SUB, font=(FONT["ui"], 10), tags=("shot", tag, tag + "-label"))
            if mine:
                continue
            self.c.tag_bind(tag, "<Button-1>", lambda _, n=name: self.donor_pick(n))
            self.c.tag_bind(tag, "<Enter>", lambda _, t=tag: (self.c.itemconfig(t + "-box", outline=WHITE),
                                                              self.c.itemconfig(t + "-label", fill=WHITE),
                                                              self.c.config(cursor="hand2")))
            self.c.tag_bind(tag, "<Leave>", lambda _, t=tag, c=idle, f=WHITE if on else SUB: (
                self.c.itemconfig(t + "-box", outline=c), self.c.itemconfig(t + "-label", fill=f),
                self.c.config(cursor="")))

    def thumb(self, out, name, size):
        path = core.shot_image(out, name)
        try:
            key = (path, path.stat().st_mtime_ns, size)
            if key not in self.thumbs:
                with Image.open(path) as im:
                    im.draft("RGB", size)
                    im = im.convert("RGB")
                    im.thumbnail(size, Image.BILINEAR)
                if len(self.thumbs) > 48:
                    self.thumbs.clear()
                self.thumbs[key] = ImageTk.PhotoImage(im)
        except OSError:
            return None
        return self.thumbs[key]

    def donor_pick(self, name):
        if self.tool == "carry":
            self.carry(name)
            return
        if self.tool == "scenepick":
            self.toggle_scene(name)
            return
        self.c.config(cursor="watch")
        self.c.update_idletasks()
        try:
            shot = core.load_shot(self.shot["out"], name, self.app.cfg)
        except (OSError, ValueError):
            shot = None
        self.c.config(cursor="")
        if shot is None:
            self.note = "фон той СС не открылся"
            self.update_meta()
            return
        self.tool = "images"
        self.add_image(Image.fromarray(shot["bg"]))

    def carry(self, name):
        self.c.config(cursor="watch")
        self.c.update_idletasks()
        shot = self.target
        if shot is None:
            return
        try:
            added = core.carry_chat(shot, name, self.app.cfg)
        except (OSError, ValueError) as e:
            self.c.config(cursor="")
            self.note = f"чат не перенёсся: {e}"
            self.update_meta()
            return
        self.c.config(cursor="")
        self.tool = "lines"
        self.redraw()
        if added:
            self.schedule_save(shot)
        self.note = (f"из СС от {when(name)} добавлено строк: {added}" if added
                     else "все строки той СС уже есть в этой")
        self.update_meta()

    def drop_repeats(self):
        missing = [n for n, shot in self.members() if shot is None and self.cache.get(n) is not False]
        if missing:
            self.c.config(cursor="watch")
            self.c.update_idletasks()
        for name in missing:
            try:
                shot = core.load_shot(self.shot["out"], name, self.app.cfg)
            except (OSError, ValueError):
                shot = None
            self.cache[name] = shot or False
        self.c.config(cursor="")
        shots, gone = [shot for _, shot in self.members()], 0
        for shot, dup in zip(shots, core.repeats(shots)):
            if dup:
                for i in dup:
                    shot["rows"][i]["keep"] = False
                shot["edit"]["keep"] = [r["keep"] for r in shot["rows"]]
                self.schedule_save(shot)
                gone += len(dup)
        self.note = f"убрал повторы из сцены: {gone}" if gone else "повторов в сцене нет"
        if self.tool == "lines":
            self.redraw()
        self.update_meta()

    def reset_lines(self):
        keep = self.app.cfg["keep"]
        for shot in [s for _, s in self.members() if s] if self.scene_names() else [self.shot]:
            log = core.log_path(shot["out"], shot["name"]).exists()
            for r in shot["rows"]:
                r["keep"] = log or r["kind"] in keep
            shot["edit"]["keep"] = [r["keep"] for r in shot["rows"]]
            self.schedule_save(shot)
        self.redraw()

    def tags_here(self):
        return self.c.gettags("current")

    def press(self, e):
        tags = self.tags_here()
        if any(t.startswith(("rail", "nav", "older")) for t in tags) or self.shot is None or self.index == 0:
            return
        row = next((t for t in tags if re.fullmatch(r"row\d+", t)), None)
        cut = next((t for t in tags if re.fullmatch(r"cut\d+", t)), None)
        head = next((t for t in tags if re.fullmatch(r"head\d+", t)), None)
        if self.tool == "logpick":
            row = next((int(t[4:]) for t in tags if re.fullmatch(r"lrow\d+", t)), None)
            head = next((int(t[5:]) for t in tags if re.fullmatch(r"lhead\d+", t)), None)
            if head is not None:
                self.toggle_chunk(head)
            elif row is not None:
                on = self.logview["items"][row][1] not in self.logview["on"]
                self.drag = {"kind": "log", "on": on, "first": row, "last": row}
                self.mark_log(row, row, on)
            return
        if self.tool == "lines":
            pick = next((t[4:] for t in tags if t.startswith("pop-") and not t.endswith("-bg")), None)
            if pick or self.popup:
                self.popup_pick(pick) if pick else self.close_popup()
                return
            home = next((int(t[4:]) for t in tags if re.fullmatch(r"home\d+", t)), None)
            if home is not None:
                self.next_home(home)
                return
            if not (head or cut or row):
                return
            j = int(head[4:] if head else (cut or row)[3:])
            name = self.items[j][3]
            self.part = None if name == self.name else name
            self.hint(None)
            if head:
                self.draw_lines(self.area())
            elif cut:
                self.toggle_cut(j)
            else:
                shot, i = self.items[j][:2]
                self.drag = {"kind": "rows", "keep": not shot["rows"][i]["keep"], "first": j, "last": j,
                             "shots": {}, "moved": False}
            return
        hit = self.scene_chat_at(e) if self.previewing() else None
        if hit:
            self.drag = {"kind": "scenechat", "x": e.x, "y": e.y, "hit": hit}
            self.c.config(cursor="fleur")
            return
        if self.view_box and self.inside(e, {"img": self.preview_rect}):
            self.drag = {"kind": "view", "x": e.x, "y": e.y, "at": (self.view["cx"], self.view["cy"]), "moved": False}
            self.loupe.hide()
            return
        shot = self.target
        if self.tool in DONORS + PREVIEWS or shot is None or self.previewing():
            return
        over = self.tool == "images"
        handle = next((t[7:] for t in tags if t.startswith("handle-")), None)
        if over and handle and self.painter.geo:
            item = shot["edit"]["overlays"][self.active_ov]
            box = self.painter.geo["overlays"][self.active_ov]
            size = self.source_size(item)
            if box and size:
                self.drag = {"kind": "crop", "handle": handle, "part": self.active_ov, "x": e.x, "y": e.y,
                             "crop": list(item["crop"]), "box": dict(box), "size": size}
            return
        ov = next((int(t[7:]) for t in tags if re.fullmatch(r"shot-ov\d+", t)), None)
        if over and ov is not None:
            self.active_ov = ov
            item = shot["edit"]["overlays"][ov]
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
            self.drag = {"kind": "pan", "x": e.x, "y": e.y, "center": list(shot["edit"]["center"])}
            self.c.config(cursor="fleur")

    def inside(self, e, geo):
        ix, iy, dw, dh = geo["img"]
        return ix <= e.x <= ix + dw and iy <= e.y <= iy + dh

    def motion(self, e):
        if not self.drag:
            return
        geo = self.painter.geo
        if self.drag["kind"] == "log":
            j = self.log_item_at(e.y)
            if j != self.drag["last"]:
                self.drag["last"] = j
                self.mark_log(self.drag["first"], j, self.drag["on"])
        elif self.drag["kind"] == "rows":
            i = self.row_at(e.y)
            if i != self.drag["last"]:
                self.drag["moved"], self.drag["last"] = True, i
                self.mark_rows(self.drag["first"], i, self.drag)
        elif self.drag["kind"] == "chat":
            at = (self.drag["at"][0] + e.x - self.drag["x"], self.drag["at"][1] + e.y - self.drag["y"])
            self.c.coords(f"shot-chat{self.drag['part']}", *self.chat_spot(self.drag["part"], *at)[1:])
        elif self.drag["kind"] == "crop":
            self.drag_crop(e, geo)
        elif self.drag["kind"] == "scenechat":
            x0, y0, d = self.view_box
            rx, ry = self.preview_rect[:2]
            _, _, left, top, w, h = self.drag["hit"]
            x = rx + (left - x0) * d + e.x - self.drag["x"]
            y = ry + (top - y0) * d + e.y - self.drag["y"]
            self.c.delete("ghost")
            self.c.create_rectangle(x, y, x + w * d, y + h * d, outline=VOID, width=3, tags=("ghost",))
            self.c.create_rectangle(x, y, x + w * d, y + h * d, outline=WHITE, width=1, dash=(5, 3), tags=("ghost",))
        elif self.drag["kind"] == "view":
            dx, dy = e.x - self.drag["x"], e.y - self.drag["y"]
            if not self.drag["moved"] and max(abs(dx), abs(dy)) < px(4):
                return
            self.drag["moved"] = True
            self.c.config(cursor="fleur")
            H, W = self.preview.shape[:2]
            d = self.view_box[2]
            self.view["cx"] = self.drag["at"][0] - dx / d / W
            self.view["cy"] = self.drag["at"][1] - dy / d / H
            if not self.pending_media:
                self.pending_media = True
                self.c.after(16, self.flush_media)

        elif self.drag["kind"] in ("ov", "ovpan"):
            ov = self.target["edit"]["overlays"][self.drag["part"]]
            (out_w, out_h), d = geo["out"], geo["d"]
            if self.drag["kind"] == "ov":
                ov["x"] = round(min(max(self.drag["at"][0] + (e.x - self.drag["x"]) / d / out_w, 0.0), 1.0), 4)
                ov["y"] = round(min(max(self.drag["at"][1] + (e.y - self.drag["y"]) / d / out_h, 0.0), 1.0), 4)
                self.snap_ov(ov, geo["overlays"][self.drag["part"]], geo)
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
            shot = self.target
            H, W = shot["bg"].shape[:2]
            x0, y0, x1, y1 = geo["plan"]["rect"]
            k = (x1 - x0) / (geo["plan"]["base"][0] * geo["d"])
            cx = self.drag["center"][0] - (e.x - self.drag["x"]) * k / W
            cy = self.drag["center"][1] - (e.y - self.drag["y"]) * k / H
            shot["edit"]["center"] = [cx, cy]
            if not self.pending_media:
                self.pending_media = True
                self.c.after(16, self.flush_media)

    def chat_spot(self, part, x, y):
        geo = self.painter.geo
        ix, iy = geo["img"][:2]
        d, pad, margin = geo["d"], geo["pad"], geo["plan"]["margin"]
        (W, H), (it, ib) = geo["out"], geo["inset"]
        inner = H - it - ib
        lw, lh = geo["chats"][part]["lw"], geo["chats"][part]["lh"]
        left, top = (x - ix) / d + pad, (y - iy) / d - it + pad
        near = margin + 0.04 * min(W, inner)
        hx = "left" if left < near else "right" if left + lw - 2 * pad > W - near else round(left / W, 4)
        vy = "top" if top < near else "bottom" if top + lh - 2 * pad > inner - near else round(top / inner, 4)
        pos = f"{vy}-{hx}" if isinstance(hx, str) and isinstance(vy, str) else [hx, vy]
        left, top = chat.place(W, inner, lw, lh, pad, pos, margin)
        return pos, ix + left * d, iy + (top + it) * d

    def snap_ov(self, ov, box, geo):
        if not box:
            return
        (W, H), d = geo["out"], geo["d"]
        near = 0.015 * min(W, H)
        for key, size, half in (("x", W, box["w"] / d / 2), ("y", H, box["h"] / d / 2)):
            c = ov[key] * size
            if abs(c - half) < near:
                ov[key] = round(half / size, 4)
            elif abs(c + half - size) < near:
                ov[key] = round((size - half) / size, 4)

    def drag_crop(self, e, geo):
        drag = self.drag
        ov = self.target["edit"]["overlays"][drag["part"]]
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

    def loaded_members(self):
        return [(n, shot) for n, shot in self.members() if shot]

    def scene_chat_at(self, e):
        if not self.view_box or not self.layout or not self.layout.get("chats"):
            return None
        x0, y0, d = self.view_box
        x, y = x0 + (e.x - self.preview_rect[0]) / d, y0 + (e.y - self.preview_rect[1]) / d
        return next((c for c in reversed(self.layout["chats"])
                     if c[2] <= x <= c[2] + c[4] and c[3] <= y <= c[3] + c[5]), None)

    def drop_scene_chat(self, drag, e):
        k, part, left, top, lw, lh = drag["hit"]
        layout, d = self.layout, self.view_box[2]
        names = layout.get("names") or [n for n, _ in self.loaded_members()]
        if k >= len(names) or max(abs(e.x - drag["x"]), abs(e.y - drag["y"])) < px(4):
            return
        name, shot = names[k], self.member(names[k])
        if shot is None:
            self.note = "эта СС не открылась, чат не перенёсся"
            self.update_meta()
            return
        pad, margin, W = layout["pads"][k], layout["margins"][k], self.preview.shape[1]
        left, top = left + (e.x - drag["x"]) / d + pad, top + (e.y - drag["y"]) / d + pad
        w, h = lw - 2 * pad, lh - 2 * pad
        mid = top + h / 2
        j = next((n for n, (a, b) in enumerate(layout["spans"]) if mid < b), len(layout["spans"]) - 1)
        a, b = layout["spans"][j]
        inner, top = b - a, top - a
        near = margin + 0.04 * min(W, inner)
        hx = "left" if left < near else "right" if left + w > W - near else None
        vy = None if top < 0 or top + h > inner else "top" if top < near else "bottom" if top + h > inner - near else None
        if hx and vy:
            pos = f"{vy}-{hx}"
        else:
            x = {"left": margin, "right": W - margin - w}.get(hx, left)
            y = {"top": margin, "bottom": inner - margin - h}.get(vy, top)
            pos = [round(min(max(x, 0), W - w) / W, 4), round(y / inner, 4)]
        edit = shot["edit"]
        if part == 0:
            edit["pos"] = pos
        else:
            spots = core.places(edit, len(core.parts(shot["rows"], edit)))[1:]
            spots[part - 1] = pos
            edit["places"] = spots
        at = core.homes_of(shot["rows"], edit)
        at[part] = None if j == k else names[j]
        edit["home"] = at if len(set(at)) > 1 else at[0]
        self.schedule_save(shot)
        self.want_preview()
        what = f"часть {part + 1} чата СС {k + 1}" if len(at) > 1 else f"чат СС {k + 1}"
        self.note = f"{what} теперь на СС {j + 1}" if j != k else ""
        self.update_meta()

    def next_home(self, j):
        shot, _, k, name = self.items[j]
        names = [n for n, _ in self.loaded_members()]
        if shot is None or len(names) < 2:
            return
        at = core.homes_of(shot["rows"], shot["edit"])[0]
        now = names.index(at) if at in names else names.index(name)
        to = names[(now + 1) % len(names)]
        shot["edit"]["home"] = None if to == name else to
        self.schedule_save(shot)
        self.draw_lines(self.area())

    def flush_media(self):
        self.pending_media = False
        self.media_redraw()

    def release(self, e):
        drag, self.drag = self.drag, None
        self.c.config(cursor="")
        if not drag or self.shot is None or drag["kind"] == "log":
            return
        if drag["kind"] == "scenechat":
            self.c.delete("ghost")
            self.drop_scene_chat(drag, e)
            return
        if drag["kind"] == "view":
            k = None if drag["moved"] or self.tool != "scene" else self.seam_at(e.y)
            if k is not None:
                self.seam = "all" if self.seam == str(k) else str(k)
                self.redraw()
            return
        if drag["kind"] == "rows":
            if not drag["moved"]:
                j = drag["first"]
                shot, i = self.items[j][:2]
                r, x = shot["rows"][i], (e.x - self.lines_x0) / self.lines_s
                word = next(((a, b) for a, b in chat.words(r) if a - 3 <= x <= b + 3), None)
                if r["keep"] and word and e.x >= self.lines_x0 - px(4):
                    self.open_popup(j, word)
                    return
                self.mark_rows(j, j, drag)
            for shot in drag["shots"].values():
                self.schedule_save(shot)
            return
        shot = self.target
        if shot is None:
            return
        if drag["kind"] == "chat":
            at = (drag["at"][0] + e.x - drag["x"], drag["at"][1] + e.y - drag["y"])
            self.set_place(drag["part"], self.chat_spot(drag["part"], *at)[0])
        elif drag["kind"] in ("ov", "ovpan", "crop"):
            self.redraw()
            self.schedule_save()
            return
        else:
            look = self.look(shot)[0]
            H, W = shot["bg"].shape[:2]
            x0, y0, x1, y1 = chat.frame_rect(W, H, core.ratio_of(look["format"]), look["zoom"], look["center"])
            shot["edit"]["center"] = [round((x0 + x1) / 2 / W, 4), round((y0 + y1) / 2 / H, 4)]
        self.media_redraw()
        if self.tool == "text":
            self.redraw()
        self.schedule_save()

    def hover(self, e):
        if self.drag or self.index == 0 or self.shot is None:
            return
        tags = self.tags_here()
        rail = next((t[5:] for t in tags if t.startswith("rail-")), None)
        if rail or any(t.startswith(("rail", "nav", "older")) for t in tags):
            self.loupe.hide()
            self.hint(RAIL_HINTS.get(rail))
            return
        if self.tool == "lines":
            self.hint(self.lines_hint(tags, e))
            return
        if self.tool == "logpick":
            head = any(re.fullmatch(r"lhead\d+", t) for t in tags)
            row = any(re.fullmatch(r"lrow\d+", t) for t in tags)
            self.hint("Клик — отметить весь кусок или снять с него отметки" if head else
                      "Клик — отметить строку · веди мышью, чтобы отметить несколько" if row else None)
            return
        if self.tool in DONORS:
            donor = any(re.fullmatch(r"donor\d+", t) for t in tags)
            self.hint({"carry": "Клик — добавить строки этой СС", "photopick": "Клик — положить фон этой СС поверх",
                       "scenepick": "Клик — добавить в сцену или убрать"}[self.tool] if donor else None)
            return
        if self.previewing():
            rect = self.preview_rect
            inside = self.preview is not None and rect and self.inside(e, {"img": rect})
            grab = inside and self.view_box and self.scene_chat_at(e) is not None
            seam = inside and self.view_box and self.tool == "scene" and self.seam_at(e.y) is not None
            self.c.config(cursor=("hand2" if seam else "fleur") if inside and self.view_box else "")
            if inside and not grab and (not self.view_box or self.view_box[2] < 1):
                self.loupe.show(e.x, e.y, rect, self.preview_view)
            else:
                self.loupe.hide()
            self.hint(None if not inside else
                      "Тяни чат — на переход, на другую СС или в её угол" if grab else
                      "Клик — настроить только этот переход" if seam else
                      "Тяни — двигать · колесо — прокрутка · Ctrl + колесо — масштаб" if self.view_box else
                      "Точно как в файле · лупа показывает пиксели 1:1")
            return
        over = self.tool == "images"
        if "shot-chat" in tags:
            self.c.config(cursor="fleur")
            self.hint("Тяни чат мышью — у края он сам встанет на отступ")
        elif over and any(t.startswith("handle-") for t in tags):
            self.hint("Тяни — обрезать картинку")
        elif over and "shot-ov" in tags:
            self.c.config(cursor="fleur")
            self.hint("Тяни — двигать · колесо — размер · Shift + тяни — сдвинуть обрезку")
        elif self.tool == "crop" and self.painter.geo and self.inside(e, self.painter.geo):
            self.c.config(cursor="fleur")
            self.hint("Тяни — выбрать, что в кадре · колесо — приближение")
        else:
            self.c.config(cursor="")
            self.hint(None)

    def lines_hint(self, tags, e):
        if "popup" in tags:
            return None
        if any(re.fullmatch(r"cut\d+", t) for t in tags):
            return "Разрезать чат здесь — дальше пойдёт новая часть"
        if any(re.fullmatch(r"home\d+", t) for t in tags):
            return "Клик — перенести чат этой СС на следующую СС сцены"
        if any(re.fullmatch(r"head\d+", t) for t in tags):
            return "Клик — выбрать эту СС"
        row = next((t for t in tags if re.fullmatch(r"row\d+", t)), None)
        if row is None:
            return None
        shot, i = self.items[int(row[3:])][:2]
        if not shot["rows"][i]["keep"]:
            return "Клик — вернуть строку"
        if e.x < self.lines_x0 - px(4):
            return "Клик — убрать строку · веди мышью, чтобы отметить несколько"
        return "Клик по слову — закрыть или удалить его · по галочке — убрать строку"

    def wheel(self, e):
        step = -1 if e.delta > 0 else 1
        if self.popup:
            self.close_popup()
        if self.tool == "logpick" and self.logview and self.logview["offset"] is not None:
            self.logview["offset"] += step * px(72)
            self.draw_log(self.area())
            return
        if self.view_box:
            if e.state & 0x4:
                self.zoom_view(self.view["zoom"] * (1.25 if step < 0 else 0.8), (e.x, e.y))
            else:
                x0, y0, d = self.view_box
                self.view["cy"] += step * 0.25 * self.preview_rect[3] / d / self.preview.shape[0]
                self.media_redraw()
            self.loupe.hide()
            return
        if self.tool == "lines" and self.shot is not None:
            self.offset += step * px(72)
            self.draw_lines(self.area())
            return
        shot = self.target
        ov = next((int(t[7:]) for t in self.tags_here() if re.fullmatch(r"shot-ov\d+", t)), None)
        if self.tool == "images" and shot is not None and ov is not None:
            item = shot["edit"]["overlays"][ov]
            item["w"] = round(min(max(item["w"] * (1.08 if step < 0 else 1 / 1.08), 0.05), 2.0), 4)
            self.active_ov = ov
            self.media_redraw()
            self.schedule_save()
            return
        if self.tool == "crop" and shot is not None:
            zoom = min(3.0, max(1.0, round(shot["edit"]["zoom"] - step * 0.1, 2)))
            self.change(zoom=zoom)
            return
        now = time.monotonic()
        if self.tool is None and now - self.last_wheel > 0.25:
            self.last_wheel = now
            self.go(self.index + step)

    def schedule_save(self, shot=None):
        shot = shot or self.target
        if shot is None:
            return
        self.note = "сохраняю…"
        self.update_meta()
        if self.save_job:
            self.c.after_cancel(self.save_job)
        self.saves[shot["name"]] = shot
        self.save_job = self.c.after(450, self.save_now)

    def flush_save(self):
        if self.save_job:
            self.c.after_cancel(self.save_job)
            self.save_now()

    def save_sync(self):
        if self.save_job:
            self.c.after_cancel(self.save_job)
            self.save_job = None
            snaps, self.saves = [self.snapshot(s) for s in self.saves.values()], {}
            self.store(snaps, lambda *_: None)

    def snapshot(self, shot=None, deep=True):
        shot = shot or self.shot
        snap = {**shot, "rows": [dict(r) for r in shot["rows"]], "edit": json.loads(json.dumps(shot["edit"]))}
        scene = shot["edit"].get("scene") if deep else None
        if scene:
            snap["members"] = {n: self.snapshot(m, False) for n in scene["shots"]
                               if n != shot["name"] and (m := self.cache.get(n))}
        return snap

    def save_now(self):
        self.save_job = None
        snaps, self.saves = [self.snapshot(s) for s in self.saves.values()], {}
        if snaps:
            self.save_queue.put(snaps)

    def save_loop(self):
        while True:
            self.store(self.save_queue.get(), lambda *a: self.app.inbox.put(("saved",) + a))

    @staticmethod
    def store(snaps, report):
        snaps.sort(key=lambda snap: bool(snap["edit"].get("scene")))
        for snap in snaps:
            try:
                core.save_shot(snap, heads=False)
                report(snap["name"], None)
            except Exception as e:
                report(snap["name"], str(e))
        if snaps:
            names = [snap["name"] for snap in snaps]
            for head in core.refresh_heads(snaps[0]["out"], names, snaps[0].get("cfg"), names):
                report(head, None)

    def saved(self, name, error):
        self.media = None
        if name in (self.name, self.part):
            self.note = f"не сохранилось: {error}" if error else "сохранено"
            self.update_meta()
        if self.shot is not None and name in self.scene_names() and self.drag is None:
            if self.previewing() and name != self.name:
                self.want_preview()
            elif self.tool is None:
                self.redraw()

    def copy(self):
        name = self.name
        snap = self.snapshot() if self.shot is not None else None
        path = core.shot_image(self.app.cfg["out"], name)
        self.note = "копирую…"
        self.update_meta()

        def work():
            try:
                img = core.render_shot(snap)[0] if snap else core.read_image(path)
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
        elif e.keysym == "Escape" and self.popup:
            self.close_popup()
        elif e.keysym == "Escape" and self.tool:
            self.toggle_tool(self.tool)
        elif e.keycode == 67 and e.state & 0x4 and self.index > 0:
            self.copy()
        elif 49 <= e.keycode < 49 + len(TOOLS) and self.shot is not None and self.index > 0:
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
        self.example.bind("<Motion>", self.example_hover)
        self.example.bind("<Leave>", lambda _: self.loupe.hide())
        self.painter = Painter(self.example)
        self.loupe = Loupe(self.example)
        self.example_geo = None
        self.encoded_arr = None
        self.encoded_photo = None
        self.estimate_job = None
        self.estimate_rev = 0
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
        hair = tk.Frame(parent, bg=HAIR, height=1)
        hair.pack(fill="x")
        self.last_row = (line, hair)
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
        control, _, _ = self.row(f, "Чат", "Из чатлога — F11 снимает только сцену, строки потом выбираешь из записи "
                                           "чата")
        self.source_pick = self.choice(control, SOURCES, cfg["source"], self.set_source)
        control, _, _ = self.row(f, "Звук", "Сигнал, когда СС готова")
        self.choice(control, SOUND, "yes" if cfg["sound"] else "no", lambda v: self.app.set("sound", v))
        control, _, _ = self.row(f, "Трей", "Крестик прячет окно в трей, съёмка работает. Выход — через значок")
        self.choice(control, SOUND, "yes" if cfg["tray"] else "no", self.app.set_tray)
        self.section(f, "Новые СС: кадр и файл")
        control, _, _ = self.row(f, "Кадр", "Свой — ширина и высота в пикселях")
        FramePick(control, cfg["format"], self.set_frame, self.frame_now, self.list_w - self.label_w).pack(anchor="w")
        control, _, _ = self.row(f, "Размер файла", "По короткой стороне, в пикселях")
        self.size_pick = SizePick(control, cfg["size"], lambda v: self.app.set("size", v), self.list_w - self.label_w)
        self.size_pick.pack(anchor="w")
        self.size_pick.show(cfg["format"])
        control, _, _ = self.row(f, "Файл", "JPG весит примерно втрое меньше PNG, чат остаётся чётким")
        self.choice(control, FILES, cfg["file"], self.set_file)
        self.file_row = self.last_row
        control, _, _ = self.row(f, "Качество JPG", "Сжимается только фон, чат всегда чёткий. Наведи на пример — "
                                                    "лупа покажет пиксели 1:1")
        self.quality = Slider(control, 10, 100, cfg["quality"], lambda v: self.estimate(),
                              lambda v: self.app.set("quality", str(int(v))), width=self.list_w - self.label_w - px(20),
                              fmt=lambda v: f"{v:.0f}")
        self.quality.pack(anchor="w")
        self.quality_row = self.last_row
        self.show_quality()
        self.section(f, "Новые СС: чат")
        control, _, _ = self.row(f, "Текст чата")
        self.choice(control, SCALES, raw["text_scale"], lambda v: self.app.set("text_scale", v))
        control, _, _ = self.row(f, "Обводка")
        self.choice(control, OUTLINES, raw["outline"], lambda v: self.app.set("outline", v))
        control, _, _ = self.row(f, "Угол чата")
        self.choice(control, POSITIONS, cfg["chat_pos"], lambda v: self.app.set("chat_pos", v), cols=2)
        control, _, _ = self.row(f, "Отступ от края", "Чат у края кадра встаёт на этот отступ. В редакторе — «Текст»")
        Slider(control, 0, 96, cfg["margin"], lambda v: None, lambda v: self.app.set("margin", str(int(v))),
               width=self.list_w - self.label_w - px(20), step=2, fmt=lambda v: f"{v:.0f} px").pack(anchor="w")
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
        self.chatlog_pick = self.choice(control, SOUND, "yes" if cfg["chatlog"] else "no", self.set_chatlog)
        self.chatlog_state = tk.Label(control, text="Выключен", bg=VOID, fg=SUB, font=(FONT["ui"], 9), anchor="w",
                                      justify="left", wraplength=self.list_w - self.label_w - px(10))
        self.chatlog_state.pack(fill="x", pady=(px(4), 0))
        Pill(control, "Открыть", self.open_chatlog, kind="ghost").pack(anchor="w", pady=(px(8), 0))

    def set_chatlog(self, value):
        self.app.set("chatlog", value)
        self.toggle_chatlog(value)
        if value == "no" and self.app.cfg["source"] == "log":
            self.app.set("source", "screen")
            self.source_pick.set("screen")
            self.mode_sub.config(text=self.mode_text())

    def set_source(self, value):
        self.app.set("source", value)
        self.mode_sub.config(text=self.mode_text())
        if value == "log" and not self.app.cfg["chatlog"]:
            self.chatlog_pick.set("yes")
            self.set_chatlog("yes")

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

    def set_file(self, value):
        self.app.set("file", value)
        self.show_quality()

    def show_quality(self):
        line, hair = self.quality_row
        if self.app.cfg["file"] == "jpg":
            line.pack(fill="x", after=self.file_row[1])
            hair.pack(fill="x", after=line)
        else:
            line.pack_forget()
            hair.pack_forget()

    def frame_now(self):
        shot = self.sample or core.sample_shot(self.app.cfg)
        return core.plan(shot["bg"], core.new_edit(self.app.cfg, shot["rows"]))["base"]

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
        keys = cfg["hud_key"] if cfg["source"] == "log" else f"{cfg['hud_key']} и {cfg['dark_key']}"
        if cfg["auto"]:
            return f"Программа сама жмёт {keys}."
        return f"Сам жмёшь {keys} перед {cfg['key']}."

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
        self.example_geo, self.encoded_arr = geo, None
        self.loupe.hide()
        self.example.create_text(geo["img"][0], geo["img"][1] + geo["img"][3] + px(14), anchor="nw", fill=SUB,
                                 font=(FONT["ui"], 10), width=geo["img"][2], text=self.caption(), tags=("caption",))
        self.estimate()

    def caption(self, size=None):
        shot = self.sample
        out_w, out_h = core.plan(shot["bg"], shot["edit"])["size"]
        weight = f", ≈ {megabytes(size)}" if size else ""
        source = f"твоя СС от {when(shot['name'])}" if shot["name"] else "встроенный кадр"
        return (f"Так будет выглядеть новая СС: {out_w} × {out_h}{weight}. Пример — {source}. "
                f"Каждую готовую СС можно поправить в редакторе.")

    def estimate(self):
        if self.estimate_job:
            self.example.after_cancel(self.estimate_job)
        self.estimate_job = self.example.after(150, self.run_estimate)

    def run_estimate(self):
        self.estimate_job = None
        if self.sample is None or self.example_geo is None:
            return
        shot = self.sample
        edit = dict(shot["edit"], quality=int(self.quality.value))
        snap = {**shot, "rows": [dict(r) for r in shot["rows"]], "edit": edit,
                "out": shot.get("out") or self.app.cfg["out"]}
        self.estimate_rev += 1
        rev = self.estimate_rev

        def work():
            try:
                img, _, data = core.encoded(snap)
                arr = core.decoded(data) if edit["file"] == "jpg" else img
                self.app.inbox.put(("estimated", rev, (arr, len(data))))
            except Exception:
                self.app.inbox.put(("estimated", rev, None))

        threading.Thread(target=work, daemon=True).start()

    def estimated(self, rev, value):
        if rev != self.estimate_rev or value is None or self.example_geo is None:
            return
        self.encoded_arr, size = value
        ix, iy, dw, dh = self.example_geo["img"]
        img = Image.fromarray(self.encoded_arr).resize((dw, dh), Image.BILINEAR, reducing_gap=2.0)
        self.encoded_photo = ImageTk.PhotoImage(img)
        self.example.delete("encoded")
        self.example.create_image(ix, iy, anchor="nw", image=self.encoded_photo, tags=("encoded",))
        self.example.itemconfig("caption", text=self.caption(size))

    def example_hover(self, e):
        geo = self.example_geo
        if self.encoded_arr is None or geo is None:
            return
        ix, iy, dw, dh = geo["img"]
        if ix <= e.x <= ix + dw and iy <= e.y <= iy + dh:
            self.loupe.show(e.x, e.y, geo["img"], self.encoded_arr)
        else:
            self.loupe.hide()


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
        self.mark.place(x=PAD + px(12), rely=0.5, anchor="w")
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
