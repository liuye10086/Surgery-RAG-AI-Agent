"""Preflight by default; explicitly rebuild one frozen RF or replay saved JSON."""

import argparse
import json
from pathlib import Path
import sys

BACKEND = Path(__file__).resolve().parents[1] / 'backend'
if str(BACKEND) not in sys.path:
    sys.path.insert(0, str(BACKEND))

from app.services.numeric_history_bundle_build import (
    BuildError, build_numeric_history_bundle, preflight_numeric_history_bundle, verify_numeric_history_bundle,
)


class SafeParser(argparse.ArgumentParser):
    def error(self, message):
        raise ValueError('invalid_arguments')


def main(argv=None):
    parser = SafeParser(description=__doc__, allow_abbrev=False)
    parser.add_argument('--history-dir', type=Path)
    parser.add_argument('--legacy-bundle', type=Path)
    parser.add_argument('--output-dir', type=Path)
    parser.add_argument('--build', action='store_true')
    parser.add_argument('--verify-dir', type=Path)
    try:
        args = parser.parse_args(argv)
        if args.verify_dir:
            if args.history_dir or args.legacy_bundle or args.output_dir or args.build:
                raise ValueError('invalid_arguments')
        elif not all((args.history_dir, args.legacy_bundle, args.output_dir)):
            raise ValueError('invalid_arguments')
    except SystemExit as exc:
        return int(exc.code)
    except ValueError:
        print(json.dumps({'status': 'error', 'error': 'invalid_arguments'}))
        return 2
    code = 0
    try:
        if args.verify_dir:
            result = verify_numeric_history_bundle(args.verify_dir)
        else:
            operation = build_numeric_history_bundle if args.build else preflight_numeric_history_bundle
            result = operation(args.history_dir, args.legacy_bundle, args.output_dir)
    except FileExistsError:
        result, code = {'status': 'error', 'error': 'output_exists'}, 2
    except BuildError as exc:
        result, code = {'status': 'error', 'error': str(exc)}, 3
    except (ValueError, KeyError, TypeError, OSError):
        result, code = {'status': 'error', 'error': 'numeric_history_not_verified'}, 3
    except Exception:
        result, code = {'status': 'error', 'error': 'numeric_history_runtime_error'}, 4
    print(json.dumps(result, ensure_ascii=False, sort_keys=True))
    return code if code else (0 if result.get('status') == 'passed' else 3)


if __name__ == '__main__':
    raise SystemExit(main())
