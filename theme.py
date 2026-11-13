import ctypes
import tkinter.font as tkfont
from ctypes import wintypes
from datetime import datetime
from functools import lru_cache

import numpy as np
from PIL import Image, ImageDraw

import chat
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


STYLES = {"none": "Нет", "cctv": "Камера наблюдения", "body": "Бодикам"}


UNDO_MAX = 200


UNDO_MERGE_S = 0.8


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
