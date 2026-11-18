use std::path::Path;
use std::sync::LazyLock;

use chrono::{Duration, NaiveDate, NaiveDateTime, NaiveTime};
use image::RgbImage;
use regex::Regex;
use serde_json::Value;

use crate::chat::Kind;
use crate::edit::LogLine;
use crate::py;
use crate::text::Face;

pub const PORT: u16 = 13172;
pub const RESOURCE: &str = "lspr";
pub const RECENT: usize = 1000;
pub const MATCH: usize = 200;
pub const STATUS_MAX: u64 = 512 * 1024;
pub const TAIL_BYTES: u64 = 1024 * 1024;
pub const LOG_FONT: &str = "arialbd.ttf";
pub const LOG_SIZE: f64 = 18.0 / 1440.0;
pub const LOG_PITCH: f64 = 21.5 / 1440.0;
pub const LOG_LEFT: f64 = 27.0 / 1440.0;
pub const LOG_WIDTH: f64 = 0.25;
pub const LOG_SPAN_S: i64 = 60 * 60;
pub const LOG_GAP_S: i64 = 3 * 60;
pub const LOG_STAMP: &str = "%Y-%m-%d %H:%M:%S";
pub const LOG_TEXT: &str = "#e6e6e6";
pub const LOG_PINK: &str = "#c2a2da";
pub const LOG_NEAR_S: i64 = 10 * 60;

pub type Parts = Vec<(String, String)>;
pub type Line = (NaiveDateTime, Parts);

static SAY: LazyLock<Regex> = LazyLock::new(|| {
    Regex::new(r"^(?:\[!\] )?(?P<who>[^\s:(*>\[][^:()]{1,40}?) (?:говорит|кричит|шепчет)[^:(]*(?:\((?:к (?P<to>[^)]+)|[^)]*)\))?:").unwrap()
});
static WHISPERED: LazyLock<Regex> = LazyLock::new(|| Regex::new(r"^Вы сказали (.{1,40}?) шепотом:").unwrap());
static STAR_TAIL: LazyLock<Regex> = LazyLock::new(|| Regex::new(r"\*([^*()]{3,40})\)?\s*$").unwrap());
static HEX: LazyLock<Regex> = LazyLock::new(|| Regex::new(r"^#[0-9a-fA-F]{6}$").unwrap());
static NUMS: LazyLock<Regex> = LazyLock::new(|| Regex::new(r"\d+").unwrap());
static PLAIN: LazyLock<Regex> = LazyLock::new(|| Regex::new(r"^\[(\d\d:\d\d:\d\d)\] (.*)").unwrap());
static TOKENS: LazyLock<Regex> = LazyLock::new(|| Regex::new(r"\S+\s*|\s+").unwrap());

pub fn hex_color(text: &str) -> String {
    let nums: Vec<u32> = NUMS.find_iter(text).filter_map(|m| m.as_str().parse().ok()).collect();
    if text.starts_with('#') || nums.len() < 3 {
        return if HEX.is_match(text) { text.to_string() } else { LOG_TEXT.to_string() };
    }
    format!("#{:02x}{:02x}{:02x}", nums[0].min(255), nums[1].min(255), nums[2].min(255))
}

pub fn rgb_of(hex: &str) -> [u8; 3] {
    let v = u32::from_str_radix(hex.trim_start_matches('#'), 16).unwrap_or(0xe6e6e6);
    [(v >> 16) as u8, (v >> 8) as u8, v as u8]
}

pub fn guess_parts(text: &str) -> Parts {
    let color = if text.starts_with('*') { LOG_PINK } else if text.starts_with("((") { "#a0a0a0" } else { LOG_TEXT };
    vec![(text.to_string(), color.to_string())]
}

pub fn log_entry(line: &str, plain: bool) -> Option<(String, Parts)> {
    if plain {
        let m = PLAIN.captures(line)?;
        return if m[2].trim().is_empty() { None } else { Some((m[1].to_string(), guess_parts(&m[2]))) };
    }
    let item: Value = serde_json::from_str(line).ok()?;
    let time = item.get("time")?.as_str()?.to_string();
    let parts: Parts = item
        .get("parts")?
        .as_array()?
        .iter()
        .filter_map(|p| {
            let t = p.get(0).map(text_of)?;
            let c = p.get(1).map(text_of)?;
            if t.is_empty() { None } else { Some((t, hex_color(&c))) }
        })
        .collect();
    if parts.is_empty() { None } else { Some((time, parts)) }
}

fn text_of(v: &Value) -> String {
    match v {
        Value::String(s) => s.clone(),
        other => other.to_string(),
    }
}

pub fn read_log(out: &Path, at: NaiveDateTime, span: i64) -> Vec<Line> {
    let start = at - Duration::seconds(span);
    let end = at + Duration::seconds(span);
    let mut days = vec![start.date()];
    if end.date() != start.date() {
        days.push(end.date());
    }
    let mut lines = Vec::new();
    for day in days {
        let base = out.join("chatlog").join(day.format("%Y-%m-%d").to_string());
        let candidates = [base.with_extension("jsonl"), base.with_extension("txt")];
        let Some(path) = candidates.iter().find(|p| p.exists()) else { continue };
        let Ok(bytes) = std::fs::read(path) else { continue };
        let plain = path.extension().is_some_and(|e| e == "txt");
        for line in String::from_utf8_lossy(&bytes).lines() {
            let Some((time, parts)) = log_entry(line, plain) else { continue };
            let Ok(t) = NaiveTime::parse_from_str(&time, "%H:%M:%S") else { continue };
            let when = day.and_time(t);
            if start <= when && when <= end {
                lines.push((when, parts));
            }
        }
    }
    lines
}

pub fn log_who(parts: &Parts) -> (Kind, Option<String>, Option<String>) {
    let joined: String = parts.iter().map(|(t, _)| t.as_str()).collect();
    let text = joined.trim();
    if let Some(m) = SAY.captures(text) {
        let to = m.name("to").map(|t| t.as_str().trim().to_string()).filter(|t| !t.is_empty());
        return (Kind::Speech, Some(m["who"].trim().to_string()), to);
    }
    if let Some(m) = WHISPERED.captures(text) {
        return (Kind::Speech, Some(m[1].to_string()), Some(m[1].to_string()));
    }
    if text.starts_with("((") {
        return (Kind::Ooc, None, None);
    }
    let pink = parts.iter().any(|(_, c)| c.to_lowercase() == LOG_PINK);
    let words: Vec<&str> = text.trim_start_matches(['*', '>', ' ']).split_whitespace().collect();
    let two = || if words.is_empty() { None } else { Some(words[..words.len().min(2)].join(" ")) };
    if text.starts_with("* ") {
        return (Kind::Action, two(), None);
    }
    if text.starts_with('>') {
        return if pink { (Kind::Ame, two(), None) } else { (Kind::System, None, None) };
    }
    if pink {
        if let Some(m) = STAR_TAIL.captures(text) {
            return (Kind::Action, Some(m[1].trim().to_string()), None);
        }
    }
    (Kind::System, None, None)
}

pub fn log_chunks(lines: &[Line], gap: i64) -> Vec<usize> {
    (0..lines.len()).filter(|&k| k == 0 || (lines[k].0 - lines[k - 1].0).num_seconds() > gap).collect()
}

pub fn log_key(when: NaiveDateTime, parts: &Parts) -> (String, String) {
    (when.format(LOG_STAMP).to_string(), parts.iter().map(|(t, _)| t.as_str()).collect())
}

pub fn picked_log(log: Option<&Vec<LogLine>>) -> Vec<Line> {
    let Some(log) = log else { return vec![] };
    let mut out = Vec::new();
    for e in log {
        let Ok(when) = NaiveDateTime::parse_from_str(&e.at, LOG_STAMP) else { return vec![] };
        out.push((when, e.parts.iter().map(|(t, c)| (t.clone(), hex_color(c))).collect()));
    }
    out
}

pub type LogRow = (NaiveDateTime, Vec<(f32, String, String)>);

pub fn log_rows(lines: &[Line], measure: &dyn Fn(&str) -> f32, limit: f32) -> Vec<LogRow> {
    let mut rows = Vec::new();
    for (when, parts) in lines {
        let mut row: Vec<(f32, String, String)> = Vec::new();
        let mut x = 0f32;
        let mut words: Vec<(String, String)> = parts
            .iter()
            .flat_map(|(text, c)| TOKENS.find_iter(text).map(move |m| (m.as_str().to_string(), c.clone())))
            .collect();
        while words.first().is_some_and(|(w, _)| w.trim().is_empty()) {
            words.remove(0);
        }
        for (word, color) in words {
            let mut word = word;
            if x != 0.0 && x + measure(word.trim_end()) > limit {
                rows.push((*when, std::mem::take(&mut row)));
                x = 0.0;
                word = word.trim_start().to_string();
                if word.is_empty() {
                    continue;
                }
            }
            match row.last_mut() {
                Some(last) if last.2 == color => last.1.push_str(&word),
                _ => row.push((x, word.clone(), color)),
            }
            x += measure(&word);
        }
        if !row.is_empty() {
            rows.push((*when, row));
        }
    }
    rows
}

pub fn log_frame(lines: &[Line], size: (u32, u32)) -> RgbImage {
    let (w, h) = size;
    let face = Face::new(LOG_FONT, py::round(LOG_SIZE * h as f64).max(8));
    let pitch = LOG_PITCH * h as f64;
    let left = py::round(LOG_LEFT * h as f64);
    let Some(face) = face else { return RgbImage::new(w, h) };
    let rows = log_rows(lines, &|s| face.length(s), (LOG_WIDTH * w as f64) as f32);
    let top = py::round(pitch);
    let ascent = face.ascent().ceil() as i64;
    let total = (h as i64).max(py::round(2.0 * top as f64 + pitch * rows.len() as f64)) as u32;
    let mut out = RgbImage::new(w, total);
    for (k, (_, row)) in rows.iter().enumerate() {
        let base = top + py::round(k as f64 * pitch) + ascent;
        for (x, text, color) in row {
            face.draw(&mut out, text.trim_end(), (left as f32 + x, base as f32), "ls", rgb_of(color));
        }
    }
    out
}

pub fn fresh<T: PartialEq + Clone>(batch: &[T], known: &[T]) -> Vec<T> {
    let tail = &known[known.len().saturating_sub(MATCH)..];
    if !tail.is_empty() {
        for j in (0..batch.len()).rev() {
            let k = (j + 1).min(tail.len());
            if batch[j] == tail[tail.len() - 1] && batch[j + 1 - k..=j] == tail[tail.len() - k..] {
                return batch[j + 1..].to_vec();
            }
        }
    }
    batch.to_vec()
}

pub fn grown<T: PartialEq + Clone>(prev: &[T], cur: &[T]) -> Vec<T> {
    if cur.len() >= prev.len() && cur[..prev.len()] == *prev { cur[prev.len()..].to_vec() } else { fresh(cur, prev) }
}

pub fn day_of(when: NaiveDateTime) -> NaiveDate {
    when.date()
}
