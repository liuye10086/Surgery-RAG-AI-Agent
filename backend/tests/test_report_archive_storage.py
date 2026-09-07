import hashlib
import pytest
from app.services.report_archive_storage import ArchiveStorage

KEY = "reports/17/11111111-1111-4111-8111-111111111111/document.pdf"


def test_storage_verifies_same_handle_and_rejects_traversal(tmp_path):
    storage = ArchiveStorage(tmp_path)
    with pytest.raises(ValueError):
        storage.candidate_path("../escape.pdf")
    path = storage.candidate_path(KEY)
    path.parent.mkdir(parents=True)
    raw = b"%PDF-fixture"
    path.write_bytes(raw)
    with storage.open_verified(
        KEY, hashlib.sha256(raw).hexdigest(), len(raw)
    ) as stream:
        assert stream.read() == raw
    path.write_bytes(b"corrupt")
    with pytest.raises(ValueError):
        storage.open_verified(KEY, hashlib.sha256(raw).hexdigest(), len(raw))


def test_candidate_does_not_replace_an_existing_original(tmp_path):
    import fitz

    document = fitz.open()
    document.new_page()
    raw = document.tobytes()
    document.close()
    storage = ArchiveStorage(tmp_path)
    candidate = storage.write_candidate(KEY, raw)
    with pytest.raises(ValueError):
        storage.write_candidate(KEY, raw)
    with storage.open_verified(
        KEY, candidate.pdf_sha256, candidate.size_bytes
    ) as stream:
        assert stream.read() == raw


def test_storage_rejects_directory_reparse_point(tmp_path):
    import os

    outside = tmp_path / "outside"
    outside.mkdir()
    storage = ArchiveStorage(tmp_path / "root")
    link = storage.root / "reports"
    if os.name == "nt":
        import subprocess

        subprocess.run(
            ["cmd", "/c", "mklink", "/J", str(link), str(outside)],
            check=True,
            capture_output=True,
        )
    else:
        link.symlink_to(outside, target_is_directory=True)
    with pytest.raises(ValueError):
        storage.candidate_path(KEY)
    assert list(outside.iterdir()) == []
