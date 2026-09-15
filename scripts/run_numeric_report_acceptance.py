"""Repeatable real numeric-report acceptance in an explicit local test database.

Default: validate inputs without connecting to PostgreSQL or creating output.
Execution requires both --apply and --allow-external-llm. The caller prepares
migrations, synthetic reference indexes, renderer and trained bundles first.
"""
import argparse
import hashlib
import json
import os
from pathlib import Path
import socket
import subprocess
import sys
import time
import traceback
import urllib.request

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT), str(ROOT / 'backend')]
DISEASES = ('ad', 'fatty_liver')
SEED_EMAILS = ('numeric-a@example.com', 'numeric-b@example.com')


class SafeParser(argparse.ArgumentParser):
    def error(self, message):
        raise ValueError('invalid_arguments')


def require_free_ports(ports=(18060, 15173)):
    for port in ports:
        with socket.socket() as probe:
            try:
                probe.bind(('127.0.0.1', port))
            except OSError:
                raise ValueError('port_in_use') from None


def preflight(args):
    from sqlalchemy.engine import make_url
    from app.services.synthetic_case_source import require_isolated_test_database, load_synthetic_case_package
    from app.services.numeric_model_bundle import load_numeric_model_bundle, verify_numeric_bundle_runtime, trained_numeric_algorithm
    from app.services.report_pdf_renderer_manifest import load_renderer_manifest

    configured = os.environ.get('TEST_DATABASE_URL', '')
    if not configured:
        raise ValueError('test_database_url_required')
    try:
        url = make_url(configured)
        require_isolated_test_database(url)
    except Exception:
        raise ValueError('isolated_test_database_required') from None
    if args.apply and not args.allow_external_llm:
        raise ValueError('external_llm_authorization_required')
    if args.output.exists():
        raise ValueError('output_already_exists')
    require_free_ports()
    identities = {}
    for label in ('a', 'b'):
        source = getattr(args, 'source_' + label).resolve()
        manifest = json.loads((source / 'manifest.json').read_text(encoding='utf-8'))
        patients = [json.loads(line) for line in (source / 'patients.jsonl').read_text(encoding='utf-8').splitlines()]
        subjects = [next(p['subject_id'] for p in patients if p['disease'] == disease) for disease in DISEASES]
        load_synthetic_case_package(source, subjects)
        bundle = load_numeric_model_bundle(getattr(args, 'model_' + label))
        verify_numeric_bundle_runtime(bundle)
        if (bundle.source.cases.run_id != manifest['run_id'] or
                bundle.source.cases.data_content_sha256 != manifest['data_content_sha256']):
            raise ValueError('model_source_mismatch')
        identities[label] = dict(source_run_id=manifest['run_id'],
            source_manifest_sha256=hashlib.sha256((source / 'manifest.json').read_bytes()).hexdigest(),
            subjects=subjects, algorithm=trained_numeric_algorithm(bundle).model_dump(mode='json'))
    if (identities['a']['source_run_id'] == identities['b']['source_run_id'] or
            identities['a']['algorithm']['parameters_sha256'] == identities['b']['algorithm']['parameters_sha256']):
        raise ValueError('distinct_source_and_trained_models_required')
    load_renderer_manifest(args.renderer.resolve())
    return identities


class OwnedProcesses:
    """Same process-tree ownership as run_operator_report_e2e, including CLI workers."""
    def __init__(self, output, env):
        self.output, self.env, self.processes, self.logs = output, env, {}, []
        self.jobs = {}

    def start(self, name, command, cwd, extra=None):
        if name in self.processes:
            raise ValueError('owned_process_already_started')
        log = (self.output / (name + '.log')).open('a', encoding='utf-8')
        self.logs.append(log)
        job, process = None, None
        try:
            if os.name == 'nt':
                from app.workers.report_process_control import _WindowsJob
                job = _WindowsJob()
            process = subprocess.Popen(command, cwd=cwd, env={**self.env, **(extra or {})},
                stdout=log, stderr=log,
                # CREATE_SUSPENDED prevents descendants escaping before Job assignment.
                creationflags=(subprocess.CREATE_NO_WINDOW | 0x00000004) if os.name == 'nt' else 0,
                start_new_session=os.name != 'nt')
            if job is not None:
                import ctypes
                from ctypes import wintypes
                from types import SimpleNamespace
                job.assign(SimpleNamespace(sentinel=int(process._handle)))
                api = ctypes.WinDLL('ntdll', use_last_error=True)
                api.NtResumeProcess.argtypes = [wintypes.HANDLE]
                api.NtResumeProcess.restype = wintypes.LONG
                if api.NtResumeProcess(int(process._handle)) < 0:
                    raise RuntimeError('owned_process_resume_failed')
                self.jobs[name] = job
            self.processes[name] = process
            return process
        except BaseException:
            if job is not None:
                job.close()
            if process is not None:
                if process.poll() is None:
                    process.kill()
                process.wait(timeout=5)
            raise

    def stop(self, name):
        process = self.processes.pop(name, None)
        if process is None:
            return
        job = self.jobs.pop(name, None)
        if job is not None:
            # Job lifetime is independent of its root PID. Closing it also kills
            # descendants after the root has already exited and been reaped.
            job.close()
            process.wait(timeout=5)
            return
        import signal
        # start_new_session fixes the process-group identity at the original PID;
        # never look it up through an already-exited root process.
        try:
            os.killpg(process.pid, signal.SIGTERM)
        except ProcessLookupError:
            pass
        try:
            process.wait(timeout=5)
        except subprocess.TimeoutExpired:
            pass
        finally:
            try:
                os.killpg(process.pid, signal.SIGKILL)
            except ProcessLookupError:
                pass
            process.wait(timeout=5)

    def worker(self, module):
        process = self.start('worker', [sys.executable, '-m', module, '--once'], ROOT / 'backend')
        try:
            if process.wait(timeout=340) != 0:
                raise RuntimeError('worker_cli_failed')
        finally:
            self.stop('worker')

    def ready(self, endpoint):
        deadline = time.monotonic() + 60
        while time.monotonic() < deadline:
            if any(p.poll() is not None for p in self.processes.values()):
                raise RuntimeError('owned_service_exited')
            try:
                with urllib.request.urlopen(endpoint, timeout=2) as response:
                    if response.status == 200:
                        return
            except OSError:
                pass
            time.sleep(.25)
        raise RuntimeError('owned_service_start_timeout')

    def close(self):
        for name in list(self.processes)[::-1]:
            self.stop(name)
        for log in self.logs:
            log.close()


def execute(args, identities):
    # Override both SQL and vector connections before importing application settings.
    url = os.environ['TEST_DATABASE_URL']
    output = args.output.resolve()
    env = {**os.environ, 'DATABASE_URL': url, 'VECTOR_STORE_CONNECTION_STRING': url,
        'PYTHONPATH': os.pathsep.join((str(ROOT), str(ROOT / 'backend'))), 'PYTHONUTF8': '1',
        'HF_HUB_OFFLINE': '1', 'TRANSFORMERS_OFFLINE': '1',
        'REPORT_HISTORY_CURSOR_SECRET': 'isolated-numeric-history-secret-32-bytes',
        'REPORT_PDF_ENABLED': 'true', 'REPORT_PDF_ACCEPTING': 'true',
        'REPORT_PDF_RENDERER_MANIFEST': str(args.renderer.resolve()),
        'REPORT_ARCHIVE_ROOT': str(output / 'archive'), 'REPORT_JOBS_ENABLED': 'true',
        'REPORT_JOBS_ACCEPTING': 'true', 'NUMERIC_REPORTS_ENABLED': 'true',
        'NUMERIC_MODEL_BUNDLE': str(args.model_a.resolve()),
        'E2E_API_PROXY': 'http://127.0.0.1:18060'}
    previous = dict(os.environ)
    os.environ.update(env)
    engine = None
    owned = None
    output_created = False
    result = {'status': 'running', 'is_synthetic': True, 'clinical_validity_claim': False,
              'identities': identities, 'reports': [], 'checks': {}}
    try:
        from sqlalchemy import create_engine, text
        from sqlalchemy.orm import sessionmaker
        from app.services.synthetic_case_source import seed_synthetic_cases
        from app.core.security import create_access_token
        from app.core.config import settings
        engine = create_engine(url)
        factory = sessionmaker(bind=engine, expire_on_commit=False)
        # A populated reference index and migrated disease catalog are allowed;
        # existing application users/cases/reports are never erased or adopted.
        with engine.connect() as db:
            db.execute(text('SET TRANSACTION READ ONLY'))
            if any(db.execute(text(f'SELECT count(*) FROM {table}')).scalar_one()
                   for table in ('users', 'operator_cases', 'ai_reports')):
                raise ValueError('clean_test_database_required')
        require_free_ports()
        output.mkdir(parents=True, exist_ok=False)
        output_created = True
        with engine.begin() as db:
            users = db.execute(text("INSERT INTO users (username,email,hashed_password,role) VALUES "
                "('numeric-acceptance-a',:email_a,'x','ai_operator'),"
                "('numeric-acceptance-b',:email_b,'x','ai_operator') RETURNING id"),
                {'email_a': SEED_EMAILS[0], 'email_b': SEED_EMAILS[1]}).scalars().all()
            for code, name in (('ad', '阿尔茨海默病'), ('fatty_liver', '脂肪肝')):
                db.execute(text('INSERT INTO diseases (code,name,operator_enabled) VALUES (:code,:name,true) '
                    'ON CONFLICT (code) DO UPDATE SET operator_enabled=true'), dict(code=code, name=name))
        ids = {'a': seed_synthetic_cases(factory, args.source_a, users[0], identities['a']['subjects'])}
        from scripts.numeric_report_acceptance_browser import convert_source_package
        from app.services.prediction_case_source import seed_prediction_cases
        package_b = convert_source_package(args.source_b, identities['b'], output / 'source-b-package')
        ids['b'] = seed_prediction_cases(factory, package_b, users[0])
        tokens = [create_access_token({'sub': str(user)}, settings.JWT_SECRET, settings.JWT_ALGORITHM) for user in users]
        owned = OwnedProcesses(output, env)
        from scripts.numeric_report_acceptance_browser import run_scenarios
        run_scenarios(args, identities, ids, tokens, owned, result)
        result['status'] = 'passed'
        return 0
    except Exception as exc:
        # Do not serialize exception text: HTTP/SQL errors can contain secrets.
        frames = traceback.extract_tb(exc.__traceback__)
        result.update(status='failed', error_type=type(exc).__name__,
            error_location=[{'file': Path(frame.filename).name, 'line': frame.lineno, 'function': frame.name}
                            for frame in frames])
        if not output_created:
            raise ValueError('execution_precondition_failed') from None
        return 1
    finally:
        if owned is not None:
            owned.close()
        if engine is not None:
            engine.dispose()
        if output_created:
            (output / 'result.json').write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding='utf-8')
        os.environ.clear()
        os.environ.update(previous)


def main(argv=None):
    parser = SafeParser(description=__doc__, allow_abbrev=False)
    for name in ('source-a', 'source-b', 'model-a', 'model-b', 'renderer', 'output'):
        parser.add_argument('--' + name, type=Path, required=True)
    parser.add_argument('--apply', action='store_true')
    parser.add_argument('--allow-external-llm', action='store_true')
    try:
        args = parser.parse_args(argv)
        identities = preflight(args)
        if args.apply:
            return execute(args, identities)
        print(json.dumps({'status': 'dry_run', 'database_connected': False, 'identities': identities}, ensure_ascii=False))
        return 0
    except Exception as exc:
        known = {'invalid_arguments', 'test_database_url_required', 'isolated_test_database_required',
                 'external_llm_authorization_required', 'output_already_exists', 'port_in_use',
                 'model_source_mismatch', 'distinct_source_and_trained_models_required', 'execution_precondition_failed'}
        code = str(exc) if str(exc) in known else 'acceptance_preflight_failed'
        print(json.dumps({'status': 'error', 'error': code}))
        return 2


if __name__ == '__main__':
    raise SystemExit(main())
