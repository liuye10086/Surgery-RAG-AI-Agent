from datetime import datetime
from typing import List, Optional

from pydantic import BaseModel, ConfigDict


class DocumentUploadResponse(BaseModel):
    id: int
    filename: str
    title: Optional[str]
    status: str
    department_id: Optional[int] = None


class DocumentOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    title: Optional[str]
    filename: str
    file_type: Optional[str]
    file_size: Optional[int]
    status: str
    error_message: Optional[str]
    version: int
    is_current: bool
    chunk_count: int = 0
    department_id: Optional[int] = None
    department_name: Optional[str] = None
    created_at: datetime
    updated_at: datetime


class ChunkOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    document_id: int
    content: str
    page_number: Optional[int]
    chunk_index: int
    chunk_metadata: dict
    created_at: datetime


class DocumentWithChunksOut(DocumentOut):
    chunks: List[ChunkOut] = []


class DocumentListOut(BaseModel):
    total: int
    items: List[DocumentOut]


class DocumentUpdateIn(BaseModel):
    department_id: Optional[int] = None
