import ctypes
import time
import traceback
import winsound
from ctypes import wintypes
from datetime import datetime

import numpy as np
from PIL import ImageGrab

import chat
from compose import LAYOUT_KEYS, MARKS, auto_hide, new_edit, spans_of
from config import ERROR_LOG, EVENTS, KEYS, log
from store import (
    SRC_BG, SRC_CHAT, chat_number, explain, load_rows, recent_mark, save_shot, save_src, saved_edit, shot_files,
    use_log,
)

EXTENDED_KEYS = {0x2D, 0x24, 0x23, 0x21, 0x22}
POLL_S = 0.025
KEY_HOLD_S = 0.04
DARK_TIMEOUT_S = 2.0
DARK_SETTLE_S = 0.06

TONE_STEP = ((1000, 70),)
TONE_SS = ((1000, 70), (1500, 120))
TONE_FAIL = ((300, 450),)

user32 = ctypes.WinDLL("user32", use_last_error=True)


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
        s.mark = s.mark or chat.watermark(img)
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
    bg = chat.clean_bg(s.bg, s.mark)
    img, painted = save_shot({"name": s.name, "out": cfg["out"], "bg": bg, "rows": s.rows, "edit": edit, "cfg": cfg},
                             heads=bool(old))
    kept = sum(r["keep"] for r in s.rows)
    tail = "" if painted == kept else f" Влезло {painted} строк из {kept}."
    log(f"СС готова: {s.name}.{edit['file']}, {img.shape[1]}×{img.shape[0]}.{tail}", "ok")
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
    shot = {"name": s.name, "out": out, "bg": chat.clean_bg(bg, recent_mark(out)), "rows": [],
            "edit": new_edit(cfg, []), "cfg": cfg}
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
