use eframe::egui::{self, Id, Pos2, Sense, Ui, vec2};
use engine::chat;
use engine::compose;
use engine::edit::{Coord, Edit, Home, Pos};

use crate::feed::{Drag, Feed};
use crate::theme::{self, WHITE};
use crate::widgets;

pub fn place_name(pos: &Pos) -> String {
    match pos {
        Pos::Corner(_) => theme::label_of(theme::POSITIONS, &compose::corner_of(pos)).to_lowercase(),
        Pos::Free(x, y) => {
            for c in [x, y] {
                if let Coord::Side(s) = c {
                    let edge = match s.as_str() {
                        "left" => "у левого края",
                        "right" => "у правого края",
                        "top" => "у верхнего края",
                        "bottom" => "у нижнего края",
                        _ => continue,
                    };
                    return edge.into();
                }
            }
            "своё место".into()
        }
    }
}

impl Feed {
    pub fn sheet_text(&mut self, ui: &mut Ui, w: f32) {
        let Some(shot) = self.target() else { return };
        let names = self.scene_names();
        let edit = shot.edit.clone();
        let spots: Vec<Pos> = compose::parts(&shot.rows, &edit).into_iter().map(|(_, p)| p).collect();
        let whole = if names.is_empty() { "" } else { " · вся сцена" };
        if !names.is_empty() {
            widgets::field(ui, "Показывать", 0.0);
            if let Some(v) = widgets::choice(ui, Id::unique("text-view"), theme::VIEWS, if self.whole { "all" } else { "one" }, w) {
                self.set_whole(&v);
            }
            if self.whole {
                widgets::label(ui, "Тяни чат любой СС мышью прямо по сцене: на переход, на соседнюю СС или в её угол. Колесо — прокрутка, Ctrl + колесо — масштаб.", 8.0);
            }
        }
        widgets::field(ui, &format!("Размер текста{whole}"), if names.is_empty() { 0.0 } else { 14.0 });
        if let Some(v) = widgets::choice(ui, Id::unique("text-scale"), theme::SCALES, &edit.text_scale.to_string(), w) {
            let s: f64 = v.parse().unwrap_or(1.5);
            self.change_text(|e| e.text_scale = s);
        }
        widgets::field(ui, &format!("Обводка{whole}"), 14.0);
        if let Some(v) = widgets::choice(ui, Id::unique("text-outline"), theme::OUTLINES, &edit.outline.to_string(), w) {
            let o: i64 = v.parse().unwrap_or(2);
            self.change_text(|e| e.outline = o);
        }
        widgets::field(ui, &format!("Отступ от края{whole}"), 14.0);
        let margin = widgets::slider(ui, Id::unique("text-margin"), 0.0, 96.0, edit.margin as f64, 2.0, &|v| format!("{v:.0} px"), w);
        if margin.moved {
            let m = margin.value as i64;
            self.change_text(|e| e.margin = m);
        }
        widgets::field(ui, if spots.len() == 1 { "Где чат" } else { "Где части чата" }, 14.0);
        for (k, pos) in spots.iter().enumerate() {
            let mut picked = None;
            ui.horizontal(|ui| {
                let value = match pos {
                    Pos::Corner(s) => Some(s.as_str()),
                    _ => None,
                };
                picked = crate::tools::corners(ui, Id::unique(("corners", k)), value);
                ui.add_space(10.0);
                let text = format!("{}{}", if spots.len() == 1 { String::new() } else { format!("Часть {} · ", k + 1) }, place_name(pos));
                ui.label(egui::RichText::new(text).font(theme::ui(10.0)).color(WHITE));
            });
            ui.add_space(6.0);
            if let Some(c) = picked {
                self.set_place(k, Pos::Corner(c));
                if let Some(n) = self.target_name() {
                    self.schedule_save(&n);
                }
            }
        }
        widgets::label(ui, "Клик по углу ставит туда чат. Его можно и тянуть мышью по картинке.", 6.0);
    }

    pub fn change_text(&mut self, f: impl Fn(&mut Edit)) {
        let names = self.scene_names();
        let targets: Vec<String> = if names.is_empty() { self.target_name().into_iter().collect() } else { names };
        for n in targets {
            if let Some(shot) = self.shot_mut(&n) {
                f(&mut shot.edit);
                self.schedule_save(&n);
            }
        }
        if self.previewing() {
            self.want_preview();
        }
    }

    pub fn set_whole(&mut self, value: &str) {
        self.whole = value == "all";
        if self.whole {
            self.fetch_scene();
            self.preview = None;
            self.preview_info = None;
            self.want_preview();
        }
    }

    pub fn set_place(&mut self, part: usize, pos: Pos) {
        let Some(shot) = self.target_mut() else { return };
        if part == 0 {
            shot.edit.pos = pos;
            return;
        }
        let count = compose::parts(&shot.rows, &shot.edit).len();
        let mut spots = compose::places(&shot.edit, count)[1..].to_vec();
        if part - 1 < spots.len() {
            spots[part - 1] = pos;
        }
        shot.edit.places = spots;
    }

    pub fn chat_spot(&self, part: usize, x: f32, y: f32) -> Option<(Pos, f32, f32)> {
        let geo = self.geo.as_ref().or(self.painter.geo.as_ref())?;
        let c = geo.chats.get(part)?.as_ref()?;
        let (ix, iy) = (geo.img.left() as f64, geo.img.top() as f64);
        let d = geo.d as f64;
        let pad = geo.pad;
        let margin = geo.plan.margin;
        let (w, h) = (geo.out.0 as f64, geo.out.1 as f64);
        let (it, ib) = (geo.inset.0 as f64, geo.inset.1 as f64);
        let inner = h - it - ib;
        let (lw, lh) = (c.lw as f64, c.lh as f64);
        let left = (x as f64 - ix) / d + pad as f64;
        let top = (y as f64 - iy) / d - it + pad as f64;
        let near = margin as f64 + 0.04 * w.min(inner);
        let hx = if left < near { Coord::Side("left".into()) } else if left + lw - 2.0 * pad as f64 > w - near { Coord::Side("right".into()) } else { Coord::Num(engine::py::round_to(left / w, 4)) };
        let vy = if top < near { Coord::Side("top".into()) } else if top + lh - 2.0 * pad as f64 > inner - near { Coord::Side("bottom".into()) } else { Coord::Num(engine::py::round_to(top / inner, 4)) };
        let pos = match (&hx, &vy) {
            (Coord::Side(a), Coord::Side(b)) => Pos::Corner(format!("{b}-{a}")),
            _ => Pos::Free(hx, vy),
        };
        let (l, t) = chat::place(w as i64, inner as i64, lw as i64, lh as i64, pad, &pos, margin);
        Some((pos, (ix + l as f64 * d) as f32, (iy + (t as f64 + it) * d) as f32))
    }

    pub fn scene_chat_at(&self, pos: Pos2) -> Option<(usize, usize, f64, f64, f64, f64)> {
        let (x0, y0, d) = self.view_box?;
        let layout = self.layout.as_ref()?;
        let rect = self.preview_rect?;
        let x = x0 + (pos.x - rect.left()) as f64 / d;
        let y = y0 + (pos.y - rect.top()) as f64 / d;
        layout.chats.iter().rev().find(|(_, f)| f.x as f64 <= x && x <= (f.x + f.w) as f64 && f.y as f64 <= y && y <= (f.y + f.h) as f64)
            .map(|(k, f)| (*k, f.part, f.x as f64, f.y as f64, f.w as f64, f.h as f64))
    }

    pub fn drop_scene_chat(&mut self, drag: &Drag, pos: Pos2) {
        let Drag::SceneChat { x, y, hit, .. } = drag else { return };
        let (k, part, left, top, lw, lh) = *hit;
        let (Some(layout), Some((_, _, d)), Some((img, _))) = (self.layout.clone(), self.view_box, self.preview.clone()) else { return };
        let names = if layout.names.is_empty() { self.scene_names() } else { layout.names.clone() };
        if k >= names.len() || (pos.x - x).abs().max((pos.y - y).abs()) < 4.0 {
            return;
        }
        let name = names[k].clone();
        if self.member(&name).is_none() {
            self.note = "эта СС не открылась, чат не перенёсся".into();
            return;
        }
        let (pad, margin, wimg) = (layout.pads[k] as f64, layout.margins[k] as f64, img.width() as f64);
        let left = left + (pos.x - x) as f64 / d + pad;
        let top = top + (pos.y - y) as f64 / d + pad;
        let (w, h) = (lw - 2.0 * pad, lh - 2.0 * pad);
        let mid = top + h / 2.0;
        let j = layout.spans.iter().position(|(_, b)| mid < *b as f64).unwrap_or(layout.spans.len() - 1);
        let (a, b) = layout.spans[j];
        let inner = (b - a) as f64;
        let top = top - a as f64;
        let near = margin + 0.04 * wimg.min(inner);
        let hx = if left < near { Some("left") } else if left + w > wimg - near { Some("right") } else { None };
        let vy = if top < 0.0 || top + h > inner { None } else if top < near { Some("top") } else if top + h > inner - near { Some("bottom") } else { None };
        let pos = match (hx, vy) {
            (Some(hx), Some(vy)) => Pos::Corner(format!("{vy}-{hx}")),
            _ => {
                let px = match hx { Some("left") => margin, Some("right") => wimg - margin - w, _ => left };
                let py = match vy { Some("top") => margin, Some("bottom") => inner - margin - h, _ => top };
                Pos::Free(Coord::Num(engine::py::round_to(px.max(0.0).min(wimg - w) / wimg, 4)), Coord::Num(engine::py::round_to(py / inner, 4)))
            }
        };
        let target = if j == k { None } else { Some(names[j].clone()) };
        let Some(shot) = self.shot_mut(&name) else { return };
        let count = compose::parts(&shot.rows, &shot.edit).len();
        if part == 0 {
            shot.edit.pos = pos;
        } else {
            let mut spots = compose::places(&shot.edit, count)[1..].to_vec();
            if part - 1 < spots.len() {
                spots[part - 1] = pos;
            }
            shot.edit.places = spots;
        }
        let mut at = compose::homes_of(shot.rows.len(), &shot.edit);
        if part < at.len() {
            at[part] = target;
        }
        let distinct: std::collections::HashSet<_> = at.iter().collect();
        shot.edit.home = if distinct.len() > 1 { Some(Home::Many(at.clone())) } else { at[0].clone().map(Home::One) };
        self.schedule_save(&name);
        self.want_preview();
        let what = if at.len() > 1 { format!("часть {} чата СС {}", part + 1, k + 1) } else { format!("чат СС {}", k + 1) };
        self.note = if j != k { format!("{what} теперь на СС {}", j + 1) } else { String::new() };
        let _ = (vec2(0.0, 0.0), Sense::hover());
    }
}
