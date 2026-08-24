# Longitudinal Prediction Report Validation

## Verified

- `python -m pytest backend/tests -q`: 201 passed, 5 warnings.
- `python -m pytest backend/tests/test_alembic_contracts.py backend/tests/test_longitudinal_schema_contracts.py -q`: 21 passed.
- `python -m pytest scripts/tests/test_train_longitudinal_models.py -q`: 4 passed.
- `npm --prefix frontend run build`: passed; existing Rollup chunk-size warnings remain.
- `node frontend/tests/operator-legacy-cleanup.test.mjs`: passed.
- `node frontend/tests/longitudinal-case-sync.test.mjs`: passed.
- `git diff --check`: passed.
- Real local PostgreSQL validation database: Alembic `upgrade head`, `downgrade 0007`, and `upgrade head` all passed; SQLAlchemy CRUD verified visit reindexing and duplicate-date rejection. Temporary database was removed afterward.
- Vite dev server served `http://127.0.0.1:5173/` with HTTP 200 and the expected Vue app root.
- Longitudinal report normalization verified: indicator keys are case-insensitively
  deduplicated, report numbers use a consistent two-decimal format, reference
  ranges are rendered separately from similar-case evidence, and duplicate
  similar cases merge their overlapping indicators.
- A temporary PDF generated from the reported test shape was rendered to PNG and
  visually checked: two pages, no clipping or overlap, no duplicated `alt`/`ALT`,
  and synthetic-source warnings remain visible.

## Scope

The worktree now supports operator-owned longitudinal cases, dated visits,
time-prefix features, disease-specific outcome/stage contracts, direction-only
trend forecasts, provenance-marked evidence, persisted `longitudinal_predictive`
reports, PDF rendering, and the frontend case/report workflow.

Risk scores are explicitly model scores and remain uncalibrated. Direction-only
forecasts never contain fabricated future numeric values. Synthetic or rule-
recombined reference cases are marked in provenance.

## Remaining Validation

- The live PostgreSQL round trip used a temporary local validation database;
  that database was removed after verification.
- Full `scripts/tests` includes pre-existing fixture-dependent failures because
  external source DOCX files are absent and generated baseline artifact hashes
  differ from the checked-in expectations. These failures are outside the new
  longitudinal service tests.
- Clinical validity, calibration, and real-world generalization are not claimed.
- The repository currently has longitudinal model metadata files but no matching
  `.joblib` outcome artifacts, so runtime reports correctly show
  `not_estimated` model status until compatible trained artifacts are installed.
