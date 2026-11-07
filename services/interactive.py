"""交互式 Markdown 与按钮混排解析器、消息构建器及生命周期管理。"""

from __future__ import annotations

import json
import time
from dataclasses import dataclass, field
from typing import Any


class InteractivePayloadError(Exception):
    """交互消息载荷解析异常。"""


@dataclass(frozen=True, slots=True)
class MarkdownSegment:
    content: str
    type: str = "markdown"

    def to_dict(self) -> dict[str, Any]:
        return {"type": "markdown", "content": self.content}


@dataclass(frozen=True, slots=True)
class ImageSegment:
    url: str = ""
    path: str = ""
    type: str = "image"

    def to_dict(self) -> dict[str, Any]:
        result = {"type": "image"}
        if self.url:
            result["url"] = self.url
        if self.path:
            result["path"] = self.path
        return result


@dataclass(frozen=True, slots=True)
class ButtonSegment:
    id: str
    label: str
    action: str  # "callback"、"url" 或 "command"
    url: str = ""
    data: dict[str, Any] = field(default_factory=dict)
    style: str = "primary"  # primary, secondary, success, danger
    reply: str = ""  # 点击回调时的快速回复文本
    visited_label: str = ""  # 点击后的置灰/已点击文本
    type: str = "button"

    def to_dict(self) -> dict[str, Any]:
        res: dict[str, Any] = {
            "type": "button",
            "id": self.id,
            "label": self.label,
            "action": self.action,
            "style": self.style,
        }
        if self.url:
            res["url"] = self.url
        if self.data:
            res["data"] = self.data
        if self.reply:
            res["reply"] = self.reply
        if self.visited_label:
            res["visited_label"] = self.visited_label
        return res


@dataclass(frozen=True, slots=True)
class ActionRowSegment:
    buttons: tuple[ButtonSegment, ...]
    action_timeout: int | None = None
    fallback_text: str = ""
    type: str = "action_row"

    def to_dict(self) -> dict[str, Any]:
        res: dict[str, Any] = {
            "type": "action_row",
            "buttons": [b.to_dict() for b in self.buttons],
        }
        if self.action_timeout is not None:
            res["action_timeout"] = self.action_timeout
        if self.fallback_text:
            res["fallback_text"] = self.fallback_text
        return res


@dataclass(frozen=True, slots=True)
class InteractivePayload:
    segments: tuple[MarkdownSegment | ImageSegment | ActionRowSegment, ...]

    @property
    def full_markdown_text(self) -> str:
        parts = [
            seg.content
            for seg in self.segments
            if isinstance(seg, MarkdownSegment)
        ]
        return "\n\n".join(parts)

    @property
    def action_rows(self) -> tuple[ActionRowSegment, ...]:
        return tuple(
            seg for seg in self.segments if isinstance(seg, ActionRowSegment)
        )

    @property
    def images(self) -> tuple[ImageSegment, ...]:
        return tuple(
            seg for seg in self.segments if isinstance(seg, ImageSegment)
        )

    @property
    def fallback_text(self) -> str:
        parts = []
        for seg in self.segments:
            if isinstance(seg, MarkdownSegment):
                parts.append(seg.content)
            elif isinstance(seg, ImageSegment):
                ref = seg.url or seg.path
                parts.append(f"[图片: {ref}]")
            elif isinstance(seg, ActionRowSegment):
                if seg.fallback_text:
                    parts.append(seg.fallback_text)
                else:
                    btn_strs = []
                    for btn in seg.buttons:
                        if btn.action == "url":
                            btn_strs.append(f"[{btn.label}]({btn.url})")
                        elif btn.action == "command":
                            cmd = btn.data.get("command", "")
                            btn_strs.append(f"[{btn.label}: {cmd}]")
                        else:
                            btn_strs.append(f"[{btn.label}]")
                    parts.append(" ".join(btn_strs))
        return "\n".join(parts)

    def to_dict(self) -> dict[str, Any]:
        return {
            "segments": [seg.to_dict() for seg in self.segments],
            "fallback_text": self.fallback_text,
        }


def _strip_markdown_code_fences(text: str) -> str:
    text = text.strip()
    if text.startswith("```"):
        first_line_end = text.find("\n")
        if first_line_end != -1:
            text = text[first_line_end + 1 :]
        if text.endswith("```"):
            text = text[:-3]
    return text.strip()


def _extract_timeout(data: dict[str, Any]) -> int | None:
    timeout_val = (
        data.get("action_timeout")
        if data.get("action_timeout") is not None
        else (
            data.get("timeout")
            if data.get("timeout") is not None
            else data.get("expire_seconds")
        )
    )
    if timeout_val is not None:
        try:
            val = int(timeout_val)
            if val > 0:
                return val
        except (ValueError, TypeError):
            pass
    return None


def parse_interactive_payload(raw_data: str | dict | list) -> InteractivePayload:
    """将字符串或字典/列表结构解析为标准 InteractivePayload。"""

    if isinstance(raw_data, str):
        cleaned = _strip_markdown_code_fences(raw_data)
        try:
            parsed = json.loads(cleaned)
        except json.JSONDecodeError as exc:
            raise InteractivePayloadError(f"无效的 JSON 格式: {exc.msg}") from exc
    elif isinstance(raw_data, (dict, list)):
        parsed = raw_data
    else:
        raise InteractivePayloadError(f"不支持的载荷类型: {type(raw_data).__name__}")

    segments: list[MarkdownSegment | ImageSegment | ActionRowSegment] = []

    if isinstance(parsed, list):
        # 形式二：顺序分段列表
        btn_seq = 1
        for item in parsed:
            if not isinstance(item, dict):
                continue
            item_type = str(item.get("type", "markdown")).lower()
            if item_type in {"markdown", "text", "plain"}:
                content = str(item.get("content") or item.get("text") or "")
                if content:
                    segments.append(MarkdownSegment(content=content))
            elif item_type == "image":
                url = str(item.get("url") or "")
                path = str(item.get("path") or item.get("file") or "")
                if url or path:
                    segments.append(ImageSegment(url=url, path=path))
            elif item_type in {"action_row", "buttons", "button_row"}:
                row, btn_seq = _parse_action_row(item, btn_seq)
                if row.buttons:
                    segments.append(row)
    elif isinstance(parsed, dict):
        if "segments" in parsed and isinstance(parsed["segments"], list):
            return parse_interactive_payload(parsed["segments"])

        # 形式一：结构化配置对象
        default_timeout = _extract_timeout(parsed)

        # 1. 收集 Markdown 文本（兼容 markdown 为布尔值时取 text/content）
        raw_md = parsed.get("markdown")
        if isinstance(raw_md, str) and raw_md:
            md_text = raw_md
        else:
            md_text = parsed.get("text") or parsed.get("content") or ""

        if md_text:
            segments.append(MarkdownSegment(content=str(md_text)))

        # 2. 收集图片
        images = parsed.get("images") or parsed.get("image")
        if isinstance(images, list):
            for img in images:
                if isinstance(img, str) and img:
                    segments.append(ImageSegment(url=img))
                elif isinstance(img, dict):
                    segments.append(
                        ImageSegment(
                            url=str(img.get("url") or ""),
                            path=str(img.get("path") or img.get("file") or ""),
                        )
                    )
        elif isinstance(images, str) and images:
            segments.append(ImageSegment(url=images))

        # 3. 收集按钮行（支持二维数组 [[btn1, btn2], [btn3]] 或一维数组）
        btn_seq = 1
        if "action_rows" in parsed and isinstance(parsed["action_rows"], list):
            for row_data in parsed["action_rows"]:
                if isinstance(row_data, dict):
                    raw_b = row_data.get("buttons")
                    if (
                        isinstance(raw_b, list)
                        and raw_b
                        and isinstance(raw_b[0], list)
                    ):
                        for sub_row in raw_b:
                            sub_dict = dict(row_data)
                            sub_dict["buttons"] = sub_row
                            row, btn_seq = _parse_action_row(
                                sub_dict,
                                btn_seq,
                                default_timeout=default_timeout,
                            )
                            if row.buttons:
                                segments.append(row)
                    else:
                        row, btn_seq = _parse_action_row(
                            row_data, btn_seq, default_timeout=default_timeout
                        )
                        if row.buttons:
                            segments.append(row)
        elif "buttons" in parsed and isinstance(parsed["buttons"], list):
            raw_buttons = parsed["buttons"]
            if raw_buttons and isinstance(raw_buttons[0], list):
                for sub_row in raw_buttons:
                    if isinstance(sub_row, list):
                        row_dict = {"buttons": sub_row}
                        row, btn_seq = _parse_action_row(
                            row_dict, btn_seq, default_timeout=default_timeout
                        )
                        if row.buttons:
                            segments.append(row)
            else:
                row, btn_seq = _parse_action_row(
                    parsed, btn_seq, default_timeout=default_timeout
                )
                if row.buttons:
                    segments.append(row)

    if not segments:
        raise InteractivePayloadError(
            "消息载荷中未包含任何有效内容（文本、图片或按钮）"
        )

    return InteractivePayload(tuple(segments))


def _parse_action_row(
    data: dict[str, Any],
    start_seq: int,
    *,
    default_timeout: int | None = None,
) -> tuple[ActionRowSegment, int]:
    raw_buttons = data.get("buttons") or []
    if not isinstance(raw_buttons, list):
        raw_buttons = []

    action_timeout = _extract_timeout(data)
    if action_timeout is None:
        action_timeout = default_timeout

    fallback_text = str(data.get("fallback_text") or "")

    buttons: list[ButtonSegment] = []
    seq = start_seq
    for item in raw_buttons:
        if not isinstance(item, dict):
            continue
        btn_id = str(item.get("id") or f"ob2qb:btn_{seq}")
        seq += 1
        label = str(item.get("label") or item.get("text") or "按钮")
        visited_label = str(item.get("visited_label") or "")
        url = str(item.get("url") or item.get("link") or "")
        reply = str(item.get("reply") or "")
        style = str(item.get("style") or "primary").lower()
        if style not in {"primary", "secondary", "success", "danger"}:
            style = "primary"

        # 判断动作类型（兼容 action / type 为 command, callback, url）
        action = str(item.get("action") or item.get("type") or "").lower()
        cmd_val = item.get("command")
        if action in {"command", "cmd"} or cmd_val:
            action = "command"
        elif action in {"url", "link"}:
            action = "url"
        elif not action:
            action = "url" if url else "callback"

        # 规范化 data 字段（兼容字符串、字典等）
        raw_data = item.get("data")
        btn_data: dict[str, Any] = {}
        if isinstance(raw_data, dict):
            btn_data = dict(raw_data)
        elif isinstance(raw_data, str) and raw_data:
            if action == "command":
                btn_data = {"command": raw_data, "data": raw_data}
            else:
                btn_data = {"data": raw_data, "text": raw_data}
        elif raw_data is not None:
            btn_data = {"data": raw_data}

        if action == "command" and "command" not in btn_data:
            if cmd_val:
                btn_data["command"] = str(cmd_val)
            elif url:
                btn_data["command"] = url
            elif raw_data:
                btn_data["command"] = str(raw_data)

        buttons.append(
            ButtonSegment(
                id=btn_id,
                label=label,
                action=action,
                url=url,
                data=btn_data,
                style=style,
                reply=reply,
                visited_label=visited_label,
            )
        )

    return (
        ActionRowSegment(
            buttons=tuple(buttons),
            action_timeout=action_timeout,
            fallback_text=fallback_text,
        ),
        seq,
    )


def build_astbot_message_chain(payload: InteractivePayload) -> Any:
    """将 InteractivePayload 构建为 AstrBot 的 MessageChain 对象。"""
    try:
        import astrbot.api.message_components as Comp
        from astrbot.api.event import MessageChain
    except ImportError:
        # 非 AstrBot 运行环境下返回通用字典
        return payload.to_dict()

    chain = MessageChain()
    chain.use_markdown(True)

    ActionRow = getattr(Comp, "ActionRow", None)
    Button = getattr(Comp, "Button", None)

    for seg in payload.segments:
        if isinstance(seg, MarkdownSegment):
            chain.message(seg.content)
        elif isinstance(seg, ImageSegment):
            if seg.url:
                try:
                    chain.chain.append(Comp.Image.fromURL(seg.url))
                except Exception:
                    chain.chain.append(Comp.Image(file=seg.url))
            elif seg.path:
                try:
                    chain.chain.append(Comp.Image.fromFileSystem(seg.path))
                except Exception:
                    chain.chain.append(Comp.Image(file=seg.path))
        elif isinstance(seg, ActionRowSegment):
            if ActionRow is not None and Button is not None:
                comp_buttons = []
                for b in seg.buttons:
                    style_enum = getattr(Button, "Style", None)
                    chosen_style = None
                    if style_enum is not None:
                        style_map = {
                            "primary": getattr(style_enum, "PRIMARY", None),
                            "secondary": getattr(style_enum, "SECONDARY", None),
                            "success": getattr(style_enum, "SUCCESS", None),
                            "danger": getattr(style_enum, "DANGER", None),
                        }
                        chosen_style = style_map.get(b.style)

                    cb_data = dict(b.data)
                    if b.reply and "reply" not in cb_data:
                        cb_data["reply"] = b.reply

                    if b.action == "url":
                        btn_action = Button.UrlAction(url=b.url)
                    elif b.action == "command":
                        cmd_act_cls = getattr(Button, "CommandAction", None)
                        if cmd_act_cls is not None:
                            btn_action = cmd_act_cls(
                                command=cb_data.get("command", "")
                            )
                        else:
                            btn_action = Button.CallbackAction(data=cb_data)
                    else:
                        btn_action = Button.CallbackAction(data=cb_data)

                    btn_kwargs = {
                        "id": b.id,
                        "label": b.label,
                        "action": btn_action,
                    }
                    if chosen_style is not None:
                        btn_kwargs["style"] = chosen_style

                    comp_buttons.append(Button(**btn_kwargs))

                row_kwargs: dict[str, Any] = {"buttons": comp_buttons}
                if seg.action_timeout is not None:
                    row_kwargs["action_timeout"] = seg.action_timeout
                if seg.fallback_text:
                    row_kwargs["fallback_text"] = seg.fallback_text

                chain.chain.append(ActionRow(**row_kwargs))
            else:
                fallback_msg = seg.fallback_text or payload.fallback_text
                chain.chain.append(Comp.Plain(fallback_msg))

    return chain


def build_qq_keyboard_payload(payload: InteractivePayload) -> dict[str, Any] | None:
    """将交互按钮转换为 QQ 官方机器人原生的 inline keyboard 数据字典。"""
    action_rows = payload.action_rows
    if not action_rows:
        return None

    rows = []
    for row_seg in action_rows:
        buttons = []
        for btn in row_seg.buttons:
            # 按钮样式: 0 灰色/默认, 1 蓝色/primary, 2 红色/danger
            is_blue = btn.style in {"primary", "blue"}
            is_red = btn.style in {"danger", "red"}
            style_code = 1 if is_blue else (2 if is_red else 0)

            # QQ Bot Action Type: 0: 跳转, 1: 回调, 2: 指令
            if btn.action == "url":
                action_type = 0
                action_data = btn.url
            elif btn.action == "command":
                action_type = 2
                action_data = str(
                    btn.data.get("command") or btn.data.get("data") or ""
                )
            else:
                action_type = 1
                cb_data = dict(btn.data)
                if btn.reply and "reply" not in cb_data:
                    cb_data["reply"] = btn.reply
                action_data = json.dumps(cb_data, ensure_ascii=False)

            visited = btn.visited_label if btn.visited_label else btn.label

            button_item = {
                "id": btn.id,
                "render_data": {
                    "label": btn.label,
                    "visited_label": visited,
                    "style": style_code,
                },
                "action": {
                    "type": action_type,
                    "permission": {"type": 2},  # 所有人可见/可点击
                    "data": action_data,
                    "click_limit": 10,
                    "at_bot_show_channel_list": False,
                },
            }
            buttons.append(button_item)
        if buttons:
            rows.append({"buttons": buttons})

    if not rows:
        return None

    return {"content": {"rows": rows}}


class ButtonLifecycleManager:
    """交互按钮的生命周期管理与去重、回调处理。"""

    def __init__(self, cache_size: int = 500) -> None:
        self._cache_size = cache_size
        self._processed_clicks: dict[str, float] = {}

    def should_process_click(
        self, click_id: str, debounce_seconds: float = 2.0
    ) -> bool:
        """防重复点击检测。"""
        now = time.time()
        self._cleanup()
        last_time = self._processed_clicks.get(click_id)
        if last_time and (now - last_time < debounce_seconds):
            return False
        self._processed_clicks[click_id] = now
        return True

    def _cleanup(self) -> None:
        if len(self._processed_clicks) > self._cache_size:
            keys = list(self._processed_clicks.keys())[: self._cache_size // 5]
            for k in keys:
                self._processed_clicks.pop(k, None)

    @staticmethod
    def resolve_callback_response(action_id: str, data: dict[str, Any]) -> str:
        """解析回调数据，生成面向用户的友好反馈。"""
        if "reply" in data and data["reply"]:
            return str(data["reply"])
        if "text" in data and data["text"]:
            return str(data["text"])
        if "command" in data and data["command"]:
            return f"执行指令：{data['command']}"
        if "action" in data and data["action"]:
            return f"已处理操作：{data['action']}"
        return f"已触发操作：{action_id}"