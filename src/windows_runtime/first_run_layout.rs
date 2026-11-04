//! First-run vertical flow driven by measured text, in client pixels.

#[derive(Debug)]
pub struct Layout {
    pub description_height: i32,
    pub separator: i32,
    pub examples_header: i32,
    pub examples: i32,
    pub undo_header: i32,
    pub undo: i32,
    pub undo_height: i32,
    pub settings_header: i32,
    pub settings_hint: i32,
    pub settings_height: i32,
    pub footer_separator: i32,
    pub autostart: i32,
    pub sound: i32,
    pub button: i32,
    pub footer: i32,
    pub client_height: i32,
}

impl Layout {
    pub fn new(description_height: i32, undo_height: i32, settings_height: i32) -> Self {
        let description_height = description_height.max(72);
        let separator = 78 + description_height + 20;
        let examples_header = separator + 24;
        let examples = examples_header + 28;
        let undo_header = examples + 42;
        let undo = undo_header + 28;
        let undo_height = undo_height.max(44);
        let settings_header = undo + undo_height + 18;
        let settings_hint = settings_header + 28;
        let settings_height = settings_height.max(52);
        let footer_separator = settings_hint + settings_height + 20;
        let autostart = footer_separator + 18;
        let sound = autostart + 38;
        let button = sound + 48;
        let footer = button + 10;
        Self {
            description_height,
            separator,
            examples_header,
            examples,
            undo_header,
            undo,
            undo_height,
            settings_header,
            settings_hint,
            settings_height,
            footer_separator,
            autostart,
            sound,
            button,
            footer,
            client_height: button + 38 + 24,
        }
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    fn assert_fits(measured: [i32; 3]) {
        let l = Layout::new(measured[0], measured[1], measured[2]);
        assert!(l.description_height >= measured[0]);
        assert!(l.undo_height >= measured[1]);
        assert!(l.settings_height >= measured[2]);
        assert!(78 + l.description_height < l.separator);
        assert!(l.undo + l.undo_height < l.settings_header);
        assert!(l.settings_hint + l.settings_height < l.footer_separator);
        assert!(l.footer_separator + 2 < l.autostart);
        assert!(l.autostart + 28 < l.sound);
        assert!(l.sound + 28 < l.button);
        assert!(l.footer + 24 <= l.client_height);
        assert!(l.button + 38 < l.client_height);
    }

    #[test]
    fn two_line_management_hint_has_clearance() {
        // Screenshot regression: a 36px box clipped the second 21px line.
        assert_fits([63, 42, 42]);
    }

    #[test]
    fn larger_fonts_and_extra_wrapping_move_every_later_section() {
        for measured in [[84, 56, 56], [108, 96, 96], [144, 120, 160]] {
            assert_fits(measured);
        }
    }

    #[test]
    fn each_expanded_text_block_moves_the_footer_by_its_extra_height() {
        let base = Layout::new(72, 44, 52);
        assert_eq!(Layout::new(92, 44, 52).button - base.button, 20);
        assert_eq!(Layout::new(72, 64, 52).button - base.button, 20);
        assert_eq!(Layout::new(72, 44, 72).button - base.button, 20);
    }
}
