"""Private archive maintenance. No renderer or clinical data in command output."""

import argparse
import json
import signal
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)
    inspect = sub.add_parser("inspect")
    inspect.add_argument("--report-id", type=int, required=True)
    restore = sub.add_parser("restore")
    restore.add_argument("--report-id", type=int, required=True)
    restore.add_argument("--backup-file", required=True)
    restore.add_argument("--apply", action="store_true")
    cleanup = sub.add_parser("cleanup")
    modes = cleanup.add_mutually_exclusive_group(required=True)
    modes.add_argument("--once", action="store_true")
    modes.add_argument("--sweep", action="store_true")
    args = parser.parse_args(argv)
    from app.core.config import settings
    from app.db.session import SessionLocal
    from app.services.report_archive_cleanup import run_cleanup_once
    from app.services.report_archive_recovery import (
        inspect_original,
        restore_pdf_original,
    )
    from app.services.report_pdf_errors import PdfError

    stopping = False

    def stop(*_):
        nonlocal stopping
        stopping = True

    signal.signal(signal.SIGINT, stop)
    signal.signal(signal.SIGTERM, stop)
    try:
        with SessionLocal() as db:
            if args.command == "inspect":
                from sqlalchemy import text

                db.execute(text("SET TRANSACTION READ ONLY"))
                print(json.dumps(inspect_original(db, args.report_id)))
            elif args.command == "restore":
                result = restore_pdf_original(
                    db, args.report_id, args.backup_file, settings.REPORT_ARCHIVE_ROOT
                )
                print(json.dumps(result), flush=True)
                if args.apply:
                    print(
                        json.dumps(
                            restore_pdf_original(
                                db,
                                args.report_id,
                                args.backup_file,
                                settings.REPORT_ARCHIVE_ROOT,
                                apply=True,
                            )
                        )
                    )
            else:
                while not stopping:
                    result = run_cleanup_once(db, settings.REPORT_ARCHIVE_ROOT)
                    if args.once:
                        print(
                            json.dumps(
                                {
                                    "processed": result is not None,
                                    "files_removed": result is True,
                                }
                            )
                        )
                        break
                    if result is None:
                        time.sleep(1)
        return 0
    except PdfError as error:
        print(json.dumps({"status": "FAIL", "code": error.code}))
        return 1
    except Exception:
        print(json.dumps({"status": "FAIL", "code": "archive_maintenance_failed"}))
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
