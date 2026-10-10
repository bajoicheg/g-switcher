//! Portable contracts for explicit user controls; no document or typing state.
use serde::{Deserialize, Serialize};
use std::time::{Duration, Instant};

#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub(crate) enum AppMode {
    Auto,
    ManualOnly,
    Disabled,
}
#[derive(Debug, Clone, Copy, Default, PartialEq, Eq)]
pub(crate) enum StopReason {
    #[default]
    Ready,
    Disabled,
    Secure,
    Unsupported,
    WordPending,
    WordUnknown,
    WordRefused,
}
#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub(crate) struct HostKey {
    pub(crate) pid: u32,
    pub(crate) birth: u64,
}
#[derive(Debug, Default, Clone)]
pub(crate) struct ReasonMonitor {
    current: Option<HostKey>,
    unknown: Vec<HostKey>,
    pending_word: Vec<(HostKey, u64)>,
    pub(crate) reason: StopReason,
    pub(crate) events: [u64; 7],
}
impl ReasonMonitor {
    pub(crate) fn begin_word(&mut self, host: HostKey, operation: u64) {
        if !self.pending_word.contains(&(host, operation)) {
            // The client permits one active request and one queued preparation.
            if self.pending_word.len() == 2 {
                self.pending_word.remove(0);
            }
            self.pending_word.push((host, operation));
        }
        self.record(host, StopReason::WordPending);
    }
    pub(crate) fn complete_word(
        &mut self,
        host: HostKey,
        operation: u64,
        success: bool,
        uncertain: bool,
    ) {
        self.pending_word.retain(|p| *p != (host, operation));
        self.record(
            host,
            if uncertain {
                StopReason::WordUnknown
            } else if self.pending_word.iter().any(|p| p.0 == host) {
                StopReason::WordPending
            } else if success {
                StopReason::Ready
            } else {
                StopReason::WordRefused
            },
        );
    }
    pub(crate) fn observe(&mut self, host: HostKey) {
        if self.current != Some(host) {
            self.current = Some(host);
            self.reason = if self.unknown.contains(&host) {
                StopReason::WordUnknown
            } else if self.pending_word.iter().any(|p| p.0 == host) {
                StopReason::WordPending
            } else {
                StopReason::Ready
            };
        }
    }
    pub(crate) fn record(&mut self, host: HostKey, reason: StopReason) {
        self.events[reason as usize] = self.events[reason as usize].saturating_add(1);
        if reason == StopReason::WordUnknown && !self.unknown.contains(&host) {
            self.unknown.retain(|old| old.pid != host.pid);
            if self.unknown.len() == 64 {
                self.unknown.remove(0);
            }
            self.unknown.push(host);
        }
        if self.current == Some(host)
            && (self.reason != StopReason::WordUnknown || reason == StopReason::WordUnknown)
        {
            self.reason = reason;
        }
    }
    pub(crate) fn clear_transient(&mut self) {
        if !matches!(
            self.reason,
            StopReason::WordUnknown | StopReason::WordPending | StopReason::WordRefused
        ) {
            self.reason = StopReason::Ready;
        }
    }
}
pub(crate) fn apply_app_mode(
    disabled: &mut Vec<String>,
    manual: &mut Vec<String>,
    name: &str,
    mode: AppMode,
) {
    disabled.retain(|s| !s.eq_ignore_ascii_case(name));
    manual.retain(|s| !s.eq_ignore_ascii_case(name));
    match mode {
        AppMode::Auto => {}
        AppMode::ManualOnly => manual.push(name.to_ascii_lowercase()),
        AppMode::Disabled => disabled.push(name.to_ascii_lowercase()),
    }
}

#[derive(Default)]
pub(crate) struct PauseClock {
    pub(crate) paused: bool,
    until: Option<Instant>,
}
impl PauseClock {
    pub(crate) fn set(&mut self, paused: bool) {
        self.paused = paused;
        self.until = None;
    }
    pub(crate) fn pause_for(&mut self, now: Instant, minutes: u32) {
        self.paused = true;
        self.until = now.checked_add(Duration::from_secs(u64::from(minutes) * 60));
    }
    pub(crate) fn expire(&mut self, now: Instant) -> bool {
        if self.until.is_some_and(|until| now >= until) {
            self.set(false);
            true
        } else {
            false
        }
    }
    pub(crate) fn remaining(&self, now: Instant) -> Option<Duration> {
        self.until.map(|until| until.saturating_duration_since(now))
    }
}

#[derive(Clone, Debug, Serialize, Deserialize, PartialEq, Eq)]
#[serde(deny_unknown_fields)]
pub(crate) struct SettingsBackup {
    pub(crate) schema: String,
    pub(crate) auto_correct: bool,
    pub(crate) sensitivity: String,
    pub(crate) sound_enabled: bool,
    pub(crate) sound_volume: u8,
    pub(crate) disabled_apps: Vec<String>,
    pub(crate) manual_only_apps: Vec<String>,
    pub(crate) user_words: Vec<String>,
    pub(crate) hotkeys: Vec<String>,
}
impl SettingsBackup {
    pub(crate) fn validate(&self) -> Result<(), &'static str> {
        if self.schema != "g-switcher-settings/v1" {
            return Err("Неподдерживаемый формат настроек");
        }
        if !["Conservative", "Normal", "Aggressive"].contains(&self.sensitivity.as_str())
            || self.sound_volume > 100
        {
            return Err("Некорректный профиль или громкость");
        }
        for list in [&self.disabled_apps, &self.manual_only_apps] {
            if list.len() > 512
                || list.iter().any(|p| {
                    p.len() > 260
                        || p.trim() != p
                        || !p.to_ascii_lowercase().ends_with(".exe")
                        || p.chars()
                            .any(|c| c.is_control() || "/\\;:*?\"<>|".contains(c))
                })
            {
                return Err("Некорректный список приложений");
            }
        }
        if self.user_words.len() > 4096
            || self.user_words.iter().any(|w| {
                w.is_empty()
                    || w.trim() != w
                    || w.contains(';')
                    || w.chars().count() > 256
                    || w.chars().any(char::is_control)
            })
        {
            return Err("Некорректный словарь");
        }
        if self.hotkeys.len() != 5 || self.hotkeys.iter().any(|h| h.is_empty() || h.len() > 64) {
            return Err("Некорректные горячие клавиши");
        }
        Ok(())
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    #[test]
    fn word_completion_ends_pending_without_erasing_unknown_or_other_host() {
        let host = HostKey { pid: 10, birth: 1 };
        let other = HostKey { pid: 11, birth: 2 };
        let mut monitor = ReasonMonitor::default();
        monitor.observe(host);
        monitor.record(host, StopReason::WordPending);
        monitor.complete_word(host, 1, false, false);
        assert_eq!(monitor.reason, StopReason::WordRefused);
        monitor.record(host, StopReason::WordPending);
        monitor.complete_word(host, 1, true, false);
        assert_eq!(monitor.reason, StopReason::Ready);
        monitor.record(host, StopReason::WordPending);
        monitor.complete_word(host, 1, false, true);
        assert_eq!(monitor.reason, StopReason::WordUnknown);
        monitor.complete_word(host, 1, true, false);
        assert_eq!(monitor.reason, StopReason::WordUnknown);
        monitor.observe(other);
        monitor.complete_word(host, 1, false, true);
        assert_eq!(monitor.reason, StopReason::Ready);
    }
    #[test]
    fn older_word_completion_keeps_newer_operation_pending() {
        let host = HostKey { pid: 10, birth: 1 };
        let mut monitor = ReasonMonitor::default();
        monitor.observe(host);
        monitor.begin_word(host, 1);
        monitor.begin_word(host, 2);
        monitor.complete_word(host, 1, true, false);
        assert_eq!(monitor.reason, StopReason::WordPending);
        monitor.complete_word(host, 2, true, false);
        assert_eq!(monitor.reason, StopReason::Ready);
    }
    #[test]
    fn backup_rejects_registry_separators_and_trimmed_values() {
        for name in ["private;editor.exe", " editor.exe"] {
            let mut value = backup();
            value.disabled_apps = vec![name.into()];
            assert!(value.validate().is_err(), "{name}");
        }
        for word in ["foo;bar", " word "] {
            let mut value = backup();
            value.user_words = vec![word.into()];
            assert!(value.validate().is_err(), "{word}");
        }
    }
    #[test]
    fn timed_pause_expires_once_at_its_deadline() {
        let now = Instant::now();
        let mut p = PauseClock::default();
        p.pause_for(now, 5);
        assert!(p.paused);
        assert_eq!(p.remaining(now), Some(Duration::from_secs(300)));
        assert!(!p.expire(now + Duration::from_secs(299)));
        assert!(p.expire(now + Duration::from_secs(300)));
        assert!(!p.paused);
        assert!(!p.expire(now + Duration::from_secs(301)));
    }
    #[test]
    fn manual_pause_cancels_old_timer() {
        let now = Instant::now();
        let mut p = PauseClock::default();
        p.pause_for(now, 5);
        p.set(true);
        assert!(!p.expire(now + Duration::from_secs(400)));
        assert!(p.paused);
        assert_eq!(p.remaining(now), None);
    }
    #[test]
    fn new_pause_replaces_the_previous_deadline() {
        let now = Instant::now();
        let mut p = PauseClock::default();
        p.pause_for(now, 5);
        p.pause_for(now + Duration::from_secs(60), 15);
        assert!(!p.expire(now + Duration::from_secs(300)));
        assert!(p.expire(now + Duration::from_secs(960)));
    }
    fn backup() -> SettingsBackup {
        SettingsBackup {
            schema: "g-switcher-settings/v1".into(),
            auto_correct: true,
            sensitivity: "Normal".into(),
            sound_enabled: true,
            sound_volume: 20,
            disabled_apps: vec!["winword.exe".into()],
            manual_only_apps: vec![],
            user_words: vec!["Градиент".into()],
            hotkeys: vec![
                "Ctrl+Shift+F9",
                "Ctrl+Shift+F12",
                "Ctrl+Shift+F10",
                "Ctrl+Backspace",
                "Ctrl+Shift+F11",
            ]
            .into_iter()
            .map(str::to_string)
            .collect(),
        }
    }
    #[test]
    fn backup_roundtrip_preserves_explicit_configuration() {
        let b = backup();
        let restored: SettingsBackup =
            toml::from_str(&toml::to_string_pretty(&b).unwrap()).unwrap();
        assert_eq!(restored, b);
        assert!(restored.validate().is_ok());
    }
    #[test]
    fn invalid_backup_is_rejected_before_any_application() {
        let mut b = backup();
        b.schema = "future/v99".into();
        assert!(b.validate().is_err());
        b = backup();
        b.sound_volume = 101;
        assert!(b.validate().is_err());
        b = backup();
        b.disabled_apps = vec!["C:\\secret\\word.exe".into()];
        assert!(b.validate().is_err());
        b = backup();
        b.user_words = vec!["x".repeat(257)];
        assert!(b.validate().is_err());
        b = backup();
        b.hotkeys.pop();
        assert!(b.validate().is_err());
    }
    #[test]
    fn backup_rejects_implicit_autostart_or_extra_fields() {
        let text = toml::to_string_pretty(&backup()).unwrap();
        assert!(toml::from_str::<SettingsBackup>(&format!("autostart = true\n{text}")).is_err());
    }
    #[test]
    fn app_mode_changes_remove_conflicts_and_preserve_other_apps() {
        let mut disabled = vec!["WINWORD.EXE".into(), "chrome.exe".into()];
        let mut manual = vec!["winword.exe".into(), "code.exe".into()];
        apply_app_mode(
            &mut disabled,
            &mut manual,
            "winword.exe",
            AppMode::ManualOnly,
        );
        assert_eq!(disabled, ["chrome.exe"]);
        assert_eq!(manual, ["code.exe", "winword.exe"]);
        apply_app_mode(&mut disabled, &mut manual, "winword.exe", AppMode::Disabled);
        assert_eq!(disabled, ["chrome.exe", "winword.exe"]);
        assert_eq!(manual, ["code.exe"]);
        apply_app_mode(&mut disabled, &mut manual, "winword.exe", AppMode::Auto);
        assert_eq!(disabled, ["chrome.exe"]);
        assert_eq!(manual, ["code.exe"]);
    }
    #[test]
    fn uncertain_word_status_survives_other_apps_and_pending_requests() {
        let word = HostKey { pid: 10, birth: 1 };
        let chrome = HostKey { pid: 11, birth: 2 };
        let mut monitor = ReasonMonitor::default();
        monitor.observe(word);
        monitor.record(word, StopReason::WordUnknown);
        assert_eq!(monitor.reason, StopReason::WordUnknown);
        monitor.clear_transient();
        monitor.record(word, StopReason::WordPending);
        assert_eq!(monitor.reason, StopReason::WordUnknown);
        monitor.observe(chrome);
        assert_eq!(monitor.reason, StopReason::Ready);
        monitor.observe(word);
        assert_eq!(monitor.reason, StopReason::WordUnknown);
        monitor.observe(HostKey {
            pid: word.pid,
            birth: 3,
        });
        assert_eq!(monitor.reason, StopReason::Ready);
    }
    #[test]
    fn late_word_result_does_not_replace_another_apps_status() {
        let word = HostKey { pid: 10, birth: 1 };
        let chrome = HostKey { pid: 11, birth: 2 };
        let mut monitor = ReasonMonitor::default();
        monitor.observe(chrome);
        monitor.record(chrome, StopReason::Secure);
        monitor.record(word, StopReason::WordUnknown);
        assert_eq!(monitor.reason, StopReason::Secure);
        assert_eq!(monitor.events[StopReason::WordUnknown as usize], 1);
        monitor.observe(word);
        assert_eq!(monitor.reason, StopReason::WordUnknown);
    }
    #[test]
    fn ordinary_stop_reasons_clear_when_context_is_rechecked() {
        let host = HostKey { pid: 1, birth: 2 };
        for reason in [
            StopReason::Disabled,
            StopReason::Secure,
            StopReason::Unsupported,
        ] {
            let mut monitor = ReasonMonitor::default();
            monitor.observe(host);
            monitor.record(host, reason);
            assert_eq!(monitor.reason, reason);
            monitor.clear_transient();
            assert_eq!(monitor.reason, StopReason::Ready);
        }
        let mut monitor = ReasonMonitor::default();
        monitor.observe(host);
        monitor.record(host, StopReason::WordRefused);
        monitor.clear_transient();
        assert_eq!(monitor.reason, StopReason::WordRefused);
    }
}
