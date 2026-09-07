"""Pin rule values and exact source bindings, independently of active pointers."""

import hashlib
import json
from sqlalchemy import select
from app.db.models import StandardRule, StandardSegment, StandardIndicator


def standard_rules_hash(db, version_id):
    def projection(model):
        return [
            column
            for column in model.__table__.columns
            if column.name not in ("created_at", "updated_at")
        ]

    rows = db.execute(
        select(
            *projection(StandardRule),
            *projection(StandardSegment),
            *projection(StandardIndicator),
        )
        .select_from(StandardRule)
        .outerjoin(
            StandardSegment, StandardRule.source_segment_id == StandardSegment.id
        )
        .outerjoin(StandardIndicator, StandardRule.indicator_id == StandardIndicator.id)
        .where(StandardRule.version_id == version_id)
        .order_by(StandardRule.id)
    ).all()
    if not rows:
        raise ValueError("standard_integrity_failed")
    return hashlib.sha256(
        json.dumps(
            [list(row) for row in rows],
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
            allow_nan=False,
        ).encode()
    ).hexdigest()
