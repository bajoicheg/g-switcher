# CDC 2.8 publication safety

Secret scanning is necessary but not sufficient for a private-to-public transition.

Use `scripts/sensitive_context.py` with project policy to detect organization literals, internal domain suffixes and private IP addresses. Example/test documentation domains can be explicitly allowed. This scanner complements Gitleaks or equivalent credential scanners; it does not replace them.

Use `scripts/publication_guard.py` against an inventory that covers:

- current tree text;
- every ref that would become reachable;
- pull-request/issue/review conversation text;
- release/workflow artifacts and metadata.

Direct publication is blocked when sensitive-context findings exist, when operational control-plane paths are present, or when coordination/backup/migration refs would be exposed. The safe default is a sanitized export with new public history rather than toggling visibility on an internal development repository.

The publication assessment is evidence only. It never authorizes the visibility change itself.
