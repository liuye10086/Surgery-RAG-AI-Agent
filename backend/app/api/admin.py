from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile, status
from sqlalchemy.orm import Session

from app.api.deps import require_admin
from app.db.models import Chunk, Document
from app.db.session import get_db
from app.ingestion.chunker import chunk_pages
from app.ingestion.parser import parse_file
from app.schemas.document import (
    DocumentListOut,
    DocumentOut,
    DocumentUploadResponse,
    DocumentWithChunksOut,
)
from app.rag.vectorstore import add_chunks, delete_chunk_vectors, get_vectorstore
from app.services import file_storage
from app.services.document_indexing import (
    activate_generation,
    delete_generation_chunks,
    delete_obsolete_chunks,
    next_generation,
    staged_generation,
)

router = APIRouter(prefix="", tags=["admin"])


def _save_extracted_images(doc_id: int, generation: int, pages: list) -> list:
    """将解析阶段提取的图片 blob 写入磁盘，返回图片 URL 列表。

    每张图片记录 {url, page}，后续按页码关联到对应 chunk。
    """
    if not pages:
        return []
    images_dir = file_storage.document_images_dir(doc_id, generation)
    images_dir.mkdir(parents=True, exist_ok=True)

    saved: list = []
    for page in pages:
        for img in page.images:
            filename = f"p{img.page_number or 0}_{len(saved)}.{img.ext}"
            filepath = images_dir / filename
            filepath.write_bytes(img.blob)
            url = f"/api/v1/files/images/{doc_id}/{generation}/{filename}"
            saved.append({"url": url, "page": img.page_number})
    return saved


def _document_to_out(doc: Document) -> DocumentOut:
    return DocumentOut(
        id=doc.id,
        title=doc.title,
        filename=doc.filename,
        file_type=doc.file_type,
        file_size=doc.file_size,
        status=doc.status,
        error_message=doc.error_message,
        version=doc.version,
        is_current=doc.is_current,
        chunk_count=len(doc.chunks),
        created_at=doc.created_at,
        updated_at=doc.updated_at,
    )


@router.post("/documents/upload", response_model=DocumentUploadResponse)
def upload_document(
    file: UploadFile = File(...),
    title: str | None = Form(None),
    admin=Depends(require_admin),
    db: Session = Depends(get_db),
):
    try:
        file_path = file_storage.save_upload(file)
    except ValueError as e:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(e),
        )

    file_size = file_storage.get_file_size(file_path)
    safe_title = title.strip() if title else None
    if not safe_title:
        safe_title = file.filename

    doc = Document(
        title=safe_title,
        filename=file.filename,
        file_path=file_path,
        file_type=file_storage.validate_extension(file.filename),
        file_size=file_size,
        status="pending",
    )
    db.add(doc)
    db.commit()
    db.refresh(doc)

    return DocumentUploadResponse(
        id=doc.id,
        filename=doc.filename,
        title=doc.title,
        status=doc.status,
    )


@router.get("/documents", response_model=DocumentListOut)
def list_documents(
    skip: int = 0,
    limit: int = 100,
    search: str | None = None,
    admin=Depends(require_admin),
    db: Session = Depends(get_db),
):
    q = db.query(Document)
    if search:
        pattern = f"%{search}%"
        q = q.filter(
            Document.title.ilike(pattern) | Document.filename.ilike(pattern)
        )
    total = q.count()
    docs = (
        q.order_by(Document.created_at.desc())
        .offset(skip)
        .limit(limit)
        .all()
    )
    return DocumentListOut(total=total, items=[_document_to_out(d) for d in docs])


@router.get("/documents/{document_id}", response_model=DocumentWithChunksOut)
def get_document(
    document_id: int,
    admin=Depends(require_admin),
    db: Session = Depends(get_db),
):
    doc = db.query(Document).filter(Document.id == document_id).first()
    if not doc:
        raise HTTPException(status_code=404, detail="文档不存在")
    base = _document_to_out(doc).model_dump()
    base["chunks"] = doc.chunks
    return DocumentWithChunksOut(**base)


@router.delete("/documents/{document_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_document(
    document_id: int,
    admin=Depends(require_admin),
    db: Session = Depends(get_db),
):
    doc = db.query(Document).filter(Document.id == document_id).first()
    if not doc:
        raise HTTPException(status_code=404, detail="文档不存在")

    # 清理 PGVector 中的向量
    chunk_ids = [
        r[0] for r in
        db.query(Chunk.id).filter(Chunk.document_id == document_id).all()
    ]
    if chunk_ids:
        chunks = db.query(Chunk).filter(Chunk.id.in_(chunk_ids)).all()
        delete_chunk_vectors(get_vectorstore(), chunks)

    file_storage.delete_upload(doc.file_path)
    file_storage.delete_all_document_images(doc.id)
    db.delete(doc)
    db.commit()
    return None


@router.post("/documents/{document_id}/chunk", response_model=DocumentWithChunksOut)
def chunk_document(
    document_id: int,
    admin=Depends(require_admin),
    db: Session = Depends(get_db),
):
    doc = db.query(Document).filter(Document.id == document_id).first()
    if not doc:
        raise HTTPException(status_code=404, detail="文档不存在")

    if not doc.file_path or not file_storage.get_file_size(doc.file_path):
        raise HTTPException(status_code=400, detail="文件不存在或已丢失")

    doc.status = "parsing"
    doc.error_message = None
    db.commit()

    try:
        pages = parse_file(doc.file_path)
        generation = next_generation(db, doc)
        previous_staged = staged_generation(db, doc)
        if previous_staged is not None:
            staged_chunks = db.query(Chunk).filter(
                Chunk.document_id == doc.id,
                Chunk.generation == previous_staged,
                Chunk.is_current.is_(False),
            ).all()
            delete_chunk_vectors(get_vectorstore(), staged_chunks)
            delete_generation_chunks(db, doc.id, previous_staged)
            file_storage.delete_document_generation_images(doc.id, previous_staged)
            db.commit()

        all_images = _save_extracted_images(doc.id, generation, pages)
        chunks = chunk_pages(pages)

        for chunk in chunks:
            # 将匹配该 chunk 页码的图片路径写入 metadata
            chunk_images = [
                {"url": img["url"], "page": img["page"]}
                for img in all_images
                if img["page"] is None or chunk.page_number is None
                or img["page"] == chunk.page_number
            ]
            meta = dict(chunk.metadata)
            if chunk_images:
                meta["images"] = chunk_images
            db.add(
                Chunk(
                    document_id=doc.id,
                    content=chunk.content,
                    page_number=chunk.page_number,
                    chunk_index=chunk.chunk_index,
                    chunk_metadata=meta,
                    generation=generation,
                    is_current=False,
                )
            )

        doc.status = "chunked"
        doc.error_message = None
        db.commit()
        db.refresh(doc)
    except Exception as e:
        db.rollback()
        if "generation" in locals():
            try:
                staged_chunks = db.query(Chunk).filter(
                    Chunk.document_id == doc.id,
                    Chunk.generation == generation,
                    Chunk.is_current.is_(False),
                ).all()
                delete_chunk_vectors(get_vectorstore(), staged_chunks)
                delete_generation_chunks(db, doc.id, generation)
                file_storage.delete_document_generation_images(doc.id, generation)
                db.commit()
            except Exception:
                db.rollback()
        doc.status = "failed"
        doc.error_message = str(e)
        db.commit()
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"分块失败: {e}",
        )

    base = _document_to_out(doc).model_dump()
    base["chunks"] = doc.chunks
    return DocumentWithChunksOut(**base)


@router.post("/documents/{document_id}/index", response_model=DocumentWithChunksOut)
def index_document(
    document_id: int,
    admin=Depends(require_admin),
    db: Session = Depends(get_db),
):
    doc = db.query(Document).filter(Document.id == document_id).first()
    if not doc:
        raise HTTPException(status_code=404, detail="文档不存在")

    if doc.status == "pending":
        raise HTTPException(status_code=400, detail="请先分块")
    if doc.status not in {"chunked", "indexed", "failed"}:
        raise HTTPException(
            status_code=400,
            detail=f"当前状态 {doc.status} 不允许向量化",
        )

    generation = staged_generation(db, doc)
    if generation is None:
        raise HTTPException(status_code=400, detail="没有待向量化的新分块，请先分块")

    doc.status = "indexing"
    doc.error_message = None
    db.commit()

    try:

        chunks = (
            db.query(Chunk)
            .filter(
                Chunk.document_id == doc.id,
                Chunk.generation == generation,
                Chunk.is_current.is_(False),
            )
            .order_by(Chunk.chunk_index)
            .all()
        )
        if not chunks:
            raise HTTPException(status_code=400, detail="没有可分块的文本，请先分块")

        store = get_vectorstore()
        delete_chunk_vectors(store, chunks)
        vector_ids = add_chunks(store, chunks)
        if len(vector_ids) != len(chunks):
            raise RuntimeError("向量写入数量与分块数量不一致")

        old_chunks = db.query(Chunk).filter(
            Chunk.document_id == doc.id,
            Chunk.is_current.is_(True),
        ).all()
        old_generations = {chunk.generation for chunk in old_chunks}
        activate_generation(db, doc, generation)
        db.commit()
        db.refresh(doc)

        try:
            delete_chunk_vectors(store, old_chunks)
            delete_obsolete_chunks(db, doc.id, generation)
            db.commit()
            for old_generation in old_generations:
                file_storage.delete_document_generation_images(doc.id, old_generation)
        except Exception:
            db.rollback()
    except HTTPException:
        raise
    except Exception as e:
        db.rollback()
        if "chunks" in locals():
            try:
                delete_chunk_vectors(get_vectorstore(), chunks)
                delete_generation_chunks(db, doc.id, generation)
                file_storage.delete_document_generation_images(doc.id, generation)
                db.commit()
            except Exception:
                db.rollback()
        doc.status = "failed"
        doc.error_message = str(e)
        db.commit()
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"向量化失败: {e}",
        )

    base = _document_to_out(doc).model_dump()
    base["chunks"] = doc.chunks
    return DocumentWithChunksOut(**base)


@router.delete(
    "/documents/{document_id}/chunks/{chunk_id}",
    status_code=status.HTTP_204_NO_CONTENT,
)
def delete_chunk(
    document_id: int,
    chunk_id: int,
    admin=Depends(require_admin),
    db: Session = Depends(get_db),
):
    chunk = (
        db.query(Chunk)
        .filter(Chunk.id == chunk_id, Chunk.document_id == document_id)
        .first()
    )
    if not chunk:
        raise HTTPException(status_code=404, detail="分块不存在")

    # 清理 PGVector 中的向量
    delete_chunk_vectors(get_vectorstore(), [chunk])

    db.delete(chunk)
    db.commit()

    remaining = db.query(Chunk).filter(Chunk.document_id == document_id).count()
    if remaining == 0:
        doc = db.query(Document).filter(Document.id == document_id).first()
        if doc:
            doc.status = "chunked"
            db.commit()

    return None


@router.get("/dashboard")
def dashboard(admin=Depends(require_admin)):
    return {"message": "admin dashboard", "admin_email": admin.email}
