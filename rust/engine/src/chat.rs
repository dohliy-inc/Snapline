use std::collections::HashSet;
use std::sync::Arc;
use std::sync::atomic::{AtomicU64, Ordering};

use image::{RgbImage, RgbaImage};

use crate::edit::{Coord, Pos};
use crate::img::{self, Filter};
use crate::py::{self, median, runs};

pub const INK: f32 = 60.0;
pub const BLACK: u8 = 6;
pub const CHAT_SHOT_BLACK: f64 = 0.9;
pub const CHAT_COLUMN: f64 = 0.4;
pub const CHAT_GAP: f64 = 3.0;
pub const WRAP_SHARE: f64 = 0.22;
pub const WORD_GAP: f64 = 0.18;
pub const SAME_ROW: f32 = 0.08;
pub const TAG_TOP: f64 = 0.52;
pub const TAG_DROP: f64 = 0.12;
pub const TAG_COLOR: f32 = 30.0;

#[derive(Clone, Copy, Debug, PartialEq, Eq, Hash)]
pub enum Kind {
    Speech,
    Action,
    Ame,
    System,
    Ooc,
}

impl Kind {
    pub const ALL: [Kind; 5] = [Kind::Speech, Kind::Action, Kind::Ame, Kind::System, Kind::Ooc];

    pub fn label(self) -> &'static str {
        match self {
            Kind::Speech => "речь",
            Kind::Action => "действие",
            Kind::Ame => "над головой",
            Kind::System => "система",
            Kind::Ooc => "OOC",
        }
    }

    pub fn from_label(text: &str) -> Option<Kind> {
        let low = text.trim().to_lowercase();
        Kind::ALL.into_iter().find(|k| k.label().to_lowercase() == low)
    }
}

pub type Span = (usize, usize);

static NEXT_UID: AtomicU64 = AtomicU64::new(1);

#[derive(Clone, Debug)]
pub struct Row {
    pub uid: u64,
    pub y0: usize,
    pub base: usize,
    pub pitch: f64,
    pub screen_w: usize,
    pub h: usize,
    pub w: usize,
    pub ink: Arc<Vec<bool>>,
    pub glyphs: Vec<Span>,
    pub rgb: Arc<Vec<f32>>,
    pub lum: Arc<Vec<f32>>,
    pub profile: Arc<Vec<f32>>,
    pub kind: Kind,
    pub body: [f32; 3],
    pub keep: bool,
    pub cont: bool,
    pub mark: Option<char>,
    pub hide: Option<Vec<Span>>,
    pub drop: Vec<Span>,
    pub cut: bool,
}

impl Row {
    fn ink_at(&self, y: usize, x: usize) -> bool {
        self.ink[y * self.w + x]
    }

    fn ink_rows(&self, a: usize, b: usize) -> Vec<usize> {
        let b = b.min(self.w.saturating_sub(1));
        (0..self.h).filter(|&y| (a..=b).any(|x| self.ink_at(y, x))).collect()
    }

    fn col(&self, x: usize) -> Vec<usize> {
        (0..self.h).filter(|&y| self.ink_at(y, x)).collect()
    }

    pub fn hidden(&self) -> &[Span] {
        self.hide.as_deref().unwrap_or(&[])
    }
}

pub fn lum8(img: &RgbImage) -> Vec<u8> {
    img.pixels().map(|p| p[0].max(p[1]).max(p[2])).collect()
}

pub fn is_chat_shot(img: &RgbImage) -> bool {
    let lum = lum8(img);
    let dark = lum.iter().filter(|&&v| v <= BLACK).count();
    dark as f64 / lum.len().max(1) as f64 > CHAT_SHOT_BLACK
}

fn block_of(any_rows: &[bool]) -> (Vec<Span>, f64) {
    let lines = runs(any_rows.iter().copied());
    if lines.is_empty() {
        return (vec![], 0.0);
    }
    let tall = median(&lines.iter().map(|(a, b)| (b - a + 1) as f64).collect::<Vec<_>>());
    let mut fused: Vec<Span> = Vec::new();
    for &(a, b) in &lines {
        if let Some(last) = fused.last_mut() {
            if ((last.1 - last.0 + 1) as f64) < 0.4 * tall && a as i64 - last.1 as i64 <= 3 {
                last.1 = b;
                continue;
            }
        }
        fused.push((a, b));
    }
    let mut block = vec![fused[0]];
    for &(a, b) in &fused[1..] {
        let (pa, pb) = *block.last().unwrap();
        if a as i64 - pb as i64 > 3 * (pb as i64 - pa as i64 + 4) {
            break;
        }
        block.push((a, b));
    }
    let pitch = if block.len() > 1 {
        median(&block.windows(2).map(|w| (w[1].0 - w[0].0) as f64).collect::<Vec<_>>())
    } else {
        1.3 * (block[0].1 - block[0].0 + 1) as f64
    };
    (block, pitch)
}

fn chat_right(ink: &[bool], width: usize, block: &[Span], pitch: f64) -> usize {
    let (y0, y1) = (block[0].0, block[block.len() - 1].1);
    let cols = runs((0..width).map(|x| (y0..=y1).any(|y| ink[y * width + x])));
    let mut right = cols[0].1;
    for &(a, b) in &cols[1..] {
        if a as f64 - right as f64 > CHAT_GAP * pitch {
            break;
        }
        right = b;
    }
    right + 1
}

pub fn extract_rows(img: &RgbImage) -> Vec<Row> {
    let (width, height) = (img.width() as usize, img.height() as usize);
    let lum = lum8(img);
    let ink: Vec<bool> = lum.iter().map(|&v| v as f32 > INK).collect();
    let limit = (width as f64 * CHAT_COLUMN) as usize;
    let any: Vec<bool> = (0..height).map(|y| ink[y * width..y * width + limit].iter().any(|&v| v)).collect();
    let (block, pitch) = block_of(&any);
    if block.is_empty() {
        return vec![];
    }
    let right = chat_right(&ink, width, &block, pitch);
    let top = (block[0].0 as i64 - py::round(pitch)).max(0) as usize;
    let bottom = ((block[block.len() - 1].1 as i64 + py::round(pitch) + 1) as usize).min(height);
    let h = bottom - top;
    let mut rgb = vec![0f32; h * width * 3];
    let raw = img.as_raw();
    for y in 0..h {
        for x in 0..right {
            for c in 0..3 {
                rgb[(y * width + x) * 3 + c] = raw[((top + y) * width + x) * 3 + c] as f32;
            }
        }
    }
    let shade: Vec<f32> = rgb.chunks_exact(3).map(|p| p[0].max(p[1]).max(p[2])).collect();
    let ink: Vec<bool> = shade.iter().map(|&v| v > INK).collect();
    let any: Vec<bool> = (0..h).map(|y| ink[y * width..(y + 1) * width].iter().any(|&v| v)).collect();
    let (block, pitch) = block_of(&any);
    let mut rows = Vec::new();
    for (a, b) in block {
        let rh = b - a + 1;
        let rink = ink[a * width..(b + 1) * width].to_vec();
        let dense: Vec<usize> = (0..rh).map(|y| rink[y * width..(y + 1) * width].iter().filter(|&&v| v).count()).collect();
        let peak = *dense.iter().max().unwrap_or(&0) as f64;
        let base = (0..rh).rev().find(|&y| dense[y] as f64 >= 0.5 * peak).unwrap_or(0);
        let rlum = shade[a * width..(b + 1) * width].to_vec();
        let mut profile = vec![0f32; width];
        for y in 0..rh {
            for x in 0..width {
                profile[x] += rlum[y * width + x];
            }
        }
        let glyphs = runs((0..width).map(|x| (0..rh).any(|y| rink[y * width + x])));
        rows.push(Row {
            uid: NEXT_UID.fetch_add(1, Ordering::Relaxed),
            y0: top + a,
            base,
            pitch,
            screen_w: width,
            h: rh,
            w: width,
            ink: Arc::new(rink),
            glyphs,
            rgb: Arc::new(rgb[a * width * 3..(b + 1) * width * 3].to_vec()),
            lum: Arc::new(rlum),
            profile: Arc::new(profile),
            kind: Kind::Speech,
            body: [0.0; 3],
            keep: false,
            cont: false,
            mark: None,
            hide: None,
            drop: vec![],
            cut: false,
        });
    }
    rows
}

fn prefix(row: &Row) -> Option<char> {
    let pitch = row.pitch;
    let (a, b) = row.glyphs[0];
    let ys = row.ink_rows(a, b);
    let (ys0, ys1) = (ys[0], ys[ys.len() - 1]);
    let h = (ys1 - ys0 + 1) as f64;
    let w = (b - a + 1) as f64;
    let gap = if row.glyphs.len() > 1 { (row.glyphs[1].0 as f64) - b as f64 - 1.0 } else { pitch };
    let base = row.base as f64;
    let stem = row.col(a);
    if !stem.is_empty() {
        let (s0, s1) = (stem[0] as f64, stem[stem.len() - 1] as f64);
        if s0 <= base - TAG_TOP * pitch && s1 >= base + TAG_DROP * pitch && stem.len() as f64 >= 0.9 * (s1 - s0 + 1.0) {
            return Some('[');
        }
    }
    if h > 0.7 * pitch && w < 0.6 * pitch {
        let left: Vec<f64> = row.col(a).iter().map(|&y| y as f64 - ys0 as f64).collect();
        let right: Vec<f64> = row.col(b).iter().map(|&y| y as f64 - ys0 as f64).collect();
        if left.len() as f64 >= 0.8 * h {
            return Some('[');
        }
        if !left.is_empty() && !right.is_empty() {
            let (lmin, lmax) = min_max(&left);
            let (rmin, rmax) = min_max(&right);
            if lmin > 0.2 * h && lmax < 0.8 * h && rmin < 0.2 * h && rmax > 0.8 * h
                && !right.iter().any(|&v| v > 0.25 * h && v < 0.75 * h) {
                return Some('(');
            }
        }
    }
    if h < 0.4 * pitch && (ys1 as f64) - base < -0.25 * pitch {
        return Some('*');
    }
    if gap >= 0.15 * pitch && w < 0.65 * pitch {
        let left: Vec<f64> = row.col(a).iter().map(|&y| y as f64).collect();
        let right: Vec<f64> = row.col(b).iter().map(|&y| y as f64).collect();
        let mid = (ys0 + ys1) as f64 / 2.0;
        if !left.is_empty() && !right.is_empty() {
            let (lmin, lmax) = min_max(&left);
            let (rmin, rmax) = min_max(&right);
            let mean = right.iter().sum::<f64>() / right.len() as f64;
            if lmin <= ys0 as f64 + 1.0 && lmax >= ys1 as f64 - 1.0 && (mean - mid).abs() < 0.15 * pitch
                && rmax - rmin < 0.5 * h {
                return Some('>');
            }
        }
    }
    None
}

fn min_max(v: &[f64]) -> (f64, f64) {
    v.iter().fold((f64::INFINITY, f64::NEG_INFINITY), |(lo, hi), &x| (lo.min(x), hi.max(x)))
}

fn strong(row: &Row, a: usize, b: usize) -> Vec<[f32; 3]> {
    let b = b.min(row.w - 1);
    let mut peak = f32::NEG_INFINITY;
    for y in 0..row.h {
        for x in a..=b {
            peak = peak.max(row.lum[y * row.w + x]);
        }
    }
    let mut out = Vec::new();
    for y in 0..row.h {
        for x in a..=b {
            if row.lum[y * row.w + x] > 0.8 * peak {
                let i = (y * row.w + x) * 3;
                out.push([row.rgb[i], row.rgb[i + 1], row.rgb[i + 2]]);
            }
        }
    }
    out
}

fn mean3(px: &[[f32; 3]]) -> [f32; 3] {
    let n = px.len().max(1) as f64;
    let mut s = [0f64; 3];
    for p in px {
        for c in 0..3 {
            s[c] += p[c] as f64;
        }
    }
    if px.is_empty() { [f32::NAN; 3] } else { s.map(|v| (v / n) as f32) }
}

fn pink(c: [f32; 3]) -> bool {
    c[2] > c[1] + 20.0 && c[0] > c[1] + 10.0
}

fn red(c: [f32; 3]) -> bool {
    c[0] > 150.0 && c[1] < 0.6 * c[0] && c[2] < 0.6 * c[0]
}

fn orange_share(px: &[[f32; 3]]) -> f64 {
    let n = px.iter().filter(|p| p[0] > 200.0 && p[1] > 90.0 && p[1] < 170.0 && p[2] < 90.0).count();
    n as f64 / px.len().max(1) as f64
}

fn tagged(row: &Row) -> Option<[f32; 3]> {
    let spans = words(row);
    if spans.len() < 2 {
        return None;
    }
    let tag = mean3(&strong(row, spans[0].0, spans[0].1));
    let rest = mean3(&strong(row, spans[1].0, spans[spans.len() - 1].1));
    let warm = tag[0] > 180.0 && tag[2] < tag[0].min(tag[1]) - 40.0;
    let diff = (0..3).map(|c| (tag[c] - rest[c]).abs()).fold(0f32, f32::max);
    if warm && diff > TAG_COLOR { Some(rest) } else { None }
}

pub fn classify(mut rows: Vec<Row>, keep: &[Kind]) -> Vec<Row> {
    let mut prev: Option<(usize, [f32; 3], Kind)> = None;
    for row in rows.iter_mut() {
        let mark = prefix(row);
        let px = strong(row, row.glyphs[0].0, row.w - 1);
        let mut body = mean3(&px);
        let tail = if mark == Some('[') { tagged(row) } else { None };
        let mut kind = if let Some(t) = tail {
            body = t;
            Kind::System
        } else if mark == Some('>') {
            if pink(body) { Kind::Ame } else { Kind::System }
        } else if mark == Some('(') {
            Kind::Ooc
        } else if red(body) || orange_share(&px) > 0.1 {
            Kind::System
        } else if mark == Some('*') || pink(body) {
            Kind::Action
        } else {
            Kind::Speech
        };
        let cont = match (mark, prev) {
            (None, Some((end, pbody, _))) => {
                end as f64 >= WRAP_SHARE * row.screen_w as f64
                    && (0..3).map(|c| (body[c] - pbody[c]).abs()).fold(0f32, f32::max) < 10.0
            }
            _ => false,
        };
        if cont {
            kind = prev.unwrap().2;
        }
        row.kind = kind;
        row.body = body;
        row.keep = keep.contains(&kind);
        row.cont = cont;
        row.mark = mark;
        prev = Some((row.glyphs[row.glyphs.len() - 1].1, body, kind));
    }
    rows
}

pub fn words(row: &Row) -> Vec<Span> {
    let mut spans: Vec<Span> = Vec::new();
    for &(a, b) in &row.glyphs {
        if let Some(last) = spans.last_mut() {
            if ((a as f64) - last.1 as f64 - 1.0) < WORD_GAP * row.pitch {
                last.1 = b;
                continue;
            }
        }
        spans.push((a, b));
    }
    spans
}

fn star_end(row: &Row, a: usize, b: usize) -> usize {
    for &(ga, gb) in &row.glyphs {
        if ga < a || gb > b {
            continue;
        }
        let ys = row.ink_rows(ga, gb);
        if let (Some(&y0), Some(&y1)) = (ys.first(), ys.last()) {
            if ((y1 - y0 + 1) as f64) < 0.4 * row.pitch && (y1 as f64) - (row.base as f64) < -0.25 * row.pitch {
                return gb + 1;
            }
        }
        return a;
    }
    a
}

pub fn nick_spans(rows: &[Row]) -> Vec<Vec<Span>> {
    let mut found = Vec::new();
    let mut start: Option<usize> = None;
    for (i, r) in rows.iter().enumerate() {
        if !r.cont {
            start = Some(i);
        }
        let w = words(r);
        let mut spans: Vec<(usize, usize)> = Vec::new();
        if !r.cont && w.len() >= 3 {
            if r.kind == Kind::Speech {
                spans = w[..2].to_vec();
            } else if r.kind == Kind::Action && r.mark == Some('*') {
                spans = w[1..3].to_vec();
            }
        }
        let last = i + 1 == rows.len() || !rows[i + 1].cont;
        if spans.is_empty() && last && r.kind == Kind::Action && w.len() >= 3
            && start.is_some_and(|s| rows[s].mark != Some('*')) {
            let (a, b) = w[w.len() - 2];
            let tail = w[w.len() - 1];
            spans = vec![(star_end(r, a, b), b), tail];
        }
        found.push(spans.into_iter().filter(|(a, b)| b >= a).collect());
    }
    found
}

fn dropped(row: &Row) -> Vec<(usize, usize)> {
    let gone: HashSet<Span> = row.drop.iter().copied().collect();
    let spans = words(row);
    let mut cols = Vec::new();
    for (j, &(a, b)) in spans.iter().enumerate() {
        if !gone.contains(&(a, b)) {
            continue;
        }
        if j + 1 < spans.len() {
            cols.push((a, spans[j + 1].0));
        } else if j > 0 && !gone.contains(&spans[j - 1]) {
            cols.push((spans[j - 1].1 + 1, b + 1));
        } else {
            cols.push((a, b + 1));
        }
    }
    cols
}

pub fn masked(row: &Row, preview: bool) -> Vec<f32> {
    if row.hidden().is_empty() && row.drop.is_empty() {
        return row.rgb.as_ref().clone();
    }
    let (w, h) = (row.w, row.h);
    let mut rgb = row.rgb.as_ref().clone();
    let color = row.body.map(|c| c.clamp(0.0, 255.0));
    for &(a, b) in row.hidden() {
        if a >= w {
            continue;
        }
        let b = b.min(w - 1);
        let ys = row.ink_rows(a, b);
        for y in 0..h {
            for x in a..=b {
                rgb[(y * w + x) * 3..(y * w + x) * 3 + 3].fill(0.0);
            }
        }
        if let Some(&y0) = ys.first() {
            for y in y0..=row.base.min(h - 1) {
                for x in a..=b {
                    rgb[(y * w + x) * 3..(y * w + x) * 3 + 3].copy_from_slice(&color);
                }
            }
        }
    }
    if preview {
        for &(a, b) in &row.drop {
            for y in 0..h {
                for x in a..=b.min(w - 1) {
                    for c in 0..3 {
                        rgb[(y * w + x) * 3 + c] *= 0.3;
                    }
                }
            }
        }
        return rgb;
    }
    let mut keep = vec![true; w];
    for (a, b) in dropped(row) {
        for k in keep.iter_mut().take(b.min(w)).skip(a) {
            *k = false;
        }
    }
    let cols: Vec<usize> = (0..w).filter(|&x| keep[x]).collect();
    let mut out = vec![0f32; rgb.len()];
    for y in 0..h {
        for (nx, &x) in cols.iter().enumerate() {
            out[(y * w + nx) * 3..(y * w + nx) * 3 + 3].copy_from_slice(&rgb[(y * w + x) * 3..(y * w + x) * 3 + 3]);
        }
    }
    out
}

pub fn same_row(a: &Row, b: &Row) -> bool {
    if a.profile.len() != b.profile.len() {
        return false;
    }
    let diff: f32 = a.profile.iter().zip(b.profile.iter()).map(|(x, y)| (x - y).abs()).sum();
    let total: f32 = a.profile.iter().sum::<f32>() + b.profile.iter().sum::<f32>();
    diff / total.max(1.0) < SAME_ROW
}

fn overlap(a: &[Row], b: &[Row]) -> usize {
    for k in (1..=a.len().min(b.len())).rev() {
        if (0..k).all(|i| same_row(&a[a.len() - k + i], &b[i])) {
            return k;
        }
    }
    0
}

pub fn merge(rows: Vec<Row>, new: Vec<Row>) -> Vec<Row> {
    let n = new.len();
    if n == 0 || (n <= rows.len() && (0..=rows.len() - n).any(|i| (0..n).all(|j| same_row(&rows[i + j], &new[j])))) {
        return rows;
    }
    let after = overlap(&rows, &new);
    let before = overlap(&new, &rows);
    if before > after {
        let mut out: Vec<Row> = new.into_iter().take(n - before).collect();
        out.extend(rows);
        out
    } else {
        let mut out = rows;
        out.extend(new.into_iter().skip(after));
        out
    }
}

pub fn frame_rect(width: i64, height: i64, ratio: Option<f64>, zoom: f64, center: [f64; 2]) -> (i64, i64, i64, i64) {
    let (w, h) = match ratio {
        None => (width, height),
        Some(r) => {
            if (width as f64) / (height as f64) < r {
                (width, py::round(width as f64 / r))
            } else {
                (py::round(height as f64 * r), height)
            }
        }
    };
    let w = py::round(w as f64 / zoom).max(1);
    let h = py::round(h as f64 / zoom).max(1);
    let x0 = py::round(center[0] * width as f64 - w as f64 / 2.0).max(0).min(width - w);
    let y0 = py::round(center[1] * height as f64 - h as f64 / 2.0).max(0).min(height - h);
    (x0, y0, x0 + w, y0 + h)
}

pub fn messages(rows: &[Row]) -> Vec<Vec<usize>> {
    let mut groups: Vec<Vec<usize>> = Vec::new();
    for (i, r) in rows.iter().enumerate() {
        match groups.last_mut() {
            Some(g) if r.cont => g.push(i),
            _ => groups.push(vec![i]),
        }
    }
    groups
}

struct Line {
    rgb: Vec<f32>,
    h: usize,
    w: usize,
    base: usize,
    n: usize,
}

fn pieces(row: &Row, space: i64) -> Vec<(Vec<f32>, usize, usize, i64)> {
    let mut plain = row.clone();
    plain.drop.clear();
    let rgb = masked(&plain, false);
    let gone: HashSet<Span> = row.drop.iter().copied().collect();
    let spans = words(row);
    let mut out = Vec::new();
    for (j, &(a, b)) in spans.iter().enumerate() {
        if gone.contains(&(a, b)) {
            continue;
        }
        let gap = if j + 1 < spans.len() { spans[j + 1].0 as i64 - b as i64 - 1 } else { space };
        let cw = b - a + 1;
        let mut cols = vec![0f32; row.h * cw * 3];
        for y in 0..row.h {
            cols[y * cw * 3..(y + 1) * cw * 3].copy_from_slice(&rgb[(y * row.w + a) * 3..(y * row.w + b + 1) * 3]);
        }
        out.push((cols, cw, row.base, gap));
    }
    out
}

fn flow(rows: &[Row], group: &[usize], limit: usize) -> Vec<Line> {
    let kept: Vec<&Row> = group.iter().map(|&i| &rows[i]).filter(|r| r.keep).collect();
    if kept.len() < 2 || !kept.iter().any(|r| !r.drop.is_empty()) {
        return kept.iter().map(|r| Line { rgb: masked(r, false), h: r.h, w: r.w, base: r.base, n: 1 }).collect();
    }
    let head = kept.iter().map(|r| r.base).max().unwrap();
    let tall = head + kept.iter().map(|r| r.h - r.base).max().unwrap();
    let width = kept[0].w;
    let x0 = kept.iter().map(|r| r.glyphs[0].0).min().unwrap();
    let spans: Vec<Vec<Span>> = kept.iter().map(|r| words(r)).collect();
    let gaps: Vec<f64> =
        spans.iter().flat_map(|w| w.windows(2).map(|p| (p[1].0 as f64) - p[0].1 as f64 - 1.0)).collect();
    let space = if gaps.is_empty() { py::round(0.3 * kept[0].pitch) } else { median(&gaps) as i64 };
    let mut lines: Vec<Vec<f32>> = Vec::new();
    let mut x = 0usize;
    for r in &kept {
        for (cols, cw, base, gap) in pieces(r, space) {
            if lines.is_empty() || x + cw > limit {
                lines.push(vec![0f32; tall * width * 3]);
                x = x0;
            }
            let line = lines.last_mut().unwrap();
            let rh = cols.len() / (cw * 3);
            for y in 0..rh {
                let ty = head - base + y;
                for dx in 0..cw {
                    if x + dx < width {
                        let t = (ty * width + x + dx) * 3;
                        line[t..t + 3].copy_from_slice(&cols[(y * cw + dx) * 3..(y * cw + dx) * 3 + 3]);
                    }
                }
            }
            x = (x as i64 + cw as i64 + gap).max(0) as usize;
        }
    }
    let count = lines.len();
    lines.into_iter().enumerate().map(|(i, rgb)| Line {
        rgb,
        h: tall,
        w: width,
        base: head,
        n: 1 + if i + 1 == count { kept.len() - count } else { 0 },
    }).collect()
}

fn strip(lines: &[Line], pitch: f64, scale: f64, max_h: f64) -> (Option<(Vec<f32>, usize, usize)>, usize) {
    let head = lines.iter().map(|l| l.base).max().unwrap();
    let mut slots: Vec<(usize, &Line)> = Vec::new();
    let mut painted = 0;
    for (i, line) in lines.iter().enumerate() {
        let y0 = (head as i64 + py::round(i as f64 * pitch) - line.base as i64) as usize;
        if ((y0 + line.h) as f64) * scale > max_h && !slots.is_empty() {
            break;
        }
        slots.push((y0, line));
        painted += line.n;
    }
    let h = slots.iter().map(|(y0, l)| y0 + l.h).max().unwrap();
    let w = lines[0].w;
    let mut out = vec![0f32; h * w * 3];
    for (y0, line) in &slots {
        for y in 0..line.h {
            let src = &line.rgb[y * line.w * 3..(y * line.w + w.min(line.w)) * 3];
            let dst = &mut out[(y0 + y) * w * 3..(y0 + y) * w * 3 + src.len()];
            for (d, s) in dst.iter_mut().zip(src) {
                *d = d.max(*s);
            }
        }
    }
    let ink: Vec<bool> = out.chunks_exact(3).map(|p| p[0].max(p[1]).max(p[2]) > 0.0).collect();
    let ys: Vec<usize> = (0..h).filter(|&y| ink[y * w..(y + 1) * w].iter().any(|&v| v)).collect();
    if ys.is_empty() {
        return (None, painted);
    }
    let xs: Vec<usize> = (0..w).filter(|&x| (0..h).any(|y| ink[y * w + x])).collect();
    let (y0, y1, x0, x1) = (ys[0], ys[ys.len() - 1], xs[0], xs[xs.len() - 1]);
    let (cw, ch) = (x1 - x0 + 1, y1 - y0 + 1);
    let mut cut = vec![0f32; cw * ch * 3];
    for y in 0..ch {
        cut[y * cw * 3..(y + 1) * cw * 3].copy_from_slice(&out[((y0 + y) * w + x0) * 3..((y0 + y) * w + x1 + 1) * 3]);
    }
    if scale != 1.0 {
        let small = RgbImage::from_raw(cw as u32, ch as u32, cut.iter().map(|&v| py::u8c(v)).collect()).unwrap();
        let nw = py::round(cw as f64 * scale).max(1) as u32;
        let nh = py::round(ch as f64 * scale).max(1) as u32;
        let big = img::resize(&small, nw, nh, Filter::Lanczos);
        return (Some((big.as_raw().iter().map(|&v| v as f32).collect(), nw as usize, nh as usize)), painted);
    }
    (Some((cut, cw, ch)), painted)
}

pub fn grow(a: &[f32], w: usize, h: usize, r: usize) -> Vec<f32> {
    if r == 0 {
        return a.to_vec();
    }
    let mut tmp = vec![0f32; w * h];
    for y in 0..h {
        for x in 0..w {
            let mut m = 0f32;
            for xx in x.saturating_sub(r)..=(x + r).min(w - 1) {
                m = m.max(a[y * w + xx]);
            }
            tmp[y * w + x] = m;
        }
    }
    let mut out = vec![0f32; w * h];
    for y in 0..h {
        for x in 0..w {
            let mut m = 0f32;
            for yy in y.saturating_sub(r)..=(y + r).min(h - 1) {
                m = m.max(tmp[yy * w + x]);
            }
            out[y * w + x] = m;
        }
    }
    out
}

pub struct Layer {
    pub image: RgbaImage,
    pub painted: usize,
    pub pad: usize,
}

pub fn chat_layer(rows: &[Row], outline: usize, scale: f64, max_h: Option<f64>) -> Option<Layer> {
    let limit = rows.iter().map(|r| r.glyphs[r.glyphs.len() - 1].1 + 1).max().unwrap_or(0);
    let lines: Vec<Line> = messages(rows).iter().flat_map(|g| flow(rows, g, limit)).collect();
    if lines.is_empty() {
        return None;
    }
    let pad = outline + 2;
    let room = match max_h {
        Some(m) if m != 0.0 => m - 2.0 * pad as f64,
        _ => f64::INFINITY,
    };
    let (cut, painted) = strip(&lines, rows[0].pitch, scale, room);
    let (rgb, cw, ch) = cut?;
    let (w, h) = (cw + 2 * pad, ch + 2 * pad);
    let mut padded = vec![0f32; w * h * 3];
    for y in 0..ch {
        padded[((y + pad) * w + pad) * 3..((y + pad) * w + pad + cw) * 3].copy_from_slice(&rgb[y * cw * 3..(y + 1) * cw * 3]);
    }
    let lum: Vec<f32> = padded.chunks_exact(3).map(|p| p[0].max(p[1]).max(p[2])).collect();
    let peak = grow(&lum, w, h, 2);
    let a: Vec<f32> = lum.iter().zip(&peak).map(|(&l, &p)| if p > INK { l / p.max(1.0) } else { 0.0 }).collect();
    let ring = if outline > 0 { grow(&a, w, h, outline) } else { vec![0f32; w * h] };
    let mut layer = RgbaImage::new(w as u32, h as u32);
    for (i, px) in layer.pixels_mut().enumerate() {
        let ai = a[i];
        let cover = ai + ring[i] * (1.0 - ai);
        for c in 0..3 {
            let color = (padded[i * 3 + c] / ai.max(1e-3)).min(255.0);
            let straight = if cover > 0.0 { color * ai / cover.max(1e-6) } else { 0.0 };
            px[c] = py::u8c(straight);
        }
        px[3] = py::u8c(cover * 255.0);
    }
    Some(Layer { image: layer, painted, pad })
}

fn axis(c: &Coord, size: f64, near: &str, far: &str, margin: i64, pad: i64, len: i64) -> i64 {
    match c {
        Coord::Side(s) if s == near => margin - pad,
        Coord::Side(s) if s == far => size as i64 - margin + pad - len,
        Coord::Side(_) => margin - pad,
        Coord::Num(v) => py::round(v * size) - pad,
    }
}

pub fn place(width: i64, height: i64, lw: i64, lh: i64, pad: i64, pos: &Pos, margin: i64) -> (i64, i64) {
    let (x, y) = pos.axes();
    let left = axis(&x, width as f64, "left", "right", margin, pad, lw);
    let top = axis(&y, height as f64, "top", "bottom", margin, pad, lh);
    let left = left.max(-pad).min((width - lw + pad).max(-pad));
    let top = top.max(-pad).min((height - lh + pad).max(-pad));
    (left, top)
}

pub fn blend(frame: &mut RgbImage, layer: &RgbaImage, left: i64, top: i64) {
    let (fw, fh) = (frame.width() as i64, frame.height() as i64);
    let (lw, lh) = (layer.width() as i64, layer.height() as i64);
    let (x0, y0, x1, y1) = (left.max(0), top.max(0), (left + lw).min(fw), (top + lh).min(fh));
    if x0 >= x1 || y0 >= y1 {
        return;
    }
    for y in y0..y1 {
        for x in x0..x1 {
            let s = layer.get_pixel((x - left) as u32, (y - top) as u32);
            let a = s[3] as f32 / 255.0;
            let d = frame.get_pixel_mut(x as u32, y as u32);
            for c in 0..3 {
                d[c] = py::u8c(d[c] as f32 * (1.0 - a) + s[c] as f32 * a);
            }
        }
    }
}

#[derive(Clone, Debug)]
pub struct Mark {
    pub t: Vec<f32>,
    pub w: usize,
    pub h: usize,
    pub x: usize,
}

pub fn watermark(chat_img: &RgbImage) -> Option<Mark> {
    let (w_img, h_img) = (chat_img.width() as usize, chat_img.height() as usize);
    let left = w_img - py::round(w_img as f64 * 0.12) as usize;
    let tall = py::round(h_img as f64 * 0.08) as usize;
    let bw = w_img - left;
    for top in [0, h_img - tall] {
        let px = |y: usize, x: usize| chat_img.get_pixel((left + x) as u32, (top + y) as u32);
        let ink = |y: usize, x: usize| {
            let p = px(y, x);
            p[0].max(p[1]).max(p[2]) > 24
        };
        for (y0, y1) in runs((0..tall).map(|y| (0..bw).any(|x| ink(y, x)))) {
            let xs: Vec<usize> = (0..bw).filter(|&x| (y0..=y1).any(|y| ink(y, x))).collect();
            if (xs[xs.len() - 1] - xs[0]) as f64 >= w_img as f64 * 0.05 && ((y1 - y0) as f64) < h_img as f64 * 0.04 {
                let (mw, mh) = (xs[xs.len() - 1] - xs[0] + 1, y1 - y0 + 1);
                let mut t = Vec::with_capacity(mw * mh * 3);
                for y in y0..=y1 {
                    for x in xs[0]..=xs[xs.len() - 1] {
                        t.extend(px(y, x).0.iter().map(|&v| v as f32));
                    }
                }
                return Some(Mark { t, w: mw, h: mh, x: left + xs[0] });
            }
        }
    }
    None
}

fn corr(a: &[f64], b: &[f64]) -> f64 {
    let n = a.len().max(1) as f64;
    let ma = a.iter().sum::<f64>() / n;
    let mb = b.iter().sum::<f64>() / n;
    let (mut ab, mut aa, mut bb) = (0f64, 0f64, 0f64);
    for (x, y) in a.iter().zip(b) {
        let (x, y) = (x - ma, y - mb);
        ab += x * y;
        aa += x * x;
        bb += y * y;
    }
    ab / ((aa * bb).sqrt() + 1e-6)
}

fn max3(px: &[f64]) -> Vec<f64> {
    px.chunks_exact(3).map(|p| p[0].max(p[1]).max(p[2])).collect()
}

pub fn clean_bg(bg: &RgbImage, mark: Option<&Mark>) -> RgbImage {
    let Some(mark) = mark else { return bg.clone() };
    let threshold = 0.5;
    let (w, h, x) = (mark.w, mark.h, mark.x);
    let (bw_img, bh_img) = (bg.width() as usize, bg.height() as usize);
    if x + w > bw_img || h * 3 > bh_img {
        return bg.clone();
    }
    let reach = (h * 4).max(py::round(bh_img as f64 * 0.1) as usize);
    let tl: Vec<f64> = max3(&mark.t.iter().map(|&v| v as f64).collect::<Vec<_>>());
    let strip_lum = |y: usize| -> Vec<f64> {
        let mut out = Vec::with_capacity(w * h);
        for yy in y..y + h {
            for xx in x..x + w {
                let p = bg.get_pixel(xx as u32, yy as u32);
                out.push(p[0].max(p[1]).max(p[2]) as f64);
            }
        }
        out
    };
    let mut best = threshold;
    let mut at: Option<usize> = None;
    let tail_start = bh_img.saturating_sub(reach);
    let candidates = (0..reach).chain(tail_start..=bh_img.saturating_sub(h));
    for y in candidates {
        if y + h > bh_img {
            continue;
        }
        let score = corr(&strip_lum(y), &tl);
        if score > best {
            best = score;
            at = Some(y);
        }
    }
    let Some(at) = at else { return bg.clone() };
    let by = at.saturating_sub(3);
    let bx = x.saturating_sub(3);
    let ey = (at + h + 3).min(bh_img);
    let ex = (x + w + 3).min(bw_img);
    let (boxw, boxh) = (ex - bx, ey - by);
    let mut boxv = vec![0f64; boxw * boxh * 3];
    for yy in 0..boxh {
        for xx in 0..boxw {
            let p = bg.get_pixel((bx + xx) as u32, (by + yy) as u32);
            for c in 0..3 {
                boxv[(yy * boxw + xx) * 3 + c] = p[c] as f64;
            }
        }
    }
    let (ry, rx) = (at - by, x - bx);
    let bright = &tl;
    let solid: Vec<bool> = (0..w).map(|c| (0..h).any(|r| bright[r * w + c] > 0.7 * 255.0)).collect();
    let text: Vec<usize> = (0..w).filter(|&c| !solid[c]).collect();
    if !text.is_empty() {
        let n = text.len();
        let mut tt = vec![0f64; h * n * 3];
        let mut seen = vec![0f64; h * n * 3];
        for r in 0..h {
            for (k, &c) in text.iter().enumerate() {
                for ch in 0..3 {
                    tt[(r * n + k) * 3 + ch] = mark.t[(r * w + c) * 3 + ch] as f64;
                    seen[(r * n + k) * 3 + ch] = boxv[((ry + r) * boxw + rx + c) * 3 + ch];
                }
            }
        }
        let tmax = max3(&tt);
        let matched = |img: &[f64]| corr(&max3(img), &tmax);
        if matched(&seen) > 0.3 {
            let level = &tmax;
            let top = level.iter().cloned().fold(f64::NEG_INFINITY, f64::max).max(1.0);
            let lift = |c: f64| -> Vec<f64> {
                let mut out = vec![0f64; seen.len()];
                for i in 0..h * n {
                    let a = (level[i] / c).clamp(0.0, 0.9);
                    for ch in 0..3 {
                        out[i * 3 + ch] = ((seen[i * 3 + ch] - tt[i * 3 + ch]) / (1.0 - a)).clamp(0.0, 255.0);
                    }
                }
                out
            };
            let mut best_c = 255.0;
            let mut best_s: Option<f64> = None;
            for k in 0..28 {
                let c = top + 1.0 + (255.0 - (top + 1.0)) * k as f64 / 27.0;
                let s = matched(&lift(c)).abs();
                if best_s.is_none_or(|b| s < b) {
                    best_c = c;
                    best_s = Some(s);
                }
            }
            let lifted = lift(best_c);
            let fixed: Vec<f64> = seen.iter().zip(&lifted).map(|(&s, &l)| if s >= 250.0 { s } else { l }).collect();
            if matched(&fixed).abs() < 0.3 {
                for r in 0..h {
                    for (k, &c) in text.iter().enumerate() {
                        for ch in 0..3 {
                            boxv[((ry + r) * boxw + rx + c) * 3 + ch] = fixed[(r * n + k) * 3 + ch];
                        }
                    }
                }
            }
        }
    }
    let cols: Vec<usize> = (0..w).filter(|&c| solid[c]).collect();
    if let (Some(&c0), Some(&c1)) = (cols.first(), cols.last()) {
        let x0 = rx + c0.saturating_sub(4);
        let x1 = rx + (c1 + 5).min(w);
        fill(&mut boxv, boxw, boxh, ry, ry + h, x0, x1);
    }
    let mut out = bg.clone();
    for yy in 0..boxh {
        for xx in 0..boxw {
            let i = (yy * boxw + xx) * 3;
            out.put_pixel((bx + xx) as u32, (by + yy) as u32,
                          image::Rgb([0, 1, 2].map(|c| boxv[i + c].round_ties_even().clamp(0.0, 255.0) as u8)));
        }
    }
    out
}

fn fill(out: &mut [f64], w: usize, h: usize, y0: usize, y1: usize, x0: usize, x1: usize) {
    let margin = 3;
    let (py0, py1, px0, px1) = (y0.saturating_sub(margin), (y1 + margin).min(h), x0.saturating_sub(margin), (x1 + margin).min(w));
    let (pw, ph) = (px1 - px0, py1 - py0);
    if pw == 0 || ph == 0 {
        return;
    }
    let inside = |y: usize, x: usize| (y0..y1).contains(&(y + py0)) && (x0..x1).contains(&(x + px0));
    let mut patch = vec![0f64; pw * ph * 3];
    for y in 0..ph {
        for x in 0..pw {
            for c in 0..3 {
                patch[(y * pw + x) * 3 + c] = out[((py0 + y) * w + px0 + x) * 3 + c];
            }
        }
    }
    let mut sum = [0f64; 3];
    let mut count = 0;
    for y in 0..ph {
        for x in 0..pw {
            if !inside(y, x) {
                for c in 0..3 {
                    sum[c] += patch[(y * pw + x) * 3 + c];
                }
                count += 1;
            }
        }
    }
    let avg0 = sum.map(|s| s / count.max(1) as f64);
    for y in 0..ph {
        for x in 0..pw {
            if inside(y, x) {
                patch[(y * pw + x) * 3..(y * pw + x) * 3 + 3].copy_from_slice(&avg0);
            }
        }
    }
    let mut next = patch.clone();
    for _ in 0..150 {
        for y in 0..ph {
            for x in 0..pw {
                if !inside(y, x) {
                    continue;
                }
                let up = (y + ph - 1) % ph;
                let down = (y + 1) % ph;
                let lf = (x + pw - 1) % pw;
                let rt = (x + 1) % pw;
                for c in 0..3 {
                    next[(y * pw + x) * 3 + c] = (patch[(up * pw + x) * 3 + c] + patch[(down * pw + x) * 3 + c]
                        + patch[(y * pw + lf) * 3 + c] + patch[(y * pw + rt) * 3 + c]) / 4.0;
                }
            }
        }
        patch.copy_from_slice(&next);
    }
    for y in 0..ph {
        for x in 0..pw {
            for c in 0..3 {
                out[((py0 + y) * w + px0 + x) * 3 + c] = patch[(y * pw + x) * 3 + c];
            }
        }
    }
}
