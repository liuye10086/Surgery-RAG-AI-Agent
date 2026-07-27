from pydantic import BaseModel, ConfigDict, EmailStr


class UserBase(BaseModel):
    username: str
    email: EmailStr


class UserOut(UserBase):
    id: int
    real_name: str | None
    role: str

    model_config = ConfigDict(from_attributes=True)
