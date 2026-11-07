"""AstrBot 插件入口：绑定命令、发送前 Markdown 转发钩子与交互式按钮工具。"""

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
from .services.interaction_engine import InteractionEngine
from .services.interactive import (
    ButtonLifecycleManager,
    InteractivePayloadError,
    build_astbot_message_chain,
    build_qq_keyboard_payload,
    parse_interactive_payload,
)
from .services.models import Endpoint
from .services.qq_sender import QQMarkdownSender
from .services.settings import PluginSettings

ONEBOT_PLATFORM = "aiocqhttp"
SATORI_PLATFORM = "satori"
SOURCE_PLATFORMS = {ONEBOT_PLATFORM, SATORI_PLATFORM}
QQ_PLATFORM_TYPES = (
    filter.PlatformAdapterType.QQOFFICIAL
    | filter.PlatformAdapterType.QQOFFICIAL_WEBHOOK
)
SKIP_FORWARD_EXTRA = "ob2qb_skip_forward"
STORAGE_KEY = "binding_state"

IDENTIFIER_LABELS = {
    "group_number": "群号",
    "qq_number": "私聊 QQ 号",
    "group_id": "群 ID",
    "user_id": "用户 ID",
    "group_openid": "群 OpenID",
    "user_openid": "用户 OpenID",
    "channel_id": "频道 ID",
    "guild_id": "频道私信 Guild ID",
    "session_id": "会话 ID",
}


def _noop_decorator(*_args, **_kwargs):
    def decorate(fn):
        return fn

    return decorate


llm_tool_filter = getattr(filter, "llm_tool", _noop_decorator)
button_action_filter = getattr(filter, "button_action", _noop_decorator)


class Main(Star):
    """将绑定 OneBot / Satori 会话的 Markdown 输出转发到 QQ 官方机器人。"""

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
        self.button_lifecycle = ButtonLifecycleManager()
        self.interaction_engine = InteractionEngine()
        self.game_engine = self.interaction_engine

        if self.detector.invalid_patterns:
            logger.warning(
                "Markdown 转发器忽略了无效正则: "
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
        """管理 OneBot / Satori 到 QQ 官方机器人的 Markdown 转发绑定。"""

        pass

    @ob2qb.command("req_bind")
    @filter.permission_type(filter.PermissionType.ADMIN)
    async def req_bind(self, event: AstrMessageEvent):
        """从当前 OneBot 或 Satori 群聊或私聊发出绑定请求。"""

        self._mark_command_result(event)
        if event.get_platform_name() not in SOURCE_PLATFORMS:
            yield event.plain_result("req_bind 只能在 OneBot 或 Satori 平台中执行。")
            return

        source = Endpoint.from_event(event)
        if not source.chat_id:
            plat = self._platform_display_name(source.platform_name)
            yield event.plain_result(
                f"无法读取当前 {plat} 群号/ID，未创建绑定请求。"
            )
            return
        request = await self.binding_store.request_binding(
            source, self.settings.pending_request_ttl_seconds
        )
        yield event.plain_result(
            "绑定请求已创建。\n"
            f"请求码：{request.code}\n"
            f"来源：{self._format_endpoint(source)}\n"
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
        valid_scenes = {"group", "c2c", "channel", "guild_direct"}
        if target.scene not in valid_scenes or not (
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
            yield event.plain_result("该绑定请求已过期，请在来源端重新申请。")
            return
        except BindingRequestNotFound:
            yield event.plain_result("未找到该绑定请求，请检查四位请求码。")
            return

        status = "绑定成功" if created else "该转发关系已存在"
        yield event.plain_result(
            f"{status}。\n"
            f"绑定 ID：{binding.binding_id}\n"
            f"来源端：{self._format_endpoint(binding.source)}\n"
            f"目标端：{self._format_endpoint(binding.target)}"
        )

    @ob2qb.command("list_bind")
    @filter.permission_type(filter.PermissionType.ADMIN)
    async def list_bind(self, event: AstrMessageEvent):
        """列出全部转发绑定关系及平台标识。"""

        self._mark_command_result(event)
        bindings = await self.binding_store.list_bindings()
        if not bindings:
            yield event.plain_result("当前没有来源端 → QQBot 转发绑定。")
            return

        lines = [f"当前共有 {len(bindings)} 条绑定："]
        for index, binding in enumerate(bindings, start=1):
            lines.extend(
                (
                    f"{index}. 绑定 ID：{binding.binding_id}",
                    f"   来源端：{self._format_endpoint(binding.source)} "
                    f"[适配器 {binding.source.platform_id}]",
                    f"   目标端：{self._format_endpoint(binding.target)} "
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
            f"来源端：{self._format_endpoint(binding.source)} → "
            f"目标端：{self._format_endpoint(binding.target)}"
        )

    @filter.platform_adapter_type(QQ_PLATFORM_TYPES)
    @filter.event_message_type(filter.EventMessageType.ALL, priority=100)
    async def remember_qq_event(self, event: AstrMessageEvent) -> None:
        """刷新已运行 QQ 会话的原生发送上下文。"""

        self.qq_sender.remember_event(event)

    @filter.on_decorating_result(priority=1000)
    async def forward_markdown_before_send(self, event: AstrMessageEvent) -> None:
        """发送前检测 Markdown，转发成功后清空原发送内容。"""

        if (
            not self.settings.enabled
            or event.get_platform_name() not in SOURCE_PLATFORMS
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
                logger.warning(f"QQ 转发成功，但更新目标消息 ID 失败: {exc!s}")

        if report.should_intercept(self.settings.intercept_policy):
            result.chain.clear()
            logger.info(
                f"已转发并清空 {event.get_platform_name()} Markdown 原消息: "
                f"success={report.success_count}, failed={report.failure_count}"
            )
        else:
            logger.warning(
                "Markdown 未达到拦截策略，保留原发送: "
                f"success={report.success_count}, failed={report.failure_count}"
            )

    @llm_tool_filter(name="send_markdown_with_buttons")
    async def send_markdown_with_buttons(
        self,
        event: AstrMessageEvent,
        layout: str,
    ):
        """发送排版丰富的 Markdown 消息与交互按钮（支持图文与多轮决策按钮混排）。

        【Bot 核心指引】：
        本工具发送后，插件后台已自动接管异步按钮回调！Bot 无需等待。
        要实现不同的业务，只需在按钮的 data 中配置对应字段：
        1. 猜拳对决小游戏：
           在 data 中设置 {"game": "rps", "choice": "rock/scissors/paper"}，
           或直接将按钮 ID 设为 rps_rock / rps_scissors / rps_paper。
           插件会自动判定输赢并输出包含『再来一局』按钮的新卡片！
        2. 唤醒大模型（你）继续多轮对话：
           在 data 中配置 "prompt": "用户 {user_name} 点击了..."，
           用户点击后插件会自动再次调用你生成回复！
        3. 声明式卡片跳转（分级菜单、分步向导、剧情分支）：
           在 data 中配置 "next_layout": { ... }，点击后直接无缝切换至下一级卡片。
        4. 执行聊天指令：
           设置 "type": "command", "data": "/指令"，点击后自动触发。

        Args:
            layout(string): 符合 JSON 格式的消息排版描述。详细规范如下：

        ## JSON 格式示例

        ### 形式一：猜拳互动对决小游戏示例
        ```json
        {
          "markdown": "🎮 **猜拳小游戏（剪刀石头布）**\\n请选择你的出拳：",
          "timeout": 60,
          "buttons": [
            [
              {"id": "rps_rock", "label": "✊ 石头", "action": "callback"},
              {"id": "rps_scissors", "label": "✌️ 剪刀", "action": "callback"},
              {"id": "rps_paper", "label": "🖐️ 布", "action": "callback"}
            ]
          ]
        }
        ```

        ### 形式二：客服与帮助多级菜单跳转示例
        ```json
        {
          "markdown": "您好！请选择需要咨询的服务类别：",
          "buttons": [
            [
              {
                "label": "售后服务",
                "action": "callback",
                "data": {
                  "next_layout": {
                    "markdown": "## 售后服务专区\\n请选择诉求：",
                    "buttons": [
                      {
                        "label": "退款",
                        "action": "callback",
                        "data": {"prompt": "退款"},
                      }
                    ]
                  }
                }
              }
            ]
          ]
        }
        ```

        ### 核心参数说明
        - markdown / content: Markdown 文本（请勿传布尔值 true）。
        - images / image: 图片 URL 或本地文件绝对路径。
        - timeout / action_timeout: 超时秒数（默认 60~180 秒）。
        - buttons: 按钮数组（支持一维列表或二维 [行[列]] 数组）。
          - id: 按钮唯一标识（如 rps_rock）。
          - label / text: 按钮标题。
          - visited_label: 点击后置灰的文字。
          - action / type: "callback"(回调), "url"(外链), "command"(指令)。
          - data: 携带参数（支持字典或字符串）。
            - prompt: 动态唤醒大模型的提示词（支持 {user_name} 变量）。
            - next_layout: 点击后切换的下一级交互卡片结构。
            - reply: 点击后的即时文本反馈。
          - style: primary, secondary, success, danger。
        """

        self._mark_command_result(event)
        try:
            payload = parse_interactive_payload(layout)
        except InteractivePayloadError as exc:
            yield f"排版 JSON 解析错误: {exc!s}"
            return

        chain = build_astbot_message_chain(payload)
        keyboard = build_qq_keyboard_payload(payload)

        # 检查当前会话是否有绑定的 QQ 官方机器人目标
        bindings = await self.binding_store.bindings_for_source(
            event.unified_msg_origin
        )
        forward_count = 0

        if bindings:
            report = await self.forwarder.forward(
                bindings,
                payload.full_markdown_text or payload.fallback_text,
                keyboard=keyboard,
                chain=chain,
            )
            forward_count = report.success_count
            message_ids = {
                attempt.binding.binding_id: attempt.receipt.message_id
                for attempt in report.attempts
                if attempt.success and attempt.receipt and attempt.receipt.message_id
            }
            if message_ids:
                try:
                    await self.binding_store.update_target_message_ids(message_ids)
                except Exception as exc:
                    logger.warning(f"更新目标消息 ID 失败: {exc!s}")

        # 若当前会话是 Satori 或 QQBot 等平台，或者当前会话无转发绑定，
        # 则在当前会话直接呈现消息
        platform_name = event.get_platform_name()
        sent_locally = False
        if platform_name not in SOURCE_PLATFORMS or not bindings:
            elements = getattr(chain, "chain", None)
            if elements is None:
                elements = [chain] if not isinstance(chain, list) else chain
            yield event.chain_result(elements)
            sent_locally = True

        if forward_count > 0:
            local_hint = "，且已在当前会话呈现" if sent_locally else ""
            yield (
                f"已成功将交互式 Markdown 消息转发到 {forward_count} 个 "
                f"QQ 官方机器人目标{local_hint}。"
            )
        elif sent_locally:
            yield "已成功在当前会话发送含交互按钮的 Markdown 消息。"
        else:
            yield "消息未能成功发送至目标端（请检查绑定或当前平台状态）。"

    @button_action_filter()
    async def handle_button_action(self, event: AstrMessageEvent):
        """处理交互按钮的回调生命周期、Prompt 动态触发与多轮决策流转。"""

        get_interaction = getattr(event, "get_button_interaction", None)
        interaction = get_interaction() if callable(get_interaction) else None
        if interaction is None:
            return

        action_id = str(getattr(interaction, "action_id", "") or "")
        data = getattr(interaction, "data", {}) or {}
        if not isinstance(data, dict):
            data = {}

        act = data.get("action", "")
        item = data.get("item_id", "")
        click_key = f"{event.unified_msg_origin}:{action_id}:{act}:{item}"
        if not self.button_lifecycle.should_process_click(
            click_key, debounce_seconds=1.5
        ):
            logger.debug(f"按钮重复点击已过滤: {click_key}")
            return

        logger.info(f"收到交互按钮点击回调: action_id={action_id}, data={data}")

        # 提取用户信息用于 Prompt 与决策模板动态注入
        user_name = ""
        get_sender_name = getattr(event, "get_sender_name", None)
        if callable(get_sender_name):
            try:
                user_name = str(get_sender_name())
            except Exception:
                user_name = ""
        user_id = str(getattr(event, "get_sender_id", lambda: "")() or "")

        # 1. 通过通用多轮决策引擎评估动作
        decision = self.interaction_engine.evaluate(
            action_id, data, user_name=user_name, user_id=user_id
        )

        # 2. 如果包含预设 Prompt，触发当前会话对应的来源 Bot LLM 动态回复
        if decision.use_llm:
            get_provider = getattr(self.context, "get_using_provider", None)
            provider = (
                get_provider(event.unified_msg_origin)
                if callable(get_provider)
                else None
            )
            if provider is not None and hasattr(provider, "text_chat"):
                try:
                    logger.info(
                        "交互按钮触发预设 Prompt 调用 LLM: "
                        f"{decision.prompt[:50]}..."
                    )
                    kw: dict[str, Any] = {}
                    if decision.system_prompt:
                        kw["system_prompt"] = decision.system_prompt
                    llm_resp = await provider.text_chat(
                        prompt=decision.prompt,
                        session_id=getattr(event, "session_id", None),
                        **kw,
                    )
                    completion = getattr(llm_resp, "completion_text", None)
                    if completion:
                        yield event.plain_result(str(completion))

                        # 若同时声明了下一级状态机卡片，将下一级卡片连带呈现
                        if decision.next_layout:
                            try:
                                next_p = parse_interactive_payload(
                                    decision.next_layout
                                )
                                next_c = build_astbot_message_chain(next_p)
                                elem = getattr(next_c, "chain", [next_c])
                                yield event.chain_result(elem)
                            except Exception as exc:
                                logger.warning(
                                    f"渲染伴随 next_layout 失败: {exc!s}"
                                )
                        return
                except Exception as exc:
                    logger.warning(f"交互按钮触发 LLM 回复失败: {exc!s}")

        # 3. 如果决策包含状态机卡片跳转（Next Layout），直接呈现新交互卡片
        if decision.next_layout:
            try:
                next_payload = parse_interactive_payload(decision.next_layout)
                next_chain = build_astbot_message_chain(next_payload)
                elements = getattr(next_chain, "chain", None)
                if elements is None:
                    elements = (
                        [next_chain]
                        if not isinstance(next_chain, list)
                        else next_chain
                    )
                if decision.text:
                    yield event.plain_result(decision.text)
                yield event.chain_result(elements)
                return
            except Exception as exc:
                logger.warning(f"渲染交互卡片 next_layout 失败: {exc!s}")

        # 4. 如果通用决策引擎有明确输出（如规则判定、分支说明等）
        if decision.text:
            yield event.plain_result(decision.text)
            return

        # 5. 常规预设反馈回退
        response_text = self.button_lifecycle.resolve_callback_response(
            action_id, data
        )
        yield event.plain_result(response_text)

    @staticmethod
    def _mark_command_result(event: AstrMessageEvent) -> None:
        event.set_extra(SKIP_FORWARD_EXTRA, True)

    @classmethod
    def _platform_display_name(cls, platform_name: str) -> str:
        if platform_name == ONEBOT_PLATFORM:
            return "OneBot"
        if platform_name == SATORI_PLATFORM:
            return "Satori"
        if platform_name in {"qq_official", "qq_official_webhook"}:
            return "QQBot"
        return platform_name

    @classmethod
    def _format_endpoint(cls, endpoint: Endpoint) -> str:
        plat = cls._platform_display_name(endpoint.platform_name)
        label = IDENTIFIER_LABELS.get(endpoint.id_kind, "会话 ID")
        value = endpoint.chat_id or endpoint.address_id or endpoint.session_id
        chat_label = "群聊" if endpoint.chat_type == "group" else "私聊"
        return f"{plat} {chat_label}（{label}：{value}）"

    @classmethod
    def _format_identifier(cls, endpoint: Endpoint) -> str:
        return cls._format_endpoint(endpoint)

    async def terminate(self) -> None:
        """插件无后台任务，保留生命周期入口供 AstrBot 正常卸载。"""