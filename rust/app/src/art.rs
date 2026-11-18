use ab_glyph::{Font, FontVec, PxScale, VariableFont, point};
use image::{Rgba, RgbaImage};

fn in_rounded(px: f32, py: f32, b: [f32; 4], r: f32) -> bool {
    let (cx, cy) = ((b[0] + b[2]) / 2.0, (b[1] + b[3]) / 2.0);
    let (hw, hh) = ((b[2] - b[0]) / 2.0 - r, (b[3] - b[1]) / 2.0 - r);
    let dx = ((px - cx).abs() - hw).max(0.0);
    let dy = ((py - cy).abs() - hh).max(0.0);
    dx * dx + dy * dy <= r * r
}

fn mix(img: &mut RgbaImage, x: u32, y: u32, color: [u8; 3], a: f32) {
    if a <= 0.0 {
        return;
    }
    let p = img.get_pixel_mut(x, y);
    let da = p[3] as f32 / 255.0;
    let out = a + da * (1.0 - a);
    for c in 0..3 {
        let v = (color[c] as f32 * a + p[c] as f32 * da * (1.0 - a)) / out.max(1e-6);
        p[c] = v.round().clamp(0.0, 255.0) as u8;
    }
    p[3] = (out * 255.0).round() as u8;
}

fn layer(img: &mut RgbaImage, color: [u8; 3], test: &dyn Fn(f32, f32) -> bool, scale: f32) {
    let n = 4;
    for y in 0..img.height() {
        for x in 0..img.width() {
            let mut hit = 0;
            for sy in 0..n {
                for sx in 0..n {
                    let px = (x as f32 + (sx as f32 + 0.5) / n as f32) / scale;
                    let py = (y as f32 + (sy as f32 + 0.5) / n as f32) / scale;
                    hit += test(px, py) as u32;
                }
            }
            mix(img, x, y, color, hit as f32 / (n * n) as f32);
        }
    }
}

fn brand_font() -> Option<FontVec> {
    let dir = std::path::PathBuf::from(std::env::var_os("WINDIR").unwrap_or_else(|| r"C:\Windows".into())).join("Fonts");
    ["SegUIVar.ttf", "segoeuib.ttf"].iter().find_map(|file| {
        let mut font = FontVec::try_from_vec(std::fs::read(dir.join(file)).ok()?).ok()?;
        font.set_variation(b"wght", 700.0);
        font.set_variation(b"opsz", 36.0);
        Some(font)
    })
}

pub fn make_icon(size: u32) -> RgbaImage {
    let s = size as f32 / 256.0;
    let mut img = RgbaImage::from_pixel(size, size, Rgba([0, 0, 0, 0]));
    layer(&mut img, [0x0a, 0x0a, 0x0a], &|x, y| in_rounded(x, y, [8.0, 8.0, 248.0, 248.0], 56.0), s);
    let Some(font) = brand_font() else { return img };
    let em = size as f32 * if size <= 24 { 0.86 } else if size <= 32 { 0.8 } else { 0.73 };
    let scale = PxScale::from(em * font.height_unscaled() / font.units_per_em().unwrap_or(2048.0));
    let id = font.glyph_id('S');
    let Some(probe) = font.outline_glyph(id.with_scale_and_position(scale, point(0.0, 0.0))) else { return img };
    let b = probe.px_bounds();
    let c = size as f32 / 2.0;
    let at = point((c - (b.min.x + b.max.x) / 2.0).round(), (c - (b.min.y + b.max.y) / 2.0).round());
    let Some(glyph) = font.outline_glyph(id.with_scale_and_position(scale, at)) else { return img };
    let b = glyph.px_bounds();
    glyph.draw(|x, y, cover| {
        let (x, y) = (b.min.x as i32 + x as i32, b.min.y as i32 + y as i32);
        if x >= 0 && y >= 0 && (x as u32) < size && (y as u32) < size {
            mix(&mut img, x as u32, y as u32, [0xf4, 0xf4, 0xf5], cover.min(1.0));
        }
    });
    img
}

pub fn png(img: &RgbaImage) -> Vec<u8> {
    let mut buf = Vec::new();
    let _ = image::DynamicImage::ImageRgba8(img.clone()).write_to(&mut std::io::Cursor::new(&mut buf), image::ImageFormat::Png);
    buf
}
