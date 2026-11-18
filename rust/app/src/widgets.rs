use eframe::egui::{self, Align2, Color32, CornerRadius, FontId, Id, Pos2, Rect, Response, Sense, Stroke, StrokeKind, Ui, vec2};

use crate::theme::{self, CHIP_TEXT, LINE, MIST, SLATE, SUB, VOID, WHITE};

#[derive(Clone, Copy, PartialEq, Eq)]
pub enum Kind {
    Chip,
    On,
    Primary,
    Ghost,
}

pub fn text_width(ui: &Ui, text: &str, font: FontId) -> f32 {
    ui.fonts_mut(|f| f.layout_no_wrap(text.to_string(), font, WHITE).size().x)
}

pub fn pill_size(ui: &Ui, text: &str, kind: Kind, size: f32, height: f32, padx: f32) -> egui::Vec2 {
    let font = if matches!(kind, Kind::On | Kind::Primary) { theme::semi(size) } else { theme::ui(size) };
    vec2(text_width(ui, text, font) + 2.0 * padx, height)
}

pub fn pill_at(ui: &mut Ui, rect: Rect, id: Id, text: &str, kind: Kind, size: f32) -> Response {
    let resp = ui.interact(rect, id, Sense::click());
    let hover = resp.hovered();
    let t = ui.ctx().animate_bool_responsive(id.with("hover"), hover);
    let mix = crate::feed::mix;
    let (fill, line, fg) = match kind {
        Kind::Chip => (Some(mix(SLATE, MIST, t)), None, mix(CHIP_TEXT, WHITE, t)),
        Kind::On => (Some(WHITE), None, VOID),
        Kind::Primary => (Some(Color32::WHITE), None, VOID),
        Kind::Ghost => (if t > 0.01 { Some(SLATE.gamma_multiply(t)) } else { None }, Some(mix(LINE, WHITE, t)), WHITE),
    };
    let r = CornerRadius::same((rect.height() / 2.0) as u8);
    let p = ui.painter();
    if let Some(f) = fill {
        p.rect_filled(rect, r, f);
    }
    if let Some(l) = line {
        p.rect_stroke(rect.shrink(0.6), r, Stroke::new(1.2, l), StrokeKind::Middle);
    }
    let font = if matches!(kind, Kind::On | Kind::Primary) { theme::semi(size) } else { theme::ui(size) };
    p.text(rect.center(), Align2::CENTER_CENTER, text, font, fg);
    if hover {
        ui.ctx().set_cursor_icon(egui::CursorIcon::PointingHand);
    }
    resp
}

pub fn pill(ui: &mut Ui, id: Id, text: &str, kind: Kind) -> Response {
    let size = pill_size(ui, text, kind, 10.0, 32.0, 13.0);
    let (rect, _) = ui.allocate_exact_size(size, Sense::hover());
    pill_at(ui, rect, id, text, kind, 10.0)
}

fn pack(widths: &[f32], gap: f32, limit: f32) -> Vec<Vec<usize>> {
    let mut rows: Vec<Vec<usize>> = vec![vec![]];
    let mut used = 0.0;
    for (i, w) in widths.iter().enumerate() {
        if used > 0.0 && used + w > limit {
            rows.push(vec![]);
            used = 0.0;
        }
        rows.last_mut().unwrap().push(i);
        used += w + gap;
    }
    rows
}

pub fn choice(ui: &mut Ui, id: Id, options: &[(&str, &str)], value: &str, wrap: f32) -> Option<String> {
    let mut picked = None;
    let gap = 6.0;
    let widths: Vec<f32> = options.iter().map(|(_, label)| text_width(ui, label, theme::semi(10.0)) + 26.0).collect();
    let mut rows = pack(&widths, gap, wrap);
    if rows.len() > 1 {
        let total: f32 = widths.iter().map(|w| w + gap).sum();
        let mut limit = (total / rows.len() as f32).max(widths.iter().cloned().fold(0.0, f32::max));
        while limit < wrap {
            let even = pack(&widths, gap, limit);
            if even.len() <= rows.len() {
                rows = even;
                break;
            }
            limit += 4.0;
        }
    }
    for (r, row) in rows.iter().enumerate() {
        let (line, _) = ui.allocate_exact_size(vec2(wrap, 32.0), Sense::hover());
        let mut x = line.left();
        for &i in row {
            let (key, label) = options[i];
            let on = theme::same(key, value);
            let rect = Rect::from_min_size(Pos2::new(x, line.top()), vec2(widths[i], 32.0));
            if pill_at(ui, rect, id.with(key), label, if on { Kind::On } else { Kind::Chip }, 10.0).clicked() {
                picked = Some(key.to_string());
            }
            x += widths[i] + gap;
        }
        if r + 1 < rows.len() {
            ui.add_space(gap);
        }
    }
    picked
}

pub fn buttons(ui: &mut Ui, id: Id, items: &[&str], top: f32) -> Option<usize> {
    ui.add_space(top);
    let mut picked = None;
    let (line, _) = ui.allocate_exact_size(vec2(ui.available_width(), 32.0), Sense::hover());
    let mut x = line.left();
    for (i, text) in items.iter().enumerate() {
        let size = pill_size(ui, text, Kind::Ghost, 10.0, 32.0, 13.0);
        let rect = Rect::from_min_size(Pos2::new(x, line.top()), size);
        if pill_at(ui, rect, id.with(i), text, Kind::Ghost, 10.0).clicked() {
            picked = Some(i);
        }
        x += size.x + 6.0;
    }
    picked
}

pub fn field(ui: &mut Ui, text: &str, top: f32) {
    ui.add_space(if top > 0.0 { top.max(theme::S5 - 2.0) } else { 0.0 });
    ui.label(egui::RichText::new(text).font(theme::semi(10.0)).color(WHITE));
    ui.add_space(theme::S2);
}

pub fn label(ui: &mut Ui, text: &str, top: f32) {
    ui.add_space(top);
    ui.add(egui::Label::new(egui::RichText::new(text).font(theme::ui(10.0)).color(SUB)).wrap());
    ui.add_space(8.0);
}

pub struct SliderOut {
    pub value: f64,
    pub moved: bool,
    pub done: bool,
}

pub fn snap(v: f64, lo: f64, hi: f64, step: f64) -> f64 {
    let v = (((v - lo) / step).round() * step + lo) * 10000.0;
    (v.round() / 10000.0).clamp(lo, hi)
}

pub fn slider(ui: &mut Ui, id: Id, lo: f64, hi: f64, value: f64, step: f64, fmt: &dyn Fn(f64) -> String, width: f32) -> SliderOut {
    let value = snap(value, lo, hi, step);
    let (rect, resp) = ui.allocate_exact_size(vec2(width, 30.0), Sense::click_and_drag());
    let (a, b) = (rect.left() + 9.0, rect.right() - 64.0);
    let mut out = SliderOut { value, moved: false, done: false };
    if let Some(p) = resp.interact_pointer_pos().filter(|_| resp.is_pointer_button_down_on()) {
        let v = snap(lo + ((p.x - a) / (b - a)) as f64 * (hi - lo), lo, hi, step);
        if v != value {
            out.value = v;
            out.moved = true;
        }
    }
    if resp.drag_stopped() || resp.clicked() {
        out.done = true;
    }
    if resp.hovered() {
        ui.ctx().set_cursor_icon(egui::CursorIcon::PointingHand);
        let scroll = crate::widgets::wheel(ui);
        if scroll != 0.0 {
            out.value = snap(value + if scroll > 0.0 { step } else { -step }, lo, hi, step);
            out.moved = out.value != value;
            out.done = out.moved;
        }
    }
    let _ = id;
    let y = rect.center().y;
    let x = a + ((out.value - lo) / (hi - lo)) as f32 * (b - a);
    let p = ui.painter();
    p.line_segment([Pos2::new(a, y), Pos2::new(b, y)], Stroke::new(4.0, MIST));
    p.line_segment([Pos2::new(a, y), Pos2::new(x, y)], Stroke::new(4.0, WHITE));
    p.circle_filled(Pos2::new(a, y), 2.0, WHITE);
    p.circle_filled(Pos2::new(b, y), 2.0, MIST);
    p.circle_filled(Pos2::new(x, y), 8.0, WHITE);
    p.circle_stroke(Pos2::new(x, y), 8.0, Stroke::new(2.0, if resp.has_focus() { SUB } else { VOID }));
    p.text(Pos2::new(rect.right(), y), Align2::RIGHT_CENTER, fmt(out.value), theme::semi(10.0), WHITE);
    out
}

pub fn tick(ui: &Ui, rect: Rect, on: bool) {
    let p = ui.painter();
    let r = CornerRadius::same(5);
    if on {
        p.rect_filled(rect, r, WHITE);
        let s = rect.width();
        let at = |fx: f32, fy: f32| Pos2::new(rect.left() + s * fx, rect.top() + s * fy);
        p.line(vec![at(0.26, 0.52), at(0.43, 0.68), at(0.75, 0.33)], Stroke::new(2.2, VOID));
    } else {
        p.rect_stroke(rect.shrink(1.0), r, Stroke::new(1.5, theme::DIM), StrokeKind::Middle);
    }
}

pub fn wheel(ui: &Ui) -> f32 {
    ui.input(|i| {
        i.events.iter().map(|e| match e {
            egui::Event::MouseWheel { delta, .. } => delta.y,
            _ => 0.0,
        }).sum()
    })
}
