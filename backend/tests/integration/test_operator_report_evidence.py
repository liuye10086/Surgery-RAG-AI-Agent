"""End-to-end evidence acceptance scenarios run only in deployment CI."""

import os

import pytest


@pytest.mark.integration
def test_operator_report_evidence_requires_explicit_pg_fixture():
    if not os.getenv("TEST_DATABASE_URL"):
        pytest.skip("TEST_DATABASE_URL is not configured")

