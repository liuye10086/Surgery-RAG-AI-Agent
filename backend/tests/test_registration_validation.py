import pytest
from pydantic import ValidationError

from app.schemas.auth import LoginRequest, RegisterRequest


@pytest.mark.parametrize("username", ["", " \t\n", "u" * 101])
def test_registration_rejects_invalid_username(username):
    with pytest.raises(ValidationError):
        RegisterRequest(username=username, email="test@example.com", password="123456")


@pytest.mark.parametrize("password", ["", "x", "12345"])
def test_registration_rejects_short_password(password):
    with pytest.raises(ValidationError):
        RegisterRequest(username="user", email="test@example.com", password=password)


def test_registration_trims_username_but_preserves_password():
    payload = RegisterRequest(username=" 用户 ", email="test@example.com", password=" 1234 ")
    assert payload.username == "用户"
    assert payload.password == " 1234 "
    assert LoginRequest(username="old-user", password="x").password == "x"
