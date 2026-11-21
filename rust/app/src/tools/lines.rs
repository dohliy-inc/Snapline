use std::collections::HashSet;

use eframe::egui::{self, Align2, Color32, CornerRadius, CursorIcon, Id, Pos2, Rect, Sense, Stroke, StrokeKind, Ui, vec2};
use engine::chat;
use engine::compose;
use engine::edit::{Home, Pos};
use engine::store;
use image::RgbImage;

use crate::feed::{Feed, Item, full_uv, texture};
use crate::theme::{self, BLACK, DIM, ERR, HAIR, LINE, MIST, ROW, SLATE, SUB, WHITE};
use crate::widgets;

impl Feed {
    pub fn sheet_lines(&mut self, ui: &mut Ui, w: f32) {
        let Some(shot) = self.target() else { return };
        let log = shot.name.as_ref().is_some_and(|n| store::log_path(&shot.out, n).exists());
        let screen = log && shot.name.as_ref().is_some_and(|n| !store::screen_chats(&shot.out, n).is_empty());
        let names = self.scene_names();
        ui.label(egui::RichText::new(self.count_text()).font(theme::semi(12.0)).color(WHITE));
        ui.add_space(10.0);
        let first: Vec<&str> = if log { vec!["Как после съёмки"] } else { vec!["Как после съёмки", "Чат из другой СС"] };
        match widgets::buttons(ui, Id::unique("lines-a"), &first, 0.0) {
            Some(0) => self.reset_lines(),
            Some(1) => {
                self.toggle_tool("carry");
                return;
            }
            _ => {}
        }
        let mut second = vec!["Из чатлога"];
        if screen {
            second.push("С экрана");
        }
        if !names.is_empty() {
            second.push("Убрать повторы");
        }
        match widgets::buttons(ui, Id::unique("lines-b"), &second, 6.0).map(|i| second[i]) {
            Some("Из чатлога") => {
                self.toggle_tool("logpick");
                return;
            }
            Some("С экрана") => self.from_screen(),
            Some("Убрать повторы") => self.drop_repeats(),
            _ => {}
        }
        let text = format!("{}Галочка — строка в СС, мышью можно провести по нескольким. Клик по слову — закрыть его плашкой или удалить. Ножницы делят чат на части.{}",
                           if log { "Чат этой СС собран из чатлога. " } else { "" },
                           if names.is_empty() { "" } else { " Здесь строки всех СС сцены, повторы из СС выше убираются сами." });
        widgets::label(ui, &text, 16.0);
        let _ = w;
    }

    pub fn sheet_carry(&mut self, ui: &mut Ui) {
        let names = self.scene_names();
        let mine = if names.is_empty() {
            "к этой".to_string()
        } else {
            let cur = self.current().unwrap_or_default();
            format!("к СС {} сцены", names.iter().position(|n| *n == cur).unwrap_or(0) + 1)
        };
        widgets::label(ui, &format!("Нажми на СС справа — её строки добавятся {mine}, повторы склеятся сами."), 0.0);
        if widgets::buttons(ui, Id::unique("carry-back"), &["Назад к строкам"], 8.0).is_some() {
            self.toggle_tool("lines");
        }
    }

    pub fn line_items(&self) -> Vec<Item> {
        let names = self.scene_names();
        if names.is_empty() {
            let Some(shot) = &self.shot else { return vec![] };
            let name = shot.name.clone().unwrap_or_default();
            return (0..shot.rows.len()).map(|i| Item { name: name.clone(), row: Some(i), k: 0 }).collect();
        }
        let mut items = Vec::new();
        for (k, (name, shot)) in self.members().into_iter().enumerate() {
            items.push(Item { name: name.clone(), row: None, k });
            if let Some(s) = shot {
                items.extend((0..s.rows.len()).map(|i| Item { name: name.clone(), row: Some(i), k }));
            }
        }
        items
    }

    fn row_texture(&mut self, name: &str, i: usize, s: f32) -> Option<egui::TextureHandle> {
        let shot = self.shot_of(name)?;
        let r = shot.rows.get(i)?;
        let key = format!("row:{}:{}:{:?}:{:?}:{}", r.uid, r.keep, r.hidden(), r.drop, (s * 1000.0) as i32);
        if let Some(t) = self.thumbs.get(&key) {
            return Some(t.clone());
        }
        let rgb = chat::masked(r, true);
        let cw = (r.glyphs[r.glyphs.len() - 1].1 + 8).min(r.w);
        let k = if r.keep { 1.0 } else { 0.3 };
        let mut data = Vec::with_capacity(cw * r.h * 3);
        for y in 0..r.h {
            for x in 0..cw {
                for c in 0..3 {
                    data.push((rgb[(y * r.w + x) * 3 + c] * k).clamp(0.0, 255.0) as u8);
                }
            }
        }
        let mut img = RgbImage::from_raw(cw as u32, r.h as u32, data)?;
        if s < 0.999 {
            img = engine::img::resize(&img, ((cw as f32 * s).round() as u32).max(1), ((r.h as f32 * s).round() as u32).max(1), engine::img::Filter::Lanczos);
        }
        if self.thumbs.len() > 400 {
            self.thumbs.retain(|k, _| !k.starts_with("row:"));
        }
        let t = texture(&self.ctx, "row", &img);
        self.thumbs.insert(key, t.clone());
        Some(t)
    }

    pub fn draw_lines(&mut self, ui: &mut Ui, area: Rect) {
        self.zones.clear();
        let items = self.line_items();
        self.items = items.clone();
        let rows: Vec<(usize, f64)> = items.iter().filter_map(|it| {
            let r = self.shot_of(&it.name)?.rows.get(it.row?)?;
            Some((r.glyphs[r.glyphs.len() - 1].1 + 8, r.pitch))
        }).collect();
        let widest = rows.iter().map(|(w, _)| *w).max().unwrap_or(1) as f32;
        let ppp = ui.ctx().pixels_per_point();
        let s = (1.0 / ppp).min((area.width() - 104.0) / widest);
        self.lines_x0 = area.left() + 48.0;
        self.lines_s = s;
        let slot = 28f32.max((rows.iter().map(|(_, p)| *p).fold(0.0, f64::max) as f32 * s).round() + 12.0);
        self.lines_slot = slot;
        self.offset = self.offset.min((slot * items.len() as f32 + 24.0 - area.height()).max(0.0)).max(0.0);
        let p = ui.painter().clone();
        p.rect_filled(area, CornerRadius::ZERO, BLACK);
        let clip = ui.painter().with_clip_rect(area);
        if items.is_empty() {
            p.text(area.center(), Align2::CENTER_CENTER, "Строк нет. Выбери их в чатлоге: кнопка «Из чатлога» слева.", theme::ui(12.0), SUB);
            return;
        }
        let mut y = area.top() + 12.0 - self.offset;
        self.lines_top = y;
        let current = self.current();
        let hover = ui.input(|i| i.pointer.hover_pos()).filter(|h| area.contains(*h));
        let mut cuts_cache: std::collections::HashMap<String, Vec<usize>> = std::collections::HashMap::new();
        let names = self.scene_names();
        for (j, it) in items.iter().enumerate() {
            if !(y + slot > area.top() && y < area.bottom()) {
                y += slot;
                continue;
            }
            let row_rect = Rect::from_min_size(Pos2::new(area.left(), y), vec2(area.width(), slot));
            match it.row {
                None => {
                    let shot = self.shot_of(&it.name);
                    let state = if shot.is_some() { "" } else if matches!(self.cache.get(&it.name), Some(None)) { " · не открылась" } else { " · загружаю…" };
                    let text = format!("СС {} · {}{}{}", it.k + 1, theme::when(&it.name), if Some(&it.name) == self.name().as_ref() { " · эта" } else { "" }, state);
                    if j > 0 {
                        clip.line_segment([Pos2::new(area.left() + 16.0, y + 4.0), Pos2::new(area.right() - 16.0, y + 4.0)], Stroke::new(1.0, MIST));
                    }
                    clip.text(Pos2::new(area.left() + 16.0, y + slot / 2.0 + 2.0), Align2::LEFT_CENTER, text, theme::semi(10.0),
                              if Some(&it.name) == current.as_ref() { WHITE } else { SUB });
                    if let Some(shot) = shot.filter(|s| !s.rows.is_empty()) {
                        let at: std::collections::BTreeSet<usize> = compose::homes_of(shot.rows.len(), &shot.edit).into_iter()
                            .map(|h| h.and_then(|h| names.iter().position(|n| *n == h)).map(|i| i + 1).unwrap_or(it.k + 1)).collect();
                        let moved = at.iter().copied().collect::<Vec<_>>() != vec![it.k + 1];
                        let label = format!("чат на СС {}", at.iter().map(|v| v.to_string()).collect::<Vec<_>>().join(", "));
                        let w = widgets::text_width(ui, &label, theme::semi(9.0));
                        let r = Rect::from_min_size(Pos2::new(area.right() - 16.0 - w, y + slot / 2.0 - 8.0), vec2(w, 16.0));
                        let hot = hover.is_some_and(|h| r.contains(h));
                        clip.text(Pos2::new(r.right(), y + slot / 2.0 + 2.0), Align2::RIGHT_CENTER, label, theme::semi(9.0), if moved || hot { WHITE } else { SUB });
                        self.zones.push(("home", j, r));
                    }
                    self.zones.push(("head", j, row_rect));
                }
                Some(i) => {
                    let Some(shot) = self.shot_of(&it.name) else { y += slot; continue };
                    let r = shot.rows[i].clone();
                    let cuts = cuts_cache.entry(it.name.clone()).or_insert_with(|| compose::cuts(shot.rows.len(), &shot.edit)).clone();
                    let hot = hover.is_some_and(|h| row_rect.contains(h));
                    if hot {
                        clip.rect_filled(row_rect, CornerRadius::ZERO, ROW);
                    }
                    widgets::tick(ui, Rect::from_center_size(Pos2::new(area.left() + 16.0 + 9.0, y + slot / 2.0), vec2(18.0, 18.0)), r.keep);
                    if let Some(t) = self.row_texture(&it.name, i, s * ppp) {
                        let size = t.size_vec2() / ppp;
                        let top = ((y + slot / 2.0 - size.y / 2.0) * ppp).round() / ppp;
                        let pic = Rect::from_min_size(Pos2::new(((area.left() + 48.0) * ppp).round() / ppp, top), size);
                        clip.image(t.id(), pic, full_uv(), Color32::WHITE);
                        if !r.keep {
                            clip.line_segment([Pos2::new(pic.left(), y + slot / 2.0), Pos2::new(pic.right(), y + slot / 2.0)], Stroke::new(1.0, LINE));
                        }
                    }
                    for (a, b) in &r.drop {
                        clip.line_segment([Pos2::new(area.left() + 48.0 + *a as f32 * s, y + slot / 2.0), Pos2::new(area.left() + 48.0 + (*b + 1) as f32 * s, y + slot / 2.0)],
                                          Stroke::new(2.0, ERR));
                    }
                    if cuts.contains(&i) {
                        crate::tools::dashed_line(&clip, Pos2::new(area.left() + 16.0, y), Pos2::new(area.right() - 16.0, y), SUB, 4.0, 3.0);
                        let n = cuts.iter().position(|c| *c == i).unwrap() + 2;
                        clip.text(Pos2::new(area.right() - 52.0, y + 3.0), Align2::RIGHT_TOP, format!("часть {n}"), theme::semi(9.0), WHITE);
                    }
                    if i > 0 {
                        let c = Rect::from_center_size(Pos2::new(area.right() - 28.0, y + slot / 2.0), vec2(24.0, slot));
                        let on = cuts.contains(&i);
                        let color = if hover.is_some_and(|h| c.contains(h)) { WHITE } else if on { WHITE } else if hot { SUB } else { DIM };
                        clip.text(c.center(), Align2::CENTER_CENTER, theme::icon("cut"), theme::glyph(12.0), color);
                        self.zones.push(("cut", j, c));
                    }
                    self.zones.push(("row", j, row_rect));
                }
            }
            y += slot;
        }
    }

    pub fn row_at(&self, y: f32) -> usize {
        (((y - self.lines_top) / self.lines_slot).floor().max(0.0) as usize).min(self.items.len().saturating_sub(1))
    }

    pub fn lines_press(&mut self, pos: Pos2, _area: Rect) {
        let zone = self.zones.iter().find(|(k, _, r)| matches!(*k, "home" | "cut") && r.contains(pos)).cloned()
            .or_else(|| self.zones.iter().find(|(_, _, r)| r.contains(pos)).cloned());
        let Some((kind, j, _)) = zone else { return };
        if kind == "home" {
            self.next_home(j);
            return;
        }
        let Some(it) = self.items.get(j).cloned() else { return };
        self.part = if Some(&it.name) == self.name().as_ref() { None } else { Some(it.name.clone()) };
        self.hint_text = None;
        match kind {
            "head" => {}
            "cut" => self.toggle_cut(j),
            _ => {
                let Some(i) = it.row else { return };
                let keep = self.shot_of(&it.name).map(|s| !s.rows[i].keep).unwrap_or(true);
                self.drag = Some(crate::feed::Drag::Rows { keep, first: j, last: j, shots: HashSet::new(), moved: false });
            }
        }
    }

    pub fn mark_rows(&mut self, a: usize, b: usize, keep: bool, touched: &mut HashSet<String>) {
        let items = self.items.clone();
        for it in &items[a.min(b)..=a.max(b).min(items.len().saturating_sub(1))] {
            let Some(i) = it.row else { continue };
            if let Some(shot) = self.shot_mut(&it.name) {
                shot.rows[i].keep = keep;
                touched.insert(it.name.clone());
            }
        }
        for n in touched.iter() {
            if let Some(shot) = self.shot_mut(n) {
                shot.edit.keep = shot.rows.iter().map(|r| r.keep).collect();
            }
        }
    }

    pub fn word_at(&self, j: usize, pos: Pos2) -> Option<(usize, usize)> {
        let it = self.items.get(j)?;
        let r = self.shot_of(&it.name)?.rows.get(it.row?)?;
        let x = (pos.x - self.lines_x0) / self.lines_s;
        if !r.keep || pos.x < self.lines_x0 - 4.0 {
            return None;
        }
        chat::words(r).into_iter().find(|(a, b)| *a as f32 - 3.0 <= x && x <= *b as f32 + 3.0)
    }

    pub fn popup_rect(&self) -> Option<Rect> {
        let pop = self.popup.as_ref()?;
        let s = self.lines_s;
        let top = self.lines_top + pop.j as f32 * self.lines_slot;
        let left = self.lines_x0 + pop.word.0 as f32 * s;
        let w = 200.0;
        let h = 34.0 * 3.0 + 8.0;
        let area = self.zones.iter().find(|(k, _, _)| *k == "row" || *k == "head").map(|(_, _, r)| *r)?;
        let x = left.max(area.left() + 8.0).min(area.right() - w - 8.0);
        let y = top + self.lines_slot;
        Some(Rect::from_min_size(Pos2::new(x, y), vec2(w, h)))
    }

    pub fn draw_popup(&mut self, ui: &mut Ui, _body: Rect) {
        let Some(rect) = self.popup_rect() else { return };
        let Some(pop) = self.popup.as_ref() else { return };
        let (j, word) = (pop.j, pop.word);
        let Some(it) = self.items.get(j).cloned() else { return };
        let Some(r) = it.row.and_then(|i| self.shot_of(&it.name).map(|s| s.rows[i].clone())) else { return };
        let hidden = r.hidden().contains(&word);
        let gone = r.drop.contains(&word);
        let picks = [("hide", if hidden { "Убрать плашку" } else { "Закрыть плашкой" }), ("drop", if gone { "Вернуть слово" } else { "Удалить слово" }),
                     ("row", "Убрать строку")];
        let p = ui.ctx().layer_painter(egui::LayerId::new(egui::Order::Foreground, Id::unique("popup")));
        let top = self.lines_top + j as f32 * self.lines_slot;
        let mark = Rect::from_min_max(Pos2::new(self.lines_x0 + word.0 as f32 * self.lines_s - 3.0, top + 3.0),
                                      Pos2::new(self.lines_x0 + (word.1 + 1) as f32 * self.lines_s + 3.0, top + self.lines_slot - 3.0));
        p.rect_stroke(mark, CornerRadius::ZERO, Stroke::new(1.0, WHITE), StrokeKind::Middle);
        p.rect_filled(rect, CornerRadius::same(10), SLATE);
        p.rect_stroke(rect, CornerRadius::same(10), Stroke::new(1.2, LINE), StrokeKind::Inside);
        let mut picked = None;
        for (k, (key, text)) in picks.iter().enumerate() {
            let row = Rect::from_min_size(Pos2::new(rect.left() + 4.0, rect.top() + 4.0 + k as f32 * 34.0), vec2(rect.width() - 8.0, 34.0));
            let resp = ui.interact(row, Id::unique(("pop", *key)), Sense::click());
            if resp.hovered() {
                p.rect_filled(row, CornerRadius::same(6), MIST);
                ui.ctx().set_cursor_icon(CursorIcon::PointingHand);
            }
            p.text(Pos2::new(row.left() + 14.0, row.center().y), Align2::LEFT_CENTER, *text, theme::ui(10.0), WHITE);
            if resp.clicked() {
                picked = Some(*key);
            }
        }
        if let Some(key) = picked {
            self.popup_pick(key);
        }
    }

    pub fn popup_pick(&mut self, key: &str) {
        let Some(pop) = self.popup.take() else { return };
        let (j, word) = (pop.j, pop.word);
        let Some(it) = self.items.get(j).cloned() else { return };
        let Some(i) = it.row else { return };
        if key == "row" {
            if let Some(shot) = self.shot_mut(&it.name) {
                shot.rows[i].keep = false;
                shot.edit.keep = shot.rows.iter().map(|r| r.keep).collect();
            }
        } else if let Some(shot) = self.shot_mut(&it.name) {
            let row = &mut shot.rows[i];
            let mut hide = row.hidden().to_vec();
            let mut drop = row.drop.clone();
            let (mine, other) = if key == "hide" { (&mut hide, &mut drop) } else { (&mut drop, &mut hide) };
            other.retain(|s| *s != word);
            if mine.contains(&word) { mine.retain(|s| *s != word) } else { mine.push(word) }
            row.hide = Some(hide);
            row.drop = drop;
            shot.edit.hidden = engine::edit::spans_of(&shot.rows, false);
            shot.edit.dropped = engine::edit::spans_of(&shot.rows, true);
        }
        self.schedule_save(&it.name);
    }

    pub fn toggle_cut(&mut self, j: usize) {
        let Some(it) = self.items.get(j).cloned() else { return };
        let Some(i) = it.row else { return };
        let Some(shot) = self.shot_mut(&it.name) else { return };
        let rows = shot.rows.len();
        let edit = &mut shot.edit;
        let mut breaks = compose::cuts(rows, edit);
        let mut spots = compose::places(edit, breaks.len() + 1)[1..].to_vec();
        let mut homes = compose::homes_of(rows, edit);
        if let Some(k) = breaks.iter().position(|b| *b == i) {
            breaks.remove(k);
            spots.remove(k);
            homes.remove(k + 1);
        } else {
            let mut sorted = breaks.clone();
            sorted.push(i);
            sorted.sort();
            let k = sorted.iter().position(|b| *b == i).unwrap();
            let mut used = vec![edit.pos.clone()];
            used.extend(spots.iter().cloned());
            let corner = compose::corner_of(&edit.pos);
            let mut order: Vec<&str> = compose::spare_places(&corner).to_vec();
            order.extend(engine::config::CHAT_POSITIONS);
            let free = order.iter().find(|c| !used.contains(&Pos::corner(c))).map(|c| Pos::corner(c));
            breaks.insert(k, i);
            spots.insert(k, free.unwrap_or_else(|| Pos::Corner(compose::corner_of(&used[k]))));
            let h = homes[k].clone();
            homes.insert(k + 1, h);
        }
        edit.breaks = breaks.into_iter().map(|b| b as i64).collect();
        edit.places = spots;
        if matches!(edit.home, Some(Home::Many(_))) {
            edit.home = Some(Home::Many(homes));
        }
        self.schedule_save(&it.name);
    }

    pub fn count_text(&self) -> String {
        let names = self.scene_names();
        let shots: Vec<&engine::store::Shot> = if names.is_empty() {
            self.shot.iter().collect()
        } else {
            self.members().into_iter().filter_map(|(_, s)| s).collect()
        };
        let kept: usize = shots.iter().map(|s| s.rows.iter().filter(|r| r.keep).count()).sum();
        let total: usize = shots.iter().map(|s| s.rows.len()).sum();
        if shots.len() > 1 {
            return format!("В сцене {kept} из {total}");
        }
        let n = self.shot.as_ref().map(|s| compose::parts(&s.rows, &s.edit).len()).unwrap_or(1);
        format!("В СС {kept} из {total}{}", if n > 1 { format!(" · частей: {n}") } else { String::new() })
    }

    pub fn reset_lines(&mut self) {
        let names = self.scene_names();
        let targets: Vec<String> = if names.is_empty() { self.name().into_iter().collect() } else { names };
        let keep = self.cfg.keep.clone();
        for n in targets {
            if let Some(shot) = self.shot_mut(&n) {
                let log = store::log_path(&shot.out, &n).exists();
                for r in shot.rows.iter_mut() {
                    r.keep = log || keep.contains(&r.kind);
                }
                shot.edit.keep = shot.rows.iter().map(|r| r.keep).collect();
                self.schedule_save(&n);
            }
        }
    }

    pub fn next_home(&mut self, j: usize) {
        let Some(it) = self.items.get(j).cloned() else { return };
        let names: Vec<String> = self.members().into_iter().filter(|(_, s)| s.is_some()).map(|(n, _)| n).collect();
        if names.len() < 2 {
            return;
        }
        let Some(shot) = self.shot_mut(&it.name) else { return };
        let at = compose::homes_of(shot.rows.len(), &shot.edit)[0].clone();
        let now = at.and_then(|a| names.iter().position(|n| *n == a)).or_else(|| names.iter().position(|n| *n == it.name)).unwrap_or(0);
        let to = names[(now + 1) % names.len()].clone();
        shot.edit.home = if to == it.name { None } else { Some(Home::One(to)) };
        self.schedule_save(&it.name);
    }

    pub fn lines_hint(&self, pos: Pos2) -> Option<String> {
        if self.popup_rect().is_some_and(|r| r.contains(pos)) {
            return None;
        }
        let zone = self.zones.iter().find(|(k, _, r)| matches!(*k, "home" | "cut") && r.contains(pos))
            .or_else(|| self.zones.iter().find(|(_, _, r)| r.contains(pos)))?;
        Some(match zone.0 {
            "cut" => "Разрезать чат здесь — дальше пойдёт новая часть".into(),
            "home" => "Клик — перенести чат этой СС на следующую СС сцены".into(),
            "head" => "Клик — выбрать эту СС".into(),
            _ => {
                let it = self.items.get(zone.1)?;
                let r = self.shot_of(&it.name)?.rows.get(it.row?)?;
                if !r.keep {
                    "Клик — вернуть строку".into()
                } else if pos.x < self.lines_x0 - 4.0 {
                    "Клик — убрать строку · веди мышью, чтобы отметить несколько".into()
                } else {
                    "Клик по слову — закрыть или удалить его · по галочке — убрать строку".into()
                }
            }
        })
    }

    pub fn draw_donors(&mut self, ui: &mut Ui, area: Rect) {
        self.zones.clear();
        let Some(shot) = self.shot.as_ref() else { return };
        let out = shot.out.clone();
        let picking = self.tool == Some("scenepick");
        let me = self.name().unwrap_or_default();
        let base = if picking { me.clone() } else { self.current().unwrap_or_default() };
        let mut names = store::donors(&out, &base, &self.names, 12);
        let p = ui.painter().clone();
        if names.is_empty() {
            p.text(area.center(), Align2::CENTER_CENTER, "Других СС с исходными кадрами нет", theme::ui(12.0), SUB);
            return;
        }
        let chosen: HashSet<String> = self.scene_names().into_iter().chain(std::iter::once(me.clone())).collect();
        if picking {
            names = self.names.iter().rev().filter(|n| chosen.contains(*n) || names.contains(n)).cloned().collect();
        }
        self.donor_names = names.clone();
        let cols = if names.len() <= 4 { 2 } else if names.len() <= 9 { 3 } else { 4 };
        let lines = names.len().div_ceil(cols);
        let (gap, cap) = (16.0, 28.0);
        let cw = (area.width() - gap * (cols - 1) as f32) / cols as f32;
        let ch = (cw * 0.75).min((area.height() - gap * (lines - 1) as f32) / lines as f32 - cap);
        let top = area.top() + (area.height() - lines as f32 * (ch + cap) - gap * (lines - 1) as f32) / 2.0;
        let hover = ui.input(|i| i.pointer.hover_pos());
        for (k, name) in names.iter().enumerate() {
            let x = area.left() + (k % cols) as f32 * (cw + gap);
            let y = top + (k / cols) as f32 * (ch + cap + gap);
            let t = self.thumb(&out, name, (cw.round().max(1.0) as u32, ch.round().max(1.0) as u32));
            let size = t.as_ref().map(|t| t.size_vec2()).unwrap_or(vec2(cw, ch));
            let pic = Rect::from_min_size(Pos2::new(x + (cw - size.x) / 2.0, y + (ch - size.y) / 2.0), size);
            let on = picking && chosen.contains(name);
            let mine = picking && *name == me;
            let hot = !mine && hover.is_some_and(|h| pic.expand(2.0).contains(h) || Rect::from_min_size(pic.left_bottom(), vec2(pic.width(), 24.0)).contains(h));
            match &t {
                Some(t) => {
                    p.image(t.id(), pic, full_uv(), Color32::WHITE);
                }
                None => {
                    p.rect_filled(pic, CornerRadius::ZERO, ROW);
                }
            }
            p.rect_stroke(pic.expand(1.0), CornerRadius::ZERO, Stroke::new(if on { 2.0 } else { 1.0 }, if on || hot { WHITE } else { HAIR }), StrokeKind::Inside);
            if picking {
                widgets::tick(ui, Rect::from_min_size(pic.left_top() + vec2(8.0, 8.0), vec2(20.0, 20.0)), on);
            }
            p.text(Pos2::new(pic.left(), pic.bottom() + 8.0), Align2::LEFT_TOP, format!("{}{}", theme::when(name), if mine { " · эта СС" } else { "" }),
                   theme::ui(10.0), if on || hot { WHITE } else { SUB });
            if !mine {
                self.zones.push(("donor", k, Rect::from_min_max(pic.left_top(), pic.right_bottom() + vec2(0.0, 28.0))));
            }
        }
    }

    pub fn donor_press(&mut self, pos: Pos2) {
        let Some((_, k, _)) = self.zones.iter().find(|(kind, _, r)| *kind == "donor" && r.contains(pos)).cloned() else { return };
        let Some(name) = self.donor_names.get(k).cloned() else { return };
        match self.tool {
            Some("carry") => self.carry(&name),
            Some("scenepick") => self.toggle_scene(&name),
            _ => {
                let shot = store::load_shot(&self.cfg.out, &name, &self.cfg).ok().flatten();
                let Some(shot) = shot else {
                    self.note = "фон той СС не открылся".into();
                    return;
                };
                let (w, h) = shot.bg.dimensions();
                let part = compose::bg_part(&shot.bg, (0, 0, w as i64, h as i64), shot.edit.mirror);
                self.tool = Some("images");
                self.add_image(engine::img::to_rgba(&part));
            }
        }
    }

    pub fn donor_hint(&self, pos: Pos2) -> Option<String> {
        if !self.zones.iter().any(|(k, _, r)| *k == "donor" && r.contains(pos)) {
            return None;
        }
        self.ctx.set_cursor_icon(CursorIcon::PointingHand);
        Some(match self.tool {
            Some("carry") => "Клик — добавить строки этой СС",
            Some("photopick") => "Клик — положить фон этой СС поверх",
            _ => "Клик — добавить в сцену или убрать",
        }.into())
    }

    pub fn carry(&mut self, name: &str) {
        let cfg = self.cfg.clone();
        let Some(target) = self.target_name() else { return };
        let result = match self.shot_mut(&target) {
            Some(shot) => store::carry_chat(shot, name, &cfg),
            None => return,
        };
        match result {
            Err(e) => self.note = format!("чат не перенёсся: {e}"),
            Ok(added) => {
                self.tool = Some("lines");
                if added > 0 {
                    self.schedule_save(&target);
                }
                self.note = if added > 0 { format!("из СС от {} добавлено строк: {added}", theme::when(name)) } else { "все строки той СС уже есть в этой".into() };
            }
        }
    }

    pub fn drop_repeats(&mut self) {
        let names = self.scene_names();
        for n in &names {
            if self.shot_of(n).is_none() && !matches!(self.cache.get(n), Some(None)) {
                let _ = self.member(n);
            }
        }
        let shots: Vec<Option<engine::store::Shot>> = names.iter().map(|n| self.shot_of(n).cloned()).collect();
        let dups = store::repeats(&shots.iter().map(|s| s.as_ref()).collect::<Vec<_>>());
        let mut gone = 0;
        for (n, dup) in names.iter().zip(dups) {
            if dup.is_empty() {
                continue;
            }
            if let Some(shot) = self.shot_mut(n) {
                for i in &dup {
                    shot.rows[*i].keep = false;
                }
                shot.edit.keep = shot.rows.iter().map(|r| r.keep).collect();
            }
            gone += dup.len();
            self.schedule_save(n);
        }
        self.note = if gone > 0 { format!("убрал повторы из сцены: {gone}") } else { "повторов в сцене нет".into() };
    }
}
