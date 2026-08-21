from sqlalchemy import Boolean, Column, DateTime, Float, ForeignKey, Index, Integer, String, Text, func, text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import relationship

from app.db.base import Base


class User(Base):
    __tablename__ = "users"

    id = Column(Integer, primary_key=True)
    username = Column(String(100), unique=True, nullable=False)
    email = Column(String(255), unique=True, nullable=False)
    real_name = Column(String(100))
    hashed_password = Column(String(255), nullable=False)
    role = Column(String(50), nullable=False, default="user")
    created_at = Column(DateTime(timezone=True), server_default=func.now())

    sessions = relationship("Session", back_populates="user", cascade="all, delete-orphan")
    audit_logs = relationship("AuditLog", back_populates="user")
    reports = relationship("AIReport", back_populates="user", cascade="all, delete-orphan")


class Department(Base):
    __tablename__ = "departments"

    id = Column(Integer, primary_key=True)
    name = Column(String(100), unique=True, nullable=False)
    description = Column(Text)
    is_active = Column(Boolean, default=True, nullable=False)
    created_at = Column(DateTime(timezone=True), server_default=func.now())

    documents = relationship("Document", back_populates="department")


class Document(Base):
    __tablename__ = "documents"

    id = Column(Integer, primary_key=True)
    title = Column(String(500))
    filename = Column(String(500), nullable=False)
    file_path = Column(String(1000))
    file_type = Column(String(50))
    file_size = Column(Integer)
    status = Column(String(50), default="pending")
    error_message = Column(Text)
    version = Column(Integer, default=1)
    active_generation = Column(Integer, nullable=False, default=1, server_default="1")
    is_current = Column(Boolean, default=True)
    department_id = Column(Integer, ForeignKey("departments.id", ondelete="RESTRICT"), nullable=True)
    access_scope = Column(String(20), nullable=False, default="chat", server_default="chat")
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())

    department = relationship("Department", back_populates="documents")
    chunks = relationship("Chunk", back_populates="document", cascade="all, delete-orphan", order_by="Chunk.chunk_index")


class Chunk(Base):
    __tablename__ = "chunks"
    __table_args__ = (
        Index("ix_chunks_document_id", "document_id"),
        Index("idx_chunks_document_generation", "document_id", "generation"),
    )

    id = Column(Integer, primary_key=True)
    document_id = Column(Integer, ForeignKey("documents.id", ondelete="CASCADE"), nullable=False)
    content = Column(Text, nullable=False)
    chunk_metadata = Column("metadata", JSONB, default=dict)
    page_number = Column(Integer)
    chunk_index = Column(Integer)
    generation = Column(Integer, nullable=False, default=1, server_default="1")
    is_current = Column(Boolean, default=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now())

    document = relationship("Document", back_populates="chunks")


class Session(Base):
    __tablename__ = "sessions"
    __table_args__ = (Index("ix_sessions_user_id", "user_id"),)

    id = Column(Integer, primary_key=True)
    user_id = Column(Integer, ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    title = Column(String(500))
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())

    user = relationship("User", back_populates="sessions")
    messages = relationship(
        "Message",
        back_populates="session",
        cascade="all, delete-orphan",
        order_by="Message.created_at",
    )


class Message(Base):
    __tablename__ = "messages"
    __table_args__ = (
        Index("ix_messages_session_id", "session_id"),
        Index(
            "uq_messages_session_client_request",
            "session_id",
            "client_request_id",
            unique=True,
            postgresql_where=text("client_request_id IS NOT NULL"),
        ),
    )

    id = Column(Integer, primary_key=True)
    session_id = Column(Integer, ForeignKey("sessions.id", ondelete="CASCADE"), nullable=False)
    role = Column(String(50), nullable=False)
    content = Column(Text, nullable=False)
    lc_message = Column(JSONB)
    sources = Column(JSONB, default=list)
    is_error = Column(Boolean, default=False)
    is_no_knowledge = Column(Boolean, default=False)
    client_request_id = Column(String(64), nullable=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now())

    session = relationship("Session", back_populates="messages")


class Disease(Base):
    __tablename__ = "diseases"

    id = Column(Integer, primary_key=True)
    name = Column(String(200), unique=True, nullable=False)
    description = Column(Text)
    created_at = Column(DateTime(timezone=True), server_default=func.now())

    case_records = relationship("CaseRecord", back_populates="disease", cascade="all, delete-orphan")


class CaseRecord(Base):
    __tablename__ = "case_records"
    __table_args__ = (Index("ix_case_records_disease_id", "disease_id"),)

    id = Column(Integer, primary_key=True)
    disease_id = Column(Integer, ForeignKey("diseases.id", ondelete="CASCADE"), nullable=False)
    patient_label = Column(String(100))
    indicators = Column(JSONB, nullable=False, default=list)
    confirmed = Column(Boolean, nullable=False, default=True, server_default="true")
    # 注意：`metadata` 是 SQLAlchemy declarative 的保留类属性（MetaData），
    # 不能直接作为 ORM 属性名，否则 models.py 导入即失败。
    # DB 列名仍为 "metadata"，ORM 属性命名为 case_metadata（与 Chunk.chunk_metadata 同模式）。
    case_metadata = Column("metadata", JSONB, default=dict)
    created_at = Column(DateTime(timezone=True), server_default=func.now())

    disease = relationship("Disease", back_populates="case_records")


class ReferenceRange(Base):
    __tablename__ = "reference_ranges"
    __table_args__ = (Index("ix_reference_ranges_indicator", "indicator_name"),)

    id = Column(Integer, primary_key=True)
    indicator_name = Column(String(100), nullable=False)
    name_cn = Column(String(200))
    unit = Column(String(50))
    lower = Column(Float)
    upper = Column(Float)
    # 边界开闭语义：<21 → upper=21, upper_inclusive=False；≤21 → True；
    # 区间 3.5-9.5 → 两端 True。见 Global Constraints「参考范围边界语义」。
    lower_inclusive = Column(Boolean, nullable=False, default=True, server_default="true")
    upper_inclusive = Column(Boolean, nullable=False, default=True, server_default="true")
    # 部分标准按性别分列（如脂肪肝 ALT 男性9-50/女性7-40）；None 表示通用范围，
    # 不区分性别。与 indicator_name 一起构成同一文档内的逻辑唯一键。
    sex = Column(String(10))
    category = Column(String(100))
    # 删除语义：参考标准文档删除时，其解析出的范围**级联删除**（CASCADE）。
    # 若用 SET NULL，文档删除后范围变孤儿仍参与预测，会基于已删除标准给出误导结果；
    # 级联后预测遇缺范围会明确报"缺少参考范围"提示操作者重新同步，行为更安全。
    document_id = Column(Integer, ForeignKey("documents.id", ondelete="CASCADE"), nullable=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now())


class AIReport(Base):
    __tablename__ = "ai_reports"
    __table_args__ = (
        Index("ix_ai_reports_user_id", "user_id"),
        Index("ix_ai_reports_created_at", "created_at"),
        Index("ix_ai_reports_status", "status"),
    )

    id = Column(Integer, primary_key=True)
    user_id = Column(
        Integer, ForeignKey("users.id", ondelete="CASCADE"), nullable=False
    )
    title = Column(String(500))
    query = Column(Text, nullable=False)
    department_ids = Column(JSONB, default=list)
    content = Column(Text, nullable=False, default="")
    sources = Column(JSONB, default=list)
    retrieval_meta = Column(JSONB, default=dict)
    status = Column(String(50), default="generating")
    error_message = Column(Text)
    download_count = Column(Integer, default=0)
    # 预测分析新列（旧数据兼容：全部 nullable/default，旧报告以 analysis_type='retrospective' 标记）
    analysis_type = Column(String(50), nullable=False, default="retrospective", server_default="retrospective")
    disease_id = Column(Integer, ForeignKey("diseases.id", ondelete="SET NULL"), nullable=True)
    # server_default 保证 0006 迁移后旧报告行这两列回填为 []/{}，不出现 NULL
    # （Task 10 按 list[dict]/dict 输出时旧报告才不会被 Pydantic 校验失败）。
    indicators = Column(JSONB, default=list, server_default=text("'[]'::jsonb"))
    prediction_result = Column(JSONB, default=dict, server_default=text("'{}'::jsonb"))
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )

    user = relationship("User", back_populates="reports")


class AuditLog(Base):
    __tablename__ = "audit_logs"
    __table_args__ = (
        Index("ix_audit_logs_user_id", "user_id"),
        Index("ix_audit_logs_session_id", "session_id"),
    )

    id = Column(Integer, primary_key=True)
    user_id = Column(Integer, ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    session_id = Column(Integer, ForeignKey("sessions.id", ondelete="SET NULL"), nullable=True)
    request_body = Column(JSONB)
    retrieved_chunk_ids = Column(JSONB, default=list)
    response_text = Column(Text)
    latency_ms = Column(Integer)
    model = Column(String(100))
    safety_flags = Column(JSONB, default=dict)
    created_at = Column(DateTime(timezone=True), server_default=func.now())

    user = relationship("User", back_populates="audit_logs")
