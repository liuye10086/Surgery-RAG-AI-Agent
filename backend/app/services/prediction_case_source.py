"""Source-neutral binding; only the explicit server CLI imports source facts."""

from pathlib import Path
import hashlib

from app.schemas.numeric_prediction import NumericInput
from app.schemas.prediction_case_source import (
    PredictionCaseSource, PredictionPackageManifest, PredictionPackageRecord,
)
from app.schemas.synthetic_numeric_prediction import SyntheticNumericInput
from app.services.numeric_prediction import numeric_input_sha256
from app.services.operator_case_validation import normalize_operator_timeline, validate_operator_case_profile
from app.services.synthetic_case_source import (
    _projection, _sha, _safe_directory, _read_file, _json,
    require_isolated_test_database as _require_isolated_test_database, validate_engineering_case,
)


class PredictionCaseSourceError(ValueError):
    def __init__(self, code):
        super().__init__(code)
        self.code = code


def require_isolated_test_database(url):
    try:
        _require_isolated_test_database(url)
    except ValueError as exc:
        raise PredictionCaseSourceError('isolated_test_database_required') from exc


def _numeric(raw):
    return NumericInput.model_validate(raw.model_dump(mode='python') if hasattr(raw, 'model_dump') else raw)


def convert_legacy_input(raw) -> NumericInput:
    """Convert verified legacy facts in memory without overwriting their stored version."""
    old = SyntheticNumericInput.model_validate(raw.model_dump(mode='python') if hasattr(raw, 'model_dump') else raw)
    value = old.model_dump(mode='json')
    value['schema_version'] = 'numeric_input.v1'
    version = {'dataset_id': 'legacy.synthetic_prediction_cases',
               'dataset_version': old.source.generator_version}
    value['source'].update(version)
    for packet in value['packets']:
        packet['source'].update(version)
    return NumericInput.model_validate(value)


def numeric_display_visits(raw):
    numeric = _numeric(raw)
    rows = numeric.packets[0].input_observations
    if not rows:
        raise PredictionCaseSourceError('display_visits_required')
    return normalize_operator_timeline(numeric.disease_code, [
        {'visit_date': row.measured_on,
         'indicators': [{'name': row.indicator, 'value': row.value, 'unit': row.unit}],
         'visit_context': {'method': row.method}, 'notes': None} for row in rows
    ])


def build_prediction_binding(case, numeric) -> dict:
    try:
        if getattr(case, 'prediction_source', None) is not None or getattr(case, 'engineering_source', None) is not None:
            raise PredictionCaseSourceError('prediction_source_already_bound')
        numeric = _numeric(numeric)
        projection = _projection(case)
        if projection['disease_code'] != numeric.disease_code:
            raise PredictionCaseSourceError('prediction_case_disease_mismatch')
        if numeric_display_visits(numeric) != normalize_operator_timeline(numeric.disease_code, case.visits):
            raise PredictionCaseSourceError('prediction_display_input_mismatch')
        return PredictionCaseSource(
            **numeric.source.model_dump(), case_id=case.id, user_id=case.user_id,
            disease_id=case.disease_id, disease_code=numeric.disease_code,
            subject_id=numeric.subject_id, numeric_input=numeric,
            numeric_input_sha256=numeric_input_sha256(numeric), display_projection_sha256=_sha(projection),
        ).model_dump(mode='json')
    except PredictionCaseSourceError:
        raise
    except (ValueError, TypeError, AttributeError, KeyError) as exc:
        raise PredictionCaseSourceError('prediction_source_invalid') from exc


def validate_prediction_case(case) -> NumericInput:
    try:
        raw = getattr(case, 'prediction_source', None)
        if raw is None:
            if getattr(case, 'engineering_source', None) is None:
                raise PredictionCaseSourceError('prediction_source_required')
            return convert_legacy_input(validate_engineering_case(case))
        source = PredictionCaseSource.model_validate(raw)
        if (source.case_id, source.user_id, source.disease_id, source.disease_code) != (
            case.id, case.user_id, case.disease_id, case.disease.code
        ):
            raise PredictionCaseSourceError('prediction_case_identity_mismatch')
        if source.numeric_input_sha256 != numeric_input_sha256(source.numeric_input):
            raise PredictionCaseSourceError('prediction_input_hash_mismatch')
        if source.display_projection_sha256 != _sha(_projection(case)):
            raise PredictionCaseSourceError('prediction_display_hash_mismatch')
        if numeric_display_visits(source.numeric_input) != normalize_operator_timeline(source.disease_code, case.visits):
            raise PredictionCaseSourceError('prediction_display_input_mismatch')
        return source.numeric_input
    except PredictionCaseSourceError:
        raise
    except (ValueError, TypeError, AttributeError, KeyError) as exc:
        raise PredictionCaseSourceError('prediction_source_invalid') from exc


def load_prediction_case_package(package_dir: Path):
    """Explicit local package authority; hashes detect corruption, not source authenticity."""
    try:
        requested = Path(package_dir).absolute()
        directory = _safe_directory(requested, requested.parent)
        manifest_bytes = _read_file(directory, 'manifest.json')
        manifest = PredictionPackageManifest.model_validate(_json(manifest_bytes))
        content = _read_file(directory, 'records.jsonl')
        digest = hashlib.sha256(content).hexdigest()
        if (len(content), digest) != (manifest.records.bytes, manifest.records.sha256):
            raise PredictionCaseSourceError('prediction_package_file_hash_mismatch')
        rows = [_json(line) for line in content.splitlines()]
        if len(rows) != manifest.record_count:
            raise PredictionCaseSourceError('prediction_package_count_mismatch')
        source = {**manifest.source.model_dump(), 'manifest_sha256': hashlib.sha256(manifest_bytes).hexdigest(),
                  'input_file_sha256': digest}
        result, subjects, sample_ids = [], set(), set()
        for raw in rows:
            record = PredictionPackageRecord.model_validate(raw)
            if 'source' in record.numeric_input:
                raise PredictionCaseSourceError('prediction_package_source_must_be_manifest')
            numeric = NumericInput.model_validate({**record.numeric_input, 'source': source})
            ids = {packet.sample_id for packet in numeric.packets}
            if numeric.subject_id in subjects or sample_ids.intersection(ids):
                raise PredictionCaseSourceError('prediction_package_duplicate_identity')
            subjects.add(numeric.subject_id)
            sample_ids.update(ids)
            validate_operator_case_profile(numeric.disease_code, record.age, record.sex, record.baseline_stage)
            numeric_display_visits(numeric)
            result.append((record, numeric))
        return result
    except PredictionCaseSourceError:
        raise
    except (OSError, ValueError, TypeError, AttributeError, KeyError) as exc:
        raise PredictionCaseSourceError('prediction_package_invalid') from exc


def seed_prediction_cases(session_factory, package_dir: Path, user_id: int) -> list[int]:
    """Create an explicit version package and audits atomically in a caller's test DB."""
    from app.db.models import Disease, OperatorCase, OperatorCaseVisit, User
    from app.services.anonymous_case_code import generate_anonymous_case_code
    from app.services.disease_catalog import require_operator_disease
    from app.services.operator_case_audit import append_case_change_log, build_creation_changes

    with session_factory() as db:
        require_isolated_test_database(db.get_bind().url)
        if type(user_id) is not int or user_id <= 0:
            raise PredictionCaseSourceError('prediction_seed_operator_required')
        selected = load_prediction_case_package(package_dir)
        with db.begin():
            # Serialize imports by owner so concurrent calls cannot import the same source twice.
            owner = db.query(User).filter(User.id == user_id).with_for_update().first()
            if owner is None or owner.role not in {'ai_operator', 'admin'}:
                raise PredictionCaseSourceError('prediction_seed_operator_required')
            case_ids = []
            first_source = selected[0][1].source
            duplicate = db.query(OperatorCase).filter(
                OperatorCase.user_id == user_id,
                OperatorCase.prediction_source['dataset_id'].astext == first_source.dataset_id,
                OperatorCase.prediction_source['dataset_version'].astext == first_source.dataset_version,
            ).first()
            if duplicate is not None:
                raise PredictionCaseSourceError('prediction_version_already_imported')
            for patient, numeric in selected:
                disease = db.query(Disease).filter(Disease.code == numeric.disease_code).first()
                if disease is None:
                    raise PredictionCaseSourceError('prediction_seed_disease_missing')
                disease = require_operator_disease(db, disease.id, for_update=True)
                anonymous_code = None
                for _ in range(5):
                    candidate = generate_anonymous_case_code()
                    if db.query(OperatorCase).filter(OperatorCase.anonymous_case_code == candidate).first() is None:
                        anonymous_code = candidate
                        break
                if anonymous_code is None:
                    raise PredictionCaseSourceError('anonymous_case_code_generation_failed')
                case = OperatorCase(user_id=user_id, disease_id=disease.id, disease=disease,
                                    patient_label=anonymous_code, anonymous_case_code=anonymous_code,
                                    age=patient.age, sex=patient.sex, baseline_stage=patient.baseline_stage,
                                    notes=None, status='active')
                db.add(case)
                db.flush()
                timeline = numeric_display_visits(numeric)
                for visit in timeline:
                    db.add(OperatorCaseVisit(case=case, **visit.as_orm_kwargs()))
                db.flush()
                case.prediction_source = build_prediction_binding(case, numeric)
                changes = build_creation_changes(case, visit_count=len(timeline))
                changes['prediction_source'] = {
                    'source_kind': numeric.source.source_kind, 'is_synthetic': numeric.source.is_synthetic,
                    'dataset_id': numeric.source.dataset_id, 'dataset_version': numeric.source.dataset_version,
                    'numeric_input_sha256': case.prediction_source['numeric_input_sha256'],
                    'manifest_sha256': numeric.source.manifest_sha256,
                }
                append_case_change_log(db, case=case, actor_id=user_id, action='created',
                                       reason='系统：导入版本化预测病例', changes=changes)
                case_ids.append(case.id)
            return case_ids
