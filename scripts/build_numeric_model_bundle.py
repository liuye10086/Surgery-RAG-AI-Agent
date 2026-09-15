"""Build fixed JSON numeric models in a new directory without publishing them."""

import argparse
import json
from pathlib import Path
import sys


BACKEND = Path(__file__).resolve().parents[1] / 'backend'
if str(BACKEND) not in sys.path:
    sys.path.insert(0, str(BACKEND))

from app.services.numeric_model_bundle import build_numeric_model_bundle


class SafeParser(argparse.ArgumentParser):
    def error(self, message):
        raise ValueError('invalid_arguments')


def _print(value):
    print(json.dumps(value, ensure_ascii=False, sort_keys=True))


def main(argv=None):
    parser = SafeParser(description=__doc__, allow_abbrev=False)
    parser.add_argument('--source-dir', required=True, type=Path)
    parser.add_argument('--calculation-dir', required=True, type=Path)
    parser.add_argument('--output-dir', required=True, type=Path)
    try:
        args = parser.parse_args(argv)
    except ValueError:
        _print({'status': 'error', 'error': 'invalid_arguments'})
        return 2
    try:
        result = build_numeric_model_bundle(args.source_dir, args.calculation_dir, args.output_dir)
    except FileExistsError:
        _print({'status': 'error', 'error': 'output_exists'})
        return 2
    except ValueError:
        _print({'status': 'error', 'error': 'numeric_model_not_verified'})
        return 3
    except Exception:
        _print({'status': 'error', 'error': 'numeric_model_runtime_error'})
        return 4
    _print(result)
    return 0 if result['status'] == 'passed' else 3


if __name__ == '__main__':
    raise SystemExit(main())
