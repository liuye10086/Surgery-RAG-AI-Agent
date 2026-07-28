from datetime import datetime
from typing import List, Optional

from pydantic import BaseModel, ConfigDict, Field, field_validator


class MessageBase(BaseModel):
    role: str
    content: str


class AskRequest(BaseModel):
    content: str = Field(
        ...,
        min_length=1,
        max_length=2000,
        description="用户问题，1-2000 字符",
    )
    retry_message_id: Optional[int] = None
    client_request_id: Optional[str] = Field(default=None, max_length=64)
    department_id: Optional[int] = Field(
        default=None,
        description="可选科室筛选，为 None 时全库检索",
    )

    @field_validator("content", mode="before")
    @classmethod
    def strip_content(cls, v: str) -> str:
        if isinstance(v, str):
            return v.strip()
        return v

    @field_validator("client_request_id", mode="before")
    @classmethod
    def validate_client_request_id(cls, v: Optional[str]) -> Optional[str]:
        if v is None:
            return None
        if not isinstance(v, str):
            return v
        value = v.strip()
        if not value:
            raise ValueError("client_request_id 不能为空")
        return value


class MessageOut(MessageBase):
    id: int
    session_id: int
    sources: List[dict] = []
    is_no_knowledge: bool = False
    is_error: bool = False
    created_at: datetime

    model_config = ConfigDict(from_attributes=True)


class SessionBase(BaseModel):
    title: Optional[str] = None


class SessionCreate(SessionBase):
    pass


class SessionOut(SessionBase):
    id: int
    user_id: int
    created_at: datetime
    updated_at: datetime

    model_config = ConfigDict(from_attributes=True)


class SessionDetail(SessionOut):
    messages: List[MessageOut] = []
