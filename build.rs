fn main() {
    #[cfg(windows)]
    {
        let mut resource = winres::WindowsResource::new();
        resource.set_icon("assets/g-switcher.ico");
        resource.set("FileDescription", "G-switcher");
        resource.set("ProductName", "G-switcher");
        resource.set("CompanyName", "V. Vasilev");
        resource.set("LegalCopyright", "Copyright (c) V. Vasilev 2026");
        resource.set("FileVersion", "1.0.6.0");
        resource.set("ProductVersion", "1.0.6");
        resource
            .compile()
            .expect("failed to compile Windows resources");
    }
}
