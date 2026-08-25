from datetime import datetime

from pydantic import BaseModel, ConfigDict


class StandardDocumentOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    title: str | None = None
    filename: str
    file_type: str
    file_size: int
    content_hash: str
    uploaded_by: int | None = None
    created_at: datetime | None = None
    is_locked: bool
    standard_id: int | None = None
    standard_name: str | None = None
    version_id: int | None = None
    version_label: str | None = None
