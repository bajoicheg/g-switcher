use crate::model::CorrectionRecord;

#[derive(Debug, Clone, Default, PartialEq, Eq)]
pub struct UndoState {
    record: Option<CorrectionRecord>,
    focus_token: Option<u64>,
}

impl UndoState {
    pub fn arm(&mut self, record: CorrectionRecord, focus_token: u64) {
        self.record = Some(record);
        self.focus_token = Some(focus_token);
    }

    pub fn invalidate(&mut self) {
        self.record = None;
        self.focus_token = None;
    }

    pub fn take_if_compatible(&mut self, focus_token: u64) -> Option<CorrectionRecord> {
        if self.focus_token == Some(focus_token) {
            self.focus_token = None;
            self.record.take()
        } else {
            self.invalidate();
            None
        }
    }

    pub fn is_armed(&self) -> bool {
        self.record.is_some()
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    use crate::model::Language;

    fn record() -> CorrectionRecord {
        CorrectionRecord::new(
            "ghbdtn".to_owned(),
            "привет".to_owned(),
            Language::English,
            Language::Russian,
        )
    }

    #[test]
    fn undo_is_one_shot_for_same_focus() {
        let mut state = UndoState::default();
        state.arm(record(), 42);
        assert!(state.take_if_compatible(42).is_some());
        assert!(!state.is_armed());
        assert!(state.take_if_compatible(42).is_none());
    }

    #[test]
    fn focus_change_invalidates_undo() {
        let mut state = UndoState::default();
        state.arm(record(), 42);
        assert!(state.take_if_compatible(43).is_none());
        assert!(!state.is_armed());
    }
}
