# Standalone Rust XML writer proposal

Source-only staged proposal under the approved broker plan `dbe7bc09dd15a3d28e5965b2c2f6f9098d0fcaabe5de7683fcc1040317d5da43`. No product checkout, native adapter, broker, CDC, lease or remote files changed. No COM, destination, clipboard, document, IPC or network operation exists in the transformation module. Not accepted product; no Word formatting fidelity, atomicity or recovery claim.

Local rustc is unavailable. Rust test sources were written before the transformation module, but no compiled failing test has yet been observed and no TDD/RED/GREEN success is claimed. This proposal must undergo review and actual owner-hosted compiled named RED before any product integration, then exact-module GREEN, typed Windows/Clippy/full checks. Python was used only to inspect synthetic fixture well-formedness and hashes, never as a substitute transformer or product GREEN.

## API and accepted structural subset

`word_xml_plan::prepare(xml, original, replacement, fresh_binding, evidence)` returns a sealed immutable XmlPlan or a structured Refusal. It preserves the source XML byte-for-byte except changed w:t bodies. Unchanged runs retain original numeric-entity spelling. Text-node slices map exact decoded UTF16/BMP offsets across mixed runs; run properties/namespace declarations/order/attributes are preserved verbatim. Plan Debug and evidence Debug redact text/XML. No serialization of the original tree, formatting rewrite or fallback exists.

The parser is std-only and intentionally a strict QName/namespace-specific bounded subset, not a general XML library:

- At most65,536 UTF8 source/output bytes,128 UTF16 text units,64 runs,512 nodes,12 nesting levels,16 attributes/node,256 bytes/attribute value.
- One pkg:package with exact xmlPackage namespace, one `/word/document.xml` main-content part, one xmlData/document/body/paragraph, one or more ordinary runs. Fixed `pkg`/`w` prefix bindings are required; harmless alternative namespace spellings/prefixes are unsupported rather than guessed.
- Each run contains only one w:t, optionally preceded by w:rPr. Text is one nonempty ASCII-Latin/Russian-Cyrillic BMP token, equal replacement UTF16 length. No whitespace, digits, punctuation/delimiter, paragraph mark, surrogate/supplementary scalar, combining mark or controls. Separate entity parser/escape tests cover valid predefined/numeric XML entities; unsupported token characters still refuse before planning.
- Direct run-property allowlist: b/i/bCs/iCs, numeric sz/szCs, explicit RGB color, finite highlight/underline subset, explicit rFonts and lang attributes. Duplicate/unknown properties, theme attributes and style references refuse. xml:space='preserve' is preserved but actual text whitespace remains unsupported.
- No pPr/sectPr, paragraph terminator, tabs/breaks, field codes, bookmarks/comments, revision markup, content controls, drawings, hyperlink, binary part, relationships, style/theme/default/font-table/package dependency part. No DTD, PI/XML declaration, CDATA, comment, entity definition, XSLT, schema or external resource resolution. The parser rejects these before any plan.

This corresponds to a narrow possible document-part-only Flat OPC shape. **No fixture is an actual installed Word.Range.WordOpenXML capture.** The two pinned fixtures are authored synthetic shapes, clearly named. Typical real Word exports may include an XML declaration, relationship/style/theme/font/settings parts, paragraph properties, extra namespaces or implicit formatting dependencies and will be rejected. There is no evidence yet that real Word emits the accepted subset for a useful correction. Do not strip parts/declarations/styles to force acceptance: that can change meaning. Real captures must be obtained under broker ownership and reviewed before broadening the grammar.

## Effective dependency evidence: explicit unresolved integration seam

XML run properties alone cannot prove effective formatting or import behavior. Missing evidence and DependencyAssessment::Unknown refuse. Caller-supplied EffectiveDependencyEvidence must bind exact source XML, operation nonce, authenticated Word PID/birth, document/range identity, input/policy epochs, nonzero equal source/destination context fingerprints, and a nonzero measured effective-format fingerprint for every UTF16 unit. These measurements remain unchanged in the planned mapping. A mismatch refuses.

The public typed evidence is **not cryptographically authenticated or semantically established by this module**. Its `NoImplicitOrImportedDependencies` assessment is a trusted future broker seam, not a bool that clients/IPC or tests may promote into native authority. The broker must privately construct evidence from fresh owned source/destination checks; definition and measurement of complete effective context/dependency fingerprints remain unresolved. Neither identical fingerprints nor direct-run XML prove that Word import will preserve styles/defaults/themes/language/paragraph behavior. Synthetic tests use synthetic fingerprints, not mocked proof of actual Word fidelity.

Consequently XmlPlan is only a transformation proposal. It has no method granting native dispatch. The future broker must independently verify actual Word export/import/effective-format/style-scope round trips and current binding before any destination call. If a complete dependency proof for this subset cannot be implemented, remain at structured refusal. Source XML/original content are held only in memory, never logged or persisted by this module; a future native test fixture acquisition needs its own privacy scope.

## Call-sequence model and honest baseline

`contract_model.rs` and shared_contract_tests.rs are test-only interface models, never imported by the product or invoked against Word. Candidate model makes one `DestinationModel::insert_xml` submission and returns Unknown on failure, with no retry/plaintext fallback. It does not validate XML or authorize mutation; actual transformation validation is tested separately. The baseline reifies the prior per-character submission contract and fails after two completed character submissions. It is **not** original diagnostic3407 runtime code, an exact old executable or a COM atomicity experiment. Shared named tests expose multiple attempted calls/prefix and demand one candidate submission. One call may still mutate partially or hang inside Word.

Owner-hosted commands, with Rust1.98.1 selected:

```
rustc --edition=2021 --test baseline.rs -o baseline-tests
./baseline-tests tests::one_destination_attempt_even_when_destination_outcome_unknown --exact --nocapture
# Must compile first, then exit101 for an actual assertion (attempts3 versus1).
./baseline-tests baseline_model_exposes_two_completed_prefix_before_failure --exact --nocapture
# Must pass and exhibit two completed prefix characters in the model.
rustc --edition=2021 --test green_harness.rs -o proposal-tests
./proposal-tests --test-threads=1 --nocapture
# Require every manifest-listed GREEN name present and passed, never zero tests.
```

All Rust compile/test/format/Clippy outcomes are pending. No local shell command above has been run. Existing project checks are not claimed repeated; product integration and actual broker/native call tests are explicitly out of this task.

## Primary documentation examined

- [Word.Range.WordOpenXML](https://learn.microsoft.com/en-us/office/vba/api/word.range.wordopenxml): exports XML necessary to represent a range; no detached formatting or byte-stable import guarantee.
- [Word.Range.InsertXML](https://learn.microsoft.com/en-us/office/vba/api/word.range.insertxml): XML replacement within destination range; no documented ACID/cancellation/all-or-nothing guarantee.
- [Microsoft Open XML SDK WordprocessingDocument](https://learn.microsoft.com/en-us/dotnet/api/documentformat.openxml.packaging.wordprocessingdocument?view=openxml-3.0.1): Flat OPC package/string conversion support; it does not establish that the document-only fixture is an actual Word export.

The native guard, one Undo closure, fresh security/focus/protection/generation checks, persistent uncertainty and complete teardown must still wrap any future integrated destination call. Effective formatting and ordinary Word Undo/stored-original formatted Undo remain actual Word acceptance gates.
