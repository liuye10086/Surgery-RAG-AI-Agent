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
