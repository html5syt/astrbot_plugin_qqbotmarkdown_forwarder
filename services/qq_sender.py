"""QQ 官方机器人 Markdown 与交互按钮发送实现。"""

from __future__ import annotations

import asyncio
import random
from collections import OrderedDict
from dataclasses import dataclass
from types import SimpleNamespace
from typing import Any

from .models import Endpoint

QQ_PLATFORM_NAMES = {"qq_official", "qq_official_webhook"}


class QQMarkdownSendError(Exception):
    """QQ Markdown 发送失败。"""


@dataclass(frozen=True, slots=True)
class SendReceipt:
    method: str
    message_id: str = ""


class QQMarkdownSender:
    """优先复用活跃事件，必要时通过 QQ 官方客户端主动发送。"""

    def __init__(
        self,
        context: Any,
        logger: Any,
        *,
        event_cache_size: int = 256,
        native_plain_fallback: bool = True,
        debug_logging: bool = False,
    ) -> None:
        self._context = context
        self._logger = logger
        self._event_cache_size = max(8, event_cache_size)
        self._native_plain_fallback = native_plain_fallback
        self._debug_logging = debug_logging
        self._events: OrderedDict[str, Any] = OrderedDict()
        self._target_locks: dict[str, asyncio.Lock] = {}

    def remember_event(self, event: Any) -> None:
        """缓存 QQ 端最新事件，使发送走 AstrBot 官方的被动回复路径。"""

        if event.get_platform_name() not in QQ_PLATFORM_NAMES:
            return
        origin = str(event.unified_msg_origin)
        self._events[origin] = event
        self._events.move_to_end(origin)
        while len(self._events) > self._event_cache_size:
            self._events.popitem(last=False)

    async def send_markdown(
        self,
        endpoint: Endpoint,
        text: str,
        *,
        keyboard: dict[str, Any] | None = None,
        chain: Any = None,
    ) -> SendReceipt:
        if endpoint.platform_name not in QQ_PLATFORM_NAMES:
            raise QQMarkdownSendError(
                f"目标平台不是 QQ 官方机器人: {endpoint.platform_name}"
            )
        if not text and chain is None:
            raise QQMarkdownSendError("Markdown 内容为空")

        lock = self._target_locks.setdefault(
            endpoint.unified_msg_origin, asyncio.Lock()
        )
        async with lock:
            event = self._events.get(endpoint.unified_msg_origin)
            if event is not None:
                try:
                    send_target = (
                        chain if chain is not None else self._build_markdown_chain(text)
                    )
                    await event.send(send_target)
                    return SendReceipt(method="runtime_event")
                except Exception as exc:
                    self._logger.warning(
                        "QQ 运行时事件发送失败，将尝试持久化会话发送: "
                        f"{endpoint.unified_msg_origin}, {exc!s}"
                    )

            return await self._send_native(endpoint, text, keyboard=keyboard)

    @staticmethod
    def _build_markdown_chain(text: str) -> Any:
        from astrbot.api.event import MessageChain

        return MessageChain().message(text).use_markdown(True)

    async def _send_native(
        self,
        endpoint: Endpoint,
        text: str,
        *,
        keyboard: dict[str, Any] | None = None,
    ) -> SendReceipt:
        platform = self._context.get_platform_inst(endpoint.platform_id)
        if platform is None:
            raise QQMarkdownSendError(f"未找到 QQ 平台实例: {endpoint.platform_id}")

        client = getattr(platform, "client", None)
        if client is None:
            get_client = getattr(platform, "get_client", None)
            client = get_client() if callable(get_client) else None
        if client is None:
            raise QQMarkdownSendError("QQ 平台实例没有可用客户端")

        try:
            result = await self._send_payload(
                client, endpoint, text, use_markdown=True, keyboard=keyboard
            )
            if result is None:
                raise QQMarkdownSendError("QQ Markdown API 未返回发送结果")
            method = "native_markdown"
        except Exception as markdown_error:
            if keyboard is not None:
                try:
                    self._logger.warning(
                        "QQ Markdown 带键盘发送失败，尝试无键盘发送: "
                        f"{markdown_error!s}"
                    )
                    result = await self._send_payload(
                        client, endpoint, text, use_markdown=True, keyboard=None
                    )
                    if result is not None:
                        message_id = self._extract_message_id(result)
                        return SendReceipt(
                            method="native_markdown_nokeyboard",
                            message_id=message_id,
                        )
                except Exception:
                    pass

            if not self._native_plain_fallback:
                raise QQMarkdownSendError(str(markdown_error)) from markdown_error
            self._logger.warning(
                "QQ 原生 Markdown 发送失败，按配置降级为纯文本: "
                f"{endpoint.unified_msg_origin}, {markdown_error!s}"
            )
            try:
                result = await self._send_payload(
                    client, endpoint, text, use_markdown=False, keyboard=keyboard
                )
                if result is None:
                    raise QQMarkdownSendError("QQ 纯文本 API 未返回发送结果")
                method = "native_plain_fallback"
            except Exception as plain_error:
                raise QQMarkdownSendError(str(plain_error)) from plain_error

        message_id = self._extract_message_id(result)
        remember = getattr(platform, "remember_session_message_id", None)
        if message_id and callable(remember):
            remember(endpoint.session_id, message_id)
        if self._debug_logging:
            self._logger.debug(
                f"QQ 转发成功: method={method}, target={endpoint.unified_msg_origin}"
            )
        return SendReceipt(method=method, message_id=message_id)

    async def _send_payload(
        self,
        client: Any,
        endpoint: Endpoint,
        text: str,
        *,
        use_markdown: bool,
        keyboard: dict[str, Any] | None = None,
    ) -> Any:
        scene = endpoint.scene
        if not scene:
            scene = "c2c" if endpoint.message_type == "FriendMessage" else "group"
        address = endpoint.address_id or endpoint.session_id
        if not address:
            raise QQMarkdownSendError("QQ 目标地址为空")

        if use_markdown:
            from botpy.types.message import MarkdownPayload

            payload: dict[str, Any] = {
                "markdown": MarkdownPayload(content=text),
            }
        else:
            payload = {"content": text}

        if keyboard is not None:
            payload["keyboard"] = keyboard

        if scene in {"group", "c2c"}:
            payload["msg_type"] = 2 if use_markdown else 0
            payload["msg_seq"] = random.randint(1, 10000)
        elif endpoint.last_message_id:
            payload["msg_id"] = endpoint.last_message_id

        try:
            return await self._dispatch(client, scene, address, payload)
        except self._retryable_api_errors():
            if "msg_id" not in payload:
                raise
            retry_payload = dict(payload)
            retry_payload.pop("msg_id", None)
            return await self._dispatch(client, scene, address, retry_payload)

    @staticmethod
    async def _dispatch(
        client: Any, scene: str, address: str, payload: dict[str, Any]
    ) -> Any:
        api = getattr(client, "api", None)
        if api is None:
            raise QQMarkdownSendError("QQ 客户端 API 不可用")

        if scene == "group":
            return await api.post_group_message(group_openid=address, **payload)
        if scene == "channel":
            payload.pop("msg_type", None)
            payload.pop("msg_seq", None)
            return await api.post_message(channel_id=address, **payload)
        if scene == "guild_direct":
            payload.pop("msg_type", None)
            payload.pop("msg_seq", None)
            return await api.post_dms(guild_id=address, **payload)
        if scene == "c2c":
            from astrbot.core.platform.sources.qqofficial import (
                qqofficial_message_event as qq_event_module,
            )

            helper = SimpleNamespace(bot=client)
            return await qq_event_module.QQOfficialMessageEvent.post_c2c_message(
                helper,
                openid=address,
                **payload,
            )
        raise QQMarkdownSendError(f"不支持的 QQ 会话场景: {scene}")

    @staticmethod
    def _retryable_api_errors() -> tuple[type[BaseException], ...]:
        try:
            import botpy.errors as errors

            return (
                errors.ForbiddenError,
                errors.MethodNotAllowedError,
                errors.NotFoundError,
                errors.SequenceNumberError,
                errors.ServerError,
            )
        except (ImportError, AttributeError):
            return (QQMarkdownSendError,)

    @staticmethod
    def _extract_message_id(result: Any) -> str:
        if isinstance(result, dict):
            value = result.get("id")
        else:
            value = getattr(result, "id", None)
        return str(value) if value else ""