"""Opt-in browser fixtures; no production URL or credentials are inferred."""

from __future__ import annotations

import os
from urllib.parse import urlparse

import pytest
from playwright.sync_api import Page, Playwright, sync_playwright


BASE_URL = os.getenv("E2E_BASE_URL")
if BASE_URL and (
    urlparse(BASE_URL).hostname not in ("127.0.0.1", "localhost")
    or urlparse(BASE_URL).port != 15173
):
    raise RuntimeError("E2E_BASE_URL must use the isolated local test harness")
TOKEN_A = os.getenv("E2E_OPERATOR_TOKEN_A")
TOKEN_B = os.getenv("E2E_OPERATOR_TOKEN_B")

pytestmark = pytest.mark.e2e


@pytest.fixture(scope="session")
def playwright_instance():
    if not BASE_URL or not TOKEN_A or not TOKEN_B:
        pytest.skip("E2E_BASE_URL and two explicit operator tokens are required")
    with sync_playwright() as playwright:
        yield playwright


@pytest.fixture()
def browser_page(playwright_instance: Playwright, request):
    browser = playwright_instance.chromium.launch(headless=True)
    context = browser.new_context(base_url=BASE_URL)
    page = context.new_page()
    errors=[]
    page.on('pageerror',lambda error:errors.append(str(error)))
    yield page
    from pathlib import Path
    import re,json
    output=Path(__file__).resolve().parents[3]/'outputs/operator-report-verification/browser'
    output.mkdir(parents=True,exist_ok=True)
    name=re.sub(r'[^a-zA-Z0-9_-]','_',request.node.name)
    page.screenshot(path=str(output/(name+'.png')),full_page=True)
    (output/(name+'.html')).write_text(page.content(),encoding='utf-8')
    (output/(name+'-errors.json')).write_text(json.dumps(errors),encoding='utf-8')
    context.close()
    browser.close()


@pytest.fixture()
def operator_tokens():
    return {"a": TOKEN_A, "b": TOKEN_B}
