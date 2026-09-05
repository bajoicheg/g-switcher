use std::mem::size_of;

const SAMPLE_RATE: u32 = 24_000;
const DURATION_MS: u32 = 72;
const FREQUENCY_HZ: f32 = 880.0;
const PEAK_AMPLITUDE: f32 = i16::MAX as f32 * 0.42;

pub(crate) const DEFAULT_SOUND_VOLUME: u8 = 20;
pub(crate) const MAX_SOUND_VOLUME: u8 = 100;

pub(crate) fn correction_wav(volume: u8) -> Vec<u8> {
    let volume = volume.min(MAX_SOUND_VOLUME);
    let sample_count = SAMPLE_RATE * DURATION_MS / 1_000;
    let data_len = sample_count * size_of::<i16>() as u32;
    let mut wave = Vec::with_capacity(44 + data_len as usize);

    wave.extend_from_slice(b"RIFF");
    wave.extend_from_slice(&(36 + data_len).to_le_bytes());
    wave.extend_from_slice(b"WAVEfmt ");
    wave.extend_from_slice(&16u32.to_le_bytes());
    wave.extend_from_slice(&1u16.to_le_bytes());
    wave.extend_from_slice(&1u16.to_le_bytes());
    wave.extend_from_slice(&SAMPLE_RATE.to_le_bytes());
    wave.extend_from_slice(&(SAMPLE_RATE * size_of::<i16>() as u32).to_le_bytes());
    wave.extend_from_slice(&(size_of::<i16>() as u16).to_le_bytes());
    wave.extend_from_slice(&16u16.to_le_bytes());
    wave.extend_from_slice(b"data");
    wave.extend_from_slice(&data_len.to_le_bytes());

    let fade_samples = (SAMPLE_RATE / 125).max(1);
    let gain = f32::from(volume) / f32::from(MAX_SOUND_VOLUME);
    for index in 0..sample_count {
        let attack = (index as f32 / fade_samples as f32).min(1.0);
        let remaining = sample_count.saturating_sub(index + 1);
        let release = (remaining as f32 / fade_samples as f32).min(1.0);
        let envelope = attack.min(release);
        let phase = std::f32::consts::TAU * FREQUENCY_HZ * index as f32 / SAMPLE_RATE as f32;
        let sample = (phase.sin() * PEAK_AMPLITUDE * gain * envelope) as i16;
        wave.extend_from_slice(&sample.to_le_bytes());
    }

    wave
}

#[cfg(test)]
mod tests {
    use super::*;

    fn peak(wave: &[u8]) -> u16 {
        let (samples, remainder) = wave[44..].as_chunks::<2>();
        assert!(remainder.is_empty());
        samples
            .iter()
            .map(|bytes| i16::from_le_bytes([bytes[0], bytes[1]]).unsigned_abs())
            .max()
            .unwrap_or(0)
    }

    #[test]
    fn builds_valid_short_pcm_wave() {
        let wave = correction_wav(DEFAULT_SOUND_VOLUME);
        assert_eq!(&wave[0..4], b"RIFF");
        assert_eq!(&wave[8..12], b"WAVE");
        assert_eq!(&wave[36..40], b"data");
        assert_eq!(
            wave.len(),
            44 + (SAMPLE_RATE * DURATION_MS / 1_000 * 2) as usize
        );
    }

    #[test]
    fn volume_scales_amplitude_and_is_clamped() {
        assert_eq!(peak(&correction_wav(0)), 0);
        let quiet = peak(&correction_wav(20));
        let loud = peak(&correction_wav(100));
        assert!(quiet > 0);
        assert!(loud > quiet * 4);
        assert_eq!(correction_wav(101), correction_wav(100));
    }
}
