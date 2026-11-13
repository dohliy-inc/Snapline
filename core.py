import configparser
import ctypes
import io
import json
import queue
import re
import sys
import threading
import time
import traceback
import winsound
from ctypes import wintypes
from datetime import datetime, timedelta
from functools import lru_cache
from pathlib import Path

import numpy as np
from PIL import Image, ImageDraw, ImageFilter, ImageFont, ImageGrab

import chat

VERSION = "1.4"
RELEASES = "https://github.com/dohliy-inc/Snapline/releases/latest"
APP_DIR = Path(sys.executable if getattr(sys, "frozen", False) else __file__).resolve().parent
RES_DIR = Path(getattr(sys, "_MEIPASS", APP_DIR))
CONFIG_PATH = APP_DIR / "config.ini"
ERROR_LOG = APP_DIR / "error.log"
REFERENCE_SIDE = 1440

DEFAULTS = {
    "hotkey": "F11",
    "auto": "yes",
    "hud_key": "F7",
    "dark_key": "F2",
    "hud_delay_ms": "300",
    "output": "~/Pictures/Snapline",
    "format": "square",
    "size": "native",
    "file": "jpg",
    "quality": "92",
    "chat_pos": "top-left",
    "margin": "24",
    "text_scale": "1.5",
    "outline": "2",
    "keep": "речь, действие",
    "sound": "yes",
    "hide_names": "no",
    "chatlog": "no",
    "source": "screen",
    "tray": "yes",
    "tray_hint": "yes",
}
SIZES = {"native": None, "hd": 720, "fhd": 1080, "qhd": 1440, "4k": 2160}
SIDE_RANGE = (360, 4320)
FRAME_RANGE = (200, 7680)
FILE_TYPES = {"jpg": {"quality": 92, "subsampling": 0, "optimize": True, "progressive": True},
              "png": {"compress_level": 6}}
TEXT_QUALITY = 92
SRC_BG = (".jpg", {"quality": 95, "subsampling": 0})
SRC_CHAT = (".webp", {"lossless": True, "quality": 0, "method": 1})
CHAT_POSITIONS = ("top-left", "top-right", "bottom-left", "bottom-right")
LAYOUT_KEYS = ("format", "zoom", "center", "pos", "places", "size", "file", "quality", "text_scale", "outline",
               "margin", "overlays", "join", "scene")
JOIN_SIDES = {"left": Image.Transpose.FLIP_LEFT_RIGHT, "right": None, "top": Image.Transpose.TRANSVERSE,
              "bottom": Image.Transpose.TRANSPOSE}
MAX_OVERLAYS = 4
SCENE_MAX = 8
SEAM = {"fade": 0.2, "blur": 0.6, "dark": 0.3}
LUMA = np.array([0.299, 0.587, 0.114], np.float32)
GRAIN_TAPS = np.exp(-np.arange(-3, 4, dtype=np.float32) ** 2 / 2)
GRAIN_TAPS /= GRAIN_TAPS.sum()
GRAIN_GAIN = 0.873
GRAIN_MIN = 0.3
GRAIN_TILE, GRAIN_STEP = 64, 160
GRAIN_SPREAD = 32
MARKS = (("hide", "hidden"), ("drop", "dropped"))
LOG_FONT = "arialbd.ttf"
LOG_SIZE = 18 / 1440
LOG_PITCH = 21.5 / 1440
LOG_LEFT = 27 / 1440
LOG_WIDTH = 0.25
LOG_SPAN_S = 60 * 60
LOG_GAP_S = 3 * 60
LOG_STAMP = "%Y-%m-%d %H:%M:%S"
LOG_GUESS = (("*", "#c2a2da"), ("((", "#a0a0a0"))
LOG_TEXT = "#e6e6e6"
LOG_SAY = re.compile(r"(?:\[!\] )?(?P<who>[^\s:(*>\[][^:()]{1,40}?) (?:говорит|кричит|шепчет)[^:(]*"
                     r"(?:\((?:к (?P<to>[^)]+)|[^)]*)\))?:")
LOG_NEAR_S = 10 * 60
SOURCES = ("screen", "log")
SPARE_PLACES = {"top-left": ("bottom-left", "top-right"), "top-right": ("bottom-right", "top-left"),
                "bottom-left": ("top-left", "bottom-right"), "bottom-right": ("top-right", "bottom-left")}
KEYS = {f"F{i}": 0x6F + i for i in range(1, 25)}
KEYS.update(PAUSE=0x13, SCROLLLOCK=0x91, INSERT=0x2D, HOME=0x24, END=0x23, PAGEUP=0x21, PAGEDOWN=0x22)
EXTENDED_KEYS = {0x2D, 0x24, 0x23, 0x21, 0x22}
POLL_S = 0.025
KEY_HOLD_S = 0.04
DARK_TIMEOUT_S = 2.0
DARK_SETTLE_S = 0.06

TONE_STEP = ((1000, 70),)
TONE_SS = ((1000, 70), (1500, 120))
TONE_FAIL = ((300, 450),)

EVENTS = queue.Queue()
FILES = threading.Lock()
FRAMES = threading.Lock()
_frames = {}

user32 = ctypes.WinDLL("user32", use_last_error=True)
kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)


class KEYBDINPUT(ctypes.Structure):
    _fields_ = [("wVk", wintypes.WORD), ("wScan", wintypes.WORD), ("dwFlags", wintypes.DWORD),
                ("time", wintypes.DWORD), ("dwExtraInfo", ctypes.c_size_t)]


class MOUSEINPUT(ctypes.Structure):
    _fields_ = [("dx", wintypes.LONG), ("dy", wintypes.LONG), ("mouseData", wintypes.DWORD),
                ("dwFlags", wintypes.DWORD), ("time", wintypes.DWORD), ("dwExtraInfo", ctypes.c_size_t)]


class _INPUTUNION(ctypes.Union):
    _fields_ = [("mi", MOUSEINPUT), ("ki", KEYBDINPUT)]


class INPUT(ctypes.Structure):
    _fields_ = [("type", wintypes.DWORD), ("u", _INPUTUNION)]


INPUT_KEYBOARD, KEYEVENTF_EXTENDEDKEY, KEYEVENTF_KEYUP, KEYEVENTF_SCANCODE = 1, 0x1, 0x2, 0x8
user32.SendInput.argtypes = [wintypes.UINT, ctypes.POINTER(INPUT), ctypes.c_int]
user32.SendInput.restype = wintypes.UINT
user32.MapVirtualKeyW.argtypes = [wintypes.UINT, wintypes.UINT]
user32.MapVirtualKeyW.restype = wintypes.UINT
user32.GetAsyncKeyState.argtypes = [ctypes.c_int]
user32.GetAsyncKeyState.restype = ctypes.c_short
user32.OpenClipboard.argtypes = [wintypes.HWND]
user32.SetClipboardData.argtypes = [wintypes.UINT, wintypes.HANDLE]
user32.SetClipboardData.restype = wintypes.HANDLE
kernel32.GlobalAlloc.argtypes = [wintypes.UINT, ctypes.c_size_t]
kernel32.GlobalAlloc.restype = wintypes.HGLOBAL
kernel32.GlobalLock.argtypes = [wintypes.HGLOBAL]
kernel32.GlobalLock.restype = ctypes.c_void_p
kernel32.GlobalUnlock.argtypes = [wintypes.HGLOBAL]
kernel32.GlobalFree.argtypes = [wintypes.HGLOBAL]


def log(msg, level="info"):
    stamp = datetime.now().strftime("%H:%M:%S")
    print(f"[{stamp}] {msg}", flush=True)
    EVENTS.put(("log", stamp, msg, level))


def read_raw():
    raw = dict(DEFAULTS)
    if CONFIG_PATH.exists():
        cp = configparser.ConfigParser(inline_comment_prefixes=(";",))
        cp.read(CONFIG_PATH, encoding="utf-8-sig")
        section = next((s for s in ("snapline", "lspscreen") if s in cp), None)
        if section:
            raw.update({k: v for k, v in cp[section].items() if k in DEFAULTS})
    return raw


def write_raw(raw):
    cp = configparser.ConfigParser()
    cp["snapline"] = {k: str(raw[k]) for k in DEFAULTS}
    with open(CONFIG_PATH, "w", encoding="utf-8") as f:
        cp.write(f)


def _key(raw, name):
    key = raw[name].strip().upper()
    if key not in KEYS:
        raise ValueError(f"{name} = {key}: такой клавиши нет, можно {', '.join(KEYS)}")
    return key


def _bool(raw, name):
    try:
        return configparser.ConfigParser.BOOLEAN_STATES[raw[name].strip().lower()]
    except KeyError:
        raise ValueError(f"{name} = {raw[name]}: нужно yes или no") from None


def _num(raw, name, kind, lo, hi):
    try:
        value = kind(raw[name])
    except ValueError:
        raise ValueError(f"{name} = {raw[name]}: нужно число") from None
    if not lo <= value <= hi:
        raise ValueError(f"{name} = {value}: нужно от {lo} до {hi}")
    return value


def exact_of(fmt):
    m = re.fullmatch(r"(\d+)\s*[x×]\s*(\d+)", str(fmt).strip().lower())
    return (int(m[1]), int(m[2])) if m else None


def ratio_of(fmt):
    fmt = fmt.strip().lower()
    if fmt == "full":
        return None
    if fmt == "square":
        return 1.0
    exact = exact_of(fmt)
    if exact:
        lo, hi = FRAME_RANGE
        if not all(lo <= v <= hi for v in exact):
            raise ValueError(f"format = {fmt}: ширина и высота от {lo} до {hi} px")
        return exact[0] / exact[1]
    m = re.fullmatch(r"(\d+(?:\.\d+)?)\s*:\s*(\d+(?:\.\d+)?)", fmt)
    if not m or float(m[1]) <= 0 or float(m[2]) <= 0:
        raise ValueError(f"format = {fmt}: нужно square, full, соотношение вроде 4:3 или размер вроде 1200x800")
    return float(m[1]) / float(m[2])


def side_of(size):
    return SIZES[size] if size in SIZES else int(size)


def parse_size(value):
    size = str(value).strip().lower()
    lo, hi = SIDE_RANGE
    if size in SIZES:
        return size
    if size.isdigit() and lo <= int(size) <= hi:
        return str(int(size))
    raise ValueError(f"size = {size}: можно {', '.join(SIZES)} или число от {lo} до {hi}")


def parse_config(raw):
    key, hud, dark = _key(raw, "hotkey"), _key(raw, "hud_key"), _key(raw, "dark_key")
    if key in (hud, dark):
        raise ValueError(f"hotkey = {key} совпадает с клавишей игры, которую программа жмёт сама")
    fmt = raw["format"].strip().lower()
    ratio = ratio_of(fmt)
    exact = exact_of(fmt)
    if exact:
        fmt = f"{exact[0]}x{exact[1]}"
    size = parse_size(raw["size"])
    file = raw["file"].strip().lower()
    if file not in FILE_TYPES:
        raise ValueError(f"file = {file}: можно {', '.join(FILE_TYPES)}")
    pos = raw["chat_pos"].strip().lower()
    if pos not in CHAT_POSITIONS:
        raise ValueError(f"chat_pos = {pos}: можно {', '.join(CHAT_POSITIONS)}")
    source = raw["source"].strip().lower()
    if source not in SOURCES:
        raise ValueError(f"source = {source}: можно {', '.join(SOURCES)}")
    kinds = {k.lower(): k for k in chat.KINDS}
    keep = [k.strip().lower() for k in raw["keep"].split(",") if k.strip()]
    bad = [k for k in keep if k not in kinds]
    if bad:
        raise ValueError(f"keep = {', '.join(bad)}: таких строк нет, можно {', '.join(chat.KINDS)}")
    return {
        "key": key,
        "vk": KEYS[key],
        "auto": _bool(raw, "auto"),
        "hud_key": hud,
        "dark_key": dark,
        "hud_delay": _num(raw, "hud_delay_ms", int, 0, 3000) / 1000,
        "out": Path(raw["output"].strip()).expanduser(),
        "format": fmt,
        "ratio": ratio,
        "size": size,
        "file": file,
        "quality": _num(raw, "quality", int, 10, 100),
        "chat_pos": pos,
        "margin": _num(raw, "margin", int, 0, 400),
        "text_scale": _num(raw, "text_scale", float, 0.5, 3),
        "outline": _num(raw, "outline", int, 0, 10),
        "keep": tuple(kinds[k] for k in keep),
        "sound": _bool(raw, "sound"),
        "hide_names": _bool(raw, "hide_names"),
        "chatlog": _bool(raw, "chatlog"),
        "source": source,
        "tray": _bool(raw, "tray"),
        "tray_hint": _bool(raw, "tray_hint"),
    }


def load_config():
    raw = read_raw()
    cfg = parse_config(raw)
    if not CONFIG_PATH.exists():
        write_raw(raw)
    return raw, cfg


def new_edit(cfg, rows):
    return {
        "keep": [bool(r["keep"]) for r in rows],
        "format": cfg["format"],
        "zoom": 1.0,
        "center": [0.5, 0.5],
        "pos": cfg["chat_pos"],
        "breaks": [],
        "places": [],
        "hidden": spans_of(rows, "hide"),
        "dropped": spans_of(rows, "drop"),
        "overlays": [],
        "join": None,
        "scene": None,
        "size": cfg["size"],
        "file": cfg["file"],
        "quality": cfg["quality"],
        "text_scale": cfg["text_scale"],
        "outline": cfg["outline"],
        "margin": cfg["margin"],
    }


def apply_keep(rows, edit):
    if len(edit["keep"]) == len(rows):
        for r, k in zip(rows, edit["keep"]):
            r["keep"] = k
    else:
        edit["keep"] = [bool(r["keep"]) for r in rows]
    edit["breaks"] = cuts(rows, edit)
    for key, field in MARKS:
        spans = {}
        for i, a, b in edit.get(field, []):
            if 0 <= i < len(rows):
                spans.setdefault(int(i), []).append((int(a), int(b)))
        for i, r in enumerate(rows):
            r[key] = spans.get(i, [])
        edit[field] = spans_of(rows, key)


def spans_of(rows, key):
    return [[i, int(a), int(b)] for i, r in enumerate(rows) for a, b in r.get(key, [])]


def auto_hide(rows, only_new=False):
    for r, spans in zip(rows, chat.nick_spans(rows)):
        if not only_new or "hide" not in r:
            r["hide"] = spans


def cuts(rows, edit):
    return sorted({int(i) for i in edit.get("breaks", []) if 0 < int(i) < len(rows)})


def corner_of(pos):
    if isinstance(pos, str):
        return pos if pos in SPARE_PLACES else "top-left"
    x, y = pos
    v = y if y in ("top", "bottom") else "top" if y < 0.5 else "bottom"
    h = x if x in ("left", "right") else "left" if x < 0.5 else "right"
    return f"{v}-{h}"


def places(edit, count):
    first, extra = edit["pos"], list(edit.get("places", []))
    corner = corner_of(first)
    spare = SPARE_PLACES[corner]
    order = list(spare) + [c for c in CHAT_POSITIONS if c != corner and c not in spare] + [corner]
    while len(extra) < count - 1:
        extra.append(order[len(extra) % len(order)])
    return [first] + extra[:count - 1]


def parts(rows, edit):
    bounds = [0] + cuts(rows, edit) + [len(rows)]
    spans = list(zip(bounds, bounds[1:]))
    return [(rows[a:b], pos) for (a, b), pos in zip(spans, places(edit, len(spans)))]


def plan(bg, edit, width=None):
    H, W = bg.shape[:2]
    rect = chat.frame_rect(W, H, ratio_of(edit["format"]), edit["zoom"], edit["center"])
    cw, ch = rect[2] - rect[0], rect[3] - rect[1]
    join = edit.get("join")
    edge = join["side"] if join and join.get("side") in JOIN_SIDES else None
    wide = edge in ("left", "right")
    if width:
        bw = max(1, round(width / (1 + join["size"]) if wide else width))
        base = (bw, max(1, round(bw * ch / cw)))
    else:
        short = min(cw, ch)
        exact = exact_of(edit["format"])
        side = min(exact) if exact else side_of(edit["size"]) or short
        f = side / short
        base = exact or (max(1, round(cw * f)), max(1, round(ch * f)))
    side = min(base)
    k = side / REFERENCE_SIDE
    ext, fade = join_sizes(join, base[0] if wide else base[1]) if edge else (0, 0)
    size = (base[0] + ext, base[1]) if wide else (base[0], base[1] + ext)
    box = {"left": (0, 0, ext, base[1]), "right": (base[0], 0, base[0] + ext, base[1]),
           "top": (0, 0, base[0], ext), "bottom": (0, base[1], base[0], base[1] + ext)}.get(edge)
    return {
        "rect": rect,
        "base": base,
        "size": size,
        "at": (ext if edge == "left" else 0, ext if edge == "top" else 0),
        "ext_box": box,
        "outline": max(1, round(edit["outline"] * k)) if edit["outline"] else 0,
        "margin": round(edit["margin"] * k),
        "scale": edit["text_scale"] * side / min(H, W),
    }


@lru_cache(maxsize=16)
def _overlay(path, stamp, mode):
    with Image.open(path) as im:
        return im.convert(mode)


def overlay_image(path, mode="RGBA"):
    return _overlay(str(path), path.stat().st_mtime_ns, mode)


def add_overlay(out, name, image):
    src = out / "src"
    src.mkdir(parents=True, exist_ok=True)
    taken = {int(m[1]) for p in src.glob(f"{name}_ov*.*") if (m := re.search(r"_ov(\d+)$", p.stem))}
    image = image.convert("RGBA")
    image.thumbnail((2560, 2560), Image.LANCZOS)
    sticker = image.getchannel("A").getextrema()[0] < 255
    file = f"{name}_ov{max(taken, default=0) + 1}.{'png' if sticker else 'jpg'}"
    if sticker:
        image.save(src / file, compress_level=3)
    else:
        image.convert("RGB").save(src / file, quality=95)
    return {"file": file, "x": 0.7 if sticker else 0.72, "y": 0.68, "w": 0.4 if sticker else 0.6,
            "crop": [0.0, 0.0, 1.0, 1.0], "cut": "free", "soft": 0.0 if sticker else 0.4, "alpha": 1.0}


def fit_field(ov, p, src):
    W, H = p["size"]
    l, t, r, b = p["ext_box"]
    if r - l == W:
        lap = round((b - t) * 0.5)
        t, b = (t, b + lap) if t == 0 else (t - lap, b)
    else:
        lap = round((r - l) * 0.5)
        l, r = (l, r + lap) if l == 0 else (l - lap, r)
    w, h = r - l, b - t
    ov.update(crop=crop_for(src, w / h), cut="free", w=round(w / W, 4), x=round((l + r) / 2 / W, 4),
              y=round((t + b) / 2 / H, 4), soft=round(min(1.0, 2 * lap / min(w, h)), 3))
    return ov


def join_sizes(join, along):
    ext = max(1, round(join["size"] * along))
    return ext, min(round(join["fade"] * min(ext, along / 2)), along)


def cover_box(src, size, cx=0.5, cy=0.5):
    SW, SH = src
    w, h = size
    s = min(SW / w, SH / h)
    cw, ch = w * s, h * s
    x0 = min(max(cx * SW - cw / 2, 0), SW - cw)
    y0 = min(max(cy * SH - ch / 2, 0), SH - ch)
    return x0, y0, x0 + cw, y0 + ch


def join_canvas(frame, join):
    op = JOIN_SIDES[join["side"]]
    base = frame if op is None else frame.transpose(op)
    bw, bh = base.size
    ext, fade = join_sizes(join, bw)
    pw = ext + fade
    small = base.transpose(Image.Transpose.FLIP_LEFT_RIGHT).resize(
        (max(1, bw // 8), max(1, bh // 8)), Image.BILINEAR, reducing_gap=2.0)
    soft = small.filter(ImageFilter.GaussianBlur(max(2.0, min(small.size) * 0.04)))
    cover = np.asarray(soft.resize((pw, bh), Image.BICUBIC, box=cover_box(soft.size, (pw, bh), 0.0, 0.5)))
    dim = 1 - 0.55 * np.clip((np.arange(pw, dtype=np.float32) - fade) / max(ext, 1), 0, 1) ** 1.5
    cover = (cover * dim[None, :, None]).astype(np.uint8)
    canvas = np.empty((bh, bw + ext, 3), np.uint8)
    canvas[:, :bw] = np.asarray(base)
    canvas[:, bw:] = cover[:, fade:]
    if fade:
        a = ramp(fade)[None, :, None]
        under = canvas[:, bw - fade:bw].astype(np.float32)
        canvas[:, bw - fade:bw] = np.clip((under + (cover[:, :fade] - under) * a).round(), 0, 255).astype(np.uint8)
    out = Image.fromarray(canvas)
    return out if op is None else out.transpose(op)


def jpeg_pass(arr, quality):
    buf = io.BytesIO()
    Image.fromarray(arr).save(buf, "JPEG", quality=quality, subsampling=2)
    return np.asarray(Image.open(buf).convert("RGB"))


def lock_ratio(cut):
    exact = exact_of(cut)
    if exact:
        return exact[0] / exact[1] if exact[1] else None
    m = re.fullmatch(r"(\d+):(\d+)", str(cut))
    return int(m[1]) / int(m[2]) if m and int(m[2]) else None


def crop_for(size, ratio, within=(0.0, 0.0, 1.0, 1.0)):
    W, H = size
    l, t, r, b = within
    rw, rh = (r - l) * W, (b - t) * H
    if ratio is None:
        return [0.0, 0.0, 1.0, 1.0]
    cw, ch = (rw, rw / ratio) if rw / rh < ratio else (rh * ratio, rh)
    cx, cy = (l + r) / 2 * W, (t + b) / 2 * H
    return [round((cx - cw / 2) / W, 4), round((cy - ch / 2) / H, 4), round((cx + cw / 2) / W, 4),
            round((cy + ch / 2) / H, 4)]


def crop_exact(size, w, h, within):
    W, H = size
    w, h = min(max(1, w), W), min(max(1, h), H)
    l, t, r, b = within
    cx = min(max((l + r) / 2 * W, w / 2), W - w / 2)
    cy = min(max((t + b) / 2 * H, h / 2), H - h / 2)
    return [round((cx - w / 2) / W, 4), round((cy - h / 2) / H, 4), round((cx + w / 2) / W, 4),
            round((cy + h / 2) / H, 4)]


def overlay_box(ov, out_size, src_size):
    l, t, r, b = ov["crop"]
    cw, ch = max(1.0, (r - l) * src_size[0]), max(1.0, (b - t) * src_size[1])
    w = max(1, round(ov["w"] * out_size[0]))
    h = max(1, round(w * ch / cw))
    return round(ov["x"] * out_size[0] - w / 2), round(ov["y"] * out_size[1] - h / 2), w, h


def edge_ramp(n, f, near=True, far=True):
    i = np.arange(n) + 0.5
    d = np.minimum(i if near else np.inf, n - i if far else np.inf)
    t = np.clip(d / f, 0, 1) if f >= 1 else np.ones(n)
    return (t * t * (3 - 2 * t)).astype(np.float32)


def soft_edges(box, out_size):
    x, y, w, h = box
    return x > 0, y > 0, x + w < out_size[0], y + h < out_size[1]


def overlay_piece(src, ov, size):
    l, t, r, b = ov["crop"]
    W, H = src.size
    return src.crop((round(l * W), round(t * H), max(round(l * W) + 1, round(r * W)),
                     max(round(t * H) + 1, round(b * H)))).resize(size, Image.LANCZOS)


def soften(piece, ov, edges):
    soft, alpha = ov.get("soft", 0.0), ov.get("alpha", 1.0)
    if soft <= 0 and alpha >= 1:
        return piece
    w, h = piece.size
    left, top, right, bottom = edges
    f = soft * min(w, h) / 2
    mask = np.outer(edge_ramp(h, f, top, bottom), edge_ramp(w, f, left, right)) * alpha
    out = piece.copy()
    out.putalpha(Image.fromarray(np.clip((np.asarray(piece.getchannel("A"), np.float32) * mask).round(), 0, 255)
                                 .astype(np.uint8)))
    return out


def paste_overlays(frame, overlays, src):
    img = Image.fromarray(frame).convert("RGBA")
    for ov in overlays:
        try:
            source = overlay_image(src / ov["file"])
        except OSError:
            continue
        x, y, w, h = overlay_box(ov, img.size, source.size)
        piece = soften(overlay_piece(source, ov, (w, h)), ov, soft_edges((x, y, w, h), img.size))
        img.paste(piece, (x, y), piece)
    return np.asarray(img.convert("RGB"))


def grain(img):
    h, w, s = img.shape[0], img.shape[1], GRAIN_TILE
    y = np.stack([img[a:a + s, b:b + s] for a in range(0, max(1, h - s + 1), GRAIN_STEP)
                  for b in range(0, max(1, w - s + 1), GRAIN_STEP)]).astype(np.float32) @ LUMA
    pad = np.pad(y, ((0, 0), (3, 3), (3, 3)), mode="reflect")
    row = sum(t * pad[:, :, i:i + y.shape[2]] for i, t in enumerate(GRAIN_TAPS))
    soft = sum(t * row[:, i:i + y.shape[1]] for i, t in enumerate(GRAIN_TAPS))
    d = np.abs(y - soft).ravel()
    return float(np.partition(d, d.size // 2)[d.size // 2] * 1.4826)


def regrain(small, big):
    add = max(0.0, grain(big) ** 2 - grain(small) ** 2) ** 0.5 / GRAIN_GAIN
    if add < GRAIN_MIN:
        return small
    noise = np.asarray(Image.effect_noise(small.shape[1::-1], GRAIN_SPREAD), np.float32)
    noise = (noise - noise.mean()) * (add / GRAIN_SPREAD)
    return np.clip((small + noise[..., None]).round(), 0, 255).astype(np.uint8)


def shrink(img, size):
    out = np.asarray(Image.fromarray(img).resize(size, Image.LANCZOS))
    return regrain(out, img) if size[0] < img.shape[1] else out


def backdrop(bg, edit, src=None, width=None):
    p = plan(bg, edit, width)
    x0, y0, x1, y1 = p["rect"]
    frame = bg[y0:y1, x0:x1]
    if (frame.shape[1], frame.shape[0]) != p["base"]:
        frame = (shrink(frame, p["base"]) if p["base"][0] < frame.shape[1]
                 else np.asarray(Image.fromarray(frame).resize(p["base"], Image.BICUBIC)))
    if p["size"] != p["base"]:
        frame = np.asarray(join_canvas(Image.fromarray(frame), edit["join"]))
    if src is not None and edit.get("overlays"):
        frame = paste_overlays(frame, edit["overlays"], src)
    if width and frame.shape[1] != width:
        frame = shrink(frame, (width, max(1, round(frame.shape[0] * width / frame.shape[1]))))
    return frame, p


def chat_spots(size, layers, spots, pad, margin, boxes=None, span=None):
    W, H = size
    boxes, out = [] if boxes is None else boxes, []
    for layer, pos in zip(layers, spots):
        if layer is None:
            out.append(None)
            continue
        lh, lw = layer.shape[:2]
        left, top = chat.place(W, H, lw, lh, pad, pos, margin)
        if span and not isinstance(pos, str):
            top = min(max(round(pos[1] * H) - pad, span[0] - pad), max(span[1] - lh + pad, span[0] - pad))
            boxes.append((left + pad, top + pad, left + lw - pad, top + lh - pad))
            out.append((left, top))
            continue
        for _ in boxes if isinstance(pos, str) else ():
            hit = [b for b in boxes if b[0] < left + lw - pad and left + pad < b[2] and b[1] < top + lh - pad
                   and top + pad < b[3]]
            if not hit:
                break
            top = (max(b[3] for b in hit) + margin - pad if pos.startswith("top")
                   else min(b[1] for b in hit) - margin - lh + pad)
        top = min(max(top, -pad), max(H - lh + pad, -pad))
        boxes.append((left + pad, top + pad, left + lw - pad, top + lh - pad))
        out.append((left, top))
    return out


def paint_chat(img, rows, edit, p, window=None, boxes=None, found=None):
    y0, y1 = window or (0, img.shape[0])
    groups = parts(rows, edit)
    made = [chat.chat_layer(part, p["outline"], p["scale"], y1 - y0 - 2 * p["margin"]) for part, _ in groups]
    spots = chat_spots((img.shape[1], y1 - y0), [m[0] for m in made], [pos for _, pos in groups], p["outline"] + 2,
                       p["margin"], boxes, (-y0, img.shape[0] - y0) if window else None)
    painted = 0
    for k, ((layer, n, _), spot) in enumerate(zip(made, spots)):
        if layer is not None:
            img, painted = chat.blend(img, layer, spot[0], spot[1] + y0), painted + n
            if found is not None:
                found.append((k, spot[0], spot[1] + y0, layer.shape[1], layer.shape[0]))
    return img, painted


def ramp(n):
    t = (np.arange(n, dtype=np.float32) + 0.5) / n
    return t * t * (3 - 2 * t)


def seam(upper, lower, lap, look):
    w = ramp(lap)[:, None, None]
    a, b = upper[-lap:].astype(np.float32), lower[:lap].astype(np.float32)
    r = look["blur"] * lap / 6
    if r >= 0.5:
        pad = round(3 * r)
        soft = lambda part: np.asarray(Image.fromarray(part).filter(ImageFilter.GaussianBlur(r)), np.float32)
        a += (soft(upper[-lap - pad:])[-lap:] - a) * w
        b += (soft(lower[:lap + pad])[:lap] - b) * (1 - w)
    mix = (a + (b - a) * w) * (1 - look["dark"] * np.sin(np.pi * w))
    return np.clip(mix.round(), 0, 255).astype(np.uint8)


def framed(edit, head):
    return dict(edit, format=head["format"], size=head["size"], join=None)


def laps_of(hs, seams):
    return [round(min(max(s["fade"], 0.0), 0.5) * min(a, b)) for s, a, b in zip(seams, hs, hs[1:])]


def inset(laps, k):
    return (laps[k - 1] // 2 if k else 0), (laps[k] // 2 if k < len(laps) else 0)


def stack(frames, seams):
    hs = [f.shape[0] for f in frames]
    laps = laps_of(hs, seams)
    tops = [0]
    for h, lap in zip(hs, laps):
        tops.append(tops[-1] + h - lap)
    out = np.empty((tops[-1] + hs[-1], frames[0].shape[1], 3), np.uint8)
    for f, top in zip(frames, tops):
        out[top:top + f.shape[0]] = f
    for i, lap in enumerate(laps):
        if lap:
            out[tops[i + 1]:tops[i + 1] + lap] = seam(frames[i], frames[i + 1], lap, seams[i])
    return out, {"tops": tops, "heights": hs, "laps": laps}


def render(bg, rows, edit, src=None, rough=None, scene=None, layout=None):
    if rows and bg.shape[1] != rows[0]["screen_w"]:
        raise ValueError(f"фон шириной {bg.shape[1]} px, а чат снят на экране {rows[0]['screen_w']} px")
    if not scene:
        frame, p = backdrop(bg, edit, src)
        if rough:
            frame = jpeg_pass(frame, rough)
        img, painted = paint_chat(frame, rows, edit, p)
        return (frame.copy() if img is frame else img), painted
    frame, p = backdrop(bg, framed(edit, edit), src)
    frames = []
    for other in scene[0]:
        if other is None:
            frames.append((frame, p, rows, edit))
        else:
            f, q = backdrop(other["bg"], framed(other["edit"], edit), other["out"] / "src", frame.shape[1])
            frames.append((f, q, other["rows"], other["edit"]))
    img, where = stack([f for f, _, _, _ in frames], scene[1])
    if layout is not None:
        layout.update(where)
    if rough:
        img = np.array(jpeg_pass(img, rough))
    painted, spans, taken, chats = 0, [], {}, []
    for k, ((f, _, _, _), top) in enumerate(zip(frames, where["tops"])):
        a, b = inset(where["laps"], k)
        spans.append((top + a, top + f.shape[0] - b))
    homes = scene[2] if len(scene) > 2 else list(range(len(frames)))
    for k, (f, q, r, e) in enumerate(frames):
        found = []
        img, n = paint_chat(img, r, e, q, spans[homes[k]], taken.setdefault(homes[k], []), found)
        chats += [(k,) + box for box in found]
        painted = n if e is edit else painted
    if layout is not None:
        layout.update(chats=chats, spans=spans, names=scene[3] if len(scene) > 3 else None,
                      pads=[q["outline"] + 2 for _, q, _, _ in frames],
                      margins=[q["margin"] for _, q, _, _ in frames])
    return img, painted


def watermark(chat_img):
    H, W = chat_img.shape[:2]
    left, tall = W - round(W * 0.12), round(H * 0.08)
    for top in (0, H - tall):
        box = chat_img[top:top + tall, left:].astype(np.float32)
        ink = box.max(axis=2) > 24
        for y0, y1 in chat._runs(ink.any(axis=1)):
            xs = np.flatnonzero(ink[y0:y1 + 1].any(axis=0))
            if xs[-1] - xs[0] >= W * 0.05 and y1 - y0 < H * 0.04:
                return {"t": box[y0:y1 + 1, xs[0]:xs[-1] + 1], "x": left + int(xs[0])}
    return None


def _corr(a, b):
    a, b = a - a.mean(), b - b.mean()
    return float((a * b).sum() / (np.sqrt((a * a).sum() * (b * b).sum()) + 1e-6))


def _match(region, t):
    return _corr(region.max(axis=2), t.max(axis=2))


def clean_bg(bg, mark, threshold=0.5):
    if mark is None:
        return bg
    t, x = mark["t"], mark["x"]
    h, w = t.shape[:2]
    H = bg.shape[0]
    if x + w > bg.shape[1] or h * 3 > H:
        return bg
    reach = max(h * 4, round(H * 0.1))
    best, at = threshold, None
    strip, tl = chat.lum(bg[:, x:x + w]).astype(np.float32), t.max(axis=2)
    for y in list(range(0, reach)) + list(range(H - reach, H - h + 1)):
        score = _corr(strip[y:y + h], tl)
        if score > best:
            best, at = score, y
    if at is None:
        return bg
    by, bx = max(at - 3, 0), max(x - 3, 0)
    box = bg[by:at + h + 3, bx:x + w + 3].astype(np.float32)
    region = box[at - by:at - by + h, x - bx:x - bx + w]
    lum = t.max(axis=2)
    solid = (lum > 0.7 * 255).any(axis=0)
    text = ~solid
    if text.any():
        tt, seen = t[:, text], region[:, text].copy()
        if _match(seen, tt) > 0.3:
            level = tt.max(axis=2, keepdims=True)
            top = max(float(level.max()), 1.0)
            best_c, best_s = 255.0, None
            for c in np.linspace(top + 1, 255, 28):
                a = np.clip(level / c, 0, 0.9)
                s = abs(_match(np.clip((seen - tt) / (1 - a), 0, 255), tt))
                if best_s is None or s < best_s:
                    best_c, best_s = c, s
            a = np.clip(level / best_c, 0, 0.9)
            fixed = np.where(seen >= 250, seen, np.clip((seen - tt) / (1 - a), 0, 255))
            if abs(_match(fixed, tt)) < 0.3:
                region[:, text] = fixed
    cols = np.flatnonzero(solid)
    if len(cols):
        _fill(box, at - by, at - by + h, x - bx + max(cols[0] - 4, 0), x - bx + min(cols[-1] + 5, w))
    out = bg.copy()
    out[by:by + box.shape[0], bx:bx + box.shape[1]] = np.clip(box.round(), 0, 255).astype(np.uint8)
    return out


def _fill(out, y0, y1, x0, x1, margin=3, steps=150):
    H, W = out.shape[:2]
    py0, py1, px0, px1 = max(y0 - margin, 0), min(y1 + margin, H), max(x0 - margin, 0), min(x1 + margin, W)
    patch = out[py0:py1, px0:px1]
    mask = np.zeros(patch.shape[:2], bool)
    mask[y0 - py0:y1 - py0, x0 - px0:x1 - px0] = True
    patch[mask] = patch[~mask].mean(axis=0)
    for _ in range(steps):
        avg = (np.roll(patch, 1, 0) + np.roll(patch, -1, 0) + np.roll(patch, 1, 1) + np.roll(patch, -1, 1)) / 4
        patch[mask] = avg[mask]


def chat_number(path):
    return int(re.search(r"_chat(\d+)$", path.stem)[1])


def log_path(out, name):
    return out / "src" / f"{name}_log.png"


def screen_chats(out, name):
    chats = [p for p in (out / "src").glob(f"{name}_chat*") if p.suffix in (SRC_CHAT[0], ".png")]
    return sorted(chats, key=chat_number)


def shot_files(out, name):
    src = out / "src"
    bgs = [src / f"{name}_bg{ext}" for ext in (SRC_BG[0], ".png")]
    log = log_path(out, name)
    chats = [log] if log.exists() else screen_chats(out, name)
    return next((p for p in bgs if p.exists()), bgs[0]), chats, src / f"{name}.json"


def shot_image(out, name):
    paths = [out / f"{name}.{ext}" for ext in FILE_TYPES]
    return next((p for p in paths if p.exists()), paths[0])


def list_shots(out):
    if not out.is_dir():
        return []
    shots = {p.stem: p for p in out.glob("SS_*.*") if p.suffix[1:].lower() in FILE_TYPES}

    def taken(name):
        m = re.match(r"SS_(\d{4}-\d\d-\d\d_\d\d-\d\d-\d\d)", name)
        return m[1] if m else datetime.fromtimestamp(shots[name].stat().st_mtime).strftime("%Y-%m-%d_%H-%M-%S")

    return sorted(shots, key=lambda n: (taken(n), n), reverse=True)


def src_size(out):
    files = [p for p in (out / "src").glob("SS_*") if p.is_file()]
    return sum(p.stat().st_size for p in files), sum("_bg." in p.name for p in files)


def clear_src(out):
    with FILES:
        for p in (out / "src").glob("SS_*"):
            try:
                p.unlink()
            except OSError:
                pass


def read_image(path):
    with Image.open(path) as im:
        return np.asarray(im.convert("RGB"))


def load_rows(out, name, cfg):
    _, chat_paths, meta = shot_files(out, name)
    rows, mark = [], None
    for p in chat_paths:
        img = read_image(p)
        mark = mark or watermark(img)
        rows = chat.merge(rows, chat.classify(chat.extract_rows(img), cfg["keep"]))
    edit = new_edit(cfg, rows)
    legacy = not meta.exists()
    if not legacy:
        try:
            edit.update(json.loads(meta.read_text(encoding="utf-8")))
        except (ValueError, OSError):
            pass
    apply_keep(rows, edit)
    return rows, edit, mark, legacy


def load_shot(out, name, cfg):
    bg_path, chat_paths, _ = shot_files(out, name)
    if not bg_path.exists() or not chat_paths:
        return None
    rows, edit, mark, legacy = load_rows(out, name, cfg)
    if mark is None and chat_paths[0] == log_path(out, name):
        mark = recent_mark(out)
    return {"name": name, "out": out, "bg": clean_bg(read_image(bg_path), mark), "rows": rows, "edit": edit,
            "legacy": legacy, "cfg": cfg}


def shot_time(name):
    try:
        return datetime.strptime(name[3:22], "%Y-%m-%d_%H-%M-%S")
    except (ValueError, TypeError):
        return None


def hex_color(text):
    nums = re.findall(r"\d+", text)
    if text.startswith("#") or len(nums) < 3:
        return text if re.fullmatch(r"#[0-9a-fA-F]{6}", text) else LOG_TEXT
    return "#" + "".join(f"{min(int(v), 255):02x}" for v in nums[:3])


def guess_parts(text):
    color = next((c for mark, c in LOG_GUESS if text.startswith(mark)), LOG_TEXT)
    return [[text, color]]


def log_entry(line, plain):
    if plain:
        m = re.match(r"\[(\d\d:\d\d:\d\d)\] (.*)", line)
        return (m[1], guess_parts(m[2])) if m and m[2].strip() else None
    try:
        item = json.loads(line)
        parts = [[str(t), hex_color(str(c))] for t, c in item["parts"] if str(t)]
        return (item["time"], parts) if parts else None
    except (ValueError, KeyError, TypeError):
        return None


def read_log(out, at, span=LOG_SPAN_S):
    start, end, lines = at - timedelta(seconds=span), at + timedelta(seconds=span), []
    for day in sorted({start.date(), end.date()}):
        base = out / "chatlog" / f"{day:%Y-%m-%d}"
        path = next((p for p in (base.with_suffix(".jsonl"), base.with_suffix(".txt")) if p.exists()), None)
        if path is None:
            continue
        try:
            text = path.read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue
        for line in text.splitlines():
            entry = log_entry(line, path.suffix == ".txt")
            if entry is None:
                continue
            when = datetime.combine(day, datetime.strptime(entry[0], "%H:%M:%S").time())
            if start <= when <= end:
                lines.append((when, entry[1]))
    return lines


def log_who(parts):
    text = "".join(t for t, _ in parts).strip()
    m = LOG_SAY.match(text)
    if m:
        return chat.SPEECH, m["who"].strip(), (m["to"] or "").strip() or None
    m = re.match(r"Вы сказали (.{1,40}?) шепотом:", text)
    if m:
        return chat.SPEECH, m[1], m[1]
    if text.startswith("(("):
        return chat.OOC, None, None
    pink =any(c.lower() == LOG_GUESS[0][1] for _, c in parts)
    words = text.lstrip("*> ").split()
    if text.startswith("* "):
        return chat.ACTION, " ".join(words[:2]) or None, None
    if text.startswith(">"):
        return (chat.AME, " ".join(words[:2]) or None, None) if pink else (chat.SYSTEM, None, None)
    m = re.search(r"\*([^*()]{3,40})\)?\s*$", text)
    if pink and m:
        return chat.ACTION, m[1].strip(), None
    return chat.SYSTEM, None, None


def log_chunks(lines, gap=LOG_GAP_S):
    return [k for k in range(len(lines)) if not k or (lines[k][0] - lines[k - 1][0]).total_seconds() > gap]


def log_key(when, parts):
    return f"{when:{LOG_STAMP}}", "".join(text for text, _ in parts)


def picked_log(edit):
    try:
        return [(datetime.strptime(e["at"], LOG_STAMP), [[str(t), hex_color(str(c))] for t, c in e["parts"]])
                for e in edit.get("log") or []]
    except (ValueError, KeyError, TypeError):
        return []


def log_rows(lines, measure, limit):
    rows = []
    for when, parts in lines:
        row, x = [], 0.0
        words = [(w, c) for text, c in parts for w in re.findall(r"\S+\s*|\s+", text)]
        while words and not words[0][0].strip():
            words.pop(0)
        for word, color in words:
            if x and x + measure(word.rstrip()) > limit:
                rows.append((when, row))
                row, x = [], 0.0
                word = word.lstrip()
                if not word:
                    continue
            if row and row[-1][2] == color:
                row[-1][1] += word
            else:
                row.append([x, word, color])
            x += measure(word)
        if row:
            rows.append((when, row))
    return rows


def log_frame(lines, size):
    W, H = size
    font = ImageFont.truetype(LOG_FONT, max(8, round(LOG_SIZE * H)))
    pitch, left = LOG_PITCH * H, round(LOG_LEFT * H)
    rows = log_rows(lines, font.getlength, LOG_WIDTH * W)
    top, ascent = round(pitch), font.getmetrics()[0]
    img = Image.new("RGB", (W, max(H, round(2 * top + pitch * len(rows)))))
    d = ImageDraw.Draw(img)
    for k, (_, row) in enumerate(rows):
        base = top + round(k * pitch) + ascent
        for x, text, color in row:
            d.text((left + x, base), text.rstrip(), font=font, fill=color, anchor="ls")
    return np.asarray(img)


_marks = {}


def recent_mark(out):
    chats = sorted((out / "src").glob("SS_*_chat*"), key=stamp)[-6:]
    for p in reversed(chats):
        if p not in _marks:
            try:
                _marks[p] = watermark(read_image(p))
            except OSError:
                _marks[p] = None
        if _marks[p]:
            return _marks[p]
    return None


def adopt(shot, rows, cfg):
    if cfg["hide_names"]:
        auto_hide(rows)
    shot["rows"] = rows
    shot["edit"].update(keep=[bool(r["keep"]) for r in rows], breaks=[], hidden=spans_of(rows, "hide"),
                        dropped=spans_of(rows, "drop"))


def use_log(shot, cfg, lines):
    frame = log_frame(lines, shot["bg"].shape[1::-1])
    path = log_path(shot["out"], shot["name"])
    with FILES:
        path.parent.mkdir(parents=True, exist_ok=True)
        save(frame, path)
    rows = chat.classify(chat.extract_rows(frame), cfg["keep"])
    for r in rows:
        r["keep"] = True
    adopt(shot, rows, cfg)
    shot["edit"]["log"] = [{"at": log_key(when, parts)[0], "parts": parts} for when, parts in lines]
    return len(rows)


def use_screen(shot, cfg):
    out, name = shot["out"], shot["name"]
    with FILES:
        log_path(out, name).unlink(missing_ok=True)
    rows = []
    for p in screen_chats(out, name):
        rows = chat.merge(rows, chat.classify(chat.extract_rows(read_image(p)), cfg["keep"]))
    adopt(shot, rows, cfg)
    return len(rows)


def stamp(path):
    try:
        return path.stat().st_mtime_ns
    except OSError:
        return 0


def frame_shot(out, name, cfg):
    bg, chats, meta = shot_files(out, name)
    key = (str(out), name, stamp(meta), stamp(bg), len(chats))
    with FRAMES:
        if key not in _frames:
            if len(_frames) >= SCENE_MAX:
                _frames.pop(next(iter(_frames)))
            try:
                _frames[key] = load_shot(out, name, cfg)
            except (OSError, ValueError):
                _frames[key] = None
        return _frames[key]


def scene_of(shot):
    scene, name, cfg = shot["edit"].get("scene"), shot.get("name"), shot.get("cfg")
    if not scene or name not in scene.get("shots", ()) or cfg is None:
        return None
    frames, seams, given, ready, names = [], [], scene.get("seams") or [], shot.get("members") or {}, []
    for k, n in enumerate(scene["shots"]):
        other = None if n == name else ready.get(n) or frame_shot(shot["out"], n, cfg)
        if n != name and other is None:
            continue
        if frames:
            seams.append(dict(SEAM, **given[k - 1]) if k - 1 < len(given) else dict(SEAM))
        frames.append(other)
        names.append(n)
    homes = [names.index(h) if h in names else k
             for k, h in enumerate((f or shot)["edit"].get("home") for f in frames)]
    return (frames, seams, homes, names) if len(frames) > 1 else None


def repeats(shots):
    seen, out = [], []
    for shot in shots:
        rows = shot["rows"] if shot else []
        out.append([i for i, r in enumerate(rows) if r["keep"] and any(chat.same_row(r, s) for s in seen)])
        seen += [r for i, r in enumerate(rows) if r["keep"] and i not in out[-1]]
    return out


def scenes_with(out, name):
    heads = []
    for meta in (out / "src").glob("SS_*.json"):
        try:
            text = meta.read_text(encoding="utf-8")
            if meta.stem != name and name in text and name in (json.loads(text).get("scene") or {})["shots"]:
                heads.append(meta.stem)
        except (OSError, ValueError, KeyError, TypeError):
            pass
    return heads


def render_shot(shot, rough=None, layout=None):
    return render(shot["bg"], shot["rows"], shot["edit"], shot["out"] / "src", rough, scene_of(shot), layout)


def donors(out, name, names, limit=12):
    at = names.index(name) if name in names else 0
    near = sorted((k for k in range(len(names)) if k != at), key=lambda k: abs(k - at))
    found = [k for k in near if shot_files(out, names[k])[1]][:limit]
    return [names[k] for k in sorted(found)]


def carry_chat(shot, donor, cfg):
    out, name, rows, edit = shot["out"], shot["name"], shot["rows"], shot["edit"]
    if log_path(out, name).exists():
        raise ValueError("чат этой СС взят из чатлога, добавь строки оттуда")
    _, files, _ = shot_files(out, donor)
    if not files:
        raise ValueError("у этой СС нет исходных кадров чата")
    theirs = load_rows(out, donor, cfg)[0]
    if theirs and rows and theirs[0]["screen_w"] != rows[0]["screen_w"]:
        raise ValueError("та СС снята при другом разрешении экрана")
    merged = rows
    for src in files:
        merged = chat.merge(merged, chat.classify(chat.extract_rows(read_image(src)), cfg["keep"]))
    if len(merged) == len(rows):
        return 0
    first = max((chat_number(p) for p in shot_files(out, name)[1]), default=0) + 1
    with FILES:
        for k, src in enumerate(files):
            (out / "src" / f"{name}_chat{first + k}{src.suffix}").write_bytes(src.read_bytes())
    cut = [rows[i] for i in cuts(rows, edit)]
    old = {id(r) for r in rows}
    for r in merged:
        twin = None if id(r) in old else next((t for t in theirs if chat.same_row(t, r)), None)
        if twin:
            r.update(keep=twin["keep"], hide=list(twin.get("hide", [])), drop=list(twin.get("drop", [])))
    where = {id(r): i for i, r in enumerate(merged)}
    shot["rows"] = merged
    edit["keep"] = [bool(r["keep"]) for r in merged]
    edit["breaks"] = [where[id(r)] for r in cut]
    for key, field in MARKS:
        edit[field] = spans_of(merged, key)
    return len(merged) - len(rows)


def encoded(shot, layout=None):
    edit = shot["edit"]
    file, params, rough = edit["file"], dict(FILE_TYPES[edit["file"]]), None
    if file == "jpg":
        quality = int(edit.get("quality", TEXT_QUALITY))
        params["quality"] = max(quality, TEXT_QUALITY)
        rough = quality if quality < TEXT_QUALITY else None
    img, painted = render_shot(shot, rough, layout)
    buf = io.BytesIO()
    Image.fromarray(img).save(buf, "JPEG" if file == "jpg" else "PNG", **params)
    return img, painted, buf.getvalue()


def decoded(data):
    return np.asarray(Image.open(io.BytesIO(data)).convert("RGB"))


def write_image(out, name, file, data):
    (out / f"{name}.{file}").write_bytes(data)
    for other in FILE_TYPES.keys() - {file}:
        (out / f"{name}.{other}").unlink(missing_ok=True)


def save_shot(shot, heads=True):
    img, painted, data = encoded(shot)
    out, name, file = shot["out"], shot["name"], shot["edit"]["file"]
    _, _, meta = shot_files(out, name)
    with FILES:
        meta.parent.mkdir(parents=True, exist_ok=True)
        write_image(out, name, file, data)
        meta.write_text(json.dumps(shot["edit"], ensure_ascii=False), encoding="utf-8")
    if heads:
        refresh_heads(out, [name], shot.get("cfg"))
    return img, painted


def refresh_heads(out, names, cfg, skip=()):
    heads = sorted({h for n in names for h in scenes_with(out, n)} - set(skip)) if cfg else []
    for head in heads:
        try:
            whole = load_shot(out, head, cfg)
            if whole:
                data = encoded(whole)[2]
                with FILES:
                    write_image(out, head, whole["edit"]["file"], data)
        except (OSError, ValueError) as e:
            log(f"Сцена {head} не обновилась: {e}", "fail")
    return heads


def copy_image(arr):
    buf = io.BytesIO()
    Image.fromarray(arr).save(buf, "BMP")
    data = buf.getvalue()[14:]
    handle = kernel32.GlobalAlloc(0x0002, len(data))
    if not handle:
        raise OSError("не хватило памяти для буфера обмена")
    ptr = kernel32.GlobalLock(handle)
    ctypes.memmove(ptr, data, len(data))
    kernel32.GlobalUnlock(handle)
    for _ in range(10):
        if user32.OpenClipboard(None):
            break
        time.sleep(0.05)
    else:
        kernel32.GlobalFree(handle)
        raise OSError("буфер обмена занят другой программой")
    try:
        user32.EmptyClipboard()
        if not user32.SetClipboardData(8, handle):
            kernel32.GlobalFree(handle)
            raise OSError(f"Windows не принял картинку: {ctypes.WinError(ctypes.get_last_error())}")
    finally:
        user32.CloseClipboard()


def sample_shot(cfg):
    out = cfg["out"]
    for name in list_shots(out):
        shot = load_shot(out, name, cfg)
        if shot:
            return shot
    shot = read_image(RES_DIR / "samples" / "example_chat.png")
    rows = chat.classify(chat.extract_rows(shot), cfg["keep"])
    bg = clean_bg(read_image(RES_DIR / "samples" / "example_bg.webp"), watermark(shot))
    return {"name": None, "out": out, "bg": bg, "rows": rows, "edit": new_edit(cfg, rows), "cfg": cfg}


class Session:
    def __init__(self):
        self.name = datetime.now().strftime("SS_%Y-%m-%d_%H-%M-%S")
        self.bg = None
        self.rows = []
        self.chats = 0
        self.mark = None


def grab():
    return np.asarray(ImageGrab.grab().convert("RGB"))


def tap(key):
    vk = KEYS[key]
    flags = KEYEVENTF_SCANCODE | (KEYEVENTF_EXTENDEDKEY if vk in EXTENDED_KEYS else 0)
    scan = user32.MapVirtualKeyW(vk, 0)
    for up in (0, KEYEVENTF_KEYUP):
        inp = INPUT(type=INPUT_KEYBOARD, u=_INPUTUNION(ki=KEYBDINPUT(wScan=scan, dwFlags=flags | up)))
        if user32.SendInput(1, ctypes.byref(inp), ctypes.sizeof(INPUT)) != 1:
            raise OSError(f"Windows не дал нажать {key}: {ctypes.WinError(ctypes.get_last_error())}")
        time.sleep(KEY_HOLD_S)


def save(arr, path, **params):
    Image.fromarray(arr).save(path, **params)


def save_src(arr, cfg, stem, kind):
    path = cfg["out"] / "src"
    path.mkdir(parents=True, exist_ok=True)
    ext, params = kind
    save(arr, path / f"{stem}{ext}", **params)


def explain(e, cfg):
    blocked = isinstance(e, OSError) and e.filename and Path(e.filename).is_relative_to(cfg["out"])
    if not blocked:
        return f"Не получилось: {e}"
    return (f"Windows не даёт записать в папку {cfg['out']}. Обычно её защищает «Контролируемый доступ к папкам» "
            "в Защитнике Windows. Выбери в настройках другую папку, например D:\\Snapline, "
            "или разреши snapline.exe в Защитнике.")


def version_key(version):
    return tuple(int(n) for n in re.findall(r"\d+", version))


def final_url(url, timeout_ms=5000):
    net = ctypes.WinDLL("wininet", use_last_error=True)
    net.InternetOpenW.argtypes = [wintypes.LPCWSTR, wintypes.DWORD, wintypes.LPCWSTR, wintypes.LPCWSTR, wintypes.DWORD]
    net.InternetOpenW.restype = ctypes.c_void_p
    net.InternetOpenUrlW.argtypes = [ctypes.c_void_p, wintypes.LPCWSTR, wintypes.LPCWSTR, wintypes.DWORD,
                                     wintypes.DWORD, ctypes.c_size_t]
    net.InternetOpenUrlW.restype = ctypes.c_void_p
    net.InternetSetOptionW.argtypes = [ctypes.c_void_p, wintypes.DWORD, ctypes.c_void_p, wintypes.DWORD]
    net.InternetQueryOptionW.argtypes = [ctypes.c_void_p, wintypes.DWORD, ctypes.c_void_p, ctypes.POINTER(wintypes.DWORD)]
    net.InternetCloseHandle.argtypes = [ctypes.c_void_p]
    session = net.InternetOpenW(f"Snapline/{VERSION}", 0, None, None, 0)
    if not session:
        raise OSError(f"WinINet не открылся: {ctypes.WinError(ctypes.get_last_error())}")
    try:
        limit = wintypes.DWORD(timeout_ms)
        for option in (2, 5, 6):
            net.InternetSetOptionW(session, option, ctypes.byref(limit), ctypes.sizeof(limit))
        fresh = "Cache-Control: no-cache\r\n"
        handle = net.InternetOpenUrlW(session, url, fresh, len(fresh), 0x84080000, 0)
        if not handle:
            raise OSError(f"{url} не открылся: {ctypes.WinError(ctypes.get_last_error())}")
        try:
            buf, size = ctypes.create_unicode_buffer(2048), wintypes.DWORD(2048 * 2)
            if not net.InternetQueryOptionW(handle, 34, buf, ctypes.byref(size)):
                raise OSError(f"адрес ответа не прочитан: {ctypes.WinError(ctypes.get_last_error())}")
            return buf.value
        finally:
            net.InternetCloseHandle(handle)
    finally:
        net.InternetCloseHandle(session)


def latest_release():
    try:
        url = final_url(RELEASES)
    except OSError:
        return None
    m = re.search(r"/releases/tag/v?(\d+(?:\.\d+)*)$", url)
    return (m[1], url) if m and version_key(m[1]) > version_key(VERSION) else None


def check_out(cfg):
    try:
        probe = cfg["out"] / "src" / "SS_write_check.tmp"
        probe.parent.mkdir(parents=True, exist_ok=True)
        probe.write_bytes(b"")
        probe.unlink()
    except OSError as e:
        return explain(e, cfg)
    return None


def handle(img, state, cfg):
    s = state["session"]
    key = cfg["key"]

    if chat.is_chat_shot(img):
        rows = chat.classify(chat.extract_rows(img), cfg["keep"])
        if not rows:
            log("Экран чёрный, но чата на нём нет. Если ты не на F2, значит захват не видит игру: "
                "поставь в настройках графики GTA режим «Оконный без рамки».", "fail")
            return TONE_FAIL
        _, files, meta = shot_files(cfg["out"], s.name)
        if meta.exists():
            s.rows, saved, _, _ = load_rows(cfg["out"], s.name, cfg)
            for i, r in enumerate(s.rows):
                r["cut"] = i in saved["breaks"]
        s.chats += 1
        save_src(img, cfg, f"{s.name}_chat{max(map(chat_number, files), default=0) + 1}", SRC_CHAT)
        s.mark = s.mark or watermark(img)
        s.rows = chat.merge(s.rows, rows)
        log(f"Чат #{s.chats}: строк {len(rows)}, из них в СС {sum(r['keep'] for r in rows)}.")
    else:
        if s.bg is not None:
            s = state["session"] = Session()
        s.bg = img
        save_src(img, cfg, f"{s.name}_bg", SRC_BG)
        log("Фон принят.")

    if s.bg is None:
        log(f"Чат есть. Теперь фон: {cfg['hud_key']}, затем {key}.", "step")
        return TONE_STEP
    if not s.rows:
        log(f"Фон есть. Теперь чат: {cfg['dark_key']}, затем {key}.", "step")
        return TONE_STEP
    if not any(r["keep"] for r in s.rows):
        log("В чате нет реплик для СС: только системные строки и OOC.", "fail")
        return TONE_FAIL
    edit = new_edit(cfg, s.rows)
    old = saved_edit(cfg["out"], s.name)
    edit.update({k: old[k] for k in LAYOUT_KEYS if k in old})
    edit["breaks"] = [i for i, r in enumerate(s.rows) if r.get("cut") and i]
    if cfg["hide_names"]:
        auto_hide(s.rows, only_new=True)
    for key, field in MARKS:
        edit[field] = spans_of(s.rows, key)
    bg = clean_bg(s.bg, s.mark)
    img, painted = save_shot({"name": s.name, "out": cfg["out"], "bg": bg, "rows": s.rows, "edit": edit, "cfg": cfg},
                             heads=bool(old))
    kept = sum(r["keep"] for r in s.rows)
    tail = "" if painted == kept else f" Влезло {painted} строк из {kept}."
    log(f"СС готова: {s.name}.{edit['file']}, {img.shape[1]}×{img.shape[0]}.{tail}", "ok")
    EVENTS.put(("ss", s.name))
    return TONE_SS


def saved_edit(out, name):
    _, _, meta = shot_files(out, name)
    try:
        return json.loads(meta.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}


def wait_dark():
    end = time.perf_counter() + DARK_TIMEOUT_S
    while time.perf_counter() < end:
        if chat.is_chat_shot(grab()):
            time.sleep(DARK_SETTLE_S)
            return grab()
        time.sleep(POLL_S)
    return None


def auto_shot(state, cfg):
    tap(cfg["hud_key"])
    try:
        time.sleep(cfg["hud_delay"])
        bg = grab()
    finally:
        tap(cfg["hud_key"])
    tap(cfg["dark_key"])
    shot = wait_dark()
    if shot is None:
        log(f"Игра не затемнилась по {cfg['dark_key']} за {DARK_TIMEOUT_S:.0f} с. Проверь клавишу затемнения; "
            "если FiveM запущен от администратора, запусти и программу от администратора.", "fail")
        return TONE_FAIL
    tap(cfg["dark_key"])

    s = state["session"] = Session()
    s.bg = bg
    save_src(bg, cfg, f"{s.name}_bg", SRC_BG)
    return handle(shot, state, cfg)


def scene_shot(state, cfg):
    if cfg["auto"]:
        tap(cfg["hud_key"])
        try:
            time.sleep(cfg["hud_delay"])
            bg = grab()
        finally:
            tap(cfg["hud_key"])
    else:
        bg = grab()
    s = state["session"] = Session()
    save_src(bg, cfg, f"{s.name}_bg", SRC_BG)
    out = cfg["out"]
    shot = {"name": s.name, "out": out, "bg": clean_bg(bg, recent_mark(out)), "rows": [], "edit": new_edit(cfg, []),
            "cfg": cfg}
    use_log(shot, cfg, [])
    img, _ = save_shot(shot, heads=False)
    EVENTS.put(("ss", s.name))
    log(f"СС готова: {s.name}.{shot['edit']['file']}, {img.shape[1]}×{img.shape[0]}. Чат пока пустой: строки "
        "выбери в «Строках» из чатлога.", "ok")
    return TONE_SS


def on_hotkey(state, cfg):
    if cfg["source"] == "log":
        return scene_shot(state, cfg)
    img = grab()
    if cfg["auto"] and not chat.is_chat_shot(img):
        return auto_shot(state, cfg)
    return handle(img, state, cfg)


def play(tone, cfg):
    if cfg["sound"]:
        for freq, ms in tone:
            winsound.Beep(freq, ms)


def run(get_cfg, stop, paused=lambda: False):
    state = {"session": Session()}
    was_down = False
    while not stop.is_set():
        cfg = get_cfg()
        down = bool(user32.GetAsyncKeyState(cfg["vk"]) & 0x8000)
        if down and not was_down and not paused():
            EVENTS.put(("busy", True))
            try:
                tone = on_hotkey(state, cfg)
            except (ValueError, OSError) as e:
                log(explain(e, cfg), "fail")
                tone = TONE_FAIL
            except Exception:
                with open(ERROR_LOG, "a", encoding="utf-8") as f:
                    f.write(f"{datetime.now()}\n{traceback.format_exc()}\n")
                log(f"Ошибка программы, подробности в {ERROR_LOG}", "fail")
                tone = TONE_FAIL
            EVENTS.put(("busy", False))
            play(tone, cfg)
        was_down = down
        time.sleep(POLL_S)
