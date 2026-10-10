//! G-switcher core interfaces.
//! Runtime modules are developed against the functional specification and
//! acceptance matrix in `docs/`.

pub mod code_safe;
pub mod detector;
pub mod frequency_model;
mod frequent_forms;
pub mod layout;
pub mod model;
mod sound_wave;
pub mod state;
pub mod undo;

#[cfg(windows)]
#[path = "windows_runtime_v201.rs"]
pub mod windows_runtime;

pub const PRODUCT_NAME: &str = "G-switcher";
pub const PRODUCT_VERSION: &str = env!("CARGO_PKG_VERSION");

#[cfg(any(windows, test))]
#[path = "windows_runtime/word_candidate.rs"]
pub(crate) mod word_candidate;

#[cfg(any(windows, test))]
#[path = "windows_runtime/word_wire.rs"]
pub(crate) mod word_wire;
