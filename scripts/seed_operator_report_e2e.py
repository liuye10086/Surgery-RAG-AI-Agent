"""Seed only an explicitly selected local _test database with reviewed fixtures."""

import os
import sys
from pathlib import Path
from urllib.parse import urlparse

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))
sys.path.insert(0, str(ROOT))


def require_test_database(url):
    parsed = urlparse(url)
    if parsed.hostname not in ("localhost", "127.0.0.1") or not parsed.path.endswith(
        "_test"
    ):
        raise ValueError("explicit_local_test_database_required")


def seed(session_factory):
    from sqlalchemy import text
    from app.db.models import User, Disease, CaseRecord
    from app.services.standard_manifest import load_standard_manifest
    from app.services.standard_manifest_import import import_manifest_rules
    from app.services.standard_draft_service import (
        DraftPreparationSpec,
        prepare_standard_drafts,
    )
    from app.services.standard_lifecycle import (
        submit_review_version,
        publish_review_version,
    )
    from app.services.longitudinal_case_service import create_operator_case
    from app.schemas.longitudinal_case import OperatorCaseCreate
    from backend.tests.report_document_fixtures import snapshot_payload

    with session_factory() as db:
        require_test_database(str(db.get_bind().url))
        db.execute(
            text(
                "TRUNCATE report_file_cleanup_tasks, report_deletion_tombstones, users, diseases, standard_documents, reference_standards, standard_indicators RESTART IDENTITY CASCADE"
            )
        )
        db.add_all(
            [
                User(
                    username="operator-a",
                    email="operator-a@example.com",
                    hashed_password="disabled",
                    role="ai_operator",
                ),
                User(
                    username="operator-b",
                    email="operator-b@example.com",
                    hashed_password="disabled",
                    role="ai_operator",
                ),
                User(
                    username="reviewer",
                    email="reviewer@example.com",
                    hashed_password="disabled",
                    role="admin",
                ),
            ]
        )
        db.add_all(
            [
                Disease(code="fatty_liver", name="脂肪肝", operator_enabled=True),
                Disease(code="ad", name="阿尔茨海默病", operator_enabled=True),
            ]
        )
        db.commit()
        specs = []
        manifests = {}
        for disease in ("fatty_liver", "ad"):
            manifest = load_standard_manifest(
                ROOT / "standard_manifests" / f"{disease}.v1.json"
            )
            if manifest.review_state != "approved":
                raise ValueError("reviewed_fixture_required")
            manifests[disease] = manifest
            specs.append(
                DraftPreparationSpec(
                    disease,
                    ROOT
                    / "backend/tests/fixtures/standards"
                    / f"{disease}_standard.docx",
                    manifest.source_document_sha256,
                    manifest.target_version_label,
                    "v2",
                )
            )
        prepared = prepare_standard_drafts(db, specs, admin_id=3)
        db.commit()
        for item in prepared.items:
            import_manifest_rules(
                db,
                manifest=manifests[item.dataset],
                version_id=item.version_id,
                admin_id=3,
            )
            db.flush()
            db.expire_all()
            submit_review_version(db, version_id=item.version_id, commit=False)
            publish_review_version(
                db, version_id=item.version_id, admin_id=3, commit=False
            )
            db.commit()
        case_ids = {}
        for disease in ("fatty_liver", "ad"):
            data = snapshot_payload(disease)
            payload = {
                key: data[key] for key in ("disease_id", "age", "sex", "baseline_stage")
            }
            payload["notes"] = "自动化验收虚构病例，不用于临床判断"
            payload["visits"] = [
                {k: v for k, v in visit.items() if k != "visit_index"}
                for visit in data["visits"]
            ]
            case = create_operator_case(
                db, 1, OperatorCaseCreate.model_validate(payload)
            )
            case_ids[disease] = case.id
        from app.services.reference_case_windows import (
            synchronize_reference_case_windows,
            resolve_reference_dataset,
        )
        import hashlib, json

        for disease in ("fatty_liver", "ad"):
            data = snapshot_payload(disease)
            digest = hashlib.sha256(
                json.dumps(data, sort_keys=True).encode()
            ).hexdigest()
            for visit in data["visits"]:
                db.add(
                    CaseRecord(
                        disease_id=data["disease_id"],
                        anonymous_case_code="CASE-E2ET-2345",
                        indicators=visit["indicators"],
                        case_metadata={
                            "logical_dataset": resolve_reference_dataset(disease)[1],
                            "dataset_release_id": "e2e-synthetic-" + disease,
                            "dataset_active": True,
                            "data_content_sha256": digest,
                            "is_synthetic": False,
                            "visit_date": visit["visit_date"],
                            "patient_age": data["age"],
                            "sex": data["sex"],
                            "baseline_stage": data["baseline_stage"],
                            "source_trace": {"source_system": "automated_test"},
                            "outcome_source": "explicit_cirrhosis"
                            if disease == "fatty_liver"
                            else "explicit_cdr",
                            "outcome_reliability": "high",
                            "outcome_status": "positive",
                            "outcome_value": {
                                "event_date": "2026-01-01",
                                "event_type": "cirrhosis"
                                if disease == "fatty_liver"
                                else "dementia",
                            },
                            "event_dates": {"cirrhosis_date": "2026-01-01"}
                            if disease == "fatty_liver"
                            else {},
                            "final_stage": "cirrhosis"
                            if disease == "fatty_liver"
                            else "dementia",
                        },
                    )
                )
            db.commit()
            synchronize_reference_case_windows(db, disease, apply=True)
        return case_ids


if __name__ == "__main__":
    url = os.environ.get("TEST_DATABASE_URL", "")
    require_test_database(url)
    os.environ["DATABASE_URL"] = url
    from app.db.session import SessionLocal

    print(seed(SessionLocal))
