use eframe::egui::{Align2, Color32, CornerRadius, CursorIcon, Id, Pos2, Rect, Sense, Stroke, StrokeKind, Ui, vec2};
use engine::compose;
use engine::store;

use crate::feed::{Feed, full_uv};
use crate::theme::{self, LINE, PAD, S2, S3, S5, SIDE_W, SUB, WHITE};

const THUMB: (f32, f32) = (96.0, 54.0);
const ROW: f32 = THUMB.1 + S3;

fn short_when(name: &str) -> String {
    theme::when(name)
}

impl Feed {
    pub fn summary(&self) -> String {
        let Some(name) = self.name() else { return String::new() };
        let Some(shot) = &self.shot else {
            return if matches!(self.cache.get(&name), Some(None)) { "только просмотр".into() } else { "загружаю…".into() };
        };
        let mut parts = Vec::new();
        let names = self.scene_names();
        if names.is_empty() {
            let p = compose::plan(shot.bg.dimensions(), &shot.edit, None);
            parts.push(format!("{} × {}", p.size.0, p.size.1));
        } else {
            let (w, h) = self.scene_size();
            parts.push(format!("сцена из {} СС, {w} × {h}", names.len()));
        }
        let kept = shot.rows.iter().filter(|r| r.keep).count();
        if !shot.rows.is_empty() {
            parts.push(format!("{kept} из {} строк", shot.rows.len()));
        }
        let chunks = compose::parts(&shot.rows, &shot.edit).len();
        if chunks > 1 {
            parts.push(format!("частей: {chunks}"));
        }
        if let Ok(meta) = std::fs::metadata(store::shot_image(&self.cfg.out, &name)) {
            parts.push(theme::megabytes(meta.len()));
        }
        parts.join(" · ")
    }

    pub fn side(&mut self, ui: &mut Ui, body: Rect, name: &str, view_only: bool) {
        let x = body.left() + PAD + 12.0;
        let width = SIDE_W - PAD - 24.0;
        let p = ui.painter().clone();
        let title = p.layout(theme::when(name), theme::display(24.0), WHITE, width);
        let title_h = title.size().y;
        let top = body.top() + PAD;
        p.galley(Pos2::new(x, top), title, WHITE);
        let summary = p.layout(self.summary(), theme::ui(11.0), SUB, width);
        let summary_h = summary.size().y;
        p.galley(Pos2::new(x, top + title_h + S2), summary, SUB);
        let mut notice = None;
        if view_only {
            notice = Some("Исходные кадры этой СС не найдены: её можно посмотреть и скопировать, но не поправить.");
        } else if self.empty_log() {
            notice = Some("Чат пока пустой. Открой «Строки» (клавиша 1) и отметь нужные строки из чатлога.");
        } else if self.shot.as_ref().is_some_and(|s| s.legacy) {
            notice = Some("Старая СС: файл обновится после первой правки.");
        }
        let mut list_top = top + title_h + S2 + summary_h + S5;
        if let Some(text) = notice {
            let g = p.layout(text.to_string(), theme::ui(10.0), WHITE, width);
            let h = g.size().y;
            p.galley(Pos2::new(x, list_top - S2), g, WHITE);
            list_top += h + S3;
        }
        let keys = if self.scene_names().is_empty() {
            "Колесо или ↑ ↓ — листать СС · 1–8 — инструменты
Ctrl+Z — отменить · Ctrl+C — скопировать СС"
        } else {
            "Это сцена из нескольких СС. Колесо — листать
1–8 — инструменты · Ctrl+Z — отменить"
        };
        let hint = p.layout(keys.to_string(), theme::ui(9.0), SUB, width);
        let hint_h = hint.size().y;
        let bottom = body.bottom() - PAD - 12.0;
        p.galley(Pos2::new(x, bottom - hint_h), hint, SUB);
        let list_bottom = bottom - hint_h - S5;
        let room = (list_bottom - list_top).max(0.0);
        let count = ((room / ROW).floor() as usize).min(self.names.len());
        if count < 2 {
            return;
        }
        let here = self.index.saturating_sub(1);
        let start = here.saturating_sub(count / 2).min(self.names.len() - count);
        let used = count as f32 * ROW - S3;
        let y0 = list_top + (room - used) / 2.0;
        let out = self.cfg.out.clone();
        let hover = ui.input(|i| i.pointer.hover_pos());
        let mut go = None;
        let widest = (start..start + count)
            .filter_map(|i| { let n = self.names[i].clone(); self.thumb(&out, &n, (THUMB.0 as u32, THUMB.1 as u32)) })
            .map(|t| t.size_vec2().x / ui.ctx().pixels_per_point())
            .fold(0.0f32, f32::max)
            .max(THUMB.1);
        for (k, idx) in (start..start + count).enumerate() {
            let shot_name = self.names[idx].clone();
            let y = y0 + k as f32 * ROW;
            let row = Rect::from_min_size(Pos2::new(x - S2, y - theme::S1), vec2(width + S2 * 2.0, THUMB.1 + theme::S1 * 2.0));
            let current = idx == here;
            let resp = ui.interact(row, Id::unique(("strip-row", &shot_name)), Sense::click());
            let hot = !current && hover.is_some_and(|h| row.contains(h));
            let t = ui.ctx().animate_bool_responsive(Id::unique(("strip-hot", &shot_name)), hot || current);
            let frame = Rect::from_min_size(Pos2::new(x, y), vec2(THUMB.0, THUMB.1));
            match self.thumb(&out, &shot_name, (THUMB.0 as u32, THUMB.1 as u32)) {
                Some(tex) => {
                    let size = self.shown(&tex);
                    let pic = Rect::from_min_size(self.snap(Pos2::new(frame.left(), frame.center().y - size.y / 2.0)), size);
                    let dim = if current { 255 } else { (150.0 + 105.0 * t) as u8 };
                    p.image(tex.id(), pic, full_uv(), Color32::from_gray(dim));
                    if current {
                        p.rect_stroke(pic.expand(2.0), CornerRadius::same(3), Stroke::new(1.5, WHITE), StrokeKind::Outside);
                    } else if t > 0.01 {
                        p.rect_stroke(pic.expand(2.0), CornerRadius::same(3), Stroke::new(1.0, LINE.gamma_multiply(t)), StrokeKind::Outside);
                    }
                }
                None => {
                    p.rect_filled(frame, CornerRadius::same(3), theme::ROW);
                }
            }
            let color = Color32::from_rgb(lerp(SUB.r(), WHITE.r(), t), lerp(SUB.g(), WHITE.g(), t), lerp(SUB.b(), WHITE.b(), t));
            let label_x = x + widest + S3 + 4.0;
            let lift = if current { 8.0 } else { 0.0 };
            p.text(Pos2::new(label_x, y + THUMB.1 / 2.0 - lift), Align2::LEFT_CENTER, short_when(&shot_name), theme::ui(10.0), color);
            if current {
                p.text(Pos2::new(label_x, y + THUMB.1 / 2.0 + 10.0), Align2::LEFT_CENTER, "сейчас открыта", theme::ui(9.0), SUB);
            }
            if hot {
                ui.ctx().set_cursor_icon(CursorIcon::PointingHand);
            }
            if resp.clicked() && !current {
                go = Some(idx + 1);
            }
        }
        if let Some(i) = go {
            self.go(i as isize);
        }
    }
}

fn lerp(a: u8, b: u8, t: f32) -> u8 {
    (a as f32 + (b as f32 - a as f32) * t).round() as u8
}
