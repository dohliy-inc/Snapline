import io
import re
from datetime import datetime
from functools import lru_cache
from pathlib import Path

import numpy as np
from PIL import Image, ImageFilter

import chat
import styles
from config import CHAT_POSITIONS, exact_of, ratio_of, side_of

REFERENCE_SIDE = 1440

LAYOUT_KEYS = ("format", "zoom", "center", "pos", "places", "size", "file", "quality", "text_scale", "outline",
               "margin", "overlays", "join", "scene", "style", "style_text", "preset", "look", "lut")
LUT_DIR = "luts"
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
MARKS = (("hide", "hidden"), ("drop", "dropped"))

SPARE_PLACES = {"top-left": ("bottom-left", "top-right"), "top-right": ("bottom-right", "top-left"),
                "bottom-left": ("top-left", "bottom-right"), "bottom-right": ("top-right", "bottom-left")}


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
    noise = styles.noise(small.shape[0], small.shape[1], add)
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
    if edit.get("blurs"):
        frame = np.asarray(styles.obscure(Image.fromarray(frame), edit["blurs"]))
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


def lut_of(edit, src):
    name = edit.get("lut")
    if not name or src is None:
        return None
    path = Path(src).parent / LUT_DIR / name
    try:
        return styles.load_lut(str(path), path.stat().st_mtime_ns)
    except (OSError, ValueError):
        return None


def add_lut(out, path):
    path = Path(path)
    data = path.read_bytes()
    styles.read_cube(data.decode("utf-8", errors="replace"))
    folder = Path(out) / LUT_DIR
    folder.mkdir(parents=True, exist_ok=True)
    stem, k = re.sub(r"[^\w.-]+", "_", path.stem)[:60] or "lut", 1
    target = folder / f"{stem}.cube"
    while target.exists() and target.read_bytes() != data:
        k += 1
        target = folder / f"{stem}_{k}.cube"
    if not target.exists():
        target.write_bytes(data)
    return target.name


def styled(frame, edit, when, src=None):
    frame = styles.grade(frame, edit.get("preset"), edit.get("look"), lut_of(edit, src))
    return styles.apply(frame, edit.get("style"), when, edit.get("style_text"))


def render(bg, rows, edit, src=None, rough=None, scene=None, layout=None, when=None):
    if rows and bg.shape[1] != rows[0]["screen_w"]:
        raise ValueError(f"фон шириной {bg.shape[1]} px, а чат снят на экране {rows[0]['screen_w']} px")
    if not scene:
        frame, p = backdrop(bg, edit, src)
        frame, marks = styled(frame, edit, when, src)
        if rough:
            frame = jpeg_pass(frame, rough)
        img, painted = paint_chat(frame, rows, edit, p, boxes=marks)
        return (frame.copy() if img is frame else img), painted
    frame, p = backdrop(bg, framed(edit, edit), src)
    frames, marks = [], []
    for other in scene[0]:
        if other is None:
            f, q, r, e, t = frame, p, rows, edit, when
        else:
            f, q = backdrop(other["bg"], framed(other["edit"], edit), other["out"] / "src", frame.shape[1])
            r, e, t = other["rows"], other["edit"], shot_time(other.get("name"))
        f, b = styled(f, edit, t, src)
        frames.append((f, q, r, e))
        marks.append(b)
    img, where = stack([f for f, _, _, _ in frames], scene[1])
    if layout is not None:
        layout.update(where)
    if rough:
        img = np.array(jpeg_pass(img, rough))
    painted, spans, taken, chats = 0, [], {}, []
    for k, ((f, _, _, _), top) in enumerate(zip(frames, where["tops"])):
        a, b = inset(where["laps"], k)
        spans.append((top + a, top + f.shape[0] - b))
        taken[k] = [(x0, y0 - a, x1, y1 - a) for x0, y0, x1, y1 in marks[k]]
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


def shot_time(name):
    try:
        return datetime.strptime(name[3:22], "%Y-%m-%d_%H-%M-%S")
    except (ValueError, TypeError):
        return None
