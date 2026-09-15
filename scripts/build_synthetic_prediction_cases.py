"""Generate a fresh synthetic software-verification package, without importing it."""

import argparse
import json
from pathlib import Path
import sys


BACKEND = Path(__file__).resolve().parents[1] / "backend"
if str(BACKEND) not in sys.path:
    sys.path.insert(0, str(BACKEND))

from app.schemas.synthetic_prediction_cases import GenerationConfig
from app.services.synthetic_prediction_case_export import export_synthetic_cases


class SafeParser(argparse.ArgumentParser):
    def error(self, message):
        raise ValueError("invalid_arguments")


def _print(value):
    print(json.dumps(value, ensure_ascii=False, sort_keys=True))


def main(argv=None):
    parser = SafeParser(description=__doc__, allow_abbrev=False)
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--seed", type=int, default=20260914)
    parser.add_argument("--patients-per-disease", type=int, default=120)
    parser.add_argument("--challenge-per-disease", type=int, default=40)
    try:
        args = parser.parse_args(argv)
        config = GenerationConfig(seed=args.seed, patients_per_disease=args.patients_per_disease,
                                  challenge_per_disease=args.challenge_per_disease)
    except ValueError:
        _print({"status": "error", "error": "invalid_arguments"})
        return 2
    try:
        result = export_synthetic_cases(config, args.output_dir)
    except FileExistsError:
        _print({"status": "error", "error": "output_exists"})
        return 2
    except Exception:
        # This command only prints stable codes, never exception paths or payloads.
        _print({"status": "error", "error": "generation_runtime_error"})
        return 4
    _print(result)
    return 0 if result["status"] == "passed" else 3


if __name__ == "__main__":
    raise SystemExit(main())
