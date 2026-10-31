import numpy as np
from PIL import Image

INK = 60
BLACK = 6
CHAT_SHOT_BLACK = 0.9
CHAT_COLUMN = 0.4
CHAT_GAP = 3
WRAP_SHARE = 0.22
WORD_GAP = 0.18
SAME_ROW = 0.08

SPEECH, ACTION, AME, SYSTEM, OOC = "речь", "действие", "над головой", "система", "OOC"
KINDS = (SPEECH, ACTION, AME, SYSTEM, OOC)


def lum(img):
    return np.maximum(np.maximum(img[..., 0], img[..., 1]), img[..., 2])


def is_chat_shot(img):
    return (lum(img) <= BLACK).mean() > CHAT_SHOT_BLACK


def _runs(mask):
    edges = np.flatnonzero(np.diff(np.concatenate(([0], mask.astype(np.int8), [0]))))
    return [(int(a), int(b) - 1) for a, b in zip(edges[::2], edges[1::2])]


def _grow(a, r):
    p = np.pad(a, r)
    out = a.copy()
    for dy in range(2 * r + 1):
        for dx in range(2 * r + 1):
            np.maximum(out, p[dy:dy + a.shape[0], dx:dx + a.shape[1]], out=out)
    return out


def _block(ink):
    lines = _runs(ink.any(axis=1))
    if not lines:
        return [], 0.0
    tall = np.median([b - a + 1 for a, b in lines])
    fused = []
    for a, b in lines:
        if fused and fused[-1][1] - fused[-1][0] + 1 < 0.4 * tall and a - fused[-1][1] <= 3:
            fused[-1] = (fused[-1][0], b)
        else:
            fused.append((a, b))

    block = [fused[0]]
    for a, b in fused[1:]:
        pa, pb = block[-1]
        if a - pb > 3 * (pb - pa + 4):
            break
        block.append((a, b))
    pitch = (float(np.median(np.diff([a for a, _ in block]))) if len(block) > 1
             else 1.3 * (block[0][1] - block[0][0] + 1))
    return block, pitch


def _chat_right(ink, block, pitch):
    cols = _runs(ink[block[0][0]:block[-1][1] + 1].any(axis=0))
    right = cols[0][1]
    for a, b in cols[1:]:
        if a - right > CHAT_GAP * pitch:
            break
        right = b
    return right + 1


def extract_rows(img):
    width = img.shape[1]
    ink = lum(img) > INK
    block, pitch = _block(ink[:, :int(width * CHAT_COLUMN)])
    if not block:
        return []
    right = _chat_right(ink, block, pitch)
    top, bottom = max(0, block[0][0] - round(pitch)), min(len(img), block[-1][1] + round(pitch) + 1)
    rgb = np.zeros((bottom - top, width, 3), np.float32)
    rgb[:, :right] = img[top:bottom, :right]
    shade = lum(rgb)
    ink = shade > INK
    block, pitch = _block(ink)

    rows = []
    for a, b in block:
        rink = ink[a:b + 1]
        dense = rink.sum(axis=1)
        rlum = shade[a:b + 1]
        rows.append({
            "y0": top + a,
            "base": int(np.flatnonzero(dense >= 0.5 * dense.max())[-1]),
            "pitch": pitch,
            "screen_w": width,
            "ink": rink,
            "glyphs": _runs(rink.any(axis=0)),
            "rgb": rgb[a:b + 1],
            "lum": rlum,
            "profile": rlum.sum(axis=0),
        })
    return rows


def _prefix(row):
    pitch, ink, glyphs = row["pitch"], row["ink"], row["glyphs"]
    a, b = glyphs[0]
    g = ink[:, a:b + 1]
    ys = np.flatnonzero(g.any(axis=1))
    h, w = ys[-1] - ys[0] + 1, b - a + 1
    gap = glyphs[1][0] - b - 1 if len(glyphs) > 1 else pitch
    if h > 0.7 * pitch and w < 0.6 * pitch:
        left, right = np.flatnonzero(g[:, 0]) - ys[0], np.flatnonzero(g[:, -1]) - ys[0]
        if len(left) >= 0.8 * h:
            return "["
        if (len(left) and len(right) and left.min() > 0.2 * h and left.max() < 0.8 * h
                and right.min() < 0.2 * h and right.max() > 0.8 * h
                and not ((right > 0.25 * h) & (right < 0.75 * h)).any()):
            return "("
    if h < 0.4 * pitch and ys[-1] - row["base"] < -0.25 * pitch:
        return "*"
    if gap >= 0.15 * pitch and w < 0.65 * pitch:
        left, right = np.flatnonzero(g[:, 0]), np.flatnonzero(g[:, -1])
        mid = (ys[0] + ys[-1]) / 2
        if (len(left) and len(right) and left.min() <= ys[0] + 1 and left.max() >= ys[-1] - 1
                and abs(right.mean() - mid) < 0.15 * pitch and right.max() - right.min() < 0.5 * h):
            return ">"
    return None


def _strong(row, x0):
    lum = row["lum"][:, x0:]
    return row["rgb"][:, x0:][lum > 0.8 * lum.max()]


def _pink(c):
    r, g, b = c
    return b > g + 20 and r > g + 10


def _red(c):
    r, g, b = c
    return r > 150 and g < 0.6 * r and b < 0.6 * r


def _orange_share(px):
    r, g, b = px[:, 0], px[:, 1], px[:, 2]
    return float(((r > 200) & (g > 90) & (g < 170) & (b < 90)).mean())


def classify(rows, keep=(SPEECH, ACTION)):
    prev = None
    for row in rows:
        mark = _prefix(row)
        px = _strong(row, row["glyphs"][0][0])
        body = px.mean(axis=0)
        if mark == ">":
            kind = AME if _pink(body) else SYSTEM
        elif mark == "(":
            kind = OOC
        elif _red(body) or _orange_share(px) > 0.1:
            kind = SYSTEM
        elif mark == "*" or _pink(body):
            kind = ACTION
        else:
            kind = SPEECH
        cont = (mark is None and prev is not None
                and prev["glyphs"][-1][1] >= WRAP_SHARE * row["screen_w"]
                and np.abs(body - prev["body"]).max() < 10)
        if cont:
            kind = prev["kind"]
        row["kind"], row["body"], row["keep"], row["cont"], row["mark"] = kind, body, kind in keep, cont, mark
        prev = row
    return rows


def words(row):
    spans = []
    for a, b in row["glyphs"]:
        if spans and a - spans[-1][1] - 1 < WORD_GAP * row["pitch"]:
            spans[-1] = (spans[-1][0], b)
        else:
            spans.append((a, b))
    return spans


def _star_end(row, a, b):
    pitch, ink = row["pitch"], row["ink"]
    for ga, gb in row["glyphs"]:
        if ga < a or gb > b:
            continue
        ys = np.flatnonzero(ink[:, ga:gb + 1].any(axis=1))
        if len(ys) and ys[-1] - ys[0] + 1 < 0.4 * pitch and ys[-1] - row["base"] < -0.25 * pitch:
            return gb + 1
        return a
    return a


def nick_spans(rows):
    found, start = [], None
    for i, r in enumerate(rows):
        if not r.get("cont"):
            start = r
        w = words(r)
        spans = []
        if not r.get("cont") and len(w) >= 3:
            if r["kind"] == SPEECH:
                spans = w[:2]
            elif r["kind"] == ACTION and r.get("mark") == "*":
                spans = w[1:3]
        last = i + 1 == len(rows) or not rows[i + 1].get("cont")
        if (not spans and last and r["kind"] == ACTION and start is not None and start.get("mark") != "*"
                and len(w) >= 3):
            (a, b), tail = w[-2], w[-1]
            spans = [(_star_end(r, a, b), b), tail]
        found.append([(int(a), int(b)) for a, b in spans if b >= a])
    return found


def _dropped(row):
    gone = {tuple(span) for span in row.get("drop", [])}
    spans = words(row)
    cols = []
    for j, (a, b) in enumerate(spans):
        if (a, b) not in gone:
            continue
        if j + 1 < len(spans):
            cols.append((a, spans[j + 1][0]))
        elif j and spans[j - 1] not in gone:
            cols.append((spans[j - 1][1] + 1, b + 1))
        else:
            cols.append((a, b + 1))
    return cols


def masked(row, preview=False):
    if not row.get("hide") and not row.get("drop"):
        return row["rgb"]
    rgb = row["rgb"].copy()
    color = np.clip(row["body"], 0, 255)
    for a, b in row.get("hide", []):
        ys = np.flatnonzero(row["ink"][:, a:b + 1].any(axis=1))
        rgb[:, a:b + 1] = 0
        if len(ys):
            rgb[ys[0]:row["base"] + 1, a:b + 1] = color
    if preview:
        for a, b in row.get("drop", []):
            rgb[:, a:b + 1] *= 0.3
        return rgb
    keep = np.ones(rgb.shape[1], bool)
    for a, b in _dropped(row):
        keep[a:b] = False
    out = np.zeros_like(rgb)
    out[:, :keep.sum()] = rgb[:, keep]
    return out


def _same(a, b):
    pa, pb = a["profile"], b["profile"]
    return len(pa) == len(pb) and np.abs(pa - pb).sum() / max(pa.sum() + pb.sum(), 1.0) < SAME_ROW


def _overlap(a, b):
    for k in range(min(len(a), len(b)), 0, -1):
        if all(_same(a[len(a) - k + i], b[i]) for i in range(k)):
            return k
    return 0


def merge(rows, new):
    n = len(new)
    if n == 0 or any(all(_same(rows[i + j], new[j]) for j in range(n)) for i in range(len(rows) - n + 1)):
        return rows
    after, before = _overlap(rows, new), _overlap(new, rows)
    return new[:n - before] + rows if before > after else rows + new[after:]


def frame_rect(width, height, ratio=None, zoom=1.0, center=(0.5, 0.5)):
    if ratio is None:
        w, h = width, height
    else:
        w, h = (width, round(width / ratio)) if width / height < ratio else (round(height * ratio), height)
    w, h = max(1, round(w / zoom)), max(1, round(h / zoom))
    x0 = min(max(round(center[0] * width - w / 2), 0), width - w)
    y0 = min(max(round(center[1] * height - h / 2), 0), height - h)
    return x0, y0, x0 + w, y0 + h


def _strip(kept, scale, max_h):
    pitch = kept[0]["pitch"]
    head = max(r["base"] for r in kept)
    slots = []
    for i, r in enumerate(kept):
        y0 = head + round(i * pitch) - r["base"]
        if (y0 + len(r["rgb"])) * scale > max_h and slots:
            break
        slots.append((y0, r))
    h = max(y0 + len(r["rgb"]) for y0, r in slots)
    rgb = np.zeros((h, kept[0]["rgb"].shape[1], 3), np.float32)
    for y0, r in slots:
        np.maximum(rgb[y0:y0 + len(r["rgb"])], masked(r), out=rgb[y0:y0 + len(r["rgb"])])
    ink = rgb.max(axis=2) > 0
    ys, xs = np.flatnonzero(ink.any(axis=1)), np.flatnonzero(ink.any(axis=0))
    rgb = rgb[ys[0]:ys[-1] + 1, xs[0]:xs[-1] + 1]
    if scale != 1:
        img = Image.fromarray(rgb.round().astype(np.uint8))
        img = img.resize((max(1, round(img.width * scale)), max(1, round(img.height * scale))), Image.LANCZOS)
        rgb = np.asarray(img).astype(np.float32)
    return rgb, len(slots)


def chat_layer(rows, outline=1, scale=1.0, max_h=None):
    kept = [r for r in rows if r["keep"]]
    if not kept:
        return None, 0, 0
    pad = outline + 2
    rgb, painted = _strip(kept, scale, (max_h - 2 * pad) if max_h else float("inf"))
    rgb = np.pad(rgb, ((pad, pad), (pad, pad), (0, 0)))
    lum = rgb.max(axis=2)
    peak = _grow(lum, 2)
    a = np.where(peak > INK, lum / np.maximum(peak, 1.0), 0.0).astype(np.float32)
    color = np.minimum(rgb / np.maximum(a, 1e-3)[..., None], 255.0)
    ring = _grow(a, outline) if outline > 0 else np.zeros_like(a)
    cover = a + ring * (1 - a)
    straight = np.where(cover[..., None] > 0, color * a[..., None] / np.maximum(cover, 1e-6)[..., None], 0.0)
    layer = np.dstack([straight, cover * 255.0])
    return np.clip(layer.round(), 0, 255).astype(np.uint8), painted, pad


def place(width, height, layer_w, layer_h, pad, pos, margin):
    if isinstance(pos, str):
        top = margin - pad if pos.startswith("top") else height - margin + pad - layer_h
        left = margin - pad if pos.endswith("left") else width - margin + pad - layer_w
    else:
        left, top = round(pos[0] * width) - pad, round(pos[1] * height) - pad
    left = min(max(left, -pad), max(width - layer_w + pad, -pad))
    top = min(max(top, -pad), max(height - layer_h + pad, -pad))
    return left, top


def blend(frame, layer, left, top):
    out = frame.astype(np.float32)
    H, W = out.shape[:2]
    h, w = layer.shape[:2]
    x0, y0, x1, y1 = max(left, 0), max(top, 0), min(left + w, W), min(top + h, H)
    if x0 >= x1 or y0 >= y1:
        return frame.copy()
    part = layer[y0 - top:y1 - top, x0 - left:x1 - left].astype(np.float32)
    a = part[..., 3:4] / 255.0
    out[y0:y1, x0:x1] = out[y0:y1, x0:x1] * (1 - a) + part[..., :3] * a
    return np.clip(out.round(), 0, 255).astype(np.uint8)


def compose(frame, rows, outline=1, pos="top-left", margin=24, scale=1.0):
    H, W = frame.shape[:2]
    layer, painted, pad = chat_layer(rows, outline, scale, H - 2 * margin)
    if layer is None:
        return None, 0, None
    left, top = place(W, H, layer.shape[1], layer.shape[0], pad, pos, margin)
    box = (left + pad, top + pad, left + layer.shape[1] - pad, top + layer.shape[0] - pad)
    return blend(frame, layer, left, top), painted, box
