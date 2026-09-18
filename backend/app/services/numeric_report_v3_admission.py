"""Pin complete mixed bundle and strictly validated input before admission."""
import hashlib

from app.core.config import settings
from app.schemas.numeric_prediction import NumericInput
from app.schemas.numeric_report_v3 import NumericGenerationContextV3, numeric_v3_algorithms
from app.services.numeric_model_dispatch import load_configured_numeric_bundle
from app.services.numeric_report_evidence import capture_numeric_references
from app.services.numeric_report_publication import _saved_input_sha256
from app.services.numeric_report_v2_admission import current_numeric_retrieval_settings


def capture_numeric_v3_context(snapshot, db):
    from app.services.numeric_report_narrative_v2 import PROMPT, PROMPT_VERSION
    numeric = NumericInput.model_validate(snapshot['numeric_input'])
    if numeric.source.source_kind != 'synthetic':
        raise ValueError('numeric_history_synthetic_required')
    if (snapshot.get('schema_version') != 'numeric_report_input.v1'
            or snapshot.get('report_kind') != 'numeric_prediction'
            or snapshot.get('disease_code') != numeric.disease_code):
        raise ValueError('numeric_context_identity_mismatch')
    bundle = load_configured_numeric_bundle()
    if bundle is None or bundle.schema_version != 'numeric_model_bundle.v2':
        raise ValueError('numeric_history_bundle_required')
    algorithm, tasks = numeric_v3_algorithms(bundle)
    return NumericGenerationContextV3(disease_code=numeric.disease_code, numeric_input=numeric,
        numeric_input_sha256=_saved_input_sha256(numeric), source_binding_sha256=snapshot['source_binding_sha256'],
        model_bundle=bundle, algorithm=algorithm, task_algorithms=tasks,
        references=capture_numeric_references(db, numeric), llm_model=settings.DEEPSEEK_MODEL,
        prompt_text=PROMPT, prompt_sha256=hashlib.sha256(PROMPT.encode('utf-8')).hexdigest(),
        prompt_version=PROMPT_VERSION, retrieval_settings=current_numeric_retrieval_settings())


def evaluate_numeric_v3_readiness(case, db):
    from app.services.numeric_model_dispatch import evaluate_configured_numeric_readiness
    return evaluate_configured_numeric_readiness(case, db)
