use std::collections::HashMap;
use std::path::{Path, PathBuf};
use std::sync::{Arc, Mutex, OnceLock};
use std::time::SystemTime;

use chrono::NaiveDateTime;
use image::{RgbImage, RgbaImage};

use crate::chat::{self, Row};
use crate::config::{self, CHAT_POSITIONS};
use crate::edit::{Blur, Coord, Edit, Home, Join, Overlay, Pos, Seam};
use crate::img::{self, Filter};
use crate::py;
use crate::styles::{self, Box4, Lut};

pub const REFERENCE_SIDE: f64 = 1440.0;
pub const LUT_DIR: &str = "luts";
pub const JOIN_SIDES: [&str; 4] = ["left", "right", "top", "bottom"];
pub const MAX_OVERLAYS: usize = 4;
pub const TILT_MAX: f64 = 30.0;
pub const SCENE_MAX: usize = 8;

pub fn spare_places(corner: &str) -> [&'static str; 2] {
    match corner {
        "top-right" => ["bottom-right", "top-left"],
        "bottom-left" => ["top-left", "bottom-right"],
        "bottom-right" => ["top-right", "bottom-left"],
        _ => ["bottom-left", "top-right"],
    }
}

pub fn apply_keep(rows: &mut [Row], edit: &mut Edit) {
    if edit.keep.len() == rows.len() {
        for (r, &k) in rows.iter_mut().zip(&edit.keep) {
            r.keep = k;
        }
    } else {
        edit.keep = rows.iter().map(|r| r.keep).collect();
    }
    edit.breaks = cuts(rows.len(), edit).into_iter().map(|i| i as i64).collect();
    for drop in [false, true] {
        let field = if drop { &edit.dropped } else { &edit.hidden };
        let mut spans: HashMap<usize, Vec<(usize, usize)>> = HashMap::new();
        for &[i, a, b] in field {
            if 0 <= i && (i as usize) < rows.len() && a >= 0 && b >= 0 {
                spans.entry(i as usize).or_default().push((a as usize, b as usize));
            }
        }
        for (i, r) in rows.iter_mut().enumerate() {
            let s = spans.remove(&i).unwrap_or_default();
            if drop {
                r.drop = s;
            } else {
                r.hide = Some(s);
            }
        }
        let fresh = crate::edit::spans_of(rows, drop);
        if drop {
            edit.dropped = fresh;
        } else {
            edit.hidden = fresh;
        }
    }
}

pub fn auto_hide(rows: &mut [Row], only_new: bool) {
    let found = chat::nick_spans(rows);
    for (r, spans) in rows.iter_mut().zip(found) {
        if !only_new || r.hide.is_none() {
            r.hide = Some(spans);
        }
    }
}

pub fn cuts(count: usize, edit: &Edit) -> Vec<usize> {
    let mut out: Vec<usize> = edit.breaks.iter().filter(|&&i| 0 < i && (i as usize) < count).map(|&i| i as usize).collect();
    out.sort();
    out.dedup();
    out
}

pub fn corner_of(pos: &Pos) -> String {
    match pos {
        Pos::Corner(s) => if CHAT_POSITIONS.contains(&s.as_str()) { s.clone() } else { "top-left".into() },
        Pos::Free(x, y) => {
            let v = match y {
                Coord::Side(s) if s == "top" || s == "bottom" => s.clone(),
                Coord::Num(n) if *n < 0.5 => "top".into(),
                Coord::Num(_) => "bottom".into(),
                Coord::Side(_) => "top".into(),
            };
            let h = match x {
                Coord::Side(s) if s == "left" || s == "right" => s.clone(),
                Coord::Num(n) if *n < 0.5 => "left".into(),
                Coord::Num(_) => "right".into(),
                Coord::Side(_) => "left".into(),
            };
            format!("{v}-{h}")
        }
    }
}

pub fn places(edit: &Edit, count: usize) -> Vec<Pos> {
    let first = edit.pos.clone();
    let mut extra = edit.places.clone();
    let corner = corner_of(&first);
    let spare = spare_places(&corner);
    let mut order: Vec<&str> = spare.to_vec();
    order.extend(CHAT_POSITIONS.iter().filter(|c| **c != corner && !spare.contains(c)));
    order.push(CHAT_POSITIONS.iter().find(|c| **c == corner).copied().unwrap_or("top-left"));
    while extra.len() + 1 < count {
        extra.push(Pos::corner(order[extra.len() % order.len()]));
    }
    let mut out = vec![first];
    out.extend(extra.into_iter().take(count.saturating_sub(1)));
    out
}

pub fn homes_of(count_rows: usize, edit: &Edit) -> Vec<Option<String>> {
    let count = cuts(count_rows, edit).len() + 1;
    match &edit.home {
        None => vec![None; count],
        Some(Home::One(h)) => vec![Some(h.clone()); count],
        Some(Home::Many(list)) if list.is_empty() => vec![None; count],
        Some(Home::Many(list)) => {
            let mut out = list.clone();
            while out.len() < count {
                out.push(list[list.len() - 1].clone());
            }
            out.truncate(count);
            out
        }
    }
}

pub fn parts(rows: &[Row], edit: &Edit) -> Vec<(std::ops::Range<usize>, Pos)> {
    let mut bounds = vec![0];
    bounds.extend(cuts(rows.len(), edit));
    bounds.push(rows.len());
    let spans: Vec<_> = bounds.windows(2).map(|w| w[0]..w[1]).collect();
    let spots = places(edit, spans.len());
    spans.into_iter().zip(spots).collect()
}

#[derive(Clone, Copy, Debug, PartialEq)]
pub struct Plan {
    pub rect: (i64, i64, i64, i64),
    pub base: (u32, u32),
    pub size: (u32, u32),
    pub at: (u32, u32),
    pub ext_box: Option<(i64, i64, i64, i64)>,
    pub outline: i64,
    pub margin: i64,
    pub scale: f64,
}

fn join_edge(join: &Option<Join>) -> Option<&str> {
    join.as_ref().map(|j| j.side.as_str()).filter(|s| JOIN_SIDES.contains(s))
}

pub fn join_sizes(join: &Join, along: u32) -> (u32, u32) {
    let ext = py::round(join.size * along as f64).max(1) as u32;
    let fade = (py::round(join.fade * (ext as f64).min(along as f64 / 2.0)) as u32).min(along);
    (ext, fade)
}

pub fn plan(bg: (u32, u32), edit: &Edit, width: Option<u32>) -> Plan {
    let (w_bg, h_bg) = bg;
    let ratio = config::ratio_of(&edit.format).unwrap_or(Some(1.0));
    let rect = chat::frame_rect(w_bg as i64, h_bg as i64, ratio, edit.zoom, edit.center);
    let (cw, ch) = ((rect.2 - rect.0) as f64, (rect.3 - rect.1) as f64);
    let edge = join_edge(&edit.join);
    let wide = matches!(edge, Some("left") | Some("right"));
    let base: (u32, u32) = if let Some(width) = width {
        let size = edit.join.as_ref().map(|j| j.size).unwrap_or(0.0);
        let bw = py::round(if wide { width as f64 / (1.0 + size) } else { width as f64 }).max(1);
        (bw as u32, py::round(bw as f64 * ch / cw).max(1) as u32)
    } else {
        let short = cw.min(ch);
        match config::exact_of(&edit.format) {
            Some((ew, eh)) => (ew, eh),
            None => {
                let side = config::side_of(&edit.size).map(|s| s as f64).unwrap_or(short);
                let f = side / short;
                (py::round(cw * f).max(1) as u32, py::round(ch * f).max(1) as u32)
            }
        }
    };
    let side = base.0.min(base.1) as f64;
    let k = side / REFERENCE_SIDE;
    let (ext, _) = match (edge, &edit.join) {
        (Some(_), Some(j)) => join_sizes(j, if wide { base.0 } else { base.1 }),
        _ => (0, 0),
    };
    let size = if wide { (base.0 + ext, base.1) } else { (base.0, base.1 + ext) };
    let (b0, b1, e) = (base.0 as i64, base.1 as i64, ext as i64);
    let ext_box = match edge {
        Some("left") => Some((0, 0, e, b1)),
        Some("right") => Some((b0, 0, b0 + e, b1)),
        Some("top") => Some((0, 0, b0, e)),
        Some("bottom") => Some((0, b1, b0, b1 + e)),
        _ => None,
    };
    Plan {
        rect,
        base,
        size,
        at: (if edge == Some("left") { ext } else { 0 }, if edge == Some("top") { ext } else { 0 }),
        ext_box,
        outline: if edit.outline != 0 { py::round(edit.outline as f64 * k).max(1) } else { 0 },
        margin: py::round(edit.margin as f64 * k),
        scale: edit.text_scale * side / (h_bg.min(w_bg) as f64),
    }
}

pub fn bg_part(bg: &RgbImage, rect: (i64, i64, i64, i64), mirror: bool) -> RgbImage {
    let (x0, y0, x1, y1) = rect;
    if !mirror {
        return img::crop(bg, x0 as u32, y0 as u32, x1 as u32, y1 as u32);
    }
    let w = bg.width() as i64;
    img::flip_h(&img::crop(bg, (w - x1) as u32, y0 as u32, (w - x0) as u32, y1 as u32))
}

type OverlayKey = (PathBuf, Option<SystemTime>, bool);

pub fn overlay_image(path: &Path, flip: bool) -> Option<Arc<RgbaImage>> {
    static CACHE: OnceLock<Mutex<Vec<(OverlayKey, Arc<RgbaImage>)>>> = OnceLock::new();
    let stamp = std::fs::metadata(path).ok()?.modified().ok();
    let key = (path.to_path_buf(), stamp, flip);
    let cache = CACHE.get_or_init(|| Mutex::new(Vec::new()));
    if let Some((_, hit)) = cache.lock().unwrap().iter().find(|(k, _)| *k == key) {
        return Some(hit.clone());
    }
    let mut im = image::open(path).ok()?.to_rgba8();
    if flip {
        im = img::flip_h_rgba(&im);
    }
    let im = Arc::new(im);
    let mut cache = cache.lock().unwrap();
    if cache.len() >= 16 {
        cache.remove(0);
    }
    cache.push((key, im.clone()));
    Some(im)
}

pub fn wrap_angle(angle: f64) -> f64 {
    py::round_to(py::modulo(angle + 180.0, 360.0) - 180.0, 2)
}

pub fn flip_overlay(ov: &mut Overlay) {
    let [l, t, r, b] = ov.crop;
    ov.crop = [py::round_to(1.0 - r, 5), t, py::round_to(1.0 - l, 5), b];
    ov.flip = Some(!ov.flipped());
    ov.angle = Some(wrap_angle(-ov.turn()));
}

pub fn turned(x: f64, y: f64, angle: f64) -> (f64, f64) {
    let a = angle.to_radians();
    (x * a.cos() - y * a.sin(), x * a.sin() + y * a.cos())
}

pub fn tilt_zoom(size: (u32, u32), angle: f64) -> f64 {
    if angle == 0.0 {
        return 1.0;
    }
    let (w, h) = (size.0 as f64, size.1 as f64);
    let (c, s) = (angle.to_radians().cos().abs(), angle.to_radians().sin().abs());
    (c + h / w * s).max(w / h * s + c) * 1.002
}

pub fn tilt_image(src: &RgbImage, angle: f64, size: (u32, u32)) -> RgbImage {
    if angle == 0.0 {
        return if src.dimensions() == size { src.clone() } else { img::resize(src, size.0, size.1, Filter::Bicubic) };
    }
    let (big_w, big_h) = (src.width() as f64, src.height() as f64);
    let (w, h) = (size.0 as f64, size.1 as f64);
    let k = big_w / (w * tilt_zoom(size, angle));
    let (a, b) = turned(k, 0.0, -angle);
    let (d, e) = turned(0.0, k, -angle);
    img::affine_rgb(src, size, [a, d, big_w / 2.0 - a * w / 2.0 - d * h / 2.0, b, e, big_h / 2.0 - b * w / 2.0 - e * h / 2.0])
}

pub fn spin(piece: &RgbaImage, angle: f64) -> RgbaImage {
    let turn = py::modulo(angle, 360.0);
    if turn == 0.0 {
        return piece.clone();
    }
    if py::modulo(angle, 90.0) == 0.0 {
        return match turn as i64 {
            90 => image::imageops::rotate90(piece),
            180 => image::imageops::rotate180(piece),
            _ => image::imageops::rotate270(piece),
        };
    }
    let mut padded = RgbaImage::new(piece.width() + 4, piece.height() + 4);
    image::imageops::replace(&mut padded, &img::premultiply(piece), 2, 2);
    let (w, h) = (padded.width() as f64, padded.height() as f64);
    let rad = angle.to_radians();
    let (cos, sin) = (py::round_to(rad.cos(), 15), py::round_to(rad.sin(), 15));
    let mut m = [cos, sin, 0.0, -sin, cos, 0.0];
    let tf = |m: &[f64; 6], x: f64, y: f64| (m[0] * x + m[1] * y + m[2], m[3] * x + m[4] * y + m[5]);
    let (cx, cy) = (w / 2.0, h / 2.0);
    let (tx, ty) = tf(&m, -cx, -cy);
    m[2] = tx + cx;
    m[5] = ty + cy;
    let corners: Vec<(f64, f64)> = [(0.0, 0.0), (w, 0.0), (w, h), (0.0, h)].iter().map(|&(x, y)| tf(&m, x, y)).collect();
    let (min_x, max_x) = corners.iter().fold((f64::MAX, f64::MIN), |(a, b), p| (a.min(p.0), b.max(p.0)));
    let (min_y, max_y) = corners.iter().fold((f64::MAX, f64::MIN), |(a, b), p| (a.min(p.1), b.max(p.1)));
    let nw = (max_x.ceil() - min_x.floor()) as u32;
    let nh = (max_y.ceil() - min_y.floor()) as u32;
    let (tx, ty) = tf(&m, -(nw as f64 - w) / 2.0, -(nh as f64 - h) / 2.0);
    m[2] = tx;
    m[5] = ty;
    img::unpremultiply(&img::affine_rgba(&padded, (nw, nh), m))
}

pub fn soft_edges(b: (i64, i64, i64, i64), out: (u32, u32)) -> [bool; 4] {
    let (x, y, w, h) = b;
    [x > 0, y > 0, x + w < out.0 as i64, y + h < out.1 as i64]
}

pub fn spun_edges(ov: &Overlay, b: (i64, i64, i64, i64), out: (u32, u32)) -> [bool; 4] {
    if py::modulo(ov.turn(), 360.0) == 0.0 { soft_edges(b, out) } else { [true; 4] }
}

pub fn mirror_blurs(blurs: &[Blur], p: &Plan) -> Vec<Blur> {
    let (at, bw, w) = (p.at.0 as f64, p.base.0 as f64, p.size.0 as f64);
    blurs.iter().map(|b| Blur { x: py::round_to((2.0 * at + bw) / w - b.x - b.w, 5), ..b.clone() }).collect()
}

pub fn cover_box(src: (u32, u32), size: (u32, u32), cx: f64, cy: f64) -> (f64, f64, f64, f64) {
    let (sw, sh) = (src.0 as f64, src.1 as f64);
    let (w, h) = (size.0 as f64, size.1 as f64);
    let s = (sw / w).min(sh / h);
    let (cw, ch) = (w * s, h * s);
    let x0 = (cx * sw - cw / 2.0).max(0.0).min(sw - cw);
    let y0 = (cy * sh - ch / 2.0).max(0.0).min(sh - ch);
    (x0, y0, x0 + cw, y0 + ch)
}

pub fn ramp(n: usize) -> Vec<f32> {
    (0..n).map(|i| {
        let t = (i as f32 + 0.5) / n as f32;
        t * t * (3.0 - 2.0 * t)
    }).collect()
}

fn orient(frame: &RgbImage, side: &str) -> RgbImage {
    match side {
        "left" => img::flip_h(frame),
        "top" => img::transverse(frame),
        "bottom" => img::transpose(frame),
        _ => frame.clone(),
    }
}

pub fn join_canvas(frame: &RgbImage, join: &Join) -> RgbImage {
    let base = orient(frame, &join.side);
    let (bw, bh) = base.dimensions();
    let (ext, fade) = join_sizes(join, bw);
    let pw = ext + fade;
    let small = img::resize(&img::flip_h(&base), (bw / 8).max(1), (bh / 8).max(1), Filter::Bilinear);
    let soft = img::gaussian_blur(&small, (small.width().min(small.height()) as f32 * 0.04).max(2.0));
    let cover = img::resize_box(&soft, pw, bh, Filter::Bicubic, cover_box(soft.dimensions(), (pw, bh), 0.0, 0.5));
    let dim: Vec<f32> = (0..pw)
        .map(|i| 1.0 - 0.55 * ((i as f32 - fade as f32) / ext.max(1) as f32).clamp(0.0, 1.0).powf(1.5))
        .collect();
    let mut canvas = RgbImage::new(bw + ext, bh);
    image::imageops::replace(&mut canvas, &base, 0, 0);
    let a = ramp(fade as usize);
    for y in 0..bh {
        for x in 0..pw {
            let c = cover.get_pixel(x, y);
            let v = [0, 1, 2].map(|k| (c[k] as f32 * dim[x as usize]) as u8);
            if x >= fade {
                canvas.put_pixel(bw + x - fade, y, image::Rgb(v));
            } else {
                let p = canvas.get_pixel_mut(bw - fade + x, y);
                for k in 0..3 {
                    let under = p[k] as f32;
                    p[k] = py::u8c(under + (v[k] as f32 - under) * a[x as usize]);
                }
            }
        }
    }
    orient(&canvas, &join.side)
}

pub fn jpeg_pass(frame: &RgbImage, quality: u8) -> RgbImage {
    let mut buf = Vec::new();
    let mut enc = jpeg_encoder::Encoder::new(&mut buf, quality);
    enc.set_sampling_factor(jpeg_encoder::SamplingFactor::R_4_2_0);
    if enc.encode(frame.as_raw(), frame.width() as u16, frame.height() as u16, jpeg_encoder::ColorType::Rgb).is_err() {
        return frame.clone();
    }
    image::load_from_memory(&buf).map(|i| i.to_rgb8()).unwrap_or_else(|_| frame.clone())
}

pub fn lock_ratio(cut: &str) -> Option<f64> {
    if let Some((w, h)) = config::exact_of(cut) {
        return if h != 0 { Some(w as f64 / h as f64) } else { None };
    }
    let (a, b) = cut.split_once(':')?;
    let (a, b): (u32, u32) = (a.parse().ok()?, b.parse().ok()?);
    if b != 0 { Some(a as f64 / b as f64) } else { None }
}

pub fn crop_for(size: (u32, u32), ratio: Option<f64>, within: [f64; 4]) -> [f64; 4] {
    let Some(ratio) = ratio else { return [0.0, 0.0, 1.0, 1.0] };
    let (w, h) = (size.0 as f64, size.1 as f64);
    let [l, t, r, b] = within;
    let (rw, rh) = ((r - l) * w, (b - t) * h);
    let (cw, ch) = if rw / rh < ratio { (rw, rw / ratio) } else { (rh * ratio, rh) };
    let (cx, cy) = ((l + r) / 2.0 * w, (t + b) / 2.0 * h);
    [(cx - cw / 2.0) / w, (cy - ch / 2.0) / h, (cx + cw / 2.0) / w, (cy + ch / 2.0) / h].map(|v| py::round_to(v, 4))
}

pub fn crop_exact(size: (u32, u32), w: u32, h: u32, within: [f64; 4]) -> [f64; 4] {
    let (sw, sh) = (size.0 as f64, size.1 as f64);
    let (w, h) = ((w.max(1) as f64).min(sw), (h.max(1) as f64).min(sh));
    let [l, t, r, b] = within;
    let cx = ((l + r) / 2.0 * sw).max(w / 2.0).min(sw - w / 2.0);
    let cy = ((t + b) / 2.0 * sh).max(h / 2.0).min(sh - h / 2.0);
    [(cx - w / 2.0) / sw, (cy - h / 2.0) / sh, (cx + w / 2.0) / sw, (cy + h / 2.0) / sh].map(|v| py::round_to(v, 4))
}

pub fn overlay_box(ov: &Overlay, out: (u32, u32), src: (u32, u32)) -> (i64, i64, i64, i64) {
    let [l, t, r, b] = ov.crop;
    let cw = ((r - l) * src.0 as f64).max(1.0);
    let ch = ((b - t) * src.1 as f64).max(1.0);
    let w = py::round(ov.w * out.0 as f64).max(1);
    let h = py::round(w as f64 * ch / cw).max(1);
    (py::round(ov.x * out.0 as f64 - w as f64 / 2.0), py::round(ov.y * out.1 as f64 - h as f64 / 2.0), w, h)
}

pub fn edge_ramp(n: usize, f: f64, near: bool, far: bool) -> Vec<f32> {
    (0..n).map(|i| {
        let i = i as f64 + 0.5;
        let d = (if near { i } else { f64::INFINITY }).min(if far { n as f64 - i } else { f64::INFINITY });
        let t = if f >= 1.0 { (d / f).clamp(0.0, 1.0) } else { 1.0 };
        (t * t * (3.0 - 2.0 * t)) as f32
    }).collect()
}

pub fn overlay_piece(src: &RgbaImage, ov: &Overlay, size: (u32, u32)) -> RgbaImage {
    let [l, t, r, b] = ov.crop;
    let (w, h) = (src.width() as f64, src.height() as f64);
    let x0 = py::round(l * w);
    let y0 = py::round(t * h);
    let x1 = (x0 + 1).max(py::round(r * w));
    let y1 = (y0 + 1).max(py::round(b * h));
    let piece = crop_any(src, x0, y0, x1, y1);
    img::resize_rgba(&piece, size.0, size.1, Filter::Lanczos)
}

fn crop_any(src: &RgbaImage, x0: i64, y0: i64, x1: i64, y1: i64) -> RgbaImage {
    let mut out = RgbaImage::new((x1 - x0).max(1) as u32, (y1 - y0).max(1) as u32);
    for y in y0..y1 {
        for x in x0..x1 {
            if x >= 0 && y >= 0 && (x as u32) < src.width() && (y as u32) < src.height() {
                out.put_pixel((x - x0) as u32, (y - y0) as u32, *src.get_pixel(x as u32, y as u32));
            }
        }
    }
    out
}

pub fn soften(piece: &RgbaImage, ov: &Overlay, edges: [bool; 4]) -> RgbaImage {
    if ov.soft <= 0.0 && ov.alpha >= 1.0 {
        return piece.clone();
    }
    let (w, h) = (piece.width() as usize, piece.height() as usize);
    let [left, top, right, bottom] = edges;
    let f = ov.soft * w.min(h) as f64 / 2.0;
    let rows = edge_ramp(h, f, top, bottom);
    let cols = edge_ramp(w, f, left, right);
    let mut out = piece.clone();
    for (i, p) in out.pixels_mut().enumerate() {
        let (y, x) = (i / w, i % w);
        p[3] = py::u8c(p[3] as f32 * rows[y] * cols[x] * ov.alpha as f32);
    }
    out
}

pub fn paste_overlays(frame: &RgbImage, overlays: &[Overlay], src: &Path) -> RgbImage {
    let mut canvas = img::to_rgba(frame);
    let size = frame.dimensions();
    for ov in overlays {
        let Some(source) = overlay_image(&src.join(&ov.file), ov.flipped()) else { continue };
        let (x, y, w, h) = overlay_box(ov, size, source.dimensions());
        let piece = soften(&overlay_piece(&source, ov, (w as u32, h as u32)), ov, spun_edges(ov, (x, y, w, h), size));
        let piece = spin(&piece, ov.turn());
        let left = py::round(x as f64 + (w as f64 - piece.width() as f64) / 2.0);
        let top = py::round(y as f64 + (h as f64 - piece.height() as f64) / 2.0);
        img::paste_rgba(&mut canvas, &piece, left, top);
    }
    img::to_rgb(&canvas)
}

pub fn backdrop(bg: &RgbImage, edit: &Edit, src: Option<&Path>, width: Option<u32>) -> (RgbImage, Plan) {
    let p = plan(bg.dimensions(), edit, width);
    let mut frame = bg_part(bg, p.rect, edit.mirror);
    if edit.tilt() != 0.0 {
        let size = frame.dimensions();
        frame = tilt_image(&frame, edit.tilt(), size);
    }
    if frame.dimensions() != p.base {
        let filter = if p.base.0 < frame.width() { Filter::Lanczos } else { Filter::Bicubic };
        frame = img::resize(&frame, p.base.0, p.base.1, filter);
    }
    if p.size != p.base {
        if let Some(join) = &edit.join {
            frame = join_canvas(&frame, join);
        }
    }
    if let Some(src) = src {
        if !edit.overlays.is_empty() {
            frame = paste_overlays(&frame, &edit.overlays, src);
        }
    }
    if let Some(blurs) = edit.blurs.as_deref().filter(|b| !b.is_empty()) {
        frame = styles::obscure(&frame, blurs);
    }
    if let Some(width) = width {
        if frame.width() != width {
            let h = py::round(frame.height() as f64 * width as f64 / frame.width() as f64).max(1) as u32;
            frame = img::resize(&frame, width, h, Filter::Lanczos);
        }
    }
    (frame, p)
}

pub fn chat_spots(size: (i64, i64), layers: &[Option<(i64, i64)>], spots: &[Pos], pad: i64, margin: i64,
                  boxes: &mut Vec<Box4>, span: Option<(i64, i64)>) -> Vec<Option<(i64, i64)>> {
    let (w, h) = size;
    let mut out = Vec::new();
    for (layer, pos) in layers.iter().zip(spots) {
        let Some((lw, lh)) = *layer else {
            out.push(None);
            continue;
        };
        let (left, mut top) = chat::place(w, h, lw, lh, pad, pos, margin);
        if let (Some(span), Pos::Free(_, y)) = (span, pos) {
            let yv = match y { Coord::Num(v) => *v, Coord::Side(s) => if s == "bottom" { 1.0 } else { 0.0 } };
            top = (py::round(yv * h as f64) - pad).max(span.0 - pad).min((span.1 - lh + pad).max(span.0 - pad));
            boxes.push([left + pad, top + pad, left + lw - pad, top + lh - pad]);
            out.push(Some((left, top)));
            continue;
        }
        if let Pos::Corner(name) = pos {
            for _ in 0..boxes.len() {
                let hit: Vec<Box4> = boxes.iter().copied()
                    .filter(|b| b[0] < left + lw - pad && left + pad < b[2] && b[1] < top + lh - pad && top + pad < b[3])
                    .collect();
                if hit.is_empty() {
                    break;
                }
                top = if name.starts_with("top") {
                    hit.iter().map(|b| b[3]).max().unwrap() + margin - pad
                } else {
                    hit.iter().map(|b| b[1]).min().unwrap() - margin - lh + pad
                };
            }
        }
        top = top.max(-pad).min((h - lh + pad).max(-pad));
        boxes.push([left + pad, top + pad, left + lw - pad, top + lh - pad]);
        out.push(Some((left, top)));
    }
    out
}

#[derive(Clone, Copy, Debug, PartialEq)]
pub struct Found {
    pub part: usize,
    pub x: i64,
    pub y: i64,
    pub w: i64,
    pub h: i64,
}

pub fn paint_chat(img: &mut RgbImage, rows: &[Row], edit: &Edit, p: &Plan, wins: &[Option<(i64, i64)>],
                  taken: &mut [Vec<Box4>], slots: &[usize], mut found: Option<&mut Vec<Found>>) -> usize {
    let groups = parts(rows, edit);
    let mut painted = 0;
    for (k, (range, pos)) in groups.into_iter().enumerate() {
        let win = wins.get(k).copied().flatten();
        let (y0, y1) = win.unwrap_or((0, img.height() as i64));
        let part = &rows[range];
        let layer = if part.is_empty() {
            None
        } else {
            chat::chat_layer(part, p.outline as usize, p.scale, Some((y1 - y0 - 2 * p.margin) as f64))
        };
        let dims = layer.as_ref().map(|l| (l.image.width() as i64, l.image.height() as i64));
        let slot = slots.get(k).copied().unwrap_or(0);
        let span = win.map(|_| (-y0, img.height() as i64 - y0));
        let spot = chat_spots((img.width() as i64, y1 - y0), &[dims], std::slice::from_ref(&pos),
                              p.outline + 2, p.margin, &mut taken[slot], span)[0];
        if let (Some(layer), Some((x, y))) = (layer, spot) {
            chat::blend(img, &layer.image, x, y + y0);
            painted += layer.painted;
            if let Some(f) = found.as_deref_mut() {
                f.push(Found { part: k, x, y: y + y0, w: layer.image.width() as i64, h: layer.image.height() as i64 });
            }
        }
    }
    painted
}

fn seam(upper: &RgbImage, lower: &RgbImage, lap: u32, look: &Seam) -> RgbImage {
    let w = upper.width();
    let weights = ramp(lap as usize);
    let r = look.blur * lap as f64 / 6.0;
    let uh = upper.height();
    let take = |src: &RgbImage, y0: u32, y1: u32| img::crop(src, 0, y0, w, y1);
    let mut a = take(upper, uh - lap, uh);
    let mut b = take(lower, 0, lap);
    let as_f = |i: &RgbImage| -> Vec<f32> { i.as_raw().iter().map(|&v| v as f32).collect() };
    let (mut af, mut bf) = (as_f(&a), as_f(&b));
    if r >= 0.5 {
        let pad = py::round(3.0 * r) as u32;
        let su = img::gaussian_blur(&take(upper, uh.saturating_sub(lap + pad), uh), r as f32);
        let su = take(&su, su.height() - lap, su.height());
        let sl = img::gaussian_blur(&take(lower, 0, (lap + pad).min(lower.height())), r as f32);
        let sl = take(&sl, 0, lap);
        let (suf, slf) = (as_f(&su), as_f(&sl));
        for y in 0..lap as usize {
            let wv = weights[y];
            for i in y * w as usize * 3..(y + 1) * w as usize * 3 {
                af[i] += (suf[i] - af[i]) * wv;
                bf[i] += (slf[i] - bf[i]) * (1.0 - wv);
            }
        }
    }
    for y in 0..lap as usize {
        let wv = weights[y];
        let dark = 1.0 - look.dark as f32 * (std::f32::consts::PI * wv).sin();
        for i in y * w as usize * 3..(y + 1) * w as usize * 3 {
            af[i] = (af[i] + (bf[i] - af[i]) * wv) * dark;
        }
    }
    a.as_mut().iter_mut().zip(&af).for_each(|(d, &v)| *d = py::u8c(v));
    b.as_mut().fill(0);
    a
}

pub fn framed(edit: &Edit, head: &Edit) -> Edit {
    Edit { format: head.format.clone(), size: head.size.clone(), join: None, ..edit.clone() }
}

pub fn laps_of(hs: &[u32], seams: &[Seam]) -> Vec<u32> {
    seams.iter().zip(hs.windows(2)).map(|(s, p)| py::round(s.fade.clamp(0.0, 0.5) * p[0].min(p[1]) as f64) as u32).collect()
}

pub fn inset(laps: &[u32], k: usize) -> (u32, u32) {
    (if k > 0 { laps[k - 1] / 2 } else { 0 }, if k < laps.len() { laps[k] / 2 } else { 0 })
}

#[derive(Clone, Debug, Default, PartialEq)]
pub struct Layout {
    pub tops: Vec<u32>,
    pub heights: Vec<u32>,
    pub laps: Vec<u32>,
    pub chats: Vec<(usize, Found)>,
    pub spans: Vec<(i64, i64)>,
    pub names: Vec<String>,
    pub pads: Vec<i64>,
    pub margins: Vec<i64>,
}

pub fn stack(frames: &[RgbImage], seams: &[Seam]) -> (RgbImage, Layout) {
    let hs: Vec<u32> = frames.iter().map(|f| f.height()).collect();
    let laps = laps_of(&hs, seams);
    let mut tops = vec![0u32];
    for (h, lap) in hs.iter().zip(&laps) {
        tops.push(tops[tops.len() - 1] + h - lap);
    }
    let total = tops[tops.len() - 1] + hs[hs.len() - 1];
    let mut out = RgbImage::new(frames[0].width(), total);
    for (f, &top) in frames.iter().zip(&tops) {
        image::imageops::replace(&mut out, f, 0, top as i64);
    }
    for (i, &lap) in laps.iter().enumerate() {
        if lap > 0 {
            let s = seam(&frames[i], &frames[i + 1], lap, &seams[i]);
            image::imageops::replace(&mut out, &s, 0, tops[i + 1] as i64);
        }
    }
    (out, Layout { tops, heights: hs, laps, ..Layout::default() })
}

pub fn lut_of(edit: &Edit, src: Option<&Path>) -> Option<Arc<Lut>> {
    static CACHE: OnceLock<Mutex<Vec<((PathBuf, Option<SystemTime>), Arc<Lut>)>>> = OnceLock::new();
    let name = edit.lut.as_deref().filter(|n| !n.is_empty())?;
    let path = src?.parent()?.join(LUT_DIR).join(name);
    let stamp = std::fs::metadata(&path).ok()?.modified().ok();
    let key = (path.clone(), stamp);
    let cache = CACHE.get_or_init(|| Mutex::new(Vec::new()));
    if let Some((_, hit)) = cache.lock().unwrap().iter().find(|(k, _)| *k == key) {
        return Some(hit.clone());
    }
    let text = String::from_utf8_lossy(&std::fs::read(&path).ok()?).into_owned();
    let lut = Arc::new(styles::read_cube(&text).ok()?);
    let mut cache = cache.lock().unwrap();
    if cache.len() >= 8 {
        cache.remove(0);
    }
    cache.push((key, lut.clone()));
    Some(lut)
}

pub fn styled(frame: &RgbImage, edit: &Edit, when: Option<NaiveDateTime>, src: Option<&Path>) -> (RgbImage, Vec<Box4>) {
    let lut = lut_of(edit, src);
    let graded = styles::grade(frame, edit.preset.as_deref(), edit.look.as_ref(), lut.as_deref());
    let graded = styles::grain(graded, edit.look.as_ref().and_then(|l| l.get(styles::GRAIN)).copied().unwrap_or(0.0));
    styles::apply(graded, edit.style.as_deref(), when, edit.style_text.as_deref())
}

pub struct Member<'a> {
    pub name: String,
    pub bg: &'a RgbImage,
    pub rows: &'a [Row],
    pub edit: &'a Edit,
    pub src: PathBuf,
}

pub struct SceneInput<'a> {
    pub members: Vec<Option<Member<'a>>>,
    pub seams: Vec<Seam>,
    pub homes: Vec<Vec<usize>>,
    pub names: Vec<String>,
}

pub fn render(bg: &RgbImage, rows: &[Row], edit: &Edit, src: Option<&Path>, rough: Option<u8>,
              scene: Option<&SceneInput<'_>>, layout: Option<&mut Layout>, when: Option<NaiveDateTime>)
              -> Result<(RgbImage, usize), String> {
    if let Some(r) = rows.first() {
        if bg.width() as usize != r.screen_w {
            return Err(format!("фон шириной {} px, а чат снят на экране {} px", bg.width(), r.screen_w));
        }
    }
    let Some(scene) = scene else {
        let (frame, p) = backdrop(bg, edit, src, None);
        let (mut frame, marks) = styled(&frame, edit, when, src);
        if let Some(q) = rough {
            frame = jpeg_pass(&frame, q);
        }
        let groups = parts(rows, edit).len();
        let mut taken = vec![marks];
        let painted = paint_chat(&mut frame, rows, edit, &p, &vec![None; groups], &mut taken, &vec![0; groups], None);
        return Ok((frame, painted));
    };
    let head = framed(edit, edit);
    let (frame, p) = backdrop(bg, &head, src, None);
    let mut frames: Vec<(RgbImage, Plan, &[Row], &Edit)> = Vec::new();
    let mut marks: Vec<Vec<Box4>> = Vec::new();
    for other in &scene.members {
        let (f, q, r, e, t) = match other {
            None => (frame.clone(), p, rows, edit, when),
            Some(m) => {
                let (f, q) = backdrop(m.bg, &framed(m.edit, edit), Some(&m.src), Some(frame.width()));
                (f, q, m.rows, m.edit, shot_time(&m.name))
            }
        };
        let (f, b) = styled(&f, edit, t, src);
        frames.push((f, q, r, e));
        marks.push(b);
    }
    let images: Vec<RgbImage> = frames.iter().map(|(f, ..)| f.clone()).collect();
    let (mut out, mut where_) = stack(&images, &scene.seams);
    if let Some(q) = rough {
        out = jpeg_pass(&out, q);
    }
    let mut spans = Vec::new();
    let mut taken: Vec<Vec<Box4>> = Vec::new();
    for (k, (f, ..)) in frames.iter().enumerate() {
        let (a, b) = inset(&where_.laps, k);
        let top = where_.tops[k] as i64;
        spans.push((top + a as i64, top + f.height() as i64 - b as i64));
        taken.push(marks[k].iter().map(|m| [m[0], m[1] - a as i64, m[2], m[3] - a as i64]).collect());
    }
    let mut painted = 0;
    let mut chats = Vec::new();
    for (k, (_, q, r, e)) in frames.iter().enumerate() {
        let want = cuts(r.len(), e).len() + 1;
        let mut at = scene.homes.get(k).cloned().unwrap_or_else(|| vec![k]);
        if at.is_empty() {
            at.push(k);
        }
        while at.len() < want {
            at.push(at[at.len() - 1]);
        }
        at.truncate(want);
        let wins: Vec<Option<(i64, i64)>> = at.iter().map(|&h| spans.get(h).copied()).collect();
        let mut found = Vec::new();
        let n = paint_chat(&mut out, r, e, q, &wins, &mut taken, &at, Some(&mut found));
        chats.extend(found.into_iter().map(|f| (k, f)));
        if std::ptr::eq(*e, edit) {
            painted = n;
        }
    }
    if let Some(layout) = layout {
        where_.chats = chats;
        where_.spans = spans;
        where_.names = scene.names.clone();
        where_.pads = frames.iter().map(|(_, q, ..)| q.outline + 2).collect();
        where_.margins = frames.iter().map(|(_, q, ..)| q.margin).collect();
        *layout = where_;
    }
    Ok((out, painted))
}

pub fn shot_time(name: &str) -> Option<NaiveDateTime> {
    let part = name.get(3..22)?;
    NaiveDateTime::parse_from_str(part, "%Y-%m-%d_%H-%M-%S").ok()
}

pub fn add_overlay(out: &Path, name: &str, image: &RgbaImage) -> Result<Overlay, String> {
    let src = out.join("src");
    std::fs::create_dir_all(&src).map_err(|e| e.to_string())?;
    let prefix = format!("{name}_ov");
    let taken = std::fs::read_dir(&src)
        .map_err(|e| e.to_string())?
        .filter_map(|e| e.ok())
        .filter_map(|e| {
            let stem = e.path().file_stem()?.to_string_lossy().into_owned();
            stem.strip_prefix(&prefix)?.parse::<u32>().ok()
        })
        .max()
        .unwrap_or(0);
    let (w, h) = image.dimensions();
    let mut pic = image.clone();
    if w > 2560 || h > 2560 {
        let k = (2560.0 / w as f64).min(2560.0 / h as f64);
        pic = img::resize_rgba(image, py::round(w as f64 * k).max(1) as u32, py::round(h as f64 * k).max(1) as u32, Filter::Lanczos);
    }
    let sticker = pic.pixels().any(|p| p[3] < 255);
    let file = format!("{name}_ov{}.{}", taken + 1, if sticker { "png" } else { "jpg" });
    let path = src.join(&file);
    if sticker {
        pic.save(&path).map_err(|e| e.to_string())?;
    } else {
        let rgb = img::to_rgb(&pic);
        let mut buf = Vec::new();
        jpeg_encoder::Encoder::new(&mut buf, 95)
            .encode(rgb.as_raw(), rgb.width() as u16, rgb.height() as u16, jpeg_encoder::ColorType::Rgb)
            .map_err(|e| e.to_string())?;
        std::fs::write(&path, buf).map_err(|e| e.to_string())?;
    }
    Ok(Overlay {
        file,
        x: if sticker { 0.7 } else { 0.72 },
        y: 0.68,
        w: if sticker { 0.4 } else { 0.6 },
        crop: [0.0, 0.0, 1.0, 1.0],
        cut: "free".into(),
        soft: if sticker { 0.0 } else { 0.4 },
        alpha: 1.0,
        flip: None,
        angle: None,
        extra: Default::default(),
    })
}

pub fn fit_field(ov: &mut Overlay, p: &Plan, src: (u32, u32)) {
    let Some((mut l, mut t, mut r, mut b)) = p.ext_box else { return };
    let (w_out, h_out) = (p.size.0 as i64, p.size.1 as i64);
    let lap;
    if r - l == w_out {
        lap = py::round((b - t) as f64 * 0.5);
        if t == 0 { b += lap } else { t -= lap }
    } else {
        lap = py::round((r - l) as f64 * 0.5);
        if l == 0 { r += lap } else { l -= lap }
    }
    let (w, h) = ((r - l) as f64, (b - t) as f64);
    ov.crop = crop_for(src, Some(w / h), [0.0, 0.0, 1.0, 1.0]);
    ov.cut = "free".into();
    ov.w = py::round_to(w / w_out as f64, 4);
    ov.x = py::round_to((l + r) as f64 / 2.0 / w_out as f64, 4);
    ov.y = py::round_to((t + b) as f64 / 2.0 / h_out as f64, 4);
    ov.soft = py::round_to((2.0 * lap as f64 / w.min(h)).min(1.0), 3);
}

pub fn add_lut(out: &Path, path: &Path) -> Result<String, String> {
    let data = std::fs::read(path).map_err(|e| e.to_string())?;
    styles::read_cube(&String::from_utf8_lossy(&data))?;
    let folder = out.join(LUT_DIR);
    std::fs::create_dir_all(&folder).map_err(|e| e.to_string())?;
    let raw_stem = path.file_stem().map(|s| s.to_string_lossy().into_owned()).unwrap_or_default();
    let mut stem = String::new();
    let mut gap = false;
    for c in raw_stem.chars() {
        if c.is_alphanumeric() || c == '_' || c == '.' || c == '-' {
            stem.push(c);
            gap = false;
        } else if !gap {
            stem.push('_');
            gap = true;
        }
    }
    stem = stem.chars().take(60).collect();
    if stem.is_empty() {
        stem = "lut".into();
    }
    let mut k = 1;
    let mut target = folder.join(format!("{stem}.cube"));
    while target.exists() && std::fs::read(&target).map_err(|e| e.to_string())? != data {
        k += 1;
        target = folder.join(format!("{stem}_{k}.cube"));
    }
    if !target.exists() {
        std::fs::write(&target, &data).map_err(|e| e.to_string())?;
    }
    Ok(target.file_name().unwrap().to_string_lossy().into_owned())
}
