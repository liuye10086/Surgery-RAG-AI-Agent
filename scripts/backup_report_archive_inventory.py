"""Consistent archive inventory and deletion-log replay; no implicit restoration."""

import argparse, hashlib, json, os, sys
from datetime import datetime, timezone
from pathlib import Path
from uuid import uuid4

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))


def digest(value):
    return hashlib.sha256(
        json.dumps(value, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()


def read_facts(connection):
    from sqlalchemy import text

    originals = [
        dict(row)
        for row in connection.execute(
            text(
                """SELECT a.report_id,a.published_attempt_id,p.object_key,a.pdf_sha256,a.size_bytes,a.page_count,a.renderer_sha256
        FROM report_pdf_archives a JOIN report_pdf_attempts p ON p.id=a.published_attempt_id ORDER BY a.report_id"""
            )
        ).mappings()
    ]
    tombstones = [
        {"report_id": row[0], "deleted_at": row[1].isoformat()}
        for row in connection.execute(
            text(
                "SELECT report_id_snapshot,deleted_at FROM report_deletion_tombstones ORDER BY report_id_snapshot"
            )
        )
    ]
    cleanup = [
        dict(row)
        for row in connection.execute(
            text(
                "SELECT id,report_id_snapshot,object_key,state FROM report_file_cleanup_tasks ORDER BY id"
            )
        ).mappings()
    ]
    return {"originals": originals, "deletion_log": tombstones, "cleanup": cleanup}


def build_inventory(engine, root, snapshot_id):
    from sqlalchemy import text
    from app.services.report_archive_storage import ArchiveStorage

    if not snapshot_id or len(snapshot_id) > 160:
        raise ValueError("snapshot_identity_required")
    with engine.connect() as connection:
        connection.execute(
            text("SET TRANSACTION ISOLATION LEVEL REPEATABLE READ READ ONLY")
        )
        if connection.execute(
            text(
                "SELECT count(*) FROM report_pdf_attempts WHERE status IN ('queued','running')"
            )
        ).scalar_one():
            raise ValueError("archive_writes_not_drained")
        facts = read_facts(connection)
        database_snapshot = connection.execute(
            text("SELECT pg_current_snapshot()::text")
        ).scalar_one()
    storage = ArchiveStorage(root, create=False)
    for item in facts["originals"]:
        with storage.open_verified(
            item["object_key"], item["pdf_sha256"], item["size_bytes"]
        ):
            pass
    with engine.connect() as connection:
        connection.execute(text("SET TRANSACTION READ ONLY"))
        if digest(read_facts(connection)) != digest(facts):
            raise ValueError("backup_set_changed")
        if connection.execute(
            text(
                "SELECT count(*) FROM report_pdf_attempts WHERE status IN ('queued','running')"
            )
        ).scalar_one():
            raise ValueError("archive_writes_not_drained")
    return {
        "schema_version": "report_archive_inventory.v1",
        "backup_id": str(uuid4()),
        "snapshot_id": snapshot_id,
        "database_snapshot": database_snapshot,
        "created_at": datetime.now(timezone.utc).isoformat(),
        "facts_sha256": digest(facts),
        **facts,
    }


def validated_deletions(value):
    if value.get("schema_version") != "report_archive_inventory.v1":
        raise ValueError("inventory_version_invalid")
    facts = {name: value[name] for name in ("originals", "deletion_log", "cleanup")}
    if value.get("facts_sha256") != digest(facts):
        raise ValueError("inventory_digest_invalid")
    items = value["deletion_log"]
    if not isinstance(items, list):
        raise ValueError("deletion_log_invalid")
    ids = []
    for item in items:
        if (
            set(item) != {"report_id", "deleted_at"}
            or type(item["report_id"]) is not int
            or item["report_id"] < 1
        ):
            raise ValueError("deletion_log_invalid")
        when = datetime.fromisoformat(item["deleted_at"])
        if when.tzinfo is None:
            raise ValueError("deletion_log_invalid")
        ids.append(item["report_id"])
    if len(ids) != len(set(ids)):
        raise ValueError("deletion_log_invalid")
    return items


def export_deletion_log(engine):
    from sqlalchemy import text
    with engine.connect() as connection:
        connection.execute(text('SET TRANSACTION ISOLATION LEVEL REPEATABLE READ READ ONLY'))
        facts={'originals':[],'cleanup':[],'deletion_log':[
            {'report_id':row[0],'deleted_at':row[1].isoformat()}
            for row in connection.execute(text('SELECT report_id_snapshot,deleted_at FROM report_deletion_tombstones ORDER BY report_id_snapshot'))]}
    return {'schema_version':'report_archive_inventory.v1','backup_id':str(uuid4()),
            'created_at':datetime.now(timezone.utc).isoformat(),'facts_sha256':digest(facts),**facts}


def replay_deletions(engine, inventory, *, apply=False):
    from sqlalchemy import text

    items = validated_deletions(inventory)
    matched = 0
    with engine.begin() as connection:
        if not apply:
            connection.execute(text("SET TRANSACTION READ ONLY"))
        for item in items:
            matched += connection.execute(
                text("SELECT count(*) FROM ai_reports WHERE id=:id"),
                {"id": item["report_id"]},
            ).scalar_one()
            if apply:
                connection.execute(
                    text("DELETE FROM ai_reports WHERE id=:id"),
                    {"id": item["report_id"]},
                )
                connection.execute(
                    text(
                        """INSERT INTO report_deletion_tombstones(report_id_snapshot,deleted_at) VALUES(:id,:when)
                    ON CONFLICT(report_id_snapshot) DO UPDATE SET deleted_at=LEAST(report_deletion_tombstones.deleted_at,excluded.deleted_at)"""
                    ),
                    {
                        "id": item["report_id"],
                        "when": datetime.fromisoformat(item["deleted_at"]),
                    },
                )
    return {"applied": apply, "deletion_facts": len(items), "matched_reports": matched}


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)
    create = sub.add_parser("inventory")
    create.add_argument("--output", type=Path, required=True)
    create.add_argument("--snapshot-id", required=True)
    create.add_argument("--maintenance-window", action="store_true", required=True)
    deletion_export=sub.add_parser('export-deletions')
    deletion_export.add_argument('--output',type=Path,required=True)
    replay = sub.add_parser("replay-deletions")
    replay.add_argument("--inventory", type=Path, required=True)
    replay.add_argument("--target-env", required=True)
    replay.add_argument("--apply", action="store_true")
    args = parser.parse_args(argv)
    from sqlalchemy import create_engine
    from app.core.config import settings

    engine = None
    try:
        if args.command in ("inventory","export-deletions"):
            engine = create_engine(settings.DATABASE_URL)
            result = export_deletion_log(engine) if args.command=='export-deletions' else build_inventory(
                engine, settings.REPORT_ARCHIVE_ROOT, args.snapshot_id
            )
            # Exclusive creation prevents replacing a previous backup set.
            fd = os.open(args.output, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
            with os.fdopen(fd, "w", encoding="utf-8") as stream:
                json.dump(result, stream, indent=2)
            print(
                json.dumps(
                    {
                        "status": "PASS",
                        "backup_id": result["backup_id"],
                        "originals": len(result["originals"]),
                        "deletion_facts": len(result["deletion_log"]),
                    }
                )
            )
        else:
            target = os.environ.get(args.target_env)
            if not target:
                raise ValueError("explicit_restore_target_required")
            engine = create_engine(target)
            if args.inventory.stat().st_size > 128 * 1024 * 1024:
                raise ValueError("inventory_too_large")
            value = json.loads(args.inventory.read_text(encoding="utf-8"))
            print(json.dumps(replay_deletions(engine, value, apply=args.apply)))
        return 0
    except Exception:
        print(json.dumps({"status": "FAIL", "code": "archive_backup_check_failed"}))
        return 1
    finally:
        if engine is not None:
            engine.dispose()


if __name__ == "__main__":
    raise SystemExit(main())
