"""AI 操作者报告相关 Pydantic Schema。"""

from datetime import datetime
from typing import Optional

from pydantic import BaseModel, ConfigDict, Field, field_validator


class ReportGenerateRequest(BaseModel):
    query: str = Field(
        ...,
        min_length=1,
        max_length=2000,
        description="分析问题，1-2000 字符",
    )
    department_ids: Optional[list[int]] = Field(
        default=None,
        description="可选科室筛选，为 None 或空数组时全库检索",
    )
    analysis_backend: str = Field(
        default="llm",
        pattern=r"^(llm|predictive)$",
        description="分析后端：llm（LLM 分析）或 predictive（预测模型，预留）",
    )

    @field_validator("query", mode="before")
    @classmethod
    def strip_query(cls, v: str) -> str:
        if isinstance(v, str):
            return v.strip()
        return v

    @field_validator("department_ids", mode="before")
    @classmethod
    def normalize_department_ids(
        cls, v: Optional[list[int]]
    ) -> Optional[list[int]]:
        if v is not None and len(v) == 0:
            return None
        return v


class ReportOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    user_id: int
    title: Optional[str]
    query: str
    department_ids: list[int] = []
    content: str = ""
    sources: list[dict] = []
    retrieval_meta: dict = {}
    status: str
    error_message: Optional[str]
    download_count: int
    created_at: datetime
    updated_at: datetime


class ReportListItem(BaseModel):
    """报告列表项（不含完整 content，减少传输量）。"""

    model_config = ConfigDict(from_attributes=True)

    id: int
    user_id: int
    title: Optional[str]
    query: str
    department_ids: list[int] = []
    status: str
    error_message: Optional[str]
    download_count: int
    created_at: datetime
    updated_at: datetime


class ReportListOut(BaseModel):
    reports: list[ReportListItem]
    total: int
