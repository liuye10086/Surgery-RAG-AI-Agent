import pytest
from scripts.backup_report_archive_inventory import digest, validated_deletions


def test_deletion_log_rejects_tampered_and_duplicate_identities():
    facts = {
        "originals": [],
        "cleanup": [],
        "deletion_log": [{"report_id": 17, "deleted_at": "2026-09-07T00:00:00+00:00"}],
    }
    value = {
        "schema_version": "report_archive_inventory.v1",
        **facts,
        "facts_sha256": digest(facts),
    }
    assert validated_deletions(value)[0]["report_id"] == 17
    value["deletion_log"][0]["report_id"] = 18
    with pytest.raises(ValueError, match="digest"):
        validated_deletions(value)
    value["deletion_log"] *= 2
    value["facts_sha256"] = digest({k: value[k] for k in facts})
    with pytest.raises(ValueError, match="log_invalid"):
        validated_deletions(value)
