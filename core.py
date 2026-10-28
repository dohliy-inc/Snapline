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
from datetime import datetime
from pathlib import Path

import numpy as np
from PIL import Image, ImageGrab

import chat

VERSION = "1.0"
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
    "chat_pos": "top-left",
    "margin": "24",
    "text_scale": "1.5",
    "outline": "2",
    "keep": "речь, действие",
    "sound": "yes",
}
SIZES = {"native": None, "fhd": 1080, "qhd": 1440, "4k": 2160}
CHAT_POSITIONS = ("top-left", "top-right", "bottom-left", "bottom-right")
LAYOUT_KEYS = ("format", "zoom", "center", "pos", "size", "text_scale", "outline", "margin")
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


def ratio_of(fmt):
    fmt = fmt.strip().lower()
    if fmt == "full":
        return None
    if fmt == "square":
        return 1.0
    m = re.fullmatch(r"(\d+(?:\.\d+)?)\s*:\s*(\d+(?:\.\d+)?)", fmt)
    if not m or float(m[1]) <= 0 or float(m[2]) <= 0:
        raise ValueError(f"format = {fmt}: нужно square, full или соотношение вроде 4:3")
    return float(m[1]) / float(m[2])


def parse_config(raw):
    key, hud, dark = _key(raw, "hotkey"), _key(raw, "hud_key"), _key(raw, "dark_key")
    if key in (hud, dark):
        raise ValueError(f"hotkey = {key} совпадает с клавишей игры, которую программа жмёт сама")
    fmt = raw["format"].strip().lower()
    ratio = ratio_of(fmt)
    size = raw["size"].strip().lower()
    if size not in SIZES:
        raise ValueError(f"size = {size}: можно {', '.join(SIZES)}")
    pos = raw["chat_pos"].strip().lower()
    if pos not in CHAT_POSITIONS:
        raise ValueError(f"chat_pos = {pos}: можно {', '.join(CHAT_POSITIONS)}")
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
        "chat_pos": pos,
        "margin": _num(raw, "margin", int, 0, 400),
        "text_scale": _num(raw, "text_scale", float, 0.5, 3),
        "outline": _num(raw, "outline", int, 0, 10),
        "keep": tuple(kinds[k] for k in keep),
        "sound": _bool(raw, "sound"),
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
        "size": cfg["size"],
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


def plan(bg, edit):
    H, W = bg.shape[:2]
    rect = chat.frame_rect(W, H, ratio_of(edit["format"]), edit["zoom"], edit["center"])
    cw, ch = rect[2] - rect[0], rect[3] - rect[1]
    short = min(cw, ch)
    side = SIZES[edit["size"]] or short
    f = side / short
    k = side / REFERENCE_SIDE
    return {
        "rect": rect,
        "size": (max(1, round(cw * f)), max(1, round(ch * f))),
        "outline": max(1, round(edit["outline"] * k)) if edit["outline"] else 0,
        "margin": round(edit["margin"] * k),
        "scale": edit["text_scale"] * side / min(H, W),
    }


def render(bg, rows, edit):
    if rows and bg.shape[1] != rows[0]["screen_w"]:
        raise ValueError(f"фон шириной {bg.shape[1]} px, а чат снят на экране {rows[0]['screen_w']} px")
    p = plan(bg, edit)
    x0, y0, x1, y1 = p["rect"]
    frame = bg[y0:y1, x0:x1]
    if (frame.shape[1], frame.shape[0]) != p["size"]:
        method = Image.LANCZOS if p["size"][0] < frame.shape[1] else Image.BICUBIC
        frame = np.asarray(Image.fromarray(frame).resize(p["size"], method))
    img, painted, _ = chat.compose(frame, rows, p["outline"], edit["pos"], p["margin"], p["scale"])
    return (frame.copy() if img is None else img), painted


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


def _match(region, t):
    a, b = region.max(axis=2), t.max(axis=2)
    a, b = a - a.mean(), b - b.mean()
    return float((a * b).sum() / (np.sqrt((a * a).sum() * (b * b).sum()) + 1e-6))


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
    for y in list(range(0, reach)) + list(range(H - reach, H - h + 1)):
        score = _match(bg[y:y + h, x:x + w].astype(np.float32), t)
        if score > best:
            best, at = score, y
    if at is None:
        return bg
    out = bg.astype(np.float32)
    region = out[at:at + h, x:x + w]
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
        _fill(out, at, at + h, x + max(cols[0] - 4, 0), x + min(cols[-1] + 5, w))
    return np.clip(out.round(), 0, 255).astype(np.uint8)


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
    return int(re.search(r"_chat(\d+)\.png$", path.name)[1])


def shot_files(out, name):
    src = out / "src"
    return src / f"{name}_bg.png", sorted(src.glob(f"{name}_chat*.png"), key=chat_number), src / f"{name}.json"


def list_shots(out):
    if not out.is_dir():
        return []
    shots = sorted(out.glob("SS_*.png"), key=lambda p: p.stat().st_mtime, reverse=True)
    return [p.stem for p in shots]


def read_image(path):
    with Image.open(path) as im:
        return np.asarray(im.convert("RGB"))


def load_shot(out, name, cfg):
    bg_path, chat_paths, meta = shot_files(out, name)
    if not bg_path.exists() or not chat_paths:
        return None
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
    return {"name": name, "out": out, "bg": clean_bg(read_image(bg_path), mark), "rows": rows, "edit": edit,
            "legacy": legacy}


def save_shot(shot):
    img, painted = render(shot["bg"], shot["rows"], shot["edit"])
    _, _, meta = shot_files(shot["out"], shot["name"])
    with FILES:
        meta.parent.mkdir(parents=True, exist_ok=True)
        save(img, shot["out"] / f"{shot['name']}.png")
        meta.write_text(json.dumps(shot["edit"], ensure_ascii=False), encoding="utf-8")
    return img, painted


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
    return {"name": None, "out": out, "bg": bg, "rows": rows, "edit": new_edit(cfg, rows)}


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


def save(arr, path, fast=False):
    Image.fromarray(arr).save(path, compress_level=1 if fast else 6)


def src_dir(cfg):
    path = cfg["out"] / "src"
    path.mkdir(parents=True, exist_ok=True)
    return path


def handle(img, state, cfg):
    s = state["session"]
    key = cfg["key"]

    if chat.is_chat_shot(img):
        rows = chat.classify(chat.extract_rows(img), cfg["keep"])
        if not rows:
            log("Экран чёрный, но чата на нём нет. Если ты не на F2, значит захват не видит игру: "
                "поставь в настройках графики GTA режим «Оконный без рамки».", "fail")
            return TONE_FAIL
        s.chats += 1
        save(img, src_dir(cfg) / f"{s.name}_chat{s.chats}.png", fast=True)
        s.mark = s.mark or watermark(img)
        s.rows = chat.merge(s.rows, rows)
        log(f"Чат #{s.chats}: строк {len(rows)}, из них в СС {sum(r['keep'] for r in rows)}.")
    else:
        if s.bg is not None:
            s = state["session"] = Session()
        s.bg = img
        save(img, src_dir(cfg) / f"{s.name}_bg.png", fast=True)
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
    _, _, meta = shot_files(cfg["out"], s.name)
    if meta.exists():
        try:
            old = json.loads(meta.read_text(encoding="utf-8"))
            edit.update({k: old[k] for k in LAYOUT_KEYS if k in old})
        except (ValueError, OSError):
            pass
    bg = clean_bg(s.bg, s.mark)
    img, painted = save_shot({"name": s.name, "out": cfg["out"], "bg": bg, "rows": s.rows, "edit": edit})
    kept = sum(r["keep"] for r in s.rows)
    tail = "" if painted == kept else f" Влезло {painted} строк из {kept}."
    log(f"СС готова: {s.name}.png, {img.shape[1]}×{img.shape[0]}.{tail}", "ok")
    EVENTS.put(("ss", s.name))
    return TONE_SS


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
    save(bg, src_dir(cfg) / f"{s.name}_bg.png", fast=True)
    return handle(shot, state, cfg)


def on_hotkey(state, cfg):
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
                log(f"Не получилось: {e}", "fail")
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
