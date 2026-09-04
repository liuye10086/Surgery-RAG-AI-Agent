# Operator remediation provenance hardening report

## Scope

Hardened approved-standard provenance only. No medical standard content, model or release configuration, reference releases, or historical reports were changed.

## RED evidence

The focused regression command failed with seven expected provenance defects before production edits:

- approved runtime preflight accepted zero or duplicate database rules for an approved manifest entry;
- importer accepted duplicate database manifest entry IDs, skipped unbound existing rules, and accepted mismatched existing bindings;
- repair planning accepted a document whose on-disk SHA-256 differed from the approved manifest hash;
- readonly checking had no version-to-standard ownership field.

The focused lifecycle regression also failed before its production edit: approval continued despite a source-binding validation failure.

## GREEN evidence

`python -m pytest -q backend/tests/test_standard_source_binding.py backend/tests/test_standard_manifest_import.py backend/tests/test_standard_manifest.py scripts/tests/test_apply_standard_manifest.py scripts/tests/test_bind_standard_rule_sources.py scripts/tests/test_check_operator_report_evidence_readonly.py backend/tests/test_standard_evidence_service.py backend/tests/test_evidence_bundle_service.py backend/tests/test_operator_catalog_and_reports_api.py backend/tests/test_standard_lifecycle.py`

Result: `112 passed`.

The suite emitted five existing framework deprecation warnings (Pydantic and FastAPI); no test failures or errors occurred.

## Controls added

- One shared full four-field locator tuple now governs both segment resolution and runtime source-binding validation, including fields explicitly expected to be null.
- Approved runtime preflight requires an exact one-to-one rule entry-ID set between the manifest and current version.
- Manifest import maps existing rule entry IDs, rejects duplicates before writes, and only skips an existing rule after its deterministic source binding is verified or safely completed.
- Publication now performs the same complete approved-manifest binding validation before changing version status or the current pointer.
- Repair planning hashes the actual standard document file before returning an apply plan.
- The readonly checker records and requires version ownership by the selected standard.

## Risks and operational notes

- Publication of legacy or manually-created review versions without a complete approved manifest binding now fails closed; repair or re-import is required before approval.
- The repair command remains transaction-neutral until its explicit apply mode; no repair was run here.
- Error paths use stable codes or generic messages and do not output document paths, document text, database URLs, or patient data.

## Follow-up review remediation

### RED evidence

The focused import and repair command failed with seven expected cases before the follow-up production edits:

- a cross-owned current-version pointer was accepted by repair planning;
- repair planning accepted duplicate, missing, extra, and null/untracked database manifest entry IDs;
- import accepted null and unknown existing manifest entry IDs and proceeded to writes.

### GREEN evidence

`python -m pytest -q backend/tests/test_standard_source_binding.py backend/tests/test_standard_manifest_import.py backend/tests/test_standard_manifest.py scripts/tests/test_apply_standard_manifest.py scripts/tests/test_bind_standard_rule_sources.py scripts/tests/test_check_operator_report_evidence_readonly.py backend/tests/test_standard_evidence_service.py backend/tests/test_evidence_bundle_service.py backend/tests/test_operator_catalog_and_reports_api.py backend/tests/test_standard_lifecycle.py`

Result: `119 passed`.

### Follow-up controls

- Current approved-version lookup now verifies the selected version belongs to the selected standard before planning.
- Shared rule-entry mapping rejects null and duplicate IDs; exact-set validation is used by repair planning and approved-version validation.
- Import rejects null or unknown existing entries before writes, permits genuinely missing approved entries to be created, and verifies the final logical entry-ID set is exact.
