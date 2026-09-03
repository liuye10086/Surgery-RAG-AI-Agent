"""Pure, deterministic diffs for operator case profile and timeline snapshots."""

from __future__ import annotations

from datetime import date, datetime
from typing import Any, Iterable, Literal

from app.services.operator_case_validation import NormalizedVisit


CaseChangeAction = Literal["profile_updated", "timeline_updated", "case_updated"]
PROFILE_FIELDS = ("age", "sex", "baseline_stage", "notes")


def _field(value: Any, name: str) -> Any:
    if isinstance(value, dict):
        return value.get(name)
    return getattr(value, name, None)


def _iso_date(value: Any) -> str:
    if isinstance(value, datetime):
        value = value.date()
    if isinstance(value, date):
        return value.isoformat()
    return date.fromisoformat(str(value)).isoformat()


def _notes(value: Any) -> str | None:
    return value.strip() or None if isinstance(value, str) else None


def _indicator(value: Any) -> dict[str, Any]:
    name = str(_field(value, "name") or "").strip().lower()
    unit = str(_field(value, "unit") or "").strip()
    return {"name": name, "value": float(_field(value, "value")), "unit": unit}


def _visit_snapshot(value: Any) -> dict[str, Any]:
    indicators = sorted(
        (_indicator(item) for item in (_field(value, "indicators") or [])),
        key=lambda item: item["name"],
    )
    return {
        "visit_date": _iso_date(_field(value, "visit_date")),
        "indicators": indicators,
        "notes": _notes(_field(value, "notes")),
    }


def _timeline_by_date(values: Iterable[Any]) -> dict[str, dict[str, Any]]:
    snapshots = (_visit_snapshot(value) for value in values)
    return {item["visit_date"]: item for item in snapshots}


def build_case_diff(
    case: Any,
    submitted_profile: Any,
    normalized_visits: Iterable[NormalizedVisit],
) -> dict[str, Any]:
    changes: dict[str, Any] = {}
    profile = {}
    for field in PROFILE_FIELDS:
        before = _field(case, field)
        after = _field(submitted_profile, field)
        if field == "notes":
            before, after = _notes(before), _notes(after)
        if before != after:
            profile[field] = {"before": before, "after": after}
    if profile:
        changes["profile"] = profile

    before_by_date = _timeline_by_date(getattr(case, "visits", ()) or ())
    after_by_date = _timeline_by_date(normalized_visits)
    added = [
        after_by_date[key]
        for key in sorted(after_by_date.keys() - before_by_date.keys())
    ]
    removed = [
        before_by_date[key]
        for key in sorted(before_by_date.keys() - after_by_date.keys())
    ]
    updated = []
    for key in sorted(before_by_date.keys() & after_by_date.keys()):
        before = before_by_date[key]
        after = after_by_date[key]
        fields = {
            field: {"before": before[field], "after": after[field]}
            for field in ("indicators", "notes")
            if before[field] != after[field]
        }
        if fields:
            updated.append({"visit_date": key, "fields": fields})
    if added or removed or updated:
        changes["timeline"] = {
            "added": added,
            "removed": removed,
            "updated": updated,
        }
    return changes


def classify_case_action(changes: dict[str, Any]) -> CaseChangeAction:
    profile_changed = bool(changes.get("profile"))
    timeline_changed = bool(changes.get("timeline"))
    if profile_changed and timeline_changed:
        return "case_updated"
    if profile_changed:
        return "profile_updated"
    if timeline_changed:
        return "timeline_updated"
    raise ValueError("case_changes_required")
