"""绑定请求和绑定关系的数据模型。"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any


def _string(value: Any) -> str:
    return "" if value is None else str(value)


def _raw_type_is(raw_message: Any, expected_name: str) -> bool:
    """兼容 QQ SDK 原始类型及 AstrBot 的 Patched* 包装类型。"""

    if raw_message is None:
        return False
    return type(raw_message).__name__.endswith(expected_name)


@dataclass(frozen=True, slots=True)
class Endpoint:
    """一条 AstrBot 会话端点，可安全序列化到插件 KV 存储。"""

    platform_id: str
    platform_name: str
    unified_msg_origin: str
    message_type: str
    session_id: str
    chat_type: str = ""
    chat_id: str = ""
    id_kind: str = ""
    scene: str = ""
    address_id: str = ""
    last_message_id: str = ""
    label: str = ""

    @classmethod
    def from_event(cls, event: Any) -> Endpoint:
        """从 AstrBot 事件提取端点及 QQ 官方发送所需的场景信息。"""

        message_obj = getattr(event, "message_obj", None)
        raw_message = getattr(message_obj, "raw_message", None)
        session_id = _string(getattr(event, "session_id", ""))
        platform_name = _string(event.get_platform_name())
        scene = ""
        address_id = session_id

        # QQ 官方的四类消息分别使用不同 API；持久化实际地址后，重启也能发送。
        author = getattr(raw_message, "author", None)
        group_openid = _string(getattr(raw_message, "group_openid", ""))
        user_openid = _string(getattr(author, "user_openid", ""))
        guild_id = _string(getattr(raw_message, "guild_id", ""))
        channel_id = _string(getattr(raw_message, "channel_id", ""))

        if group_openid or _raw_type_is(raw_message, "GroupMessage"):
            scene = "group"
            address_id = group_openid or session_id
        elif user_openid or _raw_type_is(raw_message, "C2CMessage"):
            scene = "c2c"
            address_id = user_openid or session_id
        elif _raw_type_is(raw_message, "DirectMessage"):
            scene = "guild_direct"
            address_id = guild_id or session_id
        elif channel_id or _raw_type_is(raw_message, "Message"):
            scene = "channel"
            address_id = channel_id or session_id

        session = getattr(event, "session", None)
        message_type_obj = getattr(session, "message_type", None)
        message_type = _string(getattr(message_type_obj, "value", message_type_obj))
        is_group = message_type == "GroupMessage"
        chat_type = "group" if is_group else "private"

        # OneBot 能提供真实群号/QQ 号；QQ 官方只提供 OpenID 或频道 ID。
        if platform_name == "aiocqhttp":
            if is_group:
                chat_id = _string(getattr(message_obj, "group_id", session_id))
                id_kind = "group_number"
            else:
                sender = getattr(message_obj, "sender", None)
                chat_id = _string(getattr(sender, "user_id", session_id))
                id_kind = "qq_number"
        else:
            chat_id = address_id
            id_kind = {
                "group": "group_openid",
                "c2c": "user_openid",
                "channel": "channel_id",
                "guild_direct": "guild_id",
            }.get(scene, "session_id")

        label = ""
        get_sender_name = getattr(event, "get_sender_name", None)
        if callable(get_sender_name):
            try:
                label = _string(get_sender_name())
            except Exception:
                label = ""

        return cls(
            platform_id=_string(event.get_platform_id()),
            platform_name=platform_name,
            unified_msg_origin=_string(event.unified_msg_origin),
            message_type=message_type,
            session_id=session_id,
            chat_type=chat_type,
            chat_id=chat_id,
            id_kind=id_kind,
            scene=scene,
            address_id=address_id,
            last_message_id=_string(getattr(message_obj, "message_id", "")),
            label=label,
        )

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> Endpoint:
        return cls(
            platform_id=_string(data.get("platform_id")),
            platform_name=_string(data.get("platform_name")),
            unified_msg_origin=_string(data.get("unified_msg_origin")),
            message_type=_string(data.get("message_type")),
            session_id=_string(data.get("session_id")),
            chat_type=_string(data.get("chat_type")),
            chat_id=_string(data.get("chat_id")),
            id_kind=_string(data.get("id_kind")),
            scene=_string(data.get("scene")),
            address_id=_string(data.get("address_id")),
            last_message_id=_string(data.get("last_message_id")),
            label=_string(data.get("label")),
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "platform_id": self.platform_id,
            "platform_name": self.platform_name,
            "unified_msg_origin": self.unified_msg_origin,
            "message_type": self.message_type,
            "session_id": self.session_id,
            "chat_type": self.chat_type,
            "chat_id": self.chat_id,
            "id_kind": self.id_kind,
            "scene": self.scene,
            "address_id": self.address_id,
            "last_message_id": self.last_message_id,
            "label": self.label,
        }

    def describe(self) -> str:
        scene = f"/{self.scene}" if self.scene else ""
        identifier = f" {self.id_kind}={self.chat_id}" if self.chat_id else ""
        return (
            f"{self.platform_name}({self.platform_id}){scene} "
            f"{self.message_type}:{self.session_id}{identifier}"
        )


@dataclass(frozen=True, slots=True)
class BindingRequest:
    code: str
    source: Endpoint
    created_at: float
    expires_at: float

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> BindingRequest:
        return cls(
            code=_string(data.get("code")),
            source=Endpoint.from_dict(data.get("source") or {}),
            created_at=float(data.get("created_at") or 0),
            expires_at=float(data.get("expires_at") or 0),
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "code": self.code,
            "source": self.source.to_dict(),
            "created_at": self.created_at,
            "expires_at": self.expires_at,
        }


@dataclass(frozen=True, slots=True)
class Binding:
    binding_id: str
    source: Endpoint
    target: Endpoint
    created_at: float

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> Binding:
        return cls(
            binding_id=_string(data.get("binding_id")),
            source=Endpoint.from_dict(data.get("source") or {}),
            target=Endpoint.from_dict(data.get("target") or {}),
            created_at=float(data.get("created_at") or 0),
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "binding_id": self.binding_id,
            "source": self.source.to_dict(),
            "target": self.target.to_dict(),
            "created_at": self.created_at,
        }
