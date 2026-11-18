use std::collections::BTreeMap;

use chrono::NaiveDateTime;
use image::{GrayImage, RgbImage};

use crate::edit::Blur;
use crate::img::{self, Filter};
use crate::py;
use crate::text::{self, Face};

pub const STYLES: [&str; 3] = ["none", "cctv", "body"];
pub const PRESETS: [&str; 7] = ["none", "film", "warm", "cold", "faded", "noir", "sepia"];
pub const LOOK: [&str; 6] = ["bright", "contrast", "sat", "temp", "shadows", "highlights"];
pub const LUT_SIDES: (usize, usize) = (2, 65);
pub const BLUR_MODES: [&str; 2] = ["blur", "pixel"];
pub const BLUR_MAX: usize = 12;
pub const TEXT_MAX: usize = 40;
pub const LUMA: [f32; 3] = [0.299, 0.587, 0.114];
const INK: [u8; 3] = [238, 242, 238];
const SHADE: [u8; 3] = [0, 0, 0];
const REC: [u8; 3] = [225, 30, 30];
const CCTV_SIDE: f64 = 300.0;
const CCTV_TINT: [f32; 3] = [0.88, 1.0, 0.92];
const BODY_TINT: [f32; 3] = [0.96, 1.0, 1.05];

pub fn label(style: &str) -> Option<&'static str> {
    match style {
        "cctv" => Some("CAM 01"),
        "body" => Some("UNIT 1"),
        _ => None,
    }
}

pub type Box4 = [i64; 4];

pub struct Plane {
    pub w: usize,
    pub h: usize,
    pub c: usize,
    pub data: Vec<f32>,
}

impl Plane {
    pub fn from_rgb(img: &RgbImage) -> Plane {
        Plane { w: img.width() as usize, h: img.height() as usize, c: 3, data: img.as_raw().iter().map(|&v| v as f32).collect() }
    }

    pub fn to_rgb(&self) -> RgbImage {
        RgbImage::from_raw(self.w as u32, self.h as u32, self.data.iter().map(|&v| py::u8c(v)).collect()).unwrap()
    }

    fn luma(&self) -> Plane {
        let data = self.data.chunks_exact(3).map(|p| p[0] * LUMA[0] + p[1] * LUMA[1] + p[2] * LUMA[2]).collect();
        Plane { w: self.w, h: self.h, c: 1, data }
    }
}

fn mix(x: u32) -> u32 {
    let x = x ^ (x >> 16);
    let x = x.wrapping_mul(0x7FEB352D);
    let x = x ^ (x >> 15);
    let x = x.wrapping_mul(0x846CA68B);
    x ^ (x >> 16)
}

pub fn noise(h: usize, w: usize, sigma: f32) -> Vec<f32> {
    let k = sigma * 6f32.sqrt();
    (0..(h * w) as u32)
        .map(|i| {
            let i = i.wrapping_mul(2);
            let u = (mix(i) >> 8) as f32 + (mix(i.wrapping_add(1)) >> 8) as f32;
            (u / 16777216.0 - 1.0) * k
        })
        .collect()
}

fn curve(v: f32, lift: f32, gain: f32, gamma: f32) -> f32 {
    let t = (v / 255.0).clamp(0.0, 1.0).powf(gamma);
    (lift + t * (gain - lift)) * 255.0
}

fn scurve(v: f32, amount: f32) -> f32 {
    let t = (v / 255.0).clamp(0.0, 1.0);
    (t + (t * t * (3.0 - 2.0 * t) - t) * amount) * 255.0
}

fn saturate(p: &mut [f32], k: f32) {
    let y = p[0] * LUMA[0] + p[1] * LUMA[1] + p[2] * LUMA[2];
    for v in p.iter_mut() {
        *v = y + (*v - y) * k;
    }
}

fn vignette(a: &mut Plane, strength: f32, power: f32) {
    let (h, w) = (a.h as f32, a.w as f32);
    for y in 0..a.h {
        let dy = ((y as f32 - h / 2.0) / (h / 2.0)).powi(2);
        for x in 0..a.w {
            let dx = ((x as f32 - w / 2.0) / (w / 2.0)).powi(2);
            let r = ((dy + dx) / 2.0).sqrt();
            let m = 1.0 - strength * r.powf(power);
            for c in 0..a.c {
                a.data[(y * a.w + x) * a.c + c] *= m;
            }
        }
    }
}

fn barrel(a: &Plane, k: f32, zoom: f32) -> Plane {
    let (w, h, ch) = (a.w, a.h, a.c);
    let (wf, hf) = (w as f32, h as f32);
    let mut out = vec![0f32; w * h * ch];
    for y in 0..h {
        let ny = (y as f32 - hf / 2.0) / (wf / 2.0);
        for x in 0..w {
            let nx = (x as f32 - wf / 2.0) / (wf / 2.0);
            let f = (1.0 + k * (nx * nx + ny * ny)) / zoom;
            let sx = nx * f * (wf / 2.0) + wf / 2.0;
            let sy = ny * f * (wf / 2.0) + hf / 2.0;
            if sx < 0.0 || sx > wf - 1.0 || sy < 0.0 || sy > hf - 1.0 {
                continue;
            }
            let (x0, y0) = (sx.floor(), sy.floor());
            let (fx, fy) = (sx - x0, sy - y0);
            let xa = (x0 as i64).clamp(0, w as i64 - 1) as usize;
            let xb = (x0 as i64 + 1).clamp(0, w as i64 - 1) as usize;
            let ya = (y0 as i64).clamp(0, h as i64 - 1) as usize;
            let yb = (y0 as i64 + 1).clamp(0, h as i64 - 1) as usize;
            for c in 0..ch {
                let at = |yy: usize, xx: usize| a.data[(yy * w + xx) * ch + c];
                out[(y * w + x) * ch + c] = (at(ya, xa) * (1.0 - fx) + at(ya, xb) * fx) * (1.0 - fy)
                    + (at(yb, xa) * (1.0 - fx) + at(yb, xb) * fx) * fy;
            }
        }
    }
    Plane { w, h, c: ch, data: out }
}

fn write(img: &mut RgbImage, xy: (i64, i64), line: &str, face: &Face, s: f64, anchor: &str) -> Box4 {
    let off = py::round(2.0 * s).max(1);
    let at = (xy.0 as f32, xy.1 as f32);
    face.draw(img, line, (at.0 + off as f32, at.1 + off as f32), anchor, SHADE);
    face.draw(img, line, at, anchor, INK);
    let b = face.bbox(line, at, anchor);
    let pad = py::round(5.0 * s);
    [b[0] - pad, b[1] - pad, b[2] + off + pad, b[3] + off + pad]
}

fn rec_dot(img: &mut RgbImage, b: Box4, s: f64) -> Box4 {
    let r = py::round(7.0 * s).max(3);
    let gap = py::round(7.0 * s);
    let cy = (b[1] + b[3]).div_euclid(2);
    text::ellipse(img, [b[0] - gap - 2 * r, cy - r, b[0] - gap, cy + r], REC);
    [b[0] - gap - 2 * r, b[1], b[2], b[3]]
}

fn cctv(frame: &RgbImage, when: Option<NaiveDateTime>, label: &str) -> (RgbImage, Vec<Box4>) {
    let (w, h) = (frame.width() as usize, frame.height() as usize);
    let side = w.min(h) as f64;
    let s = side / 720.0;
    let k = (CCTV_SIDE / side).min(1.0);
    let (sw, sh) = (py::round(w as f64 * k).max(1) as u32, py::round(h as f64 * k).max(1) as u32);
    let small = Plane::from_rgb(&img::resize(frame, sw, sh, Filter::Bilinear)).luma();
    let lifted = Plane { data: small.data.iter().map(|&v| curve(v, 0.08, 0.92, 1.1)).collect(), ..small };
    let mut y = barrel(&lifted, 0.05, (1.0 + 0.05 * (1.0 + (h as f64 / w as f64).powi(2))) as f32);
    for (v, n) in y.data.iter_mut().zip(noise(y.h, y.w, 9.0)) {
        *v += n;
    }
    let gray: Vec<u8> = y.data.iter().map(|&v| py::u8c(v)).collect();
    let big = img::resize_gray(&gray, y.w as u32, y.h as u32, w as u32, h as u32, Filter::Bilinear);
    let mut a = Plane { w, h, c: 3, data: big.iter().flat_map(|&v| CCTV_TINT.map(|t| v as f32 * t)).collect() };
    let step = py::round(side / 360.0).max(2) as usize;
    for row in (0..h).step_by(step) {
        for v in &mut a.data[row * w * 3..(row + 1) * w * 3] {
            *v *= 0.84;
        }
    }
    vignette(&mut a, 0.55, 2.2);
    let mut img = a.to_rgb();
    let m = py::round(28.0 * s);
    let mut boxes = vec![];
    if let Some(mono) = Face::new("consolab.ttf", py::round(20.0 * s)) {
        if !label.is_empty() {
            boxes.push(write(&mut img, (m, m), label, &mono, s, "la"));
        }
        let rec = write(&mut img, (w as i64 - m, m), "REC", &mono, s, "ra");
        boxes.push(rec_dot(&mut img, rec, s));
        if let Some(t) = when {
            boxes.push(write(&mut img, (m, h as i64 - m), &t.format("%d-%m-%Y  %H:%M:%S").to_string(), &mono, s, "ld"));
        }
    }
    (img, boxes)
}

fn bodycam(frame: &RgbImage, when: Option<NaiveDateTime>, label: &str) -> (RgbImage, Vec<Box4>) {
    let (w, h) = (frame.width() as usize, frame.height() as usize);
    let s = w.min(h) as f64 / 720.0;
    let mut a = barrel(&Plane::from_rgb(frame), 0.22, 1.16);
    let grain = noise(h, w, 4.0);
    for (i, p) in a.data.chunks_exact_mut(3).enumerate() {
        for v in p.iter_mut() {
            *v = scurve(*v, 0.55);
        }
        saturate(p, 0.72);
        for (c, v) in p.iter_mut().enumerate() {
            *v = curve(*v, 0.02, 1.0, 1.08) * BODY_TINT[c] + grain[i];
        }
    }
    vignette(&mut a, 0.75, 2.8);
    let mut img = a.to_rgb();
    let m = py::round(28.0 * s);
    let mut boxes: Vec<Box4> = vec![];
    if let (Some(big), Some(small)) = (Face::new("arialbd.ttf", py::round(19.0 * s)), Face::new("arialbd.ttf", py::round(15.0 * s))) {
        let (x, mut y) = (w as i64 - m, m);
        let stamp = when.map(|t| t.format("%Y-%m-%d T%H:%M:%S").to_string()).unwrap_or_default();
        for (line, face) in [(stamp.as_str(), &big), (label, &small)] {
            if !line.is_empty() {
                let b = write(&mut img, (x, y), line, face, s, "ra");
                y = b[3];
                boxes.push(b);
            }
        }
        let rec = write(&mut img, (x, y), "REC", &small, s, "ra");
        boxes.push(rec_dot(&mut img, rec, s));
    }
    (img, boxes)
}

fn preset(p: &mut [f32], name: &str) {
    let y = p[0] * LUMA[0] + p[1] * LUMA[1] + p[2] * LUMA[2];
    match name {
        "film" => {
            let lo = [-0.05, 0.02, 0.05];
            let hi = [0.06, 0.02, -0.05];
            for c in 0..3 {
                let t = p[c] + (1.0 - y) * lo[c] + y * hi[c];
                p[c] = (t - 0.5) * 1.1 + 0.5;
            }
        }
        "warm" => {
            let k = [1.07, 1.0, 0.88];
            for c in 0..3 {
                p[c] = y + (p[c] * k[c] - y) * 1.05;
            }
        }
        "cold" => {
            let k = [0.9, 0.99, 1.08];
            for c in 0..3 {
                p[c] = y + (p[c] * k[c] - y) * 0.95;
            }
        }
        "faded" => {
            let k = [1.02, 1.0, 0.95];
            for c in 0..3 {
                let t = y + (p[c] - y) * 0.72;
                p[c] = 0.07 + t * 0.88 * k[c];
            }
        }
        "noir" | "sepia" => {
            let g = y.clamp(0.0, 1.0);
            let g = g + (g * g * (3.0 - 2.0 * g) - g) * if name == "noir" { 0.65 } else { 0.25 };
            let (k, add) = if name == "noir" { ([1.0, 1.0, 1.0], 0.0) } else { ([1.08, 0.94, 0.74], 0.03) };
            for c in 0..3 {
                p[c] = g * k[c] + add;
            }
        }
        _ => {}
    }
}

fn correct(p: &mut [f32], look: &[f32; 6]) {
    let [bright, contrast, sat, temp, shadows, highlights] = *look;
    if temp != 0.0 {
        p[0] *= 1.0 + 0.12 * temp;
        p[2] *= 1.0 - 0.12 * temp;
    }
    if bright != 0.0 {
        let e = 2f32.powf(-bright);
        for v in p.iter_mut() {
            *v = v.clamp(0.0, 1.0).powf(e);
        }
    }
    if shadows != 0.0 || highlights != 0.0 {
        let y = p[0] * LUMA[0] + p[1] * LUMA[1] + p[2] * LUMA[2];
        let lift = 0.25 * shadows * (1.0 - y / 0.5).clamp(0.0, 1.0).powi(2)
            + 0.25 * highlights * (y / 0.5 - 1.0).clamp(0.0, 1.0).powi(2);
        for v in p.iter_mut() {
            *v += lift;
        }
    }
    if contrast != 0.0 {
        for v in p.iter_mut() {
            *v = (*v - 0.5) * (1.0 + 0.8 * contrast) + 0.5;
        }
    }
    if sat != 0.0 {
        let y = p[0] * LUMA[0] + p[1] * LUMA[1] + p[2] * LUMA[2];
        for v in p.iter_mut() {
            *v = y + (*v - y) * (1.0 + sat);
        }
    }
}

#[derive(Clone, Debug, PartialEq)]
pub struct Lut {
    pub size: usize,
    pub table: Vec<f32>,
}

pub fn read_cube(text: &str) -> Result<Lut, String> {
    let mut size = None;
    let mut rows: Vec<Vec<f32>> = vec![];
    for line in text.lines() {
        let line = line.trim();
        if line.is_empty() || line.starts_with('#') {
            continue;
        }
        let head = line.split_whitespace().next().unwrap_or("").to_uppercase();
        if head == "LUT_3D_SIZE" {
            size = line.split_whitespace().nth(1).and_then(|v| v.parse::<usize>().ok());
            if size.is_none() {
                return Err("в файле нет LUT_3D_SIZE от 2 до 65".into());
            }
        } else if head == "LUT_1D_SIZE" {
            return Err("одномерные LUT не поддерживаются, нужен 3D LUT".into());
        } else if head.starts_with(|c: char| c.is_ascii_digit() || c == '-' || c == '.') {
            let vals: Result<Vec<f32>, _> = line.split_whitespace().take(3).map(|v| v.parse::<f32>()).collect();
            rows.push(vals.map_err(|_| format!("не число в строке: {line}"))?);
        }
    }
    let size = match size {
        Some(s) if LUT_SIDES.0 <= s && s <= LUT_SIDES.1 => s,
        _ => return Err("в файле нет LUT_3D_SIZE от 2 до 65".into()),
    };
    if rows.len() != size.pow(3) || rows.iter().any(|r| r.len() != 3) {
        return Err(format!("ожидалось {} строк цвета, найдено {}", size.pow(3), rows.len()));
    }
    Ok(Lut { size, table: rows.into_iter().flatten().collect() })
}

fn apply_lut(p: &mut [f32], lut: &Lut) {
    let n = lut.size;
    let at = |r: usize, g: usize, b: usize, c: usize| lut.table[((b * n + g) * n + r) * 3 + c];
    let pos: Vec<(usize, usize, f32)> = (0..3)
        .map(|c| {
            let v = (p[c].clamp(0.0, 255.0).round() / 255.0) * (n - 1) as f32;
            let i = (v.floor() as usize).min(n - 2);
            (i, i + 1, v - i as f32)
        })
        .collect();
    let ((r0, r1, fr), (g0, g1, fg), (b0, b1, fb)) = (pos[0], pos[1], pos[2]);
    for c in 0..3 {
        let lerp = |a: f32, b: f32, t: f32| a + (b - a) * t;
        let c00 = lerp(at(r0, g0, b0, c), at(r1, g0, b0, c), fr);
        let c10 = lerp(at(r0, g1, b0, c), at(r1, g1, b0, c), fr);
        let c01 = lerp(at(r0, g0, b1, c), at(r1, g0, b1, c), fr);
        let c11 = lerp(at(r0, g1, b1, c), at(r1, g1, b1, c), fr);
        let v = lerp(lerp(c00, c10, fg), lerp(c01, c11, fg), fb);
        p[c] = (v * 255.0).round().clamp(0.0, 255.0);
    }
}

pub fn grade(frame: &RgbImage, name: Option<&str>, look: Option<&BTreeMap<String, f64>>, lut: Option<&Lut>) -> RgbImage {
    let named = name.filter(|n| PRESETS[1..].contains(n));
    let mut values = [0f32; 6];
    let mut any = false;
    if let Some(look) = look {
        for (i, k) in LOOK.iter().enumerate() {
            let v = look.get(*k).copied().unwrap_or(0.0);
            if v != 0.0 {
                values[i] = (v / 100.0) as f32;
                any = true;
            }
        }
    }
    if named.is_none() && !any && lut.is_none() {
        return frame.clone();
    }
    let mut out = frame.clone();
    let mut t = [0f32; 3];
    for px in out.pixels_mut() {
        for c in 0..3 {
            t[c] = px[c] as f32 / 255.0;
        }
        if let Some(n) = named {
            preset(&mut t, n);
        }
        if let Some(lut) = lut {
            let mut q = t.map(|v| py::u8c(v * 255.0) as f32);
            apply_lut(&mut q, lut);
            t = q.map(|v| v / 255.0);
        }
        if any {
            correct(&mut t, &values);
        }
        for c in 0..3 {
            px[c] = py::u8c(t[c] * 255.0);
        }
    }
    out
}

pub fn obscure(img: &RgbImage, blurs: &[Blur]) -> RgbImage {
    if blurs.is_empty() {
        return img.clone();
    }
    let mut out = img.clone();
    let (w, h) = (out.width() as i64, out.height() as i64);
    let side = w.min(h) as f64;
    for b in blurs.iter().take(BLUR_MAX) {
        let x0 = py::round(b.x * w as f64).max(0);
        let y0 = py::round(b.y * h as f64).max(0);
        let x1 = py::round((b.x + b.w) * w as f64).min(w);
        let y1 = py::round((b.y + b.h) * h as f64).min(h);
        if x1 - x0 < 2 || y1 - y0 < 2 {
            continue;
        }
        let power = b.power.clamp(0.05, 1.0);
        if b.mode == "pixel" {
            let cell = py::round(side * 0.045 * power).max(2);
            let part = img::crop(&out, x0 as u32, y0 as u32, x1 as u32, y1 as u32);
            let (pw, ph) = (part.width(), part.height());
            let sw = py::round(pw as f64 / cell as f64).max(1) as u32;
            let sh = py::round(ph as f64 / cell as f64).max(1) as u32;
            let small = img::resize(&part, sw, sh, Filter::Box);
            let back = img::resize(&small, pw, ph, Filter::Nearest);
            image::imageops::replace(&mut out, &back, x0, y0);
        } else {
            let r = (side * 0.03 * power).max(1.0);
            let pad = py::round(r * 3.0);
            let (l, t, rr, bb) = ((x0 - pad).max(0), (y0 - pad).max(0), (x1 + pad).min(w), (y1 + pad).min(h));
            let soft = img::gaussian_blur(&img::crop(&out, l as u32, t as u32, rr as u32, bb as u32), r as f32);
            let part = img::crop(&soft, (x0 - l) as u32, (y0 - t) as u32, (x1 - l) as u32, (y1 - t) as u32);
            image::imageops::replace(&mut out, &part, x0, y0);
        }
    }
    out
}

pub fn apply(frame: RgbImage, style: Option<&str>, when: Option<NaiveDateTime>, text: Option<&str>) -> (RgbImage, Vec<Box4>) {
    let Some(style) = style else { return (frame, vec![]) };
    let Some(default) = label(style) else { return (frame, vec![]) };
    let line: String = text.unwrap_or(default).chars().take(TEXT_MAX).collect();
    if style == "cctv" { cctv(&frame, when, &line) } else { bodycam(&frame, when, &line) }
}

pub fn gray(img: &GrayImage) -> Vec<f32> {
    img.as_raw().iter().map(|&v| v as f32).collect()
}
