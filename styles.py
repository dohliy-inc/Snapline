from functools import lru_cache

import numpy as np
from PIL import Image, ImageDraw, ImageFilter, ImageFont

STYLES = ("none", "cctv", "body")
PRESETS = ("none", "film", "warm", "cold", "faded", "noir", "sepia")
LOOK = ("bright", "contrast", "sat", "temp", "shadows", "highlights")
LUT_SIDES = (2, 65)
LABELS = {"cctv": "CAM 01", "body": "UNIT 1"}
TEXT_MAX = 40
LUMA = np.array([0.299, 0.587, 0.114], np.float32)
TRIANGLE = np.float32(6 ** 0.5)
INK, SHADE, REC = (238, 242, 238), (0, 0, 0), (225, 30, 30)
CCTV_SIDE = 300
CCTV_TINT = np.array([0.88, 1.0, 0.92], np.float32)
BODY_TINT = np.array([0.96, 1.0, 1.05], np.float32)


def u8(a):
    return np.clip(np.round(a), 0, 255).astype(np.uint8)


def mix(x):
    x = x ^ (x >> np.uint32(16))
    x = x * np.uint32(0x7FEB352D)
    x = x ^ (x >> np.uint32(15))
    x = x * np.uint32(0x846CA68B)
    return x ^ (x >> np.uint32(16))


def noise(h, w, sigma):
    i = np.arange(h * w, dtype=np.uint32) * np.uint32(2)
    u = (mix(i) >> np.uint32(8)).astype(np.float32) + (mix(i + np.uint32(1)) >> np.uint32(8)).astype(np.float32)
    return ((u / 2 ** 24 - 1) * (sigma * TRIANGLE)).reshape(h, w)


def curve(a, lift, gain, gamma):
    t = np.clip(np.asarray(a, np.float32) / 255, 0, 1) ** gamma
    return (lift + t * (gain - lift)) * 255


def scurve(a, amount):
    t = np.clip(np.asarray(a, np.float32) / 255, 0, 1)
    return (t + (t * t * (3 - 2 * t) - t) * amount) * 255


def saturate(a, k):
    y = (a @ LUMA)[..., None]
    return y + (a - y) * k


def vignette(a, strength, power):
    h, w = a.shape[:2]
    y = ((np.arange(h, dtype=np.float32) - h / 2) / (h / 2)) ** 2
    x = ((np.arange(w, dtype=np.float32) - w / 2) / (w / 2)) ** 2
    r = np.sqrt((y[:, None] + x[None, :]) / 2)
    mask = 1 - strength * r ** power
    return a * (mask[..., None] if a.ndim == 3 else mask)


def barrel(a, k, zoom):
    h, w = a.shape[:2]
    ny = ((np.arange(h, dtype=np.float32) - h / 2) / (w / 2))[:, None]
    nx = ((np.arange(w, dtype=np.float32) - w / 2) / (w / 2))[None, :]
    f = (1 + k * (nx * nx + ny * ny)) / zoom
    sx, sy = nx * f * (w / 2) + w / 2, ny * f * (w / 2) + h / 2
    x0, y0 = np.floor(sx).astype(np.intp), np.floor(sy).astype(np.intp)
    fx, fy = sx - x0, sy - y0
    if a.ndim == 3:
        fx, fy = fx[..., None], fy[..., None]
    xa, xb = np.clip(x0, 0, w - 1), np.clip(x0 + 1, 0, w - 1)
    ya, yb = np.clip(y0, 0, h - 1), np.clip(y0 + 1, 0, h - 1)
    out = (a[ya, xa] * (1 - fx) + a[ya, xb] * fx) * (1 - fy) + (a[yb, xa] * (1 - fx) + a[yb, xb] * fx) * fy
    out[(sx < 0) | (sx > w - 1) | (sy < 0) | (sy > h - 1)] = 0
    return out


def font(name, px):
    return ImageFont.truetype(name, max(8, px))


def write(d, xy, text, f, s, anchor="la"):
    off = max(1, round(2 * s))
    d.text((xy[0] + off, xy[1] + off), text, font=f, fill=SHADE, anchor=anchor)
    d.text(xy, text, font=f, fill=INK, anchor=anchor)
    x0, y0, x1, y1 = d.textbbox(xy, text, font=f, anchor=anchor)
    pad = round(5 * s)
    return [x0 - pad, y0 - pad, x1 + off + pad, y1 + off + pad]


def rec_dot(d, box, s):
    r, gap = max(3, round(7 * s)), round(7 * s)
    cy = (box[1] + box[3]) // 2
    d.ellipse((box[0] - gap - 2 * r, cy - r, box[0] - gap, cy + r), fill=REC)
    return [box[0] - gap - 2 * r, box[1], box[2], box[3]]


def cctv(frame, when, text):
    h, w = frame.shape[:2]
    side = min(w, h)
    s, k = side / 720, min(1.0, CCTV_SIDE / side)
    small = np.asarray(Image.fromarray(frame).resize((max(1, round(w * k)), max(1, round(h * k))), Image.BILINEAR))
    y = barrel(curve(small.astype(np.float32) @ LUMA, 0.08, 0.92, 1.1), 0.05, 1 + 0.05 * (1 + (h / w) ** 2))
    y = y + noise(y.shape[0], y.shape[1], 9)
    a = np.asarray(Image.fromarray(u8(y)).resize((w, h), Image.BILINEAR), np.float32)[..., None] * CCTV_TINT
    step = max(2, round(side / 360))
    a[::step] *= 0.84
    img = Image.fromarray(u8(vignette(a, 0.55, 2.2)))
    d = ImageDraw.Draw(img)
    m, mono = round(28 * s), font("consolab.ttf", round(20 * s))
    boxes = [write(d, (m, m), text, mono, s)] if text else []
    boxes.append(rec_dot(d, write(d, (w - m, m), "REC", mono, s, "ra"), s))
    if when:
        boxes.append(write(d, (m, h - m), when.strftime("%d-%m-%Y  %H:%M:%S"), mono, s, "ld"))
    return np.asarray(img), boxes


def bodycam(frame, when, text):
    h, w = frame.shape[:2]
    s = min(w, h) / 720
    a = saturate(scurve(barrel(frame, 0.22, 1.16), 0.55), 0.72)
    a = curve(a, 0.02, 1.0, 1.08) * BODY_TINT + noise(h, w, 4)[..., None]
    img = Image.fromarray(u8(vignette(a, 0.75, 2.8)))
    d = ImageDraw.Draw(img)
    m, big, small = round(28 * s), font("arialbd.ttf", round(19 * s)), font("arialbd.ttf", round(15 * s))
    x, y, boxes = w - m, m, []
    for line, f in ((when.strftime("%Y-%m-%d T%H:%M:%S") if when else "", big), (text, small)):
        if line:
            boxes.append(write(d, (x, y), line, f, s, "ra"))
            y = boxes[-1][3]
    boxes.append(rec_dot(d, write(d, (x, y), "REC", small, s, "ra"), s))
    return np.asarray(img), boxes


def preset(t, name):
    y = (t @ LUMA)[..., None]
    if name == "film":
        t = t + (1 - y) * np.array([-0.05, 0.02, 0.05], np.float32) + y * np.array([0.06, 0.02, -0.05], np.float32)
        return (t - 0.5) * 1.1 + 0.5
    if name == "warm":
        return y + (t * np.array([1.07, 1.0, 0.88], np.float32) - y) * 1.05
    if name == "cold":
        return y + (t * np.array([0.9, 0.99, 1.08], np.float32) - y) * 0.95
    if name == "faded":
        t = y + (t - y) * 0.72
        return 0.07 + t * 0.88 * np.array([1.02, 1.0, 0.95], np.float32)
    if name in ("noir", "sepia"):
        g = np.clip(y, 0, 1)
        g = g + (g * g * (3 - 2 * g) - g) * (0.65 if name == "noir" else 0.25)
        return g * (np.array([1.0, 1.0, 1.0], np.float32) if name == "noir" else
                    np.array([1.08, 0.94, 0.74], np.float32)) + (0.0 if name == "noir" else 0.03)
    return t


def correct(t, look):
    bright, contrast, sat, temp, shadows, highlights = (float(look.get(k, 0)) / 100 for k in LOOK)
    if temp:
        t = t * np.array([1 + 0.12 * temp, 1.0, 1 - 0.12 * temp], np.float32)
    if bright:
        t = np.clip(t, 0, 1) ** np.float32(2 ** -bright)
    if shadows or highlights:
        y = t @ LUMA
        lift = 0.25 * shadows * np.clip(1 - y / 0.5, 0, 1) ** 2 + 0.25 * highlights * np.clip(y / 0.5 - 1, 0, 1) ** 2
        t = t + lift[..., None]
    if contrast:
        t = (t - 0.5) * (1 + 0.8 * contrast) + 0.5
    if sat:
        y = (t @ LUMA)[..., None]
        t = y + (t - y) * (1 + sat)
    return t


def read_cube(text):
    size, rows = None, []
    for line in text.splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        head = line.split()[0].upper()
        if head == "LUT_3D_SIZE":
            size = int(line.split()[1])
        elif head == "LUT_1D_SIZE":
            raise ValueError("одномерные LUT не поддерживаются, нужен 3D LUT")
        elif head[0].isdigit() or head[0] in "-.":
            rows.append([float(v) for v in line.split()[:3]])
    if size is None or not LUT_SIDES[0] <= size <= LUT_SIDES[1]:
        raise ValueError("в файле нет LUT_3D_SIZE от 2 до 65")
    if len(rows) != size ** 3 or any(len(r) != 3 for r in rows):
        raise ValueError(f"ожидалось {size ** 3} строк цвета, найдено {len(rows)}")
    return size, [v for r in rows for v in r]


@lru_cache(maxsize=8)
def load_lut(path, stamp):
    size, table = read_cube(open(path, encoding="utf-8", errors="replace").read())
    return ImageFilter.Color3DLUT(size, table)


def grade(frame, name, look, lut=None):
    look = {k: v for k, v in (look or {}).items() if k in LOOK and v}
    if name not in PRESETS[1:] and not look and lut is None:
        return frame
    t = frame.astype(np.float32) / 255
    if name in PRESETS[1:]:
        t = preset(t, name)
    if lut is not None:
        t = np.asarray(Image.fromarray(u8(t * 255)).filter(lut), np.float32) / 255
    if look:
        t = correct(t, look)
    return u8(t * 255)


def apply(frame, style, when, text):
    if style not in LABELS:
        return frame, []
    text = (LABELS[style] if text is None else str(text))[:TEXT_MAX]
    return (cctv if style == "cctv" else bodycam)(frame, when, text)
