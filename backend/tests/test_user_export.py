import json
import os
from types import SimpleNamespace
from urllib.parse import unquote

import pytest

os.environ.setdefault("DEEPSEEK_API_KEY", "test-key")

from app.api.user import export_data


@pytest.mark.parametrize("username", ["张医生", 'name"with;punctuation', "用户\r\nInjected: value", "alice"])
def test_user_export_encodes_download_filename_without_changing_json(username):
    user = SimpleNamespace(
        id=7, username=username, email="synthetic@test.invalid",
        real_name="合成用户", role="user", created_at=None,
    )

    class Query:
        def filter(self, *args):
            return self

        def order_by(self, *args):
            return self

        def first(self):
            return user

        def all(self):
            return []

    response = export_data(db=SimpleNamespace(query=lambda model: Query()), current_user=user)

    assert response.status_code == 200
    header = response.headers["Content-Disposition"]
    assert header.isascii()
    assert "\r" not in header and "\n" not in header
    assert header.startswith('attachment; filename="data_export_7_')
    encoded = header.split("filename*=UTF-8''", 1)[1]
    assert unquote(encoded).startswith(f"data_export_{username}_")
    assert json.loads(response.body)["user"]["username"] == username
