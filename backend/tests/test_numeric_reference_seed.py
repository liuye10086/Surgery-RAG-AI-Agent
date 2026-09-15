import importlib.util
from pathlib import Path

import pytest
from sqlalchemy.engine import make_url


def seed_module():
    spec = importlib.util.spec_from_file_location('numeric_seed', Path(__file__).resolve().parents[2] / 'scripts/seed_numeric_reference_corpus.py')
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_reference_loader_never_opens_outcomes_and_only_uses_development_inputs(monkeypatch):
    module = seed_module()
    root = Path(__file__).resolve().parents[2] / 'outputs/synthetic-prediction-cases/2026-09-14-v1'
    original = Path.read_bytes
    def read(path):
        assert path.name not in {'followup_outcomes.jsonl', 'observations.jsonl', 'expected_results.jsonl'}
        return original(path)
    monkeypatch.setattr(Path, 'read_bytes', read)
    rows = module.load_reference_rows(root, limit_per_disease=2)
    assert len(rows) == 4
    assert {r['metadata']['disease_code'] for r in rows} == {'ad', 'fatty_liver'}
    assert all(r['metadata']['pool'] == 'development_pool' for r in rows)
    assert all('合成' not in r['content'] and 'synthetic' not in r['content'] for r in rows)


@pytest.mark.parametrize('url', ['postgresql://localhost/business', 'postgresql://remote/case_test'])
def test_reference_seed_refuses_nonisolated_engine_before_any_work(url):
    module = seed_module()
    class DB:
        def get_bind(self):
            return type('Bind', (), {'url': make_url(url)})()
    with pytest.raises(ValueError, match='isolated_test_database_required'):
        module.seed_numeric_reference_corpus(DB(), Path('missing'), limit_per_disease=2)
