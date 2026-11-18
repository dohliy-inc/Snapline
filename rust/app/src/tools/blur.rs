use eframe::egui::{CornerRadius, CursorIcon, Id, Pos2, Rect, Stroke, StrokeKind, Ui, vec2};
use engine::edit::Blur;
use engine::styles::BLUR_MAX;

use crate::feed::{Drag, Feed};
use crate::theme::{self, VOID, WHITE};
use crate::widgets;

const CORNERS: [&str; 4] = ["lt", "rt", "lb", "rb"];

impl Feed {
    pub fn sheet_blur(&mut self, ui: &mut Ui, w: f32) {
        widgets::label(ui, "Обведи мышью по кадру, что нужно спрятать: номер машины, лицо, ник или кусок интерфейса.", 0.0);
        let Some((k, b)) = self.current_blur() else { return };
        let count = self.target().and_then(|s| s.edit.blurs.as_ref()).map(|b| b.len()).unwrap_or(0);
        widgets::field(ui, &format!("Область {} из {count}", k + 1), 14.0);
        if let Some(v) = widgets::choice(ui, Id::unique("blur-mode"), theme::BLUR_NAMES, &b.mode, w) {
            self.set_blur(|x| x.mode = v);
        }
        widgets::field(ui, "Сила", 14.0);
        let bar = widgets::slider(ui, Id::unique("blur-power"), 10.0, 100.0, (b.power * 100.0).round(), 1.0, &|v| format!("{v:.0}%"), w);
        if bar.moved {
            let p = engine::py::round_to(bar.value / 100.0, 2);
            self.set_blur(|x| x.power = p);
        }
        let labels: Vec<&str> = if count > 1 { vec!["Удалить область", "Удалить все"] } else { vec!["Удалить область"] };
        match widgets::buttons(ui, Id::unique("blur-buttons"), &labels, 12.0) {
            Some(0) => self.remove_blur(),
            Some(1) => self.change(|e| e.blurs = Some(vec![])),
            _ => {}
        }
        widgets::label(ui, "Клик по области выбирает её, тяни углы — размер, Delete — удалить.", 6.0);
    }

    pub fn current_blur(&mut self) -> Option<(usize, Blur)> {
        let blurs = self.target()?.edit.blurs.clone().unwrap_or_default();
        if blurs.is_empty() {
            return None;
        }
        self.active_blur = self.active_blur.min(blurs.len() - 1);
        Some((self.active_blur, blurs[self.active_blur].clone()))
    }

    pub fn set_blur(&mut self, f: impl FnOnce(&mut Blur)) {
        let Some((k, _)) = self.current_blur() else { return };
        self.change(|e| {
            if let Some(b) = e.blurs.as_mut().and_then(|v| v.get_mut(k)) {
                f(b);
            }
        });
    }

    pub fn remove_blur(&mut self) {
        let Some((k, _)) = self.current_blur() else { return };
        self.active_blur = k.saturating_sub(1);
        self.change(|e| {
            if let Some(v) = e.blurs.as_mut() {
                if k < v.len() {
                    v.remove(k);
                }
            }
        });
    }

    fn blur_point(&self, pos: Pos2) -> Option<(f64, f64)> {
        let img = self.geo.as_ref()?.img;
        Some((engine::py::round_to(((pos.x - img.left()) / img.width()).clamp(0.0, 1.0) as f64, 4),
              engine::py::round_to(((pos.y - img.top()) / img.height()).clamp(0.0, 1.0) as f64, 4)))
    }

    fn blur_boxes(&self) -> Vec<Rect> {
        let (Some(geo), Some(shot)) = (&self.geo, self.target()) else { return vec![] };
        let img = geo.img;
        shot.edit.blurs.as_deref().unwrap_or(&[]).iter().map(|b| {
            let x0 = img.left() + b.x as f32 * img.width();
            let y0 = img.top() + b.y as f32 * img.height();
            Rect::from_min_size(Pos2::new(x0, y0), vec2(b.w as f32 * img.width(), b.h as f32 * img.height()))
        }).collect()
    }

    fn blur_at(&self, pos: Pos2) -> Option<(bool, usize, &'static str)> {
        let boxes = self.blur_boxes();
        if let Some(r) = boxes.get(self.active_blur) {
            for (name, c) in CORNERS.iter().zip([r.left_top(), r.right_top(), r.left_bottom(), r.right_bottom()]) {
                if (pos.x - c.x).abs() <= 8.0 && (pos.y - c.y).abs() <= 8.0 {
                    return Some((true, self.active_blur, name));
                }
            }
        }
        (0..boxes.len()).rev().find(|&k| boxes[k].contains(pos)).map(|k| (false, k, ""))
    }

    pub fn draw_blurs(&mut self, ui: &Ui) {
        let p = ui.painter();
        for (k, r) in self.blur_boxes().into_iter().enumerate() {
            let on = k == self.active_blur;
            p.rect_stroke(r, CornerRadius::ZERO, Stroke::new(3.0, VOID), StrokeKind::Middle);
            if on {
                p.rect_stroke(r, CornerRadius::ZERO, Stroke::new(1.0, WHITE), StrokeKind::Middle);
                for c in [r.left_top(), r.right_top(), r.left_bottom(), r.right_bottom()] {
                    let h = Rect::from_center_size(c, vec2(8.0, 8.0));
                    p.rect_filled(h, CornerRadius::ZERO, WHITE);
                    p.rect_stroke(h, CornerRadius::ZERO, Stroke::new(1.0, VOID), StrokeKind::Middle);
                }
            } else {
                crate::tools::dashed_rect(p, r, WHITE, 4.0, 3.0);
            }
        }
    }

    pub fn blur_press(&mut self, pos: Pos2) {
        let Some(geo) = self.geo.clone() else { return };
        if !geo.img.contains(pos) {
            return;
        }
        let Some(at) = self.blur_point(pos) else { return };
        let before = self.target().and_then(|s| s.edit.blurs.clone());
        let blurs = before.clone().unwrap_or_default();
        match self.blur_at(pos) {
            Some((true, k, corner)) => self.drag = Some(Drag::BSize { k, corner: corner.into(), b: blurs[k].clone() }),
            Some((false, k, _)) => {
                self.active_blur = k;
                self.drag = Some(Drag::BMove { k, at, b: blurs[k].clone() });
            }
            None if blurs.len() < BLUR_MAX => {
                let last = self.current_blur().map(|(_, b)| b);
                let mode = last.as_ref().map(|b| b.mode.clone()).unwrap_or("blur".into());
                let power = last.as_ref().map(|b| b.power).unwrap_or(0.6);
                let k = blurs.len();
                if let Some(shot) = self.target_mut() {
                    let mut list = blurs;
                    list.push(Blur { x: at.0, y: at.1, w: 0.0, h: 0.0, mode, power, extra: Default::default() });
                    shot.edit.blurs = Some(list);
                }
                self.active_blur = k;
                self.drag = Some(Drag::BNew { k, at, before });
            }
            None => self.note = format!("больше {BLUR_MAX} областей не поместится"),
        }
    }

    pub fn blur_motion(&mut self, pos: Pos2) {
        let Some(drag) = self.drag.clone() else { return };
        let Some((fx, fy)) = self.blur_point(pos) else { return };
        let (k, (l, t, r, b)) = match &drag {
            Drag::BNew { k, at, .. } => (*k, (at.0.min(fx), at.1.min(fy), at.0.max(fx), at.1.max(fy))),
            Drag::BMove { k, at, b } => {
                let l = (b.x + fx - at.0).max(0.0).min(1.0 - b.w);
                let t = (b.y + fy - at.1).max(0.0).min(1.0 - b.h);
                (*k, (l, t, l + b.w, t + b.h))
            }
            Drag::BSize { k, corner, b } => {
                let (mut l, mut t, mut r, mut bb) = (b.x, b.y, b.x + b.w, b.y + b.h);
                if corner.contains('l') { l = fx } else { r = fx }
                if corner.contains('t') { t = fy } else { bb = fy }
                (*k, (l.min(r), t.min(bb), l.max(r), t.max(bb)))
            }
            _ => return,
        };
        if let Some(shot) = self.target_mut() {
            if let Some(x) = shot.edit.blurs.as_mut().and_then(|v| v.get_mut(k)) {
                x.x = engine::py::round_to(l, 4);
                x.y = engine::py::round_to(t, 4);
                x.w = engine::py::round_to(r - l, 4);
                x.h = engine::py::round_to(b - t, 4);
            }
        }
    }

    pub fn blur_release(&mut self, drag: &Drag) {
        let Some(geo) = self.geo.clone() else { return };
        if let Drag::BNew { k, before, .. } = drag {
            let small = self.target().and_then(|s| s.edit.blurs.as_ref()?.get(*k).cloned())
                .is_some_and(|b| (b.w as f32 * geo.img.width()) < 6.0 || (b.h as f32 * geo.img.height()) < 6.0);
            if small {
                if let Some(shot) = self.target_mut() {
                    shot.edit.blurs = before.clone();
                }
                self.active_blur = k.saturating_sub(1);
                return;
            }
        }
        if let Some(n) = self.target_name() {
            self.schedule_save(&n);
        }
    }

    pub fn blur_hover(&mut self, pos: Pos2) {
        let inside = self.geo.as_ref().is_some_and(|g| g.img.contains(pos));
        match self.blur_at(pos) {
            Some((true, ..)) => {
                self.ctx.set_cursor_icon(CursorIcon::ResizeNwSe);
                self.hint_text = Some("Тяни — изменить размер области".into());
            }
            Some(_) => {
                self.ctx.set_cursor_icon(CursorIcon::Move);
                self.hint_text = Some("Тяни — двигать · Delete — удалить".into());
            }
            None if inside => {
                self.ctx.set_cursor_icon(CursorIcon::Crosshair);
                self.hint_text = Some("Обведи мышью, что спрятать".into());
            }
            None => {}
        }
    }
}
