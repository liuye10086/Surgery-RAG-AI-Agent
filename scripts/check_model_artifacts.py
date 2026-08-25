"""Print and optionally verify model artifact SHA-256 checksums."""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path


def sha256_file(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def sha256_manifest(directory: Path, patterns: tuple[str, ...] = ("*.joblib", "*.meta.json")) -> dict[str, str]:
    manifest: dict[str, str] = {}
    for pattern in patterns:
        for path in directory.rglob(pattern):
            if path.is_file():
                digest = sha256_file(path)
                manifest[str(path.relative_to(directory)).replace("\\", "/")] = digest
    return dict(sorted(manifest.items()))


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--models-dir", type=Path, required=True)
    parser.add_argument("--baseline", type=Path)
    args = parser.parse_args()
    current = sha256_manifest(args.models_dir)
    print(json.dumps(current, ensure_ascii=False, indent=2))
    if args.baseline:
        expected = json.loads(args.baseline.read_text(encoding="utf-8"))
        return 0 if current == expected else 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
