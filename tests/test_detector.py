import unittest

from services.detector import MarkdownDetector
from services.settings import DEFAULT_MARKDOWN_PATTERNS


class MarkdownDetectorTests(unittest.TestCase):
    def test_heading_is_detected_by_regex(self):
        detector = MarkdownDetector(
            DEFAULT_MARKDOWN_PATTERNS,
            mode="regex_only",
            length_threshold=0,
        )

        result = detector.detect("# 标题\n正文")

        self.assertTrue(result.matched)
        self.assertGreaterEqual(result.regex_hits, 1)

    def test_short_plain_text_is_not_markdown(self):
        detector = MarkdownDetector(
            DEFAULT_MARKDOWN_PATTERNS,
            mode="regex_or_length",
            length_threshold=100,
        )

        self.assertFalse(detector.detect("普通短消息").matched)

    def test_length_only_mode(self):
        detector = MarkdownDetector([], mode="length_only", length_threshold=5)

        self.assertTrue(detector.detect("12345").matched)
        self.assertFalse(detector.detect("1234").matched)

    def test_and_mode_requires_both_conditions(self):
        detector = MarkdownDetector(
            [r"^#\s"],
            mode="regex_and_length",
            length_threshold=10,
        )

        self.assertFalse(detector.detect("# 短").matched)
        self.assertTrue(detector.detect("# 足够长的标题文本").matched)

    def test_invalid_regex_is_ignored(self):
        detector = MarkdownDetector(["[", r"^#\s"], mode="regex_only")

        result = detector.detect("# 标题")

        self.assertEqual(result.invalid_patterns, ("[",))
        self.assertTrue(result.matched)


if __name__ == "__main__":
    unittest.main()
