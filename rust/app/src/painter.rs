use std::collections::hash_map::DefaultHasher;
use std::hash::{Hash, Hasher};

use eframe::egui::{self, Color32, ColorImage, Pos2, Rect, TextureHandle, TextureOptions, Ui, vec2};
use engine::chat::{self, Row};
use engine::compose::{self, Plan};
use engine::edit::{Edit, Pos};
use engine::img::{self, Filter};
use engine::store::Shot;
use image::{RgbImage, RgbaImage};

#[derive(Clone, Debug)]
pub struct ChatGeo {
    pub x: f32,
    pub y: f32,
    pub w: f32,
    pub h: f32,
    pub lw: f32,
    pub lh: f32,
}

#[derive(Clone, Debug)]
pub struct OvGeo {
    pub x: f32,
    pub y: f32,
    pub w: f32,
    pub h: f32,
    pub b: Rect,
    pub angle: f64,
}

#[derive(Clone, Debug)]
pub struct Geo {
    pub img: Rect,
    pub d: f32,
    pub out: (u32, u32),
    pub plan: Plan,
    pub pad: i64,
    pub chats: Vec<Option<ChatGeo>>,
    pub overlays: Vec<Option<OvGeo>>,
    pub join: Option<Rect>,
    pub inset: (u32, u32),
    pub painted: usize,
    pub blurs: Vec<Rect>,
}

#[derive(Default)]
pub struct Painter {
    frame: Option<(u64, TextureHandle, Vec<(usize, TextureHandle, Rect)>, Vec<Option<OvGeo>>)>,
    layers: Option<(u64, Vec<Option<RgbaImage>>, usize)>,
    small: Vec<(u64, TextureHandle)>,
    pub geo: Option<Geo>,
}

pub fn key_of(parts: impl Hash) -> u64 {
    let mut h = DefaultHasher::new();
    parts.hash(&mut h);
    h.finish()
}

fn rgba_texture(ctx: &egui::Context, name: &str, img: &RgbaImage) -> TextureHandle {
    let color = ColorImage::from_rgba_unmultiplied([img.width() as usize, img.height() as usize], img.as_raw());
    ctx.load_texture(name, color, TextureOptions::LINEAR)
}

fn rgb_texture(ctx: &egui::Context, name: &str, img: &RgbImage) -> TextureHandle {
    let color = ColorImage::from_rgb([img.width() as usize, img.height() as usize], img.as_raw());
    ctx.load_texture(name, color, TextureOptions::LINEAR)
}

pub fn frame_at(bg: &RgbImage, rect: (i64, i64, i64, i64), size: (u32, u32), mirror: bool, tilt: f64) -> RgbImage {
    if tilt != 0.0 {
        let k = compose::tilt_zoom(size, tilt);
        let big = frame_at(bg, rect, ((size.0 as f64 * k).round() as u32, (size.1 as f64 * k).round() as u32), mirror, 0.0);
        return compose::tilt_image(&big, tilt, size);
    }
    let (mut x0, y0, mut x1, y1) = rect;
    if mirror {
        let w = bg.width() as i64;
        (x0, x1) = (w - x1, w - x0);
    }
    let part = img::resize_box(bg, size.0.max(1), size.1.max(1), Filter::Bilinear, (x0 as f64, y0 as f64, x1 as f64, y1 as f64));
    if mirror { img::flip_h(&part) } else { part }
}

pub fn shade(frame: &mut RgbImage, bands: (f32, f32)) {
    let h = frame.height() as usize;
    let mut k = vec![1f32; h];
    let top = (bands.0.round() as usize).min(h);
    let bottom = (bands.1.round() as usize).min(h);
    if top > 0 {
        for (i, r) in compose::ramp(top).into_iter().enumerate() {
            k[i] = 0.3 + 0.7 * r;
        }
    }
    if bottom > 0 {
        let ramp = compose::ramp(bottom);
        for i in 0..bottom {
            let v = 0.3 + 0.7 * ramp[bottom - 1 - i];
            k[h - bottom + i] = k[h - bottom + i].min(v);
        }
    }
    let w = frame.width() as usize;
    for (i, v) in frame.iter_mut().enumerate() {
        *v = (*v as f32 * k[i / (w * 3)]).round() as u8;
    }
}

fn rows_key(rows: &[Row]) -> u64 {
    key_of(rows.iter().map(|r| (r.uid, r.keep, r.hidden().to_vec(), r.drop.clone())).collect::<Vec<_>>())
}

impl Painter {
    pub fn forget(&mut self) {
        self.frame = None;
        self.layers = None;
        self.small.clear();
    }

    #[allow(clippy::too_many_arguments)]
    pub fn draw(&mut self, ui: &Ui, shot: &Shot, area: Rect, edit: &Edit, laps: (u32, u32), moving: Option<(usize, Pos2)>) -> Geo {
        let ctx = ui.ctx().clone();
        let bg = &shot.bg;
        let p = compose::plan(bg.dimensions(), edit, None);
        let (out_w, out_h) = p.size;
        let k = ctx.pixels_per_point();
        let dp = (area.width() * k / out_w as f32).min(area.height() * k / out_h as f32);
        let d = dp / k;
        let (dw, dh) = (((out_w as f32 * dp).round() as u32).max(1), ((out_h as f32 * dp).round() as u32).max(1));
        let ix = (area.left() * k + (area.width() * k - dw as f32) / 2.0).floor() / k;
        let iy = (area.top() * k + (area.height() * k - dh as f32) / 2.0).floor() / k;
        let img_rect = Rect::from_min_size(Pos2::new(ix, iy), vec2(dw as f32 / k, dh as f32 / k));
        let edit_key = serde_json::to_string(&(&edit.format, edit.zoom, edit.center, &edit.size, &edit.join, &edit.overlays,
                                               edit.mirror, edit.tilt, &edit.blurs)).unwrap_or_default();
        let fkey = key_of((std::sync::Arc::as_ptr(bg) as usize, edit_key, dw, dh, laps, (ix * 4.0) as i64, (iy * 4.0) as i64));
        if self.frame.as_ref().map(|f| f.0) != Some(fkey) {
            let mut frame = if p.size == p.base {
                frame_at(bg, p.rect, (dw, dh), edit.mirror, edit.tilt())
            } else {
                let (bw, bh) = p.base;
                let base = frame_at(bg, p.rect, (((bw as f32 * dp).round() as u32).max(1), ((bh as f32 * dp).round() as u32).max(1)),
                                    edit.mirror, edit.tilt());
                let joined = edit.join.as_ref().map(|j| compose::join_canvas(&base, j)).unwrap_or(base);
                if joined.dimensions() == (dw, dh) { joined } else { img::resize(&joined, dw, dh, Filter::Bilinear) }
            };
            let (pieces, ovs) = self.overlay_pieces(shot, edit, img_rect, dp, k, (out_w, out_h));
            let blurs = edit.blurs.clone().unwrap_or_default();
            let mut textures = Vec::new();
            if !blurs.is_empty() && !pieces.is_empty() {
                let mut canvas = img::to_rgba(&frame);
                for (_, piece, r) in &pieces {
                    img::paste_rgba(&mut canvas, piece, ((r.left() - ix) * k).round() as i64, ((r.top() - iy) * k).round() as i64);
                }
                frame = engine::styles::obscure(&img::to_rgb(&canvas), &blurs);
                let px = |v: f32| (v * k).round() as u32;
                for (n, _, r) in &pieces {
                    let crop = img::crop(&frame, px(r.left() - ix), px(r.top() - iy), px(r.right() - ix), px(r.bottom() - iy));
                    textures.push((*n, rgb_texture(&ctx, "piece", &crop), *r));
                }
            } else {
                frame = engine::styles::obscure(&frame, &blurs);
                for (n, piece, r) in &pieces {
                    textures.push((*n, rgba_texture(&ctx, "piece", piece), *r));
                }
            }
            if laps != (0, 0) {
                shade(&mut frame, (laps.0 as f32 * dp, laps.1 as f32 * dp));
            }
            self.frame = Some((fkey, rgb_texture(&ctx, "frame", &frame), textures, ovs));
        }
        let (_, frame_tex, pieces, ovs) = self.frame.as_ref().unwrap();
        let full = Rect::from_min_max(Pos2::ZERO, Pos2::new(1.0, 1.0));
        ui.painter().image(frame_tex.id(), img_rect, full, Color32::WHITE);
        for (_, t, r) in pieces {
            ui.painter().image(t.id(), *r, full, Color32::WHITE);
        }
        let (it, ib) = (laps.0 / 2, laps.1 / 2);
        let inner = out_h.saturating_sub(it + ib);
        let groups = compose::parts(&shot.rows, edit);
        let lkey = key_of((rows_key(&shot.rows), compose::cuts(shot.rows.len(), edit), p.outline, (p.scale * 10000.0) as i64, inner, p.margin));
        if self.layers.as_ref().map(|l| l.0) != Some(lkey) {
            let mut painted = 0;
            let layers = groups
                .iter()
                .map(|(range, _)| {
                    let part = &shot.rows[range.clone()];
                    if part.is_empty() {
                        return None;
                    }
                    chat::chat_layer(part, p.outline as usize, p.scale, Some((inner as i64 - 2 * p.margin) as f64)).map(|l| {
                        painted += l.painted;
                        l.image
                    })
                })
                .collect();
            self.layers = Some((lkey, layers, painted));
            self.small.clear();
        }
        let (_, layers, painted) = self.layers.as_ref().unwrap();
        let pad = p.outline + 2;
        let dims: Vec<Option<(i64, i64)>> = layers.iter().map(|l| l.as_ref().map(|i| (i.width() as i64, i.height() as i64))).collect();
        let spots_pos: Vec<Pos> = groups.iter().map(|(_, pos)| pos.clone()).collect();
        let mut boxes = Vec::new();
        let spots = compose::chat_spots((out_w as i64, inner as i64), &dims, &spots_pos, pad, p.margin, &mut boxes, None);
        let mut chats = Vec::new();
        for (n, (layer, spot)) in layers.iter().zip(spots).enumerate() {
            let (Some(layer), Some((left, top))) = (layer, spot) else {
                chats.push(None);
                continue;
            };
            let (lw, lh) = (layer.width(), layer.height());
            let size = (((lw as f32 * dp).round() as u32).max(1), ((lh as f32 * dp).round() as u32).max(1));
            let skey = key_of((lkey, n, size));
            let tex = match self.small.iter().find(|(key, _)| *key == skey) {
                Some((_, t)) => t.clone(),
                None => {
                    let small = img::resize_rgba(layer, size.0, size.1, Filter::Lanczos);
                    let t = rgba_texture(&ctx, "chat", &small);
                    self.small.push((skey, t.clone()));
                    t
                }
            };
            let (mut cx, mut cy) = (ix + (left as f32 * dp).round() / k, iy + ((top + it as i64) as f32 * dp).round() / k);
            if let Some((part, at)) = moving {
                if part == n {
                    (cx, cy) = ((at.x * k).round() / k, (at.y * k).round() / k);
                }
            }
            let (sw, sh) = (size.0 as f32 / k, size.1 as f32 / k);
            ui.painter().image(tex.id(), Rect::from_min_size(Pos2::new(cx, cy), vec2(sw, sh)), full, Color32::WHITE);
            chats.push(Some(ChatGeo { x: cx, y: cy, w: sw, h: sh, lw: lw as f32, lh: lh as f32 }));
        }
        let join = p.ext_box.map(|(l, t, r, b)| Rect::from_min_max(Pos2::new(ix + l as f32 * d, iy + t as f32 * d),
                                                                     Pos2::new(ix + r as f32 * d, iy + b as f32 * d)));
        let geo = Geo { img: img_rect, d, out: (out_w, out_h), plan: p, pad, chats, overlays: ovs.clone(), join,
                        inset: (it, ib), painted: *painted, blurs: vec![] };
        self.geo = Some(geo.clone());
        geo
    }

    fn overlay_pieces(&self, shot: &Shot, edit: &Edit, img: Rect, dp: f32, k: f32, out: (u32, u32))
                      -> (Vec<(usize, RgbaImage, Rect)>, Vec<Option<OvGeo>>) {
        let img = Rect::from_min_max((img.min.to_vec2() * k).to_pos2(), (img.max.to_vec2() * k).to_pos2());
        let pt = |r: Rect| Rect::from_min_max((r.min.to_vec2() / k).to_pos2(), (r.max.to_vec2() / k).to_pos2());
        let mut pieces = Vec::new();
        let mut geos = Vec::new();
        let src = shot.src();
        for (n, ov) in edit.overlays.iter().enumerate() {
            let Some(source) = compose::overlay_image(&src.join(&ov.file), ov.flipped()) else {
                geos.push(None);
                continue;
            };
            let (x, y, w, h) = compose::overlay_box(ov, out, source.dimensions());
            let dx = (img.left() + x as f32 * dp).round();
            let dy = (img.top() + y as f32 * dp).round();
            let size = (((w as f32 * dp).round() as u32).max(1), ((h as f32 * dp).round() as u32).max(1));
            let edges = compose::spun_edges(ov, (x, y, w, h), out);
            let piece = compose::spin(&compose::soften(&compose::overlay_piece(&source, ov, size), ov, edges), ov.turn());
            let px0 = (dx + (size.0 as f32 - piece.width() as f32) / 2.0).round();
            let py0 = (dy + (size.1 as f32 - piece.height() as f32) / 2.0).round();
            let l = img.left().max(px0);
            let t = img.top().max(py0);
            let r = img.right().min(px0 + piece.width() as f32);
            let b = img.bottom().min(py0 + piece.height() as f32);
            if r <= l || b <= t {
                geos.push(None);
                continue;
            }
            let crop = img::crop_rgba(&piece, (l - px0) as u32, (t - py0) as u32, (r - px0) as u32, (b - py0) as u32);
            let rect = Rect::from_min_max(Pos2::new(l, t), Pos2::new(r, b));
            pieces.push((n, crop, pt(rect)));
            geos.push(Some(OvGeo { x: dx / k, y: dy / k, w: size.0 as f32 / k, h: size.1 as f32 / k, b: pt(rect), angle: ov.turn() }));
        }
        (pieces, geos)
    }
}
