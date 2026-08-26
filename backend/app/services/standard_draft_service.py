"""Transaction-neutral preparation of fresh parsed standard drafts."""

from __future__ import annotations

import hashlib
from dataclasses import dataclass, field
from pathlib import Path
from types import SimpleNamespace
from typing import Any

from app.db.models import (
    Disease,
    ReferenceStandard,
    ReferenceStandardVersion,
    StandardDocument,
    StandardParseCandidate,
    StandardSegment,
)
from app.services.standard_parser import parse_standard_docx


@dataclass(frozen=True)
class DraftPreparationSpec:
    dataset: str
    disease_name: str
    source_path: Path
    source_sha256: str
    version_label: str
    parser_version: str


@dataclass(frozen=True)
class DraftPlanItem:
    dataset: str
    source_hash_matches: bool
    document_id: int | None = None
    version_id: int | None = None


@dataclass(frozen=True)
class DraftPreparationPlan:
    items: list[DraftPlanItem] = field(default_factory=list)


@dataclass(frozen=True)
class DraftPreparationResult:
    items: list[Any] = field(default_factory=list)


def _hash(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def plan_draft_preparation(db: Any, specs: list[DraftPreparationSpec]) -> DraftPreparationPlan:
    items = []
    for spec in specs:
        if not spec.source_path.is_file():
            raise ValueError(f"标准源文件不存在：{spec.dataset}")
        items.append(DraftPlanItem(dataset=spec.dataset, source_hash_matches=_hash(spec.source_path) == spec.source_sha256))
    return DraftPreparationPlan(items=items)


def _candidate_json(candidate: Any) -> dict[str, Any]:
    return {
        "indicator_name": candidate.indicator_name,
        "rule_type": candidate.rule_type,
        "target_state_type": candidate.target_state_type,
        "target_state_value": candidate.target_state_value,
        "machine_actionability": candidate.machine_actionability,
        "evidence_type": candidate.evidence_type,
        "applicability": candidate.applicability,
        "interpretation": candidate.interpretation,
        "numeric": candidate.numeric.__dict__ if candidate.numeric else None,
        "sex": getattr(candidate, "sex", None),
        "parse_warnings": list(getattr(candidate, "parse_warnings", ())),
    }


def prepare_standard_drafts(db: Any, specs: list[DraftPreparationSpec], *, admin_id: int) -> DraftPreparationResult:
    results = []
    for spec in specs:
        if not spec.source_path.is_file() or _hash(spec.source_path) != spec.source_sha256:
            raise ValueError(f"标准源文件哈希不匹配：{spec.dataset}")
        disease = db.query(Disease).filter(Disease.id == (1 if spec.dataset == "fatty_liver" else 2)).with_for_update().first()
        if disease is None:
            disease = SimpleNamespace(id=1 if spec.dataset == "fatty_liver" else 2, name=spec.disease_name)
        document = db.query(StandardDocument).filter(StandardDocument.content_hash == spec.source_sha256).with_for_update().first()
        if document is None:
            document = StandardDocument(
                title=f"{spec.disease_name}标准",
                filename=spec.source_path.name,
                file_path=str(spec.source_path),
                file_type="docx",
                file_size=spec.source_path.stat().st_size,
                content_hash=spec.source_sha256,
                uploaded_by=admin_id,
            )
            db.add(document)
            if hasattr(db, "flush"):
                db.flush()
        standard = db.query(ReferenceStandard).filter(ReferenceStandard.disease_id == disease.id).with_for_update().first()
        if standard is None:
            standard = ReferenceStandard(disease_id=disease.id, name=f"{spec.disease_name}标准")
            db.add(standard)
            if hasattr(db, "flush"):
                db.flush()
        if getattr(document, "version", None) is not None:
            raise ValueError(f"标准文档已关联版本：{spec.dataset}")
        version = ReferenceStandardVersion(
            standard_id=standard.id,
            standard_document_id=document.id,
            version_label=spec.version_label,
            content_hash=spec.source_sha256,
            parser_version=spec.parser_version,
            created_by=admin_id,
            status="draft",
            supersedes_version_id=getattr(standard, "current_version_id", None),
        )
        db.add(version)
        if hasattr(db, "flush"):
            db.flush()
        parsed = parse_standard_docx(spec.source_path, parser_version=spec.parser_version)
        for segment in parsed.segments:
            db_segment = StandardSegment(
                version_id=version.id,
                section_title=segment.section_title,
                paragraph_index=segment.paragraph_index,
                table_index=segment.table_index,
                row_index=segment.row_index,
                column_index=segment.column_index,
                raw_text=segment.raw_text,
                segment_type=segment.segment_type,
                parse_status="parsed",
                source_metadata=segment.source_metadata,
            )
            db.add(db_segment)
            if hasattr(db, "flush"):
                db.flush()
            for candidate in [item for item in parsed.rule_candidates if item.segment == segment]:
                db.add(StandardParseCandidate(
                    version_id=version.id,
                    segment_id=db_segment.id,
                    source_type="deterministic",
                    parser_version=spec.parser_version,
                    candidate_json=_candidate_json(candidate),
                    status="pending",
                ))
        results.append(SimpleNamespace(dataset=spec.dataset, version_id=version.id, segment_count=len(parsed.segments), candidate_count=len(parsed.rule_candidates), status=version.status))
    return DraftPreparationResult(items=results)
