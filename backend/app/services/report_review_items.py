from app.schemas.report_document import QualityIssue


def build_review_items(issues: list[QualityIssue]) -> list[QualityIssue]:
    rank = {"blocking": 0, "warning": 1, "info": 2}
    unique = {}
    for item in issues:
        key = (item.code, item.task, item.visit_index, item.indicator, item.field)
        unique.setdefault(key, item)
    return sorted(
        unique.values(),
        key=lambda x: (
            rank[x.severity],
            x.visit_index or 0,
            x.indicator or "",
            x.task or "",
            x.code,
        ),
    )
