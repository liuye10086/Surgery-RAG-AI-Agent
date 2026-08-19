from __future__ import annotations

import argparse
import csv
import hashlib
import json
import math
import random
import re
import shutil
import tempfile
import zipfile
from collections import Counter, defaultdict
from dataclasses import dataclass, field
from datetime import date, timedelta
from pathlib import Path
from statistics import median
from typing import Iterable, Sequence
from xml.etree import ElementTree


GENERATOR_VERSION = "1.0.0"
DEFAULT_SEED = 20260819
DATA_CUTOFF = date(2026, 8, 19)
W_NS = "{http://schemas.openxmlformats.org/wordprocessingml/2006/main}"

PATIENT_HEADERS = [
    "patient_id",
    "age",
    "sex",
    "cohort_group",
    "apoe",
    "gene_mutation",
    "final_stage",
    "dementia_date",
    "last_followup_date",
    "lost_to_followup",
]

VISIT_HEADERS = [
    "patient_id",
    "visit_date",
    "cdr",
    "mmse",
    "moca",
    "abeta42",
    "abeta40",
    "abeta_ratio",
    "ptau181",
    "ttau",
    "plasma_ptau217",
    "plasma_nfl",
    "gfap",
    "ykl40",
    "strem2",
    "crp",
    "homocysteine",
]

LONGITUDINAL_FIELDS = ["cdr", "mmse", "moca", "gfap", "crp", "homocysteine"]
SINGLE_MEASUREMENT_FIELDS = [
    "abeta42",
    "abeta40",
    "abeta_ratio",
    "ptau181",
    "ttau",
    "plasma_ptau217",
    "plasma_nfl",
    "ykl40",
    "strem2",
]

SAFETY_BOUNDS = {
    "cdr": (0.0, 3.0),
    "mmse": (0.0, 30.0),
    "moca": (0.0, 30.0),
    "abeta42": (100.0, 1200.0),
    "abeta40": (2000.0, 20000.0),
    "abeta_ratio": (0.015, 0.15),
    "ptau181": (10.0, 250.0),
    "ttau": (100.0, 1500.0),
    "plasma_ptau217": (0.05, 5.0),
    "plasma_nfl": (5.0, 100.0),
    "gfap": (40.0, 500.0),
    "ykl40": (20.0, 300.0),
    "strem2": (0.5, 15.0),
    "crp": (0.1, 20.0),
    "homocysteine": (5.0, 40.0),
}

STAGE_QUOTAS = {"0": 5, "0.5": 10, "1": 55, "2": 45, "3": 35}
COHORT_QUOTAS = {"ad_progression": 124, "mixed": 26}

ARTIFACT_NAMES = {
    "patients": "patients.csv",
    "visits": "visits.csv",
    "quality": "quality_report.json",
    "extracted_cases": "extracted_cases.json",
    "provenance": "DATA_PROVENANCE.md",
}

SUBSCRIPT_TRANSLATION = str.maketrans("₀₁₂₃₄₅₆₇₈₉", "0123456789")


@dataclass(frozen=True)
class GenerationConfig:
    seed: int = DEFAULT_SEED
    abeta42_threshold: float = 540.0
    ptau181_threshold: float = 58.0
    cutoff_date: date = DATA_CUTOFF


@dataclass
class CaseRecord:
    patient_id: str
    source_document: str
    source_case_id: str | None
    source_number: str | None
    occurrence: int
    heading: str
    text: str
    record_type: str = "source_case"
    age: int | None = None
    sex: str | None = None
    anchors: dict[str, float] = field(default_factory=dict)
    date_anchors: list[date] = field(default_factory=list)
    apoe: str = ""
    gene_mutation: str = ""
    source_components: dict[str, str] = field(default_factory=dict)


@dataclass
class PatientProfile:
    patient_id: str
    age: int
    sex: str
    cohort_group: str
    apoe: str
    gene_mutation: str
    final_stage: str
    inferred_stage: str
    stage_score: float
    classification_reasons: list[str]
    outcome_source: str
    case: CaseRecord


@dataclass
class GenerationResult:
    patients: list[dict[str, str]]
    visits: list[dict[str, str]]
    profiles: list[PatientProfile]
    paths: dict[str, str]
    assigned_path_mismatches: list[dict[str, object]]


HEADING_PATTERNS = [
    re.compile(r"^病例\s*[：:]?\s*(\d+)\s*$"),
    re.compile(r"^(\d+)\s*病例\s*[：:].*$"),
    re.compile(r"^(\d+)\s*[-–—]\s*(\d+)\s*病例\s*[：:].*$"),
    re.compile(r"^(47)\s+百岁女性.*$"),
]


def _normalize_text(text: str) -> str:
    return (
        text.translate(SUBSCRIPT_TRANSLATION)
        .replace("－", "-")
        .replace("–", "-")
        .replace("—", "-")
        .replace("‐", "-")
        .replace("‑", "-")
        .replace("＜", "<")
        .replace("＞", ">")
        .replace("＝", "=")
        .replace("μ", "u")
        .replace("µ", "u")
    )


def read_docx_blocks(path: Path) -> list[str]:
    """Read body-order paragraphs/tables without resolving optional relationships."""
    with zipfile.ZipFile(path) as archive:
        root = ElementTree.fromstring(archive.read("word/document.xml"))
    body = root.find(f"{W_NS}body")
    if body is None:
        raise ValueError(f"DOCX has no document body: {path}")
    blocks: list[str] = []
    for child in body:
        if child.tag not in {f"{W_NS}p", f"{W_NS}tbl"}:
            continue
        text = "".join(node.text or "" for node in child.iter(f"{W_NS}t")).strip()
        if text:
            blocks.append(text)
    return blocks


def _heading_number(text: str) -> tuple[str, str] | None:
    for index, pattern in enumerate(HEADING_PATTERNS):
        match = pattern.match(text)
        if not match:
            continue
        if index == 2:
            return f"{match.group(1)}-{match.group(2)}", text
        return match.group(1), text
    return None


def _segment_document(path: Path, prefix: str) -> list[dict[str, object]]:
    segments: list[dict[str, object]] = []
    current: dict[str, object] | None = None
    occurrences: Counter[str] = Counter()
    for block in read_docx_blocks(path):
        heading = _heading_number(block)
        if heading:
            number, heading_text = heading
            occurrences[number] += 1
            current = {
                "number": number,
                "occurrence": occurrences[number],
                "heading": heading_text,
                "blocks": [],
            }
            segments.append(current)
        elif current is not None:
            current["blocks"].append(block)
    normalized: list[dict[str, object]] = []
    for segment in segments:
        text = "\n".join(segment.pop("blocks"))
        if segment["number"] == "24-26":
            lines = text.splitlines()
            family_lines = {
                child_index: next(
                    line
                    for line in lines
                    if re.match(rf"病例\s*{child_index}（", line)
                )
                for child_index in (1, 2, 3)
            }
            shared_start = next(
                (index for index, line in enumerate(lines) if line.startswith("二、全套实验室检查")),
                len(lines),
            )
            shared_text = "\n".join(lines[shared_start:])
            for child_index, number in enumerate(("24", "25", "26"), 1):
                normalized.append(
                    {
                        "number": number,
                        "occurrence": 1,
                        "heading": f"24-26病例（家系子病例 {child_index}）",
                        "text": f"{family_lines[child_index]}\n{shared_text}",
                        "source_case_id": f"{prefix}24-26-{child_index}",
                    }
                )
        else:
            number = str(segment["number"])
            occurrence = int(segment["occurrence"])
            normalized.append(
                {
                    **segment,
                    "text": text,
                    "source_case_id": f"{prefix}{number}-{occurrence}",
                }
            )
    return normalized


def _first_number(patterns: Sequence[str], text: str) -> float | None:
    normalized = _normalize_text(text)
    for pattern in patterns:
        match = re.search(pattern, normalized, re.I)
        if match:
            try:
                return float(match.group(1))
            except (TypeError, ValueError):
                continue
    return None


def _extract_age(text: str) -> int | None:
    lines = text.splitlines()
    head = "\n".join(lines[:20])
    patterns = [
        r"典型患者(?:举例)?[^\n。；]{0,24}?(?<![\d.])(\d{1,3}(?:\.\d+)?)\s*岁",
        r"(?m)^[^\n]{0,100}?(?<![\d.])(\d{1,3}(?:\.\d+)?)\s*岁",
        r"(?:患者|病人)?\s*(?:男性|女性|男|女)[，, ]*(?<![\d.])(\d{1,3}(?:\.\d+)?)\s*岁",
        r"(?<![\d.])(\d{1,3}(?:\.\d+)?)\s*岁\s*(?:男性|女性|男|女)",
        r"(?:年龄|现年|初诊)\s*[：:]?\s*(?<![\d.])(\d{1,3}(?:\.\d+)?)\s*岁",
        r"(?:男性|女性|男|女)[^\n。；]{0,20}?(?:发病|起病|初诊)\s*(?<![\d.])(\d{1,3}(?:\.\d+)?)\s*岁",
        r"(?:发病|起病|初诊)\s*(?<![\d.])(\d{1,3}(?:\.\d+)?)\s*岁",
    ]
    value = _first_number(patterns, head)
    return int(value) if value is not None and 1 <= value <= 110 else None


def _extract_sex(text: str) -> str | None:
    head = "\n".join(text.splitlines()[:8])
    if re.search(r"(?:患者)?\s*女性|\d+\s*岁\s*女|女[，,]\s*\d+\s*岁", head):
        return "female"
    if re.search(r"(?:患者)?\s*男性|\d+\s*岁\s*男|男[，,]\s*\d+\s*岁", head):
        return "male"
    return None


def _extract_apoe(text: str) -> str:
    normalized = _normalize_text(text)
    match = re.search(
        r"APOE[^\n；;。]{0,40}?(?:e|ε)?\s*([234])\s*[/／]\s*(?:e|ε)?\s*([234])",
        normalized,
        re.I,
    )
    if not match:
        match = re.search(r"(?:e|ε)([234])\s*[/／]\s*(?:e|ε)([234])", normalized, re.I)
    return f"{match.group(1)}/{match.group(2)}" if match else ""


def _extract_gene_mutation(text: str) -> str:
    normalized = _normalize_text(text)
    if re.search(r"(?:\d+\s*例汇总|汇总典型病例)", "\n".join(normalized.splitlines()[:3])):
        return ""
    normalized = re.split(r"(?:^|\n)(?:四、)?鉴别诊断", normalized, maxsplit=1)[0]
    normalized = re.sub(r"SORL(?=剪接)", "SORL1", normalized, flags=re.I)
    normalized = re.sub(r"\bPDGF(?=\s*基因)", "PDGFB", normalized, flags=re.I)
    unique: list[str] = []
    gene_pattern = re.compile(
        r"PSEN1|PSEN2|APP|SORL1|MAPT|GRN|C9ORF72|ABCA7|NOTCH3|PDGFB|SLC20A2|PRNP|KCNA2|HNRNPA1|FMR1",
        re.I,
    )
    negative = re.compile(
        r"阴性|未见|未(?:发现|检出|检测|完善)|无[^，,；;。\n]{0,30}?(?:突变|变异)|"
        r"无致病性|拒绝|排除|正常|意义未明|致病性存疑|非(?:显性)?致病|"
        r"多态|次要变异|风险基因|(?:与|较|晚于|早于|慢于|快于|轻于|重于)"
        r"[^，,；;。\n]{0,28}?突变",
        re.I,
    )
    positive_after = re.compile(
        r"^.{0,55}?(?:(?:杂合|错义|截短|新发)?(?:基因)?(?:前)?突变|"
        r"(?:杂合|错义|截短|新发|损伤型?)变异|"
        r"(?:预测强|可能)?致病性?变异|扩增(?!检测)|阳性|拷贝数|缺失|删除)",
        re.I,
    )
    excluded_genes: set[str] = set()
    for clause in re.split(r"[\n，,；;。]", normalized):
        if re.search(r"意义未明|ACMG\s*3\s*(?:类|级)", clause, re.I):
            excluded_genes.update(match.group(0).upper() for match in gene_pattern.finditer(clause))
    for clause in re.split(r"[\n，,；;。]", normalized):
        for match in gene_pattern.finditer(clause):
            if match.group(0).upper() in excluded_genes:
                continue
            before = clause[max(0, match.start() - 24) : match.start()]
            after = clause[match.end() : match.end() + 72]
            context = before + match.group(0) + after
            if negative.search(context):
                continue
            if re.search(r"(?:IgG|抗体)", context, re.I):
                continue
            if re.search(r"(?:CADASIL|鉴别诊断)[：:]\s*$", before, re.I):
                continue
            if re.search(r"切割\s*$", before, re.I) or re.match(r"\s*的功能", after):
                continue
            if re.search(r"突变基因为\s*$", before, re.I) or re.search(
                r"^.{0,45}?突变基因为", after, re.I
            ):
                continue
            if not positive_after.search(after):
                continue
            upper = match.group(0).upper()
            if upper not in unique:
                unique.append(upper)
    return "/".join(unique[:4])


def _extract_dates(text: str) -> list[date]:
    normalized = _normalize_text(text)
    values: set[date] = set()
    for match in re.finditer(
        r"(?<!\d)(20\d{2})\s*(?:年|[-/.])\s*(\d{1,2})?\s*(?:月|[-/.])?\s*(\d{1,2})?\s*(?:日)?",
        normalized,
    ):
        year = int(match.group(1))
        month = int(match.group(2) or 7)
        day = int(match.group(3) or 1)
        try:
            value = date(year, month, day)
        except ValueError:
            continue
        if date(2000, 1, 1) <= value <= DATA_CUTOFF:
            values.add(value)
    return sorted(values)


def _extract_anchors(text: str) -> dict[str, float]:
    normalized = _normalize_text(text)
    patterns: dict[str, list[str]] = {
        "mmse": [r"\bMMSE\s*(?:基线|初测|初诊|总分)?\s*[=:：]?\s*(\d+(?:\.\d+)?)"],
        "moca": [r"\bMoCA\s*(?:基线|初测|初诊|总分)?\s*[=:：]?\s*(\d+(?:\.\d+)?)"],
        "cdr": [r"\bCDR\s*(?![- ]?(?:SB|SOB|盒|总))\s*(?:分级|评分)?\s*[=:：]?\s*(0\.5|[0-3])(?:\.0)?"],
        "abeta42": [
            r"A(?:β|beta)?\s*(?:1\s*-\s*)?42\s*[=:：]?\s*[<>≤≥]?\s*(\d+(?:\.\d+)?)",
            r"β淀粉样蛋白\s*42\s*[=:：]?\s*(\d+(?:\.\d+)?)",
        ],
        "abeta40": [r"A(?:β|beta)?\s*(?:1\s*-\s*)?40\s*[=:：]?\s*(\d+(?:\.\d+)?)"],
        "abeta_ratio": [
            r"A(?:β|beta)?\s*(?:1\s*-\s*)?42\s*/\s*A?(?:β|beta)?\s*(?:1\s*-\s*)?40\s*(?:比值)?\s*[=:：]?\s*(\d+(?:\.\d+)?)"
        ],
        "ptau181": [
            r"p\s*-?\s*Tau\s*(?:181)?\s*[=:：]?\s*[<>≤≥]?\s*(\d+(?:\.\d+)?)",
            r"磷酸化\s*Tau(?:181)?\s*[=:：]?\s*[<>≤≥]?\s*(\d+(?:\.\d+)?)",
            r"磷酸Tau\s*[=:：]?\s*(\d+(?:\.\d+)?)",
        ],
        "ttau": [
            r"T\s*-?\s*Tau\s*[=:：]?\s*[<>≤≥]?\s*(\d+(?:\.\d+)?)",
            r"总\s*Tau(?:蛋白)?\s*[=:：]?\s*[<>≤≥]?\s*(\d+(?:\.\d+)?)",
            r"总\s*tau\s*[=:：]?\s*[<>≤≥]?\s*(\d+(?:\.\d+)?)",
        ],
        "plasma_ptau217": [r"(?:血浆|外周血)[^\n；;。]{0,20}?p\s*-?\s*tau217\s*[=:：]?\s*(\d+(?:\.\d+)?)"],
        "plasma_nfl": [r"(?:外周血|血浆)[^\n；;。]{0,20}?(?:NfL|神经丝轻链)\s*[=:：]?\s*(\d+(?:\.\d+)?)"],
        "gfap": [r"(?:血清|血浆)?\s*GFAP\s*[=:：]?\s*(\d+(?:\.\d+)?)"],
        "crp": [r"(?:hs\s*-?\s*CRP|CRP|C反应蛋白)\s*(?:最高)?\s*[=:：]?\s*(\d+(?:\.\d+)?)"],
        "homocysteine": [r"同型半胱氨酸\s*[=:：]?\s*(\d+(?:\.\d+)?)"],
    }
    anchors: dict[str, float] = {}
    for name, alternatives in patterns.items():
        value = _first_number(alternatives, normalized)
        if value is None:
            continue
        low, high = SAFETY_BOUNDS.get(name, (-math.inf, math.inf))
        if low <= value <= high:
            anchors[name] = value
    if "plasma_nfl" not in anchors:
        for line in normalized.splitlines():
            if re.search(r"外周血|血浆", line) and re.search(r"NfL|神经丝轻链", line, re.I):
                value = _first_number([r"(?:NfL|神经丝轻链)[^\d]{0,12}(\d+(?:\.\d+)?)"], line)
                if value is not None and SAFETY_BOUNDS["plasma_nfl"][0] <= value <= SAFETY_BOUNDS["plasma_nfl"][1]:
                    anchors["plasma_nfl"] = value
                    break
    if "abeta42" in anchors and "abeta40" in anchors and "abeta_ratio" not in anchors:
        anchors["abeta_ratio"] = round(anchors["abeta42"] / anchors["abeta40"], 4)
    return anchors


def _build_case(
    raw: dict[str, object], patient_id: str, source_document: str
) -> CaseRecord:
    text = f"{raw['heading']}\n{raw['text']}"
    return CaseRecord(
        patient_id=patient_id,
        source_document=source_document,
        source_case_id=str(raw["source_case_id"]),
        source_number=str(raw["number"]),
        occurrence=int(raw["occurrence"]),
        heading=str(raw["heading"]),
        text=text,
        age=_extract_age(text),
        sex=_extract_sex(text),
        anchors=_extract_anchors(text),
        date_anchors=_extract_dates(text),
        apoe=_extract_apoe(text),
        gene_mutation=_extract_gene_mutation(text),
    )


def _make_recombinations(cases: list[CaseRecord]) -> list[CaseRecord]:
    combinations = [
        (3, 77, 115),
        (24, 102, 138),
        (39, 120, 140),
        (72, 128, 143),
    ]
    output: list[CaseRecord] = []
    for offset, (demographic_index, biomarker_index, diagnosis_index) in enumerate(
        combinations, 147
    ):
        demographics = cases[demographic_index - 1]
        biomarkers = cases[biomarker_index - 1]
        diagnosis = cases[diagnosis_index - 1]
        output.append(
            CaseRecord(
                patient_id=f"P{offset:03d}",
                source_document="stratified_recombination",
                source_case_id=None,
                source_number=None,
                occurrence=1,
                heading=f"分层重组病例 {offset - 146}",
                text=(
                    f"{diagnosis.heading}\n{diagnosis.text}\n"
                    f"生物标志物来源：{biomarkers.source_case_id}"
                ),
                record_type="stratified_recombination",
                age=demographics.age,
                sex=demographics.sex,
                anchors=dict(biomarkers.anchors),
                date_anchors=list(diagnosis.date_anchors),
                apoe=biomarkers.apoe or demographics.apoe,
                gene_mutation=diagnosis.gene_mutation or biomarkers.gene_mutation,
                source_components={
                    "demographics": demographics.source_case_id or demographics.patient_id,
                    "biomarkers": biomarkers.source_case_id or biomarkers.patient_id,
                    "diagnosis": diagnosis.source_case_id or diagnosis.patient_id,
                },
            )
        )
    return output


def parse_case_documents(paths: Sequence[Path]) -> list[CaseRecord]:
    if len(paths) != 2:
        raise ValueError("Exactly two AD source DOCX files are required")
    raw_segments: list[tuple[dict[str, object], str]] = []
    for prefix, path in zip(("A", "B"), paths):
        for raw in _segment_document(Path(path), prefix):
            raw_segments.append((raw, Path(path).name))
    if len(raw_segments) != 146:
        raise ValueError(f"Expected 146 source case anchors, found {len(raw_segments)}")
    cases = [
        _build_case(raw, f"P{index:03d}", source_document)
        for index, (raw, source_document) in enumerate(raw_segments, 1)
    ]
    cases.extend(_make_recombinations(cases))
    return cases


MIXED_SOURCE_CASE_IDS = {
    "A1-1", "A11-1", "A19-1", "A23-1", "A26-1", "A27-1", "A36-1",
    "A42-1", "A43-1", "A63-1", "A64-1", "A69-1", "B3-1", "B6-1",
    "B17-1", "B18-1", "B19-1", "B27-1", "B31-1", "B35-1", "B48-1",
    "B49-1", "B53-1", "B59-1", "B60-1", "B61-1",
}


def _case_is_explicit_mimic(case: CaseRecord) -> bool:
    if case.source_case_id in MIXED_SOURCE_CASE_IDS:
        return True
    if case.record_type == "stratified_recombination":
        return any(value in MIXED_SOURCE_CASE_IDS for value in case.source_components.values())
    return False


def _severity_evidence(text: str, anchors: dict[str, float]) -> tuple[str, float, str]:
    lines = text.splitlines()
    title = " ".join(lines[:3])
    cdr = anchors.get("cdr")
    if cdr in {0.0, 0.5, 1.0, 2.0, 3.0}:
        value = str(int(cdr)) if float(cdr).is_integer() else "0.5"
        return value, float(cdr), "explicit_cdr"
    if re.search(r"临床前|主观认知下降|\bSCD\b|无痴呆|正常对照|健康对照|认知正常", title, re.I):
        return "0", 0.0, "title_preclinical_or_normal"
    if re.search(r"轻度认知障碍|\bMCI\b", title, re.I):
        return "0.5", 0.5, "title_mci"
    if re.search(r"重度|晚期", title):
        return "3", 3.0, "title_severe"
    if re.search(r"中重度|中度", title):
        return "2", 2.0, "title_moderate"
    if re.search(r"轻度|早期", title):
        return "1", 1.0, "title_mild"
    mmse = anchors.get("mmse")
    if mmse is not None:
        if mmse >= 27:
            return "0.5", 0.65, "mmse"
        if mmse >= 21:
            return "1", 1.15, "mmse"
        if mmse >= 10:
            return "2", 2.05, "mmse"
        return "3", 3.0, "mmse"
    if re.search(r"完全不能自理|完全丧失|卧床|鼻饲|缄默|终末期", text):
        return "3", 2.8, "functional_severe"
    if re.search(r"需.*(?:协助|照料|陪护)|无法独立|生活能力.*(?:下降|衰退)", text):
        return "2", 2.0, "functional_moderate"
    return "1", 1.2, "documented_ad_unspecified"


def _assign_exact_stages(cases: list[CaseRecord]) -> dict[str, tuple[str, str, float]]:
    evidence: list[tuple[float, int, CaseRecord, str, str]] = []
    explicit: dict[str, tuple[str, str, float]] = {}
    for index, case in enumerate(cases):
        inferred, score, source = _severity_evidence(case.text, case.anchors)
        if source == "explicit_cdr":
            explicit[case.patient_id] = (inferred, source, float(inferred))
        else:
            evidence.append((score, index, case, inferred, source))
    evidence.sort(key=lambda item: (item[0], item[1]))
    assignments: dict[str, tuple[str, str, float]] = dict(explicit)
    cursor = 0
    for stage in ("0", "0.5", "1", "2", "3"):
        quota = STAGE_QUOTAS[stage] - sum(
            assigned_stage == stage for assigned_stage, _, _ in explicit.values()
        )
        for _, _, case, inferred, source in evidence[cursor : cursor + quota]:
            outcome_source = source if stage == inferred else "generated_stage_assignment"
            assignments[case.patient_id] = (stage, outcome_source, float(inferred))
        cursor += quota
    return assignments


def _assign_exact_cohorts(cases: list[CaseRecord]) -> dict[str, tuple[str, list[str]]]:
    explicit = [case for case in cases if _case_is_explicit_mimic(case)]
    explicit_ids = {case.patient_id for case in explicit}
    expected = COHORT_QUOTAS["mixed"]
    if len(explicit_ids) != expected:
        raise ValueError(
            f"Calibrated explicit mixed case count must be {expected}, found {len(explicit_ids)}"
        )
    assignments: dict[str, tuple[str, list[str]]] = {}
    for case in cases:
        if case.patient_id in explicit_ids:
            reason = (
                "explicit_competing_diagnosis"
                if _case_is_explicit_mimic(case)
                else "calibrated_mixed_quota_assignment"
            )
            assignments[case.patient_id] = ("mixed", [reason])
        else:
            reasons = [
                "documented_or_biomarker_supported_ad",
                "no_primary_competing_diagnosis",
            ]
            if case.gene_mutation == "C9ORF72" and re.search(
                r"符合阿尔茨海默病生物特征|典型\s*AD\s*代谢模式|AD\s*脑脊液",
                case.text,
                re.I,
            ):
                reasons.append(
                    "ad_phenotype_and_ad_biomarker_priority_over_c9orf72_background"
                )
            assignments[case.patient_id] = (
                "ad_progression",
                reasons,
            )
    return assignments


def build_profiles(cases: list[CaseRecord], config: GenerationConfig) -> list[PatientProfile]:
    rng = random.Random(config.seed + 11)
    stages = _assign_exact_stages(cases)
    cohorts = _assign_exact_cohorts(cases)
    profiles: list[PatientProfile] = []
    for case in cases:
        stage, outcome_source, inferred_score = stages[case.patient_id]
        inferred_stage, stage_score, _ = _severity_evidence(case.text, case.anchors)
        cohort, reasons = cohorts[case.patient_id]
        age = case.age if case.age is not None else rng.randint(40, 88)
        age = max(30, min(100, age))
        sex = case.sex or ("female" if rng.random() < 0.56 else "male")
        profiles.append(
            PatientProfile(
                patient_id=case.patient_id,
                age=age,
                sex=sex,
                cohort_group=cohort,
                apoe=case.apoe,
                gene_mutation=case.gene_mutation,
                final_stage=stage,
                inferred_stage=inferred_stage,
                stage_score=stage_score,
                classification_reasons=reasons,
                outcome_source=outcome_source,
                case=case,
            )
        )
    return profiles


def _assign_paths(profiles: list[PatientProfile], seed: int) -> dict[str, str]:
    stable = [
        profile.patient_id
        for profile in profiles
        if profile.final_stage in {"0", "0.5"}
        or profile.case.anchors.get("cdr", 0.0) >= 1.0
    ]
    path_quotas = {"r1": 25, "r2": 25, "r1_r2": 25}
    progressing = [profile.patient_id for profile in profiles if profile.patient_id not in set(stable)]
    rng = random.Random(seed + 29)
    rng.shuffle(progressing)
    paths = {patient_id: "stable" for patient_id in stable}
    profile_map = {profile.patient_id: profile for profile in profiles}

    def compatible_r1(patient_id: str) -> bool:
        anchors = profile_map[patient_id].case.anchors
        return anchors.get("abeta42", 0.0) < 540.0 and anchors.get("ptau181", 59.0) > 58.0

    eligible_r1 = [
        patient_id
        for patient_id in progressing
        if profile_map[patient_id].final_stage != "3"
        or profile_map[patient_id].case.anchors.get("cdr") is not None
    ]
    compatible = [patient_id for patient_id in eligible_r1 if compatible_r1(patient_id)]
    r1_r2_ids = compatible[: path_quotas["r1_r2"]]
    r1_ids = compatible[
        path_quotas["r1_r2"] : path_quotas["r1_r2"] + path_quotas["r1"]
    ]
    if len(r1_r2_ids) != path_quotas["r1_r2"] or len(r1_ids) != path_quotas["r1"]:
        raise ValueError("Insufficient source-compatible profiles for R1 path quotas")
    used = set(r1_r2_ids + r1_ids)
    remaining = [patient_id for patient_id in progressing if patient_id not in used]
    r2_ids = remaining[: path_quotas["r2"]]
    non_rule_ids = remaining[path_quotas["r2"] :]
    for patient_id in r1_ids:
        paths[patient_id] = "r1"
    for patient_id in r1_r2_ids:
        paths[patient_id] = "r1_r2"
    for patient_id in r2_ids:
        paths[patient_id] = "r2"
    for patient_id in non_rule_ids:
        paths[patient_id] = "non_rule_progression"
    return paths


def _timeline(rng: random.Random, cutoff: date, source_dates: Sequence[date]) -> list[date]:
    visit_count = rng.randint(3, 6)
    total_days = rng.randint(760, 1760)
    latest_baseline = cutoff - timedelta(days=total_days)
    earliest = date(2015, 1, 1)
    latest = min(date(2022, 8, 19), latest_baseline)
    available = max(0, (latest - earliest).days)
    eligible_anchors = [
        value
        for value in source_dates
        if earliest <= value <= latest and value + timedelta(days=total_days) <= cutoff
    ]
    baseline = eligible_anchors[0] if eligible_anchors else earliest + timedelta(days=rng.randint(0, available))
    weights = [rng.uniform(0.85, 1.15) for _ in range(visit_count - 1)]
    cumulative = [0.0]
    running = 0.0
    for weight in weights:
        running += weight
        cumulative.append(running)
    offsets = [round(total_days * value / running) for value in cumulative]
    offsets[-1] = total_days
    return [baseline + timedelta(days=offset) for offset in offsets]


def _cdr_sequence(final_stage: str, count: int) -> list[float]:
    final = float(final_stage)
    if final < 1.0:
        return [final] * count
    if final == 1.0:
        sequence = [0.5] * max(2, count - 1) + [1.0]
    elif final == 2.0:
        if count == 4:
            sequence = [0.5, 0.5, 0.5, 2.0]
        else:
            sequence = [0.5] * (count - 1) + [2.0]
    else:
        if count == 4:
            sequence = [0.5, 0.5, 1.0, 3.0]
        elif count == 5:
            sequence = [0.5, 0.5, 0.5, 1.0, 3.0]
        else:
            sequence = [0.5, 0.5, 0.5, 0.5, 2.0, 3.0]
    return sequence[-count:]


def _cdr_sequence_with_anchor(final_stage: str, count: int, anchor: float | None) -> list[float]:
    if anchor is None:
        return _cdr_sequence(final_stage, count)
    final = max(float(final_stage), anchor)
    allowed = [0.0, 0.5, 1.0, 2.0, 3.0]
    values = [anchor]
    for index in range(1, count):
        fraction = index / (count - 1)
        target = anchor + (final - anchor) * fraction
        values.append(min(allowed, key=lambda value: (abs(value - target), value)))
    values[-1] = final
    return values


def _format_number(value: float, digits: int = 2) -> str:
    rounded = round(value, digits)
    if float(rounded).is_integer():
        return str(int(rounded))
    return f"{rounded:.{digits}f}".rstrip("0").rstrip(".")


def _clip(name: str, value: float) -> float:
    low, high = SAFETY_BOUNDS[name]
    return max(low, min(high, value))


def _baseline_single_markers(
    profile: PatientProfile, path: str, rng: random.Random, config: GenerationConfig
) -> dict[str, float]:
    anchors = profile.case.anchors
    abeta42 = anchors.get("abeta42", rng.uniform(300, 780))
    ptau181 = anchors.get("ptau181", rng.uniform(35, 150))
    if path in {"r1", "r1_r2"}:
        if "abeta42" not in anchors:
            abeta42 = rng.uniform(260, config.abeta42_threshold - 10)
        if "ptau181" not in anchors:
            ptau181 = rng.uniform(config.ptau181_threshold + 8, 175)
    abeta40 = anchors.get("abeta40", rng.uniform(4300, 10500))
    ratio = anchors.get("abeta_ratio", abeta42 / abeta40)
    values = {
        "abeta42": _clip("abeta42", abeta42),
        "abeta40": _clip("abeta40", abeta40),
        "abeta_ratio": _clip("abeta_ratio", ratio),
        "ptau181": _clip("ptau181", ptau181),
        "ttau": _clip("ttau", anchors.get("ttau", rng.uniform(250, 950))),
        "plasma_ptau217": _clip(
            "plasma_ptau217", anchors.get("plasma_ptau217", rng.uniform(0.25, 2.8))
        ),
        "plasma_nfl": _clip(
            "plasma_nfl", anchors.get("plasma_nfl", rng.uniform(12, 48))
        ),
        "ykl40": _clip("ykl40", rng.uniform(55, 190)),
        "strem2": _clip("strem2", rng.uniform(2.0, 9.0)),
    }
    return values


def _cognitive_sequences(
    profile: PatientProfile, cdrs: list[float], rng: random.Random
) -> tuple[list[float], list[float]]:
    count = len(cdrs)
    anchor_mmse = profile.case.anchors.get("mmse")
    anchor_moca = profile.case.anchors.get("moca")
    start_mmse = anchor_mmse if anchor_mmse is not None else 29.0 - cdrs[0] * 5.0 + rng.uniform(-1.5, 1.0)
    start_moca = anchor_moca if anchor_moca is not None else 27.0 - cdrs[0] * 5.5 + rng.uniform(-1.5, 1.0)
    if profile.final_stage in {"0", "0.5"}:
        mmse = [_clip("mmse", start_mmse + rng.uniform(-0.6, 0.6)) for _ in cdrs]
        moca = [_clip("moca", start_moca + rng.uniform(-0.8, 0.8)) for _ in cdrs]
        mmse[0] = _clip("mmse", start_mmse)
        moca[0] = _clip("moca", start_moca)
        return mmse, moca
    target_mmse = {"1": 21.0, "2": 12.0, "3": 4.0}[profile.final_stage] + rng.uniform(-2, 2)
    target_moca = {"1": 18.0, "2": 9.0, "3": 2.0}[profile.final_stage] + rng.uniform(-2, 2)
    target_mmse = min(start_mmse - 1.0, target_mmse)
    target_moca = min(start_moca - 1.0, target_moca)
    mmse = []
    moca = []
    for index in range(count):
        fraction = index / (count - 1)
        mmse.append(_clip("mmse", start_mmse + (target_mmse - start_mmse) * fraction))
        moca.append(_clip("moca", start_moca + (target_moca - start_moca) * fraction))
    return mmse, moca


def _inflammation_sequences(
    path: str, count: int, anchors: dict[str, float], rng: random.Random
) -> tuple[list[float], list[float], list[float]]:
    gfap_base = _clip("gfap", anchors.get("gfap", rng.uniform(75, 180)))
    crp_base = _clip("crp", anchors.get("crp", rng.uniform(0.4, 3.5)))
    hcy_base = _clip("homocysteine", anchors.get("homocysteine", rng.uniform(8, 16)))
    gfap = [gfap_base + rng.uniform(-5, 5) for _ in range(count)]
    crp = [crp_base + rng.uniform(-0.4, 0.4) for _ in range(count)]
    hcy = [hcy_base + rng.uniform(-0.5, 0.5) for _ in range(count)]
    if path in {"r1", "r1_r2"}:
        gfap[0] = gfap_base
        if count > 1:
            gfap[1] = _clip("gfap", gfap_base + rng.uniform(4, 10))
        start = _clip("gfap", gfap[-3])
        if count > 3:
            start = max(start, gfap[1] + 2)
        gfap[-3:] = [start, _clip("gfap", start + rng.uniform(15, 28)), _clip("gfap", start + rng.uniform(35, 60))]
    else:
        base = _clip("gfap", gfap[-3])
        gfap[-3:] = [base, _clip("gfap", base + 8), _clip("gfap", base + 3)]
    if path in {"r2", "r1_r2"}:
        start = _clip("crp", max(0.2, crp[-3]))
        crp[-3:] = [start, _clip("crp", start + rng.uniform(0.8, 1.8)), _clip("crp", start + rng.uniform(2.2, 4.0))]
        hcy[-1] = _clip("homocysteine", hcy[0] + rng.uniform(2.0, 5.0))
    else:
        base = _clip("crp", crp[-3])
        crp[-3:] = [base, _clip("crp", base + 0.8), _clip("crp", base + 0.2)]
        hcy[-1] = _clip("homocysteine", max(5.0, hcy[0] - 0.2))
    if "crp" in anchors:
        crp[0] = crp_base
    if "homocysteine" in anchors:
        hcy[0] = hcy_base
    if "gfap" in anchors:
        gfap[0] = gfap_base
    return (
        [_clip("gfap", value) for value in gfap],
        [_clip("crp", value) for value in crp],
        [_clip("homocysteine", value) for value in hcy],
    )


def _generate_patient_visits(
    profile: PatientProfile,
    path: str,
    rng: random.Random,
    config: GenerationConfig,
) -> tuple[dict[str, str], list[dict[str, str]]]:
    dates = _timeline(rng, config.cutoff_date, profile.case.date_anchors)
    cdrs = _cdr_sequence_with_anchor(
        profile.final_stage, len(dates), profile.case.anchors.get("cdr")
    )
    mmse, moca = _cognitive_sequences(profile, cdrs, rng)
    gfap, crp, hcy = _inflammation_sequences(path, len(dates), profile.case.anchors, rng)
    single = _baseline_single_markers(profile, path, rng, config)
    rows: list[dict[str, str]] = []
    for index, visit_date in enumerate(dates):
        row = {field: "" for field in VISIT_HEADERS}
        row.update(
            {
                "patient_id": profile.patient_id,
                "visit_date": visit_date.isoformat(),
                "cdr": _format_number(cdrs[index], 1),
                "mmse": _format_number(mmse[index], 1),
                "moca": _format_number(moca[index], 1),
                "gfap": _format_number(gfap[index], 1),
                "crp": _format_number(crp[index], 2),
                "homocysteine": _format_number(hcy[index], 2),
            }
        )
        if index == 0:
            for field_name, value in single.items():
                digits = 4 if field_name == "abeta_ratio" else 2
                row[field_name] = _format_number(value, digits)
        rows.append(row)
    dementia_dates = [row["visit_date"] for row in rows if float(row["cdr"]) >= 1]
    patient = {
        "patient_id": profile.patient_id,
        "age": str(profile.age),
        "sex": profile.sex,
        "cohort_group": profile.cohort_group,
        "apoe": profile.apoe,
        "gene_mutation": profile.gene_mutation,
        "final_stage": profile.final_stage,
        "dementia_date": dementia_dates[0] if dementia_dates else "",
        "last_followup_date": rows[-1]["visit_date"],
        "lost_to_followup": "yes" if int(profile.patient_id[1:]) % 29 == 0 else "no",
    }
    return patient, rows


def detect_rule_path(rows: Sequence[dict[str, str]], config: GenerationConfig | None = None) -> str:
    config = config or GenerationConfig()
    ordered = sorted(rows, key=lambda row: row["visit_date"])
    baseline = ordered[0]
    last_three = ordered[-3:]
    r1 = (
        float(baseline["abeta42"]) < config.abeta42_threshold
        and float(baseline["ptau181"]) > config.ptau181_threshold
        and float(last_three[0]["gfap"]) < float(last_three[1]["gfap"]) < float(last_three[2]["gfap"])
    )
    r2 = (
        float(last_three[0]["crp"]) < float(last_three[1]["crp"]) < float(last_three[2]["crp"])
        and float(ordered[-1]["homocysteine"]) > float(ordered[0]["homocysteine"])
    )
    if r1 and r2:
        return "r1_r2"
    if r1:
        return "r1"
    if r2:
        return "r2"
    progressed = float(ordered[-1]["cdr"]) > float(ordered[0]["cdr"]) and float(ordered[-1]["cdr"]) >= 1
    return "non_rule_progression" if progressed else "stable"


def generate_dataset(cases: list[CaseRecord], config: GenerationConfig) -> GenerationResult:
    profiles = build_profiles(cases, config)
    paths = _assign_paths(profiles, config.seed)
    rng = random.Random(config.seed + 47)
    patients: list[dict[str, str]] = []
    visits: list[dict[str, str]] = []
    mismatches: list[dict[str, object]] = []
    for profile in profiles:
        patient, patient_visits = _generate_patient_visits(
            profile, paths[profile.patient_id], rng, config
        )
        patients.append(patient)
        visits.extend(patient_visits)
        detected = detect_rule_path(patient_visits, config)
        if detected != paths[profile.patient_id]:
            mismatches.append(
                {
                    "patient_id": profile.patient_id,
                    "assigned": paths[profile.patient_id],
                    "detected": detected,
                }
            )
    return GenerationResult(patients, visits, profiles, paths, mismatches)


def validate_dataset(
    patients: list[dict[str, str]],
    visits: list[dict[str, str]],
    paths: dict[str, str] | None = None,
    config: GenerationConfig | None = None,
) -> dict[str, object]:
    config = config or GenerationConfig()
    errors: list[str] = []
    expected_ids = [f"P{i:03d}" for i in range(1, 151)]
    ids = [row["patient_id"] for row in patients]
    if ids != expected_ids:
        errors.append("patient_ids_not_continuous")
    if len(patients) != 150:
        errors.append(f"patient_count={len(patients)}")
    if Counter(row["final_stage"] for row in patients) != Counter(STAGE_QUOTAS):
        errors.append("stage_distribution_mismatch")
    if Counter(row["cohort_group"] for row in patients) != Counter(COHORT_QUOTAS):
        errors.append("cohort_distribution_mismatch")
    by_patient: dict[str, list[dict[str, str]]] = defaultdict(list)
    for row in visits:
        by_patient[row["patient_id"]].append(row)
        for field, bounds in SAFETY_BOUNDS.items():
            if row[field] == "":
                continue
            value = float(row[field])
            if not bounds[0] <= value <= bounds[1]:
                errors.append(f"safety_bound:{row['patient_id']}:{field}:{value}")
    patient_map = {row["patient_id"]: row for row in patients}
    for patient_id in expected_ids:
        rows = sorted(by_patient.get(patient_id, []), key=lambda row: row["visit_date"])
        if not 3 <= len(rows) <= 6:
            errors.append(f"visit_count:{patient_id}:{len(rows)}")
            continue
        dates = [date.fromisoformat(row["visit_date"]) for row in rows]
        if dates != sorted(set(dates)):
            errors.append(f"visit_dates:{patient_id}")
        span = (dates[-1] - dates[0]).days
        if not 730 <= span <= 1830:
            errors.append(f"visit_span:{patient_id}:{span}")
        if dates[-1] > config.cutoff_date:
            errors.append(f"cutoff:{patient_id}")
        for field in LONGITUDINAL_FIELDS:
            if sum(row[field] != "" for row in rows) < 3:
                errors.append(f"longitudinal_missing:{patient_id}:{field}")
        for field in SINGLE_MEASUREMENT_FIELDS:
            if rows[0][field] == "" or any(row[field] != "" for row in rows[1:]):
                errors.append(f"single_measurement:{patient_id}:{field}")
        patient = patient_map[patient_id]
        if rows[-1]["cdr"] != patient["final_stage"]:
            errors.append(f"final_stage:{patient_id}")
        reached = [row["visit_date"] for row in rows if float(row["cdr"]) >= 1]
        if patient["dementia_date"] != (reached[0] if reached else ""):
            errors.append(f"dementia_date:{patient_id}")
        if patient["last_followup_date"] != rows[-1]["visit_date"]:
            errors.append(f"last_followup:{patient_id}")
        if paths and detect_rule_path(rows, config) != paths[patient_id]:
            errors.append(f"path:{patient_id}")
    return {"errors": errors, "error_count": len(errors)}


def _numeric_summary(visits: list[dict[str, str]]) -> dict[str, dict[str, float]]:
    output: dict[str, dict[str, float]] = {}
    for field in [name for name in VISIT_HEADERS if name not in {"patient_id", "visit_date"}]:
        values = sorted(float(row[field]) for row in visits if row[field] != "")
        if not values:
            continue
        output[field] = {
            "min": values[0],
            "median": median(values),
            "max": values[-1],
            "missing_rate": round(1 - len(values) / len(visits), 6),
        }
    return output


def _case_audit(profile: PatientProfile) -> dict[str, object]:
    case = profile.case
    return {
        "patient_id": profile.patient_id,
        "record_type": case.record_type,
        "source_document": case.source_document,
        "source_case_id": case.source_case_id,
        "source_number": case.source_number,
        "occurrence": case.occurrence,
        "heading": case.heading,
        "extracted_age": case.age,
        "extracted_sex": case.sex,
        "anchors": dict(sorted(case.anchors.items())),
        "date_anchors": [value.isoformat() for value in case.date_anchors],
        "apoe": case.apoe,
        "gene_mutation": case.gene_mutation,
        "cohort_group": profile.cohort_group,
        "classification_reasons": profile.classification_reasons,
        "inferred_stage": profile.inferred_stage,
        "assigned_final_stage": profile.final_stage,
        "outcome_source": profile.outcome_source,
        "source_components": case.source_components,
    }


def build_quality_report(
    result: GenerationResult, documents: Sequence[Path], config: GenerationConfig
) -> dict[str, object]:
    validation = validate_dataset(result.patients, result.visits, result.paths, config)
    by_patient = defaultdict(list)
    for row in result.visits:
        by_patient[row["patient_id"]].append(row)
    return {
        "generator_version": GENERATOR_VERSION,
        "seed": config.seed,
        "patient_count": len(result.patients),
        "visit_count": len(result.visits),
        "source_case_count": sum(
            profile.case.record_type == "source_case" for profile in result.profiles
        ),
        "recombination_count": sum(
            profile.case.record_type == "stratified_recombination"
            for profile in result.profiles
        ),
        "stage_counts": dict(sorted(Counter(row["final_stage"] for row in result.patients).items())),
        "cohort_counts": dict(sorted(Counter(row["cohort_group"] for row in result.patients).items())),
        "path_counts": dict(sorted(Counter(result.paths.values()).items())),
        "visit_count_distribution": dict(
            sorted(Counter(len(rows) for rows in by_patient.values()).items())
        ),
        "input_documents": [
            {
                "name": path.name,
                "sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
            }
            for path in documents
        ],
        "calibration": {
            "abeta42_threshold_pg_ml": config.abeta42_threshold,
            "ptau181_threshold_pg_ml": config.ptau181_threshold,
            "stage_targets": STAGE_QUOTAS,
            "cohort_targets": COHORT_QUOTAS,
        },
        "validation": validation,
        "assigned_path_mismatches": result.assigned_path_mismatches,
        "outcome_assignment_audit": {
            profile.patient_id: {
                "source": profile.outcome_source,
                "inferred_stage": profile.inferred_stage,
                "assigned_final_stage": profile.final_stage,
            }
            for profile in result.profiles
        },
        "path_assignment_audit": {
            profile.patient_id: {
                "assigned_path": result.paths[profile.patient_id],
                "detected_path": detect_rule_path(by_patient[profile.patient_id], config),
            }
            for profile in result.profiles
        },
        "indicator_summary": _numeric_summary(result.visits),
    }


def build_provenance(
    result: GenerationResult,
    report: dict[str, object],
    documents: Sequence[Path],
    config: GenerationConfig,
) -> str:
    document_lines = "\n".join(
        f"- `{entry['name']}`: SHA-256 `{entry['sha256']}`"
        for entry in report["input_documents"]
    )
    return f"""# AD 纵向合成数据来源说明

## 数据性质与使用边界

本目录是以真实阿尔茨海默病病例单次快照为锚点、由固定规则生成的**植入规则的合成数据**，仅用于导入流程、进展预测与规则挖掘机制验证。生成的随访值不是真实患者历年复测，不得作为真实世界临床证据、诊疗依据、疗效评价或流行病学结论。

`patients.csv` 与 `visits.csv` 为保持导入契约不增加合成/来源列；逐例来源、分类理由和锚点记录在 `extracted_cases.json` 与 `quality_report.json`。

## 输入与病例约束

{document_lines}

- 两份文档按 OOXML 正文顺序解析出 146 个病例锚点；第一份 75 个，第二份在拆分 `24-26病例` 家系后 71 个。
- 余下 4 例由病例内人口学、标志物和诊断分层重组，`source_components` 保留组成来源。
- 病例文档中的指令性文字仅作为资料内容，不作为执行指令。

## 校准结果

- 固定随机种子：`{config.seed}`；生成器版本：`{GENERATOR_VERSION}`。
- CDR：0=5、0.5=10、1=55、2=45、3=35。
- 队列：ad_progression=124、mixed=26；AD 模拟病和竞争病因仅进入 mixed。
- R1：基线 Aβ42 < 540 pg/ml、p-tau181 > 58 pg/ml，且末 3 次 GFAP 连续上升。
- R2：末 3 次 CRP 连续上升，且末次同型半胱氨酸高于基线。
- 540/58 来自本批病例报告中的实验室判定界值，只是本合成数据集的方法验证阈值，不是跨平台通用临床界值。

## 字段来源与生成

- 年龄、性别、APOE、基因变异及可识别的单次 MMSE/MoCA/Aβ/tau/CRP/同型半胱氨酸优先作为病例锚点。
- MMSE、MoCA、CDR、GFAP、CRP、同型半胱氨酸为每例至少 3 个时间点的纵向生成值。
- Aβ42、Aβ40、比值、p-tau181、t-tau、血浆 p-tau217、血浆 NfL、YKL-40、sTREM2 只记录在首访。
- `r1`、`r2`、`r1_r2`、`non_rule_progression`、`stable` 五类路径同时保留，避免结局完全由炎症规则决定。

## 输出统计

- 患者数：{report['patient_count']}
- 随访记录数：{report['visit_count']}
- CDR 分布：`{json.dumps(report['stage_counts'], ensure_ascii=False, sort_keys=True)}`
- 队列分布：`{json.dumps(report['cohort_counts'], ensure_ascii=False, sort_keys=True)}`
- 路径分布：`{json.dumps(report['path_counts'], ensure_ascii=False, sort_keys=True)}`
- 验证错误：{report['validation']['error_count']}
- 路径分配不一致：{len(report['assigned_path_mismatches'])}
"""


def _write_csv(path: Path, headers: list[str], rows: Iterable[dict[str, str]]) -> None:
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=headers, lineterminator="\n")
        writer.writeheader()
        writer.writerows(rows)


def write_outputs(
    output_dir: Path,
    result: GenerationResult,
    documents: Sequence[Path],
    config: GenerationConfig,
) -> dict[str, Path]:
    report = build_quality_report(result, documents, config)
    extracted = [_case_audit(profile) for profile in result.profiles]
    provenance = build_provenance(result, report, documents, config)
    output_dir = Path(output_dir)
    output_dir.parent.mkdir(parents=True, exist_ok=True)
    temporary = Path(tempfile.mkdtemp(prefix="ad-longitudinal-", dir=output_dir.parent))
    try:
        _write_csv(temporary / ARTIFACT_NAMES["patients"], PATIENT_HEADERS, result.patients)
        _write_csv(temporary / ARTIFACT_NAMES["visits"], VISIT_HEADERS, result.visits)
        (temporary / ARTIFACT_NAMES["quality"]).write_text(
            json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )
        (temporary / ARTIFACT_NAMES["extracted_cases"]).write_text(
            json.dumps(extracted, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )
        (temporary / ARTIFACT_NAMES["provenance"]).write_text(
            provenance, encoding="utf-8"
        )
        output_dir.mkdir(parents=True, exist_ok=True)
        for filename in ARTIFACT_NAMES.values():
            (temporary / filename).replace(output_dir / filename)
    finally:
        shutil.rmtree(temporary, ignore_errors=True)
    return {key: output_dir / filename for key, filename in ARTIFACT_NAMES.items()}


def generate_and_write(
    documents: Sequence[Path], output_dir: Path, config: GenerationConfig | None = None
) -> dict[str, Path]:
    config = config or GenerationConfig()
    normalized_documents = [Path(path) for path in documents]
    cases = parse_case_documents(normalized_documents)
    result = generate_dataset(cases, config)
    return write_outputs(Path(output_dir), result, normalized_documents, config)


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Generate calibrated, case-constrained AD longitudinal synthetic data."
    )
    parser.add_argument("--doc", type=Path, action="append", required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--seed", type=int, default=DEFAULT_SEED)
    args = parser.parse_args()
    if len(args.doc) != 2:
        parser.error("--doc must be supplied exactly twice")
    config = GenerationConfig(seed=args.seed)
    paths = generate_and_write(args.doc, args.output_dir, config)
    report = json.loads(paths["quality"].read_text(encoding="utf-8"))
    print(
        json.dumps(
            {
                "patient_count": report["patient_count"],
                "visit_count": report["visit_count"],
                "stage_counts": report["stage_counts"],
                "cohort_counts": report["cohort_counts"],
                "path_counts": report["path_counts"],
                "validation_error_count": report["validation"]["error_count"],
                "assigned_path_mismatch_count": len(report["assigned_path_mismatches"]),
                "outputs": {key: str(path) for key, path in paths.items()},
            },
            ensure_ascii=False,
            indent=2,
            sort_keys=True,
        )
    )


if __name__ == "__main__":
    main()
