#[derive(Debug, Clone, Default, PartialEq, Eq)]
pub struct CandidateState {
    chars: Vec<char>,
}

impl CandidateState {
    pub fn new() -> Self {
        Self::default()
    }

    pub fn push(&mut self, ch: char) {
        self.chars.push(ch);
    }

    pub fn backspace(&mut self) -> Option<char> {
        self.chars.pop()
    }

    pub fn clear(&mut self) {
        self.chars.clear();
    }

    pub fn text(&self) -> String {
        self.chars.iter().collect()
    }

    pub fn is_empty(&self) -> bool {
        self.chars.is_empty()
    }

    pub fn len(&self) -> usize {
        self.chars.len()
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn backspace_reconstructs_candidate() {
        let mut state = CandidateState::new();
        for ch in "ghbdtn/".chars() {
            state.push(ch);
        }
        assert_eq!(state.backspace(), Some('/'));
        assert_eq!(state.text(), "ghbdtn");
    }

    #[test]
    fn multiple_backspaces_are_reversible_until_empty() {
        let mut state = CandidateState::new();
        for ch in "abc".chars() {
            state.push(ch);
        }
        assert_eq!(state.backspace(), Some('c'));
        assert_eq!(state.backspace(), Some('b'));
        assert_eq!(state.backspace(), Some('a'));
        assert_eq!(state.backspace(), None);
        assert!(state.is_empty());
    }
}
