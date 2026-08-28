"""Print a read-only longitudinal readiness report as JSON."""

from __future__ import annotations

import json
import sys
from pathlib import Path

from alembic.config import Config
from alembic.script import ScriptDirectory
from sqlalchemy import create_engine
from sqlalchemy.exc import SQLAlchemyError


PROJECT_ROOT = Path(__file__).resolve().parents[1]
BACKEND_ROOT = PROJECT_ROOT / "backend"
for import_path in (PROJECT_ROOT, BACKEND_ROOT):
    if str(import_path) not in sys.path:
        sys.path.insert(0, str(import_path))

from app.schemas.longitudinal_readiness import LongitudinalReadinessReport
from app.core.config import settings
from app.services.longitudinal_readiness import collect_longitudinal_readiness
from app.services.model_paths import MODEL_DIR


def build_error_payload(code: str) -> dict[str, object]:
    return {
        "schema_version": "longitudinal_readiness.v1",
        "overall_status": "error",
        "error": {
            "code": code,
            "message": "无法完成纵向报告就绪检查",
        },
    }


def exit_code_for_report(report: LongitudinalReadinessReport) -> int:
    return 1 if report.overall_status == "blocked" else 0


def configure_stdout_utf8() -> None:
    reconfigure = getattr(sys.stdout, "reconfigure", None)
    if callable(reconfigure):
        reconfigure(encoding="utf-8")


def get_code_heads() -> set[str]:
    config = Config(str(BACKEND_ROOT / "alembic.ini"))
    config.set_main_option("script_location", str(BACKEND_ROOT / "alembic"))
    return set(ScriptDirectory.from_config(config).get_heads())


def run_check(
    *,
    database_url: str,
    model_dir: Path,
    code_heads: set[str],
) -> LongitudinalReadinessReport:
    engine = create_engine(database_url, future=True)
    try:
        with engine.connect() as connection:
            transaction = connection.begin()
            try:
                return collect_longitudinal_readiness(
                    connection,
                    model_dir=model_dir,
                    code_heads=code_heads,
                )
            finally:
                transaction.rollback()
    finally:
        engine.dispose()


def _print_json(payload: dict[str, object]) -> None:
    print(json.dumps(payload, ensure_ascii=False, sort_keys=True))


def main() -> int:
    configure_stdout_utf8()
    try:
        report = run_check(
            database_url=settings.DATABASE_URL,
            model_dir=Path(MODEL_DIR),
            code_heads=get_code_heads(),
        )
    except SQLAlchemyError:
        _print_json(build_error_payload("database_unavailable"))
        return 2
    except Exception:
        _print_json(build_error_payload("runtime_error"))
        return 2
    _print_json(report.model_dump(mode="json"))
    return exit_code_for_report(report)


if __name__ == "__main__":
    raise SystemExit(main())
