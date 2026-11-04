fn main() {
    // Bind broker handshake to the exact compiled source inputs, including dirty staged tests.
    use std::io::Write;
    fn collect(path: &std::path::Path, files: &mut Vec<std::path::PathBuf>) {
        for entry in std::fs::read_dir(path).expect("source directory") {
            let path = entry.expect("source entry").path();
            if path.is_dir() {
                collect(&path, files);
            } else {
                files.push(path);
            }
        }
    }
    let mut files = Vec::new();
    collect(std::path::Path::new("src"), &mut files);
    files.extend(["Cargo.toml", "Cargo.lock", "build.rs"].map(std::path::PathBuf::from));
    files.sort();
    let mut manifest = String::new();
    for file in files {
        println!("cargo:rerun-if-changed={}", file.display());
        let output = std::process::Command::new("git")
            .args(["hash-object", "--"])
            .arg(&file)
            .output()
            .expect("Git source identity");
        assert!(output.status.success());
        let hash = String::from_utf8(output.stdout).expect("Git hash UTF8");
        manifest.push_str(&format!("{}:{}\n", file.display(), hash.trim()));
    }
    let mut child = std::process::Command::new("git")
        .args(["hash-object", "--stdin"])
        .stdin(std::process::Stdio::piped())
        .stdout(std::process::Stdio::piped())
        .spawn()
        .expect("Git identity digest");
    child
        .stdin
        .take()
        .expect("identity stdin")
        .write_all(manifest.as_bytes())
        .expect("identity manifest");
    let output = child.wait_with_output().expect("identity digest");
    assert!(output.status.success());
    let hash = String::from_utf8(output.stdout).expect("identity UTF8");
    let hash = hash.trim();
    assert!(hash.len() == 40 && hash.bytes().all(|b| b.is_ascii_hexdigit()));
    println!("cargo:rustc-env=GSWITCHER_BROKER_BUILD_ID={hash}");
    #[cfg(windows)]
    {
        let version =
            std::env::var("CARGO_PKG_VERSION").expect("CARGO_PKG_VERSION is always set by Cargo");
        let file_version = format!("{version}.0");
        let mut resource = winres::WindowsResource::new();
        resource.set_icon("assets/g-switcher.ico");
        resource.set("FileDescription", "G-switcher");
        resource.set("ProductName", "G-switcher");
        resource.set("CompanyName", "V. Vasilev");
        resource.set("LegalCopyright", "Copyright (c) V. Vasilev 2026");
        resource.set("FileVersion", &file_version);
        resource.set("ProductVersion", &version);
        resource
            .compile()
            .expect("failed to compile Windows resources");
    }
}
