use std::collections::HashSet;
use std::path::PathBuf;
use std::time::{Duration, Instant};

use eframe::egui::{self, Align2, Color32, CornerRadius, CursorIcon, Id, Pos2, Rect, Sense, Stroke, StrokeKind, Ui, vec2};

use crate::feed::{Feed, Job};
use crate::theme::{self, BAR_H, LINE, MIST, PAD, RAIL_W, SIDE_W, SLATE, SUB, VOID, WHITE};
use crate::widgets::{self, Kind};
use crate::win;

pub const UNDO_DELETE: Duration = Duration::from_secs(6);
const TOAST_LIFE: f32 = 2.8;
const DEFENDER: &str = "windowsdefender:";
const PICTURES: [&str; 6] = ["png", "jpg", "jpeg", "webp", "bmp", "gif"];
const MENU_W: f32 = 228.0;
const MENU_ROW: f32 = 34.0;

pub const NEWS: [(&str, &str); 6] = [
    ("Открывается мгновенно", "Программа переписана с нуля: запуск за долю секунды, памяти нужно втрое меньше."),
    ("Стиль и Размытие", "Пресеты цвета, коррекция, свой LUT, камера наблюдения. Лица, номера и ники можно размыть или запикселить."),
    ("Кадр и картинки", "Отражение и наклон кадра. Картинку можно перетащить на СС из папки или вставить через Ctrl+V."),
    ("Отмена всего", "Ctrl+Z и стрелки над СС отменяют любую правку. Удалённую СС можно вернуть из плашки."),
    ("Правый клик по СС", "Копировать, показать в папке, сделать копию для второго варианта или удалить."),
    ("Уведомление у часов", "Когда окно спрятано, готовая СС всплывает с миниатюрой. В настройках можно сразу класть её в буфер."),
];

#[derive(Clone, PartialEq)]
pub enum Remedy {
    Restore,
    Retry,
    Settings,
    Defender,
    Open(PathBuf),
}

pub struct Toast {
    pub text: String,
    pub at: Instant,
    pub action: Option<(&'static str, Remedy)>,
}

pub fn remedies(text: &str) -> Vec<(&'static str, Remedy)> {
    if text.contains("Защитник") {
        return vec![("Сменить папку", Remedy::Settings), ("Открыть Защитник", Remedy::Defender)];
    }
    if let Some((_, path)) = text.split_once("подробности в ") {
        return vec![("Открыть отчёт", Remedy::Open(PathBuf::from(path.trim())))];
    }
    if text.starts_with("Игра не затемнилась") {
        return vec![("Проверить клавиши", Remedy::Settings)];
    }
    if text.starts_with("не скопировалось") {
        return vec![("Ещё раз", Remedy::Retry)];
    }
    vec![]
}

impl Feed {
    pub fn tell(&mut self, text: impl Into<String>, action: Option<(&'static str, Remedy)>) {
        let text = text.into();
        self.note = text.clone();
        self.last_note = text.clone();
        self.toast = Some(Toast { text, at: Instant::now(), action });
    }

    pub fn remedy(&mut self, remedy: Remedy) {
        match remedy {
            Remedy::Restore => self.restore(),
            Remedy::Retry => self.copy(),
            Remedy::Settings => self.want_settings = true,
            Remedy::Defender => win::open(DEFENDER),
            Remedy::Open(path) => win::open(&path.to_string_lossy()),
        }
    }

    pub fn delete(&mut self) {
        let Some(name) = self.name() else { return };
        self.commit_delete();
        self.flush_save();
        self.pending = Some((name.clone(), Instant::now()));
        self.names.retain(|n| *n != name);
        self.index = self.index.min(self.names.len());
        self.tool = None;
        self.offset = 0.0;
        self.menu = None;
        self.open_current();
        self.tell("СС удалена", Some(("Вернуть", Remedy::Restore)));
    }

    pub fn restore(&mut self) {
        let Some((name, _)) = self.pending.take() else { return };
        self.refresh_names();
        if let Some(i) = self.names.iter().position(|n| *n == name) {
            self.index = i + 1;
            self.tool = None;
            self.offset = 0.0;
            self.open_current();
        }
        self.tell("СС вернулась", None);
    }

    pub fn commit_delete(&mut self) {
        let Some((name, _)) = self.pending.take() else { return };
        self.saves.remove(&name);
        if self.toast.as_ref().is_some_and(|t| t.action.as_ref().is_some_and(|(_, r)| *r == Remedy::Restore)) {
            self.toast = None;
        }
        let _ = self.jobs.send(Job::Delete(name, self.cfg.out.clone(), self.cfg.clone()));
    }

    pub fn finish(&mut self) {
        self.save_sync();
        if let Some((name, _)) = self.pending.take() {
            let _ = engine::store::delete_shot(&self.cfg.out, &name, &self.cfg, &win::recycle);
        }
    }

    pub fn deleted(&mut self, name: &str, result: Result<Vec<String>, String>) {
        let here = self.name();
        let heads = match result {
            Ok(h) => h,
            Err(e) => {
                self.refresh_names();
                self.find_again(here);
                self.tell(format!("не удалилось: {e}"), None);
                return;
            }
        };
        for gone in std::iter::once(name.to_string()).chain(heads.iter().cloned()) {
            self.cache.remove(&gone);
            self.forget(&gone);
        }
        self.refresh_names();
        let reload = here.as_ref().is_some_and(|h| heads.contains(h));
        if self.find_again(here) && reload {
            self.open_current();
        }
    }

    fn find_again(&mut self, here: Option<String>) -> bool {
        match here.and_then(|h| self.names.iter().position(|n| *n == h)) {
            Some(i) => {
                self.index = i + 1;
                true
            }
            None => {
                self.index = self.index.min(self.names.len());
                self.open_current();
                false
            }
        }
    }

    pub fn duplicate(&mut self) {
        let Some(name) = self.name() else { return };
        self.flush_save();
        let _ = self.jobs.send(Job::Duplicate(name, self.cfg.out.clone()));
    }

    pub fn duplicated(&mut self, result: Result<String, String>) {
        match result {
            Ok(copy) => {
                self.refresh_names();
                if let Some(i) = self.names.iter().position(|n| *n == copy) {
                    self.index = i + 1;
                    self.tool = None;
                    self.offset = 0.0;
                    self.open_current();
                }
                self.tell("Готова копия: правь её, оригинал останется как был", None);
            }
            Err(e) => self.tell(format!("копия не получилась: {e}"), None),
        }
    }

    pub fn can_undo(&self, back: bool) -> bool {
        let scope: HashSet<String> = self.scene_names().into_iter().chain(self.name()).collect();
        let src = if back { &self.history } else { &self.future };
        src.iter().any(|(n, _)| scope.contains(n))
    }

    pub fn draw_history(&mut self, ui: &Ui, body: Rect) {
        if self.index == 0 || self.shot.is_none() {
            return;
        }
        let area = self.area(body);
        let cy = body.top() - BAR_H / 2.0;
        let p = ui.painter();
        let mut x = area.left();
        for (key, back, hint) in [("undo", true, "Отменить последнюю правку · Ctrl+Z"), ("redo", false, "Вернуть отменённое · Ctrl+Y")] {
            let r = Rect::from_min_size(Pos2::new(x, cy - 16.0), vec2(36.0, 32.0));
            let on = self.can_undo(back) || (back && self.pending.is_some());
            let resp = ui.interact(r, Id::unique(("history", key)), Sense::click());
            let hot = ui.ctx().animate_bool_responsive(Id::unique(("history-hot", key)), on && resp.hovered());
            if hot > 0.01 {
                p.rect_filled(r, CornerRadius::same(8), MIST.gamma_multiply(hot));
            }
            let ink = if on { crate::feed::mix(SUB, WHITE, hot) } else { MIST };
            p.text(r.center(), Align2::CENTER_CENTER, theme::icon(key), theme::glyph(14.0), ink);
            if resp.hovered() {
                self.hint_text = Some(hint.to_string());
                if on {
                    ui.ctx().set_cursor_icon(CursorIcon::PointingHand);
                }
            }
            if on && resp.clicked() {
                if back && self.pending.is_some() { self.restore() } else { self.undo(back) }
            }
            x += 40.0;
        }
    }

    pub fn draw_toast(&mut self, ui: &Ui, body: Rect) {
        self.toast_rect = None;
        let Some(t) = &self.toast else { return };
        let life = if t.action.is_some() { UNDO_DELETE.as_secs_f32() } else { TOAST_LIFE };
        let age = t.at.elapsed().as_secs_f32();
        if age > life {
            self.toast = None;
            return;
        }
        let alpha = if age < 0.15 { theme::ease(age / 0.15) } else if age > life - 0.4 { (life - age) / 0.4 } else { 1.0 };
        let (text, action) = (t.text.clone(), t.action.clone());
        let area = self.area(body);
        let label_w = action.as_ref().map(|(l, _)| widgets::text_width(ui, l, theme::semi(10.0)) + 32.0).unwrap_or(0.0);
        let text_w = widgets::text_width(ui, &text, theme::ui(10.0));
        let w = (text_w + 44.0 + if label_w > 0.0 { label_w + 4.0 } else { 0.0 }).min(area.width() - 40.0);
        let r = Rect::from_min_size(Pos2::new(area.center().x - w / 2.0, area.top() + 16.0 - 6.0 * (1.0 - alpha)), vec2(w, 40.0));
        let p = ui.ctx().layer_painter(egui::LayerId::new(egui::Order::Foreground, Id::unique("toast")));
        let shadow = egui::epaint::Shadow { offset: [0, 6], blur: 18, spread: 0, color: Color32::from_black_alpha((110.0 * alpha) as u8) };
        p.add(shadow.as_shape(r, CornerRadius::same(20)));
        p.rect_filled(r, CornerRadius::same(20), Color32::from_rgba_unmultiplied(30, 32, 38, (245.0 * alpha) as u8));
        p.rect_stroke(r, CornerRadius::same(20), Stroke::new(1.0, LINE.gamma_multiply(alpha)), StrokeKind::Inside);
        let hover = ui.input(|i| i.pointer.hover_pos());
        let mut picked = None;
        if let Some((label, remedy)) = action {
            p.text(Pos2::new(r.left() + 20.0, r.center().y), Align2::LEFT_CENTER, &text, theme::ui(10.0), WHITE.gamma_multiply(alpha));
            let b = Rect::from_min_size(Pos2::new(r.right() - label_w - 6.0, r.top() + 6.0), vec2(label_w, 28.0));
            let resp = ui.interact(b, Id::unique("toast-act"), Sense::click());
            let hot = ui.ctx().animate_bool_responsive(Id::unique("toast-act-hot"), resp.hovered());
            p.rect_filled(b, CornerRadius::same(14), crate::feed::mix(Color32::from_rgb(0xdd, 0xdf, 0xe4), WHITE, hot).gamma_multiply(alpha));
            p.text(b.center(), Align2::CENTER_CENTER, label, theme::semi(10.0), VOID.gamma_multiply(alpha));
            if resp.hovered() {
                ui.ctx().set_cursor_icon(CursorIcon::PointingHand);
            }
            if resp.clicked() {
                picked = Some(remedy);
            }
            self.toast_rect = Some(r);
        } else {
            p.text(r.center(), Align2::CENTER_CENTER, &text, theme::ui(10.0), WHITE.gamma_multiply(alpha));
        }
        if hover.is_some_and(|h| r.contains(h)) && self.toast_rect.is_some() {
            if let Some(t) = self.toast.as_mut() {
                t.at = Instant::now() - Duration::from_millis(200);
            }
            if let Some(p) = self.pending.as_mut() {
                p.1 = Instant::now();
            }
        }
        if let Some(remedy) = picked {
            self.toast = None;
            self.remedy(remedy);
        }
        ui.ctx().request_repaint();
    }

    pub fn menu_items(&self) -> Vec<(&'static str, &'static str, &'static str)> {
        let mut items = vec![("copy", "Копировать", "Ctrl+C"), ("folder", "Показать в папке", "")];
        if self.shot.is_some() {
            items.push(("duplicate", "Сделать копию", ""));
        }
        items.push(("delete", "Удалить", "Del"));
        items
    }

    pub fn open_menu(&mut self, pos: Pos2, bounds: Rect) {
        let h = 8.0 + MENU_ROW * self.menu_items().len() as f32 + 9.0;
        let x = pos.x.min(bounds.right() - MENU_W - 8.0);
        let y = if pos.y + h > bounds.bottom() - 8.0 { pos.y - h } else { pos.y };
        self.menu = Some(Rect::from_min_size(Pos2::new(x, y), vec2(MENU_W, h)));
        self.popup = None;
    }

    pub fn menu_allowed(&self) -> bool {
        self.index > 0 && !matches!(self.tool, Some("lines") | Some("logpick") | Some("carry") | Some("photopick") | Some("scenepick"))
    }

    pub fn draw_menu(&mut self, ui: &Ui) {
        let Some(rect) = self.menu else { return };
        let p = ui.ctx().layer_painter(egui::LayerId::new(egui::Order::Foreground, Id::unique("menu")));
        let shadow = egui::epaint::Shadow { offset: [0, 8], blur: 24, spread: 0, color: Color32::from_black_alpha(120) };
        p.add(shadow.as_shape(rect, CornerRadius::same(10)));
        p.rect_filled(rect, CornerRadius::same(10), SLATE);
        p.rect_stroke(rect, CornerRadius::same(10), Stroke::new(1.0, LINE), StrokeKind::Inside);
        let items = self.menu_items();
        let mut y = rect.top() + 4.0;
        let mut picked = None;
        for (key, label, keys) in items {
            if key == "delete" {
                p.line_segment([Pos2::new(rect.left() + 12.0, y + 4.0), Pos2::new(rect.right() - 12.0, y + 4.0)], Stroke::new(1.0, LINE));
                y += 9.0;
            }
            let row = Rect::from_min_size(Pos2::new(rect.left() + 4.0, y), vec2(rect.width() - 8.0, MENU_ROW));
            let resp = ui.interact(row, Id::unique(("menu", key)), Sense::click());
            if resp.hovered() {
                p.rect_filled(row, CornerRadius::same(6), MIST);
                ui.ctx().set_cursor_icon(CursorIcon::PointingHand);
            }
            p.text(Pos2::new(row.left() + 12.0, row.center().y), Align2::LEFT_CENTER, label, theme::ui(10.0), WHITE);
            if !keys.is_empty() {
                p.text(Pos2::new(row.right() - 12.0, row.center().y), Align2::RIGHT_CENTER, keys, theme::ui(9.0), SUB);
            }
            if resp.clicked() {
                picked = Some(key);
            }
            y += MENU_ROW;
        }
        if let Some(key) = picked {
            self.menu = None;
            match key {
                "copy" => self.copy(),
                "folder" => self.open_folder(),
                "duplicate" => self.duplicate(),
                _ => self.delete(),
            }
        }
    }

    fn open_images(&mut self) {
        if self.tool != Some("images") {
            self.toggle_tool("images");
        }
    }

    pub fn paste(&mut self) {
        if self.index == 0 || self.shot.is_none() {
            return;
        }
        match win::clipboard_image() {
            Some(img) => {
                self.open_images();
                self.add_image(img);
            }
            None => self.tell("в буфере обмена нет картинки", None),
        }
    }

    pub fn drops(&mut self, ui: &Ui, body: Rect) {
        let (hovering, dropped) = ui.input(|i| (!i.raw.hovered_files.is_empty(), i.raw.dropped_files.clone()));
        let open = self.index > 0 && self.shot.is_some();
        if hovering {
            let area = self.area(body).shrink(8.0);
            let p = ui.ctx().layer_painter(egui::LayerId::new(egui::Order::Foreground, Id::unique("drop")));
            p.rect_filled(area, CornerRadius::same(16), Color32::from_rgba_unmultiplied(10, 10, 10, 210));
            crate::tools::dashed_rect(&p, area.shrink(12.0), WHITE.gamma_multiply(0.6), 8.0, 6.0);
            let (title, sub) = if open {
                ("Отпусти, и картинка ляжет поверх СС", "PNG, JPG, WEBP, BMP или GIF")
            } else {
                ("Сначала открой СС", "Картинку можно положить только на открытую СС")
            };
            p.text(Pos2::new(area.center().x, area.center().y - 12.0), Align2::CENTER_CENTER, title, theme::display(20.0), WHITE);
            p.text(Pos2::new(area.center().x, area.center().y + 18.0), Align2::CENTER_CENTER, sub, theme::ui(10.0), SUB);
            ui.ctx().request_repaint();
        }
        let Some(path) = dropped.first().map(|f| f.path().to_path_buf()) else { return };
        if !open {
            self.tell("Открой СС, чтобы положить на неё картинку", None);
            return;
        }
        let ext = path.extension().map(|e| e.to_string_lossy().to_lowercase()).unwrap_or_default();
        if !PICTURES.contains(&ext.as_str()) {
            self.tell("Это не картинка: подойдут PNG, JPG, WEBP, BMP или GIF", None);
            return;
        }
        match image::open(&path) {
            Ok(img) => {
                self.open_images();
                self.add_image(img.to_rgba8());
            }
            Err(e) => self.tell(format!("картинка не открылась: {e}"), None),
        }
    }

    pub fn draw_news(&mut self, ui: &mut Ui, body: Rect) {
        if !self.news {
            return;
        }
        let right = body.right() - RAIL_W - 24.0;
        let left = body.left() + PAD + 12.0 + SIDE_W + 120.0 + 48.0;
        let w = (right - left).min(392.0);
        if w < 300.0 {
            return;
        }
        let inner = w - 56.0;
        let p = ui.painter().clone();
        let title = p.layout("Что нового в Snapline 2.0".to_string(), theme::display(20.0), WHITE, inner);
        let items: Vec<_> = NEWS.iter().map(|(head, text)| {
            (p.layout(head.to_string(), theme::semi(10.0), WHITE, inner), p.layout(text.to_string(), theme::ui(10.0), SUB, inner))
        }).collect();
        let list_h: f32 = items.iter().map(|(a, b)| a.size().y + 2.0 + b.size().y).sum::<f32>() + 14.0 * (items.len() as f32 - 1.0);
        let h = 28.0 + title.size().y + 18.0 + list_h + 24.0 + 32.0 + 28.0;
        let r = Rect::from_min_size(Pos2::new(right - w, body.top() + PAD), vec2(w, h.min(body.height() - 2.0 * PAD)));
        let shadow = egui::epaint::Shadow { offset: [0, 10], blur: 32, spread: 0, color: Color32::from_black_alpha(110) };
        p.add(shadow.as_shape(r, CornerRadius::same(16)));
        p.rect_filled(r, CornerRadius::same(16), Color32::from_rgba_unmultiplied(10, 10, 10, 236));
        p.rect_stroke(r, CornerRadius::same(16), Stroke::new(1.0, LINE), StrokeKind::Inside);
        let x = r.left() + 28.0;
        let mut y = r.top() + 28.0;
        let title_h = title.size().y;
        p.galley(Pos2::new(x, y), title, WHITE);
        y += title_h + 18.0;
        for (head, text) in items {
            let (hh, th) = (head.size().y, text.size().y);
            p.galley(Pos2::new(x, y), head, WHITE);
            p.galley(Pos2::new(x, y + hh + 2.0), text, SUB);
            y += hh + 2.0 + th + 14.0;
        }
        y += 10.0;
        let tour_w = widgets::text_width(ui, "Пройти тур по редактору", theme::semi(10.0)) + 32.0;
        let tour = widgets::pill_at(ui, Rect::from_min_size(Pos2::new(x, y), vec2(tour_w, 32.0)), Id::unique("news-tour"), "Пройти тур по редактору", Kind::Primary, 10.0);
        let ok_w = widgets::text_width(ui, "Понятно", theme::semi(10.0)) + 32.0;
        let ok = widgets::pill_at(ui, Rect::from_min_size(Pos2::new(x + tour_w + 8.0, y), vec2(ok_w, 32.0)), Id::unique("news-ok"), "Понятно", Kind::Ghost, 10.0);
        if tour.clicked() {
            self.news = false;
            self.news_closed = Some(true);
        } else if ok.clicked() {
            self.news = false;
            self.news_closed = Some(false);
        }
    }
}
