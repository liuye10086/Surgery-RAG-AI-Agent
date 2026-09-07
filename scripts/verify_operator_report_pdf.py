"""Export saved test reports and explicitly synthetic layout stress variants."""

import sys
import os
import json
import time
import hashlib
from uuid import uuid4
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))
sys.path.insert(0, str(ROOT))


def pdf_layout_findings(pdf_bytes):
    import fitz
    findings=[]
    with fitz.open(stream=pdf_bytes,filetype='pdf') as document:
        for index,page in enumerate(document):
            for block in page.get_text('blocks'):
                if block[6]==0 and block[4].strip() and (block[0]<-1 or block[1]<-1 or block[2]>page.rect.width+1 or block[3]>page.rect.height+1):
                    findings.append({'page':index+1,'code':'text_outside_page'})
    return findings


def pdf_font_names(document):
    names=set()
    for page in document:
        for font in page.get_fonts():
            if font[3]:names.add(font[3])
            else:
                kind,value=document.xref_get_key(font[0],'FontDescriptor')
                if kind=='xref':
                    descriptor=int(value.split()[0])
                    _,name=document.xref_get_key(descriptor,'FontName')
                    if name!='null':names.add(name.lstrip('/'))
                # Chromium may embed CFF glyph outlines as Type3 CharProcs.
                if font[2]=='Type3':assert document.xref_get_key(font[0],'CharProcs')[0]!='null'
    return names


def main():
    from scripts.seed_operator_report_e2e import require_test_database
    require_test_database(os.environ.get('TEST_DATABASE_URL',''))
    os.environ['DATABASE_URL']=os.environ['TEST_DATABASE_URL']
    import argparse
    import copy
    from app.db.session import SessionLocal
    from app.db.models import AIReport
    from app.schemas.report_document import ReportDocument
    from app.services.report_document_renderer import render_report_document
    from app.services.pdf_generator import generate_pdf
    from scripts.seed_operator_report_e2e import require_test_database
    import fitz
    from PIL import Image, ImageDraw

    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=ROOT / "outputs/operator-report-verification/pdf",
    )
    output = parser.parse_args().output_dir.resolve()
    output.mkdir(parents=True, exist_ok=True)
    from app.core.config import settings
    from app.services.report_pdf_archive_service import prepare_pdf_archive,read_pdf_archive_status
    from app.services.report_pdf_delivery import prepare_delivery,delivery_chunks
    from app.workers.report_pdf_worker import run_pdf_worker_once
    original_bytes={}
    results=[]
    with SessionLocal() as db:
        require_test_database(str(db.get_bind().url))
        reports = (
            db.query(AIReport)
            .filter(
                AIReport.status == "completed", AIReport.report_document.isnot(None)
            )
            .order_by(AIReport.id)
            .all()
        )
        saved = {}
        for report in reports:
            saved.setdefault(report.report_document["identity"]["disease_code"], report)
        if set(saved) != {"fatty_liver", "ad"}:
            raise RuntimeError("both_completed_test_reports_required")
        for report in reports:
            label=report.report_document['identity']['disease_code']
            if len(report.input_snapshot.get('visits',[]))==10:label+='-catalog-10'
            if label in original_bytes:continue
            report_id=report.id;user_id=report.user_id
            accepted=prepare_pdf_archive(db,user_id,report_id,str(uuid4()))
            if accepted.state=='failed' and accepted.can_retry:
                prepare_pdf_archive(db,user_id,report_id,str(uuid4()),retry=True)
            deadline=time.monotonic()+150
            while time.monotonic()<deadline:
                db.rollback()
                state=read_pdf_archive_status(db,user_id,report_id)
                db.rollback()
                if state.state=='ready':break
                if state.state not in ('queued','rendering'):raise RuntimeError('original_preparation_failed')
                run_pdf_worker_once(SessionLocal,'pdf-verification')
                time.sleep(.2)
            else:raise RuntimeError('original_preparation_timeout')
            original_bytes[label]=b''.join(delivery_chunks(prepare_delivery(db,user_id,report_id)))
        variants = [
            (name, r.report_document, r.prediction_result, r.evidence_snapshot)
            for name, r in saved.items()
        ]
        for name,pdf in original_bytes.items():
            if name not in saved:
                r=saved[name.split('-catalog')[0]]
                variants.append((name,r.report_document,r.prediction_result,r.evidence_snapshot))
        for name in ("long-context", "table-pressure", "legacy"):
            r = saved["fatty_liver"]
            doc = copy.deepcopy(r.report_document)
            if name == "long-context":
                doc["sections"][1]["paragraphs"] += [
                    "排版压力样例：" + ("评估条件较长，需保留完整文字并换行。" * 120)
                ]
            if name == "table-pressure":
                doc["sections"][1]["tables"].append(
                    {
                        "title": "排版压力样例：十次访视，每次三十项指标",
                        "headers": ["访视日期", "指标", "值", "单位", "上下文"],
                        "rows": [
                            [
                                f"2025-{visit:02d}-01",
                                f"虚构指标 {indicator}",
                                "0",
                                "测试单位",
                                "软件验收，无临床用途",
                            ]
                            for visit in range(1, 11)
                            for indicator in range(1, 31)
                        ],
                    }
                )
            variants.append(
                (
                    name,
                    None if name == "legacy" else doc,
                    r.prediction_result,
                    r.evidence_snapshot,
                )
            )
        from backend.tests.report_document_fixtures import demo_inputs
        from app.services.report_document_builder import build_report_document
        from datetime import datetime, timezone

        snapshot, context, audited, evidence = demo_inputs(bad_trend=True)
        partial = build_report_document(
            17,
            datetime(2026, 9, 7, tzinfo=timezone.utc),
            snapshot,
            context,
            audited.prediction,
            audited.model_runs,
            evidence,
        )
        variants.append(
            (
                "partial-model",
                partial.model_dump(mode="json"),
                audited.prediction,
                evidence.bundle.model_dump(mode="json"),
            )
        )
        for name, doc, prediction, evidence in variants:
            content = (
                render_report_document(ReportDocument.model_validate(doc))
                if doc
                else saved["fatty_liver"].content
            )
            pdf = original_bytes[name] if name in original_bytes else generate_pdf(
                content,
                title="自动化验收样例 · " + name,
                prediction_result=prediction,
                evidence_snapshot=evidence,
                report_document=doc,
                renderer_manifest=settings.REPORT_PDF_RENDERER_MANIFEST,
            )
            (output / f"{name}.pdf").write_bytes(pdf)
            assert not pdf_layout_findings(pdf),(name,'layout_overflow')
            pages = fitz.open(stream=pdf, filetype="pdf")
            fonts=pdf_font_names(pages)
            assert any('NotoSansCJK' in font for font in fonts),(name,'controlled_font_missing')
            results.append({'name':name,'kind':'archived_original' if name in original_bytes else 'synthetic_layout_only','pages':len(pages),'sha256':hashlib.sha256(pdf).hexdigest(),'size_bytes':len(pdf),'fonts':sorted(fonts),'layout_findings':[]})
            thumbs = []
            for index, page in enumerate(pages):
                pix = page.get_pixmap(matrix=fitz.Matrix(1, 1))
                path = output / f"{name}-{index + 1:02}.png"
                pix.save(path)
                im = Image.open(path).convert("RGB")
                im.thumbnail((298, 422))
                thumb = Image.new("RGB", (310, 450), "#dddddd")
                thumb.paste(im, (6, 20))
                ImageDraw.Draw(thumb).text(
                    (8, 3), f"{name} / {index + 1}", fill="black"
                )
                thumbs.append(thumb)
                # Check actual rendered text boxes, not only extracted words.
                for block in page.get_text("blocks"):
                    if block[6] == 0 and block[4].strip():
                        assert block[0] >= -1 and block[2] <= page.rect.width + 1, (
                            name,
                            index,
                            "horizontal_overflow",
                        )
                        assert block[1] >= -1 and block[3] <= page.rect.height + 1, (
                            name,
                            index,
                            "vertical_overflow",
                        )
            for start in range(0, len(thumbs), 12):
                group = thumbs[start : start + 12]
                sheet = Image.new(
                    "RGB", (310 * 4, 450 * ((len(group) + 3) // 4)), "white"
                )
                for i, thumb in enumerate(group):
                    sheet.paste(thumb, ((i % 4) * 310, (i // 4) * 450))
                sheet.save(output / f"{name}-contact-{start // 12 + 1}.png")
            print(name, len(pages), "pages", len(pdf), "bytes", flush=True)
            pages.close()
        (output / "verification.json").write_text(json.dumps(results,ensure_ascii=False,indent=2),encoding="utf-8")


if __name__ == "__main__":
    main()
