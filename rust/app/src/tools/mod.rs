pub mod blur;
pub mod crop;
pub mod file;
pub mod images;
pub mod lines;
pub mod logpick;
pub mod scene;
pub mod style;
pub mod text;

use eframe::egui::{self, Align2, Color32, CornerRadius, Id, Painter, Pos2, Rect, Sense, Stroke, StrokeKind, Ui, vec2};

use crate::theme::{self, DIM, ERR, LINE, ROW, SUB, WHITE};
use crate::widgets;

pub fn dashed_line(p: &Painter, a: Pos2, b: Pos2, color: Color32, dash: f32, gap: f32) {
    let len = a.distance(b);
    if len <= 0.0 {
        return;
    }
    let dir = (b - a) / len;
    let mut t = 0.0;
    while t < len {
        let e = (t + dash).min(len);
        p.line_segment([a + dir * t, a + dir * e], Stroke::new(1.0, color));
        t += dash + gap;
    }
}

pub fn dashed_poly(p: &Painter, pts: &[Pos2], color: Color32, dash: f32, gap: f32) {
    for i in 0..pts.len() {
        dashed_line(p, pts[i], pts[(i + 1) % pts.len()], color, dash, gap);
    }
}

pub fn dashed_rect(p: &Painter, r: Rect, color: Color32, dash: f32, gap: f32) {
    dashed_poly(p, &[r.left_top(), r.right_top(), r.right_bottom(), r.left_bottom()], color, dash, gap);
}

pub fn corners(ui: &mut Ui, id: Id, value: Option<&str>) -> Option<String> {
    let (rect, resp) = ui.allocate_exact_size(vec2(48.0, 32.0), Sense::click());
    let p = ui.painter();
    p.rect_stroke(rect.shrink(0.6), CornerRadius::same(6), Stroke::new(1.2, LINE), StrokeKind::Middle);
    let hover = resp.hover_pos();
    let spot = |pt: Pos2| -> String {
        format!("{}-{}", if pt.y < rect.center().y { "top" } else { "bottom" }, if pt.x < rect.center().x { "left" } else { "right" })
    };
    let near = hover.map(spot);
    for corner in engine::config::CHAT_POSITIONS {
        let (v, side) = corner.split_once('-').unwrap();
        let x = if side == "left" { rect.left() + 9.0 } else { rect.right() - 9.0 };
        let y = if v == "top" { rect.top() + 9.0 } else { rect.bottom() - 9.0 };
        let on = value == Some(corner);
        if on {
            p.circle_filled(Pos2::new(x, y), 4.0, WHITE);
        } else {
            p.circle_stroke(Pos2::new(x, y), 4.0, Stroke::new(1.0, if near.as_deref() == Some(corner) { WHITE } else { DIM }));
        }
    }
    if resp.hovered() {
        ui.ctx().set_cursor_icon(egui::CursorIcon::PointingHand);
    }
    let _ = id;
    if resp.clicked() { resp.interact_pointer_pos().map(spot) } else { None }
}

pub fn size_entry(ui: &mut Ui, id: Id, text: &mut String, good: bool) -> bool {
    let edit = egui::TextEdit::singleline(text)
        .id(id)
        .desired_width(64.0)
        .font(theme::ui(10.0))
        .align(egui::Align2::CENTER_CENTER)
        .text_color(if good { WHITE } else { ERR })
        .background_color(ROW)
        .margin(vec2(6.0, 8.0))
        .min_size(vec2(64.0, 32.0));
    ui.add(edit).changed()
}

pub fn frame_pick(ui: &mut Ui, id: Id, options: &[(&str, &str)], value: &str, text: &mut (String, String), current: (u32, u32),
                  wrap: f32, limits: (u32, u32)) -> Option<String> {
    let custom = engine::config::exact_of(value);
    let mut out = widgets::choice(ui, id.with("choice"), options, if custom.is_some() { "" } else { value }, wrap);
    let mut open = out.is_none() && custom.is_some();
    ui.add_space(6.0);
    let mut changed = false;
    ui.horizontal(|ui| {
        ui.spacing_mut().item_spacing = vec2(6.0, 0.0);
        if widgets::pill(ui, id.with("custom"), "Свой", if open { widgets::Kind::On } else { widgets::Kind::Chip }).clicked() && !open {
            *text = (current.0.to_string(), current.1.to_string());
            out = Some(format!("{}x{}", current.0, current.1));
            open = true;
        }
        if !open {
            return;
        }
        if let (Some((w, h)), true) = (custom, text.0.is_empty()) {
            *text = (w.to_string(), h.to_string());
        }
        ui.add_space(4.0);
        let ok = |s: &str| s.trim().parse::<u32>().is_ok_and(|v| limits.0 <= v && v <= limits.1);
        let (a, b) = (ok(&text.0), ok(&text.1));
        changed |= size_entry(ui, id.with("w"), &mut text.0, a);
        ui.label(egui::RichText::new("×").font(theme::ui(10.0)).color(SUB));
        changed |= size_entry(ui, id.with("h"), &mut text.1, b);
        ui.label(egui::RichText::new("px").font(theme::ui(10.0)).color(SUB));
    });
    if changed {
        let pasted = [text.0.clone(), text.1.clone()].into_iter().find_map(|s| {
            let parts: Vec<String> = s.trim().to_lowercase().split(|c: char| "x×х*".contains(c) || c.is_whitespace())
                .filter(|p| !p.is_empty()).map(|p| p.to_string()).collect();
            (parts.len() == 2).then(|| (parts[0].clone(), parts[1].clone()))
        });
        if let Some(both) = pasted {
            *text = both;
        }
        let parse = |s: &str| s.trim().parse::<u32>().ok().filter(|v| limits.0 <= *v && *v <= limits.1);
        if let (Some(w), Some(h)) = (parse(&text.0), parse(&text.1)) {
            out = Some(format!("{w}x{h}"));
        }
    }
    out
}

pub fn text_line(ui: &Ui, pos: Pos2, text: &str, font: egui::FontId, color: Color32) -> Rect {
    ui.painter().text(pos, Align2::LEFT_TOP, text, font, color)
}
