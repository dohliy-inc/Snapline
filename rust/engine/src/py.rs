pub fn round(x: f64) -> i64 {
    x.round_ties_even() as i64
}

pub fn round_to(x: f64, digits: i32) -> f64 {
    let k = 10f64.powi(digits);
    let y = (x * k).round_ties_even() / k;
    if y == 0.0 { 0.0 } else { y }
}

pub fn median(values: &[f64]) -> f64 {
    if values.is_empty() {
        return f64::NAN;
    }
    let mut v = values.to_vec();
    v.sort_by(|a, b| a.total_cmp(b));
    let n = v.len();
    if n % 2 == 1 { v[n / 2] } else { (v[n / 2 - 1] + v[n / 2]) / 2.0 }
}

pub fn runs(mask: impl IntoIterator<Item = bool>) -> Vec<(usize, usize)> {
    let mut out = Vec::new();
    let mut start = None;
    let mut i = 0;
    for on in mask {
        match (on, start) {
            (true, None) => start = Some(i),
            (false, Some(a)) => {
                out.push((a, i - 1));
                start = None;
            }
            _ => {}
        }
        i += 1;
    }
    if let Some(a) = start {
        out.push((a, i - 1));
    }
    out
}

pub fn u8c(x: f32) -> u8 {
    x.round_ties_even().clamp(0.0, 255.0) as u8
}

pub fn modulo(a: f64, b: f64) -> f64 {
    let r = a % b;
    if r != 0.0 && (r < 0.0) != (b < 0.0) { r + b } else { r }
}
