# Development And Test Baseline

- Task-ID: `development-baseline-001`
- Executed at: `2026-07-27 16:01:25 +08:00`
- Python: `3.11.4`
- Node.js: `22.15.0`
- npm: `10.9.2`

| Component | Status | Evidence |
|---|---|---|
| python | PASS | Python 3.11.4 |
| node | PASS | v22.15.0 |
| npm | PASS | 10.9.2 |
| postgresql-client | PASS | psql (PostgreSQL) 18.1 |
| postgresql-service | PASS | Running |
| backend-venv | PASS | Python 3.11.4 |
| frontend-dependencies | PASS | required packages present |
| DATABASE_URL | PASS | configured |
| JWT_SECRET | PASS | configured |
| unittest discover | PASS | exit code 0 |
| frontend-build | PASS | exit code 0 |
| database-readonly-command | PASS | exit code 0 |
| database-readonly | PASS | PostgreSQL 18.1; Alembic 0002; pg_trgm=1.6, uuid-ossp=1.1, vector=0.8.3 |
| external-llm | SKIP | excluded by baseline safety policy |
| model-downloads | SKIP | excluded by baseline safety policy |
| ocr-gpu | SKIP | excluded by baseline safety policy |
| document-reindex | SKIP | excluded by baseline safety policy |
| database-write-tests | SKIP | excluded by baseline safety policy |

## Known Environment Limitations

- `psql` discovery checks `PATH` and the default `C:\Program Files\PostgreSQL\*\bin` layout. Add `psql` to `PATH` when PostgreSQL uses a custom PostgreSQL installation directory.

This report contains no personal paths, connection strings, or secret values.
