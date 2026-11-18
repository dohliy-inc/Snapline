use std::collections::HashMap;
use std::path::PathBuf;
use std::sync::{Arc, Mutex, OnceLock};

use ab_glyph::{Font, FontArc, Glyph, PxScale, ScaleFont, point};
use image::RgbImage;

fn fonts_dir() -> PathBuf {
    PathBuf::from(std::env::var_os("WINDIR").unwrap_or_else(|| "C:\\Windows".into())).join("Fonts")
}

pub fn font(name: &str) -> Option<FontArc> {
    static CACHE: OnceLock<Mutex<HashMap<String, Option<FontArc>>>> = OnceLock::new();
    let cache = CACHE.get_or_init(|| Mutex::new(HashMap::new()));
    let mut cache = cache.lock().unwrap();
    cache
        .entry(name.to_string())
        .or_insert_with(|| {
            let bytes = std::fs::read(fonts_dir().join(name)).ok()?;
            FontArc::try_from_vec(bytes).ok()
        })
        .clone()
}

#[derive(Clone)]
pub struct Face {
    pub font: FontArc,
    pub scale: PxScale,
}

impl Face {
    pub fn new(name: &str, px: i64) -> Option<Face> {
        let font = font(name)?;
        let size = px.max(8) as f32;
        let scale = match font.units_per_em() {
            Some(em) => PxScale::from(size * font.height_unscaled() / em),
            None => PxScale::from(size),
        };
        Some(Face { font, scale })
    }

    pub fn ascent(&self) -> f32 {
        self.font.as_scaled(self.scale).ascent()
    }

    pub fn descent(&self) -> f32 {
        self.font.as_scaled(self.scale).descent()
    }

    pub fn length(&self, text: &str) -> f32 {
        let scaled = self.font.as_scaled(self.scale);
        let mut x = 0.0;
        let mut prev = None;
        for c in text.chars() {
            let id = scaled.glyph_id(c);
            if let Some(p) = prev {
                x += scaled.kern(p, id);
            }
            x += scaled.h_advance(id);
            prev = Some(id);
        }
        x
    }

    fn glyphs(&self, text: &str, x: f32, baseline: f32) -> Vec<Glyph> {
        let scaled = self.font.as_scaled(self.scale);
        let mut out = Vec::new();
        let mut pen = x;
        let mut prev = None;
        for c in text.chars() {
            let id = scaled.glyph_id(c);
            if let Some(p) = prev {
                pen += scaled.kern(p, id);
            }
            out.push(id.with_scale_and_position(self.scale, point(pen.round(), baseline.round())));
            pen += scaled.h_advance(id);
            prev = Some(id);
        }
        out
    }

    pub fn origin(&self, text: &str, xy: (f32, f32), anchor: &str) -> (f32, f32) {
        let mut chars = anchor.chars();
        let h = chars.next().unwrap_or('l');
        let v = chars.next().unwrap_or('a');
        let x = match h {
            'r' => xy.0 - self.length(text),
            'm' => xy.0 - self.length(text) / 2.0,
            _ => xy.0,
        };
        let baseline = match v {
            'a' => xy.1 + self.ascent(),
            'd' => xy.1 + self.descent(),
            'm' => xy.1 + (self.ascent() + self.descent()) / 2.0,
            _ => xy.1,
        };
        (x, baseline)
    }

    pub fn bbox(&self, text: &str, xy: (f32, f32), anchor: &str) -> [i64; 4] {
        let (x, baseline) = self.origin(text, xy, anchor);
        let mut b = [i64::MAX, i64::MAX, i64::MIN, i64::MIN];
        for g in self.glyphs(text, x, baseline) {
            if let Some(o) = self.font.outline_glyph(g) {
                let r = o.px_bounds();
                b[0] = b[0].min(r.min.x.floor() as i64);
                b[1] = b[1].min(r.min.y.floor() as i64);
                b[2] = b[2].max(r.max.x.ceil() as i64);
                b[3] = b[3].max(r.max.y.ceil() as i64);
            }
        }
        if b[0] == i64::MAX {
            let x = x.round() as i64;
            let y = baseline.round() as i64;
            return [x, y, x, y];
        }
        b
    }

    pub fn draw(&self, img: &mut RgbImage, text: &str, xy: (f32, f32), anchor: &str, color: [u8; 3]) {
        let (x, baseline) = self.origin(text, xy, anchor);
        let (w, h) = (img.width() as i64, img.height() as i64);
        for g in self.glyphs(text, x, baseline) {
            let Some(o) = self.font.outline_glyph(g) else { continue };
            let r = o.px_bounds();
            let (ox, oy) = (r.min.x as i64, r.min.y as i64);
            o.draw(|gx, gy, cov| {
                let (px, py) = (ox + gx as i64, oy + gy as i64);
                if px < 0 || py < 0 || px >= w || py >= h || cov <= 0.0 {
                    return;
                }
                let cov = cov.min(1.0);
                let p = img.get_pixel_mut(px as u32, py as u32);
                for c in 0..3 {
                    p[c] = (color[c] as f32 * cov + p[c] as f32 * (1.0 - cov)).round().clamp(0.0, 255.0) as u8;
                }
            });
        }
    }
}

pub fn ellipse(img: &mut RgbImage, b: [i64; 4], color: [u8; 3]) {
    let (cx, cy) = ((b[0] + b[2]) as f64 / 2.0, (b[1] + b[3]) as f64 / 2.0);
    let (rx, ry) = (((b[2] - b[0]) as f64 / 2.0 + 0.5).max(0.5), ((b[3] - b[1]) as f64 / 2.0 + 0.5).max(0.5));
    for y in b[1].max(0)..=b[3].min(img.height() as i64 - 1) {
        for x in b[0].max(0)..=b[2].min(img.width() as i64 - 1) {
            let (dx, dy) = ((x as f64 - cx) / rx, (y as f64 - cy) / ry);
            if dx * dx + dy * dy <= 1.0 {
                img.put_pixel(x as u32, y as u32, image::Rgb(color));
            }
        }
    }
}

pub type Shared = Arc<Face>;
