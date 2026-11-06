import asyncio
import unittest

from services.forwarder import MarkdownForwarder
from services.models import Binding, Endpoint
from services.qq_sender import SendReceipt


class FakeLogger:
    def __init__(self):
        self.errors = []

    def error(self, message):
        self.errors.append(message)


class FakeSender:
    def __init__(self):
        self.active = 0
        self.max_active = 0
        self.calls = []

    async def send_markdown(self, endpoint, text, **kwargs):
        self.active += 1
        self.max_active = max(self.max_active, self.active)
        self.calls.append((endpoint, text, kwargs))
        try:
            await asyncio.sleep(0)
            if endpoint.chat_id == "failed":
                raise RuntimeError("send failed")
            return SendReceipt(
                method="fake",
                message_id=f"message-{endpoint.chat_id}",
            )
        finally:
            self.active -= 1


def endpoint(platform, origin, chat_id):
    return Endpoint(
        platform_id=f"{platform}-1",
        platform_name=platform,
        unified_msg_origin=origin,
        message_type="GroupMessage",
        session_id=chat_id,
        chat_type="group",
        chat_id=chat_id,
        id_kind="group_number" if platform == "aiocqhttp" else "group_openid",
        scene="" if platform == "aiocqhttp" else "group",
        address_id=chat_id,
    )


def binding(binding_id, target_id):
    return Binding(
        binding_id=binding_id,
        source=endpoint("aiocqhttp", "ob:GroupMessage:1", "1"),
        target=endpoint(
            "qq_official",
            f"qq:GroupMessage:{target_id}",
            target_id,
        ),
        created_at=1.0,
    )


class MarkdownForwarderTests(unittest.IsolatedAsyncioTestCase):
    async def test_targets_are_concurrent_and_failures_are_isolated(self):
        sender = FakeSender()
        logger = FakeLogger()
        forwarder = MarkdownForwarder(sender, logger, timeout_seconds=5)

        report = await forwarder.forward(
            [binding("100001", "success"), binding("100002", "failed")],
            "# Markdown",
        )

        self.assertEqual(report.success_count, 1)
        self.assertEqual(report.failure_count, 1)
        self.assertGreaterEqual(sender.max_active, 2)
        self.assertTrue(report.should_intercept("any_success"))
        self.assertFalse(report.should_intercept("all_success"))
        self.assertEqual(len(logger.errors), 1)

    async def test_all_success_policy_intercepts_when_every_target_succeeds(self):
        forwarder = MarkdownForwarder(FakeSender(), FakeLogger(), timeout_seconds=5)

        report = await forwarder.forward(
            [binding("200001", "a"), binding("200002", "b")],
            "# Markdown",
        )

        self.assertEqual(report.success_count, 2)
        self.assertTrue(report.should_intercept("all_success"))

    async def test_forward_with_keyboard_and_chain(self):
        sender = FakeSender()
        logger = FakeLogger()
        forwarder = MarkdownForwarder(sender, logger, timeout_seconds=5)

        kb = {"rows": []}
        chain = object()
        report = await forwarder.forward(
            [binding("300001", "target1")],
            "# Interactive",
            keyboard=kb,
            chain=chain,
        )

        self.assertEqual(report.success_count, 1)
        self.assertEqual(len(sender.calls), 1)
        _, _, kwargs = sender.calls[0]
        self.assertIs(kwargs.get("keyboard"), kb)
        self.assertIs(kwargs.get("chain"), chain)


if __name__ == "__main__":
    unittest.main()