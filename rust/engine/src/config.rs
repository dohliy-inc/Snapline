use std::collections::VecDeque;
use std::path::{Path, PathBuf};
use std::sync::Mutex;

use regex::Regex;

use crate::chat::Kind;

pub const VERSION: &str = "2.0";

#[derive(Clone, Debug, PartialEq)]
pub enum Event {
    Log { stamp: String, msg: String, level: String },
    Shot(String),
    Busy(bool),
    Chatlog(String),
}

static EVENTS: Mutex<VecDeque<Event>> = Mutex::new(VecDeque::new());

pub fn emit(event: Event) {
    EVENTS.lock().unwrap().push_back(event);
}

pub fn drain_events() -> Vec<Event> {
    EVENTS.lock().unwrap().drain(..).collect()
}

pub fn log(msg: &str, level: &str) {
    let stamp = chrono::Local::now().format("%H:%M:%S").to_string();
    println!("[{stamp}] {msg}");
    emit(Event::Log { stamp, msg: msg.to_string(), level: level.to_string() });
}
pub const RELEASES: &str = "https://github.com/dohliy-inc/Snapline/releases/latest";

pub const DEFAULTS: [(&str, &str); 29] = [
    ("hotkey", "F11"),
    ("auto", "yes"),
    ("hud_key", "F7"),
    ("dark_key", "F2"),
    ("hud_delay_ms", "300"),
    ("output", "~/Pictures/Snapline"),
    ("format", "square"),
    ("size", "native"),
    ("file", "jpg"),
    ("quality", "92"),
    ("chat_pos", "top-left"),
    ("margin", "24"),
    ("text_scale", "1.5"),
    ("outline", "2"),
    ("keep", "речь, действие"),
    ("sound", "yes"),
    ("hide_names", "no"),
    ("chatlog", "no"),
    ("source", "screen"),
    ("tray", "yes"),
    ("tray_hint", "yes"),
    ("tour", "yes"),
    ("notify", "yes"),
    ("autocopy", "no"),
    ("seen", ""),
    ("preset", "none"),
    ("look", ""),
    ("lut", ""),
    ("style", "none"),
];

pub const SIZES: [(&str, Option<u32>); 5] =
    [("native", None), ("hd", Some(720)), ("fhd", Some(1080)), ("qhd", Some(1440)), ("4k", Some(2160))];
pub const SIDE_RANGE: (u32, u32) = (360, 4320);
pub const FRAME_RANGE: (u32, u32) = (200, 7680);
pub const FILE_TYPES: [&str; 2] = ["jpg", "png"];
pub const CHAT_POSITIONS: [&str; 4] = ["top-left", "top-right", "bottom-left", "bottom-right"];
pub const SOURCES: [&str; 2] = ["screen", "log"];

pub fn keys() -> Vec<(String, u32)> {
    let mut out: Vec<(String, u32)> = (1..=24).map(|i| (format!("F{i}"), 0x6F + i)).collect();
    for (name, vk) in [("PAUSE", 0x13), ("SCROLLLOCK", 0x91), ("INSERT", 0x2D), ("HOME", 0x24), ("END", 0x23),
                       ("PAGEUP", 0x21), ("PAGEDOWN", 0x22)] {
        out.push((name.to_string(), vk));
    }
    out
}

#[derive(Clone, Debug, PartialEq)]
pub struct Raw(pub Vec<(String, String)>);

impl Default for Raw {
    fn default() -> Self {
        Raw(DEFAULTS.iter().map(|(k, v)| (k.to_string(), v.to_string())).collect())
    }
}

impl Raw {
    pub fn get(&self, key: &str) -> &str {
        self.0.iter().find(|(k, _)| k == key).map(|(_, v)| v.as_str()).unwrap_or("")
    }

    pub fn set(&mut self, key: &str, value: impl Into<String>) {
        if let Some(slot) = self.0.iter_mut().find(|(k, _)| k == key) {
            slot.1 = value.into();
        }
    }

    pub fn parse_ini(text: &str) -> Raw {
        let mut raw = Raw::default();
        let text = text.trim_start_matches('\u{feff}');
        let mut sections: Vec<(String, Vec<(String, String)>)> = Vec::new();
        let mut last_key: Option<String> = None;
        for line in text.lines() {
            let trimmed = line.trim();
            if trimmed.is_empty() || trimmed.starts_with('#') || trimmed.starts_with(';') {
                continue;
            }
            if trimmed.starts_with('[') && trimmed.ends_with(']') {
                sections.push((trimmed[1..trimmed.len() - 1].trim().to_string(), Vec::new()));
                last_key = None;
                continue;
            }
            let Some((_, items)) = sections.last_mut() else { continue };
            if line.starts_with([' ', '\t']) {
                if let Some(k) = &last_key {
                    if let Some(slot) = items.iter_mut().find(|(key, _)| key == k) {
                        slot.1 = format!("{}\n{}", slot.1, strip_inline(trimmed));
                    }
                }
                continue;
            }
            let at = match (line.find('='), line.find(':')) {
                (Some(a), Some(b)) => a.min(b),
                (Some(a), None) | (None, Some(a)) => a,
                _ => continue,
            };
            let key = line[..at].trim().to_lowercase();
            let value = strip_inline(line[at + 1..].trim()).to_string();
            items.retain(|(k, _)| *k != key);
            items.push((key.clone(), value));
            last_key = Some(key);
        }
        for name in ["snapline", "lspscreen"] {
            if let Some((_, items)) = sections.iter().find(|(s, _)| s == name) {
                for (k, v) in items {
                    raw.set(k, v.clone());
                }
                break;
            }
        }
        raw
    }

    pub fn to_ini(&self) -> String {
        let mut out = String::from("[snapline]\n");
        for (k, v) in &self.0 {
            out.push_str(&format!("{k} = {v}\n"));
        }
        out.push('\n');
        out
    }
}

fn strip_inline(value: &str) -> &str {
    let bytes = value.as_bytes();
    for (i, &c) in bytes.iter().enumerate() {
        if c == b';' && i > 0 && bytes[i - 1].is_ascii_whitespace() {
            return value[..i].trim_end();
        }
    }
    value
}

#[derive(Clone, Debug, PartialEq)]
pub struct Config {
    pub key: String,
    pub vk: u32,
    pub auto: bool,
    pub hud_key: String,
    pub dark_key: String,
    pub hud_delay: f64,
    pub out: PathBuf,
    pub format: String,
    pub ratio: Option<f64>,
    pub size: String,
    pub file: String,
    pub quality: i64,
    pub chat_pos: String,
    pub margin: i64,
    pub text_scale: f64,
    pub outline: i64,
    pub keep: Vec<Kind>,
    pub sound: bool,
    pub hide_names: bool,
    pub chatlog: bool,
    pub source: String,
    pub tray: bool,
    pub tray_hint: bool,
    pub tour: bool,
    pub notify: bool,
    pub autocopy: bool,
    pub seen: String,
    pub preset: String,
    pub look: std::collections::BTreeMap<String, f64>,
    pub lut: String,
    pub style: String,
}

fn key_of(raw: &Raw, name: &str) -> Result<(String, u32), String> {
    let key = raw.get(name).trim().to_uppercase();
    let all = keys();
    match all.iter().find(|(k, _)| *k == key) {
        Some((k, vk)) => Ok((k.clone(), *vk)),
        None => Err(format!("{name} = {key}: такой клавиши нет, можно {}",
                            all.iter().map(|(k, _)| k.as_str()).collect::<Vec<_>>().join(", "))),
    }
}

fn one_of(raw: &Raw, name: &str, options: &[&str]) -> Result<String, String> {
    let value = raw.get(name).trim().to_lowercase();
    let value = if value.is_empty() { "none".to_string() } else { value };
    if options.contains(&value.as_str()) { Ok(value) } else { Err(format!("{name} = {value}: можно {}", options.join(", "))) }
}

pub fn look_of(raw: &Raw) -> Result<std::collections::BTreeMap<String, f64>, String> {
    let mut look = std::collections::BTreeMap::new();
    for part in raw.get("look").split(',').map(str::trim).filter(|p| !p.is_empty()) {
        let bad = || format!("look = {}: нужно, например, bright:10, contrast:-5", raw.get("look"));
        let (key, value) = part.split_once(':').ok_or_else(bad)?;
        let key = key.trim().to_lowercase();
        let value: f64 = value.trim().parse().map_err(|_| bad())?;
        if !crate::styles::LOOK.contains(&key.as_str()) || !(-100.0..=100.0).contains(&value) {
            return Err(bad());
        }
        if value != 0.0 {
            look.insert(key, value);
        }
    }
    Ok(look)
}

pub fn look_text(look: &std::collections::BTreeMap<String, f64>) -> String {
    look.iter().filter(|(_, v)| **v != 0.0).map(|(k, v)| format!("{k}:{v}")).collect::<Vec<_>>().join(", ")
}

fn bool_of(raw: &Raw, name: &str) -> Result<bool, String> {
    match raw.get(name).trim().to_lowercase().as_str() {
        "1" | "yes" | "true" | "on" => Ok(true),
        "0" | "no" | "false" | "off" => Ok(false),
        _ => Err(format!("{name} = {}: нужно yes или no", raw.get(name))),
    }
}

fn int_of(raw: &Raw, name: &str, lo: i64, hi: i64) -> Result<i64, String> {
    let value: i64 = raw.get(name).trim().parse().map_err(|_| format!("{name} = {}: нужно число", raw.get(name)))?;
    if !(lo <= value && value <= hi) {
        return Err(format!("{name} = {value}: нужно от {lo} до {hi}"));
    }
    Ok(value)
}

fn float_of(raw: &Raw, name: &str, lo: f64, hi: f64) -> Result<f64, String> {
    let value: f64 = raw.get(name).trim().parse().map_err(|_| format!("{name} = {}: нужно число", raw.get(name)))?;
    if !(lo <= value && value <= hi) {
        return Err(format!("{name} = {}: нужно от {lo} до {hi}", py_num(value)));
    }
    Ok(value)
}

fn py_num(v: f64) -> String {
    if v.fract() == 0.0 && v.is_finite() { format!("{v:.1}") } else { format!("{v}") }
}

pub fn exact_of(fmt: &str) -> Option<(u32, u32)> {
    let re = Regex::new(r"^(\d+)\s*[x×]\s*(\d+)$").unwrap();
    let low = fmt.trim().to_lowercase();
    let m = re.captures(&low)?;
    Some((m[1].parse().ok()?, m[2].parse().ok()?))
}

pub fn ratio_of(fmt: &str) -> Result<Option<f64>, String> {
    let fmt = fmt.trim().to_lowercase();
    if fmt == "full" {
        return Ok(None);
    }
    if fmt == "square" {
        return Ok(Some(1.0));
    }
    if let Some((w, h)) = exact_of(&fmt) {
        let (lo, hi) = FRAME_RANGE;
        if ![w, h].iter().all(|v| lo <= *v && *v <= hi) {
            return Err(format!("format = {fmt}: ширина и высота от {lo} до {hi} px"));
        }
        return Ok(Some(w as f64 / h as f64));
    }
    let re = Regex::new(r"^(\d+(?:\.\d+)?)\s*:\s*(\d+(?:\.\d+)?)$").unwrap();
    let bad = || format!("format = {fmt}: нужно square, full, соотношение вроде 4:3 или размер вроде 1200x800");
    let m = re.captures(&fmt).ok_or_else(bad)?;
    let (a, b): (f64, f64) = (m[1].parse().unwrap_or(0.0), m[2].parse().unwrap_or(0.0));
    if a <= 0.0 || b <= 0.0 {
        return Err(bad());
    }
    Ok(Some(a / b))
}

pub fn side_of(size: &str) -> Option<u32> {
    match SIZES.iter().find(|(k, _)| *k == size) {
        Some((_, side)) => *side,
        None => size.parse().ok(),
    }
}

pub fn parse_size(value: &str) -> Result<String, String> {
    let size = value.trim().to_lowercase();
    let (lo, hi) = SIDE_RANGE;
    if SIZES.iter().any(|(k, _)| *k == size) {
        return Ok(size);
    }
    if !size.is_empty() && size.chars().all(|c| c.is_ascii_digit()) {
        if let Ok(n) = size.parse::<u32>() {
            if lo <= n && n <= hi {
                return Ok(n.to_string());
            }
        }
    }
    Err(format!("size = {size}: можно {} или число от {lo} до {hi}",
                SIZES.iter().map(|(k, _)| *k).collect::<Vec<_>>().join(", ")))
}

pub fn expand_home(path: &str) -> PathBuf {
    let home = std::env::var_os("USERPROFILE").or_else(|| std::env::var_os("HOME")).map(PathBuf::from);
    match (path.strip_prefix('~'), home) {
        (Some(rest), Some(home)) if rest.is_empty() || rest.starts_with(['/', '\\']) => {
            home.join(rest.trim_start_matches(['/', '\\']))
        }
        _ => PathBuf::from(path),
    }
}

pub fn parse_config(raw: &Raw) -> Result<Config, String> {
    let (key, vk) = key_of(raw, "hotkey")?;
    let (hud, _) = key_of(raw, "hud_key")?;
    let (dark, _) = key_of(raw, "dark_key")?;
    if key == hud || key == dark {
        return Err(format!("hotkey = {key} совпадает с клавишей игры, которую программа жмёт сама"));
    }
    let mut format = raw.get("format").trim().to_lowercase();
    let ratio = ratio_of(&format)?;
    if let Some((w, h)) = exact_of(&format) {
        format = format!("{w}x{h}");
    }
    let size = parse_size(raw.get("size"))?;
    let file = raw.get("file").trim().to_lowercase();
    if !FILE_TYPES.contains(&file.as_str()) {
        return Err(format!("file = {file}: можно {}", FILE_TYPES.join(", ")));
    }
    let pos = raw.get("chat_pos").trim().to_lowercase();
    if !CHAT_POSITIONS.contains(&pos.as_str()) {
        return Err(format!("chat_pos = {pos}: можно {}", CHAT_POSITIONS.join(", ")));
    }
    let source = raw.get("source").trim().to_lowercase();
    if !SOURCES.contains(&source.as_str()) {
        return Err(format!("source = {source}: можно {}", SOURCES.join(", ")));
    }
    let wanted: Vec<String> =
        raw.get("keep").split(',').map(|k| k.trim().to_lowercase()).filter(|k| !k.is_empty()).collect();
    let bad: Vec<&str> =
        wanted.iter().filter(|k| Kind::from_label(k).is_none()).map(|k| k.as_str()).collect();
    if !bad.is_empty() {
        return Err(format!("keep = {}: таких строк нет, можно {}", bad.join(", "),
                           Kind::ALL.iter().map(|k| k.label()).collect::<Vec<_>>().join(", ")));
    }
    Ok(Config {
        key,
        vk,
        auto: bool_of(raw, "auto")?,
        hud_key: hud,
        dark_key: dark,
        hud_delay: int_of(raw, "hud_delay_ms", 0, 3000)? as f64 / 1000.0,
        out: expand_home(raw.get("output").trim()),
        format,
        ratio,
        size,
        file,
        quality: int_of(raw, "quality", 10, 100)?,
        chat_pos: pos,
        margin: int_of(raw, "margin", 0, 400)?,
        text_scale: float_of(raw, "text_scale", 0.5, 3.0)?,
        outline: int_of(raw, "outline", 0, 10)?,
        keep: wanted.iter().filter_map(|k| Kind::from_label(k)).collect(),
        sound: bool_of(raw, "sound")?,
        hide_names: bool_of(raw, "hide_names")?,
        chatlog: bool_of(raw, "chatlog")?,
        source,
        tray: bool_of(raw, "tray")?,
        tray_hint: bool_of(raw, "tray_hint")?,
        tour: bool_of(raw, "tour")?,
        notify: bool_of(raw, "notify")?,
        autocopy: bool_of(raw, "autocopy")?,
        seen: raw.get("seen").trim().to_string(),
        preset: one_of(raw, "preset", &crate::styles::PRESETS)?,
        look: look_of(raw)?,
        lut: raw.get("lut").trim().to_string(),
        style: one_of(raw, "style", &crate::styles::STYLES)?,
    })
}

pub fn read_raw(path: &Path) -> Raw {
    match std::fs::read(path) {
        Ok(bytes) => Raw::parse_ini(&String::from_utf8_lossy(&bytes)),
        Err(_) => Raw::default(),
    }
}

pub fn write_raw(path: &Path, raw: &Raw) -> std::io::Result<()> {
    std::fs::write(path, raw.to_ini())
}

pub fn load_config(path: &Path) -> Result<(Raw, Config), String> {
    let raw = read_raw(path);
    let cfg = parse_config(&raw)?;
    if !path.exists() {
        let _ = write_raw(path, &raw);
    }
    Ok((raw, cfg))
}
