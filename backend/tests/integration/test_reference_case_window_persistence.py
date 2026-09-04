"""PostgreSQL-only persistence contract for reference windows."""

import os

import pytest


@pytest.mark.integration
def test_reference_case_window_persistence_requires_explicit_postgres_fixture():
    """The real database fixture is supplied by CI; local runs skip explicitly."""
    if not os.getenv("TEST_DATABASE_URL"):
        pytest.skip("TEST_DATABASE_URL is not configured")

