from typing import Annotated

from pydantic import BaseModel, EmailStr, Field, StringConstraints


class Token(BaseModel):
    access_token: str
    token_type: str = "bearer"


class LoginRequest(BaseModel):
    username: str
    password: str


class RegisterRequest(BaseModel):
    username: Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=100)]
    email: EmailStr
    real_name: str | None = None
    password: str = Field(min_length=6)
