import re

import pytest

from app.services.anonymous_case_code import (
    generate_anonymous_case_code,
    validate_anonymous_case_code,
)


def test_generated_code_is_readable_and_uses_safe_alphabet():
    value = generate_anonymous_case_code()
    assert re.fullmatch(r"CASE-[A-HJ-NP-Z2-9]{4}-[A-HJ-NP-Z2-9]{4}", value)
    assert not any(char in value for char in "IO10")


@pytest.mark.parametrize(
    "value",
    ["张三", "住院号-123", "13800138000", "110101199001011234", "a@example.com", "CASE-1234-5678"],
)
def test_code_validation_rejects_non_anonymous_or_ambiguous_values(value):
    with pytest.raises(ValueError):
        validate_anonymous_case_code(value)
