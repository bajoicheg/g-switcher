pub fn is_code_safe_token(token: &str) -> bool {
    let t = token.trim();
    if t.len() < 2 {
        return false;
    }

    looks_like_url_or_email(t)
        || looks_like_path(t)
        || looks_like_ip_or_cidr(t)
        || looks_like_guid(t)
        || looks_like_hash(t)
        || looks_like_identifier(t)
        || looks_like_switch(t)
}

fn looks_like_url_or_email(t: &str) -> bool {
    t.contains("://") || (t.contains('@') && t.contains('.'))
}

fn looks_like_path(t: &str) -> bool {
    t.starts_with('/')
        || t.starts_with("\\\\")
        || (t.len() >= 3 && t.as_bytes()[1] == b':' && matches!(t.as_bytes()[2], b'\\' | b'/'))
}

fn looks_like_ip_or_cidr(t: &str) -> bool {
    let (ip, prefix) = match t.split_once('/') {
        Some((ip, prefix)) if prefix.chars().all(|c| c.is_ascii_digit()) => (ip, true),
        _ => (t, false),
    };
    let parts: Vec<_> = ip.split('.').collect();
    parts.len() == 4
        && parts
            .iter()
            .all(|p| !p.is_empty() && p.parse::<u8>().is_ok())
        && (!prefix || t.rsplit('/').next().is_some())
}

fn looks_like_guid(t: &str) -> bool {
    let groups: Vec<_> = t.split('-').collect();
    let lens = [8, 4, 4, 4, 12];
    groups.len() == lens.len()
        && groups
            .iter()
            .zip(lens)
            .all(|(g, len)| g.len() == len && g.chars().all(|c| c.is_ascii_hexdigit()))
}

fn looks_like_hash(t: &str) -> bool {
    let candidate = t.split_once(':').map(|(_, rhs)| rhs).unwrap_or(t);
    candidate.len() >= 16 && candidate.chars().all(|c| c.is_ascii_hexdigit())
}

fn looks_like_identifier(t: &str) -> bool {
    let has_alpha = t.chars().any(|c| c.is_ascii_alphabetic());
    let has_digit = t.chars().any(|c| c.is_ascii_digit());
    let snake = t.contains('_');
    let camel = t.chars().skip(1).any(|c| c.is_ascii_uppercase());
    (has_alpha && has_digit) || snake || camel
}

fn looks_like_switch(t: &str) -> bool {
    t.starts_with("--") || (t.starts_with('-') && t.len() > 2)
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn protects_technical_tokens() {
        for token in [
            "HOST-SRV-01",
            "10.20.30.40",
            "10.20.0.0/16",
            "C:\\Windows\\System32",
            "/usr/local/bin",
            "user@example.test",
            "https://example.test/path",
            "550e8400-e29b-41d4-a716-446655440000",
            "sha256:abcdef0123456789",
            "SomeVariable42",
            "some_variable",
            "--background",
        ] {
            assert!(is_code_safe_token(token), "not protected: {token}");
        }
    }

    #[test]
    fn ordinary_words_are_not_code_safe() {
        for token in ["hello", "привет", "ghbdtn", "руддщ", "беру"] {
            assert!(!is_code_safe_token(token), "unexpected protection: {token}");
        }
    }
}
