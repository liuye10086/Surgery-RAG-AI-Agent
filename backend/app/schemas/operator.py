"""AI 操作者报告相关 Pydantic Schema。"""

from datetime import datetime
from typing import Optional

from pydantic import BaseModel, ConfigDict


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
    # 预测分析字段（旧报告默认 retrospective，预测报告为 predictive）
    analysis_type: str = "retrospective"
    disease_id: Optional[int] = None
    operator_case_id: Optional[int] = None
    indicators: list[dict] = []
    prediction_result: dict = {}
    input_snapshot: dict | None = None
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
    # 预测分析字段（旧报告默认 retrospective）
    analysis_type: str = "retrospective"
    disease_id: Optional[int] = None
    operator_case_id: Optional[int] = None
    indicators: list[dict] = []
    prediction_result: dict = {}
    input_snapshot: dict | None = None
    created_at: datetime
    updated_at: datetime


class ReportListOut(BaseModel):
    reports: list[ReportListItem]
    total: int
