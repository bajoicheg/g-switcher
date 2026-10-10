# Prepared usability controls

This owner-approved batch extends the existing 2.0.1 tray/settings flows. It does
not establish Word compatibility, repair native Word mutation, or authorize
public release. Windows execution and independent review remain pending.

## Behavior and acceptance

| Control | Expected behavior |
| --- | --- |
| Stop reason | Show disabled, secure, unsupported, Word pending, uncertain or unconfirmed states. A late Word observation cannot overwrite another process's status. Unknown status binds PID and process creation time and survives app switching. Status is presentation only and never admits a provider write. |
| Application mode | The menu names the captured foreground application. Auto/manual/disabled choices reuse existing executable-basename policy. Revalidate PID, creation time and basename before applying; a closed/replaced process produces an error. Other app rules remain intact. Explorer/tray focus uses the last observed application snapshot; no keyboard input is needed to capture it. |
| Diagnostics | Explicit Save dialog exports version, source build fingerprint, capture time, current mode/reason codes, category counters and configuration counts. No typing, selected text, document contents/names, application names/paths, dictionary words or raw logs are exported. Nothing is sent over the network. |
| Settings transfer | Explicit TOML save/open dialogs include all five hotkeys, sensitivity, sound, app exceptions and explicitly configured dictionary words. Import requires confirmation, validates schema/fields/hotkeys/limits before registry writes, and attempts to restore the prior configuration on a save error. This is not a crash-atomic registry transaction. Autostart, onboarding, pause and Word admission state are excluded. |
| Timed pause | Pause for 5/15/30 minutes, with rounded-up remaining time in the tooltip. Explicit pause/resume cancels the old timer; a new timed pause replaces it. Deadline uses a monotonic clock. Expiration invalidates transient typing state and leaves all Word admission/unknown state intact. Pause is not persisted. |

Mode codes: `0` auto, `1` manual only, `2` disabled. Reason codes and
`event_counts` positions: `0` ready, `1` disabled, `2` secure, `3` unsupported,
`4` Word pending, `5` Word unknown, `6` Word unconfirmed. Counters describe
observations, not the number of text mutations. The bounded status cache is
volatile; the existing independent persistent Word guard remains authoritative.

Settings format is `g-switcher-settings/v1`. Import rejects unknown fields and
files over 1 MiB. Limits: 512 entries per application list, 4096 dictionary
entries, 256 characters per word, exactly five parseable distinct hotkeys,
volume 0–100 and a known sensitivity profile.
Application and dictionary entries containing semicolons or surrounding
whitespace are rejected because the existing registry reader treats these as
separators/trimmed data. Quick application controls reject such executable names
before a write. Terminal Word replies, including Undo or a stale successful
reply, end the presentation-only pending status. Cancelled preparation is
unconfirmed; a lost transport reply is unknown. Neither observation changes
Word admission or authorizes a retry.

## Validation still required

Run the existing full Windows Rust CI on the exact frozen candidate, including
all native input/browser/failure/security/artifact gates. Obtain ordered
independent requirements and quality reviews. On a real Windows desktop check
the menu snapshot during focus changes, a target closing while its menu is open,
file-dialog cancel/error/overwrite, confirmed import and restored hotkeys, timed
pause expiry and manual cancellation. Verify secure fields remain untouched and
that neither a mode change nor timer expiry permits a second unknown Word write.

These checks supplement the existing real Word/browser acceptance matrix; they
do not replace it.
