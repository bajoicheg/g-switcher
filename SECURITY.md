# Security and publication policy

G-switcher is a personal, local Windows utility. Repository examples must be synthetic and must not identify an employer, customer, private infrastructure, or a user's real input.

## Reporting a vulnerability

Do not post passwords, access tokens, private keys, session cookies, real credentials, internal addresses, user lists, or unredacted screenshots in public issues, pull requests, logs, or attachments. Use GitHub's private vulnerability reporting when the repository's Security tab offers it. Otherwise, ask the maintainer to arrange a private reporting channel without including sensitive details in that request.

Use fake input and an isolated test account to reproduce keyboard-layout problems. Remove names, addresses, paths, application titles, and sensitive field contents from screenshots and diagnostics before sharing. Report the application version, Windows build, G-switcher commit or release, and minimal synthetic reproduction instead.

## Contribution checks

All pull requests run secret scanning and current-tree publication checks. Gitleaks retains its default detectors. Exact documented keyboard shortcuts and their synthetic scanner-regression representations are narrowly excepted for the generic credential rule in explicitly named paths only. No directories, historical commits, or broad token patterns are exempted. Negative regression checks prove credential-shaped values in documentation and source are still detected.

Private material and diagnostic outputs are excluded by `.gitignore`. Ignoring a file is not access control and does not remove a previously committed version. Never force-add real signing keys, environment files, credential stores, packet captures, or memory dumps.

Use a GitHub no-reply address for new Git commits. Existing Git history, release archives, issue content, build logs, and external copies require independent review; a clean current checkout does not prove those surfaces are clean.

## Exposure response

Treat a discovered issued credential as exposed. Revoke or rotate it at its provider before relying on content cleanup. Do not test a discovered credential against a live system as part of repository scanning.

Coordinate any history rewrite with the repository owner and contributors. Rewriting changes commit identities and can invalidate tags, signatures, release evidence, and pull-request references. Never claim that a normal deletion commit removes older public copies or that a scan proves no secrets exist.

The publication audit is read-only and emits redacted coordinates and coverage gaps, not secret values. A successful audit job means the scan finished, not that all candidates are benign. Findings must be reviewed and inaccessible logs, expired artifacts, image pixels, unreachable objects, and external forks must be recorded as coverage limitations.
