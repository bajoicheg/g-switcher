//! G-switcher core interfaces for the 0.6 implementation line.
//! Runtime modules are developed against the functional specification and
//! acceptance matrix in `docs/`.

pub mod code_safe;
pub mod detector;
pub mod layout;
pub mod model;
pub mod state;
pub mod undo;

pub const PRODUCT_NAME: &str = "G-switcher";
pub const PRODUCT_VERSION: &str = "0.6.0-rc2";
