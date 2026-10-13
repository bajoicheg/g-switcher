# CDC 2.11.1 adoption

Source: `bajoicheg/g-switcher@0b6f7e3cff9762f9508c8e42d1fd23298a496306` on `release/2.0.1`.
Canonical release: `a262f78b82cd9e8eba9bc3b6108e0b52a17c33b0`; exact package tree: `6ffacd32cce74c3537150778d9b37cfeb361a621`.
Policy migration uses strict YAML and section replacement; replay is a no-op.
Adapter and checkpoint v4 validators pass under released CDC 2.11.1.

CDC 2.11.1 process-only adoption under owner-attested recovery. The previous owner is quiescent by current user confirmation and fresh provider reconciliation. This checkpoint records the adoption invocation at integration; final adoption evidence and actual ownership release are authoritative on cdc/coordination. Product source, prior platform evidence, release gates, budget history and scheduler pause are preserved.

This update changes the CDC dependency and project policy/checkpoint only. It does not close a product implementation task or provide new Windows/Android/runtime evidence. Existing product release and acceptance gates remain unchanged. No scheduler mutation or product Compute/CI launch is part of this adoption.

Recovery evidence: `cdc/coordination@ea96130b14b81e5fb41295dbbe8346f6c8f7c579:recovery/cdc-2.11.1-owner-attestation.json`.
