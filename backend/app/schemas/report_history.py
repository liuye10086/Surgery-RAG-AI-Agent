from datetime import datetime
from typing import Literal
from pydantic import (
    AwareDatetime,
    BaseModel,
    ConfigDict,
    field_validator,
    model_validator,
)
from app.schemas.operator import ReportListItem
from app.services.anonymous_case_code import validate_anonymous_case_code


class HistoryFilters(BaseModel):
    model_config = ConfigDict(extra="forbid")
    disease_code: Literal["fatty_liver", "ad"] | None = None
    anonymous_case_code: str | None = None
    created_from: AwareDatetime | None = None
    created_before: AwareDatetime | None = None
    status: Literal["generating", "completed", "failed", "cancelled"] | None = None

    @field_validator("anonymous_case_code")
    @classmethod
    def validate_code(cls, value):
        return validate_anonymous_case_code(value) if value is not None else None

    @model_validator(mode="after")
    def ordered_dates(self):
        if (
            self.created_from
            and self.created_before
            and self.created_from >= self.created_before
        ):
            raise ValueError("history_date_range_invalid")
        return self


class HistoryItem(ReportListItem):
    pdf_status: str = "not_requested"


class ReportHistoryPage(BaseModel):
    items: list[HistoryItem]
    next_cursor: str | None
    has_more: bool
