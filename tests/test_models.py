import unittest
from types import SimpleNamespace

from services.models import Endpoint


class FakeEvent:
    def __init__(self, platform_name, message_type, session_id, message_obj, raw):
        self._platform_name = platform_name
        self.session_id = session_id
        self.unified_msg_origin = f"adapter:{message_type}:{session_id}"
        self.session = SimpleNamespace(message_type=SimpleNamespace(value=message_type))
        message_obj.raw_message = raw
        self.message_obj = message_obj

    def get_platform_name(self):
        return self._platform_name

    def get_platform_id(self):
        return "adapter"

    def get_sender_name(self):
        return "???"


class EndpointIdentityTests(unittest.TestCase):
    def test_onebot_group_keeps_numeric_group_id(self):
        message_obj = SimpleNamespace(
            group_id="123456789",
            sender=SimpleNamespace(user_id="10001"),
            message_id="m1",
        )
        event = FakeEvent(
            "aiocqhttp", "GroupMessage", "123456789", message_obj, object()
        )

        endpoint = Endpoint.from_event(event)

        self.assertEqual(endpoint.chat_type, "group")
        self.assertEqual(endpoint.chat_id, "123456789")
        self.assertEqual(endpoint.id_kind, "group_number")

    def test_onebot_private_keeps_numeric_qq_id(self):
        message_obj = SimpleNamespace(
            group_id="",
            sender=SimpleNamespace(user_id="99887766"),
            message_id="m2",
        )
        event = FakeEvent(
            "aiocqhttp", "FriendMessage", "99887766", message_obj, object()
        )

        endpoint = Endpoint.from_event(event)

        self.assertEqual(endpoint.chat_type, "private")
        self.assertEqual(endpoint.chat_id, "99887766")
        self.assertEqual(endpoint.id_kind, "qq_number")

    def test_satori_group_endpoint(self):
        message_obj = SimpleNamespace(
            group_id="guild_channel_123",
            sender=SimpleNamespace(user_id="user_satori_1"),
            message_id="sm1",
        )
        event = FakeEvent(
            "satori", "GroupMessage", "channel_123", message_obj, object()
        )

        endpoint = Endpoint.from_event(event)

        self.assertEqual(endpoint.platform_name, "satori")
        self.assertEqual(endpoint.chat_type, "group")
        self.assertEqual(endpoint.chat_id, "guild_channel_123")
        self.assertEqual(endpoint.id_kind, "group_id")

    def test_satori_private_endpoint(self):
        message_obj = SimpleNamespace(
            group_id=None,
            sender=SimpleNamespace(user_id="user_satori_2"),
            message_id="sm2",
        )
        event = FakeEvent(
            "satori", "FriendMessage", "direct_channel_456", message_obj, object()
        )

        endpoint = Endpoint.from_event(event)

        self.assertEqual(endpoint.platform_name, "satori")
        self.assertEqual(endpoint.chat_type, "private")
        self.assertEqual(endpoint.chat_id, "user_satori_2")
        self.assertEqual(endpoint.id_kind, "user_id")

    def test_qq_group_uses_group_openid(self):
        raw = SimpleNamespace(group_openid="group-openid-1")
        message_obj = SimpleNamespace(
            group_id="group-openid-1",
            sender=SimpleNamespace(user_id="user-openid"),
            message_id="m3",
        )
        event = FakeEvent(
            "qq_official", "GroupMessage", "group-openid-1", message_obj, raw
        )

        endpoint = Endpoint.from_event(event)

        self.assertEqual(endpoint.chat_id, "group-openid-1")
        self.assertEqual(endpoint.id_kind, "group_openid")

    def test_patched_qq_c2c_uses_user_openid(self):
        raw_type = type("PatchedC2CMessage", (), {})
        raw = raw_type()
        raw.author = SimpleNamespace(user_openid="user-openid-1")
        message_obj = SimpleNamespace(
            group_id="",
            sender=SimpleNamespace(user_id="user-openid-1"),
            message_id="m4",
        )
        event = FakeEvent(
            "qq_official", "FriendMessage", "user-openid-1", message_obj, raw
        )

        endpoint = Endpoint.from_event(event)

        self.assertEqual(endpoint.scene, "c2c")
        self.assertEqual(endpoint.chat_id, "user-openid-1")
        self.assertEqual(endpoint.id_kind, "user_openid")

    def test_patched_guild_direct_prefers_guild_id_over_channel_id(self):
        raw_type = type("PatchedDirectMessage", (), {})
        raw = raw_type()
        raw.guild_id = "guild-1"
        raw.channel_id = "channel-from-dm"
        raw.author = SimpleNamespace(id="member-1")
        message_obj = SimpleNamespace(
            group_id="",
            sender=SimpleNamespace(user_id="member-1"),
            message_id="m5",
        )
        event = FakeEvent("qq_official", "FriendMessage", "member-1", message_obj, raw)

        endpoint = Endpoint.from_event(event)

        self.assertEqual(endpoint.scene, "guild_direct")
        self.assertEqual(endpoint.address_id, "guild-1")
        self.assertEqual(endpoint.id_kind, "guild_id")


if __name__ == "__main__":
    unittest.main()
