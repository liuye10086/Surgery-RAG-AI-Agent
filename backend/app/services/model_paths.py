"""Filesystem locations shared by longitudinal model services and tools."""

from pathlib import Path


MODEL_DIR = Path(__file__).resolve().parents[1] / "ml_models"
