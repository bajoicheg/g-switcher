# Release management

## Release candidate

A release starts from an exact release-candidate SHA. Record the intended semantic/project version and candidate SHA before packaging.

Verify the repository-configured release gates, typically including:

- version metadata consistency;
- full tests required for the release;
- required target-platform build;
- packaging/installability or portable-startup smoke test;
- security/signing checks when configured;
- artifact identity bound to the candidate SHA;
- checksum/hash generation when configured;
- tag/release publication evidence when configured.

A source-tree GREEN does not prove a packaged executable works. A package produced from a different SHA is not the validated release artifact.

## Sequential release lines

Do not begin the next release line merely because the previous source changes were committed. The previous release must reach its configured terminal release state (for example `released`, `published`, or an explicitly accepted blocked state) unless the repository explicitly supports parallel release trains.

After release completion, update the durable checkpoint and then advance to the next approved version/change.

## Release failure

If packaging, signing, smoke, or publication fails:

1. preserve the failing candidate/evidence;
2. diagnose the exact release stage;
3. make a bounded correction;
4. create a new candidate SHA;
5. re-run the gates invalidated by the change;
6. never reuse old release GREEN as proof for the new candidate without a documented invariant.
