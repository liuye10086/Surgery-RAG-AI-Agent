"""Test-only HTTP host: real operator/auth routers without unrelated RAG warmup."""

import os
from urllib.parse import urlparse

url = urlparse(os.environ.get("DATABASE_URL", ""))
if url.hostname not in ("localhost", "127.0.0.1") or not url.path.endswith("_test"):
    raise RuntimeError("explicit_local_test_database_required")

from fastapi import FastAPI
from fastapi.exceptions import RequestValidationError
from app.api import operator, operator_report_jobs, auth, user
from app.core.validation_errors import request_validation_exception_handler

app = FastAPI()
app.add_exception_handler(RequestValidationError, request_validation_exception_handler)
for router in (auth.router, user.router, operator.router, operator_report_jobs.router):
    app.include_router(router, prefix="/api/v1")


@app.get("/health")
def health():
    return {"status": "ok", "environment": "isolated_test"}
