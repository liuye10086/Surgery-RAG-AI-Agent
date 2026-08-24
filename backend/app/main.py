import asyncio
import warnings

from langchain_core._api.deprecation import LangChainDeprecationWarning

# RunnableWithMessageHistory 等 LangChain 弃用 API 在运行时产生大量噪音。
# 功能均正常，长期方案：随 LangChain 大版本升级逐步迁移。
warnings.filterwarnings("ignore", category=LangChainDeprecationWarning)

from fastapi import FastAPI, Depends, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from sqlalchemy.orm import Session

from app.api import admin, admin_standards, auth, chat, files, operator, user
from app.api.deps import get_current_user
from app.core.config import settings
from app.db.models import Chunk, Department, Document, User
from app.db.session import get_db
from app.rag.vectorstore import ensure_vectorstore_tables
from app.services.embedder import warmup_embedder
from app.services.file_storage import ensure_upload_dir
from app.services.source_access import user_can_access_document

app = FastAPI(title="Surgery RAG Agent")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # TODO: 生产环境收窄为前端域名
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(auth.router, prefix="/api/v1")
app.include_router(chat.router, prefix="/api/v1")
app.include_router(admin.router, prefix="/api/v1/admin")
app.include_router(admin_standards.router, prefix="/api/v1")
app.include_router(user.router, prefix="/api/v1")
app.include_router(files.router, prefix="/api/v1")
app.include_router(operator.router, prefix="/api/v1")


@app.on_event("startup")
async def startup_event():
    ensure_upload_dir()
    # 在后台线程预热 embedding 模型，避免第一个请求触发冷启动
    await asyncio.to_thread(warmup_embedder)
    # 触发 PGVector 建表，确保 langchain_pg_* 表和 GIN 索引存在
    await asyncio.to_thread(ensure_vectorstore_tables)


@app.get("/api/v1/departments")
def list_public_departments(
    active_only: bool = True,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """列出可用科室（所有登录用户可访问，仅用于前端筛选器）。"""
    q = db.query(Department)
    if active_only:
        q = q.filter(Department.is_active.is_(True))
    return q.order_by(Department.id).all()


@app.get("/health")
async def health():
    return {"status": "ok"}


@app.get("/api/v1/documents/{document_id}/content")
def get_document_content(
    document_id: int,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """获取文档完整内容（所有分块按页码和索引排序），供前端查看完整病例。"""
    doc = db.query(Document).filter(Document.id == document_id).first()
    if not doc:
        raise HTTPException(status_code=404, detail="文档不存在")
    if not user_can_access_document(db, current_user, document_id):
        raise HTTPException(status_code=403, detail="无权访问该病例文档")

    chunks = (
        db.query(Chunk)
        .filter(
            Chunk.document_id == document_id,
            Chunk.generation == doc.active_generation,
            Chunk.is_current.is_(True),
        )
        .order_by(Chunk.page_number.nullsfirst(), Chunk.chunk_index)
        .all()
    )

    return {
        "id": doc.id,
        "title": doc.title or doc.filename,
        "file_type": doc.file_type,
        "chunks": [
            {
                "id": c.id,
                "content": c.content,
                "page_number": c.page_number,
                "chunk_index": c.chunk_index,
            }
            for c in chunks
        ],
    }
