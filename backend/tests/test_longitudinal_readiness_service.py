from app.services.disease_progression import AD_ADAPTER, FATTY_LIVER_ADAPTER
from app.services.longitudinal_readiness import (
    aggregate_reference_data,
    assess_standard,
    load_database_snapshot,
)


def _row(
    patient,
    visit_date,
    *,
    final_stage,
    event_dates,
    synthetic=None,
    source="longitudinal_300",
):
    metadata = {
        "source_dataset": source,
        "visit_date": visit_date,
        "final_stage": final_stage,
        "event_dates": event_dates,
    }
    if synthetic is not None:
        metadata["is_synthetic"] = synthetic
    return {
        "patient_label": patient,
        "indicators": [{"name": "ALT", "value": 10}],
        "metadata": metadata,
    }


def test_reference_data_groups_patients_and_preserves_unknown_labels():
    rows = [
        _row(
            "P1",
            "2024-01-01",
            final_stage="fatty_liver",
            event_dates={},
            synthetic=False,
        ),
        _row(
            "P1",
            "2024-06-01",
            final_stage="fatty_liver",
            event_dates={},
            synthetic=False,
        ),
        _row(
            "P2",
            "2024-01-01",
            final_stage="cirrhosis",
            event_dates={},
            synthetic=True,
        ),
        _row(
            "P2",
            "2024-06-01",
            final_stage="cirrhosis",
            event_dates={},
            synthetic=True,
        ),
    ]
    data, reasons = aggregate_reference_data(rows, FATTY_LIVER_ADAPTER)
    assert data.patient_count == 2
    assert data.visit_count == 4
    assert data.all_prefix_count == 2
    assert data.negative_count == 1
    assert data.positive_count == 0
    assert data.unknown_count == 1
    assert data.real_patient_count == 1
    assert data.synthetic_patient_count == 1
    assert {reason.code for reason in reasons} == {"label_class_missing"}


def test_reference_data_does_not_guess_provenance_from_patient_number():
    rows = [
        _row(
            "P999",
            "2024-01-01",
            final_stage="fatty_liver",
            event_dates={},
            synthetic=None,
        ),
        _row(
            "P999",
            "2024-06-01",
            final_stage="fatty_liver",
            event_dates={},
            synthetic=None,
        ),
    ]
    data, _ = aggregate_reference_data(rows, FATTY_LIVER_ADAPTER)
    assert data.synthetic_patient_count == 0
    assert data.unknown_provenance_patient_count == 1


def test_ad_uses_ad_event_semantics_for_positive_prefix():
    rows = [
        _row(
            "A1",
            "2024-01-01",
            final_stage="dementia",
            event_dates={"dementia_date": "2024-12-01"},
            source="ad_longitudinal_300",
        ),
        _row(
            "A1",
            "2024-02-01",
            final_stage="dementia",
            event_dates={"dementia_date": "2024-12-01"},
            source="ad_longitudinal_300",
        ),
    ]
    data, _ = aggregate_reference_data(rows, AD_ADAPTER)
    assert data.positive_count == 1


def test_standard_requires_current_approved_version_and_calculable_rule():
    missing, missing_reasons = assess_standard(None)
    assert missing.status == "blocked"
    assert [reason.code for reason in missing_reasons] == [
        "approved_standard_missing"
    ]

    retired, retired_reasons = assess_standard(
        {
            "standard_id": 1,
            "current_version_id": 2,
            "version_status": "retired",
            "version_label": "v0.1",
            "content_hash": "abc",
            "rule_count": 0,
            "calculable_rule_count": 0,
        }
    )
    assert retired.status == "blocked"
    assert [reason.code for reason in retired_reasons] == [
        "approved_standard_missing"
    ]

    evidence_only, reasons = assess_standard(
        {
            "standard_id": 1,
            "current_version_id": 3,
            "version_status": "approved",
            "version_label": "v1",
            "content_hash": "def",
            "rule_count": 4,
            "calculable_rule_count": 0,
        }
    )
    assert evidence_only.status == "blocked"
    assert [reason.code for reason in reasons] == [
        "calculable_standard_rules_missing"
    ]


class _FakeResult:
    def __init__(self, rows):
        self._rows = rows

    def mappings(self):
        return self

    def all(self):
        return self._rows

    def scalar_one_or_none(self):
        return self._rows[0] if self._rows else None


class _FakeConnection:
    def __init__(self):
        self.statements = []

    def execute(self, statement, parameters=None):
        sql = str(statement).strip()
        self.statements.append(sql)
        if sql == "SET TRANSACTION READ ONLY":
            return _FakeResult([])
        if sql == "SHOW server_version":
            return _FakeResult(["18.1"])
        if "FROM alembic_version" in sql:
            return _FakeResult(["0010"])
        if (
            "FROM diseases" in sql
            and "case_records" not in sql
            and "reference_standards" not in sql
        ):
            return _FakeResult(
                [
                    {"id": 2, "name": "脂肪肝"},
                    {"id": 4, "name": "阿尔茨海默病"},
                ]
            )
        if "FROM case_records" in sql:
            return _FakeResult([])
        if "reference_standards" in sql:
            return _FakeResult([])
        if "information_schema.columns" in sql:
            return _FakeResult(
                [
                    {"table_name": "ai_reports", "column_name": "input_snapshot"},
                    {
                        "table_name": "ai_reports",
                        "column_name": "prediction_result",
                    },
                    {"table_name": "ai_reports", "column_name": "content"},
                    {"table_name": "ai_reports", "column_name": "status"},
                    {
                        "table_name": "ai_reports",
                        "column_name": "operator_case_id",
                    },
                    {
                        "table_name": "operator_cases",
                        "column_name": "patient_label",
                    },
                    {"table_name": "operator_cases", "column_name": "disease_id"},
                    {
                        "table_name": "operator_case_visits",
                        "column_name": "case_id",
                    },
                    {
                        "table_name": "operator_case_visits",
                        "column_name": "visit_date",
                    },
                    {
                        "table_name": "operator_case_visits",
                        "column_name": "indicators",
                    },
                ]
            )
        raise AssertionError(f"unexpected SQL: {sql}")


def test_load_database_snapshot_starts_with_read_only_and_uses_only_selects():
    connection = _FakeConnection()
    snapshot = load_database_snapshot(connection)
    assert connection.statements[0] == "SET TRANSACTION READ ONLY"
    assert snapshot["alembic_revision"] == "0010"
    assert snapshot["server_version"] == "18.1"
    assert snapshot["table_columns"]["ai_reports"] == {
        "input_snapshot",
        "prediction_result",
        "content",
        "status",
        "operator_case_id",
    }
    for sql in connection.statements[1:]:
        assert sql.lstrip().upper().startswith(("SELECT", "SHOW"))
