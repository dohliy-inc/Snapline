use std::path::PathBuf;
use std::sync::Arc;
use std::sync::atomic::{AtomicBool, Ordering};
use std::sync::mpsc::Sender;
use std::time::{Duration, Instant};

use eframe::egui::{self, Align2, Color32, CornerRadius, Id, Pos2, Rect, Sense, Stroke, TextureHandle, Ui, vec2};
use engine::chat::Kind;
use engine::compose;
use engine::config::{Config, Raw};
use engine::edit::Edit;
use engine::store::{self, Shot};
use image::RgbImage;

use crate::app::Msg;
use crate::feed::{full_uv, texture};
use crate::painter::{Geo, Painter};
use crate::theme::{self, ERR, HAIR, LINE, PAD, SUB, VOID, WHITE};
use crate::widgets::{self, Kind as Pill};

pub const SAMPLE_BG: &[u8] = include_bytes!("../../../samples/example_bg.webp");
pub const SAMPLE_CHAT: &[u8] = include_bytes!("../../../samples/example_chat.png");
const LOGO: &[u8] = include_bytes!("../../../assets/ls_project.png");
const LIST_W: f32 = 640.0;
const LABEL_W: f32 = 220.0;

pub enum Action {
    Set(&'static str, String),
    Tray(bool),
    OpenFolder,
    Tour,
    Folder(PathBuf),
    Cleared,
}

pub struct Settings {
    tx: Sender<Msg>,
    ctx: egui::Context,
    pub sample: Option<Shot>,
    sample_loading: bool,
    sample_missing: bool,
    painter: Painter,
    geo: Option<Geo>,
    encoded: Option<(Arc<RgbImage>, TextureHandle, usize)>,
    estimate_rev: u64,
    estimate_due: Option<Instant>,
    estimate_key: String,
    capturing: bool,
    key_note: Option<(String, bool)>,
    chatlog_stop: Option<Arc<AtomicBool>>,
    chatlog_state: (String, Color32),
    quality: Option<f64>,
    margin: Option<f64>,
    frame_text: (String, String),
    logo: Option<TextureHandle>,
    look: Option<std::collections::BTreeMap<String, f64>>,
    lut_note: Option<String>,
}

impl Settings {
    pub fn new(tx: Sender<Msg>, ctx: egui::Context) -> Settings {
        Settings {
            tx,
            ctx,
            sample: None,
            sample_loading: false,
            sample_missing: false,
            painter: Painter::default(),
            geo: None,
            encoded: None,
            estimate_rev: 0,
            estimate_due: None,
            estimate_key: String::new(),
            capturing: false,
            key_note: None,
            chatlog_stop: None,
            chatlog_state: ("Выключен".into(), SUB),
            quality: None,
            margin: None,
            frame_text: (String::new(), String::new()),
            logo: None,
            look: None,
            lut_note: None,
        }
    }

    pub fn sample_loaded(&mut self, shot: Option<Shot>) {
        self.sample_loading = false;
        self.sample_missing = shot.is_none();
        if self.sample.is_none() {
            self.sample = shot;
        }
        self.painter.forget();
        self.estimate_key.clear();
    }

    pub fn estimated(&mut self, rev: u64, value: Option<(RgbImage, usize)>) {
        if rev != self.estimate_rev {
            return;
        }
        if let Some((img, size)) = value {
            let t = texture(&self.ctx, "estimate", &img);
            self.encoded = Some((Arc::new(img), t, size));
        }
    }

    pub fn forget_sample(&mut self) {
        self.sample = None;
        self.encoded = None;
        self.estimate_key.clear();
        self.painter.forget();
    }

    pub fn toggle_chatlog(&mut self, on: bool, out: &std::path::Path) {
        if on && self.chatlog_stop.is_none() {
            let stop = Arc::new(AtomicBool::new(false));
            let folder = out.join("chatlog");
            let flag = stop.clone();
            std::thread::spawn(move || {
                let report = |m: &str| engine::config::emit(engine::config::Event::Chatlog(m.to_string()));
                engine::cdp::run(engine::chatlog::PORT, &format!("cfx-nui-{}", engine::chatlog::RESOURCE), &folder, flag, &report);
            });
            self.chatlog_stop = Some(stop);
            self.chatlog_state = ("Запускаю…".into(), WHITE);
        } else if !on {
            if let Some(stop) = self.chatlog_stop.take() {
                stop.store(true, Ordering::Relaxed);
            }
            self.chatlog_state = ("Выключен".into(), SUB);
        }
    }

    pub fn chatlog_running(&self) -> bool {
        self.chatlog_stop.is_some()
    }

    pub fn chatlog_note(&mut self, msg: &str) {
        if self.chatlog_stop.is_some() {
            self.chatlog_state = (msg.to_string(), WHITE);
        }
    }

    fn mode_text(cfg: &Config) -> String {
        let keys = if cfg.source == "log" { cfg.hud_key.clone() } else { format!("{} и {}", cfg.hud_key, cfg.dark_key) };
        if cfg.auto { format!("Ты жмёшь только {}, а {keys} программа нажмёт сама.", cfg.key) } else { format!("Перед {} ты сам жмёшь {keys}, программа только снимает.", cfg.key) }
    }

    fn load_sample(&mut self, cfg: &Config, cached: Option<&Shot>) -> bool {
        if let Some(shot) = cached {
            self.sample = Some(shot.clone());
            return true;
        }
        if !self.sample_loading && !self.sample_missing {
            self.sample_loading = true;
            let (cfg, tx, ctx) = (cfg.clone(), self.tx.clone(), self.ctx.clone());
            std::thread::spawn(move || {
                let shot = store::sample_shot(&cfg, SAMPLE_BG, SAMPLE_CHAT);
                let _ = tx.send(Msg::SampleLoaded(shot));
                ctx.request_repaint();
            });
        }
        false
    }

    pub fn keys(&mut self, ctx: &egui::Context, cfg: &Config) -> Vec<Action> {
        if !self.capturing {
            return vec![];
        }
        let mut out = vec![];
        for e in ctx.input(|i| i.events.clone()) {
            let egui::Event::Key { key, pressed: true, .. } = e else { continue };
            use egui::Key;
            if key == Key::Escape {
                self.capturing = false;
                self.key_note = None;
                return out;
            }
            let name = match key {
                Key::Insert => Some("INSERT".to_string()),
                Key::Home => Some("HOME".into()),
                Key::End => Some("END".into()),
                Key::PageUp => Some("PAGEUP".into()),
                Key::PageDown => Some("PAGEDOWN".into()),
                k => {
                    let s = format!("{k:?}");
                    s.strip_prefix('F').filter(|n| n.parse::<u32>().is_ok_and(|v| (1..=24).contains(&v))).map(|_| s.clone())
                }
            };
            match name {
                None => self.key_note = Some(("Не подойдёт: нужна F1–F24, Insert, Home, End, PgUp или PgDn".into(), true)),
                Some(k) => {
                    self.capturing = false;
                    if k == cfg.hud_key || k == cfg.dark_key {
                        self.key_note = Some((format!("{k} занята игрой, выбери другую"), true));
                    } else {
                        self.key_note = None;
                        out.push(Action::Set("hotkey", k));
                    }
                }
            }
            break;
        }
        out
    }

    fn fold(ui: &mut Ui, key: &str, title: &str, summary: &str, first: bool) -> egui::collapsing_header::CollapsingState {
        let id = Id::new(("settings-fold", key));
        let mut state = egui::collapsing_header::CollapsingState::load_with_default_open(ui.ctx(), id, first);
        let (rect, _) = ui.allocate_exact_size(vec2(LIST_W, 60.0), Sense::hover());
        Self::hair(ui);
        let resp = ui.interact(rect, id.with("head"), Sense::click());
        let open = state.openness(ui.ctx());
        let hot = ui.ctx().animate_bool_responsive(id.with("hot"), resp.hovered());
        let p = ui.painter();
        if hot > 0.01 {
            p.rect_filled(rect.expand2(vec2(10.0, -4.0)), CornerRadius::same(10), theme::SLATE.gamma_multiply(hot * 0.7));
        }
        p.text(Pos2::new(rect.left(), rect.top() + 21.0), Align2::LEFT_CENTER, title, theme::semi(13.0), WHITE);
        p.text(Pos2::new(rect.left(), rect.top() + 41.0), Align2::LEFT_CENTER, summary, theme::ui(9.0), SUB);
        let chevron = Pos2::new(rect.right() - 12.0, rect.center().y);
        let glyph = egui::epaint::TextShape::new(chevron, p.layout_no_wrap(theme::icon("down").to_string(), theme::glyph(11.0), crate::feed::mix(SUB, WHITE, hot)), WHITE);
        let size = glyph.galley.size();
        let turned = std::f32::consts::PI * open;
        let center = egui::Vec2::new(size.x / 2.0, size.y / 2.0);
        let rot = egui::emath::Rot2::from_angle(turned);
        let pos = chevron - rot * center;
        p.add(egui::epaint::TextShape { pos, angle: turned, ..glyph });
        if resp.hovered() {
            ui.ctx().set_cursor_icon(egui::CursorIcon::PointingHand);
        }
        if resp.clicked() {
            state.toggle(ui);
            state.store(ui.ctx());
        }
        state
    }

    fn hair(ui: &mut Ui) {
        let (r, _) = ui.allocate_exact_size(vec2(LIST_W, 1.0), Sense::hover());
        ui.painter().rect_filled(r, CornerRadius::ZERO, HAIR);
    }

    fn row(ui: &mut Ui, title: &str, sub: Option<&str>, sub_color: Color32, control: impl FnOnce(&mut Ui)) {
        ui.add_space(10.0);
        ui.horizontal_top(|ui| {
            ui.vertical(|ui| {
                ui.set_width(LABEL_W);
                ui.add_space(2.0);
                ui.label(egui::RichText::new(title).font(theme::semi(11.0)).color(WHITE));
                if let Some(s) = sub {
                    ui.add_space(2.0);
                    ui.set_max_width(LABEL_W - 20.0);
                    ui.add(egui::Label::new(egui::RichText::new(s).font(theme::ui(9.0)).color(sub_color)).wrap());
                }
            });
            ui.vertical(|ui| {
                ui.set_width(LIST_W - LABEL_W);
                control(ui);
            });
        });
        ui.add_space(10.0);
        Self::hair(ui);
    }

    #[allow(clippy::too_many_arguments)]
    pub fn show(&mut self, ui: &mut Ui, body: Rect, cfg: &Config, raw: &Raw, cached: Option<&Shot>, update: Option<&(String, String)>) -> Vec<Action> {
        let mut actions = vec![];
        let list = Rect::from_min_size(Pos2::new(body.left() + PAD + 12.0, body.top() + 8.0), vec2(LIST_W + 14.0, body.height() - 8.0 - PAD));
        let mut child = ui.new_child(egui::UiBuilder::new().max_rect(list).id_salt("settings-list"));
        child.set_clip_rect(list);
        egui::ScrollArea::vertical().id_salt("settings-scroll").auto_shrink([false, false]).show(&mut child, |ui| {
            ui.set_width(LIST_W);
            ui.spacing_mut().item_spacing = vec2(0.0, 0.0);
            self.list(ui, cfg, raw, &mut actions);
        });
        let right = Rect::from_min_max(Pos2::new(list.right() + 24.0, body.top() + 8.0), Pos2::new(body.right() - PAD, body.bottom() - PAD));
        self.credits(ui, right, update);
        self.example(ui, Rect::from_min_max(right.min, Pos2::new(right.right(), right.bottom() - 90.0)), cfg, cached);
        actions
    }

    fn list(&mut self, ui: &mut Ui, cfg: &Config, raw: &Raw, actions: &mut Vec<Action>) {
        let w = LIST_W - LABEL_W;
        let summary = capture_summary(cfg);
        let mut fold = Self::fold(ui, "capture", "Съёмка", &summary, true);
        fold.show_body_unindented(ui, |ui| {
        let (note, bad) = self.key_note.clone().unwrap_or_else(|| (if self.capturing { "Нажми нужную клавишу на клавиатуре. Esc — отмена".into() } else { "Её жмёшь в игре, чтобы снять СС. Кликни, чтобы сменить".into() }, false));
        let capturing = self.capturing;
        let mut start = false;
        Self::row(ui, "Клавиша съёмки", Some(&note), if bad { ERR } else { SUB }, |ui| {
            let text = if capturing { "Нажми клавишу…".to_string() } else { cfg.key.clone() };
            let size = widgets::pill_size(ui, &text, Pill::Ghost, 12.0, 36.0, 18.0);
            let (r, _) = ui.allocate_exact_size(size, Sense::hover());
            if widgets::pill_at(ui, r, Id::unique("hotkey"), &text, Pill::Ghost, 12.0).clicked() {
                start = true;
            }
        });
        if start {
            self.capturing = true;
            self.key_note = None;
        }
        Self::row(ui, "Режим", Some(&Self::mode_text(cfg)), SUB, |ui| {
            if let Some(v) = widgets::choice(ui, Id::unique("set-mode"), theme::MODES, if cfg.auto { "yes" } else { "no" }, w) {
                actions.push(Action::Set("auto", v));
            }
        });
        Self::row(ui, "Чат", Some("С экрана — чат вырезается из игры в момент снимка. Из чатлога — снимается только картинка, а строки выберешь потом из записи чата"), SUB, |ui| {
            if let Some(v) = widgets::choice(ui, Id::unique("set-source"), theme::SOURCES, &cfg.source, w) {
                if v == "log" && !cfg.chatlog {
                    actions.push(Action::Set("chatlog", "yes".into()));
                }
                actions.push(Action::Set("source", v));
            }
        });
        Self::row(ui, "Звук", Some("Короткий сигнал, когда СС готова. Удобно, когда игра на весь экран"), SUB, |ui| {
            if let Some(v) = widgets::choice(ui, Id::unique("set-sound"), theme::SOUND, if cfg.sound { "yes" } else { "no" }, w) {
                actions.push(Action::Set("sound", v));
            }
        });
        Self::row(ui, "Уведомление", Some("Когда окно спрятано, готовая СС всплывает у часов с миниатюрой. Клик по ней открывает СС"), SUB, |ui| {
            if let Some(v) = widgets::choice(ui, Id::unique("set-notify"), theme::SOUND, if cfg.notify { "yes" } else { "no" }, w) {
                actions.push(Action::Set("notify", v));
            }
        });
        Self::row(ui, "Сразу в буфер", Some("Готовая СС сама попадает в буфер обмена: на форуме можно сразу жать Ctrl+V"), SUB, |ui| {
            if let Some(v) = widgets::choice(ui, Id::unique("set-autocopy"), theme::SOUND, if cfg.autocopy { "yes" } else { "no" }, w) {
                actions.push(Action::Set("autocopy", v));
            }
        });
        Self::row(ui, "Трей", Some("Крестик прячет окно к часам, а съёмка продолжает работать. Закрыть совсем — правой кнопкой по значку у часов"), SUB, |ui| {
            if let Some(v) = widgets::choice(ui, Id::unique("set-tray"), theme::SOUND, if cfg.tray { "yes" } else { "no" }, w) {
                actions.push(Action::Tray(v == "yes"));
            }
        });
        });
        let summary = frame_summary(cfg);
        let mut fold = Self::fold(ui, "frame", "Новые СС: кадр и файл", &summary, false);
        fold.show_body_unindented(ui, |ui| {
        let base = self.sample.as_ref().map(|s| compose::plan(s.bg.dimensions(), &Edit::new(cfg, &s.rows), None).base).unwrap_or((1440, 1440));
        let mut text = self.frame_text.clone();
        Self::row(ui, "Кадр", Some("Форма новых СС. Квадрат удобен для форума, Экран — как в игре, Свой — точные ширина и высота"), SUB, |ui| {
            if let Some(v) = crate::tools::frame_pick(ui, Id::unique("set-frame"), theme::FORMATS, &cfg.format, &mut text, base, w, engine::config::FRAME_RANGE) {
                actions.push(Action::Set("format", v));
            }
        });
        self.frame_text = text;
        Self::row(ui, "Размер файла", Some("Длина короткой стороны картинки. «Как снято» — без уменьшения"), SUB, |ui| {
            if engine::config::exact_of(&cfg.format).is_some() {
                ui.label(egui::RichText::new("Задан шириной и высотой кадра").font(theme::ui(10.0)).color(SUB));
            } else {
                let mut options: Vec<(&str, &str)> = theme::SIZES.to_vec();
                if !theme::SIZES.iter().any(|(k, _)| *k == cfg.size) {
                    options.push((cfg.size.as_str(), cfg.size.as_str()));
                }
                if let Some(v) = widgets::choice(ui, Id::unique("set-size"), &options, &cfg.size, w) {
                    actions.push(Action::Set("size", v));
                }
            }
        });
        Self::row(ui, "Файл", Some("JPG весит примерно втрое меньше PNG. Чат в обоих остаётся чётким"), SUB, |ui| {
            if let Some(v) = widgets::choice(ui, Id::unique("set-file"), theme::FILES, &cfg.file, w) {
                actions.push(Action::Set("file", v));
            }
        });
        if cfg.file == "jpg" {
            let value = self.quality.unwrap_or(cfg.quality as f64);
            let mut done = None;
            let mut moved = None;
            Self::row(ui, "Качество JPG", Some("Чем ниже, тем легче файл. Сжимается только фон, текст чата всегда чёткий. Наведи мышь на пример справа — лупа покажет пиксели"), SUB, |ui| {
                let s = widgets::slider(ui, Id::unique("set-quality"), 10.0, 100.0, value, 1.0, &|v| format!("{v:.0}"), w - 20.0);
                if s.moved {
                    moved = Some(s.value);
                }
                if s.done {
                    done = Some(s.value);
                }
            });
            if let Some(v) = moved {
                self.quality = Some(v);
                self.estimate_due = Some(Instant::now() + Duration::from_millis(150));
            }
            if let Some(v) = done {
                self.quality = None;
                actions.push(Action::Set("quality", (v as i64).to_string()));
            }
        }
        });
        let summary = style_summary(cfg);
        let mut fold = Self::fold(ui, "style", "Новые СС: стиль", &summary, false);
        fold.show_body_unindented(ui, |ui| {
        Self::row(ui, "Цвет", Some("Готовый цветокор для каждой новой СС. Поправить любую можно в редакторе, в «Стиле»"), SUB, |ui| {
            if let Some(v) = widgets::choice(ui, Id::unique("set-preset"), theme::PRESET_NAMES, &cfg.preset, w) {
                actions.push(Action::Set("preset", v));
            }
        });
        let look = self.look.clone().unwrap_or_else(|| cfg.look.clone());
        let mut moved = None;
        let mut done = None;
        let mut reset = false;
        Self::row(ui, "Коррекция", Some("Яркость, контраст, зерно и остальное поверх цвета"), SUB, |ui| {
            for (k, (key, title)) in theme::LOOK_NAMES.iter().enumerate() {
                widgets::label(ui, title, if k == 0 { 0.0 } else { 6.0 });
                let value = look.get(*key).copied().unwrap_or(0.0);
                let lo = theme::look_range(key);
                let s = widgets::slider(ui, Id::unique(("set-look", *key)), lo, 100.0, value, 1.0, &|v| theme::look_value(v, lo), w - 20.0);
                if s.moved {
                    moved = Some((key.to_string(), s.value.round()));
                }
                if s.done {
                    done = Some((key.to_string(), s.value.round()));
                }
            }
            if !look.is_empty() && widgets::buttons(ui, Id::unique("set-look-reset"), &["Сбросить коррекцию"], 10.0).is_some() {
                reset = true;
            }
        });
        if let Some((k, v)) = moved.clone().or(done.clone()) {
            let mut next = look.clone();
            next.insert(k, v);
            next.retain(|_, v| *v != 0.0);
            if done.is_some() {
                self.look = None;
                actions.push(Action::Set("look", engine::config::look_text(&next)));
            } else {
                self.look = Some(next);
                self.estimate_due = Some(Instant::now() + Duration::from_millis(150));
            }
        }
        if reset {
            self.look = None;
            actions.push(Action::Set("look", String::new()));
        }
        let lut_note = self.lut_note.clone();
        let mut lut_error = None;
        Self::row(ui, "LUT", Some(lut_note.as_deref().unwrap_or("Свой цветокор из .cube — тот же, что в ReShade или видеоредакторе")),
                  if lut_note.is_some() { ERR } else { SUB }, |ui| {
            if !cfg.lut.is_empty() {
                ui.label(egui::RichText::new(format!("Сейчас: {}", cfg.lut)).font(theme::ui(9.0)).color(SUB));
            }
            let labels: Vec<&str> = if cfg.lut.is_empty() { vec!["Загрузить .cube"] } else { vec!["Заменить", "Убрать"] };
            match widgets::buttons(ui, Id::unique("set-lut"), &labels, if cfg.lut.is_empty() { 0.0 } else { 8.0 }) {
                Some(0) => {
                    if let Some(path) = rfd::FileDialog::new().set_title("LUT для новых СС").add_filter("LUT", &["cube"]).add_filter("Все файлы", &["*"]).pick_file() {
                        match compose::add_lut(&cfg.out, &path) {
                            Ok(name) => actions.push(Action::Set("lut", name)),
                            Err(e) => lut_error = Some(format!("LUT не загрузился: {e}")),
                        }
                    }
                }
                Some(1) => actions.push(Action::Set("lut", String::new())),
                _ => {}
            }
        });
        if lut_error.is_some() || actions.iter().any(|a| matches!(a, Action::Set("lut", _))) {
            self.lut_note = lut_error;
        }
        Self::row(ui, "Камера", Some("Рамка, время и надпись камеры наблюдения или бодикама"), SUB, |ui| {
            if let Some(v) = widgets::choice(ui, Id::unique("set-style"), theme::STYLES, &cfg.style, w) {
                actions.push(Action::Set("style", v));
            }
        });
        });
        let summary = chat_summary(cfg);
        let mut fold = Self::fold(ui, "chat", "Новые СС: чат", &summary, false);
        fold.show_body_unindented(ui, |ui| {
        Self::row(ui, "Текст чата", Some("Размер букв чата по сравнению с игрой"), SUB, |ui| {
            if let Some(v) = widgets::choice(ui, Id::unique("set-scale"), theme::SCALES, raw.get("text_scale"), w) {
                actions.push(Action::Set("text_scale", v));
            }
        });
        Self::row(ui, "Обводка", Some("Тёмный контур вокруг букв, чтобы чат читался на светлом фоне"), SUB, |ui| {
            if let Some(v) = widgets::choice(ui, Id::unique("set-outline"), theme::OUTLINES, raw.get("outline"), w) {
                actions.push(Action::Set("outline", v));
            }
        });
        Self::row(ui, "Угол чата", Some("Куда встанет чат в новой СС. Потом его можно перетащить мышью"), SUB, |ui| {
            if let Some(v) = widgets::choice(ui, Id::unique("set-pos"), theme::POSITIONS, &cfg.chat_pos, 280.0) {
                actions.push(Action::Set("chat_pos", v));
            }
        });
        let margin = self.margin.unwrap_or(cfg.margin as f64);
        let mut set_margin = None;
        let mut move_margin = None;
        Self::row(ui, "Отступ от края", Some("Расстояние от чата до края картинки"), SUB, |ui| {
            let s = widgets::slider(ui, Id::unique("set-margin"), 0.0, 96.0, margin, 2.0, &|v| format!("{v:.0} px"), w - 20.0);
            if s.moved {
                move_margin = Some(s.value);
            }
            if s.done {
                set_margin = Some(s.value);
            }
        });
        if let Some(v) = move_margin {
            self.margin = Some(v);
        }
        if let Some(v) = set_margin {
            self.margin = None;
            actions.push(Action::Set("margin", (v as i64).to_string()));
        }
        Self::row(ui, "Ники", Some("Прятать — ники в репликах закрываются плашкой. Любой ник можно открыть или закрыть в «Строках»"), SUB, |ui| {
            if let Some(v) = widgets::choice(ui, Id::unique("set-nicks"), theme::NICKS, if cfg.hide_names { "yes" } else { "no" }, w) {
                actions.push(Action::Set("hide_names", v));
            }
        });
        Self::row(ui, "Строки в СС", Some("Какие строки сразу попадут в новую СС. Остальные останутся, их можно вернуть в «Строках»"), SUB, |ui| {
            for chunk in Kind::ALL.chunks(3) {
                let (line, _) = ui.allocate_exact_size(vec2(w, 32.0), Sense::hover());
                let mut x = line.left();
                for kind in chunk {
                    let label = theme::kind_name(*kind);
                    let on = cfg.keep.contains(kind);
                    let size = widgets::pill_size(ui, label, if on { Pill::On } else { Pill::Chip }, 10.0, 32.0, 13.0);
                    let r = Rect::from_min_size(Pos2::new(x, line.top()), size);
                    if widgets::pill_at(ui, r, Id::unique(("kind", kind.label())), label, if on { Pill::On } else { Pill::Chip }, 10.0).clicked() {
                        let keep: Vec<&str> = Kind::ALL.iter().filter(|k| if *k == kind { !on } else { cfg.keep.contains(k) }).map(|k| k.label()).collect();
                        actions.push(Action::Set("keep", keep.join(", ")));
                    }
                    x += size.x + 6.0;
                }
                ui.add_space(6.0);
            }
        });
        });
        let summary = cfg.out.display().to_string();
        let mut fold = Self::fold(ui, "files", "Файлы", &summary, false);
        fold.show_body_unindented(ui, |ui| {
        let (size, count) = store::src_size(&cfg.out);
        Self::row(ui, "Папка", Some("Куда сохраняются готовые СС"), SUB, |ui| {
            ui.add(egui::Label::new(egui::RichText::new(cfg.out.display().to_string()).font(theme::ui(9.0)).color(SUB)).wrap());
            match widgets::buttons(ui, Id::unique("set-folder"), &["Изменить", "Открыть"], 8.0) {
                Some(0) => {
                    if let Some(p) = rfd::FileDialog::new().set_title("Куда сохранять СС").set_directory(&cfg.out).pick_folder() {
                        actions.push(Action::Folder(p));
                    }
                }
                Some(1) => actions.push(Action::OpenFolder),
                _ => {}
            }
        });
        Self::row(ui, "Исходники", Some("Кадры, из которых собрана СС: фон и снимки чата. Нужны, чтобы править СС. Если удалить, готовые СС останутся, но править их будет нельзя"), SUB, |ui| {
            ui.label(egui::RichText::new(if size > 0 { format!("{count} СС · {}", theme::megabytes(size)) } else { "Пусто".into() })
                .font(theme::ui(9.0)).color(SUB));
            if widgets::buttons(ui, Id::unique("set-clear"), &["Очистить"], 8.0).is_some() && size > 0 {
                let question = format!("Удалить исходники {count} СС ({})?\n\nГотовые СС останутся в папке, но поправить их в редакторе будет нельзя.", theme::megabytes(size));
                let yes = rfd::MessageDialog::new().set_title("Snapline").set_description(question).set_buttons(rfd::MessageButtons::YesNo).show();
                if yes == rfd::MessageDialogResult::Yes {
                    store::clear_src(&cfg.out);
                    actions.push(Action::Cleared);
                }
            }
        });
        });
        let summary = if cfg.chatlog { "Запись включена".to_string() } else { "Запись выключена".to_string() };
        let mut fold = Self::fold(ui, "chatlog", "Чатлог", &summary, false);
        fold.show_body_unindented(ui, |ui| {
        let state = self.chatlog_state.clone();
        Self::row(ui, "Запись чата", Some("Пока включено, программа записывает каждую строку чата с временем. Нужно для «Из чатлога»"), SUB, |ui| {
            if let Some(v) = widgets::choice(ui, Id::unique("set-chatlog"), theme::SOUND, if cfg.chatlog { "yes" } else { "no" }, w) {
                if v == "no" && cfg.source == "log" {
                    actions.push(Action::Set("source", "screen".into()));
                }
                actions.push(Action::Set("chatlog", v));
            }
            ui.add_space(4.0);
            ui.add(egui::Label::new(egui::RichText::new(state.0.clone()).font(theme::ui(9.0)).color(state.1)).wrap());
            if widgets::buttons(ui, Id::unique("set-chatlog-open"), &["Открыть"], 8.0).is_some() {
                let folder = cfg.out.join("chatlog");
                let _ = std::fs::create_dir_all(&folder);
                crate::win::open(&folder.to_string_lossy());
            }
        });
        });
        let summary = "Тур по редактору".to_string();
        let mut fold = Self::fold(ui, "help", "Помощь", &summary, false);
        fold.show_body_unindented(ui, |ui| {
        Self::row(ui, "Обучение", Some("Короткий тур по редактору на твоей последней СС, семь шагов"), SUB, |ui| {
            if widgets::buttons(ui, Id::unique("set-tour"), &["Показать"], 0.0).is_some() {
                actions.push(Action::Tour);
            }
        });
        });
        ui.add_space(24.0);
    }

    fn credits(&mut self, ui: &mut Ui, right: Rect, update: Option<&(String, String)>) {
        let top = right.bottom() - 60.0;
        ui.painter().line_segment([Pos2::new(right.left(), top), Pos2::new(right.right(), top)], Stroke::new(1.0, HAIR));
        let p = ui.painter().clone();
        let v = p.text(Pos2::new(right.left(), top + 14.0), Align2::LEFT_TOP, format!("Snapline {}", engine::config::VERSION), theme::semi(11.0), WHITE);
        let mut x = right.left();
        let y = v.bottom() + 2.0;
        for (text, link) in [("Дохлый", Some(theme::DISCORD)), (" для ", None), ("ls-project.com", Some(theme::SITE))] {
            let r = p.text(Pos2::new(x, y), Align2::LEFT_TOP, text, theme::ui(9.0), if link.is_some() { WHITE } else { SUB });
            if let Some(url) = link {
                let resp = ui.interact(r, Id::unique(("credit", text)), Sense::click());
                if resp.hovered() {
                    p.line_segment([Pos2::new(r.left(), r.bottom()), Pos2::new(r.right(), r.bottom())], Stroke::new(1.0, WHITE));
                    ui.ctx().set_cursor_icon(egui::CursorIcon::PointingHand);
                }
                if resp.clicked() {
                    crate::win::open(url);
                }
            }
            x = r.right();
        }
        if let Some((version, url)) = update {
            let r = p.text(Pos2::new(right.left(), y + 18.0), Align2::LEFT_TOP, format!("Вышла версия {version} — скачать"), theme::semi(9.0), WHITE);
            if ui.interact(r, Id::unique("credit-update"), Sense::click()).clicked() {
                crate::win::open(url);
            }
        }
        if self.logo.is_none() {
            if let Ok(img) = image::load_from_memory(LOGO) {
                let img = img.to_rgba8();
                let h = 44u32;
                let w = (img.width() as f32 * h as f32 / img.height() as f32).round() as u32;
                let small = engine::img::resize_rgba(&img, w, h, engine::img::Filter::Lanczos);
                let color = egui::ColorImage::from_rgba_unmultiplied([w as usize, h as usize], small.as_raw());
                self.logo = Some(self.ctx.load_texture("logo", color, egui::TextureOptions::LINEAR));
            }
        }
        if let Some(t) = &self.logo {
            let size = t.size_vec2();
            ui.painter().image(t.id(), Rect::from_min_size(Pos2::new(right.right() - size.x, top + 14.0), size), full_uv(), Color32::WHITE);
        }
    }

    fn example(&mut self, ui: &mut Ui, area: Rect, cfg: &Config, cached: Option<&Shot>) {
        if self.sample.is_none() && !self.load_sample(cfg, cached) {
            let text = if self.sample_missing { "Пример не загрузился: нет ни своих СС, ни встроенного кадра." } else { "Загружаю пример…" };
            ui.painter().text(area.left_top(), Align2::LEFT_TOP, text, theme::ui(10.0), SUB);
            return;
        }
        let shot = self.sample.as_mut().unwrap();
        for r in shot.rows.iter_mut() {
            r.keep = cfg.keep.contains(&r.kind);
            r.hide = Some(vec![]);
        }
        if cfg.hide_names {
            compose::auto_hide(&mut shot.rows, false);
        }
        let mut edit = Edit::new(cfg, &shot.rows).with_style(cfg);
        if let Some(l) = &self.look {
            edit.look = Some(l.clone());
        }
        if let Some(m) = self.margin {
            edit.margin = m as i64;
        }
        shot.edit = edit.clone();
        let p = compose::plan(shot.bg.dimensions(), &edit, None);
        let (ow, oh) = (p.size.0 as f32, p.size.1 as f32);
        let d = (area.width() / ow).min((area.height() - 72.0) / oh);
        let rect = Rect::from_min_size(area.left_top(), vec2((ow * d).round(), (oh * d).round()));
        let shot = shot.clone();
        let geo = self.painter.draw(ui, &shot, rect, &edit, (0, 0), None);
        let quality = self.quality.unwrap_or(cfg.quality as f64) as i64;
        let key = format!("{}:{quality}", edit.to_json());
        if key != self.estimate_key && self.estimate_due.is_none() {
            self.estimate_key = key;
            self.estimate_due = Some(Instant::now() + Duration::from_millis(150));
        }
        if self.estimate_due.is_some_and(|t| Instant::now() >= t) {
            self.estimate_due = None;
            self.estimate_rev += 1;
            let rev = self.estimate_rev;
            let mut snap = shot.clone();
            snap.edit.quality = quality;
            let (tx, ctx) = (self.tx.clone(), self.ctx.clone());
            std::thread::spawn(move || {
                let result = store::encoded(&snap, None).ok().map(|(img, _, data)| {
                    let shown = if snap.edit.file == "jpg" { image::load_from_memory(&data).map(|i| i.to_rgb8()).unwrap_or(img) } else { img };
                    (shown, data.len())
                });
                let _ = tx.send(Msg::Estimated(rev, result));
                ctx.request_repaint();
            });
        }
        if self.estimate_due.is_some() {
            ui.ctx().request_repaint_after(Duration::from_millis(60));
        }
        let mut weight = String::new();
        if let Some((img, t, size)) = &self.encoded {
            ui.painter().image(t.id(), geo.img, full_uv(), Color32::WHITE);
            weight = format!(", ≈ {}", theme::megabytes(*size as u64));
            if let Some(pos) = ui.input(|i| i.pointer.hover_pos()).filter(|p| geo.img.contains(*p)) {
                let (iw, ih) = (img.width() as f32, img.height() as f32);
                let (cx, cy) = ((pos.x - geo.img.left()) * iw / geo.img.width(), (pos.y - geo.img.top()) * ih / geo.img.height());
                let side = 240.0f32.min(iw).min(ih);
                let x0 = (cx - side / 2.0).clamp(0.0, iw - side);
                let y0 = (cy - side / 2.0).clamp(0.0, ih - side);
                let uv = Rect::from_min_max(Pos2::new(x0 / iw, y0 / ih), Pos2::new((x0 + side) / iw, (y0 + side) / ih));
                let lx = if pos.x + 28.0 + side < area.right() { pos.x + 28.0 } else { pos.x - 28.0 - side };
                let ly = (pos.y - side / 2.0).clamp(area.top() + 4.0, area.bottom() - side - 4.0);
                let r = Rect::from_min_size(Pos2::new(lx, ly), vec2(side, side));
                let lp = ui.ctx().layer_painter(egui::LayerId::new(egui::Order::Foreground, Id::unique("loupe")));
                lp.rect_filled(r.expand(2.0), CornerRadius::ZERO, VOID);
                lp.rect_stroke(r.expand(2.0), CornerRadius::ZERO, Stroke::new(1.0, WHITE), egui::StrokeKind::Inside);
                lp.image(t.id(), r, uv, Color32::WHITE);
                let tag = Rect::from_min_size(r.min, vec2(34.0, 20.0));
                lp.rect_filled(tag, CornerRadius::ZERO, VOID);
                lp.text(tag.center(), Align2::CENTER_CENTER, "1:1", theme::semi(9.0), WHITE);
            }
        }
        let source = match &shot.name {
            Some(n) => format!("твоя СС от {}", theme::when(n)),
            None => "встроенный кадр".into(),
        };
        let caption = format!("Так будет выглядеть новая СС: {} × {}{weight}. Пример — {source}. Каждую готовую СС можно поправить в редакторе.", p.size.0, p.size.1);
        let g = ui.painter().layout(caption, theme::ui(10.0), SUB, geo.img.width().max(200.0));
        ui.painter().galley(Pos2::new(geo.img.left(), geo.img.bottom() + 14.0), g, SUB);
        let _ = LINE;
    }
}

fn capture_summary(cfg: &Config) -> String {
    format!("{} · {} · чат {}", cfg.key, theme::label_of(theme::MODES, if cfg.auto { "yes" } else { "no" }).to_lowercase(),
            theme::label_of(theme::SOURCES, &cfg.source).to_lowercase())
}

fn frame_summary(cfg: &Config) -> String {
    let frame = match engine::config::exact_of(&cfg.format) {
        Some((w, h)) => format!("{w} × {h}"),
        None => format!("{}, {}", theme::label_of(theme::FORMATS, &cfg.format), theme::label_of(theme::SIZES, &cfg.size).to_lowercase()),
    };
    let file = if cfg.file == "jpg" { format!("JPG {}", cfg.quality) } else { "PNG".into() };
    format!("{frame} · {file}")
}

fn chat_summary(cfg: &Config) -> String {
    format!("текст ×{} · обводка {} · {}", cfg.text_scale, cfg.outline, theme::label_of(theme::POSITIONS, &cfg.chat_pos).to_lowercase())
}

fn style_summary(cfg: &Config) -> String {
    let mut parts: Vec<String> = vec![];
    if cfg.preset != "none" {
        parts.push(theme::label_of(theme::PRESET_NAMES, &cfg.preset).to_string());
    }
    if !cfg.look.is_empty() {
        parts.push("коррекция".into());
    }
    if !cfg.lut.is_empty() {
        parts.push(cfg.lut.clone());
    }
    if cfg.style != "none" {
        parts.push(theme::label_of(theme::STYLES, &cfg.style).to_string());
    }
    if parts.is_empty() { "Без обработки".into() } else { parts.join(" · ") }
}
