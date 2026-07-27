import unittest

from app.services.safe_stream import SAFE_OUTPUT_REPLACEMENT, SafeSentenceBuffer


class SafeSentenceBufferTests(unittest.TestCase):
    def test_safe_sentence_is_emitted_after_boundary(self):
        buffer = SafeSentenceBuffer()
        self.assertEqual(buffer.push("建议先复查"), [])
        segments = buffer.push("。下一句")
        self.assertEqual([segment.text for segment in segments], ["建议先复查。"])

    def test_diagnosis_sentence_is_replaced_before_emission(self):
        segments = SafeSentenceBuffer().push("你肯定是胆囊炎。")
        self.assertEqual(segments[0].text, SAFE_OUTPUT_REPLACEMENT)
        self.assertTrue(segments[0].replaced)
        self.assertEqual(segments[0].reason, "deterministic_diagnosis")

    def test_dosage_sentence_is_replaced(self):
        segments = SafeSentenceBuffer().push("每日口服20mg。")
        self.assertTrue(segments[0].replaced)
        self.assertEqual(segments[0].reason, "dosage_info")

    def test_partial_tail_is_checked_on_finish(self):
        buffer = SafeSentenceBuffer()
        buffer.push("你确诊了肿瘤")
        self.assertTrue(buffer.finish()[0].replaced)

    def test_consecutive_unsafe_sentences_share_one_replacement(self):
        segments = SafeSentenceBuffer().push("你肯定是胆囊炎。每日口服20mg。")
        self.assertEqual(
            [segment.text for segment in segments if segment.text],
            [SAFE_OUTPUT_REPLACEMENT],
        )
        self.assertEqual(
            {segment.reason for segment in segments},
            {"deterministic_diagnosis", "dosage_info"},
        )


if __name__ == "__main__":
    unittest.main()
