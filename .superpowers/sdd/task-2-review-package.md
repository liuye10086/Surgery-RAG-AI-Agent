# Task 2 Review Package

## Task

`longitudinal-prediction-report-002` — operator longitudinal case and visit
CRUD.

## Review Range

Review the implementation commit for:

- `backend/app/schemas/longitudinal_case.py`
- `backend/app/services/longitudinal_case_service.py`
- `backend/app/api/operator.py`
- `backend/tests/test_longitudinal_case_service.py`

## Acceptance Checks

1. Case and visit Pydantic payloads reject empty indicator lists, non-finite
   values, invalid sex, empty names/units, and overlong text.
2. Every case/visit query includes the current operator owner predicate.
3. Missing and cross-owner resources both return HTTP 404.
4. Duplicate visit dates are rejected and date order rewrites `visit_index`.
5. A snapshot contains sorted visits and model options but no user identity
   fields such as `real_name` or `user_id`.
6. Existing reference-case `/operator/cases` routes and predictive tests stay
   green.

## Verification Evidence

`33 passed` for the focused Task 2, operator permissions, and operator
predictive API tests. `compileall` and `git diff --check` also pass.

## Reviewer Attention

- Confirm the response shape (`{"cases": [...], "total": n}`) matches the
  frontend client contract introduced by the later UI task.
- Confirm PostgreSQL uniqueness and cascade behavior from Task 1 with a real
  migration test before end-to-end completion.
- Confirm the later report generator uses `build_input_snapshot` and retains
  snapshots immutably when a case is edited.

