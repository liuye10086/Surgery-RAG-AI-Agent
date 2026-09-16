import importlib.util
import json
from pathlib import Path
import shutil
import subprocess

import pytest


def api():
    path = Path(__file__).resolve().parents[1] / "run_synthetic_prediction_history.py"
    spec = importlib.util.spec_from_file_location("history_runner", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_public_api_and_frozen_protocol():
    module = api()
    assert callable(module.run) and callable(module.verify) and callable(module.main)
    assert module.PROTOCOL["seeds"] == [20260914, 20260915, 20260916]
    assert module.PROTOCOL["patients_per_disease"] == 1200
    assert module.PROTOCOL["challenge_per_disease"] == 400
    assert module.PROTOCOL["training_groups_per_disease"] == 640
    assert module.PROTOCOL["bootstrap_iterations"] == 2000
    assert module.PROTOCOL["is_test_fixture"] is False


def test_existing_destination_is_rejected_without_modification(tmp_path):
    module = api()
    keep = tmp_path / "keep.txt"
    keep.write_text("original", encoding="utf-8")
    try:
        module.run(tmp_path)
    except FileExistsError:
        pass
    else:
        raise AssertionError("existing output must be rejected")
    assert keep.read_text(encoding="utf-8") == "original"


def test_cli_errors_are_sanitized(tmp_path, monkeypatch, capsys):
    module = api()
    assert module.main([]) == 2
    assert json.loads(capsys.readouterr().out)["reason"] == "invalid_arguments"

    def fail(_):
        raise RuntimeError("private path and secret")

    monkeypatch.setattr(module, "run", fail)
    assert module.main(["--output-dir", str(tmp_path / "new")]) == 4
    output = capsys.readouterr().out
    assert "private" not in output and "secret" not in output


def test_unexpected_output_preflight_error_is_sanitized(monkeypatch, capsys):
    module = api()
    monkeypatch.setattr(module, "_validate_new_output",
                        lambda path: (_ for _ in ()).throw(OSError("private controlled path")))
    assert module.main(["--output-dir", "unused-test-path"]) == 4
    output = capsys.readouterr().out
    assert "private" not in output and "controlled" not in output


def test_project_paths_and_artifact_nesting_are_rejected(tmp_path):
    module = api()
    with pytest.raises(ValueError):
        module.run(module.ROOT / "data" / "forbidden-history-package")
    ancestor = tmp_path / "artifact"
    ancestor.mkdir()
    (ancestor / "manifest.json").write_text("{}", encoding="utf-8")
    with pytest.raises(ValueError):
        module.run(ancestor / "nested")


def test_symlink_output_parent_is_rejected(tmp_path):
    module = api()
    target = tmp_path / "target"
    target.mkdir()
    link = tmp_path / "link"
    try:
        link.symlink_to(target, target_is_directory=True)
    except OSError:
        pytest.skip("symlink creation is unavailable")
    with pytest.raises(ValueError):
        module.run(link / "package")


def test_quality_failure_keeps_frozen_protocol_and_evidence(tmp_path, monkeypatch):
    module = api()
    module.PROTOCOL = {**module.PROTOCOL, "patients_per_disease": 60,
                       "challenge_per_disease": 20, "training_groups_per_disease": 32,
                       "is_test_fixture": True, "test_fixture_purpose": "quality_failure_test_only"}
    monkeypatch.setattr(module, "assess_cohort", lambda cohort: {"status": "failed", "checks": {}})
    output = tmp_path / "failed"
    result = module.run(output)
    assert result["status"] == "failed"
    assert (output / "protocol.json").exists()
    assert (output / "seed-20260914/cohort.json").exists()
    assert json.loads((output / "seed-20260914/quality.json").read_text())["status"] == "failed"
    manifest = json.loads((output / "manifest.json").read_text())
    assert manifest["error"] == "source_quality_failed"
    assert "traceback" not in (output / "manifest.json").read_text().lower()


def test_envelope_initialization_failure_keeps_safe_failure_package(tmp_path, monkeypatch):
    module = api()
    monkeypatch.setattr(module, "_envelope",
                        lambda: (_ for _ in ()).throw(OSError("private initialization detail")))
    output = tmp_path / "initialization-failure"
    with pytest.raises(OSError):
        module.run(output)
    protocol = json.loads((output / "protocol.json").read_text(encoding="utf-8"))
    manifest = json.loads((output / "manifest.json").read_text(encoding="utf-8"))
    assert protocol["envelope_status"] == "failed"
    assert manifest["status"] == "failed" and manifest["error"] == "experiment_runtime_error"
    assert "private" not in (output / "manifest.json").read_text(encoding="utf-8")


def test_protocol_write_failure_still_keeps_safe_manifest(tmp_path, monkeypatch):
    module = api()
    original = module._write
    def fail_protocol(directory, name, value, **kwargs):
        if name == "protocol.json":
            raise OSError("private protocol path")
        return original(directory, name, value, **kwargs)
    monkeypatch.setattr(module, "_write", fail_protocol)
    output = tmp_path / "protocol-write-failure"
    with pytest.raises(OSError):
        module.run(output)
    manifest = json.loads((output / "manifest.json").read_text(encoding="utf-8"))
    assert manifest["status"] == "failed" and manifest["error"] == "experiment_runtime_error"
    assert not (output / "protocol.json").exists()
    assert "private" not in (output / "manifest.json").read_text(encoding="utf-8")


def test_output_cli_calls_verify_before_returning_zero(tmp_path, monkeypatch, capsys):
    module = api()
    calls = []
    monkeypatch.setattr(module, "_validate_new_output", lambda path: Path(path))
    monkeypatch.setattr(module, "run", lambda path: {"status": "passed"})
    def verified(path):
        calls.append(Path(path))
        return {"status": "passed", "engineering_status": "passed"}
    monkeypatch.setattr(module, "verify", verified)
    target = tmp_path / "new"
    assert module.main(["--output-dir", str(target)]) == 0
    assert calls == [target]
    assert json.loads(capsys.readouterr().out)["status"] == "passed"


def _small_protocol(module, *, seeds=None):
    return {
        **module.PROTOCOL,
        "seeds": seeds or [20260914, 20260915, 20260916],
        "patients_per_disease": 120,
        "challenge_per_disease": 40,
        "training_groups_per_disease": 64,
        "is_test_fixture": True,
        "test_fixture_purpose": "automated_cli_recalculation_test_only",
    }


@pytest.fixture(scope="module")
def small_package(tmp_path_factory):
    module = api()
    module.PROTOCOL = _small_protocol(module)
    output = tmp_path_factory.mktemp("history-package") / "package"
    script = module.ROOT / "scripts/run_synthetic_prediction_history.py"
    code = (
        "import importlib.util,sys;"
        f"p={str(script)!r};s=importlib.util.spec_from_file_location('h',p);m=importlib.util.module_from_spec(s);s.loader.exec_module(m);"
        f"m.PROTOCOL={module.PROTOCOL!r};sys.exit(m.main(['--output-dir',{str(output)!r}]))"
    )
    completed = subprocess.run(
        [str(module.ROOT / "backend/.venv/Scripts/python.exe"), "-c", code],
        cwd=module.ROOT / "backend", capture_output=True, text=True, check=False,
    )
    assert completed.returncode == 0, completed.stdout + completed.stderr
    result = json.loads(completed.stdout.strip().splitlines()[-1])
    return module, output, result


def test_real_small_package_has_all_attempts_evaluations_and_partitions(small_package):
    module, output, result = small_package
    assert result["status"] == "passed"
    assert result["counts"]["model_attempts"] == 120
    assert result["counts"]["comparisons"] == 1440
    assert result["counts"]["aggregate_rows"] == 480
    assert result["is_test_fixture"] is True
    for seed in module.PROTOCOL["seeds"]:
        features = json.loads((output / f"seed-{seed}/features.json").read_text())
        roles = {role: {row["sample_id"] for row in features if row["evaluation_role"] == role}
                 for role in module.PROTOCOL["roles"]}
        assert set.union(*roles.values()) == {row["sample_id"] for row in features}
        assert not any(roles[left] & roles[right] for left in roles for right in roles if left < right)


def test_new_process_verifies_test_fixture_with_explicit_protocol(small_package):
    module, output, _ = small_package
    script = module.ROOT / "scripts/run_synthetic_prediction_history.py"
    code = (
        "import importlib.util,sys;"
        f"p={str(script)!r};s=importlib.util.spec_from_file_location('h',p);m=importlib.util.module_from_spec(s);s.loader.exec_module(m);"
        f"m.PROTOCOL={module.PROTOCOL!r};sys.exit(m.main(['--verify-dir',{str(output)!r}]))"
    )
    completed = subprocess.run(
        [str(module.ROOT / "backend/.venv/Scripts/python.exe"), "-c", code],
        cwd=module.ROOT / "backend", capture_output=True, text=True, check=False,
    )
    assert completed.returncode == 0, completed.stdout + completed.stderr
    assert json.loads(completed.stdout.strip().splitlines()[-1])["status"] == "passed"


def test_tamper_and_rehash_cannot_pass(small_package, tmp_path):
    module, output, _ = small_package
    changed = tmp_path / "changed"
    shutil.copytree(output, changed)
    path = changed / "seed-20260914/predictions.json"
    rows = json.loads(path.read_text())
    valid = next(row for row in rows if row["status"] == "valid")
    valid["value"] += 1
    path.write_text(json.dumps(rows), encoding="utf-8")
    manifest = json.loads((changed / "manifest.json").read_text())
    manifest["files"] = module._file_records(changed)
    manifest["data_content_sha256"] = module._hash(manifest["files"])
    (changed / "manifest.json").write_text(json.dumps(manifest), encoding="utf-8")
    assert module.verify(changed)["status"] == "failed"


@pytest.mark.parametrize("kind", ["input", "model", "score"])
def test_rehashed_input_model_or_score_tamper_cannot_pass(small_package, tmp_path, kind):
    module, output, _ = small_package
    changed = tmp_path / kind
    shutil.copytree(output, changed)
    paths = {
        "input": changed / "seed-20260914/features.json",
        "model": changed / "seed-20260914/models.json",
        "score": changed / "seed-20260914/challenge/evaluation.json",
    }
    path = paths[kind]
    value = json.loads(path.read_text(encoding="utf-8"))
    if kind == "input":
        value[0]["anchor_value"] += 1
    elif kind == "model":
        next(row for row in value if row["status"] == "fitted")["mean"][0] += 1
    else:
        value["comparisons"][0]["statistics"]["mae"] += 1
    path.write_text(json.dumps(value), encoding="utf-8")
    manifest = json.loads((changed / "manifest.json").read_text())
    manifest["files"] = module._file_records(changed)
    manifest["data_content_sha256"] = module._hash(manifest["files"])
    (changed / "manifest.json").write_text(json.dumps(manifest), encoding="utf-8")
    assert module.verify(changed)["status"] == "failed"


def test_extra_file_is_rejected_before_source_recalculation(small_package, tmp_path, monkeypatch):
    module, output, _ = small_package
    changed = tmp_path / "changed"
    shutil.copytree(output, changed)
    (changed / "extra.json").write_text("{}", encoding="utf-8")
    monkeypatch.setattr(module, "_source", lambda seed: (_ for _ in ()).throw(AssertionError("source called")))
    assert module.verify(changed)["reason"] == "file_integrity_mismatch"


def test_current_protocol_change_is_rejected_before_source_recalculation(small_package, monkeypatch):
    module, output, _ = small_package
    monkeypatch.setattr(module, "PROTOCOL", {**module.PROTOCOL, "bootstrap_seed": 1})
    monkeypatch.setattr(module, "_source", lambda seed: (_ for _ in ()).throw(AssertionError("source called")))
    assert module.verify(output)["reason"] == "protocol_runtime_or_code_mismatch"


def test_runtime_change_is_rejected_before_source_recalculation(small_package, monkeypatch):
    module, output, _ = small_package
    monkeypatch.setattr(module, "_runtime", lambda: {"python": "changed"})
    monkeypatch.setattr(module, "_source", lambda seed: (_ for _ in ()).throw(AssertionError("source called")))
    assert module.verify(output)["reason"] == "protocol_runtime_or_code_mismatch"


def test_code_identity_change_is_rejected_before_source_recalculation(small_package, monkeypatch):
    module, output, _ = small_package
    monkeypatch.setattr(module, "CODE_FILES", module.CODE_FILES[:-1])
    monkeypatch.setattr(module, "_source", lambda seed: (_ for _ in ()).throw(AssertionError("source called")))
    assert module.verify(output)["reason"] == "protocol_runtime_or_code_mismatch"


def test_recorded_first_fit_error_is_not_retried_by_verifier(tmp_path, monkeypatch):
    from sklearn.linear_model import Ridge

    module = api()
    module.PROTOCOL = {
        **module.PROTOCOL, "seeds": [20260914], "patients_per_disease": 60,
        "challenge_per_disease": 20, "training_groups_per_disease": 32,
        "is_test_fixture": True, "test_fixture_purpose": "fit_error_replay_test_only",
    }
    original = Ridge.fit
    calls = []
    def fail_first(self, X, y, **kwargs):
        calls.append(1)
        if len(calls) == 1:
            raise RuntimeError("sensitive first failure")
        return original(self, X, y, **kwargs)
    monkeypatch.setattr(Ridge, "fit", fail_first)
    output = tmp_path / "fit-error"
    result = module.run(output)
    assert result["status"] == "incomplete"
    assert len(calls) == 20
    verified = module.verify(output)
    assert verified["status"] == "passed" and verified["engineering_status"] == "incomplete"
    assert verified["fit_error_verification"] == "inputs_checked_not_retried"
    assert len(calls) == 39
