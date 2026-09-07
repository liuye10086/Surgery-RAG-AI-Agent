"""Test-only HTTP host: real operator/auth routers without unrelated RAG warmup."""

import os
from urllib.parse import urlparse

url = urlparse(os.environ.get("DATABASE_URL", ""))
if url.hostname not in ("localhost", "127.0.0.1") or not url.path.endswith("_test"):
    raise RuntimeError("explicit_local_test_database_required")

from fastapi import FastAPI
from fastapi.exceptions import RequestValidationError
from app.api import operator, operator_report_jobs, operator_report_history, operator_report_archives, auth, user
from app.core.validation_errors import request_validation_exception_handler

app = FastAPI()
app.add_exception_handler(RequestValidationError, request_validation_exception_handler)
for router in (auth.router, user.router, operator.router, operator_report_jobs.router, operator_report_history.router, operator_report_archives.router):
    app.include_router(router, prefix="/api/v1")


@app.get("/health")
def health():
    return {"status": "ok", "environment": "isolated_test"}

@app.middleware("http")
async def private_reports(request, call_next):
    response = await call_next(request)
    if request.url.path.startswith(("/api/v1/operator/reports", "/api/v1/operator/report-history")):
        response.headers["Cache-Control"] = "private, no-store"
        response.headers["Pragma"] = "no-cache"
    return response
