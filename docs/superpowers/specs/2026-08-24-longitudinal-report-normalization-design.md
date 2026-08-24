# Longitudinal Report Normalization Design

## Goal

Make structured longitudinal predictions and rendered reports canonical, readable, and provenance-aware without changing the prediction model contract or raw input snapshots.

## Design

` summarize_observation` will keep one canonical lowercase key per indicator. The first submitted display name may be retained as metadata, but it must not become a second indicator entry. Report rendering will format finite numeric values to at most two decimal places and use explicit labels for unavailable values.

Evidence objects will retain their source type. Reference-range entries will render as reference standards with indicator, unit, and bounds. Similar cases will be deduplicated by patient label and their overlapping indicators merged. The normalized evidence list will be stored in `AIReport.sources` and included in the structured SSE prediction payload.

## Compatibility and Limits

- Raw `input_snapshot` remains unchanged for auditability.
- Existing prediction fields and `direction_only` semantics remain unchanged.
- No clinical probability or new model output is introduced.
- Existing single-timepoint reports are unaffected.

## Verification

Add regression tests for case-insensitive indicator deduplication, numeric formatting, reference-range rendering, similar-case deduplication, and preserved required sections. Re-render the supplied style-equivalent PDF fixture after implementation and run the backend suite plus frontend build.
