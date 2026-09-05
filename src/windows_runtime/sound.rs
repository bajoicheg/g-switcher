use std::ptr::null_mut;
use std::sync::OnceLock;

use windows_sys::Win32::Media::Audio::{PlaySoundW, SND_ASYNC, SND_MEMORY, SND_NODEFAULT};

use crate::sound_wave::{correction_wav, MAX_SOUND_VOLUME};

use super::settings::RuntimeSettings;

static CORRECTION_SOUNDS: OnceLock<Vec<Vec<u8>>> = OnceLock::new();

pub fn play_correction(runtime: &RuntimeSettings) {
    if !runtime.sound_enabled || runtime.sound_volume == 0 {
        return;
    }

    let volume = runtime.sound_volume.min(MAX_SOUND_VOLUME);
    let sounds = CORRECTION_SOUNDS.get_or_init(|| {
        (0..=MAX_SOUND_VOLUME)
            .map(correction_wav)
            .collect::<Vec<_>>()
    });
    let wave = &sounds[usize::from(volume)];

    unsafe {
        PlaySoundW(
            wave.as_ptr().cast::<u16>(),
            null_mut(),
            SND_ASYNC | SND_MEMORY | SND_NODEFAULT,
        );
    }
}
