import unittest

from app.services.source_access import source_grants_document, source_grants_image


class ImageGrantTests(unittest.TestCase):
    def test_matching_cited_image_grants_access(self):
        source = {
            "document_id": 12,
            "images": [{"url": "/api/v1/files/images/12/p1_0.jpg"}],
        }
        self.assertTrue(source_grants_image(source, 12, None, "p1_0.jpg"))

    def test_other_document_does_not_grant_access(self):
        source = {
            "document_id": 13,
            "images": [{"url": "/api/v1/files/images/13/p1_0.jpg"}],
        }
        self.assertFalse(source_grants_image(source, 12, None, "p1_0.jpg"))

    def test_generation_image_requires_exact_generation(self):
        source = {
            "document_id": 12,
            "images": [{"url": "/api/v1/files/images/12/2/p1_0.jpg"}],
        }
        self.assertTrue(source_grants_image(source, 12, 2, "p1_0.jpg"))
        self.assertFalse(source_grants_image(source, 12, 1, "p1_0.jpg"))


class DocumentGrantTests(unittest.TestCase):
    def test_matching_source_grants_document_access(self):
        self.assertTrue(source_grants_document({"document_id": 12}, 12))

    def test_other_document_does_not_grant_document_access(self):
        self.assertFalse(source_grants_document({"document_id": 13}, 12))


if __name__ == "__main__":
    unittest.main()
