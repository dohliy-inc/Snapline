use std::collections::BTreeMap;

use serde::{Deserialize, Deserializer, Serialize};
use serde_json::{Map, Value};

use crate::chat::Row;
use crate::config::Config;

pub const LAYOUT_KEYS: [&str; 21] = ["format", "zoom", "center", "pos", "places", "size", "file", "quality", "text_scale",
    "outline", "margin", "overlays", "join", "scene", "style", "style_text", "preset", "look", "lut", "mirror", "tilt"];

fn int<'de, D: Deserializer<'de>>(d: D) -> Result<i64, D::Error> {
    let v = f64::deserialize(d)?;
    Ok(v.round_ties_even() as i64)
}

fn ints<'de, D: Deserializer<'de>>(d: D) -> Result<Vec<i64>, D::Error> {
    let v = Vec::<f64>::deserialize(d)?;
    Ok(v.into_iter().map(|x| x.round_ties_even() as i64).collect())
}

fn triples<'de, D: Deserializer<'de>>(d: D) -> Result<Vec<[i64; 3]>, D::Error> {
    let v = Vec::<Vec<f64>>::deserialize(d)?;
    Ok(v.into_iter().filter(|t| t.len() == 3).map(|t| [t[0], t[1], t[2]].map(|x| x.round_ties_even() as i64)).collect())
}

fn no(v: &bool) -> bool {
    !*v
}

#[derive(Clone, Debug, PartialEq, Serialize, Deserialize)]
#[serde(untagged)]
pub enum Coord {
    Num(f64),
    Side(String),
}

#[derive(Clone, Debug, PartialEq, Serialize, Deserialize)]
#[serde(untagged)]
pub enum Pos {
    Corner(String),
    Free(Coord, Coord),
}

impl Pos {
    pub fn corner(name: &str) -> Pos {
        Pos::Corner(name.to_string())
    }

    pub fn axes(&self) -> (Coord, Coord) {
        match self {
            Pos::Corner(s) => {
                let (y, x) = s.split_once('-').unwrap_or(("top", "left"));
                (Coord::Side(x.to_string()), Coord::Side(y.to_string()))
            }
            Pos::Free(x, y) => (x.clone(), y.clone()),
        }
    }

    pub fn is_corner(&self) -> bool {
        matches!(self, Pos::Corner(_))
    }
}

#[derive(Clone, Debug, PartialEq, Serialize, Deserialize)]
pub struct Overlay {
    pub file: String,
    pub x: f64,
    pub y: f64,
    pub w: f64,
    pub crop: [f64; 4],
    #[serde(default = "free")]
    pub cut: String,
    #[serde(default)]
    pub soft: f64,
    #[serde(default = "one")]
    pub alpha: f64,
    #[serde(default, skip_serializing_if = "Option::is_none")]
    pub flip: Option<bool>,
    #[serde(default, skip_serializing_if = "Option::is_none")]
    pub angle: Option<f64>,
    #[serde(flatten)]
    pub extra: Map<String, Value>,
}

impl Overlay {
    pub fn flipped(&self) -> bool {
        self.flip.unwrap_or(false)
    }

    pub fn turn(&self) -> f64 {
        self.angle.unwrap_or(0.0)
    }
}

fn free() -> String {
    "free".to_string()
}

fn one() -> f64 {
    1.0
}

#[derive(Clone, Debug, PartialEq, Serialize, Deserialize)]
pub struct Join {
    pub side: String,
    pub size: f64,
    pub fade: f64,
    #[serde(flatten)]
    pub extra: Map<String, Value>,
}

#[derive(Clone, Copy, Debug, PartialEq, Serialize, Deserialize)]
pub struct Seam {
    pub fade: f64,
    pub blur: f64,
    pub dark: f64,
}

impl Default for Seam {
    fn default() -> Self {
        Seam { fade: 0.2, blur: 0.6, dark: 0.3 }
    }
}

#[derive(Clone, Debug, Default, PartialEq, Serialize, Deserialize)]
pub struct SeamPart {
    #[serde(default, skip_serializing_if = "Option::is_none")]
    pub fade: Option<f64>,
    #[serde(default, skip_serializing_if = "Option::is_none")]
    pub blur: Option<f64>,
    #[serde(default, skip_serializing_if = "Option::is_none")]
    pub dark: Option<f64>,
    #[serde(flatten)]
    pub extra: Map<String, Value>,
}

impl SeamPart {
    pub fn full(&self) -> Seam {
        let d = Seam::default();
        Seam { fade: self.fade.unwrap_or(d.fade), blur: self.blur.unwrap_or(d.blur), dark: self.dark.unwrap_or(d.dark) }
    }

    pub fn of(seam: Seam) -> SeamPart {
        SeamPart { fade: Some(seam.fade), blur: Some(seam.blur), dark: Some(seam.dark), extra: Map::new() }
    }
}

#[derive(Clone, Debug, PartialEq, Serialize, Deserialize)]
pub struct Scene {
    pub shots: Vec<String>,
    #[serde(default)]
    pub seams: Vec<SeamPart>,
    #[serde(flatten)]
    pub extra: Map<String, Value>,
}

#[derive(Clone, Debug, PartialEq, Serialize, Deserialize)]
pub struct Blur {
    pub x: f64,
    pub y: f64,
    pub w: f64,
    pub h: f64,
    #[serde(default = "blur_mode")]
    pub mode: String,
    #[serde(default = "blur_power")]
    pub power: f64,
    #[serde(flatten)]
    pub extra: Map<String, Value>,
}

fn blur_mode() -> String {
    "blur".to_string()
}

fn blur_power() -> f64 {
    0.6
}

#[derive(Clone, Debug, PartialEq, Serialize, Deserialize)]
#[serde(untagged)]
pub enum Home {
    One(String),
    Many(Vec<Option<String>>),
}

#[derive(Clone, Debug, PartialEq, Serialize, Deserialize)]
pub struct LogLine {
    pub at: String,
    pub parts: Vec<(String, String)>,
}

#[derive(Clone, Debug, PartialEq, Serialize, Deserialize)]
pub struct Edit {
    pub keep: Vec<bool>,
    pub format: String,
    pub zoom: f64,
    pub center: [f64; 2],
    pub pos: Pos,
    #[serde(deserialize_with = "ints")]
    pub breaks: Vec<i64>,
    pub places: Vec<Pos>,
    #[serde(deserialize_with = "triples")]
    pub hidden: Vec<[i64; 3]>,
    #[serde(deserialize_with = "triples")]
    pub dropped: Vec<[i64; 3]>,
    pub overlays: Vec<Overlay>,
    pub join: Option<Join>,
    pub scene: Option<Scene>,
    pub size: String,
    pub file: String,
    #[serde(deserialize_with = "int")]
    pub quality: i64,
    pub text_scale: f64,
    #[serde(deserialize_with = "int")]
    pub outline: i64,
    #[serde(deserialize_with = "int")]
    pub margin: i64,
    #[serde(default, skip_serializing_if = "Option::is_none")]
    pub home: Option<Home>,
    #[serde(default, skip_serializing_if = "Option::is_none")]
    pub log: Option<Vec<LogLine>>,
    #[serde(default, skip_serializing_if = "Option::is_none")]
    pub style: Option<String>,
    #[serde(default, skip_serializing_if = "Option::is_none")]
    pub style_text: Option<String>,
    #[serde(default, skip_serializing_if = "Option::is_none")]
    pub preset: Option<String>,
    #[serde(default, skip_serializing_if = "Option::is_none")]
    pub look: Option<BTreeMap<String, f64>>,
    #[serde(default, skip_serializing_if = "Option::is_none")]
    pub lut: Option<String>,
    #[serde(default, skip_serializing_if = "no")]
    pub mirror: bool,
    #[serde(default, skip_serializing_if = "Option::is_none")]
    pub tilt: Option<f64>,
    #[serde(default, skip_serializing_if = "Option::is_none")]
    pub blurs: Option<Vec<Blur>>,
    #[serde(flatten)]
    pub extra: Map<String, Value>,
}

pub fn spans_of(rows: &[Row], drop: bool) -> Vec<[i64; 3]> {
    rows.iter()
        .enumerate()
        .flat_map(|(i, r)| {
            let spans = if drop { r.drop.clone() } else { r.hidden().to_vec() };
            spans.into_iter().map(move |(a, b)| [i as i64, a as i64, b as i64])
        })
        .collect()
}

impl Edit {
    pub fn new(cfg: &Config, rows: &[Row]) -> Edit {
        Edit {
            keep: rows.iter().map(|r| r.keep).collect(),
            format: cfg.format.clone(),
            zoom: 1.0,
            center: [0.5, 0.5],
            pos: Pos::corner(&cfg.chat_pos),
            breaks: vec![],
            places: vec![],
            hidden: spans_of(rows, false),
            dropped: spans_of(rows, true),
            overlays: vec![],
            join: None,
            scene: None,
            size: cfg.size.clone(),
            file: cfg.file.clone(),
            quality: cfg.quality,
            text_scale: cfg.text_scale,
            outline: cfg.outline,
            margin: cfg.margin,
            home: None,
            log: None,
            style: None,
            style_text: None,
            preset: None,
            look: None,
            lut: None,
            mirror: false,
            tilt: None,
            blurs: None,
            extra: Map::new(),
        }
    }

    pub fn merged(base: Edit, saved: &Value) -> Edit {
        let Value::Object(saved) = saved else { return base };
        let Ok(Value::Object(mut whole)) = serde_json::to_value(&base) else { return base };
        for (k, v) in saved {
            whole.insert(k.clone(), v.clone());
        }
        serde_json::from_value(Value::Object(whole)).unwrap_or(base)
    }

    pub fn with_style(mut self, cfg: &Config) -> Edit {
        self.preset = (cfg.preset != "none").then(|| cfg.preset.clone());
        self.look = (!cfg.look.is_empty()).then(|| cfg.look.clone());
        self.lut = (!cfg.lut.is_empty()).then(|| cfg.lut.clone());
        self.style = (cfg.style != "none").then(|| cfg.style.clone());
        self
    }

    pub fn with_keys(base: Edit, old: &Value, keys: &[&str]) -> Edit {
        let Value::Object(old) = old else { return base };
        let picked: Map<String, Value> = old.iter().filter(|(k, _)| keys.contains(&k.as_str())).map(|(k, v)| (k.clone(), v.clone())).collect();
        Edit::merged(base, &Value::Object(picked))
    }

    pub fn to_json(&self) -> String {
        serde_json::to_string(self).unwrap_or_else(|_| "{}".to_string())
    }

    pub fn tilt(&self) -> f64 {
        self.tilt.unwrap_or(0.0)
    }
}
