"""Trusted server-side input binding and explicit isolated-test seeding.

File hashes are integrity links only. Admission trust comes from this restricted
filesystem loader and server-owned transaction, never from client-supplied hashes.
"""

from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path

from sqlalchemy.engine import URL

from app.schemas.synthetic_case_source import SyntheticCaseSource, SyntheticPackageManifest
from app.schemas.synthetic_numeric_prediction import NumericPacketSource, SyntheticNumericInput
from app.schemas.synthetic_prediction_cases import PredictionInput, SyntheticPatient
from app.services.operator_case_validation import normalize_operator_timeline, validate_operator_case_profile
from app.services.synthetic_numeric_prediction import numeric_input_sha256
from app.services.synthetic_prediction_cases import canonical_json


PACKAGE_ROOT = Path(__file__).resolve().parents[3] / 'outputs' / 'synthetic-prediction-cases'


class SyntheticCaseSourceError(ValueError):
    def __init__(self, code: str):
        super().__init__(code)
        self.code = code


def _sha(value):
    return hashlib.sha256(canonical_json(value).encode('utf-8')).hexdigest()


def _numeric(raw):
    return SyntheticNumericInput.model_validate(raw.model_dump(mode='python') if hasattr(raw, 'model_dump') else raw)


def numeric_display_visits(raw):
    """Project measured input facts only; preserve missingness and method identity."""
    numeric = _numeric(raw)
    observations = numeric.packets[0].input_observations
    if not observations:
        raise SyntheticCaseSourceError('display_visits_required')
    return normalize_operator_timeline(numeric.disease_code, [
        {'visit_date': row.measured_on,
         'indicators': [{'name': row.indicator, 'value': row.value, 'unit': row.unit}],
         'visit_context': {'method': row.method}, 'notes': None}
        for row in observations
    ])


def _projection(case):
    disease_code = case.disease.code
    stage = validate_operator_case_profile(disease_code, case.age, case.sex, case.baseline_stage)
    visits = list(case.visits)
    normalized = normalize_operator_timeline(disease_code, visits)
    if any(type(getattr(case, name, None)) is not int or getattr(case, name) <= 0
           for name in ('id', 'user_id', 'disease_id')):
        raise SyntheticCaseSourceError('engineering_case_identity_missing')
    if not case.anonymous_case_code or case.patient_label != case.anonymous_case_code:
        raise SyntheticCaseSourceError('engineering_anonymous_identity_required')
    if any(type(v.id) is not int or v.id <= 0 or v.case_id != case.id for v in visits):
        raise SyntheticCaseSourceError('engineering_visit_identity_mismatch')
    ids = {v.visit_date: v.id for v in visits}
    if len(set(ids.values())) != len(visits):
        raise SyntheticCaseSourceError('engineering_visit_identity_mismatch')
    return {
        'case_id': case.id, 'user_id': case.user_id, 'disease_id': case.disease_id,
        'disease_code': disease_code, 'anonymous_case_code': case.anonymous_case_code,
        'patient_label': case.patient_label, 'age': case.age, 'sex': case.sex,
        'baseline_stage': stage, 'notes': case.notes,
        'visits': [{'id': ids[v.visit_date], **v.as_orm_kwargs(), 'visit_date': v.visit_date.isoformat()}
                   for v in normalized],
    }


def build_engineering_binding(case, numeric_input) -> dict:
    """Bind a flushed case once; callers must own the entire creation transaction."""
    try:
        if getattr(case, 'engineering_source', None) is not None:
            raise SyntheticCaseSourceError('engineering_source_already_bound')
        numeric = _numeric(numeric_input)
        projection = _projection(case)
        if projection['disease_code'] != numeric.disease_code:
            raise SyntheticCaseSourceError('engineering_case_disease_mismatch')
        expected = numeric_display_visits(numeric)
        actual = normalize_operator_timeline(numeric.disease_code, case.visits)
        if expected != actual:
            raise SyntheticCaseSourceError('engineering_display_input_mismatch')
        return SyntheticCaseSource(
            **numeric.source.model_dump(), case_id=case.id, user_id=case.user_id,
            disease_id=case.disease_id, disease_code=numeric.disease_code,
            subject_id=numeric.subject_id, numeric_input=numeric,
            numeric_input_sha256=numeric_input_sha256(numeric),
            display_projection_sha256=_sha(projection),
        ).model_dump(mode='json')
    except SyntheticCaseSourceError:
        raise
    except (ValueError, TypeError, AttributeError, KeyError) as exc:
        raise SyntheticCaseSourceError('engineering_source_invalid') from exc


def validate_engineering_case(case) -> SyntheticNumericInput:
    """Verify persisted binding without reopening source files or executing models."""
    try:
        source = SyntheticCaseSource.model_validate(getattr(case, 'engineering_source', None))
        if (source.case_id, source.user_id, source.disease_id, source.disease_code) != (
            case.id, case.user_id, case.disease_id, case.disease.code
        ):
            raise SyntheticCaseSourceError('engineering_case_identity_mismatch')
        if source.numeric_input_sha256 != numeric_input_sha256(source.numeric_input):
            raise SyntheticCaseSourceError('engineering_input_hash_mismatch')
        if source.display_projection_sha256 != _sha(_projection(case)):
            raise SyntheticCaseSourceError('engineering_display_hash_mismatch')
        return source.numeric_input
    except SyntheticCaseSourceError:
        raise
    except (ValueError, TypeError, AttributeError, KeyError) as exc:
        raise SyntheticCaseSourceError('engineering_source_invalid') from exc


def require_isolated_test_database(url):
    """Inspect the actual engine URL, including libpq host/service overrides."""
    if (any(os.environ.get(name) for name in ('PGHOSTADDR', 'PGSERVICE'))
            or not isinstance(url, URL) or url.get_backend_name() != 'postgresql'
            or url.host not in {'localhost', '127.0.0.1', '::1'}
            or not url.database or not url.database.endswith('_test') or url.query):
        raise SyntheticCaseSourceError('isolated_test_database_required')


def _safe_directory(package_dir, trusted_root):
    root = Path(trusted_root).absolute()
    candidate = Path(package_dir).absolute()
    try:
        candidate.relative_to(root)
        if candidate == root or not candidate.is_dir():
            raise ValueError('invalid_directory')
        # Windows directory junctions are reparse points too; reject every path component.
        for component in (candidate, *candidate.parents):
            if component.is_symlink() or getattr(component.lstat(), 'st_file_attributes', 0) & 0x400:
                raise ValueError('linked_directory')
        candidate.resolve(strict=True).relative_to(root.resolve(strict=True))
    except (OSError, ValueError) as exc:
        raise SyntheticCaseSourceError('synthetic_package_path_invalid') from exc
    return candidate


def _read_file(directory, name):
    path = directory / name
    if (path.is_symlink() or not path.is_file()
            or getattr(path.lstat(), 'st_file_attributes', 0) & 0x400):
        raise SyntheticCaseSourceError('synthetic_package_file_invalid')
    return path.read_bytes()


def _json(data):
    def unique_pairs(pairs):
        result = {}
        for key, value in pairs:
            if key in result:
                raise ValueError('duplicate_json_key')
            result[key] = value
        return result
    return json.loads(data, object_pairs_hook=unique_pairs)


def load_synthetic_case_package(package_dir: Path, subject_ids: list[str], *, trusted_root: Path | None = None):
    """Read manifest, patients, and prediction inputs only. No outcome files are opened."""
    try:
        if (not subject_ids or any(not isinstance(s, str) or not s.strip() for s in subject_ids)
                or len(set(subject_ids)) != len(subject_ids)):
            raise SyntheticCaseSourceError('explicit_unique_subjects_required')
        directory = _safe_directory(package_dir, PACKAGE_ROOT if trusted_root is None else trusted_root)
        manifest_bytes = _read_file(directory, 'manifest.json')
        manifest = SyntheticPackageManifest.model_validate(_json(manifest_bytes))
        identity = _sha({'generator_version': manifest.generator_version,
                         'config': manifest.config.model_dump(), 'source_sha256': manifest.source_sha256})
        if (manifest.run_identity_sha256, manifest.run_id) != (identity, 'syn-' + identity[:16]):
            raise SyntheticCaseSourceError('synthetic_package_run_mismatch')
        if _sha({name: value.model_dump() for name, value in manifest.files.items()}) != manifest.data_content_sha256:
            raise SyntheticCaseSourceError('synthetic_package_manifest_hash_mismatch')
        raw = {}
        file_hashes = {}
        for name in ('patients', 'prediction_inputs'):
            content = _read_file(directory, name + '.jsonl')
            file_hashes[name] = hashlib.sha256(content).hexdigest()
            record = manifest.files[name + '.jsonl']
            if record.bytes != len(content) or record.sha256 != file_hashes[name]:
                raise SyntheticCaseSourceError('synthetic_package_file_hash_mismatch')
            raw[name] = [_json(line) for line in content.splitlines()]
            if len(raw[name]) != manifest.counts[name]:
                raise SyntheticCaseSourceError('synthetic_package_count_mismatch')
        source = {'source_kind': 'synthetic', 'is_synthetic': True,
                  'generator_version': manifest.generator_version, 'run_id': manifest.run_id}
        patients = {}
        for row in raw['patients']:
            patient = SyntheticPatient.model_validate(row)
            if patient.subject_id in patients or NumericPacketSource.model_validate(row['source']).model_dump() != source:
                raise SyntheticCaseSourceError('synthetic_package_patient_identity_mismatch')
            patients[patient.subject_id] = patient
        packets = {}
        sample_ids = set()
        for row in raw['prediction_inputs']:
            packet = PredictionInput.model_validate(row)
            if (packet.subject_id not in patients or packet.sample_id in sample_ids
                    or NumericPacketSource.model_validate(row['source']).model_dump() != source):
                raise SyntheticCaseSourceError('synthetic_package_packet_identity_mismatch')
            sample_ids.add(packet.sample_id)
            packets.setdefault(packet.subject_id, []).append(row)
        result = []
        for subject_id in subject_ids:
            patient = patients[subject_id]
            numeric = SyntheticNumericInput(
                disease_code=patient.disease, subject_id=patient.subject_id,
                dependency_group_id=patient.dependency_group_id, anchor_date=patient.anchor_date,
                source={**source, 'manifest_sha256': hashlib.sha256(manifest_bytes).hexdigest(),
                        'input_file_sha256': file_hashes['prediction_inputs']}, packets=packets[subject_id],
            )
            validate_operator_case_profile(patient.disease, patient.age, patient.sex, patient.baseline_stage)
            numeric_display_visits(numeric)
            result.append((patient, numeric))
        return result
    except SyntheticCaseSourceError:
        raise
    except (OSError, ValueError, TypeError, AttributeError, KeyError) as exc:
        raise SyntheticCaseSourceError('synthetic_package_invalid') from exc


def seed_synthetic_cases(session_factory, package_dir: Path, user_id: int, subject_ids: list[str]) -> list[int]:
    """Create selected synthetic cases and audits atomically in a caller's test DB."""
    from app.db.models import Disease, OperatorCase, OperatorCaseVisit, User
    from app.services.anonymous_case_code import generate_anonymous_case_code
    from app.services.disease_catalog import require_operator_disease
    from app.services.operator_case_audit import append_case_change_log, build_creation_changes

    with session_factory() as db:
        require_isolated_test_database(db.get_bind().url)
        if type(user_id) is not int or user_id <= 0:
            raise SyntheticCaseSourceError('synthetic_seed_operator_required')
        selected = load_synthetic_case_package(package_dir, subject_ids)
        with db.begin():
            # Serialize imports by owner so concurrent calls cannot import the same source twice.
            owner = db.query(User).filter(User.id == user_id).with_for_update().first()
            if owner is None or owner.role not in {'ai_operator', 'admin'}:
                raise SyntheticCaseSourceError('synthetic_seed_operator_required')
            case_ids = []
            for patient, numeric in selected:
                duplicate = db.query(OperatorCase).filter(
                    OperatorCase.user_id == user_id,
                    OperatorCase.engineering_source['run_id'].astext == numeric.source.run_id,
                    OperatorCase.engineering_source['subject_id'].astext == numeric.subject_id,
                ).first()
                if duplicate is not None:
                    raise SyntheticCaseSourceError('synthetic_subject_already_imported')
                disease = db.query(Disease).filter(Disease.code == patient.disease).first()
                if disease is None:
                    raise SyntheticCaseSourceError('synthetic_seed_disease_missing')
                disease = require_operator_disease(db, disease.id, for_update=True)
                anonymous_code = None
                for _ in range(5):
                    candidate = generate_anonymous_case_code()
                    if db.query(OperatorCase).filter(OperatorCase.anonymous_case_code == candidate).first() is None:
                        anonymous_code = candidate
                        break
                if anonymous_code is None:
                    raise SyntheticCaseSourceError('anonymous_case_code_generation_failed')
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
                case.engineering_source = build_engineering_binding(case, numeric)
                changes = build_creation_changes(case, visit_count=len(timeline))
                changes['engineering_source'] = {
                    'source_kind': 'synthetic', 'is_synthetic': True,
                    'numeric_input_sha256': case.engineering_source['numeric_input_sha256'],
                    'manifest_sha256': numeric.source.manifest_sha256,
                }
                append_case_change_log(db, case=case, actor_id=user_id, action='created',
                                       reason='系统：建立合成工程病例', changes=changes)
                case_ids.append(case.id)
            return case_ids
