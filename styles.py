import numpy as np
from PIL import Image, ImageDraw, ImageFont

STYLES = ("none", "cctv", "body")
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


def apply(frame, style, when, text):
    if style not in LABELS:
        return frame, []
    text = (LABELS[style] if text is None else str(text))[:TEXT_MAX]
    return (cctv if style == "cctv" else bodycam)(frame, when, text)
