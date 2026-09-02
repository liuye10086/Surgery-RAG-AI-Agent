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
    anonymous_case_code: Optional[str] = None
    indicators: list[dict] = []
    prediction_result: dict = {}
    input_snapshot: dict | None = None
    input_snapshot_sha256: Optional[str] = None
    generation_batch_id: Optional[str] = None
    generation_fingerprint: Optional[str] = None
    error_stage: Optional[str] = None
    integrity_status: Optional[str] = None
    integrity_reason_code: Optional[str] = None
    created_at: datetime
    updated_at: datetime


class ReportListItem(BaseModel):
    """报告列表项（仅返回安全摘要，不含完整正文和预测 JSON）。"""

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
    anonymous_case_code: Optional[str] = None
    indicators: list[dict] = []
    disease_name: Optional[str] = None
    baseline_stage: Optional[str] = None
    visit_count: Optional[int] = None
    model_version_summary: Optional[str] = None
    error_stage: Optional[str] = None
    input_snapshot_sha256: Optional[str] = None
    generation_batch_id: Optional[str] = None
    generation_fingerprint: Optional[str] = None
    created_at: datetime
    updated_at: datetime


class ReportListOut(BaseModel):
    reports: list[ReportListItem]
    total: int
