import unittest
from types import SimpleNamespace
from unittest.mock import AsyncMock

from services.models import Endpoint
from services.qq_sender import QQMarkdownSender, QQMarkdownSendError


class FakeLogger:
    def __init__(self):
        self.warnings = []

    def warning(self, message):
        self.warnings.append(message)

    def debug(self, message):
        pass


class FakePlatform:
    def __init__(self):
        self.client = object()
        self.remembered = []

    def remember_session_message_id(self, session_id, message_id):
        self.remembered.append((session_id, message_id))


class FakeContext:
    def __init__(self, platform):
        self.platform = platform

    def get_platform_inst(self, platform_id):
        return self.platform if platform_id == "qq-1" else None


def target_endpoint():
    return Endpoint(
        platform_id="qq-1",
        platform_name="qq_official",
        unified_msg_origin="qq-1:GroupMessage:group-1",
        message_type="GroupMessage",
        session_id="group-1",
        chat_type="group",
        chat_id="group-1",
        id_kind="group_openid",
        scene="group",
        address_id="group-1",
    )


class QQMarkdownSenderTests(unittest.IsolatedAsyncioTestCase):
    async def test_none_markdown_result_triggers_plain_fallback(self):
        platform = FakePlatform()
        logger = FakeLogger()
        sender = QQMarkdownSender(
            FakeContext(platform), logger, native_plain_fallback=True
        )
        sender._send_payload = AsyncMock(
            side_effect=[None, SimpleNamespace(id="plain-message")]
        )

        receipt = await sender._send_native(target_endpoint(), "# Markdown")

        self.assertEqual(receipt.method, "native_plain_fallback")
        self.assertEqual(receipt.message_id, "plain-message")
        self.assertEqual(sender._send_payload.await_count, 2)
        self.assertTrue(sender._send_payload.await_args_list[0].kwargs["use_markdown"])
        self.assertFalse(sender._send_payload.await_args_list[1].kwargs["use_markdown"])
        self.assertEqual(platform.remembered, [("group-1", "plain-message")])

    async def test_none_plain_result_is_final_failure(self):
        sender = QQMarkdownSender(
            FakeContext(FakePlatform()),
            FakeLogger(),
            native_plain_fallback=True,
        )
        sender._send_payload = AsyncMock(
            side_effect=[RuntimeError("markdown rejected"), None]
        )

        with self.assertRaisesRegex(QQMarkdownSendError, "纯文本 API"):
            await sender._send_native(target_endpoint(), "# Markdown")

    async def test_none_markdown_result_fails_when_fallback_disabled(self):
        sender = QQMarkdownSender(
            FakeContext(FakePlatform()),
            FakeLogger(),
            native_plain_fallback=False,
        )
        sender._send_payload = AsyncMock(return_value=None)

        with self.assertRaisesRegex(QQMarkdownSendError, "Markdown API"):
            await sender._send_native(target_endpoint(), "# Markdown")

        self.assertEqual(sender._send_payload.await_count, 1)


if __name__ == "__main__":
    unittest.main()
