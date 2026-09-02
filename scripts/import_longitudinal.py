"""纵向数据集导入 AI 操作者端 case_records。

每访视一行快照：每位患者的每次 visit 导入为一条 CaseRecord，
patient_label = patient_id，indicators 为该次访视非空指标，
case_metadata 承载 visit_date/结局/人口学/溯源语义。

支持幂等重跑（同一 (source_dataset, patient_label, visit_date) 不重复插入）
与 --reset（按 source_dataset 删除已导入行后重导）。

用法:
    python scripts/import_longitudinal.py [--dataset fatty_liver|ad|all] [--reset] [--db-url URL]
"""
import argparse
import csv
import json
import sys
from collections import defaultdict
from pathlib import Path

IMPORT_VERSION = "1.0.0"

DATASETS = {
    "fatty_liver": {
        "dir": "data/generated/longitudinal_300",
        "disease_code": "fatty_liver",
        "synthetic_from": 151,  # P151-P300 为分层重组合成（见 DATA_PROVENANCE）
        "final_stage_fields": {"cirrhosis", "hcc"},
    },
    "ad": {
        "dir": "data/generated/ad_longitudinal_300",
        "disease_code": "ad",
        "synthetic_from": 151,
        "final_stage_fields": None,  # final_stage 为 CDR 分级数值
    },
}

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
if str(ROOT / "backend") not in sys.path:
    sys.path.insert(0, str(ROOT / "backend"))


def load_patients(csv_path: Path) -> list[dict]:
    with csv_path.open(encoding="utf-8", newline="") as handle:
        return list(csv.DictReader(handle))


def load_visits(csv_path: Path) -> list[dict]:
    with csv_path.open(encoding="utf-8", newline="") as handle:
        return list(csv.DictReader(handle))


def load_source_documents(dataset_dir: Path) -> dict[str, str]:
    """从 extracted_cases.json 读取 patient_id -> source_document 溯源映射。

    仅当该条记录存在非空 source_document 时才收录（合成病例无原始文档；
    脂肪肝数据集 extracted_cases.json 不含该字段，返回空字典）。
    """
    path = dataset_dir / "extracted_cases.json"
    if not path.is_file():
        return {}
    with path.open(encoding="utf-8") as handle:
        records = json.load(handle)
    return {
        record["patient_id"]: record["source_document"]
        for record in records
        if record.get("patient_id") and record.get("source_document")
    }


def group_visits_by_patient(visits: list[dict]) -> dict[str, list[dict]]:
    grouped: dict[str, list[dict]] = defaultdict(list)
    for row in visits:
        grouped[row["patient_id"]].append(row)
    return dict(grouped)


def build_indicators(visit_row: dict, dataset: str) -> list[dict]:
    """从单次访视行构造 indicators，只保留非空字段。

    visit_row 中的 patient_id/visit_date 被排除；其余列名作为指标名。
    """
    from app.services.indicator_validation import (
        default_unit,
        validate_indicators,
    )

    indicators = []
    for name, value in visit_row.items():
        if name in ("patient_id", "visit_date"):
            continue
        if value is None or value == "":
            continue
        indicators.append(
            {
                "name": name,
                "value": float(value),
                "unit": default_unit(dataset, name),
            }
        )
    validate_indicators(dataset, indicators)
    return indicators


_EVENT_DATE_FIELDS = {
    "fatty_liver": ("cirrhosis_date", "hcc_date"),
    "ad": ("dementia_date",),
}


def _to_int(value) -> int | None:
    """安全转换为 int；缺失或非法值返回 None（不抛错，年龄非核心字段）。"""
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def build_case_metadata(
    dataset: str,
    patient: dict,
    visit: dict,
    visit_index: int,
    total_visits: int,
    is_synthetic: bool,
    source_document: str | None = None,
    dataset_release_id: str | None = None,
    data_content_sha256: str | None = None,
) -> dict:
    """构造承载纵向语义的 case_metadata（JSONB）。

    source_document 仅在有原始病例文档溯源时传入（如 AD 数据集 P001-P150），
    合成病例或无该字段的数据集（如脂肪肝）不写入此键。
    """
    event_dates = {}
    for field in _EVENT_DATE_FIELDS[dataset]:
        if patient.get(field):
            event_dates[field] = patient[field]
    metadata = {
        "visit_date": visit["visit_date"],
        "visit_index": visit_index,
        "total_visits": total_visits,
        "patient_age": _to_int(patient.get("age")),
        "sex": patient.get("sex"),
        "cohort_group": patient.get("cohort_group"),
        "final_stage": patient.get("final_stage"),
        "event_dates": event_dates,
        "source_dataset": DATASETS[dataset]["dir"].split("/")[-1],
        "is_synthetic": is_synthetic,
        "import_version": IMPORT_VERSION,
    }
    if source_document:
        metadata["source_document"] = source_document
    if dataset_release_id:
        metadata["logical_dataset"] = metadata["source_dataset"]
        metadata["dataset_release_id"] = dataset_release_id
        metadata["dataset_active"] = False
    if data_content_sha256:
        metadata["data_content_sha256"] = data_content_sha256
    return metadata


def is_synthetic(dataset: str, patient_id: str) -> bool:
    """P151-P300 为分层重组合成患者（DATA_PROVENANCE 边界）。"""
    return int(patient_id[1:]) >= DATASETS[dataset]["synthetic_from"]


def should_mark_confirmed(dataset: str, final_stage: str) -> bool:
    """按最终结局标记 confirmed：进展/确诊样本为 true，stable 为 false。

    脂肪肝：final_stage ∈ {cirrhosis, hcc} → true；
    AD：final_stage 为 CDR 分级数值 ≥ 1 → true。
    """
    fields = DATASETS[dataset]["final_stage_fields"]
    if fields is not None:
        return final_stage in fields
    try:
        return float(final_stage) >= 1
    except (TypeError, ValueError):
        return False


def _existing_signatures(
    db, dataset: str
) -> set[tuple[str, str | None, str, str]]:
    """查询该数据集已导入的版本化访视签名。"""
    from app.db.models import CaseRecord

    source_dataset = DATASETS[dataset]["dir"].split("/")[-1]
    rows = (
        db.query(CaseRecord)
        .filter(CaseRecord.case_metadata.op("->>")("source_dataset") == source_dataset)
        .all()
    )
    return {
        (
            (r.case_metadata or {}).get("source_dataset"),
            (r.case_metadata or {}).get("dataset_release_id"),
            r.patient_label,
            (r.case_metadata or {}).get("visit_date"),
        )
        for r in rows
    }


def import_dataset(
    db,
    dataset: str,
    patients: list | None = None,
    visits: list | None = None,
    source_documents: dict[str, str] | None = None,
    dataset_release_id: str | None = None,
    data_content_sha256: str | None = None,
) -> dict:
    """把某数据集导入 case_records。幂等：已存在签名跳过。

    patients/visits/source_documents 可注入便于测试；缺省从 DATASETS 目录
    加载真实 CSV 与 extracted_cases.json 溯源映射。
    """
    from app.db.models import CaseRecord, Disease
    from app.services.anonymous_case_code import generate_anonymous_case_code

    cfg = DATASETS[dataset]
    dataset_dir = ROOT / cfg["dir"]
    if patients is None:
        patients = load_patients(dataset_dir / "patients.csv")
    if visits is None:
        visits = load_visits(dataset_dir / "visits.csv")
    if source_documents is None:
        source_documents = load_source_documents(dataset_dir)

    disease = db.query(Disease).filter(Disease.code == cfg["disease_code"]).first()
    if disease is None:
        raise ValueError(f"数据库中缺少疾病代码：{cfg['disease_code']}")

    existing = _existing_signatures(db, dataset)
    existing_codes = {}
    for row in db.query(CaseRecord).all():
        metadata = row.case_metadata or {}
        if metadata.get("source_dataset") == cfg["dir"].split("/")[-1] and row.patient_label:
            if row.anonymous_case_code:
                existing_codes[row.patient_label] = row.anonymous_case_code
    patient_map = {p["patient_id"]: p for p in patients}
    grouped = group_visits_by_patient(visits)
    anonymous_codes: dict[str, str] = {}

    inserted = 0
    skipped = 0
    for patient_id, patient_rows in sorted(grouped.items()):
        patient = patient_map[patient_id]
        anonymous_codes[patient_id] = existing_codes.get(patient_id) or generate_anonymous_case_code()
        ordered = sorted(patient_rows, key=lambda r: r["visit_date"])
        total = len(ordered)
        if total < 1:
            raise ValueError(f"患者 {patient_id} 至少需要 1 次访视")
        if total > 10:
            raise ValueError(f"患者 {patient_id} 最多只能导入 10 次访视")
        for index, visit in enumerate(ordered, start=1):
            signature = (
                cfg["dir"].split("/")[-1],
                dataset_release_id,
                patient_id,
                visit["visit_date"],
            )
            if signature in existing:
                skipped += 1
                continue
            record = CaseRecord(
                disease_id=disease.id,
                patient_label=patient_id,
                anonymous_case_code=anonymous_codes[patient_id],
                indicators=build_indicators(visit, dataset),
                confirmed=should_mark_confirmed(dataset, patient["final_stage"]),
                case_metadata=build_case_metadata(
                    dataset=dataset,
                    patient=patient,
                    visit=visit,
                    visit_index=index,
                    total_visits=total,
                    is_synthetic=is_synthetic(dataset, patient_id),
                    source_document=source_documents.get(patient_id),
                    dataset_release_id=dataset_release_id,
                    data_content_sha256=data_content_sha256,
                ),
            )
            db.add(record)
            existing.add(signature)
            inserted += 1

    db.flush()
    return {
        "dataset": dataset,
        "disease_id": disease.id,
        "disease_name": disease.name,
        "inserted": inserted,
        "skipped": skipped,
    }


def reset_dataset(db, dataset: str) -> int:
    """删除该数据集已导入的 case 记录（按 metadata.source_dataset 匹配）。

    删除后立即 flush：确保同一事务内紧接着的 import_dataset 查询
    （_existing_signatures，autoflush 可能被禁用）能看到删除结果，
    不会把待删记录误判为"已存在"而跳过重新插入。
    """
    from app.db.models import CaseRecord

    source_dataset = DATASETS[dataset]["dir"].split("/")[-1]
    rows = (
        db.query(CaseRecord)
        .filter(CaseRecord.case_metadata.op("->>")("source_dataset") == source_dataset)
        .all()
    )
    for r in rows:
        db.delete(r)
    db.flush()
    return len(rows)


def reset_and_import(
    db,
    dataset: str,
    reset: bool = False,
    patients: list | None = None,
    visits: list | None = None,
    source_documents: dict[str, str] | None = None,
    dataset_release_id: str | None = None,
    data_content_sha256: str | None = None,
) -> dict:
    """在同一事务内完成（可选）重置与重新导入。

    调用方负责提交/回滚：任一环节抛异常时，调用方 rollback() 即可
    同时撤销 reset 的删除和本次导入的新增，不会出现"旧数据已删、
    新数据未导入成功"的中间态。
    """
    removed = reset_dataset(db, dataset) if reset else 0
    result = import_dataset(
        db,
        dataset,
        patients=patients,
        visits=visits,
        source_documents=source_documents,
        dataset_release_id=dataset_release_id,
        data_content_sha256=data_content_sha256,
    )
    result["removed"] = removed
    return result


def _load_settings() -> str:
    """从 backend/.env 读取 DATABASE_URL；不存在则抛错。"""
    env_path = ROOT / "backend" / ".env"
    if not env_path.is_file():
        raise RuntimeError(f"未找到 {env_path}，请提供 --db-url")
    for line in env_path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if line.startswith("DATABASE_URL="):
            return line.split("=", 1)[1].strip().strip('"').strip("'")
    raise RuntimeError(f"{env_path} 中未找到 DATABASE_URL")


def parse_args(argv: list | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="导入纵向数据集到 AI 操作者端 case_records（每访视一行快照）"
    )
    parser.add_argument(
        "--dataset",
        choices=["fatty_liver", "ad", "all"],
        default="all",
        help="要导入的数据集（默认 all）",
    )
    parser.add_argument(
        "--reset",
        action="store_true",
        help="先删除该数据集已导入的 case 记录再重新导入",
    )
    parser.add_argument(
        "--db-url",
        default=None,
        help="DATABASE_URL；缺省从 backend/.env 读取",
    )
    parser.add_argument(
        "--release-id",
        default=None,
        help="显式数据 release ID；正式更新时必须与内容哈希一起提供",
    )
    parser.add_argument(
        "--data-content-sha256",
        default=None,
        help="数据 manifest 中的整体内容 SHA-256",
    )
    parser.add_argument(
        "--activate",
        action="store_true",
        help="导入成功后在同一事务内激活该数据 release",
    )
    args = parser.parse_args(argv)
    has_release_id = bool(args.release_id)
    has_content_hash = bool(args.data_content_sha256)
    if has_release_id != has_content_hash:
        parser.error("--release-id 与 --data-content-sha256 必须成对提供")
    if has_content_hash and (
        len(args.data_content_sha256) != 64
        or any(character not in "0123456789abcdefABCDEF" for character in args.data_content_sha256)
    ):
        parser.error("--data-content-sha256 必须是 64 位十六进制 SHA-256")
    if args.activate and not has_release_id:
        parser.error("--activate 必须与 --release-id 一起使用")
    if has_release_id and args.dataset == "all":
        parser.error("版本化导入必须一次明确选择一种疾病")
    return args


def main(argv: list | None = None) -> int:
    args = parse_args(argv)

    db_url = args.db_url or _load_settings()
    from sqlalchemy import create_engine
    from sqlalchemy.orm import sessionmaker

    engine = create_engine(db_url, future=True)
    Session = sessionmaker(autocommit=False, autoflush=False, bind=engine, future=True)

    names = ["fatty_liver", "ad"] if args.dataset == "all" else [args.dataset]
    for name in names:
        with Session() as db:
            try:
                result = reset_and_import(
                    db,
                    name,
                    reset=args.reset,
                    dataset_release_id=args.release_id,
                    data_content_sha256=(
                        args.data_content_sha256.lower()
                        if args.data_content_sha256
                        else None
                    ),
                )
                if args.activate:
                    from app.services.longitudinal_data_release import (
                        activate_data_release,
                    )

                    switch = activate_data_release(
                        db,
                        DATASETS[name]["dir"].split("/")[-1],
                        args.release_id,
                    )
                    result["active_release_id"] = switch.active_release_id
                    result["previous_release_id"] = switch.previous_release_id
            except Exception:
                db.rollback()
                raise
            db.commit()
            if args.reset:
                print(f"[{name}] --reset 删除 {result['removed']} 条已导入记录")
            print(
                f"[{result['dataset']}] {result['disease_name']} "
                f"(disease_id={result['disease_id']}): "
                f"新增 {result['inserted']} 条，跳过 {result['skipped']} 条"
            )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
