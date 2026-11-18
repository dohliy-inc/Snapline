use std::collections::HashMap;
use std::path::{Path, PathBuf};
use std::sync::{Arc, LazyLock, Mutex};
use std::time::SystemTime;

use image::RgbImage;
use regex::Regex;
use serde_json::Value;

use crate::chat::{self, Mark, Row};
use crate::chatlog;
use crate::compose::{self, Layout, Member, SceneInput};
use crate::config::{self, Config, FILE_TYPES};
use crate::edit::{Edit, LogLine, Seam, SeamPart};

pub const TEXT_QUALITY: i64 = 92;
pub const SRC_BG: &str = ".jpg";
pub const SRC_CHAT: &str = ".webp";

pub static FILES: Mutex<()> = Mutex::new(());

#[derive(Clone)]
pub struct Shot {
    pub name: Option<String>,
    pub out: PathBuf,
    pub bg: Arc<RgbImage>,
    pub rows: Vec<Row>,
    pub edit: Edit,
    pub legacy: bool,
    pub cfg: Option<Config>,
    pub members: HashMap<String, Arc<Shot>>,
}

impl Shot {
    pub fn src(&self) -> PathBuf {
        self.out.join("src")
    }
}

pub fn chat_number(path: &Path) -> u32 {
    static RE: LazyLock<Regex> = LazyLock::new(|| Regex::new(r"_chat(\d+)$").unwrap());
    let stem = path.file_stem().map(|s| s.to_string_lossy().into_owned()).unwrap_or_default();
    RE.captures(&stem).and_then(|m| m[1].parse().ok()).unwrap_or(0)
}

pub fn log_path(out: &Path, name: &str) -> PathBuf {
    out.join("src").join(format!("{name}_log.png"))
}

fn glob(dir: &Path, test: impl Fn(&str) -> bool) -> Vec<PathBuf> {
    let Ok(entries) = std::fs::read_dir(dir) else { return vec![] };
    let mut out: Vec<PathBuf> = entries
        .filter_map(|e| e.ok())
        .map(|e| e.path())
        .filter(|p| p.file_name().map(|n| test(&n.to_string_lossy())).unwrap_or(false))
        .collect();
    out.sort();
    out
}

fn ext_of(p: &Path) -> String {
    p.extension().map(|e| format!(".{}", e.to_string_lossy())).unwrap_or_default()
}

fn stem_of(p: &Path) -> String {
    p.file_stem().map(|s| s.to_string_lossy().into_owned()).unwrap_or_default()
}

pub fn screen_chats(out: &Path, name: &str) -> Vec<PathBuf> {
    let prefix = format!("{name}_chat");
    let mut chats = glob(&out.join("src"), |n| n.starts_with(&prefix));
    chats.retain(|p| {
        let e = ext_of(p);
        (e == SRC_CHAT || e == ".png") && stem_of(p)[prefix.len()..].chars().all(|c| c.is_ascii_digit())
    });
    chats.sort_by_key(|p| chat_number(p));
    chats
}

pub fn shot_files(out: &Path, name: &str) -> (PathBuf, Vec<PathBuf>, PathBuf) {
    let src = out.join("src");
    let bgs = [src.join(format!("{name}_bg{SRC_BG}")), src.join(format!("{name}_bg.png"))];
    let log = log_path(out, name);
    let chats = if log.exists() { vec![log] } else { screen_chats(out, name) };
    let bg = bgs.iter().find(|p| p.exists()).cloned().unwrap_or_else(|| bgs[0].clone());
    (bg, chats, src.join(format!("{name}.json")))
}

pub fn shot_image(out: &Path, name: &str) -> PathBuf {
    let paths: Vec<PathBuf> = FILE_TYPES.iter().map(|e| out.join(format!("{name}.{e}"))).collect();
    paths.iter().find(|p| p.exists()).cloned().unwrap_or_else(|| paths[0].clone())
}

pub fn list_shots(out: &Path) -> Vec<String> {
    static TAKEN: LazyLock<Regex> = LazyLock::new(|| Regex::new(r"^SS_(\d{4}-\d\d-\d\d_\d\d-\d\d-\d\d)").unwrap());
    if !out.is_dir() {
        return vec![];
    }
    let mut shots: HashMap<String, PathBuf> = HashMap::new();
    for p in glob(out, |n| n.starts_with("SS_")) {
        let e = ext_of(&p).trim_start_matches('.').to_lowercase();
        if FILE_TYPES.contains(&e.as_str()) {
            shots.insert(stem_of(&p), p);
        }
    }
    let taken = |name: &str| -> String {
        match TAKEN.captures(name) {
            Some(m) => m[1].to_string(),
            None => shots
                .get(name)
                .and_then(|p| std::fs::metadata(p).ok()?.modified().ok())
                .map(|t| chrono::DateTime::<chrono::Local>::from(t).format("%Y-%m-%d_%H-%M-%S").to_string())
                .unwrap_or_default(),
        }
    };
    let mut names: Vec<String> = shots.keys().cloned().collect();
    names.sort_by_key(|n| std::cmp::Reverse((taken(n), n.clone())));
    names
}

pub fn src_size(out: &Path) -> (u64, usize) {
    let files = glob(&out.join("src"), |n| n.starts_with("SS_"));
    let files: Vec<&PathBuf> = files.iter().filter(|p| p.is_file()).collect();
    let bytes = files.iter().filter_map(|p| std::fs::metadata(p).ok()).map(|m| m.len()).sum();
    (bytes, files.iter().filter(|p| p.to_string_lossy().contains("_bg.")).count())
}

pub fn clear_src(out: &Path) {
    let _g = FILES.lock().unwrap();
    for p in glob(&out.join("src"), |n| n.starts_with("SS_")) {
        let _ = std::fs::remove_file(p);
    }
}

pub fn read_image(path: &Path) -> Result<RgbImage, String> {
    image::open(path).map(|i| i.to_rgb8()).map_err(|e| format!("{}: {e}", path.display()))
}

pub fn load_rows(out: &Path, name: &str, cfg: &Config) -> Result<(Vec<Row>, Edit, Option<Mark>, bool), String> {
    let (_, chat_paths, meta) = shot_files(out, name);
    let mut rows = Vec::new();
    let mut mark = None;
    for p in &chat_paths {
        let img = read_image(p)?;
        if mark.is_none() {
            mark = chat::watermark(&img);
        }
        rows = chat::merge(rows, chat::classify(chat::extract_rows(&img), &cfg.keep));
    }
    let mut edit = Edit::new(cfg, &rows);
    let legacy = !meta.exists();
    if !legacy {
        if let Some(saved) = std::fs::read(&meta).ok().and_then(|b| serde_json::from_slice::<Value>(&b).ok()) {
            edit = Edit::merged(edit, &saved);
        }
    }
    compose::apply_keep(&mut rows, &mut edit);
    Ok((rows, edit, mark, legacy))
}

pub fn load_shot(out: &Path, name: &str, cfg: &Config) -> Result<Option<Shot>, String> {
    let (bg_path, chat_paths, _) = shot_files(out, name);
    if !bg_path.exists() || chat_paths.is_empty() {
        return Ok(None);
    }
    let (rows, edit, mut mark, legacy) = load_rows(out, name, cfg)?;
    if mark.is_none() && chat_paths[0] == log_path(out, name) {
        mark = recent_mark(out);
    }
    let bg = chat::clean_bg(&read_image(&bg_path)?, mark.as_ref());
    Ok(Some(Shot { name: Some(name.to_string()), out: out.to_path_buf(), bg: Arc::new(bg), rows, edit, legacy, cfg: Some(cfg.clone()),
                   members: HashMap::new() }))
}

fn stamp(path: &Path) -> Option<SystemTime> {
    std::fs::metadata(path).ok()?.modified().ok()
}

pub fn recent_mark(out: &Path) -> Option<Mark> {
    static MARKS: LazyLock<Mutex<HashMap<PathBuf, Option<Mark>>>> = LazyLock::new(|| Mutex::new(HashMap::new()));
    let mut chats = glob(&out.join("src"), |n| n.starts_with("SS_") && n.contains("_chat"));
    chats.sort_by_key(|p| stamp(p));
    let start = chats.len().saturating_sub(6);
    for p in chats[start..].iter().rev() {
        let found = MARKS.lock().unwrap().get(p).cloned();
        let mark = match found {
            Some(m) => m,
            None => {
                let m = read_image(p).ok().and_then(|i| chat::watermark(&i));
                MARKS.lock().unwrap().insert(p.clone(), m.clone());
                m
            }
        };
        if mark.is_some() {
            return mark;
        }
    }
    None
}

pub fn adopt(shot: &mut Shot, mut rows: Vec<Row>, cfg: &Config) {
    if cfg.hide_names {
        compose::auto_hide(&mut rows, false);
    }
    shot.edit.keep = rows.iter().map(|r| r.keep).collect();
    shot.edit.breaks = vec![];
    shot.edit.hidden = crate::edit::spans_of(&rows, false);
    shot.edit.dropped = crate::edit::spans_of(&rows, true);
    shot.rows = rows;
}

pub fn use_log(shot: &mut Shot, cfg: &Config, lines: &[chatlog::Line]) -> Result<usize, String> {
    let name = shot.name.clone().ok_or("у примера нет файлов")?;
    let frame = chatlog::log_frame(lines, shot.bg.dimensions());
    let path = log_path(&shot.out, &name);
    {
        let _g = FILES.lock().unwrap();
        if let Some(dir) = path.parent() {
            std::fs::create_dir_all(dir).map_err(|e| e.to_string())?;
        }
        frame.save(&path).map_err(|e| e.to_string())?;
    }
    let mut rows = chat::classify(chat::extract_rows(&frame), &cfg.keep);
    for r in rows.iter_mut() {
        r.keep = true;
    }
    let n = rows.len();
    adopt(shot, rows, cfg);
    shot.edit.log = Some(lines.iter().map(|(when, parts)| LogLine { at: chatlog::log_key(*when, parts).0, parts: parts.clone() }).collect());
    Ok(n)
}

pub fn use_screen(shot: &mut Shot, cfg: &Config) -> Result<usize, String> {
    let name = shot.name.clone().ok_or("у примера нет файлов")?;
    {
        let _g = FILES.lock().unwrap();
        let _ = std::fs::remove_file(log_path(&shot.out, &name));
    }
    let mut rows = Vec::new();
    for p in screen_chats(&shot.out, &name) {
        rows = chat::merge(rows, chat::classify(chat::extract_rows(&read_image(&p)?), &cfg.keep));
    }
    let n = rows.len();
    adopt(shot, rows, cfg);
    Ok(n)
}

type FrameKey = (PathBuf, String, Option<SystemTime>, Option<SystemTime>, usize);

pub fn frame_shot(out: &Path, name: &str, cfg: &Config) -> Option<Arc<Shot>> {
    static FRAMES: LazyLock<Mutex<Vec<(FrameKey, Option<Arc<Shot>>)>>> = LazyLock::new(|| Mutex::new(Vec::new()));
    let (bg, chats, meta) = shot_files(out, name);
    let key = (out.to_path_buf(), name.to_string(), stamp(&meta), stamp(&bg), chats.len());
    if let Some((_, hit)) = FRAMES.lock().unwrap().iter().find(|(k, _)| *k == key) {
        return hit.clone();
    }
    let shot = load_shot(out, name, cfg).ok().flatten().map(Arc::new);
    let mut frames = FRAMES.lock().unwrap();
    if frames.len() >= compose::SCENE_MAX {
        frames.remove(0);
    }
    frames.push((key, shot.clone()));
    shot
}

pub struct SceneData {
    pub frames: Vec<Option<Arc<Shot>>>,
    pub seams: Vec<Seam>,
    pub homes: Vec<Vec<usize>>,
    pub names: Vec<String>,
}

pub fn scene_of(shot: &Shot) -> Option<SceneData> {
    let scene = shot.edit.scene.as_ref()?;
    let name = shot.name.as_ref()?;
    let cfg = shot.cfg.as_ref()?;
    if !scene.shots.contains(name) {
        return None;
    }
    let mut frames: Vec<Option<Arc<Shot>>> = Vec::new();
    let mut seams = Vec::new();
    let mut names = Vec::new();
    for (k, n) in scene.shots.iter().enumerate() {
        let other = if n == name {
            None
        } else {
            match shot.members.get(n).cloned().or_else(|| frame_shot(&shot.out, n, cfg)) {
                Some(s) => Some(s),
                None => continue,
            }
        };
        if !frames.is_empty() {
            seams.push(if k >= 1 && k - 1 < scene.seams.len() { scene.seams[k - 1].full() } else { Seam::default() });
        }
        frames.push(other);
        names.push(n.clone());
    }
    let homes = frames
        .iter()
        .enumerate()
        .map(|(k, f)| {
            let s: &Shot = f.as_deref().unwrap_or(shot);
            compose::homes_of(s.rows.len(), &s.edit)
                .into_iter()
                .map(|h| h.and_then(|h| names.iter().position(|n| *n == h)).unwrap_or(k))
                .collect()
        })
        .collect();
    if frames.len() > 1 { Some(SceneData { frames, seams, homes, names }) } else { None }
}

pub fn repeats(shots: &[Option<&Shot>]) -> Vec<Vec<usize>> {
    let mut seen: Vec<&Row> = Vec::new();
    let mut out = Vec::new();
    for shot in shots {
        let rows: &[Row] = shot.map(|s| s.rows.as_slice()).unwrap_or(&[]);
        let mine: Vec<usize> =
            (0..rows.len()).filter(|&i| rows[i].keep && seen.iter().any(|s| chat::same_row(&rows[i], s))).collect();
        seen.extend((0..rows.len()).filter(|i| rows[*i].keep && !mine.contains(i)).map(|i| &rows[i]));
        out.push(mine);
    }
    out
}

pub fn scenes_with(out: &Path, name: &str) -> Vec<String> {
    let mut heads = Vec::new();
    for meta in glob(&out.join("src"), |n| n.starts_with("SS_") && n.ends_with(".json")) {
        let stem = stem_of(&meta);
        if stem == name {
            continue;
        }
        let Ok(text) = std::fs::read_to_string(&meta) else { continue };
        if !text.contains(name) {
            continue;
        }
        let shots = serde_json::from_str::<Value>(&text).ok().and_then(|v| v.get("scene")?.get("shots")?.as_array().cloned());
        if shots.is_some_and(|s| s.iter().any(|v| v.as_str() == Some(name))) {
            heads.push(stem);
        }
    }
    heads
}

pub fn render_shot(shot: &Shot, rough: Option<u8>, layout: Option<&mut Layout>) -> Result<(RgbImage, usize), String> {
    let src = shot.src();
    let scene = scene_of(shot);
    let members: Vec<Option<Member>> = scene
        .as_ref()
        .map(|s| {
            s.frames
                .iter()
                .map(|f| f.as_deref().map(|o| Member {
                    name: o.name.clone().unwrap_or_default(),
                    bg: &o.bg,
                    rows: &o.rows,
                    edit: &o.edit,
                    src: o.src(),
                }))
                .collect()
        })
        .unwrap_or_default();
    let input = scene.as_ref().map(|s| SceneInput { members, seams: s.seams.clone(), homes: s.homes.clone(), names: s.names.clone() });
    let when = shot.name.as_deref().and_then(compose::shot_time);
    compose::render(&shot.bg, &shot.rows, &shot.edit, Some(&src), rough, input.as_ref(), layout, when)
}

pub fn donors(out: &Path, name: &str, names: &[String], limit: usize) -> Vec<String> {
    let at = names.iter().position(|n| n == name).unwrap_or(0);
    let mut near: Vec<usize> = (0..names.len()).filter(|&k| k != at).collect();
    near.sort_by_key(|&k| (k as i64 - at as i64).abs());
    let mut found: Vec<usize> = near.into_iter().filter(|&k| !shot_files(out, &names[k]).1.is_empty()).take(limit).collect();
    found.sort();
    found.into_iter().map(|k| names[k].clone()).collect()
}

pub fn carry_chat(shot: &mut Shot, donor: &str, cfg: &Config) -> Result<usize, String> {
    let name = shot.name.clone().ok_or("у примера нет файлов")?;
    let out = shot.out.clone();
    if log_path(&out, &name).exists() {
        return Err("чат этой СС взят из чатлога, добавь строки оттуда".into());
    }
    let (_, files, _) = shot_files(&out, donor);
    if files.is_empty() {
        return Err("у этой СС нет исходных кадров чата".into());
    }
    let theirs = load_rows(&out, donor, cfg)?.0;
    if let (Some(a), Some(b)) = (theirs.first(), shot.rows.first()) {
        if a.screen_w != b.screen_w {
            return Err("та СС снята при другом разрешении экрана".into());
        }
    }
    let old: Vec<u64> = shot.rows.iter().map(|r| r.uid).collect();
    let cut: Vec<u64> = compose::cuts(shot.rows.len(), &shot.edit).into_iter().map(|i| shot.rows[i].uid).collect();
    let mut merged = shot.rows.clone();
    for src in &files {
        merged = chat::merge(merged, chat::classify(chat::extract_rows(&read_image(src)?), &cfg.keep));
    }
    if merged.len() == old.len() {
        return Ok(0);
    }
    let first = shot_files(&out, &name).1.iter().map(|p| chat_number(p)).max().unwrap_or(0) + 1;
    {
        let _g = FILES.lock().unwrap();
        for (k, src) in files.iter().enumerate() {
            let target = out.join("src").join(format!("{name}_chat{}{}", first + k as u32, ext_of(src)));
            std::fs::copy(src, target).map_err(|e| e.to_string())?;
        }
    }
    for r in merged.iter_mut().filter(|r| !old.contains(&r.uid)) {
        if let Some(twin) = theirs.iter().find(|t| chat::same_row(t, r)) {
            r.keep = twin.keep;
            r.hide = Some(twin.hidden().to_vec());
            r.drop = twin.drop.clone();
        }
    }
    shot.edit.keep = merged.iter().map(|r| r.keep).collect();
    shot.edit.breaks = cut.iter().filter_map(|u| merged.iter().position(|r| r.uid == *u)).map(|i| i as i64).collect();
    shot.edit.hidden = crate::edit::spans_of(&merged, false);
    shot.edit.dropped = crate::edit::spans_of(&merged, true);
    let added = merged.len() - old.len();
    shot.rows = merged;
    Ok(added)
}

pub fn encode(img: &RgbImage, file: &str, quality: u8) -> Result<Vec<u8>, String> {
    let mut buf = Vec::new();
    if file == "jpg" {
        let mut enc = jpeg_encoder::Encoder::new(&mut buf, quality);
        enc.set_sampling_factor(jpeg_encoder::SamplingFactor::R_4_4_4);
        enc.set_progressive(true);
        enc.set_optimized_huffman_tables(true);
        enc.encode(img.as_raw(), img.width() as u16, img.height() as u16, jpeg_encoder::ColorType::Rgb)
            .map_err(|e| e.to_string())?;
    } else {
        let enc = image::codecs::png::PngEncoder::new_with_quality(&mut buf, image::codecs::png::CompressionType::Default,
                                                                   image::codecs::png::FilterType::Adaptive);
        image::ImageEncoder::write_image(enc, img.as_raw(), img.width(), img.height(), image::ExtendedColorType::Rgb8)
            .map_err(|e| e.to_string())?;
    }
    Ok(buf)
}

pub fn encoded(shot: &Shot, layout: Option<&mut Layout>) -> Result<(RgbImage, usize, Vec<u8>), String> {
    let file = shot.edit.file.as_str();
    let mut quality = 95u8;
    let mut rough = None;
    if file == "jpg" {
        let q = shot.edit.quality;
        quality = q.max(TEXT_QUALITY).clamp(1, 100) as u8;
        rough = if q < TEXT_QUALITY { Some(q.clamp(1, 100) as u8) } else { None };
    }
    let (img, painted) = render_shot(shot, rough, layout)?;
    let data = encode(&img, file, quality)?;
    Ok((img, painted, data))
}

pub fn write_image(out: &Path, name: &str, file: &str, data: &[u8]) -> std::io::Result<()> {
    std::fs::write(out.join(format!("{name}.{file}")), data)?;
    for other in FILE_TYPES.iter().filter(|f| **f != file) {
        let _ = std::fs::remove_file(out.join(format!("{name}.{other}")));
    }
    Ok(())
}

pub fn save_shot(shot: &Shot, heads: bool) -> Result<(RgbImage, usize), String> {
    let name = shot.name.clone().ok_or("у примера нет файлов")?;
    let (img, painted, data) = encoded(shot, None)?;
    let (_, _, meta) = shot_files(&shot.out, &name);
    {
        let _g = FILES.lock().unwrap();
        if let Some(dir) = meta.parent() {
            std::fs::create_dir_all(dir).map_err(|e| e.to_string())?;
        }
        write_image(&shot.out, &name, &shot.edit.file, &data).map_err(|e| e.to_string())?;
        std::fs::write(&meta, shot.edit.to_json()).map_err(|e| e.to_string())?;
    }
    if heads {
        refresh_heads(&shot.out, &[name], shot.cfg.as_ref(), &[]);
    }
    Ok((img, painted))
}

pub fn refresh_heads(out: &Path, names: &[String], cfg: Option<&Config>, skip: &[String]) -> Vec<String> {
    let Some(cfg) = cfg else { return vec![] };
    let mut heads: Vec<String> = names.iter().flat_map(|n| scenes_with(out, n)).filter(|h| !skip.contains(h)).collect();
    heads.sort();
    heads.dedup();
    rerender(out, &heads, cfg)
}

pub fn rerender(out: &Path, heads: &[String], cfg: &Config) -> Vec<String> {
    for head in heads {
        let result = load_shot(out, head, cfg).and_then(|whole| match whole {
            Some(whole) => {
                let data = encoded(&whole, None)?.2;
                let _g = FILES.lock().unwrap();
                write_image(out, head, &whole.edit.file, &data).map_err(|e| e.to_string())
            }
            None => Ok(()),
        });
        if let Err(e) = result {
            config::log(&format!("Сцена {head} не обновилась: {e}"), "fail");
        }
    }
    heads.to_vec()
}

pub fn shot_paths(out: &Path, name: &str) -> Vec<PathBuf> {
    let own = Regex::new(&format!(r"^{}(_bg|_chat\d+|_log|_ov\d+)?$", regex::escape(name))).unwrap();
    let mut paths: Vec<PathBuf> = glob(out, |n| n.starts_with(name))
        .into_iter()
        .filter(|p| stem_of(p) == name && FILE_TYPES.contains(&ext_of(p).trim_start_matches('.').to_lowercase().as_str()))
        .collect();
    paths.extend(glob(&out.join("src"), |n| n.starts_with(name)).into_iter().filter(|p| own.is_match(&stem_of(p))));
    paths
}

pub fn drop_member(edit: &mut Value, name: &str) {
    let Some(scene) = edit.get_mut("scene").filter(|s| s.is_object()) else { return };
    let mut shots: Vec<Value> = scene.get("shots").and_then(|v| v.as_array().cloned()).unwrap_or_default();
    let mut seams: Vec<Value> = scene.get("seams").and_then(|v| v.as_array().cloned()).unwrap_or_default();
    let Some(k) = shots.iter().position(|v| v.as_str() == Some(name)) else { return };
    shots.remove(k);
    if !seams.is_empty() {
        let at = k.min(seams.len() - 1);
        seams.remove(at);
    }
    if shots.len() > 1 {
        scene["shots"] = Value::Array(shots);
        scene["seams"] = Value::Array(seams);
    } else {
        edit["scene"] = Value::Null;
    }
}

pub fn delete_shot(out: &Path, name: &str, cfg: &Config, recycle: &dyn Fn(&[PathBuf]) -> Result<(), String>)
                   -> Result<Vec<String>, String> {
    let heads = scenes_with(out, name);
    {
        let _g = FILES.lock().unwrap();
        recycle(&shot_paths(out, name))?;
        for head in &heads {
            let mut edit = saved_edit(out, head);
            drop_member(&mut edit, name);
            std::fs::write(shot_files(out, head).2, serde_json::to_string(&edit).unwrap_or_default()).map_err(|e| e.to_string())?;
        }
    }
    Ok(rerender(out, &heads, cfg))
}

pub fn duplicate_shot(out: &Path, name: &str) -> Result<String, String> {
    let _g = FILES.lock().unwrap();
    let base = chrono::NaiveDateTime::parse_from_str(name, "SS_%Y-%m-%d_%H-%M-%S").ok();
    let copy = (1..1000)
        .map(|k| match base {
            Some(t) => (t + chrono::TimeDelta::seconds(k)).format("SS_%Y-%m-%d_%H-%M-%S").to_string(),
            None => format!("{name}-{}", k + 1),
        })
        .find(|n| shot_paths(out, n).is_empty())
        .ok_or("не нашлось свободного имени")?;
    for p in shot_paths(out, name) {
        let file = p.file_name().map(|f| f.to_string_lossy().replacen(name, &copy, 1)).unwrap_or_default();
        let to = p.with_file_name(file);
        if ext_of(&p) == ".json" {
            let text = std::fs::read_to_string(&p).map_err(|e| e.to_string())?;
            std::fs::write(&to, text.replace(name, &copy)).map_err(|e| e.to_string())?;
        } else {
            std::fs::copy(&p, &to).map_err(|e| e.to_string())?;
        }
    }
    Ok(copy)
}

pub fn save_src(img: &RgbImage, out: &Path, stem: &str, chat_frame: bool) -> Result<PathBuf, String> {
    let dir = out.join("src");
    std::fs::create_dir_all(&dir).map_err(|e| e.to_string())?;
    let path = dir.join(format!("{stem}{}", if chat_frame { SRC_CHAT } else { SRC_BG }));
    let mut buf = Vec::new();
    if chat_frame {
        image::codecs::webp::WebPEncoder::new_lossless(&mut buf)
            .encode(img.as_raw(), img.width(), img.height(), image::ExtendedColorType::Rgb8)
            .map_err(|e| e.to_string())?;
    } else {
        let mut enc = jpeg_encoder::Encoder::new(&mut buf, 95);
        enc.set_sampling_factor(jpeg_encoder::SamplingFactor::R_4_4_4);
        enc.encode(img.as_raw(), img.width() as u16, img.height() as u16, jpeg_encoder::ColorType::Rgb)
            .map_err(|e| e.to_string())?;
    }
    std::fs::write(&path, buf).map_err(|e| e.to_string())?;
    Ok(path)
}

pub fn explain(e: &str, path: Option<&Path>, cfg: &Config) -> String {
    match path {
        Some(p) if p.starts_with(&cfg.out) => format!(
            "Windows не даёт записать в папку {}. Обычно её защищает «Контролируемый доступ к папкам» в Защитнике Windows. \
             Выбери в настройках другую папку, например D:\\Snapline, или разреши snapline.exe в Защитнике.",
            cfg.out.display()),
        _ => format!("Не получилось: {e}"),
    }
}

pub fn check_out(cfg: &Config) -> Option<String> {
    let probe = cfg.out.join("src").join("SS_write_check.tmp");
    let attempt = (|| -> std::io::Result<()> {
        std::fs::create_dir_all(probe.parent().unwrap())?;
        std::fs::write(&probe, b"")?;
        std::fs::remove_file(&probe)
    })();
    attempt.err().map(|e| explain(&e.to_string(), Some(&probe), cfg))
}

pub fn saved_edit(out: &Path, name: &str) -> Value {
    let (_, _, meta) = shot_files(out, name);
    std::fs::read(meta).ok().and_then(|b| serde_json::from_slice(&b).ok()).unwrap_or_else(|| Value::Object(Default::default()))
}

pub fn seam_parts(seams: &[Seam]) -> Vec<SeamPart> {
    seams.iter().map(|s| SeamPart::of(*s)).collect()
}

pub fn sample_shot(cfg: &Config, bg: &[u8], frame: &[u8]) -> Option<Shot> {
    for name in list_shots(&cfg.out) {
        if let Ok(Some(shot)) = load_shot(&cfg.out, &name, cfg) {
            return Some(shot);
        }
    }
    let frame = image::load_from_memory(frame).ok()?.to_rgb8();
    let rows = chat::classify(chat::extract_rows(&frame), &cfg.keep);
    let bg = chat::clean_bg(&image::load_from_memory(bg).ok()?.to_rgb8(), chat::watermark(&frame).as_ref());
    let edit = Edit::new(cfg, &rows);
    Some(Shot { name: None, out: cfg.out.clone(), bg: Arc::new(bg), rows, edit, legacy: false, cfg: Some(cfg.clone()), members: HashMap::new() })
}
