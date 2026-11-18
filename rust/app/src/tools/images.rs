use eframe::egui::{CornerRadius, Id, Pos2, Rect, Stroke, StrokeKind, Ui, vec2};
use engine::compose;
use engine::edit::Overlay;
use image::RgbaImage;

use crate::feed::{Drag, Feed};
use crate::painter::{Geo, OvGeo};
use crate::theme::{self, HANDLES, VOID, WHITE};
use crate::widgets;

fn spots(b: &OvGeo) -> Vec<(&'static str, Pos2)> {
    let (l, t, r, bb) = (b.x, b.y, b.x + b.w, b.y + b.h);
    let (cx, cy) = ((l + r) / 2.0, (t + bb) / 2.0);
    let at = |x: f32, y: f32| {
        let (dx, dy) = compose::turned((x - cx) as f64, (y - cy) as f64, b.angle);
        Pos2::new(cx + dx as f32, cy + dy as f32)
    };
    HANDLES.iter().map(|h| {
        let p = match *h {
            "l" => (l, cy),
            "r" => (r, cy),
            "t" => (cx, t),
            "b" => (cx, bb),
            "lt" => (l, t),
            "rt" => (r, t),
            "lb" => (l, bb),
            _ => (r, bb),
        };
        (*h, at(p.0, p.1))
    }).collect()
}

impl Feed {
    pub fn mark_overlay(&self, ui: &Ui, geo: &Geo) {
        if self.tool != Some("images") {
            return;
        }
        let Some(Some(b)) = geo.overlays.get(self.active_ov) else { return };
        let all = spots(b);
        let corners: Vec<Pos2> = ["lt", "rt", "rb", "lb"].iter().map(|n| all.iter().find(|(k, _)| k == n).unwrap().1).collect();
        crate::tools::dashed_poly(ui.painter(), &corners, WHITE, 4.0, 3.0);
        let locked = self.target().and_then(|s| s.edit.overlays.get(self.active_ov)).is_some_and(|o| compose::lock_ratio(&o.cut).is_some());
        for (name, p) in all {
            if locked && name.len() == 1 {
                continue;
            }
            let r = Rect::from_center_size(p, vec2(10.0, 10.0));
            ui.painter().rect_filled(r, CornerRadius::ZERO, WHITE);
            ui.painter().rect_stroke(r, CornerRadius::ZERO, Stroke::new(1.0, VOID), StrokeKind::Middle);
        }
    }

    pub fn handle_at(&self, pos: Pos2, geo: &Geo) -> Option<String> {
        let Some(Some(b)) = geo.overlays.get(self.active_ov) else { return None };
        let locked = self.target().and_then(|s| s.edit.overlays.get(self.active_ov)).is_some_and(|o| compose::lock_ratio(&o.cut).is_some());
        spots(b).into_iter().rev().find(|(name, p)| !(locked && name.len() == 1) && (pos.x - p.x).abs() <= 6.0 && (pos.y - p.y).abs() <= 6.0)
            .map(|(n, _)| n.to_string())
    }

    pub fn sheet_images(&mut self, ui: &mut Ui, w: f32) {
        widgets::label(ui, "Второй ракурс, коллаж или стикер поверх СС. С мягкими краями фото растворяется в ней.", 0.0);
        match widgets::buttons(ui, Id::unique("ov-add"), &["Из файла", "Из буфера"], 0.0) {
            Some(0) => self.add_file(),
            Some(1) => self.add_clipboard(),
            _ => {}
        }
        if widgets::buttons(ui, Id::unique("ov-photo"), &["Из другой СС"], 6.0).is_some() {
            self.toggle_tool("photopick");
            return;
        }
        let Some(shot) = self.target() else { return };
        let overlays = shot.edit.overlays.clone();
        if overlays.is_empty() {
            return;
        }
        self.active_ov = self.active_ov.min(overlays.len() - 1);
        let ov = overlays[self.active_ov].clone();
        if overlays.len() > 1 {
            widgets::field(ui, "Картинка", 14.0);
            let keys: Vec<String> = (0..overlays.len()).map(|i| i.to_string()).collect();
            let labels: Vec<String> = (0..overlays.len()).map(|i| (i + 1).to_string()).collect();
            let options: Vec<(&str, &str)> = keys.iter().zip(&labels).map(|(k, l)| (k.as_str(), l.as_str())).collect();
            if let Some(v) = widgets::choice(ui, Id::unique("ov-pick"), &options, &self.active_ov.to_string(), w) {
                self.active_ov = v.parse().unwrap_or(0);
                self.painter.forget();
            }
        }
        let pct = |v: f64| format!("{v:.0}%");
        widgets::field(ui, "Размер по ширине кадра", 14.0);
        let size = widgets::slider(ui, Id::unique("ov-size"), 5.0, 200.0, (ov.w * 100.0).round(), 1.0, &pct, w);
        if size.moved {
            self.change_ov(|o| o.w = engine::py::round_to(size.value / 100.0, 4));
        }
        widgets::field(ui, "Угол", 14.0);
        let angle = widgets::slider(ui, Id::unique("ov-angle"), -180.0, 180.0, ov.turn().round(), 1.0, &|v| format!("{v:.0}°"), w);
        if angle.moved {
            self.change_ov(|o| o.angle = Some(angle.value.round()));
        }
        widgets::field(ui, "Мягкие края", 14.0);
        let soft = widgets::slider(ui, Id::unique("ov-soft"), 0.0, 100.0, (ov.soft * 100.0).round(), 1.0, &pct, w);
        if soft.moved {
            self.change_ov(|o| o.soft = soft.value / 100.0);
        }
        widgets::field(ui, "Прозрачность", 14.0);
        let alpha = widgets::slider(ui, Id::unique("ov-alpha"), 0.0, 90.0, ((1.0 - ov.alpha) * 100.0).round(), 1.0, &pct, w);
        if alpha.moved {
            self.change_ov(|o| o.alpha = engine::py::round_to(1.0 - alpha.value / 100.0, 2));
        }
        match widgets::buttons(ui, Id::unique("ov-turn"), &["Отразить", "Повернуть на 90°"], 12.0) {
            Some(0) => self.change_ov(compose::flip_overlay),
            Some(1) => self.change_ov(|o| o.angle = Some(compose::wrap_angle(o.turn() + 90.0))),
            _ => {}
        }
        widgets::field(ui, "Обрезка", 14.0);
        let current = self.crop_size();
        let key = format!("ov:{}:{}", self.target_name().unwrap_or_default(), self.active_ov);
        if self.frame_text_for != key {
            self.frame_text_for = key;
            self.frame_text = (String::new(), String::new());
        }
        let mut text = self.frame_text.clone();
        let picked = crate::tools::frame_pick(ui, Id::unique("ov-crop"), theme::CROPS, &ov.cut, &mut text, current, w, (16, 20000));
        self.frame_text = text;
        if let Some(v) = picked {
            self.crop_ov(&v);
        }
        match widgets::buttons(ui, Id::unique("ov-reset"), &["Сбросить обрезку", "Убрать"], 8.0) {
            Some(0) => self.crop_ov("reset"),
            Some(1) => self.remove_ov(),
            _ => {}
        }
    }

    pub fn sheet_photopick(&mut self, ui: &mut Ui) {
        widgets::label(ui, "Нажми на СС справа — её фон ляжет поверх этой с мягкими краями.", 0.0);
        if widgets::buttons(ui, Id::unique("photo-back"), &["Назад"], 8.0).is_some() {
            self.toggle_tool("images");
        }
    }

    pub fn add_file(&mut self) {
        let Some(path) = rfd::FileDialog::new().set_title("Картинка поверх СС")
            .add_filter("Картинки", &["png", "jpg", "jpeg", "webp", "bmp", "gif"]).add_filter("Все файлы", &["*"]).pick_file() else { return };
        match image::open(&path) {
            Ok(img) => self.add_image(img.to_rgba8()),
            Err(e) => self.note = format!("картинка не открылась: {e}"),
        }
    }

    pub fn add_clipboard(&mut self) {
        match crate::win::clipboard_image() {
            Some(img) => self.add_image(img),
            None => self.note = "в буфере обмена нет картинки".into(),
        }
    }

    pub fn add_image(&mut self, image: RgbaImage) {
        let Some(shot) = self.target() else { return };
        if shot.edit.overlays.len() >= compose::MAX_OVERLAYS {
            self.note = format!("больше {} картинок не поместится", compose::MAX_OVERLAYS);
            return;
        }
        let (out, name) = (shot.out.clone(), shot.name.clone().unwrap_or_default());
        let look = self.look(shot).0;
        let p = compose::plan(shot.bg.dimensions(), &look, None);
        let mut ov = match compose::add_overlay(&out, &name, &image) {
            Ok(ov) => ov,
            Err(e) => {
                self.note = format!("картинка не сохранилась: {e}");
                return;
            }
        };
        if p.ext_box.is_some() && ov.soft > 0.0 {
            compose::fit_field(&mut ov, &p, image.dimensions());
        }
        let count = shot.edit.overlays.len();
        self.active_ov = count;
        self.change(|e| e.overlays.push(ov));
        self.painter.forget();
    }

    pub fn source_size(&self, ov: &Overlay) -> Option<(u32, u32)> {
        let shot = self.target()?;
        compose::overlay_image(&shot.src().join(&ov.file), ov.flipped()).map(|i| i.dimensions())
    }

    pub fn crop_size(&self) -> (u32, u32) {
        let Some(ov) = self.target().and_then(|s| s.edit.overlays.get(self.active_ov)) else { return (1, 1) };
        let (w, h) = self.source_size(ov).unwrap_or((1, 1));
        let [l, t, r, b] = ov.crop;
        (((r - l) * w as f64).round() as u32, ((b - t) * h as f64).round() as u32)
    }

    pub fn crop_ov(&mut self, value: &str) {
        let Some(shot) = self.target() else { return };
        let Some(ov) = shot.edit.overlays.get(self.active_ov).cloned() else { return };
        let Some(size) = self.source_size(&ov) else { return };
        let out_w = compose::plan(shot.bg.dimensions(), &self.look(shot).0, None).size.0 as f64;
        let before = ov.w * out_w / (ov.crop[2] - ov.crop[0]).max(1e-6);
        let value = value.to_string();
        self.change_ov(move |o| {
            let mut v = value.clone();
            if v == "reset" {
                o.crop = [0.0, 0.0, 1.0, 1.0];
                v = "free".into();
            } else if let Some((w, h)) = engine::config::exact_of(&v) {
                o.crop = compose::crop_exact(size, w, h, o.crop);
            } else if v != "free" {
                o.crop = compose::crop_for(size, compose::lock_ratio(&v), o.crop);
            }
            o.w = engine::py::round_to(before * (o.crop[2] - o.crop[0]) / out_w, 4);
            o.cut = v;
        });
    }

    pub fn change_ov(&mut self, f: impl FnOnce(&mut Overlay)) {
        let k = self.active_ov;
        self.change(|e| {
            if let Some(o) = e.overlays.get_mut(k) {
                f(o);
            }
        });
    }

    pub fn remove_ov(&mut self) {
        let k = self.active_ov;
        self.active_ov = k.saturating_sub(1);
        self.change(|e| {
            if k < e.overlays.len() {
                e.overlays.remove(k);
            }
        });
        self.painter.forget();
    }

    pub fn snap_ov(&mut self, part: usize, b: &OvGeo, geo: &Geo) {
        let (w, h) = (geo.out.0 as f64, geo.out.1 as f64);
        let d = geo.d as f64;
        let near = 0.015 * w.min(h);
        let a = b.angle.to_radians();
        let bw = (b.w as f64 * a.cos()).abs() + (b.h as f64 * a.sin()).abs();
        let bh = (b.w as f64 * a.sin()).abs() + (b.h as f64 * a.cos()).abs();
        let Some(shot) = self.target_mut() else { return };
        let Some(ov) = shot.edit.overlays.get_mut(part) else { return };
        for (is_x, size, half) in [(true, w, bw / d / 2.0), (false, h, bh / d / 2.0)] {
            let v = if is_x { &mut ov.x } else { &mut ov.y };
            let c = *v * size;
            if (c - half).abs() < near {
                *v = engine::py::round_to(half / size, 4);
            } else if (c + half - size).abs() < near {
                *v = engine::py::round_to((size - half) / size, 4);
            }
        }
    }

    pub fn drag_crop(&mut self, pos: Pos2) {
        let Some(Drag::Crop { handle, part, x, y, crop, b, size }) = self.drag.clone() else { return };
        let Some(geo) = self.geo.clone() else { return };
        let (out_w, out_h) = (geo.out.0 as f64, geo.out.1 as f64);
        let d = geo.d as f64;
        let (sw, sh) = (size.0 as f64, size.1 as f64);
        let [l, t, r, bb] = crop;
        let bx = (b.x - geo.img.left()) as f64 / d;
        let by = (b.y - geo.img.top()) as f64 / d;
        let (wd, hd) = (b.w as f64 / d, b.h as f64 / d);
        let k = wd / ((r - l) * sw).max(1e-6);
        let (mut ll, mut tt, mut rr, mut bt) = (bx, by, bx + wd, by + hd);
        let bounds = (bx - l * sw * k, by - t * sh * k, rr + (1.0 - r) * sw * k, bt + (1.0 - bb) * sh * k);
        let angle = self.target().and_then(|s| s.edit.overlays.get(part)).map(|o| o.turn()).unwrap_or(0.0);
        let (dx, dy) = compose::turned((pos.x - x) as f64 / d, (pos.y - y) as f64 / d, -angle);
        let least = 12.0 / d;
        if handle.contains('l') {
            ll = (ll + dx).max(bounds.0).min(rr - least);
        }
        if handle.contains('r') {
            rr = (rr + dx).min(bounds.2).max(ll + least);
        }
        if handle.contains('t') {
            tt = (tt + dy).max(bounds.1).min(bt - least);
        }
        if handle.contains('b') {
            bt = (bt + dy).min(bounds.3).max(tt + least);
        }
        let cut = self.target().and_then(|s| s.edit.overlays.get(part)).map(|o| o.cut.clone()).unwrap_or_default();
        if let (Some(ratio), 2) = (compose::lock_ratio(&cut), handle.len()) {
            let (mut w, mut hh) = (rr - ll, bt - tt);
            if dx.abs() >= dy.abs() * ratio { hh = w / ratio } else { w = hh * ratio }
            let room_w = if handle.contains('l') { rr - bounds.0 } else { bounds.2 - ll };
            let room_h = if handle.contains('t') { bt - bounds.1 } else { bounds.3 - tt };
            let scale = 1f64.min(room_w / w).min(room_h / hh);
            w *= scale;
            hh *= scale;
            if handle.contains('l') { ll = rr - w } else { rr = ll + w }
            if handle.contains('t') { tt = bt - hh } else { bt = tt + hh }
        }
        let (span_x, span_y) = (sw * k, sh * k);
        let new_crop = [
            engine::py::round_to((l + (ll - bx) / span_x).clamp(0.0, 1.0), 5),
            engine::py::round_to((t + (tt - by) / span_y).clamp(0.0, 1.0), 5),
            engine::py::round_to((r + (rr - bx - wd) / span_x).clamp(0.0, 1.0), 5),
            engine::py::round_to((bb + (bt - by - hd) / span_y).clamp(0.0, 1.0), 5),
        ];
        let (ex, ey) = compose::turned((ll + rr) / 2.0 - bx - wd / 2.0, (tt + bt) / 2.0 - by - hd / 2.0, angle);
        if let Some(ov) = self.target_mut().and_then(|s| s.edit.overlays.get_mut(part)) {
            ov.crop = new_crop;
            ov.w = engine::py::round_to((rr - ll) / out_w, 5);
            ov.x = engine::py::round_to((bx + wd / 2.0 + ex) / out_w, 5);
            ov.y = engine::py::round_to((by + hd / 2.0 + ey) / out_h, 5);
        }
    }
}
