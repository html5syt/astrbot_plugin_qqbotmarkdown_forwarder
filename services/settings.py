"""WebUI ?????????"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any

DEFAULT_MARKDOWN_PATTERNS = (
    r"(?m)^#{1,6}\s+\S",
    r"(?m)^\s{0,3}(?:[-*+]|\d+\.)\s+\S",
    r"(?m)^\s{0,3}>\s+\S",
    r"(?s)```.+?```",
    r"(?<!\*)\*\*(?=\S).+?(?<=\S)\*\*(?!\*)|(?<![\w_])__(?=\S)(?!_)[^\n]+?(?<!_)(?<=\S)__(?![\w_])",
    r"`[^`\n]+`",
    r"!?\[[^\]\n]*\]\([^\)\n]+\)",
    r"(?m)^\|?.+\|.+\r?\n\|?\s*:?-{3,}:?\s*\|",
    r"~~(?=\S).+?(?<=\S)~~",
    r"(?s)(?<!\\)\$\$.+?(?<!\\)\$\$",
    r"(?<![\$\\])\$(?!\$)(?!\s)[^\$\n]+?(?<!\s)(?<!\\)\$(?!\$)",
)


def _as_int(value: Any, default: int, minimum: int, maximum: int) -> int:
    try:
        parsed = int(value)
    except (TypeError, ValueError):
        parsed = default
    return max(minimum, min(parsed, maximum))


@dataclass(frozen=True, slots=True)
class PluginSettings:
    enabled: bool
    detection_mode: str
    markdown_patterns: tuple[str, ...]
    minimum_regex_matches: int
    length_threshold: int
    only_plain_text: bool
    pending_request_ttl_seconds: int
    forward_timeout_seconds: int
    intercept_policy: str
    runtime_event_cache_size: int
    native_plain_fallback: bool
    debug_logging: bool

    @classmethod
    def from_mapping(cls, config: Mapping[str, Any] | None) -> PluginSettings:
        config = config or {}
        mode = str(config.get("detection_mode", "regex_or_length"))
        if mode not in {
            "regex_only",
            "length_only",
            "regex_or_length",
            "regex_and_length",
        }:
            mode = "regex_or_length"

        raw_patterns = config.get("markdown_patterns", DEFAULT_MARKDOWN_PATTERNS)
        if not isinstance(raw_patterns, list | tuple):
            raw_patterns = DEFAULT_MARKDOWN_PATTERNS
        patterns = tuple(
            pattern for pattern in raw_patterns if isinstance(pattern, str) and pattern
        )

        intercept_policy = str(config.get("intercept_policy", "any_success"))
        if intercept_policy not in {"any_success", "all_success"}:
            intercept_policy = "any_success"

        return cls(
            enabled=bool(config.get("enabled", True)),
            detection_mode=mode,
            markdown_patterns=patterns,
            minimum_regex_matches=_as_int(
                config.get("minimum_regex_matches"), 1, 1, 100
            ),
            length_threshold=_as_int(config.get("length_threshold"), 800, 0, 100000),
            only_plain_text=bool(config.get("only_plain_text", True)),
            pending_request_ttl_seconds=_as_int(
                config.get("pending_request_ttl_seconds"), 600, 30, 86400
            ),
            forward_timeout_seconds=_as_int(
                config.get("forward_timeout_seconds"), 20, 1, 120
            ),
            intercept_policy=intercept_policy,
            runtime_event_cache_size=_as_int(
                config.get("runtime_event_cache_size"), 256, 8, 4096
            ),
            native_plain_fallback=bool(config.get("native_plain_fallback", True)),
            debug_logging=bool(config.get("debug_logging", False)),
        )
