"""Read-only validation and deterministic rendering for reviewed manifests."""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from app.schemas.standard_manifest import StandardManifest


CORE_INDICATORS: dict[str, tuple[str, ...]] = {
    "fatty_liver": ("alt", "ast", "ggt", "tbil", "alb", "plt", "afp", "hba1c", "bmi", "waist"),
    "ad": ("mmse", "moca", "cdr", "nfl", "p-tau217", "aβ42/aβ40"),
}

OWNER_REVIEWED_APPROXIMATE_INDICATORS = frozenset({"alt", "ast", "ggt"})
OWNER_REVIEWED_APPROXIMATE_POLICY = "owner_reviewed_strict"
APPROXIMATE_SOURCE_TOKENS = ("约", "常见为", "常作正常参考", "大约", "通常为")


@dataclass(frozen=True)
class ManifestFinding:
    code: str
    message: str
    entry_id: str | None = None


@dataclass(frozen=True)
class ManifestValidationResult:
    errors: list[ManifestFinding] = field(default_factory=list)
    warnings: list[ManifestFinding] = field(default_factory=list)
    missing_core_indicators: list[str] = field(default_factory=list)

    @property
    def valid(self) -> bool:
        return not self.errors


def load_standard_manifest(path: Path) -> StandardManifest:
    payload = json.loads(path.read_text(encoding="utf-8"))
    return StandardManifest.model_validate(payload)


def _segment_key(item: Any) -> tuple[int | None, int | None, int | None, int | None]:
    return (item.paragraph_index, item.table_index, item.row_index, item.column_index)


def _has_valid_approximate_override(manifest: StandardManifest, entry: Any) -> bool:
    rule = entry.rule
    applicability = rule.applicability or {}
    return (
        manifest.dataset == "fatty_liver"
        and entry.indicator.canonical_key in OWNER_REVIEWED_APPROXIMATE_INDICATORS
        and manifest.review_state == "approved"
        and manifest.reviewed_at is not None
        and entry.review_status == "approved"
        and rule.rule_type == "numeric_range"
        and rule.lower is not None
        and rule.upper is not None
        and rule.lower_inclusive is True
        and rule.upper_inclusive is True
        and bool(rule.unit)
        and applicability.get("source_language") == "approximate"
        and applicability.get("approximate_boundary_policy") == OWNER_REVIEWED_APPROXIMATE_POLICY
    )


def validate_standard_manifest(
    manifest: StandardManifest,
    *,
    source_path: Path,
    parsed_document: Any,
) -> ManifestValidationResult:
    errors: list[ManifestFinding] = []
    digest = hashlib.sha256(source_path.read_bytes()).hexdigest()
    if digest != manifest.source_document_sha256:
        errors.append(ManifestFinding("source_hash_mismatch", "源 DOCX 哈希不一致"))

    locations = {_segment_key(item): item.raw_text for item in parsed_document.segments}
    for entry in manifest.entries:
        if entry.source.document_absence_terms:
            document_text = "\n".join(str(item.raw_text) for item in parsed_document.segments).casefold()
            if any(term.casefold() in document_text for term in entry.source.document_absence_terms):
                errors.append(ManifestFinding("source_absence_contradicted", "文档级缺失结论与源文档内容冲突", entry.entry_id))
        else:
            key = _segment_key(entry.source)
            if locations.get(key) != entry.source.raw_text:
                errors.append(ManifestFinding("source_segment_mismatch", "源片段定位或原文不一致", entry.entry_id))

        rule = entry.rule
        if rule is not None and rule.machine_actionability == "calculable":
            applicability = rule.applicability or {}
            raw_text = entry.source.raw_text or ""
            approximate = (
                applicability.get("source_language") == "approximate"
                or any(token in raw_text for token in APPROXIMATE_SOURCE_TOKENS)
            )
            if approximate and not _has_valid_approximate_override(manifest, entry):
                errors.append(ManifestFinding(
                    "invalid_approximate_override",
                    "近似范围只有经审核的脂肪肝 ALT、AST、GGT 闭区间可以严格计算",
                    entry.entry_id,
                ))

    covered = {entry.indicator.canonical_key for entry in manifest.entries}
    missing = sorted(set(CORE_INDICATORS[manifest.dataset]) - covered)
    for key in missing:
        errors.append(ManifestFinding("core_indicator_missing", f"核心指标缺少明确结论：{key}"))

    if manifest.review_state == "approved":
        approved_rules = [
            entry.rule
            for entry in manifest.entries
            if entry.entry_kind == "rule" and entry.review_status == "approved" and entry.rule is not None
        ]
        if any(rule.machine_actionability == "blocked" for rule in approved_rules):
            errors.append(ManifestFinding("approved_blocked_rule", "approved manifest 不得包含 blocked 规则"))
        has_calculable = any(rule.machine_actionability == "calculable" for rule in approved_rules)
        has_evidence_only = any(rule.machine_actionability == "evidence-only" for rule in approved_rules)
        if manifest.dataset != "ad" and not has_calculable:
            errors.append(ManifestFinding("approved_calculable_rule_missing", "每种疾病至少需要一条审核通过的 calculable 规则"))
        if manifest.dataset == "ad" and not has_calculable and not has_evidence_only:
            errors.append(ManifestFinding("approved_evidence_rule_missing", "AD 标准至少需要一条审核通过的 evidence-only 正式规则"))

    return ManifestValidationResult(errors=errors, missing_core_indicators=missing)


def render_standard_review_markdown(manifest: StandardManifest) -> str:
    lines = [
        f"# {manifest.disease_name}标准规则审核清单",
        "",
        f"- Manifest：`{manifest.schema_version}`",
        f"- 数据集：`{manifest.dataset}`",
        f"- 源文档 SHA-256：`{manifest.source_document_sha256}`",
        f"- 目标版本：`{manifest.target_version_label}`",
        f"- 整体审核状态：`{manifest.review_state}`",
        "",
    ]
    for entry in sorted(manifest.entries, key=lambda item: item.entry_id):
        actionability = entry.rule.machine_actionability if entry.rule else "no_safe_rule"
        lines.extend([
            f"## {entry.entry_id}",
            "",
            f"- 指标：`{entry.indicator.canonical_key}` / {entry.indicator.name_cn or entry.indicator.name_en}",
            f"- 条目类型：`{entry.entry_kind}`",
            f"- 建议 actionability：`{actionability}`",
            f"- 审核状态：`{entry.review_status}`",
            f"- 审核备注：{entry.review_note or '无'}",
        ])
        if entry.source.document_absence_terms:
            lines.extend([
                "- 来源结论：整份源文档未检索到对应指标内容",
                f"- 文档检索词：{', '.join(entry.source.document_absence_terms)}",
                "",
            ])
        else:
            lines.extend([
                f"- 原文位置：paragraph={entry.source.paragraph_index}, table={entry.source.table_index}, row={entry.source.row_index}, column={entry.source.column_index}",
                f"- 原文：{entry.source.raw_text}",
                "",
            ])
    return "\n".join(lines).rstrip() + "\n"
