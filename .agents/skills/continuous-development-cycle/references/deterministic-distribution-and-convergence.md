# CDC 2.9.0 — Deterministic Distribution & Convergence

## Package transport is not a trust boundary

CDC release provenance stays in the canonical source, but package delivery may use any least-privilege carrier that can deliver the package directory plus a transport manifest. The carrier is not trusted for release identity.

A trusted consumer binding supplies the expected stable version, immutable release commit and exact package Git tree. scripts/package_transport.py validates that binding first. The manifest then binds every relative path to its Git file mode, blob SHA-1 and byte length and reconstructs the exact Git tree. Transported bytes are checked against those blob identities. After adoption, the actual vendored Git subtree is compared to the same package tree.

A content-only archive that loses Git mode metadata is therefore insufficient by itself. Mode and object identity come from the manifest, and adoption fails closed if the resulting subtree differs from the trusted package tree.

## Canonical convergence vector

scripts/convergence_vector.py normalizes one project observation into a comparable vector containing repository/source ref, exact source HEAD, CDC version, exact package tree, consumer release identity, semantic policy digest, checkpoint validity and binding, lease state, guard state and adoption state.

Integrated is a proof state, not a label. It requires all exact bindings to agree on the same source HEAD, a valid checkpoint, reconciled owner state and no unresolved guard. A version string alone can never produce integrated state.

## CI evidence classification

scripts/ci_evidence_classifier.py classifies evidence before remediation:

- pre_run_infrastructure — no job or zero executable steps; recover/fail over the execution channel;
- setup — job started but product validation did not; repair setup or recover the channel;
- product_test — product validation executed; only concrete product failure evidence can permit product/test correction;
- terminal_success — product validation completed successfully.

No source change is justified solely by a pre-run or setup failure. Classification is diagnostic only and grants no product write, external start, takeover, merge or release authority.
