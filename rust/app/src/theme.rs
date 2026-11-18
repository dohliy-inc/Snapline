use std::path::PathBuf;
use std::sync::Arc;

use eframe::egui::{self, Color32, FontData, FontDefinitions, FontFamily, FontId};

pub const VOID: Color32 = Color32::from_rgb(0x0a, 0x0a, 0x0a);
pub const BLACK: Color32 = Color32::from_rgb(0, 0, 0);
pub const ROW: Color32 = Color32::from_rgb(0x15, 0x17, 0x1b);
pub const SLATE: Color32 = Color32::from_rgb(0x1e, 0x20, 0x26);
pub const MIST: Color32 = Color32::from_rgb(0x2a, 0x2f, 0x39);
pub const HAIR: Color32 = Color32::from_rgb(0x20, 0x23, 0x29);
pub const LINE: Color32 = Color32::from_rgb(0x45, 0x4b, 0x57);
pub const DIM: Color32 = Color32::from_rgb(0x6b, 0x71, 0x80);
pub const WHITE: Color32 = Color32::from_rgb(0xf4, 0xf4, 0xf5);
pub const SUB: Color32 = Color32::from_rgb(0xa3, 0xa8, 0xb3);
pub const ERR: Color32 = Color32::from_rgb(0xff, 0x7a, 0x70);
pub const CHIP_TEXT: Color32 = Color32::from_rgb(0xd7, 0xd9, 0xde);
pub const DANGER: Color32 = Color32::from_rgb(0xc4, 0x2b, 0x1c);

pub const SIDE_W: f32 = 400.0;
pub const RAIL_W: f32 = 112.0;
pub const PAD: f32 = 36.0;
pub const BAR_H: f32 = 64.0;
pub const UNDO_MAX: usize = 200;
pub const UNDO_MERGE_S: f64 = 0.8;

pub fn icon(key: &str) -> char {
    let code = match key {
        "blur" => 0xED1A,
        "style" => 0xE706,
        "file" => 0xE74E,
        "scene" => 0xE81E,
        "images" => 0xE91B,
        "cut" => 0xE8C6,
        "lines" => 0xE8FD,
        "crop" => 0xE7A8,
        "text" => 0xE8E9,
        "copy" => 0xE8C8,
        "folder" => 0xE8B7,
        "delete" => 0xE74D,
        "up" => 0xE70E,
        "down" => 0xE70D,
        "close" => 0xE711,
        "undo" => 0xE7A7,
        "redo" => 0xE7A6,
        "min" => 0xE921,
        "max" => 0xE922,
        "restore" => 0xE923,
        "chrome-close" => 0xE8BB,
        _ => 0x20,
    };
    char::from_u32(code).unwrap_or(' ')
}

pub const TOOLS: [&str; 8] = ["lines", "text", "crop", "images", "blur", "style", "scene", "file"];
pub const PREVIEWS: [&str; 3] = ["scene", "file", "style"];
pub const DONORS: [&str; 3] = ["carry", "photopick", "scenepick"];
pub const EDITS: [&str; 8] = ["lines", "carry", "logpick", "crop", "text", "images", "photopick", "blur"];
pub const FRAMED: [&str; 4] = ["crop", "text", "images", "blur"];
pub const HANDLES: [&str; 8] = ["l", "r", "t", "b", "lt", "rt", "lb", "rb"];

pub const FORMATS: &[(&str, &str)] = &[("square", "Квадрат"), ("full", "Экран"), ("16:9", "16:9"), ("4:3", "4:3"), ("4:5", "4:5")];
pub const SIZES: &[(&str, &str)] = &[("native", "Как снято"), ("hd", "720"), ("fhd", "1080"), ("qhd", "1440"), ("4k", "2160")];
pub const FILES: &[(&str, &str)] = &[("jpg", "JPG"), ("png", "PNG")];
pub const STYLES: &[(&str, &str)] = &[("none", "Нет"), ("cctv", "Камера наблюдения"), ("body", "Бодикам")];
pub const PRESET_NAMES: &[(&str, &str)] = &[("none", "Нет"), ("film", "Кино"), ("warm", "Тёплый"), ("cold", "Холодный"),
                                             ("faded", "Выцветший"), ("noir", "Нуар"), ("sepia", "Сепия")];
pub const BLUR_NAMES: &[(&str, &str)] = &[("blur", "Размытие"), ("pixel", "Пиксели")];
pub const LOOK_NAMES: &[(&str, &str)] = &[("bright", "Яркость"), ("contrast", "Контраст"), ("sat", "Насыщенность"),
                                           ("temp", "Температура"), ("shadows", "Тени"), ("highlights", "Света")];
pub const NICKS: &[(&str, &str)] = &[("no", "Показывать"), ("yes", "Прятать")];
pub const CROPS: &[(&str, &str)] = &[("free", "Свободно"), ("1:1", "Квадрат"), ("4:3", "4:3"), ("3:4", "3:4"), ("16:9", "16:9"), ("9:16", "9:16")];
pub const SIDES: &[(&str, &str)] = &[("none", "Нет"), ("left", "Слева"), ("right", "Справа"), ("top", "Сверху"), ("bottom", "Снизу")];
pub const SCALES: &[(&str, &str)] = &[("1", "×1"), ("1.25", "×1.25"), ("1.5", "×1.5"), ("1.75", "×1.75"), ("2", "×2")];
pub const OUTLINES: &[(&str, &str)] = &[("0", "Нет"), ("1", "1 px"), ("2", "2 px"), ("3", "3 px")];
pub const POSITIONS: &[(&str, &str)] = &[("top-left", "Сверху слева"), ("top-right", "Сверху справа"),
                                          ("bottom-left", "Снизу слева"), ("bottom-right", "Снизу справа")];
pub const MODES: &[(&str, &str)] = &[("yes", "Одна кнопка"), ("no", "Две кнопки")];
pub const SOURCES: &[(&str, &str)] = &[("screen", "С экрана"), ("log", "Из чатлога")];
pub const VIEWS: &[(&str, &str)] = &[("one", "Эту СС"), ("all", "Всю сцену")];
pub const LOG_SHOW: &[(&str, &str)] = &[("rp", "Отыгровка"), ("all", "Все строки")];
pub const SOUND: &[(&str, &str)] = &[("yes", "Вкл"), ("no", "Выкл")];
pub const LOG_NAMES: usize = 14;
pub const FIELD_DEFAULT: (f64, f64) = (0.5, 0.3);
pub const DISCORD: &str = "https://discord.com/users/320909791826280452";
pub const SITE: &str = "https://ls-project.com/";

pub fn rail_hint(key: &str) -> Option<&'static str> {
    Some(match key {
        "lines" => "Какие строки чата попадут в СС · клавиша 1",
        "text" => "Размер текста, обводка и где стоит чат · клавиша 2",
        "crop" => "Что попадёт в кадр и какого он размера · клавиша 3",
        "images" => "Второй ракурс или стикер поверх СС · клавиша 4",
        "blur" => "Размыть или запикселить часть кадра · клавиша 5",
        "style" => "Цвет, пресеты, LUT и стиль камеры · клавиша 6",
        "scene" => "Несколько СС одна под другой · клавиша 7",
        "file" => "JPG или PNG, качество и вес файла · клавиша 8",
        "copy" => "Скопировать СС в буфер (Ctrl+C), вставлять через Ctrl+V",
        "folder" => "Показать файл в папке",
        "delete" => "Убрать СС в корзину (Del). Передумал — «Вернуть» в плашке или Ctrl+Z",
        _ => return None,
    })
}

pub fn kind_name(kind: engine::chat::Kind) -> &'static str {
    use engine::chat::Kind;
    match kind {
        Kind::Speech => "Речь",
        Kind::Action => "Действия",
        Kind::Ame => "Над головой",
        Kind::System => "Система",
        Kind::Ooc => "OOC и ЛС",
    }
}

pub fn label_of<'a>(options: &'a [(&'a str, &'a str)], key: &str) -> &'a str {
    options.iter().find(|(k, _)| *k == key).map(|(_, v)| *v).unwrap_or("")
}

const MONTHS: [&str; 12] = ["января", "февраля", "марта", "апреля", "мая", "июня", "июля", "августа", "сентября", "октября",
                            "ноября", "декабря"];

pub fn when(name: &str) -> String {
    match chrono::NaiveDateTime::parse_from_str(name, "SS_%Y-%m-%d_%H-%M-%S") {
        Ok(t) => {
            use chrono::{Datelike, Timelike};
            format!("{} {}, {:02}:{:02}", t.day(), MONTHS[t.month0() as usize], t.hour(), t.minute())
        }
        Err(_) => name.to_string(),
    }
}

pub fn megabytes(size: u64) -> String {
    if size >= 1 << 20 { format!("{:.1} МБ", size as f64 / (1u64 << 20) as f64) } else { format!("{} КБ", size / 1024) }
}

pub fn same(a: &str, b: &str) -> bool {
    match (a.trim().parse::<f64>(), b.trim().parse::<f64>()) {
        (Ok(x), Ok(y)) => x == y,
        _ => a.trim().to_lowercase() == b.trim().to_lowercase(),
    }
}

pub fn pt(size: f32) -> f32 {
    size * 96.0 / 72.0
}

pub fn ui(size: f32) -> FontId {
    FontId::new(pt(size), FontFamily::Proportional)
}

pub fn semi(size: f32) -> FontId {
    FontId::new(pt(size), FontFamily::Name("semi".into()))
}

pub fn display(size: f32) -> FontId {
    FontId::new(pt(size), FontFamily::Name("semi".into()))
}

pub fn bold(size: f32) -> FontId {
    FontId::new(pt(size), FontFamily::Name("bold".into()))
}

pub fn wordmark(p: &egui::Painter, pos: egui::Pos2, align: egui::Align2, size: f32, color: Color32) {
    use egui::epaint::text::{LayoutJob, TextFormat, VariationCoords};
    let px = pt(size);
    let mut job = LayoutJob::default();
    job.append("Snapline", 0.0, TextFormat {
        font_id: FontId::new(px, FontFamily::Name("brand".into())),
        extra_letter_spacing: -0.025 * px,
        coords: VariationCoords::new([(b"wght", 700.0), (b"opsz", 36.0)]),
        color,
        ..Default::default()
    });
    let galley = p.layout_job(job);
    p.galley(align.anchor_size(pos, galley.size()).min, galley, color);
}

pub fn glyph(size: f32) -> FontId {
    FontId::new(pt(size), FontFamily::Name("icon".into()))
}

fn fonts_dir() -> PathBuf {
    PathBuf::from(std::env::var_os("WINDIR").unwrap_or_else(|| "C:\\Windows".into())).join("Fonts")
}

pub fn install_fonts(ctx: &egui::Context) {
    let mut defs = FontDefinitions::default();
    let mut load = |key: &str, files: &[&str]| -> bool {
        for f in files {
            if let Ok(bytes) = std::fs::read(fonts_dir().join(f)) {
                defs.font_data.insert(key.to_string(), Arc::new(FontData::from_owned(bytes)));
                return true;
            }
        }
        false
    };
    let regular = load("segoe", &["segoeui.ttf"]);
    let semibold = load("segoe-semi", &["seguisb.ttf", "segoeuib.ttf"]);
    let heavy = load("segoe-bold", &["segoeuib.ttf", "seguisb.ttf"]);
    let brand = load("segoe-var", &["SegUIVar.ttf", "segoeuib.ttf"]);
    let icons = load("icons", &["SegoeIcons.ttf", "segmdl2.ttf"]);
    let arial = load("arial-bold", &["arialbd.ttf"]);
    let fallback: Vec<String> = defs.families.get(&FontFamily::Proportional).cloned().unwrap_or_default();
    let mut family = |name: FontFamily, first: Option<&str>| {
        let mut list: Vec<String> = first.map(|f| vec![f.to_string()]).unwrap_or_default();
        list.extend(fallback.iter().cloned());
        defs.families.insert(name, list);
    };
    family(FontFamily::Proportional, regular.then_some("segoe"));
    family(FontFamily::Name("semi".into()), semibold.then_some("segoe-semi"));
    family(FontFamily::Name("bold".into()), heavy.then_some("segoe-bold"));
    family(FontFamily::Name("brand".into()), brand.then_some("segoe-var"));
    family(FontFamily::Name("icon".into()), icons.then_some("icons"));
    family(FontFamily::Name("chat".into()), arial.then_some("arial-bold"));
    ctx.set_fonts(defs);
}

pub fn style(ctx: &egui::Context) {
    ctx.set_theme(egui::ThemePreference::Dark);
    ctx.all_styles_mut(|s| {
        s.visuals = egui::Visuals::dark();
        s.visuals.panel_fill = VOID;
        s.visuals.window_fill = VOID;
        s.visuals.extreme_bg_color = ROW;
        s.visuals.override_text_color = Some(WHITE);
        s.visuals.selection.bg_fill = MIST;
        s.visuals.text_options.color_transfer_function = egui::epaint::FontColorTransferFunction::Off;
        s.visuals.text_cursor.stroke = egui::Stroke::new(1.5, WHITE);
        s.visuals.widgets.hovered.bg_stroke = egui::Stroke::new(1.0, WHITE);
        s.visuals.widgets.inactive.bg_stroke = egui::Stroke::new(1.0, LINE);
        s.spacing.item_spacing = egui::vec2(0.0, 0.0);
        s.spacing.scroll.bar_width = 4.0;
        s.spacing.scroll.floating = true;
        s.interaction.tooltip_delay = 0.4;
        s.animation_time = if animations_on() { 0.18 } else { 0.0 };
    });
}

pub fn animations_on() -> bool {
    use windows::Win32::UI::WindowsAndMessaging::{SPI_GETCLIENTAREAANIMATION, SYSTEM_PARAMETERS_INFO_UPDATE_FLAGS, SystemParametersInfoW};
    let mut on = windows::core::BOOL(1);
    unsafe {
        let _ = SystemParametersInfoW(SPI_GETCLIENTAREAANIMATION, 0, Some(&mut on as *mut _ as *mut _), SYSTEM_PARAMETERS_INFO_UPDATE_FLAGS(0));
    }
    on.as_bool()
}

pub fn ease(t: f32) -> f32 {
    1.0 - (1.0 - t.clamp(0.0, 1.0)).powi(3)
}

pub const S1: f32 = 4.0;
pub const S2: f32 = 8.0;
pub const S3: f32 = 12.0;
pub const S4: f32 = 16.0;
pub const S5: f32 = 24.0;
pub const S6: f32 = 32.0;
