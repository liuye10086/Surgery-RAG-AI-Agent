"""Generation and validation of readable anonymous case codes."""

import re
import secrets


_ALPHABET = "ABCDEFGHJKLMNPQRSTUVWXYZ23456789"
_PATTERN = re.compile(r"^CASE-[A-HJ-NP-Z2-9]{4}-[A-HJ-NP-Z2-9]{4}$")


def generate_anonymous_case_code() -> str:
    return "CASE-{}-{}".format(
        "".join(secrets.choice(_ALPHABET) for _ in range(4)),
        "".join(secrets.choice(_ALPHABET) for _ in range(4)),
    )


def validate_anonymous_case_code(value: str) -> str:
    if not isinstance(value, str) or not _PATTERN.fullmatch(value.strip()):
        raise ValueError("匿名病例编号格式无效")
    return value.strip()
