"""Frozen phase-four acceptance; default preflight never connects or spawns.

The caller prepares surgery_rag_phase4_test, migration 0031 and real reference
indexes. --apply --allow-external-llm runs five real report/LLM/PDF jobs.
Existing output and application data are never erased or reused.
"""
import hashlib
import importlib.metadata
import importlib.util
import json
import os
from pathlib import Path
import platform
import sys
import traceback

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT), str(ROOT / 'backend')]
# Dry-run must not create import caches either.
sys.dont_write_bytecode = True
from scripts.run_numeric_report_acceptance import OwnedProcesses, SafeParser, require_free_ports

LEGACY_SHA = '32b8069f92dab3e104f3668c3639cdc6e5461f5bedf61a4f7590ce2cef478215'
HISTORY_SHA = 'a6816ed1a30d9a65ae089f67746e98473f0514732883d98a2843d3bc90db2464'
SOURCE_SHA = '3b333b090186e6c09fe938106bf2a176328e1d591b1bf6d56cf5ecbd7cd38296'
RENDERER_SHA = '328b86684e9c123ee776934b93e453a20ae4c49e4dbeb9929bcb0f53406acb6e'
SEED_EMAILS = ('history-a@example.com', 'history-b@example.com', 'history-doctor@example.com')


def validate_database_url():
    from sqlalchemy.engine import make_url
    from app.services.synthetic_case_source import require_isolated_test_database
    configured = os.environ.get('TEST_DATABASE_URL', '')
    if not configured:
        raise ValueError('test_database_url_required')
    try:
        if ('?' in configured or '#' in configured or
                any(os.environ.get(key) for key in ('PGHOSTADDR', 'PGSERVICE', 'PGSERVICEFILE', 'PGOPTIONS'))):
            raise ValueError()
        url = make_url(configured)
        require_isolated_test_database(url)
        if url.database != 'surgery_rag_phase4_test':
            raise ValueError()
        # The reused test-only HTTP host supports IPv4/localhost only.
        if url.host not in {'127.0.0.1', 'localhost'}:
            raise ValueError()
    except Exception:
        raise ValueError('isolated_test_database_required') from None
    return configured


def inspect_source(directory):
    from app.services.synthetic_case_source import load_synthetic_case_package
    from app.services.prediction_case_source import convert_legacy_input
    from app.services.numeric_history_features import project_numeric_history_features
    raw = (directory / 'manifest.json').read_bytes()
    if hashlib.sha256(raw).hexdigest() != SOURCE_SHA:
        raise ValueError('frozen_source_mismatch')
    manifest = json.loads(raw)
    for name, record in manifest['files'].items():
        content = (directory / name).read_bytes()
        if len(content) != record['bytes'] or hashlib.sha256(content).hexdigest() != record['sha256']:
            raise ValueError('frozen_source_mismatch')
    patients = [json.loads(line) for line in (directory / 'patients.jsonl').read_bytes().splitlines()]
    loaded = load_synthetic_case_package(directory, [row['subject_id'] for row in patients])
    chosen = {}
    for patient, old in loaded:
        numeric = convert_legacy_input(old)
        if not all(packet.input_status == 'available' for packet in numeric.packets):
            continue
        packet = next(packet for packet in numeric.packets if packet.horizon_months == 12)
        features = project_numeric_history_features(packet)
        if patient.disease == 'fatty_liver':
            scenario = 'fatty_liver'
        elif features.status == 'available' and packet.history_state == 'observed':
            scenario = 'ad'
        elif packet.history_state == 'confirmed_none' and features.reason == 'history_not_observed':
            scenario = 'ad_partial'
        else:
            continue
        chosen.setdefault(scenario, dict(scenario=scenario, disease=patient.disease,
            subject_id=patient.subject_id, history_state=packet.history_state))
    if set(chosen) != {'ad', 'fatty_liver', 'ad_partial'}:
        raise ValueError('frozen_source_scenarios_missing')
    cases = [chosen[name] for name in ('ad', 'fatty_liver', 'ad_partial')]
    return dict(source_run_id=manifest['run_id'], source_manifest_sha256=SOURCE_SHA,
        data_content_sha256=manifest['data_content_sha256'], cases=cases,
        subjects=[case['subject_id'] for case in cases])


def static_chromium_path():
    """Resolve this Windows-only frozen renderer without starting the JS driver."""
    spec = importlib.util.find_spec('playwright')
    package = Path(spec.origin).parent / 'driver' / 'package'
    records = json.loads((package / 'browsers.json').read_bytes())['browsers']
    chromium = next(row for row in records if row['name'] == 'chromium')
    if platform.system() != 'Windows' or chromium.get('revisionOverrides'):
        raise ValueError('renderer_static_runtime_unsupported')
    configured = os.environ.get('PLAYWRIGHT_BROWSERS_PATH')
    if configured == '0':
        cache = package / '.local-browsers'
    elif configured:
        cache = Path(configured)
        if not cache.is_absolute():
            raise ValueError('renderer_static_runtime_unsupported')
    else:
        cache = Path(os.environ['LOCALAPPDATA']) / 'ms-playwright'
    return cache / ('chromium-' + chromium['revision']) / 'chrome-win64' / 'chrome.exe', chromium['browserVersion']


def inspect_renderer(path):
    from app.services.report_pdf_renderer_manifest import (
        APP_ROOT, PRINT_OPTIONS, RENDERER_FILES, RendererManifest, file_sha, resource_path,
    )
    raw = path.read_bytes()
    if len(raw) > 65536 or hashlib.sha256(raw).hexdigest() != RENDERER_SHA:
        raise ValueError('frozen_renderer_mismatch')
    manifest = RendererManifest.model_validate_json(raw)
    executable, version = static_chromium_path()
    if (manifest.platform != platform.system()
            or manifest.playwright_version != importlib.metadata.version('playwright')
            or manifest.fonttools_version != importlib.metadata.version('fonttools')
            or manifest.print_options != PRINT_OPTIONS
            or set(manifest.source_files) != set(RENDERER_FILES)
            or manifest.chromium_version != version
            or file_sha(executable) != manifest.chromium_sha256):
        raise ValueError('frozen_renderer_mismatch')
    for relative, digest in manifest.source_files.items():
        if file_sha(APP_ROOT / relative) != digest:
            raise ValueError('frozen_renderer_mismatch')
    if (manifest.template_sha256 != manifest.source_files['templates/report_pdf.html']
            or manifest.markdown_adapter_sha256 != manifest.source_files['services/pdf_generator.py']
            or manifest.chart_renderer_sha256 != manifest.source_files['services/report_document_builder.py']):
        raise ValueError('frozen_renderer_mismatch')
    for font in manifest.font_files:
        if (file_sha(resource_path(path.parent.resolve(), font.path)) != font.sha256
                or file_sha(resource_path(path.parent.resolve(), font.license)) != font.license_sha256):
            raise ValueError('frozen_renderer_mismatch')
    return {'manifest_sha256': RENDERER_SHA, 'verification': 'static_no_driver'}


def preflight(args):
    validate_database_url()
    if args.apply and not args.allow_external_llm:
        raise ValueError('external_llm_authorization_required')
    if args.output.exists():
        raise ValueError('output_already_exists')
    require_free_ports()
    from app.services.numeric_model_bundle import load_numeric_model_bundle, verify_numeric_bundle_runtime, bundle_sha256, trained_numeric_algorithm
    from app.services.numeric_history_bundle import load_numeric_history_bundle, verify_numeric_history_runtime, history_bundle_sha256
    legacy = load_numeric_model_bundle(args.legacy_bundle)
    history = load_numeric_history_bundle(args.history_bundle)
    if (bundle_sha256(legacy) != LEGACY_SHA or history_bundle_sha256(history) != HISTORY_SHA
            or history.legacy_bundle != legacy):
        raise ValueError('frozen_model_mismatch')
    verify_numeric_bundle_runtime(legacy)
    verify_numeric_history_runtime(history)
    return dict(source=inspect_source(args.source_dir.resolve()),
        legacy={'bundle_sha256': LEGACY_SHA, 'algorithm': trained_numeric_algorithm(legacy).model_dump(mode='json')},
        history={'bundle_sha256': HISTORY_SHA}, renderer=inspect_renderer(args.renderer.resolve()))


def execute(args, identities):
    url = validate_database_url()
    if not args.apply or not args.allow_external_llm:
        raise ValueError('external_llm_authorization_required')
    # Recheck immutable resources immediately before admitting any work.
    if preflight(args) != identities:
        raise ValueError('preflight_identity_changed')
    output = args.output.resolve()
    output.mkdir(parents=True, exist_ok=False)
    env = {**os.environ, 'DATABASE_URL': url, 'VECTOR_STORE_CONNECTION_STRING': url,
        'PYTHONPATH': os.pathsep.join((str(ROOT), str(ROOT / 'backend'))), 'PYTHONUTF8': '1',
        'HF_HUB_OFFLINE': '1', 'TRANSFORMERS_OFFLINE': '1', 'MODELSCOPE_OFFLINE': '1',
        'REPORT_HISTORY_CURSOR_SECRET': 'isolated-history-acceptance-secret-32-bytes',
        'REPORT_PDF_ENABLED': 'true', 'REPORT_PDF_ACCEPTING': 'true',
        'REPORT_PDF_RENDERER_MANIFEST': str(args.renderer.resolve()),
        'REPORT_ARCHIVE_ROOT': str(output / 'archive'), 'REPORT_JOBS_ENABLED': 'true',
        'REPORT_JOBS_ACCEPTING': 'true', 'NUMERIC_REPORTS_ENABLED': 'true',
        'NUMERIC_MODEL_BUNDLE': str(args.legacy_bundle.resolve()),
        'E2E_API_PROXY': 'http://127.0.0.1:18060'}
    previous = dict(os.environ)
    os.environ.update(env)
    engine, owned = None, None
    result = {'status': 'running', 'is_synthetic': True, 'clinical_validity_claim': False,
        'identities': identities, 'reports': [], 'checks': {},
        'external_llm': {'planned_reports': 5, 'worker_invocations': 0, 'completed_reports': 0}}
    try:
        from app.services.report_pdf_renderer_manifest import load_renderer_manifest
        _, digest = load_renderer_manifest(args.renderer.resolve())
        if digest != RENDERER_SHA:
            raise ValueError('frozen_renderer_mismatch')
        from sqlalchemy import create_engine, text
        from sqlalchemy.orm import sessionmaker
        from app.core.security import create_access_token
        from app.core.config import settings
        from app.services.prediction_case_source import seed_prediction_cases
        from scripts.numeric_report_acceptance_browser import convert_source_package
        from scripts.numeric_history_acceptance_browser import run_scenarios
        engine = create_engine(url)
        factory = sessionmaker(bind=engine, expire_on_commit=False)
        with engine.connect() as db:
            db.execute(text('SET TRANSACTION READ ONLY'))
            if any(db.execute(text(f'SELECT count(*) FROM {table}')).scalar_one()
                    for table in ('users', 'operator_cases', 'ai_reports')):
                raise ValueError('clean_test_database_required')
            if db.execute(text('SELECT version_num FROM alembic_version')).scalar_one() != '0031':
                raise ValueError('phase4_migration_required')
        with engine.begin() as db:
            users = []
            for index, email in enumerate(SEED_EMAILS):
                users.append(db.execute(text('INSERT INTO users (username,email,hashed_password,role) '
                    'VALUES (:name,:email,:password,:role) RETURNING id'),
                    dict(name=f'history-acceptance-{index}', email=email, password='x',
                         role='doctor' if index == 2 else 'ai_operator')).scalar_one())
            for code, name in (('ad', '阿尔茨海默病'), ('fatty_liver', '脂肪肝')):
                db.execute(text('INSERT INTO diseases (code,name,operator_enabled) VALUES (:code,:name,true) '
                    'ON CONFLICT (code) DO UPDATE SET operator_enabled=true'), dict(code=code, name=name))
        package = convert_source_package(args.source_dir, identities['source'], output / 'source-package')
        ids = seed_prediction_cases(factory, package, users[0])
        tokens = [create_access_token({'sub': str(user)}, settings.JWT_SECRET, settings.JWT_ALGORITHM) for user in users]
        owned = OwnedProcesses(output, env)
        run_scenarios(args, identities, ids, tokens, owned, result)
        result['status'] = 'passed'
    except Exception as exc:
        # HTTP/SQL/LLM exception text may contain credentials. Keep only locations.
        result.update(status='failed', error_type=type(exc).__name__, error_location=[
            {'file': Path(frame.filename).name, 'line': frame.lineno, 'function': frame.name}
            for frame in traceback.extract_tb(exc.__traceback__)])
    finally:
        try:
            for stage, resource, method in (('owned_processes', owned, 'close'),
                                             ('database_engine', engine, 'dispose')):
                if resource is None:
                    continue
                try:
                    getattr(resource, method)()
                except Exception as exc:
                    result['status'] = 'failed'
                    result.setdefault('cleanup_errors', []).append({
                        'stage': stage, 'error_type': type(exc).__name__,
                        'error_location': [
                            {'file': Path(frame.filename).name, 'line': frame.lineno, 'function': frame.name}
                            for frame in traceback.extract_tb(exc.__traceback__)]})
            try:
                (output / 'result.json').write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding='utf-8')
            except Exception as exc:
                result['status'] = 'failed'
                print(json.dumps({'status': 'failed', 'error': 'acceptance_result_write_failed',
                                  'error_type': type(exc).__name__}))
        finally:
            os.environ.clear()
            os.environ.update(previous)
    return 0 if result['status'] == 'passed' else 1


def main(argv=None):
    parser = SafeParser(description=__doc__, allow_abbrev=False)
    for name in ('source-dir', 'legacy-bundle', 'history-bundle', 'renderer'):
        parser.add_argument('--' + name, type=Path, required=True)
    parser.add_argument('--output', type=Path, default=ROOT / 'outputs/numeric-history-acceptance/2026-09-18-v1')
    parser.add_argument('--apply', action='store_true')
    parser.add_argument('--allow-external-llm', action='store_true')
    try:
        args = parser.parse_args(argv)
        identities = preflight(args)
        if args.apply:
            return execute(args, identities)
        print(json.dumps({'status': 'dry_run', 'database_connected': False,
            'services_started': False, 'identities': identities}, ensure_ascii=False))
        return 0
    except Exception as exc:
        known = {'invalid_arguments', 'test_database_url_required', 'isolated_test_database_required',
            'external_llm_authorization_required', 'output_already_exists', 'port_in_use',
            'frozen_source_mismatch', 'frozen_source_scenarios_missing', 'frozen_model_mismatch',
            'frozen_renderer_mismatch', 'renderer_static_runtime_unsupported', 'preflight_identity_changed'}
        code = str(exc) if str(exc) in known else 'acceptance_preflight_failed'
        print(json.dumps({'status': 'error', 'error': code}))
        return 2


if __name__ == '__main__':
    raise SystemExit(main())
