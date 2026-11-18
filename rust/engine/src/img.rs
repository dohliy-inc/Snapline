use fast_image_resize::images::Image as FirImage;
use fast_image_resize::{FilterType, PixelType, ResizeAlg, ResizeOptions, Resizer};
use image::{Rgb, RgbImage, Rgba, RgbaImage};

#[derive(Clone, Copy, Debug, PartialEq, Eq)]
pub enum Filter {
    Nearest,
    Box,
    Bilinear,
    Bicubic,
    Lanczos,
}

impl Filter {
    fn alg(self) -> ResizeAlg {
        match self {
            Filter::Nearest => ResizeAlg::Nearest,
            Filter::Box => ResizeAlg::Convolution(FilterType::Box),
            Filter::Bilinear => ResizeAlg::Convolution(FilterType::Bilinear),
            Filter::Bicubic => ResizeAlg::Convolution(FilterType::CatmullRom),
            Filter::Lanczos => ResizeAlg::Convolution(FilterType::Lanczos3),
        }
    }
}

fn resize_raw(data: &[u8], w: u32, h: u32, nw: u32, nh: u32, kind: PixelType, filter: Filter,
              crop: Option<(f64, f64, f64, f64)>) -> Vec<u8> {
    let nw = nw.max(1);
    let nh = nh.max(1);
    if w == nw && h == nh && crop.is_none() {
        return data.to_vec();
    }
    let src = FirImage::from_vec_u8(w, h, data.to_vec(), kind).expect("image buffer size");
    let mut dst = FirImage::new(nw, nh, kind);
    let mut options = ResizeOptions::new().resize_alg(filter.alg());
    if let Some((x0, y0, x1, y1)) = crop {
        options = options.crop(x0, y0, x1 - x0, y1 - y0);
    }
    Resizer::new().resize(&src, &mut dst, &options).expect("resize");
    dst.into_vec()
}

pub fn resize(img: &RgbImage, w: u32, h: u32, filter: Filter) -> RgbImage {
    let data = resize_raw(img.as_raw(), img.width(), img.height(), w, h, PixelType::U8x3, filter, None);
    RgbImage::from_raw(w.max(1), h.max(1), data).unwrap()
}

pub fn resize_box(img: &RgbImage, w: u32, h: u32, filter: Filter, crop: (f64, f64, f64, f64)) -> RgbImage {
    let data = resize_raw(img.as_raw(), img.width(), img.height(), w, h, PixelType::U8x3, filter, Some(crop));
    RgbImage::from_raw(w.max(1), h.max(1), data).unwrap()
}

pub fn resize_rgba(img: &RgbaImage, w: u32, h: u32, filter: Filter) -> RgbaImage {
    let data = resize_raw(img.as_raw(), img.width(), img.height(), w, h, PixelType::U8x4, filter, None);
    RgbaImage::from_raw(w.max(1), h.max(1), data).unwrap()
}

pub fn resize_gray(data: &[u8], w: u32, h: u32, nw: u32, nh: u32, filter: Filter) -> Vec<u8> {
    resize_raw(data, w, h, nw, nh, PixelType::U8, filter, None)
}

pub fn crop(img: &RgbImage, x0: u32, y0: u32, x1: u32, y1: u32) -> RgbImage {
    image::imageops::crop_imm(img, x0, y0, x1.saturating_sub(x0).max(1), y1.saturating_sub(y0).max(1)).to_image()
}

pub fn crop_rgba(img: &RgbaImage, x0: u32, y0: u32, x1: u32, y1: u32) -> RgbaImage {
    image::imageops::crop_imm(img, x0, y0, x1.saturating_sub(x0).max(1), y1.saturating_sub(y0).max(1)).to_image()
}

pub fn flip_h(img: &RgbImage) -> RgbImage {
    image::imageops::flip_horizontal(img)
}

pub fn flip_h_rgba(img: &RgbaImage) -> RgbaImage {
    image::imageops::flip_horizontal(img)
}

pub fn transpose(img: &RgbImage) -> RgbImage {
    let (w, h) = img.dimensions();
    let mut out = RgbImage::new(h, w);
    for y in 0..h {
        for x in 0..w {
            out.put_pixel(y, x, *img.get_pixel(x, y));
        }
    }
    out
}

pub fn transverse(img: &RgbImage) -> RgbImage {
    let (w, h) = img.dimensions();
    let mut out = RgbImage::new(h, w);
    for y in 0..h {
        for x in 0..w {
            out.put_pixel(h - 1 - y, w - 1 - x, *img.get_pixel(x, y));
        }
    }
    out
}

fn blur_radius(radius: f32, passes: u32) -> f32 {
    let sigma2 = radius * radius / passes as f32;
    let big = (12.0 * sigma2 + 1.0).sqrt();
    let l = ((big - 1.0) / 2.0).floor();
    let a = (2.0 * l + 1.0) * (l * (l + 1.0) - 3.0 * sigma2) / (6.0 * (sigma2 - (l + 1.0) * (l + 1.0)));
    l + a
}

fn box_line(src: &[u8], dst: &mut [u8], n: usize, stride: usize, ch: usize, radius: f32) {
    let r = radius.floor() as i64;
    let frac = radius - r as f32;
    let norm = 1.0 / (radius * 2.0 + 1.0);
    let last = n as i64 - 1;
    let at = |i: i64, c: usize| src[(i.clamp(0, last) as usize) * stride + c] as f32;
    for c in 0..ch {
        let mut acc = 0.0f32;
        for i in -r..=r {
            acc += at(i, c);
        }
        let mut edge = at(-r - 1, c) + at(r + 1, c);
        for x in 0..n as i64 {
            let v = (acc + edge * frac) * norm;
            dst[x as usize * stride + c] = v.round().clamp(0.0, 255.0) as u8;
            acc += at(x + r + 1, c) - at(x - r, c);
            edge += at(x + r + 2, c) - at(x + r + 1, c) + at(x - r, c) - at(x - r - 1, c);
        }
    }
}

pub fn box_blur_raw(data: &mut [u8], w: usize, h: usize, ch: usize, radius: f32, passes: u32) {
    if radius <= 0.0 || w == 0 || h == 0 {
        return;
    }
    let mut line = vec![0u8; w.max(h) * ch];
    for _ in 0..passes {
        for y in 0..h {
            let row = &mut data[y * w * ch..(y + 1) * w * ch];
            line[..w * ch].copy_from_slice(row);
            box_line(&line[..w * ch], row, w, ch, ch, radius);
        }
    }
    let mut col = vec![0u8; h * ch];
    let mut out = vec![0u8; h * ch];
    for x in 0..w {
        for y in 0..h {
            col[y * ch..(y + 1) * ch].copy_from_slice(&data[(y * w + x) * ch..(y * w + x + 1) * ch]);
        }
        for _ in 0..passes {
            box_line(&col, &mut out, h, ch, ch, radius);
            col.copy_from_slice(&out);
        }
        for y in 0..h {
            data[(y * w + x) * ch..(y * w + x + 1) * ch].copy_from_slice(&col[y * ch..(y + 1) * ch]);
        }
    }
}

pub fn gaussian_blur(img: &RgbImage, radius: f32) -> RgbImage {
    let mut out = img.clone();
    let (w, h) = (img.width() as usize, img.height() as usize);
    box_blur_raw(&mut out, w, h, 3, blur_radius(radius, 3), 3);
    out
}

fn cubic(x: f32, a: f32) -> f32 {
    let x = x.abs();
    if x < 1.0 {
        ((a + 2.0) * x - (a + 3.0)) * x * x + 1.0
    } else if x < 2.0 {
        (((x - 5.0) * x + 8.0) * x - 4.0) * a
    } else {
        0.0
    }
}

pub fn sample_bicubic<const C: usize>(data: &[u8], w: usize, h: usize, x: f32, y: f32, a: f32) -> [f32; C] {
    let xf = x - 0.5;
    let yf = y - 0.5;
    let x0 = xf.floor();
    let y0 = yf.floor();
    let dx = xf - x0;
    let dy = yf - y0;
    let wx = [cubic(1.0 + dx, a), cubic(dx, a), cubic(1.0 - dx, a), cubic(2.0 - dx, a)];
    let wy = [cubic(1.0 + dy, a), cubic(dy, a), cubic(1.0 - dy, a), cubic(2.0 - dy, a)];
    let mut out = [0.0f32; C];
    for (j, wyj) in wy.iter().enumerate() {
        let yy = (y0 as i64 - 1 + j as i64).clamp(0, h as i64 - 1) as usize;
        let mut rowv = [0.0f32; C];
        for (i, wxi) in wx.iter().enumerate() {
            let xx = (x0 as i64 - 1 + i as i64).clamp(0, w as i64 - 1) as usize;
            let p = &data[(yy * w + xx) * C..(yy * w + xx + 1) * C];
            for c in 0..C {
                rowv[c] += p[c] as f32 * wxi;
            }
        }
        for c in 0..C {
            out[c] += rowv[c] * wyj;
        }
    }
    out
}

pub fn affine_rgb(img: &RgbImage, size: (u32, u32), m: [f64; 6]) -> RgbImage {
    let (w, h) = (img.width() as usize, img.height() as usize);
    let mut out = RgbImage::new(size.0, size.1);
    for oy in 0..size.1 {
        for ox in 0..size.0 {
            let (cx, cy) = (ox as f64 + 0.5, oy as f64 + 0.5);
            let sx = m[0] * cx + m[1] * cy + m[2];
            let sy = m[3] * cx + m[4] * cy + m[5];
            if sx < 0.0 || sy < 0.0 || sx >= w as f64 || sy >= h as f64 {
                continue;
            }
            let v = sample_bicubic::<3>(img.as_raw(), w, h, sx as f32, sy as f32, -1.0);
            out.put_pixel(ox, oy, Rgb([v[0], v[1], v[2]].map(|c| c.round().clamp(0.0, 255.0) as u8)));
        }
    }
    out
}

pub fn premultiply(img: &RgbaImage) -> RgbaImage {
    let mut out = img.clone();
    for p in out.pixels_mut() {
        let a = p[3] as u32;
        for c in 0..3 {
            p[c] = ((p[c] as u32 * a + 127) / 255) as u8;
        }
    }
    out
}

pub fn unpremultiply(img: &RgbaImage) -> RgbaImage {
    let mut out = img.clone();
    for p in out.pixels_mut() {
        let a = p[3] as u32;
        for c in 0..3 {
            p[c] = if a == 0 { 0 } else { ((p[c] as u32 * 255 + a / 2) / a).min(255) as u8 };
        }
    }
    out
}

pub fn affine_rgba(img: &RgbaImage, size: (u32, u32), m: [f64; 6]) -> RgbaImage {
    let (w, h) = (img.width() as usize, img.height() as usize);
    let mut out = RgbaImage::new(size.0, size.1);
    for oy in 0..size.1 {
        for ox in 0..size.0 {
            let (cx, cy) = (ox as f64 + 0.5, oy as f64 + 0.5);
            let sx = m[0] * cx + m[1] * cy + m[2];
            let sy = m[3] * cx + m[4] * cy + m[5];
            if sx < 0.0 || sy < 0.0 || sx >= w as f64 || sy >= h as f64 {
                continue;
            }
            let v = sample_bicubic::<4>(img.as_raw(), w, h, sx as f32, sy as f32, -1.0);
            out.put_pixel(ox, oy, Rgba(v.map(|c| c.round().clamp(0.0, 255.0) as u8)));
        }
    }
    out
}

pub fn paste_rgba(dst: &mut RgbaImage, src: &RgbaImage, left: i64, top: i64) {
    let (dw, dh) = (dst.width() as i64, dst.height() as i64);
    for y in 0..src.height() as i64 {
        let ty = top + y;
        if ty < 0 || ty >= dh {
            continue;
        }
        for x in 0..src.width() as i64 {
            let tx = left + x;
            if tx < 0 || tx >= dw {
                continue;
            }
            let s = *src.get_pixel(x as u32, y as u32);
            let a = s[3] as u32;
            if a == 0 {
                continue;
            }
            let d = dst.get_pixel_mut(tx as u32, ty as u32);
            if a == 255 {
                *d = s;
                continue;
            }
            let da = d[3] as u32;
            let out_a = a + da * (255 - a) / 255;
            for c in 0..3 {
                let v = (s[c] as u32 * a * 255 + d[c] as u32 * da * (255 - a)) / (out_a.max(1) * 255);
                d[c] = v.min(255) as u8;
            }
            d[3] = out_a.min(255) as u8;
        }
    }
}

pub fn to_rgba(img: &RgbImage) -> RgbaImage {
    image::DynamicImage::ImageRgb8(img.clone()).to_rgba8()
}

pub fn to_rgb(img: &RgbaImage) -> RgbImage {
    let mut out = RgbImage::new(img.width(), img.height());
    for (o, p) in out.pixels_mut().zip(img.pixels()) {
        *o = Rgb([p[0], p[1], p[2]]);
    }
    out
}
