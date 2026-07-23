"""轻量级 Markdown 特征检测。"""

from __future__ import annotations

import re
from collections.abc import Iterable
from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class DetectionResult:
    matched: bool
    regex_hits: int
    length_hit: bool
    invalid_patterns: tuple[str, ...]


class MarkdownDetector:
    """按正则、长度或两者组合判断文本是否应作为 Markdown 转发。"""

    def __init__(
        self,
        patterns: Iterable[str],
        mode: str = "regex_or_length",
        minimum_regex_matches: int = 1,
        length_threshold: int = 800,
    ) -> None:
        self.mode = mode
        self.minimum_regex_matches = max(1, minimum_regex_matches)
        self.length_threshold = max(0, length_threshold)
        self._patterns: list[re.Pattern[str]] = []
        invalid_patterns: list[str] = []

        for pattern in patterns:
            try:
                self._patterns.append(re.compile(pattern))
            except re.error:
                invalid_patterns.append(pattern)
        self.invalid_patterns = tuple(invalid_patterns)

    def detect(self, text: str) -> DetectionResult:
        """返回检测结果；正则命中数按“命中的表达式数量”计算。"""

        if not text:
            return DetectionResult(False, 0, False, self.invalid_patterns)

        regex_hits = sum(1 for pattern in self._patterns if pattern.search(text))
        regex_hit = regex_hits >= self.minimum_regex_matches
        length_hit = self.length_threshold > 0 and len(text) >= self.length_threshold

        if self.mode == "regex_only":
            matched = regex_hit
        elif self.mode == "length_only":
            matched = length_hit
        elif self.mode == "regex_and_length":
            matched = regex_hit and length_hit
        else:
            matched = regex_hit or length_hit

        return DetectionResult(
            matched=matched,
            regex_hits=regex_hits,
            length_hit=length_hit,
            invalid_patterns=self.invalid_patterns,
        )
