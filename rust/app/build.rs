mod art {
    include!("src/art.rs");
}

fn main() {
    let out = std::path::PathBuf::from(std::env::var("OUT_DIR").unwrap());
    let ico = out.join("snapline.ico");
    let sizes = [16u32, 24, 32, 48, 64, 128, 256];
    let pngs: Vec<Vec<u8>> = sizes.iter().map(|&s| art::png(&art::make_icon(s))).collect();
    let mut data = Vec::new();
    data.extend_from_slice(&[0, 0, 1, 0]);
    data.extend_from_slice(&(sizes.len() as u16).to_le_bytes());
    let mut offset = 6 + 16 * sizes.len() as u32;
    for (s, png) in sizes.iter().zip(&pngs) {
        let side = if *s >= 256 { 0 } else { *s as u8 };
        data.extend_from_slice(&[side, side, 0, 0]);
        data.extend_from_slice(&1u16.to_le_bytes());
        data.extend_from_slice(&32u16.to_le_bytes());
        data.extend_from_slice(&(png.len() as u32).to_le_bytes());
        data.extend_from_slice(&offset.to_le_bytes());
        offset += png.len() as u32;
    }
    for png in &pngs {
        data.extend_from_slice(png);
    }
    std::fs::write(&ico, data).unwrap();
    let mut res = winresource::WindowsResource::new();
    res.set_icon(ico.to_str().unwrap());
    res.set("ProductName", "Snapline");
    res.set("FileDescription", "Snapline");
    res.set("LegalCopyright", "MIT");
    res.compile().unwrap();
    println!("cargo:rerun-if-changed=src/art.rs");
}
