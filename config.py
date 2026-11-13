import configparser
import queue
import re
import sys
from datetime import datetime
from pathlib import Path

import chat

VERSION = "1.4"
RELEASES = "https://github.com/dohliy-inc/Snapline/releases/latest"
APP_DIR = Path(sys.executable if getattr(sys, "frozen", False) else __file__).resolve().parent
RES_DIR = Path(getattr(sys, "_MEIPASS", APP_DIR))
CONFIG_PATH = APP_DIR / "config.ini"
ERROR_LOG = APP_DIR / "error.log"

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
    "tour": "yes",
}
SIZES = {"native": None, "hd": 720, "fhd": 1080, "qhd": 1440, "4k": 2160}
SIDE_RANGE = (360, 4320)
FRAME_RANGE = (200, 7680)
FILE_TYPES = {"jpg": {"quality": 92, "subsampling": 0, "optimize": True, "progressive": True},
              "png": {"compress_level": 6}}
CHAT_POSITIONS = ("top-left", "top-right", "bottom-left", "bottom-right")
SOURCES = ("screen", "log")

KEYS = {f"F{i}": 0x6F + i for i in range(1, 25)}
KEYS.update(PAUSE=0x13, SCROLLLOCK=0x91, INSERT=0x2D, HOME=0x24, END=0x23, PAGEUP=0x21, PAGEDOWN=0x22)

EVENTS = queue.Queue()


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
        "tour": _bool(raw, "tour"),
    }


def load_config():
    raw = read_raw()
    cfg = parse_config(raw)
    if not CONFIG_PATH.exists():
        write_raw(raw)
    return raw, cfg
