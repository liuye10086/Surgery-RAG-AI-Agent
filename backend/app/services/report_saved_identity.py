"""Historical identity is independent of mutable or deleted cases."""

from dataclasses import dataclass

from app.services.anonymous_case_code import validate_anonymous_case_code


@dataclass(frozen=True)
class SavedReportIdentity:
    report_id: int
    anonymous_case_code: str | None
    title: str


def saved_report_identity(report_id: int, snapshot: object) -> SavedReportIdentity:
    raw = snapshot.get("anonymous_case_code") if isinstance(snapshot, dict) else None
    try:
        code = validate_anonymous_case_code(raw)
    except (ValueError, TypeError):
        code = None
    return SavedReportIdentity(
        report_id, code, f"{code}纵向进展预测报告" if code else f"报告-{report_id}"
    )
