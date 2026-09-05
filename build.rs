fn main() {
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
