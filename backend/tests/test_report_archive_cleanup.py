from app.services.report_archive_cleanup import next_cleanup_delay


def test_cleanup_backoff_is_bounded():
    assert next_cleanup_delay(0) == 5
    assert next_cleanup_delay(100) == 3600


def test_postcommit_cleanup_database_failure_keeps_deletion_successful():
    from unittest.mock import Mock
    from app.services.report_archive_cleanup import cleanup_deleted_report

    db = Mock()
    db.query.side_effect = RuntimeError("database temporarily unavailable")
    result = cleanup_deleted_report(db, 17, "unused")
    assert result.deleted is True
    assert result.cleanup_state == "pending"
    db.rollback.assert_called_once()
