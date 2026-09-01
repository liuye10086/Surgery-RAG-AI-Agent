from sqlalchemy import (
    Boolean,
    Column,
    CheckConstraint,
    Date,
    DateTime,
    Float,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
    func,
    text,
)
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
    operator_cases = relationship(
        "OperatorCase", back_populates="user", cascade="all, delete-orphan"
    )


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


class StandardDocument(Base):
    __tablename__ = "standard_documents"
    __table_args__ = (
        UniqueConstraint("content_hash", name="uq_standard_documents_content_hash"),
    )

    id = Column(Integer, primary_key=True)
    title = Column(String(500))
    filename = Column(String(500), nullable=False)
    file_path = Column(String(1000), nullable=False)
    file_type = Column(String(50), nullable=False)
    file_size = Column(Integer, nullable=False)
    content_hash = Column(String(64), nullable=False)
    uploaded_by = Column(
        Integer,
        ForeignKey(
            "users.id",
            name="fk_standard_documents_uploaded_by",
            ondelete="SET NULL",
        ),
    )
    created_at = Column(DateTime(timezone=True), nullable=False, server_default=func.now())

    version = relationship(
        "ReferenceStandardVersion",
        back_populates="standard_document",
        uselist=False,
    )


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
    operator_cases = relationship(
        "OperatorCase", back_populates="disease", cascade="all, delete-orphan"
    )
    reference_standards = relationship(
        "ReferenceStandard", back_populates="disease", passive_deletes=True
    )


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


class OperatorCase(Base):
    """A longitudinal case entered by an AI operator.

    ``CaseRecord`` remains the imported/reference-case model.  Operator cases
    are owned by a user and retain their own visit timeline for prediction.
    """

    __tablename__ = "operator_cases"
    __table_args__ = (
        CheckConstraint(
            "age IS NULL OR age BETWEEN 0 AND 120",
            name="ck_operator_cases_age_range",
        ),
        Index("ix_operator_cases_user_id", "user_id"),
        Index("ix_operator_cases_disease_id", "disease_id"),
    )

    id = Column(Integer, primary_key=True)
    user_id = Column(Integer, ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    disease_id = Column(Integer, ForeignKey("diseases.id", ondelete="CASCADE"), nullable=False)
    patient_label = Column(String(100), nullable=False)
    sex = Column(String(10))
    age = Column(Integer, nullable=True)
    baseline_stage = Column(String(100))
    notes = Column(Text)
    status = Column(String(50), nullable=False, default="active", server_default="active")
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )

    user = relationship("User", back_populates="operator_cases")
    disease = relationship("Disease", back_populates="operator_cases")
    visits = relationship(
        "OperatorCaseVisit",
        back_populates="case",
        cascade="all, delete-orphan",
        order_by="OperatorCaseVisit.visit_date",
    )
    reports = relationship("AIReport", back_populates="operator_case")


class OperatorCaseVisit(Base):
    """One dated observation in an operator-owned longitudinal case."""

    __tablename__ = "operator_case_visits"
    __table_args__ = (
        UniqueConstraint(
            "case_id",
            "visit_date",
            name="uq_operator_case_visits_case_date",
        ),
        Index("ix_operator_case_visits_case_id", "case_id"),
        Index("ix_operator_case_visits_visit_date", "visit_date"),
    )

    id = Column(Integer, primary_key=True)
    case_id = Column(
        Integer,
        ForeignKey("operator_cases.id", ondelete="CASCADE"),
        nullable=False,
    )
    visit_date = Column(Date, nullable=False)
    visit_index = Column(Integer, nullable=False)
    indicators = Column(JSONB, nullable=False, default=list, server_default=text("'[]'::jsonb"))
    notes = Column(Text)
    created_at = Column(DateTime(timezone=True), server_default=func.now())

    case = relationship("OperatorCase", back_populates="visits")


class ReferenceRange(Base):
    __tablename__ = "reference_ranges"
    __table_args__ = (
        Index("ix_reference_ranges_indicator", "indicator_name"),
        Index(
            "uq_reference_ranges_current_projection",
            "standard_id",
            "indicator_name",
            "sex",
            "category",
            "applicability_hash",
            unique=True,
            postgresql_where=text("is_current_projection IS TRUE"),
        ),
    )

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
    standard_id = Column(Integer, ForeignKey("reference_standards.id", ondelete="SET NULL"), nullable=True)
    standard_version_id = Column(Integer, ForeignKey("reference_standard_versions.id", ondelete="SET NULL"), nullable=True)
    standard_rule_id = Column(Integer, ForeignKey("standard_rules.id", ondelete="SET NULL"), nullable=True)
    applicability_hash = Column(String(64))
    is_current_projection = Column(Boolean, nullable=False, default=False, server_default="false")
    created_at = Column(DateTime(timezone=True), server_default=func.now())


class ReferenceStandard(Base):
    __tablename__ = "reference_standards"
    __table_args__ = (UniqueConstraint("disease_id", name="uq_reference_standards_disease"),)

    id = Column(Integer, primary_key=True)
    disease_id = Column(
        Integer,
        ForeignKey(
            "diseases.id",
            name="reference_standards_disease_id_fkey",
            ondelete="RESTRICT",
        ),
        nullable=False,
        unique=True,
    )
    name = Column(String(200), nullable=False)
    description = Column(Text)
    status = Column(String(50), nullable=False, default="active", server_default="active")
    current_version_id = Column(Integer, ForeignKey("reference_standard_versions.id", ondelete="SET NULL"), nullable=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())

    disease = relationship("Disease", back_populates="reference_standards")
    current_version = relationship("ReferenceStandardVersion", foreign_keys=[current_version_id], post_update=True)
    versions = relationship(
        "ReferenceStandardVersion",
        back_populates="standard",
        foreign_keys="ReferenceStandardVersion.standard_id",
        cascade="all, delete-orphan",
    )


class ReferenceStandardVersion(Base):
    __tablename__ = "reference_standard_versions"
    __table_args__ = (
        CheckConstraint(
            "status IN ('draft', 'review', 'approved', 'retired')",
            name="ck_reference_standard_versions_status",
        ),
        UniqueConstraint(
            "standard_document_id",
            name="uq_reference_standard_versions_standard_document",
        ),
        Index("ix_reference_standard_versions_standard_status", "standard_id", "status"),
    )

    id = Column(Integer, primary_key=True)
    standard_id = Column(Integer, ForeignKey("reference_standards.id", ondelete="CASCADE"), nullable=False)
    standard_document_id = Column(
        Integer,
        ForeignKey(
            "standard_documents.id",
            name="fk_reference_standard_versions_standard_document",
            ondelete="RESTRICT",
        ),
        nullable=False,
    )
    version_label = Column(String(100), nullable=False)
    content_hash = Column(String(64), nullable=False)
    parser_version = Column(String(100), nullable=False)
    status = Column(String(50), nullable=False, default="draft", server_default="draft")
    supersedes_version_id = Column(Integer, ForeignKey("reference_standard_versions.id", ondelete="SET NULL"), nullable=True)
    effective_from = Column(DateTime(timezone=True))
    retired_at = Column(DateTime(timezone=True))
    created_by = Column(Integer, ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    approved_by = Column(Integer, ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    approved_at = Column(DateTime(timezone=True))
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())

    standard = relationship("ReferenceStandard", back_populates="versions", foreign_keys=[standard_id])
    standard_document = relationship("StandardDocument", back_populates="version")
    segments = relationship("StandardSegment", back_populates="version", cascade="all, delete-orphan")
    rules = relationship("StandardRule", back_populates="version", cascade="all, delete-orphan")
    candidates = relationship("StandardParseCandidate", back_populates="version", cascade="all, delete-orphan")


class StandardIndicator(Base):
    __tablename__ = "standard_indicators"
    __table_args__ = (UniqueConstraint("canonical_key", name="uq_standard_indicators_canonical_key"),)

    id = Column(Integer, primary_key=True)
    canonical_key = Column(String(200), nullable=False)
    name_en = Column(String(200), nullable=False)
    name_cn = Column(String(200))
    aliases = Column(JSONB, nullable=False, default=list, server_default=text("'[]'::jsonb"))
    domain = Column(String(100))
    specimen_or_modality = Column(String(100))
    data_type = Column(String(50), nullable=False, default="qualitative", server_default="qualitative")
    scale_or_method = Column(String(200))
    default_unit = Column(String(50))
    clinical_dimension = Column(String(100))
    allows_numeric_comparison = Column(Boolean, nullable=False, default=False, server_default="false")
    abnormal_direction = Column(String(50), nullable=False, default="none", server_default="none")
    created_at = Column(DateTime(timezone=True), server_default=func.now())

    rules = relationship("StandardRule", back_populates="indicator")


class StandardSegment(Base):
    __tablename__ = "standard_segments"
    __table_args__ = (Index("ix_standard_segments_version_location", "version_id", "table_index", "row_index"),)

    id = Column(Integer, primary_key=True)
    version_id = Column(Integer, ForeignKey("reference_standard_versions.id", ondelete="CASCADE"), nullable=False)
    section_title = Column(String(300))
    paragraph_index = Column(Integer)
    table_index = Column(Integer)
    row_index = Column(Integer)
    column_index = Column(Integer)
    raw_text = Column(Text, nullable=False)
    segment_type = Column(String(50), nullable=False)
    parse_status = Column(String(50), nullable=False, default="pending", server_default="pending")
    review_status = Column(String(50), nullable=False, default="pending", server_default="pending")
    source_metadata = Column(JSONB, nullable=False, default=dict, server_default=text("'{}'::jsonb"))
    created_at = Column(DateTime(timezone=True), server_default=func.now())

    version = relationship("ReferenceStandardVersion", back_populates="segments")
    candidates = relationship("StandardParseCandidate", back_populates="segment", cascade="all, delete-orphan")
    rules = relationship("StandardRule", back_populates="source_segment")


class StandardParseCandidate(Base):
    __tablename__ = "standard_parse_candidates"
    __table_args__ = (Index("ix_standard_parse_candidates_segment", "segment_id"),)

    id = Column(Integer, primary_key=True)
    version_id = Column(Integer, ForeignKey("reference_standard_versions.id", ondelete="CASCADE"), nullable=False)
    segment_id = Column(Integer, ForeignKey("standard_segments.id", ondelete="CASCADE"), nullable=False)
    source_type = Column(String(50), nullable=False)
    parser_version = Column(String(100), nullable=False)
    model_name = Column(String(100))
    prompt_version = Column(String(100))
    raw_output = Column(Text)
    candidate_json = Column(JSONB, nullable=False, default=dict, server_default=text("'{}'::jsonb"))
    confidence = Column(Float)
    status = Column(String(50), nullable=False, default="pending", server_default="pending")
    created_at = Column(DateTime(timezone=True), server_default=func.now())

    version = relationship("ReferenceStandardVersion", back_populates="candidates")
    segment = relationship("StandardSegment", back_populates="candidates")


class StandardRule(Base):
    __tablename__ = "standard_rules"
    __table_args__ = (
        Index("ix_standard_rules_version_indicator", "version_id", "indicator_id"),
        Index("ix_standard_rules_conflict_group", "version_id", "conflict_group"),
    )

    id = Column(Integer, primary_key=True)
    version_id = Column(Integer, ForeignKey("reference_standard_versions.id", ondelete="CASCADE"), nullable=False)
    indicator_id = Column(Integer, ForeignKey("standard_indicators.id", ondelete="SET NULL"), nullable=True)
    source_segment_id = Column(Integer, ForeignKey("standard_segments.id", ondelete="SET NULL"), nullable=True)
    rule_type = Column(String(50), nullable=False)
    comparator = Column(String(5))
    lower = Column(Float)
    upper = Column(Float)
    lower_inclusive = Column(Boolean, nullable=False, default=True, server_default="true")
    upper_inclusive = Column(Boolean, nullable=False, default=True, server_default="true")
    unit = Column(String(50))
    sex = Column(String(10))
    category = Column(String(100))
    applicability = Column(JSONB, nullable=False, default=dict, server_default=text("'{}'::jsonb"))
    target_state_type = Column(String(50), nullable=False)
    target_state_value = Column(String(200))
    clinical_dimension = Column(String(100))
    evidence_type = Column(String(100))
    machine_actionability = Column(String(50), nullable=False, default="evidence-only", server_default="evidence-only")
    interpretation = Column(Text)
    priority = Column(Integer, nullable=False, default=0, server_default="0")
    conflict_group = Column(String(100))
    framework = Column(String(100))
    biomarker_axis = Column(String(10))
    biomarker_state = Column(String(100))
    stage = Column(String(100))
    clinical_function = Column(Text)
    conditions = Column(JSONB, nullable=False, default=dict, server_default=text("'{}'::jsonb"))
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())

    version = relationship("ReferenceStandardVersion", back_populates="rules")
    indicator = relationship("StandardIndicator", back_populates="rules")
    source_segment = relationship("StandardSegment", back_populates="rules")
    condition_nodes = relationship("StandardRuleCondition", back_populates="rule", cascade="all, delete-orphan")


class StandardRuleCondition(Base):
    __tablename__ = "standard_rule_conditions"
    __table_args__ = (Index("ix_standard_rule_conditions_rule_parent", "rule_id", "parent_id"),)

    id = Column(Integer, primary_key=True)
    rule_id = Column(Integer, ForeignKey("standard_rules.id", ondelete="CASCADE"), nullable=False)
    parent_id = Column(Integer, ForeignKey("standard_rule_conditions.id", ondelete="CASCADE"), nullable=True)
    node_type = Column(String(50), nullable=False)
    position = Column(Integer, nullable=False, default=0, server_default="0")
    payload = Column(JSONB, nullable=False, default=dict, server_default=text("'{}'::jsonb"))

    rule = relationship("StandardRule", back_populates="condition_nodes")
    children = relationship("StandardRuleCondition", cascade="all, delete-orphan")


class StandardChangeLog(Base):
    __tablename__ = "standard_change_logs"
    __table_args__ = (Index("ix_standard_change_logs_entity", "entity_type", "entity_id"),)

    id = Column(Integer, primary_key=True)
    version_id = Column(Integer, ForeignKey("reference_standard_versions.id", ondelete="CASCADE"), nullable=False)
    entity_type = Column(String(50), nullable=False)
    entity_id = Column(Integer, nullable=False)
    action = Column(String(50), nullable=False)
    before_json = Column(JSONB, nullable=False, default=dict, server_default=text("'{}'::jsonb"))
    after_json = Column(JSONB, nullable=False, default=dict, server_default=text("'{}'::jsonb"))
    reason = Column(Text, nullable=False)
    actor_id = Column(Integer, ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now())


class AIReport(Base):
    __tablename__ = "ai_reports"
    __table_args__ = (
        Index("ix_ai_reports_user_id", "user_id"),
        Index("ix_ai_reports_created_at", "created_at"),
        Index("ix_ai_reports_status", "status"),
        Index("ix_ai_reports_operator_case_id", "operator_case_id"),
    )

    id = Column(Integer, primary_key=True)
    user_id = Column(
        Integer, ForeignKey("users.id", ondelete="CASCADE"), nullable=False
    )
    title = Column(String(500))
    query = Column(Text, nullable=False)
    department_ids = Column(JSONB, nullable=False, default=list, server_default=text("'[]'::jsonb"))
    content = Column(Text, nullable=False, default="", server_default=text("''"))
    sources = Column(JSONB, nullable=False, default=list, server_default=text("'[]'::jsonb"))
    retrieval_meta = Column(JSONB, nullable=False, default=dict, server_default=text("'{}'::jsonb"))
    status = Column(String(50), nullable=False, default="generating", server_default="generating")
    error_message = Column(Text)
    download_count = Column(Integer, nullable=False, default=0, server_default="0")
    # 预测分析新列（旧数据兼容：全部 nullable/default，旧报告以 analysis_type='retrospective' 标记）
    analysis_type = Column(String(50), nullable=False, default="retrospective", server_default="retrospective")
    disease_id = Column(Integer, ForeignKey("diseases.id", ondelete="SET NULL"), nullable=True)
    operator_case_id = Column(
        Integer,
        ForeignKey("operator_cases.id", ondelete="SET NULL"),
        nullable=True,
    )
    # server_default 保证 0006 迁移后旧报告行这两列回填为 []/{}，不出现 NULL
    # （Task 10 按 list[dict]/dict 输出时旧报告才不会被 Pydantic 校验失败）。
    indicators = Column(JSONB, default=list, server_default=text("'[]'::jsonb"))
    prediction_result = Column(JSONB, default=dict, server_default=text("'{}'::jsonb"))
    input_snapshot = Column(JSONB, nullable=True)
    created_at = Column(DateTime(timezone=True), nullable=False, server_default=func.now())
    updated_at = Column(
        DateTime(timezone=True), nullable=False, server_default=func.now(), onupdate=func.now()
    )

    user = relationship("User", back_populates="reports")
    operator_case = relationship("OperatorCase", back_populates="reports")


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
