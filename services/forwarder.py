"""一对多 Markdown 转发编排。"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass
from typing import Any

from .models import Binding
from .qq_sender import QQMarkdownSender, SendReceipt


@dataclass(frozen=True, slots=True)
class ForwardAttempt:
    binding: Binding
    success: bool
    receipt: SendReceipt | None = None
    error: str = ""


@dataclass(frozen=True, slots=True)
class ForwardReport:
    attempts: tuple[ForwardAttempt, ...]

    @property
    def success_count(self) -> int:
        return sum(1 for attempt in self.attempts if attempt.success)

    @property
    def failure_count(self) -> int:
        return len(self.attempts) - self.success_count

    def should_intercept(self, policy: str) -> bool:
        if not self.attempts:
            return False
        if policy == "all_success":
            return self.failure_count == 0
        return self.success_count > 0


class MarkdownForwarder:
    def __init__(
        self,
        sender: QQMarkdownSender,
        logger: Any,
        *,
        timeout_seconds: int = 20,
    ) -> None:
        self._sender = sender
        self._logger = logger
        self._timeout_seconds = max(1, timeout_seconds)

    async def forward(self, bindings: list[Binding], text: str) -> ForwardReport:
        """并发发送所有目标，单个目标失败不会影响其他目标。"""

        attempts = await asyncio.gather(
            *(self._forward_one(binding, text) for binding in bindings)
        )
        return ForwardReport(tuple(attempts))

    async def _forward_one(self, binding: Binding, text: str) -> ForwardAttempt:
        try:
            receipt = await asyncio.wait_for(
                self._sender.send_markdown(binding.target, text),
                timeout=self._timeout_seconds,
            )
            return ForwardAttempt(binding=binding, success=True, receipt=receipt)
        except TimeoutError:
            error = f"转发超时（{self._timeout_seconds}s）"
        except Exception as exc:
            error = str(exc) or exc.__class__.__name__

        self._logger.error(
            f"绑定 {binding.binding_id} 转发失败: {error}; "
            f"target={binding.target.unified_msg_origin}"
        )
        return ForwardAttempt(binding=binding, success=False, error=error)
