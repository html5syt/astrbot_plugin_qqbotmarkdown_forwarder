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

    def test_bold_alone_is_detected(self):
        detector = MarkdownDetector(
            DEFAULT_MARKDOWN_PATTERNS,
            mode="regex_only",
            length_threshold=0,
        )

        self.assertTrue(detector.detect("**加粗**").matched)
        self.assertTrue(detector.detect("单独的**加粗**语法").matched)
        self.assertTrue(detector.detect("前缀**重点内容**后缀").matched)

    def test_latex_formulas_are_detected(self):
        detector = MarkdownDetector(
            DEFAULT_MARKDOWN_PATTERNS,
            mode="regex_only",
            length_threshold=0,
        )

        # 独立行内公式
        self.assertTrue(detector.detect("$公式$").matched)
        self.assertTrue(detector.detect("$E=mc^2$").matched)
        # 独立块级公式
        self.assertTrue(detector.detect("$$公式$$").matched)
        self.assertTrue(detector.detect("$$\n\\int_0^1 f(x)dx\n$$").matched)
        # 混合包含
        self.assertTrue(detector.detect("这里有一个公式 $a+b=c$ 很好。").matched)
        self.assertTrue(
            detector.detect("混合消息：**加粗结论**与公式 $$x=1$$ 组合").matched
        )

    def test_short_plain_text_is_not_markdown(self):
        detector = MarkdownDetector(
            DEFAULT_MARKDOWN_PATTERNS,
            mode="regex_or_length",
            length_threshold=100,
        )

        self.assertFalse(detector.detect("普通短消息").matched)
        self.assertFalse(detector.detect("售价 $100 元").matched)

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