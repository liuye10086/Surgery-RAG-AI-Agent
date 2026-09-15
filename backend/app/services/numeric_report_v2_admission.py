"""Pin model parameters and reference catalog before admitting a new report."""
import hashlib
from app.core.config import settings
from app.schemas.numeric_report_v2 import NumericGenerationContextV2, NumericRetrievalSettings
from app.schemas.numeric_prediction import NumericInput
from app.schemas.operator_case_workspace import OperatorCaseReportReadiness, OperatorCaseReadinessBlocker
from app.services.numeric_model_bundle import load_numeric_model_bundle, trained_numeric_algorithm, verify_numeric_bundle_runtime
from app.services.numeric_report_evidence import capture_numeric_references
from app.services.numeric_report_admission import build_numeric_snapshot
from app.services.numeric_report_publication import _saved_input_sha256
from app.services.report_generation_errors import ReportJobError


def capture_numeric_v2_context(snapshot, db):
    from app.services.numeric_report_narrative import PROMPT
    numeric = NumericInput.model_validate(snapshot['numeric_input'])
    bundle = load_numeric_model_bundle(settings.NUMERIC_MODEL_BUNDLE)
    verify_numeric_bundle_runtime(bundle)
    return NumericGenerationContextV2(disease_code=numeric.disease_code,
        numeric_input_sha256=_saved_input_sha256(numeric), source_binding_sha256=snapshot['source_binding_sha256'],
        model_bundle=bundle, algorithm=trained_numeric_algorithm(bundle),
        references=capture_numeric_references(db, numeric), llm_model=settings.DEEPSEEK_MODEL,
        prompt_text=PROMPT,prompt_sha256=hashlib.sha256(PROMPT.encode('utf-8')).hexdigest(),
        retrieval_settings=current_numeric_retrieval_settings())


def current_numeric_retrieval_settings():
    return NumericRetrievalSettings(embedding_model=settings.EMBEDDING_MODEL,collection_name=settings.VECTOR_COLLECTION_NAME,
        rrf_k=settings.RETRIEVER_FUSION_K,vector_top_k=settings.RETRIEVER_TOP_K_VECTOR,
        fulltext_top_k=settings.RETRIEVER_TOP_K_FULLTEXT,final_top_k=settings.RETRIEVER_FINAL_TOP_K)


def evaluate_numeric_v2_readiness(case, db):
    blockers = []
    try:
        capture_numeric_v2_context(build_numeric_snapshot(case), db)
        if not settings.DEEPSEEK_API_KEY:
            raise ValueError('numeric_narrative_configuration_missing')
    except ReportJobError as error:
        blockers.append(OperatorCaseReadinessBlocker(code=error.code, message=error.message))
    except (ValueError, OSError):
        blockers.append(OperatorCaseReadinessBlocker(code='model_unavailable', message='数值预测模型或说明生成配置不可用'))
    ready = not blockers
    return OperatorCaseReportReadiness(ready=ready, case_ready=ready, timeline_ready=ready,
        model_ready=ready, visit_count=len(case.visits), minimum_visits=1, blockers=blockers)
