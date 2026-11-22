use engine::styles;
use image::{Rgb, RgbImage};

#[test]
fn grain_is_off_unless_asked() {
    let flat = RgbImage::from_pixel(64, 64, Rgb([120, 120, 120]));
    assert_eq!(styles::grain(flat.clone(), 0.0), flat);
    let grainy = styles::grain(flat, 15.0);
    let d: Vec<f64> = grainy.pixels().map(|p| p[0] as f64 - 120.0).collect();
    let sd = (d.iter().map(|v| v * v).sum::<f64>() / d.len() as f64).sqrt();
    assert!((1.0..2.0).contains(&sd), "grain 15 gave sd {sd}");
    assert!(grainy.pixels().all(|p| p[0] == p[1] && p[1] == p[2]));
}
