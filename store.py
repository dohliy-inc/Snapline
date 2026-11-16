import io
import json
import re
import threading
from datetime import datetime
from pathlib import Path

import numpy as np
from PIL import Image

import chat
import chatlog
from compose import (
    MARKS, SCENE_MAX, SEAM, apply_keep, auto_hide, cuts, homes_of, new_edit, render, shot_time, spans_of,
)
from config import FILE_TYPES, RES_DIR, log

TEXT_QUALITY = 92
SRC_BG = (".jpg", {"quality": 95, "subsampling": 0})
SRC_CHAT = (".webp", {"lossless": True, "quality": 0, "method": 1})

FILES = threading.Lock()
FRAMES = threading.Lock()
_frames = {}


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
        mark = mark or chat.watermark(img)
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
    return {"name": name, "out": out, "bg": chat.clean_bg(read_image(bg_path), mark), "rows": rows, "edit": edit,
            "legacy": legacy, "cfg": cfg}


_marks = {}


def recent_mark(out):
    chats = sorted((out / "src").glob("SS_*_chat*"), key=stamp)[-6:]
    for p in reversed(chats):
        if p not in _marks:
            try:
                _marks[p] = chat.watermark(read_image(p))
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
    frame = chatlog.log_frame(lines, shot["bg"].shape[1::-1])
    path = log_path(shot["out"], shot["name"])
    with FILES:
        path.parent.mkdir(parents=True, exist_ok=True)
        save(frame, path)
    rows = chat.classify(chat.extract_rows(frame), cfg["keep"])
    for r in rows:
        r["keep"] = True
    adopt(shot, rows, cfg)
    shot["edit"]["log"] = [{"at": chatlog.log_key(when, parts)[0], "parts": parts} for when, parts in lines]
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
    homes = [[names.index(h) if h in names else k for h in homes_of(s["rows"], s["edit"])]
             for k, s in enumerate(f or shot for f in frames)]
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
    return render(shot["bg"], shot["rows"], shot["edit"], shot["out"] / "src", rough, scene_of(shot), layout,
                  shot_time(shot.get("name")))


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
    return rerender(out, heads, cfg)


def rerender(out, heads, cfg):
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


def shot_paths(out, name):
    own = re.compile(rf"{re.escape(name)}(_bg|_chat\d+|_log|_ov\d+)?")
    return ([p for p in out.glob(f"{name}.*") if p.suffix[1:].lower() in FILE_TYPES] +
            [p for p in (out / "src").glob(f"{name}*") if own.fullmatch(p.stem)])


def drop_member(edit, name):
    shots, seams = list(edit["scene"]["shots"]), list(edit["scene"]["seams"])
    k = shots.index(name)
    del shots[k]
    if seams:
        del seams[min(k, len(seams) - 1)]
    edit["scene"] = {**edit["scene"], "shots": shots, "seams": seams} if len(shots) > 1 else None
    return edit


def delete_shot(out, name, cfg, recycle):
    heads = scenes_with(out, name)
    with FILES:
        recycle(shot_paths(out, name))
        for head in heads:
            edit = drop_member(saved_edit(out, head), name)
            shot_files(out, head)[2].write_text(json.dumps(edit, ensure_ascii=False), encoding="utf-8")
    return rerender(out, heads, cfg)


def sample_shot(cfg):
    out = cfg["out"]
    for name in list_shots(out):
        shot = load_shot(out, name, cfg)
        if shot:
            return shot
    shot = read_image(RES_DIR / "samples" / "example_chat.png")
    rows = chat.classify(chat.extract_rows(shot), cfg["keep"])
    bg = chat.clean_bg(read_image(RES_DIR / "samples" / "example_bg.webp"), chat.watermark(shot))
    return {"name": None, "out": out, "bg": bg, "rows": rows, "edit": new_edit(cfg, rows), "cfg": cfg}


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


def check_out(cfg):
    try:
        probe = cfg["out"] / "src" / "SS_write_check.tmp"
        probe.parent.mkdir(parents=True, exist_ok=True)
        probe.write_bytes(b"")
        probe.unlink()
    except OSError as e:
        return explain(e, cfg)
    return None


def saved_edit(out, name):
    _, _, meta = shot_files(out, name)
    try:
        return json.loads(meta.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
