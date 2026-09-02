#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum Language {
    Russian,
    English,
}

#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum Decision {
    Keep,
    CorrectTo(Language),
}

#[derive(Debug, Clone, PartialEq, Eq)]
pub struct CorrectionRecord {
    pub original: String,
    pub corrected: String,
    pub source: Language,
    pub target: Language,
}

impl CorrectionRecord {
    pub fn new(original: String, corrected: String, source: Language, target: Language) -> Self {
        Self { original, corrected, source, target }
    }
}
