"""Seed verified development input snippets only into an explicit local *_test DB."""

import argparse
import hashlib
import json
import os
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'backend'))

from app.services.prediction_case_source import convert_legacy_input, require_isolated_test_database
from app.services.synthetic_case_source import load_synthetic_case_package, _read_file, _json, _safe_directory
from app.schemas.synthetic_case_source import SyntheticPackageManifest


def load_reference_rows(source_dir: Path, *, limit_per_disease=8):
    if type(limit_per_disease) is not int or not 1 <= limit_per_disease <= 80:
        raise ValueError('numeric_reference_limit_invalid')
    source_dir = Path(source_dir).absolute()
    source_dir = _safe_directory(source_dir, source_dir.parent)
    manifest = SyntheticPackageManifest.model_validate(_json(_read_file(source_dir, 'manifest.json')))
    if manifest.quality_status != 'passed':
        raise ValueError('numeric_reference_quality_required')
    audit_bytes = _read_file(source_dir, 'generation_audit.jsonl')
    entry = manifest.files['generation_audit.jsonl']
    if (len(audit_bytes), hashlib.sha256(audit_bytes).hexdigest()) != (entry.bytes, entry.sha256):
        raise ValueError('numeric_reference_pool_hash_mismatch')
    audit_rows = [_json(line) for line in audit_bytes.splitlines()]
    if len({r['subject_id'] for r in audit_rows}) != len(audit_rows):
        raise ValueError('numeric_reference_duplicate_subject')
    development = {r['subject_id']: r['dependency_group_id'] for r in audit_rows if r['pool'] == 'development_pool'}
    # Loader verifies the original manifest and only opens patient / prediction-input files.
    selected = load_synthetic_case_package(source_dir, sorted(development), trusted_root=source_dir.parent)
    counts, result = {'ad': 0, 'fatty_liver': 0}, []
    for patient, old in sorted(selected, key=lambda row: (row[1].anchor_date, row[1].subject_id)):
        numeric = convert_legacy_input(old)
        if numeric.dependency_group_id != development[numeric.subject_id]:
            raise ValueError('numeric_reference_pool_identity_mismatch')
        if counts[numeric.disease_code] >= limit_per_disease:
            continue
        observations = numeric.packets[0].input_observations
        if not observations:
            continue
        title = '认知评分输入记录' if numeric.disease_code == 'ad' else '肝功能输入记录'
        lines = [f"{r.measured_on.isoformat()}测量，{r.known_on.isoformat()}已知：{r.indicator.upper()} {r.value:g} {r.unit}。"
                 for r in sorted(observations, key=lambda r: r.measured_on)]
        result.append({'title': title, 'content': '\n'.join(lines), 'metadata': {
            'numeric_reference_version': 'numeric_reference.v1', 'disease_code': numeric.disease_code,
            'subject_id': numeric.subject_id, 'dependency_group_id': numeric.dependency_group_id,
            'known_on': max(r.known_on for r in observations).isoformat(), 'pool': 'development_pool',
            'source': numeric.source.model_dump(mode='json'),
        }})
        counts[numeric.disease_code] += 1
    if any(count < limit_per_disease for count in counts.values()):
        raise ValueError('numeric_reference_development_inputs_insufficient')
    return result


def seed_numeric_reference_corpus(db, source_dir, *, limit_per_disease=8):
    require_isolated_test_database(db.get_bind().url)
    rows = load_reference_rows(Path(source_dir), limit_per_disease=limit_per_disease)
    from sqlalchemy import text
    from langchain_postgres import PGVector
    from app.core.config import settings
    from app.db.models import Chunk, Document
    from app.rag.adapters import SurgeryEmbeddings
    from app.rag.vectorstore import add_chunks
    # Pin PGVector to the actual guarded connection; never use application DB defaults.
    store = PGVector(connection=db.get_bind(), embeddings=SurgeryEmbeddings(), collection_name=settings.VECTOR_COLLECTION_NAME)
    db.execute(text('CREATE EXTENSION IF NOT EXISTS pg_trgm'))
    db.execute(text('CREATE INDEX IF NOT EXISTS idx_langchain_embedding_document_trgm ON langchain_pg_embedding USING GIN (document gin_trgm_ops)'))
    documents, chunks = [], []
    for index, row in enumerate(rows):
        document = Document(title=row['title'], filename=f'numeric-reference-{index + 1}.txt',
                            file_type='txt', status='processing', version=1, active_generation=1,
                            is_current=False, department_id=None, access_scope='operator')
        db.add(document)
        db.flush()
        chunk = Chunk(document=document, content=row['content'], chunk_metadata=row['metadata'],
                      chunk_index=0, generation=1, is_current=False)
        db.add(chunk)
        db.flush()
        documents.append(document)
        chunks.append(chunk)
    # Inactive records survive an embedding failure but can never enter retrieval.
    db.commit()
    add_chunks(store, chunks)
    for document, chunk in zip(documents, chunks):
        document.status, document.is_current, chunk.is_current = 'indexed', True, True
    db.commit()
    return [chunk.id for chunk in chunks]


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--source-dir', type=Path, required=True)
    parser.add_argument('--limit-per-disease', type=int, default=8)
    parser.add_argument('--apply', action='store_true')
    args = parser.parse_args(argv)
    if not args.apply:
        rows = load_reference_rows(args.source_dir, limit_per_disease=args.limit_per_disease)
        print(json.dumps({'status': 'validated', 'reference_count': len(rows)}))
        return 0
    from sqlalchemy import create_engine
    from sqlalchemy.engine import make_url
    from sqlalchemy.orm import Session
    url = os.environ.get('TEST_DATABASE_URL', '')
    try:
        target = make_url(url)
    except Exception:
        raise ValueError('isolated_test_database_required') from None
    require_isolated_test_database(target)
    engine = create_engine(target)
    try:
        with Session(engine) as db:
            ids = seed_numeric_reference_corpus(db, args.source_dir, limit_per_disease=args.limit_per_disease)
        print(json.dumps({'status': 'indexed', 'chunk_ids': ids}))
        return 0
    finally:
        engine.dispose()


if __name__ == '__main__':
    raise SystemExit(main())
