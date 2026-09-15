"""Validate selected synthetic subjects; --apply writes only to TEST_DATABASE_URL."""

import argparse
import json
import os
from pathlib import Path
import sys


BACKEND = Path(__file__).resolve().parents[1] / 'backend'
if str(BACKEND) not in sys.path:
    sys.path.insert(0, str(BACKEND))

from sqlalchemy.engine import make_url

from app.services.synthetic_case_source import (
    SyntheticCaseSourceError, load_synthetic_case_package,
    require_isolated_test_database, seed_synthetic_cases,
)


class SafeParser(argparse.ArgumentParser):
    def error(self, message):
        raise ValueError('invalid_arguments')


def _print(value):
    print(json.dumps(value, ensure_ascii=False, sort_keys=True))


def main(argv=None):
    parser = SafeParser(description=__doc__, allow_abbrev=False)
    parser.add_argument('--package-dir', type=Path, required=True)
    parser.add_argument('--user-id', type=int, required=True)
    parser.add_argument('--subject-id', action='append', required=True)
    parser.add_argument('--apply', action='store_true')
    try:
        args = parser.parse_args(argv)
        if args.user_id <= 0:
            raise ValueError('invalid_arguments')
    except ValueError:
        _print({'status': 'error', 'error': 'invalid_arguments'})
        return 2
    try:
        # No .env loading and no fallback to application DATABASE_URL.
        configured_url = os.environ.get('TEST_DATABASE_URL')
        if not configured_url:
            raise SyntheticCaseSourceError('test_database_url_required')
        try:
            url = make_url(configured_url)
        except Exception:
            raise SyntheticCaseSourceError('isolated_test_database_required') from None
        require_isolated_test_database(url)
        if not args.apply:
            selected = load_synthetic_case_package(args.package_dir, args.subject_id)
            _print({'status': 'dry_run', 'selected_count': len(selected), 'is_synthetic': True})
            return 0
        from sqlalchemy import create_engine
        from sqlalchemy.orm import sessionmaker

        engine = create_engine(url, echo=False)
        try:
            ids = seed_synthetic_cases(sessionmaker(bind=engine), args.package_dir, args.user_id, args.subject_id)
        finally:
            engine.dispose()
        _print({'status': 'created', 'created_count': len(ids), 'is_synthetic': True})
        return 0
    except SyntheticCaseSourceError as exc:
        _print({'status': 'error', 'error': exc.code})
        return 2
    except Exception:
        # Stable errors only: never emit connection strings, paths, or source payloads.
        _print({'status': 'error', 'error': 'synthetic_seed_runtime_error'})
        return 4


if __name__ == '__main__':
    raise SystemExit(main())
