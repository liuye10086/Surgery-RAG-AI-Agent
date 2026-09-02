def test_operator_case_tables_have_owner_and_visit_constraints():
    from app.db.models import AIReport, OperatorCase, OperatorCaseVisit

    assert OperatorCase.__tablename__ == "operator_cases"
    assert OperatorCaseVisit.__tablename__ == "operator_case_visits"
    assert {"user_id", "disease_id", "patient_label", "baseline_stage", "status"}.issubset(
        {column.name for column in OperatorCase.__table__.columns}
    )
    assert {"case_id", "visit_date", "visit_index", "indicators"}.issubset(
        {column.name for column in OperatorCaseVisit.__table__.columns}
    )
    report_columns = {column.name for column in AIReport.__table__.columns}
    assert {"operator_case_id", "input_snapshot"}.issubset(report_columns)


def test_operator_case_age_matches_database_contract():
    from app.db.models import OperatorCase

    age = OperatorCase.__table__.columns["age"]
    assert str(age.type) == "INTEGER"
    assert age.nullable is True
    assert any(
        constraint.name == "ck_operator_cases_age_range"
        for constraint in OperatorCase.__table__.constraints
    )


def test_operator_case_status_and_audit_contracts():
    from app.db.models import OperatorCase, OperatorCaseStatusLog

    status_constraint = next(
        c for c in OperatorCase.__table__.constraints if c.name == "ck_operator_cases_status"
    )
    assert "active" in str(status_constraint.sqltext)
    assert "archived" in str(status_constraint.sqltext)
    assert OperatorCaseStatusLog.__tablename__ == "operator_case_status_logs"
    assert {"case_id", "case_id_snapshot", "actor_id", "actor_id_snapshot", "from_status", "to_status", "reason"}.issubset(
        {column.name for column in OperatorCaseStatusLog.__table__.columns}
    )
    assert any(c.name == "ck_operator_case_status_logs_changed" for c in OperatorCaseStatusLog.__table__.constraints)
