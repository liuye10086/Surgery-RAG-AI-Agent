"""Git checkout must preserve the exact source bytes frozen by existing assets.

These identities come from the retained numeric bundles and the 2026-09-20
renderer. No generated outputs, model training, browser or database is needed.
"""

import ast
import hashlib
import json
from pathlib import Path
import subprocess

import pytest


ROOT = Path(__file__).resolve().parents[2]
LEGACY_IMPLEMENTATION = "5b3827d8c00cca3f688c2d8a94af7167651d0977768951b8d5c682feaa69553c"
HISTORY_IMPLEMENTATION = "71e1fd0731cde20009c514c9b756bde8c20c4173e9570e4f84c372aefe33dfb0"
EXPECTED_IDENTITIES = {
    "legacy": LEGACY_IMPLEMENTATION,
    "history": HISTORY_IMPLEMENTATION,
    "renderer_sources": "2d17ad2bc013b637868f207588db38f38db34e2b9c9a5db1f4e575eddfa4bf69",
}


def _literal_assignment(path, name, *, function=None):
    tree = ast.parse((ROOT / path).read_text(encoding="utf-8"))
    if function:
        tree = next(node for node in tree.body
                    if isinstance(node, ast.FunctionDef) and node.name == function)
    return next(ast.literal_eval(node.value) for node in tree.body
                if isinstance(node, ast.Assign)
                and any(isinstance(target, ast.Name) and target.id == name
                        for target in node.targets))


LEGACY_FILES = _literal_assignment(
    "backend/app/services/numeric_model_bundle.py", "files",
    function="_implementation_files",
)
HISTORY_FILES = _literal_assignment(
    "backend/app/services/numeric_history_bundle.py", "SOURCE_FILES",
)
RENDERER_FILES = _literal_assignment(
    "backend/app/services/report_pdf_renderer_manifest.py", "RENDERER_FILES",
)
SOURCE_FILES = sorted(set(LEGACY_FILES) | set(HISTORY_FILES)
                      | {"backend/app/" + name for name in RENDERER_FILES})


def _json_sha(value):
    raw = json.dumps(value, ensure_ascii=False, sort_keys=True,
                     separators=(",", ":"), allow_nan=False).encode("utf-8")
    return hashlib.sha256(raw).hexdigest()


def _identities(root):
    def digest(name):
        return hashlib.sha256((root / name).read_bytes()).hexdigest()

    legacy = _json_sha({name: digest(name) for name in LEGACY_FILES})
    history = _json_sha({
        "source_sha256": {name: digest(name) for name in HISTORY_FILES},
        "legacy_implementation_sha256": legacy,
    })
    renderer = _json_sha({name: digest("backend/app/" + name)
                          for name in RENDERER_FILES})
    return {"legacy": legacy, "history": history, "renderer_sources": renderer}


def _git(root, *args):
    return subprocess.run(
        ["git", "-C", str(root), "-c", "core.safecrlf=false", *args],
        check=True, capture_output=True, text=True, encoding="utf-8",
    )


@pytest.mark.parametrize("autocrlf", ["true", "false"])
def test_git_checkout_preserves_frozen_source_identities(tmp_path, autocrlf):
    repo = tmp_path / "repo"
    checkout = tmp_path / "checkout"
    repo.mkdir()
    checkout.mkdir()
    _git(repo, "init", "--quiet")
    _git(repo, "config", "core.autocrlf", autocrlf)
    for name in [".gitattributes", *SOURCE_FILES]:
        destination = repo / name
        destination.parent.mkdir(parents=True, exist_ok=True)
        destination.write_bytes((ROOT / name).read_bytes())
    _git(repo, "add", "--", ".gitattributes", *SOURCE_FILES)
    # Export the actual index through Git's checkout conversion. No commit is made.
    _git(repo, "checkout-index", "--all", "--force",
         "--prefix=" + checkout.as_posix() + "/")
    assert _identities(checkout) == EXPECTED_IDENTITIES


def test_working_tree_preserves_frozen_source_identities():
    assert _identities(ROOT) == EXPECTED_IDENTITIES
