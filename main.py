"""AstrBot 插件入口：绑定命令与发送前 Markdown 转发钩子。"""

from __future__ import annotations

import re
from typing import Any

import astrbot.api.message_components as Comp
from astrbot.api import AstrBotConfig, logger
from astrbot.api.event import AstrMessageEvent, filter
from astrbot.api.star import Context, Star

from .services.binding_store import (
    BindingRequestExpired,
    BindingRequestNotFound,
    BindingStore,
)
from .services.detector import MarkdownDetector
from .services.forwarder import MarkdownForwarder
from .services.models import Endpoint
from .services.qq_sender import QQMarkdownSender
from .services.settings import PluginSettings

ONEBOT_PLATFORM = "aiocqhttp"
QQ_PLATFORM_TYPES = (
    filter.PlatformAdapterType.QQOFFICIAL
    | filter.PlatformAdapterType.QQOFFICIAL_WEBHOOK
)
SKIP_FORWARD_EXTRA = "ob2qb_skip_forward"
STORAGE_KEY = "binding_state"

IDENTIFIER_LABELS = {
    "group_number": "群号",
    "qq_number": "私聊 QQ 号",
    "group_openid": "群 OpenID",
    "user_openid": "用户 OpenID",
    "channel_id": "频道 ID",
    "guild_id": "频道私信 Guild ID",
    "session_id": "会话 ID",
}


class Main(Star):
    """将绑定 OneBot 会话中的 Markdown 输出转发到 QQ 官方机器人。"""

    def __init__(self, context: Context, config: AstrBotConfig) -> None:
        super().__init__(context)
        self.config = config
        self.settings = PluginSettings.from_mapping(config)
        self.detector = MarkdownDetector(
            self.settings.markdown_patterns,
            mode=self.settings.detection_mode,
            minimum_regex_matches=self.settings.minimum_regex_matches,
            length_threshold=self.settings.length_threshold,
        )
        self.binding_store = BindingStore(self._load_state, self._save_state)
        self.qq_sender = QQMarkdownSender(
            context,
            logger,
            event_cache_size=self.settings.runtime_event_cache_size,
            native_plain_fallback=self.settings.native_plain_fallback,
            debug_logging=self.settings.debug_logging,
        )
        self.forwarder = MarkdownForwarder(
            self.qq_sender,
            logger,
            timeout_seconds=self.settings.forward_timeout_seconds,
        )

        if self.detector.invalid_patterns:
            logger.warning(
                "OneBot Markdown 转发器忽略了无效正则: "
                + ", ".join(self.detector.invalid_patterns)
            )

    async def _load_state(self) -> dict[str, Any]:
        state = await self.get_kv_data(STORAGE_KEY, {})
        return state if isinstance(state, dict) else {}

    async def _save_state(self, state: dict[str, Any]) -> None:
        await self.put_kv_data(STORAGE_KEY, state)

    @filter.command_group("ob2qb")
    @filter.permission_type(filter.PermissionType.ADMIN)
    def ob2qb():
        """管理 OneBot 到 QQ 官方机器人的 Markdown 转发绑定。"""

        pass

    @ob2qb.command("req_bind")
    @filter.permission_type(filter.PermissionType.ADMIN)
    async def req_bind(self, event: AstrMessageEvent):
        """从当前 OneBot 群聊或私聊发出绑定请求。"""

        self._mark_command_result(event)
        if event.get_platform_name() != ONEBOT_PLATFORM:
            yield event.plain_result("req_bind 只能在 OneBot 平台中执行。")
            return

        source = Endpoint.from_event(event)
        if not source.chat_id:
            yield event.plain_result(
                "无法读取当前 OneBot 群号或私聊 QQ 号，未创建绑定请求。"
            )
            return
        request = await self.binding_store.request_binding(
            source, self.settings.pending_request_ttl_seconds
        )
        yield event.plain_result(
            "绑定请求已创建。\n"
            f"请求码：{request.code}\n"
            f"OneBot {self._format_identifier(source)}\n"
            "请在目标 QQ 官方机器人会话中由管理员执行：\n"
            f"/ob2qb ack_bind {request.code}\n"
            f"请求将在 {self.settings.pending_request_ttl_seconds} 秒后过期。"
        )

    @ob2qb.command("ack_bind")
    @filter.permission_type(filter.PermissionType.ADMIN)
    async def ack_bind(self, event: AstrMessageEvent, code: str):
        """在当前 QQ 官方机器人群聊或私聊确认四位请求码。"""

        self._mark_command_result(event)
        if event.get_platform_name() not in {
            "qq_official",
            "qq_official_webhook",
        }:
            yield event.plain_result("ack_bind 只能在 QQ 官方机器人平台中执行。")
            return
        if not re.fullmatch(r"\d{4}", code):
            yield event.plain_result("请求码必须是四位数字。")
            return

        target = Endpoint.from_event(event)
        if target.scene not in {"group", "c2c", "channel", "guild_direct"} or not (
            target.address_id and target.chat_id
        ):
            yield event.plain_result(
                "无法读取当前 QQ 官方会话的 OpenID/频道 ID，未建立绑定。"
            )
            return

        self.qq_sender.remember_event(event)
        try:
            binding, created = await self.binding_store.acknowledge(code, target)
        except BindingRequestExpired:
            yield event.plain_result("该绑定请求已过期，请在 OneBot 端重新申请。")
            return
        except BindingRequestNotFound:
            yield event.plain_result("未找到该绑定请求，请检查四位请求码。")
            return

        status = "绑定成功" if created else "该转发关系已存在"
        yield event.plain_result(
            f"{status}。\n"
            f"绑定 ID：{binding.binding_id}\n"
            f"OneBot {self._format_identifier(binding.source)}\n"
            f"QQBot {self._format_identifier(binding.target)}"
        )

    @ob2qb.command("list_bind")
    @filter.permission_type(filter.PermissionType.ADMIN)
    async def list_bind(self, event: AstrMessageEvent):
        """列出全部绑定及群号、私聊 QQ 号或 QQ 官方 OpenID。"""

        self._mark_command_result(event)
        bindings = await self.binding_store.list_bindings()
        if not bindings:
            yield event.plain_result("当前没有 OneBot → QQBot 转发绑定。")
            return

        lines = [f"当前共有 {len(bindings)} 条绑定："]
        for index, binding in enumerate(bindings, start=1):
            lines.extend(
                (
                    f"{index}. 绑定 ID：{binding.binding_id}",
                    "   OneBot："
                    f"{self._format_identifier(binding.source)} "
                    f"[适配器 {binding.source.platform_id}]",
                    "   QQBot："
                    f"{self._format_identifier(binding.target)} "
                    f"[适配器 {binding.target.platform_id}]",
                )
            )
        yield event.plain_result("\n".join(lines))

    @ob2qb.command("unbind")
    @filter.permission_type(filter.PermissionType.ADMIN)
    async def unbind(self, event: AstrMessageEvent, binding_id: str):
        """按六位绑定 ID 解除一条转发关系。"""

        self._mark_command_result(event)
        if not re.fullmatch(r"\d{6}", binding_id):
            yield event.plain_result("绑定 ID 必须是六位数字。")
            return
        binding = await self.binding_store.remove_binding(binding_id)
        if binding is None:
            yield event.plain_result("未找到该绑定 ID。")
            return
        yield event.plain_result(
            "已解除绑定。\n"
            f"绑定 ID：{binding.binding_id}\n"
            f"OneBot {self._format_identifier(binding.source)} → "
            f"QQBot {self._format_identifier(binding.target)}"
        )

    @filter.platform_adapter_type(QQ_PLATFORM_TYPES)
    @filter.event_message_type(filter.EventMessageType.ALL, priority=100)
    async def remember_qq_event(self, event: AstrMessageEvent) -> None:
        """刷新已运行 QQ 会话的原生发送上下文。"""

        self.qq_sender.remember_event(event)

    @filter.on_decorating_result(priority=1000)
    async def forward_markdown_before_send(self, event: AstrMessageEvent) -> None:
        """发送前检测 Markdown，转发成功后清空并终止 OneBot 原发送。"""

        if (
            not self.settings.enabled
            or event.get_platform_name() != ONEBOT_PLATFORM
            or event.get_extra(SKIP_FORWARD_EXTRA, False)
        ):
            return

        result = event.get_result()
        if result is None or not result.chain:
            return
        bindings = await self.binding_store.bindings_for_source(
            event.unified_msg_origin
        )
        if not bindings:
            return

        if self.settings.only_plain_text and any(
            not isinstance(component, Comp.Plain) for component in result.chain
        ):
            return
        text = "".join(
            component.text
            for component in result.chain
            if isinstance(component, Comp.Plain)
        )
        detection = self.detector.detect(text)
        if not detection.matched:
            return

        if self.settings.debug_logging:
            logger.debug(
                "检测到 Markdown: "
                f"regex_hits={detection.regex_hits}, "
                f"length_hit={detection.length_hit}, targets={len(bindings)}"
            )
        report = await self.forwarder.forward(bindings, text)

        message_ids = {
            attempt.binding.binding_id: attempt.receipt.message_id
            for attempt in report.attempts
            if attempt.success
            and attempt.receipt is not None
            and attempt.receipt.message_id
        }
        if message_ids:
            try:
                await self.binding_store.update_target_message_ids(message_ids)
            except Exception as exc:
                # 消息已经发出，状态刷新失败不应改变本次拦截判定。
                logger.warning(f"QQ 转发成功，但更新目标消息 ID 失败: {exc!s}")

        if report.should_intercept(self.settings.intercept_policy):
            result.chain.clear()
            event.stop_event()
            logger.info(
                "已转发并拦截 OneBot Markdown 消息: "
                f"success={report.success_count}, failed={report.failure_count}"
            )
        else:
            logger.warning(
                "Markdown 未达到拦截策略，保留 OneBot 原发送: "
                f"success={report.success_count}, failed={report.failure_count}"
            )

    @staticmethod
    def _mark_command_result(event: AstrMessageEvent) -> None:
        # 防止 list_bind 等本插件命令输出被自身再次识别为 Markdown。
        event.set_extra(SKIP_FORWARD_EXTRA, True)

    @staticmethod
    def _format_identifier(endpoint: Endpoint) -> str:
        label = IDENTIFIER_LABELS.get(endpoint.id_kind, "会话 ID")
        value = endpoint.chat_id or endpoint.address_id or endpoint.session_id
        chat_label = "群聊" if endpoint.chat_type == "group" else "私聊"
        return f"{chat_label}（{label}：{value}）"

    async def terminate(self) -> None:
        """插件无后台任务，保留生命周期入口供 AstrBot 正常卸载。"""
