//! Lossless unsigned identities for the build-bound broker TOML protocol.
//! TOML integers are signed; strings preserve every random epoch/nonce bit.

pub(crate) mod u64_value {
    use serde::{Deserialize, Deserializer, Serializer};

    pub(crate) fn serialize<S: Serializer>(value: &u64, serializer: S) -> Result<S::Ok, S::Error> {
        serializer.serialize_str(&format!("{value:016x}"))
    }

    pub(crate) fn deserialize<'de, D: Deserializer<'de>>(deserializer: D) -> Result<u64, D::Error> {
        let text = String::deserialize(deserializer)?;
        if text.len() != 16
            || !text
                .bytes()
                .all(|byte| byte.is_ascii_digit() || (b'a'..=b'f').contains(&byte))
        {
            return Err(serde::de::Error::custom("invalid broker unsigned identity"));
        }
        u64::from_str_radix(&text, 16).map_err(serde::de::Error::custom)
    }
}

#[cfg(test)]
mod tests {
    use super::u64_value;

    #[derive(Debug, PartialEq, serde::Serialize, serde::Deserialize)]
    struct Identity {
        #[serde(with = "u64_value")]
        value: u64,
    }

    #[test]
    fn broker_wire_preserves_full_u64_range() {
        for value in [0, 1, i64::MAX as u64, (i64::MAX as u64) + 1, u64::MAX] {
            let original = Identity { value };
            let encoded = toml::to_string(&original).unwrap();
            let decoded: Identity = toml::from_str(&encoded).unwrap();
            assert_eq!(decoded, original);
        }
    }

    #[test]
    fn broker_wire_rejects_invalid_u64_strings() {
        for value in [
            "",
            "0",
            "fffffffffffffffff",
            "FFFFFFFFFFFFFFFF",
            "+000000000000001",
            "-000000000000001",
            "000000000000000g",
        ] {
            let encoded = format!("value = {value:?}");
            assert!(
                toml::from_str::<Identity>(&encoded).is_err(),
                "accepted {value:?}"
            );
        }
    }

    #[test]
    fn broker_wire_rejects_signed_and_integer_u64_fields() {
        for encoded in ["value = -1", "value = 1", "value = 1.0", "value = true"] {
            assert!(
                toml::from_str::<Identity>(encoded).is_err(),
                "accepted {encoded}"
            );
        }
    }
}
