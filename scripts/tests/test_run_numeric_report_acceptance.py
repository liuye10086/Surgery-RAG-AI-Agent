"""Safety gates run without connecting to a database or starting services."""
import importlib.util
from pathlib import Path
import socket
import subprocess
import os
import sys
import time

import pytest

SCRIPT = Path(__file__).resolve().parents[1] / 'run_numeric_report_acceptance.py'


def runner():
    spec = importlib.util.spec_from_file_location('numeric_acceptance', SCRIPT)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def args(tmp_path, *extra):
    return [item for flag in ('source-a', 'source-b', 'model-a', 'model-b', 'renderer', 'output')
            for item in ('--' + flag, str(tmp_path / flag))] + list(extra)


def test_missing_arguments_does_not_execute(monkeypatch):
    module = runner()
    monkeypatch.setattr(module, 'execute', lambda *a: pytest.fail('execution forbidden'))
    assert module.main([]) == 2


def test_seed_emails_satisfy_actual_auth_response_schema():
    module = runner()
    from app.schemas.user import UserOut
    for user_id, email in enumerate(module.SEED_EMAILS, start=1):
        response = UserOut(id=user_id, username=f'numeric-acceptance-{user_id}',
            email=email, real_name=None, role='ai_operator')
        assert str(response.email) == email


@pytest.mark.parametrize('url', ['', 'postgresql://localhost/business',
    'postgresql://remote/surgery_test', 'postgresql://localhost/surgery_test?host=remote'])
def test_unsafe_database_rejected(tmp_path, monkeypatch, url):
    module = runner()
    monkeypatch.setenv('TEST_DATABASE_URL', url)
    monkeypatch.setattr(module, 'execute', lambda *a: pytest.fail('execution forbidden'))
    assert module.main(args(tmp_path, '--apply', '--allow-external-llm')) == 2
    assert not (tmp_path / 'output').exists()


def test_apply_requires_external_authorization(tmp_path, monkeypatch):
    module = runner()
    monkeypatch.setenv('TEST_DATABASE_URL', 'postgresql://localhost/numeric_test')
    assert module.main(args(tmp_path, '--apply')) == 2
    assert not (tmp_path / 'output').exists()


def test_existing_output_rejected(tmp_path, monkeypatch):
    module = runner()
    monkeypatch.setenv('TEST_DATABASE_URL', 'postgresql://localhost/numeric_test')
    (tmp_path / 'output').mkdir()
    marker = tmp_path / 'output' / 'original'
    marker.write_text('preserve')
    assert module.main(args(tmp_path)) == 2
    assert marker.read_text() == 'preserve'


def test_busy_port_rejected():
    module = runner()
    with socket.socket() as listener:
        listener.bind(('127.0.0.1', 0))
        listener.listen()
        with pytest.raises(ValueError, match='port_in_use'):
            module.require_free_ports((listener.getsockname()[1],))


def test_default_dry_run_never_executes(tmp_path, monkeypatch, capsys):
    module = runner()
    monkeypatch.setattr(module, 'preflight', lambda args: {'validated': True})
    monkeypatch.setattr(module, 'execute', lambda *a: pytest.fail('execution forbidden'))
    assert module.main(args(tmp_path)) == 0
    assert '"database_connected": false' in capsys.readouterr().out
    assert not (tmp_path / 'output').exists()


def test_worker_timeout_still_stops_owned_tree(tmp_path, monkeypatch):
    module = runner()
    owned = module.OwnedProcesses(tmp_path, {})
    class SlowWorker:
        def wait(self, timeout):
            raise subprocess.TimeoutExpired('worker', timeout)
    stopped = []
    monkeypatch.setattr(owned, 'start', lambda *a: SlowWorker())
    monkeypatch.setattr(owned, 'stop', stopped.append)
    with pytest.raises(subprocess.TimeoutExpired):
        owned.worker('app.workers.report_worker')
    assert stopped == ['worker']


def test_worker_failure_is_not_retried(tmp_path, monkeypatch):
    module = runner()
    owned = module.OwnedProcesses(tmp_path, {})
    started, stopped = [], []
    class FailedWorker:
        def wait(self, timeout):
            return 1
    def start(*values):
        started.append(values)
        return FailedWorker()
    monkeypatch.setattr(owned, 'start', start)
    monkeypatch.setattr(owned, 'stop', stopped.append)
    with pytest.raises(RuntimeError, match='worker_cli_failed'):
        owned.worker('app.workers.report_worker')
    assert len(started) == 1
    assert stopped == ['worker']


@pytest.mark.parametrize('root_exits_first', [True, False])
def test_actual_owned_child_cleanup_even_after_root_exit(tmp_path, root_exits_first):
    import psutil
    module = runner()
    owned = module.OwnedProcesses(tmp_path, dict(os.environ))
    pid_file = tmp_path / 'child.pid'
    code = (
        'import subprocess,sys,time; from pathlib import Path; '
        'p=subprocess.Popen([sys.executable,"-c","import time; time.sleep(60)"]); '
        'Path(sys.argv[1]).write_text(str(p.pid)); '
        + ('pass' if root_exits_first else 'time.sleep(60)')
    )
    child = None
    try:
        parent = owned.start('probe', [sys.executable, '-c', code, str(pid_file)], tmp_path)
        deadline = time.monotonic() + 10
        while not pid_file.exists() and time.monotonic() < deadline:
            time.sleep(.02)
        assert pid_file.exists()
        child = psutil.Process(int(pid_file.read_text()))
        assert child.is_running()
        if root_exits_first:
            assert parent.wait(timeout=10) == 0
        owned.stop('probe')
        try:
            child.wait(timeout=5)
        except psutil.TimeoutExpired:
            pytest.fail('owned child survived root cleanup')
        assert parent.poll() is not None
    finally:
        owned.close()
        if child is not None and child.is_running():
            child.kill()
            child.wait(timeout=5)
