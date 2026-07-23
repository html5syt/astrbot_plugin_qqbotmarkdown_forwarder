"""绑定关系的并发安全持久化仓库。"""

from __future__ import annotations

import asyncio
import secrets
import time
from collections.abc import Awaitable, Callable, Mapping
from dataclasses import replace
from typing import Any

from .models import Binding, BindingRequest, Endpoint

LoadCallback = Callable[[], Awaitable[dict[str, Any] | None]]
SaveCallback = Callable[[dict[str, Any]], Awaitable[None]]
CodeFactory = Callable[[], str]


class BindingStoreError(Exception):
    """绑定仓库基础异常。"""


class BindingRequestNotFound(BindingStoreError):
    pass


class BindingRequestExpired(BindingStoreError):
    pass


class BindingStore:
    """管理待确认请求和正式绑定，并将状态保存到 AstrBot KV。"""

    STATE_VERSION = 1

    def __init__(
        self,
        load_callback: LoadCallback,
        save_callback: SaveCallback,
        *,
        clock: Callable[[], float] = time.time,
        request_code_factory: CodeFactory | None = None,
        binding_id_factory: CodeFactory | None = None,
    ) -> None:
        self._load_callback = load_callback
        self._save_callback = save_callback
        self._clock = clock
        self._request_code_factory = request_code_factory or (
            lambda: f"{secrets.randbelow(10_000):04d}"
        )
        self._binding_id_factory = binding_id_factory or (
            lambda: f"{secrets.randbelow(1_000_000):06d}"
        )
        self._lock = asyncio.Lock()
        self._loaded = False
        self._pending: dict[str, BindingRequest] = {}
        self._bindings: dict[str, Binding] = {}

    async def request_binding(
        self, source: Endpoint, ttl_seconds: int
    ) -> BindingRequest:
        async with self._lock:
            await self._ensure_loaded_unlocked()
            self._cleanup_expired_unlocked()

            # 同一 OneBot 会话只保留最新请求，避免四位码被无意义占满。
            self._pending = {
                code: request
                for code, request in self._pending.items()
                if request.source.unified_msg_origin != source.unified_msg_origin
            }
            code = self._new_unique_code(
                self._request_code_factory, set(self._pending), width=4
            )
            now = self._clock()
            request = BindingRequest(
                code=code,
                source=source,
                created_at=now,
                expires_at=now + max(1, ttl_seconds),
            )
            self._pending[code] = request
            await self._save_unlocked()
            return request

    async def acknowledge(self, code: str, target: Endpoint) -> tuple[Binding, bool]:
        async with self._lock:
            await self._ensure_loaded_unlocked()
            request = self._pending.get(code)
            if request is None:
                changed = self._cleanup_expired_unlocked()
                if changed:
                    await self._save_unlocked()
                raise BindingRequestNotFound(code)

            if request.expires_at <= self._clock():
                self._pending.pop(code, None)
                await self._save_unlocked()
                raise BindingRequestExpired(code)

            self._pending.pop(code, None)
            for binding in self._bindings.values():
                if (
                    binding.source.unified_msg_origin
                    == request.source.unified_msg_origin
                    and binding.target.unified_msg_origin == target.unified_msg_origin
                ):
                    # 重复确认时刷新群号/OpenID、场景及最新消息 ID，保留原绑定 ID。
                    binding = replace(
                        binding,
                        source=request.source,
                        target=target,
                    )
                    self._bindings[binding.binding_id] = binding
                    await self._save_unlocked()
                    return binding, False

            binding_id = self._new_unique_code(
                self._binding_id_factory, set(self._bindings), width=6
            )
            binding = Binding(
                binding_id=binding_id,
                source=request.source,
                target=target,
                created_at=self._clock(),
            )
            self._bindings[binding_id] = binding
            await self._save_unlocked()
            return binding, True

    async def list_bindings(self) -> list[Binding]:
        async with self._lock:
            await self._ensure_loaded_unlocked()
            return sorted(self._bindings.values(), key=lambda item: item.created_at)

    async def bindings_for_source(self, source_origin: str) -> list[Binding]:
        async with self._lock:
            await self._ensure_loaded_unlocked()
            return [
                binding
                for binding in self._bindings.values()
                if binding.source.unified_msg_origin == source_origin
            ]

    async def remove_binding(self, binding_id: str) -> Binding | None:
        async with self._lock:
            await self._ensure_loaded_unlocked()
            binding = self._bindings.pop(binding_id, None)
            if binding is not None:
                await self._save_unlocked()
            return binding

    async def update_target_message_id(self, binding_id: str, message_id: str) -> None:
        await self.update_target_message_ids({binding_id: message_id})

    async def update_target_message_ids(self, message_ids: Mapping[str, str]) -> None:
        """批量刷新目标消息 ID，并将多目标转发合并为一次 KV 写入。"""

        updates = {
            str(binding_id): str(message_id)
            for binding_id, message_id in message_ids.items()
            if binding_id and message_id
        }
        if not updates:
            return

        async with self._lock:
            await self._ensure_loaded_unlocked()
            changed = False
            for binding_id, message_id in updates.items():
                binding = self._bindings.get(binding_id)
                if binding is None or binding.target.last_message_id == message_id:
                    continue
                target = replace(binding.target, last_message_id=message_id)
                self._bindings[binding_id] = replace(binding, target=target)
                changed = True
            if changed:
                await self._save_unlocked()

    async def _ensure_loaded_unlocked(self) -> None:
        if self._loaded:
            return
        raw_state = await self._load_callback() or {}
        pending = raw_state.get("pending") if isinstance(raw_state, dict) else {}
        bindings = raw_state.get("bindings") if isinstance(raw_state, dict) else {}

        if isinstance(pending, dict):
            for code, raw_request in pending.items():
                try:
                    request = BindingRequest.from_dict(raw_request)
                except (TypeError, ValueError, AttributeError):
                    continue
                if request.code and request.source.unified_msg_origin:
                    self._pending[str(code)] = request

        if isinstance(bindings, dict):
            for binding_id, raw_binding in bindings.items():
                try:
                    binding = Binding.from_dict(raw_binding)
                except (TypeError, ValueError, AttributeError):
                    continue
                if (
                    binding.binding_id
                    and binding.source.unified_msg_origin
                    and binding.target.unified_msg_origin
                ):
                    self._bindings[str(binding_id)] = binding

        self._loaded = True
        if self._cleanup_expired_unlocked():
            await self._save_unlocked()

    def _cleanup_expired_unlocked(self) -> bool:
        now = self._clock()
        expired = [
            code for code, request in self._pending.items() if request.expires_at <= now
        ]
        for code in expired:
            self._pending.pop(code, None)
        return bool(expired)

    def _new_unique_code(
        self, factory: CodeFactory, existing: set[str], *, width: int
    ) -> str:
        for _ in range(100):
            code = str(factory()).zfill(width)
            if len(code) == width and code.isdigit() and code not in existing:
                return code
        raise BindingStoreError(f"无法生成唯一的 {width} 位数字标识")

    async def _save_unlocked(self) -> None:
        state = {
            "version": self.STATE_VERSION,
            "pending": {
                code: request.to_dict() for code, request in self._pending.items()
            },
            "bindings": {
                binding_id: binding.to_dict()
                for binding_id, binding in self._bindings.items()
            },
        }
        await self._save_callback(state)
