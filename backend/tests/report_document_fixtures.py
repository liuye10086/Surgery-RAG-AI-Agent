from app.schemas.report_document import ReportDocument

SECTION_TITLES = [
    "报告摘要",
    "病例与预测范围",
    "数据质量与适用性",
    "已观察到的纵向变化",
    "未来 365 天进展风险",
    "阶段模型和下一次随访趋势的可用状态",
    "关键进展信号",
    "参考标准和相似病例",
    "不确定性与局限性",
    "人工复核重点",
    "模型和数据技术附录",
]


def snapshot_payload(disease="fatty_liver"):
    ad = disease == "ad"
    return {
        "generation_batch_id": "11111111-1111-4111-8111-111111111111",
        "anonymous_case_code": "CASE-ABCD-2345",
        "case_id": 1,
        "disease_id": 2 if ad else 1,
        "disease_code": disease,
        "disease": "阿尔茨海默病" if ad else "脂肪肝",
        "age": 62,
        "sex": "female",
        "baseline_stage": "mci" if ad else "pre_cirrhosis",
        "indicator_catalog_version": "a" * 64,
        "visits": [
            {
                "visit_date": day,
                "visit_index": i,
                "visit_context": {},
                "notes": None,
                "indicators": [
                    {
                        "name": "mmse" if ad else "alt",
                        "unit": "分" if ad else "U/L",
                        "value": float(29 - i if ad else 20 + i),
                    }
                ],
            }
            for i, day in enumerate(["2025-01-01", "2025-01-02", "2025-09-07"], 1)
        ],
    }


def context_payload():
    return {
        "disease_code": "fatty_liver",
        "release_set_id": "fixture-release",
        "release_set_sha256": "b" * 64,
        "data_release_id": "fixture-data",
        "dataset_manifest_sha256": "c" * 64,
        "split_sha256": "d" * 64,
        "indicator_catalog_sha256": "a" * 64,
        "minimum_visits": 3,
        "minimum_signal_observations": 3,
        "standard_rules_sha256": "5" * 64,
        "indicator_labels": [
            {
                "code": "alt",
                "label": "谷丙转氨酶",
                "allowed_units": ["U/L"],
                "context_requirements": [],
            }
        ],
        "evidence_token": {
            "standard": {
                "standard_id": 1,
                "version_id": 2,
                "document_id": 3,
                "document_sha256": "e" * 64,
                "version_sha256": "f" * 64,
            },
            "dataset_release_id": "fixture-reference",
            "data_content_sha256": "1" * 64,
            "eligibility_config_hash": "2" * 64,
            "similarity_config_hash": "3" * 64,
            "logical_dataset": "fatty_liver",
        },
    }


def document_payload():
    document = ReportDocument(
        identity={
            "report_id": 17,
            "batch_id": "11111111-1111-4111-8111-111111111111",
            "anonymous_case_code": "CASE-ABCD-2345",
            "disease_code": "fatty_liver",
            "disease_name": "脂肪肝",
            "age": 62,
            "sex": "female",
            "baseline_stage": "pre_cirrhosis",
            "baseline_stage_label": "未肝硬化阶段",
            "created_at": "2026-09-07T00:00:00Z",
            "anchor_date": "2025-09-07",
            "horizon_days": 365,
            "prediction_end_date": "2026-09-07",
        },
        generation_context=context_payload(),
        summary={
            "observation_status": "available",
            "model_input_status": "unavailable",
            "selected_model_count": 0,
            "invoked_model_count": 0,
            "available_model_count": 0,
            "signal_count": 0,
            "evidence_status": "complete",
            "limitations": [],
        },
        data_quality=[],
        model_runs=[],
        review_items=[],
        charts=[],
        evidence={
            "evidence_bundle_id": "22222222-2222-4222-8222-222222222222",
            "evidence_snapshot_sha256": "4" * 64,
        },
        sections=[
            {"number": i, "title": title, "paragraphs": [], "tables": []}
            for i, title in enumerate(SECTION_TITLES, 1)
        ],
    )
    return document.model_dump(mode="json")


def demo_inputs(disease="fatty_liver", *, bad_trend=False):
    from app.services.disease_progression import AD_ADAPTER, FATTY_LIVER_ADAPTER
    from app.services.report_input_audit import run_audited_prediction
    from app.services.evidence_bundle import (
        finalize_evidence_bundle,
        EvidenceBuildResult,
        build_sources_projection,
    )
    from app.schemas.longitudinal_evidence import EvidenceBundle
    from backend.tests.test_longitudinal_prediction_contract import _complete_ad_suite
    from backend.tests.test_evidence_bundle_service import _bundle
    from app.schemas.report_document import ReportGenerationContext

    snapshot = snapshot_payload(disease)
    adapter = AD_ADAPTER if disease == "ad" else FATTY_LIVER_ADAPTER
    suite = _complete_ad_suite(bad_mmse=bad_trend)
    if disease == "fatty_liver":
        suite = suite.model_copy(deep=True)
        suite.dataset = disease
        for entry in [*suite.outcomes.values(), suite.stage, *suite.trends.values()]:
            task = (
                entry.metadata.task.replace("ad.", "fatty_liver.")
                .replace("pre_dementia_to_dementia", "pre_cirrhosis_to_progression")
                .replace(".mmse", ".alt")
                .replace(".moca", ".ast")
            )
            entry.metadata.task = task
            entry.metadata.dataset = disease
            entry.status.task = task
            entry.metadata.target = (
                entry.metadata.target.replace("dementia", "cirrhosis_or_hcc")
                .replace(":mmse", ":alt")
                .replace(":moca", ":ast")
            )
            entry.status.target = entry.metadata.target
            contract = entry.metadata.feature_contract
            for key in (
                "feature_names",
                "required_features",
                "allowed_missing_features",
                "numeric_features",
                "categorical_features",
            ):
                values = getattr(contract, key, None)
                if values is not None:
                    setattr(
                        contract,
                        key,
                        [
                            v.replace("mmse.", "alt.").replace("moca.", "ast.")
                            for v in values
                        ],
                    )
        suite.stage.model.prediction = "cirrhosis"
        suite.stage.model.classes_ = ["pre_cirrhosis", "cirrhosis", "hcc"]
        suite.trends = {
            key.replace("mmse", "alt").replace("moca", "ast"): entry
            for key, entry in suite.trends.items()
        }
        suite.outcomes = {
            entry.metadata.task: entry for entry in suite.outcomes.values()
        }
    audited = run_audited_prediction(snapshot, adapter, suite)
    raw = _bundle().model_dump(mode="json")
    raw.update(
        disease_code=disease, generation_batch_id=snapshot["generation_batch_id"]
    )
    raw["reference_cases"]["data_release"]["logical_dataset"] = disease
    raw["standard"]["document"]["title"] = (
        "认知量表适用条件测试标准" if disease == "ad" else "检验范围测试标准"
    )
    raw["standard"]["rules"] = [
        {
            "rule_id": 1,
            "indicator": "mmse" if disease == "ad" else "alt",
            "display_name": "简易精神状态检查" if disease == "ad" else "谷丙转氨酶",
            "status": "missing_context" if disease == "ad" else "calculable",
            "machine_actionability": "evidence-only"
            if disease == "ad"
            else "calculable",
            "unit": "分" if disease == "ad" else "U/L",
            "conditions": {
                "status": "missing" if disease == "ad" else "matched",
                "missing": ["scale_version"] if disease == "ad" else [],
            },
            "source": {
                "segment_id": 1,
                "raw_text": "匿名软件测试夹具，不用于医学判断。",
            },
        }
    ]
    bundle = finalize_evidence_bundle(EvidenceBundle.model_validate(raw))
    evidence = EvidenceBuildResult(
        bundle, "complete", tuple(build_sources_projection(bundle))
    )
    audited.prediction["evidence"]["sources"] = list(evidence.sources_projection)
    context = context_payload()
    context.update(
        disease_code=disease,
        release_set_id=suite.release_set_id,
        release_set_sha256=suite.release_set_sha256,
        data_release_id=suite.data_release_id,
        split_sha256=suite.split_sha256,
    )
    context["evidence_token"]["standard"].update(
        document_id=bundle.standard.document.document_id,
        document_sha256=bundle.standard.document.content_sha256,
        version_sha256=bundle.standard.version.content_sha256,
    )
    context["evidence_token"].update(
        dataset_release_id="r1",
        data_content_sha256="c" * 64,
        logical_dataset=disease,
        similarity_config_hash="d" * 64,
    )
    if disease == "ad":
        context["indicator_labels"] = [
            {
                "code": "mmse",
                "label": "简易精神状态检查",
                "allowed_units": ["分"],
                "context_requirements": ["scale_version"],
            }
        ]
    return snapshot, ReportGenerationContext.model_validate(context), audited, evidence


def build_demo_document(disease="fatty_liver", **kwargs):
    from datetime import datetime, timezone
    from app.services.report_document_builder import build_report_document

    snapshot, context, audited, evidence = demo_inputs(disease, **kwargs)
    return build_report_document(
        17,
        datetime(2026, 9, 7, tzinfo=timezone.utc),
        snapshot,
        context,
        audited.prediction,
        audited.model_runs,
        evidence,
    )
