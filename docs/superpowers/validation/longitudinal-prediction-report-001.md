# Longitudinal Prediction Report Validation

## Verified

- `python -m pytest backend/tests -q`: 192 passed, 5 warnings.
- `python -m pytest backend/tests/test_alembic_contracts.py backend/tests/test_longitudinal_schema_contracts.py -q`: 21 passed.
- `python -m pytest scripts/tests/test_train_longitudinal_models.py -q`: 4 passed.
- `npm --prefix frontend run build`: passed; existing Rollup chunk-size warnings remain.
- `node frontend/tests/operator-legacy-cleanup.test.mjs`: passed.
- `git diff --check`: passed.

## Scope

The worktree now supports operator-owned longitudinal cases, dated visits,
time-prefix features, disease-specific outcome/stage contracts, direction-only
trend forecasts, provenance-marked evidence, persisted `longitudinal_predictive`
reports, PDF rendering, and the frontend case/report workflow.

Risk scores are explicitly model scores and remain uncalibrated. Direction-only
forecasts never contain fabricated future numeric values. Synthetic or rule-
recombined reference cases are marked in provenance.

## Remaining Validation

- A disposable PostgreSQL instance was not available for a live Alembic
  upgrade/downgrade and CRUD round trip.
- Full `scripts/tests` includes pre-existing fixture-dependent failures because
  external source DOCX files are absent and generated baseline artifact hashes
  differ from the checked-in expectations. These failures are outside the new
  longitudinal service tests.
- Clinical validity, calibration, and real-world generalization are not claimed.
