from io import BytesIO
from app.services.report_pdf_delivery import PdfDelivery, delivery_chunks


def test_delivery_closes_the_verified_handle_even_when_interrupted():
    stream = BytesIO(b"original")
    delivery = PdfDelivery(stream, "report-1.pdf", 8, "a" * 64)
    chunks = delivery_chunks(delivery)
    assert next(chunks) == b"original"
    chunks.close()
    assert stream.closed
