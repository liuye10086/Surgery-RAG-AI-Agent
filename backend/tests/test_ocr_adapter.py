from types import SimpleNamespace

import pytest

from app.ingestion import parser


@pytest.mark.parametrize("use_gpu,device", [(False, "cpu"), (True, "gpu")])
def test_paddleocr_3_constructor_and_prediction_contract(monkeypatch, use_gpu, device):
    # Keep PaddleOCR's real argument validation and predict adapter; isolate only
    # model construction/inference so the regression never downloads models.
    monkeypatch.setenv("PADDLE_PDX_DISABLE_MODEL_SOURCE_CHECK", "True")
    from paddleocr import PaddleOCR

    calls = []

    def predict(image, **kwargs):
        calls.append(image)
        return iter([{"rec_texts": ["合成病例", "", "ALT 42"]}, {"rec_texts": []}])

    monkeypatch.setattr(PaddleOCR, "_create_paddlex_pipeline", lambda self: SimpleNamespace(predict=predict))
    monkeypatch.setattr(parser, "_ocr", None)
    monkeypatch.setattr(parser.settings, "PADDLEOCR_USE_GPU", use_gpu)

    pages = parser.parse_image("synthetic.png")

    assert pages[0].text == "合成病例\nALT 42"
    assert pages[0].source_type == "image_ocr"
    assert calls == ["synthetic.png"]
    assert parser._get_ocr()._common_args["device"] == device
    assert parser._get_ocr()._common_args["enable_mkldnn"] is (parser.os.name != "nt")


def test_scanned_pdf_uses_ocr_text(monkeypatch, tmp_path):
    import fitz

    path = tmp_path / "scan.pdf"
    with fitz.open() as doc:
        doc.new_page()
        doc.save(path)
    ocr = SimpleNamespace(predict=lambda **kwargs: [{"rec_texts": ["合成扫描内容"]}])
    monkeypatch.setattr(parser, "_get_ocr", lambda: ocr)

    pages = parser.parse_pdf(str(path))

    assert pages[0].text == "合成扫描内容"
    assert pages[0].source_type == "pdf_ocr"
