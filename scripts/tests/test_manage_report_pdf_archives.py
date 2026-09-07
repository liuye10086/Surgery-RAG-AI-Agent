import pytest
from scripts.manage_report_pdf_archives import main


def test_restore_requires_named_backup_and_cleanup_requires_explicit_mode():
    with pytest.raises(SystemExit):
        main(["restore", "--report-id", "17"])
    with pytest.raises(SystemExit):
        main(["cleanup"])
