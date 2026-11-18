use std::collections::{HashMap, HashSet};

use chrono::NaiveDateTime;
use eframe::egui::{self, Align2, Color32, CornerRadius, CursorIcon, Id, Pos2, Rect, Stroke, Ui, vec2};
use engine::chat::Kind;
use engine::chatlog::{self, Line};
use engine::compose;
use engine::store;

use crate::feed::Feed;
use crate::theme::{self, BLACK, MIST, ROW, SLATE, SUB, WHITE};
use crate::widgets::{self, Kind as Pill};

pub struct LogView {
    pub name: String,
    pub at: NaiveDateTime,
    pub lines: Vec<Line>,
    pub who: Vec<(Kind, Option<String>, Option<String>)>,
    pub on: HashSet<usize>,
    pub all: bool,
    pub names: HashSet<String>,
    pub items: Vec<(&'static str, usize)>,
    pub mark: usize,
    pub bounds: HashMap<usize, Vec<usize>>,
    pub width: Option<f32>,
    pub offset: Option<f32>,
    pub tops: Vec<f32>,
    pub wraps: HashMap<usize, Vec<Vec<(f32, String, String)>>>,
    pub lh: f32,
    pub full: f32,
    pub top: f32,
}

fn chat_font() -> egui::FontId {
    egui::FontId::new(15.0, egui::FontFamily::Name("chat".into()))
}

impl Feed {
    pub fn empty_log(&self) -> bool {
        let Some(shot) = &self.shot else { return false };
        shot.rows.is_empty() && self.scene_names().is_empty() && shot.name.as_ref().is_some_and(|n| store::log_path(&shot.out, n).exists())
    }

    pub fn sheet_logpick(&mut self, ui: &mut Ui, w: f32) {
        let Some(shot) = self.target() else { return };
        let screen = shot.name.as_ref().is_some_and(|n| !store::log_path(&shot.out, n).exists());
        let count = match &self.logview {
            Some(v) if !v.lines.is_empty() => format!("Отмечено {} из {}", v.on.len(), v.lines.len()),
            _ => "Строк нет".into(),
        };
        ui.label(egui::RichText::new(count).font(theme::semi(12.0)).color(WHITE));
        ui.add_space(10.0);
        let (line, _) = ui.allocate_exact_size(vec2(w, 32.0), egui::Sense::hover());
        let a = widgets::pill_size(ui, "На СС", Pill::Primary, 10.0, 32.0, 13.0);
        let b = widgets::pill_size(ui, "Назад к строкам", Pill::Ghost, 10.0, 32.0, 13.0);
        if widgets::pill_at(ui, Rect::from_min_size(line.left_top(), a), Id::unique("log-apply"), "На СС", Pill::Primary, 10.0).clicked() {
            self.apply_log();
            return;
        }
        if widgets::pill_at(ui, Rect::from_min_size(line.left_top() + vec2(a.x + 6.0, 0.0), b), Id::unique("log-back"), "Назад к строкам", Pill::Ghost, 10.0).clicked() {
            self.toggle_tool("lines");
            return;
        }
        let has = self.logview.as_ref().is_some_and(|v| !v.lines.is_empty());
        if has {
            widgets::field(ui, "Показывать", 14.0);
            let all = self.logview.as_ref().unwrap().all;
            if let Some(v) = widgets::choice(ui, Id::unique("log-show"), theme::LOG_SHOW, if all { "all" } else { "rp" }, w) {
                if let Some(view) = self.logview.as_mut() {
                    view.all = v == "all";
                }
                self.log_refilter();
            }
            let names = self.log_names();
            if !names.is_empty() {
                widgets::field(ui, "Чьи строки", 14.0);
                widgets::label(ui, "Нажми на участников своей сцены — останется только их диалог. Ближе к моменту съёмки — выше.", 0.0);
                let picked: HashSet<String> = self.logview.as_ref().unwrap().names.clone();
                let mut rows: Vec<Vec<(String, String, f32)>> = vec![vec![]];
                let mut used = 0.0;
                for (name, n) in &names {
                    let text = format!("{name} · {n}");
                    let pw = widgets::pill_size(ui, &text, Pill::Chip, 10.0, 32.0, 13.0).x;
                    if used > 0.0 && used + pw + 6.0 > w {
                        rows.push(vec![]);
                        used = 0.0;
                    }
                    rows.last_mut().unwrap().push((name.clone(), text, pw));
                    used += pw + 6.0;
                }
                let mut toggle = None;
                for row in rows {
                    let (line, _) = ui.allocate_exact_size(vec2(w, 32.0), egui::Sense::hover());
                    let mut x = line.left();
                    for (name, text, pw) in row {
                        let on = picked.contains(&name);
                        let kind = if on { Pill::On } else { Pill::Chip };
                        if widgets::pill_at(ui, Rect::from_min_size(Pos2::new(x, line.top()), vec2(pw, 32.0)), Id::unique(("who", &name)), &text, kind, 10.0).clicked() {
                            toggle = Some(Some(name.clone()));
                        }
                        x += pw + 6.0;
                    }
                    ui.add_space(6.0);
                }
                if !picked.is_empty() && widgets::buttons(ui, Id::unique("who-all"), &["Показать всех"], 0.0).is_some() {
                    toggle = Some(None);
                }
                if let Some(t) = toggle {
                    if let Some(v) = self.logview.as_mut() {
                        match t {
                            None => v.names.clear(),
                            Some(n) => {
                                if !v.names.remove(&n) {
                                    v.names.insert(n);
                                }
                            }
                        }
                    }
                    self.log_refilter();
                }
            }
        }
        let tail = if screen { " Снятый с экрана чат заменится, вернуть его можно кнопкой «С экрана» в «Строках»." } else { "" };
        widgets::label(ui, &format!("Строки чатлога за час до и после СС, пунктир — момент съёмки. Отметь нужные и нажми «На СС»: они встанут в чат тем же шрифтом и цветом, что в игре. Клик по заголовку куска отмечает его целиком.{tail}"), 16.0);
    }

    fn log_names(&self) -> Vec<(String, usize)> {
        let Some(v) = &self.logview else { return vec![] };
        let mut near: HashMap<String, usize> = HashMap::new();
        let mut total: HashMap<String, usize> = HashMap::new();
        for ((when, _), (kind, who, _)) in v.lines.iter().zip(&v.who) {
            if let (Some(who), true) = (who, matches!(kind, Kind::Speech | Kind::Action)) {
                *total.entry(who.clone()).or_default() += 1;
                if (*when - v.at).num_seconds().abs() <= chatlog::LOG_NEAR_S {
                    *near.entry(who.clone()).or_default() += 1;
                }
            }
        }
        let mut ranked: Vec<String> = total.keys().cloned().collect();
        ranked.sort_by(|a, b| (std::cmp::Reverse(near.get(a).copied().unwrap_or(0)), std::cmp::Reverse(total[a]), a)
            .cmp(&(std::cmp::Reverse(near.get(b).copied().unwrap_or(0)), std::cmp::Reverse(total[b]), b)));
        let mut keep: Vec<String> = ranked.iter().take(theme::LOG_NAMES).cloned().collect();
        keep.extend(ranked.iter().skip(theme::LOG_NAMES).filter(|n| v.names.contains(*n)).cloned());
        keep.into_iter().map(|n| {
            let c = total[&n];
            (n, c)
        }).collect()
    }

    pub fn log_refilter(&mut self) {
        let keep = self.cfg.keep.clone();
        let Some(v) = self.logview.as_mut() else { return };
        let seen: Vec<usize> = (0..v.lines.len()).filter(|&k| {
            let (kind, who, _) = &v.who[k];
            (v.all || keep.contains(kind)) && (v.names.is_empty() || who.as_ref().is_some_and(|w| v.names.contains(w)))
        }).collect();
        let picked: Vec<Line> = seen.iter().map(|&k| v.lines[k].clone()).collect();
        let starts: HashSet<usize> = chatlog::log_chunks(&picked, chatlog::LOG_GAP_S).into_iter().collect();
        let mut items = Vec::new();
        let mut mark = None;
        let mut bounds: HashMap<usize, Vec<usize>> = HashMap::new();
        let mut chunk = 0;
        for (n, &k) in seen.iter().enumerate() {
            if mark.is_none() && v.lines[k].0 > v.at {
                mark = Some(items.len());
                items.push(("mark", k));
            }
            if starts.contains(&n) {
                chunk = k;
                bounds.insert(k, vec![]);
                items.push(("head", k));
            }
            bounds.entry(chunk).or_default().push(k);
            items.push(("line", k));
        }
        let mark = mark.unwrap_or_else(|| {
            items.push(("mark", v.lines.len()));
            items.len() - 1
        });
        v.items = items;
        v.mark = mark;
        v.bounds = bounds;
        v.width = None;
        v.offset = None;
    }

    pub fn open_log(&mut self) {
        self.logview = None;
        let Some(shot) = self.target() else { return };
        let name = shot.name.clone().unwrap_or_default();
        let at = compose::shot_time(&name).unwrap_or_else(|| chrono::Local::now().naive_local());
        let lines = chatlog::read_log(&shot.out, at, chatlog::LOG_SPAN_S);
        let saved: HashSet<(String, String)> = chatlog::picked_log(shot.edit.log.as_ref()).iter().map(|(w, p)| chatlog::log_key(*w, p)).collect();
        let on = lines.iter().enumerate().filter(|(_, (w, p))| saved.contains(&chatlog::log_key(*w, p))).map(|(k, _)| k).collect();
        let who = lines.iter().map(|(_, p)| chatlog::log_who(p)).collect();
        self.logview = Some(LogView { name, at, lines, who, on, all: false, names: HashSet::new(), items: vec![], mark: 0, bounds: HashMap::new(),
                                      width: None, offset: None, tops: vec![], wraps: HashMap::new(), lh: 18.0, full: 0.0, top: 0.0 });
        self.log_refilter();
    }

    fn log_layout(&mut self, ui: &Ui, width: f32) {
        let Some(v) = self.logview.as_mut() else { return };
        if v.width == Some(width) {
            return;
        }
        let font = chat_font();
        let measure = |s: &str| ui.fonts_mut(|f| f.layout_no_wrap(s.to_string(), font.clone(), WHITE).size().x);
        let lh = ui.fonts_mut(|f| f.row_height(&font)) + 1.0;
        let mut tops = Vec::new();
        let mut wraps = HashMap::new();
        let mut y = 10.0;
        for (kind, k) in &v.items {
            tops.push(y);
            if *kind == "line" {
                let mut rows: Vec<Vec<(f32, String, String)>> = chatlog::log_rows(&[v.lines[*k].clone()], &measure, width).into_iter().map(|(_, r)| r).collect();
                if rows.is_empty() {
                    rows.push(vec![]);
                }
                y += rows.len() as f32 * lh + 10.0;
                wraps.insert(*k, rows);
            } else {
                y += 40.0;
            }
        }
        v.width = Some(width);
        v.tops = tops;
        v.wraps = wraps;
        v.lh = lh;
        v.full = y + 10.0;
    }

    pub fn draw_log(&mut self, ui: &mut Ui, area: Rect) {
        let p = ui.painter().with_clip_rect(area);
        p.rect_filled(area, CornerRadius::ZERO, BLACK);
        if self.logview.as_ref().is_none_or(|v| v.lines.is_empty()) {
            let g = p.layout("В чатлоге нет строк за час до и после этой СС. Строки пишутся, пока в настройках включён чатлог.".into(),
                             theme::ui(12.0), SUB, area.width() - 80.0);
            let size = g.size();
            p.galley(area.center() - size / 2.0, g, SUB);
            return;
        }
        let x0 = area.left() + 120.0;
        self.log_layout(ui, (area.width() - 148.0).max(200.0));
        let hover = ui.input(|i| i.pointer.hover_pos()).filter(|h| area.contains(*h));
        let v = self.logview.as_mut().unwrap();
        if v.offset.is_none() {
            v.offset = Some(v.tops[v.mark] - area.height() / 2.0);
        }
        let offset = v.offset.unwrap().min(v.full - area.height()).max(0.0);
        v.offset = Some(offset);
        let top = area.top() - offset;
        v.top = top;
        let mut ends: Vec<f32> = v.tops[1..].to_vec();
        ends.push(v.full - 10.0);
        let lh = v.lh;
        for j in 0..v.items.len() {
            let (y, bottom) = (top + v.tops[j], top + ends[j]);
            if bottom < area.top() {
                continue;
            }
            if y > area.bottom() {
                break;
            }
            let (kind, k) = v.items[j];
            let row = Rect::from_min_max(Pos2::new(area.left(), y), Pos2::new(area.right(), bottom));
            let hot = hover.is_some_and(|h| row.contains(h));
            match kind {
                "mark" => {
                    let mid = (y + bottom) / 2.0;
                    let label = format!("СС снята · {}", v.at.format("%H:%M:%S"));
                    crate::tools::dashed_line(&p, Pos2::new(area.left() + 16.0, mid), Pos2::new(area.right() - 16.0, mid), SUB, 4.0, 3.0);
                    let wide = widgets::text_width(ui, &label, theme::semi(9.0)) + 16.0;
                    p.rect_filled(Rect::from_min_size(Pos2::new(x0 - 8.0, mid - 10.0), vec2(wide, 20.0)), CornerRadius::ZERO, BLACK);
                    p.text(Pos2::new(x0, mid), Align2::LEFT_CENTER, label, theme::semi(9.0), WHITE);
                }
                "head" => {
                    let span = v.bounds.get(&k).cloned().unwrap_or_default();
                    let picked = span.iter().filter(|i| v.on.contains(i)).count();
                    let on = picked == span.len() && !span.is_empty();
                    let last = span.last().copied().unwrap_or(k);
                    let text = format!("{}–{} · строк: {}{}", v.lines[k].0.format("%H:%M"), v.lines[last].0.format("%H:%M"), span.len(),
                                       if picked > 0 { format!(" · отмечено: {picked}") } else { String::new() });
                    p.rect_filled(row, CornerRadius::ZERO, if hot { ROW } else { BLACK });
                    widgets::tick(ui, Rect::from_center_size(Pos2::new(area.left() + 25.0, y + 24.0), vec2(18.0, 18.0)), on);
                    p.text(Pos2::new(area.left() + 48.0, y + 24.0), Align2::LEFT_CENTER, text, theme::semi(10.0), if picked > 0 { WHITE } else { SUB });
                }
                _ => {
                    let on = v.on.contains(&k);
                    let first = y + 5.0 + lh / 2.0;
                    p.rect_filled(row, CornerRadius::ZERO, match (on, hot) {
                        (true, true) => MIST,
                        (true, false) => SLATE,
                        (false, true) => ROW,
                        _ => BLACK,
                    });
                    widgets::tick(ui, Rect::from_center_size(Pos2::new(area.left() + 25.0, first), vec2(18.0, 18.0)), on);
                    p.text(Pos2::new(area.left() + 48.0, first), Align2::LEFT_CENTER, v.lines[k].0.format("%H:%M:%S").to_string(), theme::ui(9.0), SUB);
                    if let Some(rows) = v.wraps.get(&k) {
                        for (n, r) in rows.iter().enumerate() {
                            for (x, text, color) in r {
                                let c = chatlog::rgb_of(color);
                                p.text(Pos2::new(x0 + x, y + 5.0 + n as f32 * lh), Align2::LEFT_TOP, text.trim_end(), chat_font(),
                                       Color32::from_rgb(c[0], c[1], c[2]));
                            }
                        }
                    }
                }
            }
            if hot && kind != "mark" {
                ui.ctx().set_cursor_icon(CursorIcon::PointingHand);
            }
        }
        let _ = Stroke::NONE;
    }

    pub fn log_item_at(&self, y: f32) -> usize {
        let Some(v) = &self.logview else { return 0 };
        let rel = y - v.top;
        let idx = v.tops.partition_point(|t| *t <= rel);
        idx.saturating_sub(1).min(v.items.len().saturating_sub(1))
    }

    pub fn log_press(&mut self, pos: Pos2) {
        let Some(v) = &self.logview else { return };
        if v.items.is_empty() {
            return;
        }
        let j = self.log_item_at(pos.y);
        let (kind, k) = v.items[j];
        match kind {
            "head" => {
                let span: HashSet<usize> = v.bounds.get(&k).cloned().unwrap_or_default().into_iter().collect();
                let v = self.logview.as_mut().unwrap();
                if span.is_subset(&v.on) {
                    v.on.retain(|i| !span.contains(i));
                } else {
                    v.on.extend(span);
                }
            }
            "line" => {
                let on = !v.on.contains(&k);
                self.drag = Some(crate::feed::Drag::Log { on, first: j, last: j });
                self.mark_log(j, j, on);
            }
            _ => {}
        }
    }

    pub fn mark_log(&mut self, a: usize, b: usize, on: bool) {
        let Some(v) = self.logview.as_mut() else { return };
        for &(kind, k) in &v.items[a.min(b)..=a.max(b).min(v.items.len() - 1)] {
            if kind == "line" {
                if on {
                    v.on.insert(k);
                } else {
                    v.on.remove(&k);
                }
            }
        }
    }

    pub fn log_hint(&self, pos: Pos2) -> Option<String> {
        let v = self.logview.as_ref()?;
        if v.items.is_empty() {
            return None;
        }
        let (kind, _) = v.items[self.log_item_at(pos.y)];
        match kind {
            "head" => Some("Клик — отметить весь кусок или снять с него отметки".into()),
            "line" => Some("Клик — отметить строку · веди мышью, чтобы отметить несколько".into()),
            _ => None,
        }
    }

    pub fn apply_log(&mut self) {
        let cfg = self.cfg.clone();
        let Some(target) = self.target_name() else { return };
        let Some(v) = &self.logview else { return };
        if v.name != target {
            return;
        }
        if v.on.is_empty() {
            self.note = "отметь хотя бы одну строку".into();
            return;
        }
        let mut keys: Vec<usize> = v.on.iter().copied().collect();
        keys.sort();
        let picked: Vec<Line> = keys.iter().map(|k| v.lines[*k].clone()).collect();
        let result = match self.shot_mut(&target) {
            Some(shot) => store::use_log(shot, &cfg, &picked),
            None => return,
        };
        match result {
            Err(e) => self.note = format!("строки не встали: {e}"),
            Ok(_) => {
                self.tool = Some("lines");
                self.offset = 0.0;
                self.painter.forget();
                self.schedule_save(&target);
                self.note = format!("строк из чатлога: {}", picked.len());
            }
        }
    }

    pub fn from_screen(&mut self) {
        let cfg = self.cfg.clone();
        let Some(target) = self.target_name() else { return };
        let result = match self.shot_mut(&target) {
            Some(shot) => store::use_screen(shot, &cfg),
            None => return,
        };
        match result {
            Err(e) => self.note = format!("кадры чата не открылись: {e}"),
            Ok(_) => {
                self.painter.forget();
                self.schedule_save(&target);
                self.note = "чат снова с экрана".into();
            }
        }
    }
}
