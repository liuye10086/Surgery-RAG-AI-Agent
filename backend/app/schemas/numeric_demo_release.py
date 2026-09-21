"""Strict, synthetic-only record for a supervised local demo release."""

from datetime import datetime
from pathlib import PurePath
from typing import Annotated, Literal

from pydantic import Field, StrictInt, field_validator, model_validator

from app.schemas.synthetic_numeric_prediction import Sha, StrictNumericModel


Count = Annotated[StrictInt, Field(ge=0)]
Version = Annotated[str, Field(min_length=1, max_length=80, pattern=r"^[A-Za-z0-9._+-]+$")]
GitCommit = Annotated[str, Field(pattern=r"^[0-9a-f]{40}$")]
RunId = Annotated[str, Field(min_length=1, max_length=80, pattern=r"^[A-Za-z0-9][A-Za-z0-9._-]*$")]
SafeName = Annotated[str, Field(min_length=1, max_length=120, pattern=r"^[A-Za-z_][A-Za-z0-9_.-]*$")]


class SafeCodeLocation(StrictNumericModel):
    file: Annotated[str, Field(min_length=1, max_length=160)]
    line: Annotated[StrictInt, Field(ge=1)]
    function: SafeName

    @field_validator("file")
    @classmethod
    def basename_only(cls, value: str) -> str:
        if value != PurePath(value).name or "/" in value or "\\" in value:
            raise ValueError("diagnostic_basename_required")
        return value


class SafeReleaseDiagnostic(StrictNumericModel):
    stage: SafeName
    error_type: SafeName
    error_location: list[SafeCodeLocation] = Field(default_factory=list, max_length=32)


class NumericDemoReleaseIdentities(StrictNumericModel):
    source_manifest_sha256: Sha
    source_data_content_sha256: Sha
    legacy_bundle_sha256: Sha
    history_bundle_sha256: Sha
    renderer_manifest_sha256: Sha
    acceptance_result_sha256: Sha
    git_commit: GitCommit


class NumericDemoReleaseRuntime(StrictNumericModel):
    python_version: Version
    node_version: Version
    playwright_version: Version
    fonttools_version: Version
    chromium_version: Version


class AdmissionMetrics(StrictNumericModel):
    requests: Count
    idempotency_replays: Count
    rejected: Count
    admission_disabled: Count
    permission_denied: Count
    invalid_input: Count
    conflict: Count


FailurePhase = Literal[
    "queued",
    "model_loading",
    "prediction",
    "standard_evidence",
    "rendering",
    "persistence",
    "terminal",
    "unknown",
]


class JobMetrics(StrictNumericModel):
    queued: Count
    running: Count
    completed: Count
    failed: Count
    cancelled: Count
    unsettled: Count
    phase_timeouts: Count
    # Which phase timed out, so the count is diagnosable without the payloads.
    phase_timeout_phases: list[FailurePhase] = Field(default_factory=list, max_length=8)

    @field_validator("phase_timeout_phases")
    @classmethod
    def sorted_unique_phases(cls, value):
        if value != sorted(set(value)):
            raise ValueError("phase_timeout_phases_not_sorted_unique")
        return value

    @model_validator(mode="after")
    def phases_match_the_timeout_count(self):
        if len(self.phase_timeout_phases) > self.phase_timeouts:
            raise ValueError("phase_timeout_phases_exceed_count")
        return self


class PhaseTimingMetrics(StrictNumericModel):
    samples: Count
    total_ms: Count
    max_ms: Count

    @model_validator(mode="after")
    def coherent_empty_timing(self):
        if self.samples == 0 and (self.total_ms != 0 or self.max_ms != 0):
            raise ValueError("empty_timing_must_be_zero")
        if self.samples > 0 and self.max_ms > self.total_ms:
            raise ValueError("timing_max_exceeds_total")
        return self


class ExecutionTimingMetrics(StrictNumericModel):
    model_loading: PhaseTimingMetrics
    prediction: PhaseTimingMetrics
    standard_evidence: PhaseTimingMetrics
    rendering: PhaseTimingMetrics
    persistence: PhaseTimingMetrics


class LlmAuditMetrics(StrictNumericModel):
    invocation_started: Count
    task_finished: Count
    closed_reports: Count
    unclosed_reports: Count


class AuthorizationMetrics(StrictNumericModel):
    non_owner_404: Count
    wrong_role_403: Count
    disease_permission_denied: Count


class HistoryMetrics(StrictNumericModel):
    verified_reports: Count
    mismatches: Count


class PdfMetrics(StrictNumericModel):
    ready: Count
    failed: Count
    missing: Count
    corrupt: Count
    downloads: Count
    bytes_verified: Count
    sha_mismatches: Count


class IdentityMetrics(StrictNumericModel):
    source_matches: bool
    legacy_bundle_matches: bool
    history_bundle_matches: bool
    renderer_matches: bool
    acceptance_matches: bool
    git_commit_matches: bool

    @field_validator("*", mode="before")
    @classmethod
    def strict_bool(cls, value):
        if type(value) is not bool:
            raise ValueError("explicit_boolean_required")
        return value


class NumericDemoReleaseMetrics(StrictNumericModel):
    admission: AdmissionMetrics
    jobs: JobMetrics
    timings: ExecutionTimingMetrics
    llm_audit: LlmAuditMetrics
    authorization: AuthorizationMetrics
    history: HistoryMetrics
    pdf: PdfMetrics
    identity: IdentityMetrics


# The supervisor's evaluation reads exactly the file the browser session writes.
SESSION_CHECKS_FILENAME = "session-checks.json"
DemoCheckName = Literal["non_owner_404", "wrong_role_403", "idempotency_replay"]
# The closed set of checks the demo browser session must actually perform.
# Every name here has a matching counter below, so a check that observed
# nothing fails validation instead of being reported as a pass.
DEMO_SESSION_CHECKS: tuple[str, ...] = (
    "non_owner_404",
    "wrong_role_403",
    "idempotency_replay",
)


class DemoSessionAdmission(StrictNumericModel):
    submissions: Count
    accepted: Count
    idempotency_replays: Count
    admission_disabled: Count
    permission_denied: Count
    invalid_input: Count
    conflict: Count
    non_owner_404: Count
    wrong_role_403: Count
    disease_permission_denied: Count

    @model_validator(mode="after")
    def outcomes_account_for_every_submission(self):
        outcomes = (
            self.accepted
            + self.idempotency_replays
            + self.admission_disabled
            + self.permission_denied
            + self.invalid_input
            + self.conflict
        )
        if outcomes != self.submissions:
            raise ValueError("session_outcomes_do_not_match_submissions")
        return self


class NumericDemoSessionChecks(StrictNumericModel):
    """Outcomes the browser session observed itself; never inferred from silence."""

    schema_version: Literal["numeric_demo_session_checks.v1"]
    performed: list[DemoCheckName]
    admission: DemoSessionAdmission

    @model_validator(mode="after")
    def every_named_check_observed(self):
        if sorted(self.performed) != sorted(DEMO_SESSION_CHECKS):
            raise ValueError("demo_session_check_set_mismatch")
        if (
            self.admission.non_owner_404 < 1
            or self.admission.wrong_role_403 < 1
            or self.admission.idempotency_replays < 1
        ):
            raise ValueError("demo_session_check_not_observed")
        return self


class NumericDemoReleaseRecord(StrictNumericModel):
    schema_version: Literal["numeric_history_demo_release.v1"]
    run_id: RunId
    status: Literal["starting", "running", "stopped", "failed"]
    is_synthetic: Literal[True]
    clinical_validity_claim: Literal[False]
    clinical_status: Literal["not_assessable"]
    production_enabled: Literal[False]
    started_at: datetime
    stopped_at: datetime | None
    identities: NumericDemoReleaseIdentities
    runtime: NumericDemoReleaseRuntime
    metrics: NumericDemoReleaseMetrics
    diagnostics: list[SafeReleaseDiagnostic] = Field(default_factory=list, max_length=128)
    cleanup_errors: list[SafeReleaseDiagnostic] = Field(default_factory=list, max_length=128)

    @field_validator(
        "is_synthetic", "clinical_validity_claim", "production_enabled", mode="before"
    )
    @classmethod
    def explicit_boolean(cls, value):
        if type(value) is not bool:
            raise ValueError("explicit_boolean_required")
        return value

    @field_validator("started_at", "stopped_at")
    @classmethod
    def timezone_required(cls, value: datetime | None):
        if value is not None and (
            value.tzinfo is None or value.utcoffset() is None
        ):
            raise ValueError("timezone_required")
        return value

    @model_validator(mode="after")
    def lifecycle_times(self):
        terminal = self.status in {"stopped", "failed"}
        if terminal != (self.stopped_at is not None):
            raise ValueError("release_stop_time_mismatch")
        if self.stopped_at is not None and self.stopped_at < self.started_at:
            raise ValueError("release_time_order_invalid")
        return self
