# Longitudinal Report Normalization Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Remove duplicated indicators, floating-point noise, and ambiguous repeated evidence from longitudinal reports.

**Architecture:** Normalize indicator summaries at feature extraction, then format and group typed evidence in the report renderer. Persist the same normalized evidence payload used by Markdown/PDF so API, UI, and PDF remain consistent.

**Tech Stack:** Python 3.11, Pydantic v2, FastAPI, SQLAlchemy JSONB, pytest, Markdown/PDF renderer.

## Global Constraints

- Preserve raw input snapshots and existing prediction schema semantics.
- Keep `direction_only` forecasts free of future numeric values.
- Do not introduce clinical probability claims.
- Preserve single-timepoint reports.

### Task 1: Canonicalize observations and evidence

**Files:**
- Modify: `backend/app/services/longitudinal_features.py`
- Modify: `backend/app/services/longitudinal_evidence.py`
- Test: `backend/tests/test_longitudinal_features.py`
- Test: `backend/tests/test_longitudinal_evidence.py`

- [ ] Write failing tests asserting mixed-case indicators produce one summary key and similar cases with repeated labels are merged.
- [ ] Run the focused tests and confirm the expected failures.
- [ ] Remove display-name alias entries from observation and missingness summaries.
- [ ] Deduplicate similar-case evidence by patient label while merging sorted overlap features.
- [ ] Run focused tests and confirm they pass.

### Task 2: Format and render typed report values

**Files:**
- Modify: `backend/app/services/longitudinal_report_generator.py`
- Test: `backend/tests/test_longitudinal_end_to_end.py`

- [ ] Write failing tests for two-decimal numeric formatting and distinct reference-range/similar-case evidence lines.
- [ ] Run the focused tests and confirm the expected failures.
- [ ] Add a small report-local numeric formatter and source renderer.
- [ ] Render reference ranges with bounds and similar cases with merged indicators/provenance.
- [ ] Run focused tests and confirm they pass.

### Task 3: Regression verification and artifact documentation

**Files:**
- Modify: `docs/superpowers/validation/longitudinal-prediction-report-001.md`

- [ ] Run `python -m pytest backend/tests -q`.
- [ ] Run `npm --prefix frontend run build` and both frontend contract tests.
- [ ] Generate/render a representative longitudinal PDF and inspect both pages.
- [ ] Record the normalization fix and remaining model-artifact limitation.

