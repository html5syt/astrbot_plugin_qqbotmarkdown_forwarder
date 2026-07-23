import copy
import unittest

from services.binding_store import BindingRequestExpired, BindingStore
from services.models import Endpoint


class MemoryBackend:
    def __init__(self):
        self.state = {}
        self.save_count = 0

    async def load(self):
        return copy.deepcopy(self.state)

    async def save(self, state):
        self.save_count += 1
        self.state = copy.deepcopy(state)


def endpoint(platform, origin, chat_id):
    is_onebot = platform == "aiocqhttp"
    return Endpoint(
        platform_id=f"{platform}-1",
        platform_name=platform,
        unified_msg_origin=origin,
        message_type="GroupMessage",
        session_id=chat_id,
        chat_type="group",
        chat_id=chat_id,
        id_kind="group_number" if is_onebot else "group_openid",
        scene="" if is_onebot else "group",
        address_id=chat_id,
    )


class BindingStoreTests(unittest.IsolatedAsyncioTestCase):
    async def test_one_to_many_and_persistence(self):
        backend = MemoryBackend()
        request_codes = iter(["1001", "1002"])
        binding_ids = iter(["200001", "200002"])
        store = BindingStore(
            backend.load,
            backend.save,
            request_code_factory=request_codes.__next__,
            binding_id_factory=binding_ids.__next__,
        )
        source = endpoint("aiocqhttp", "ob:GroupMessage:123", "123")
        target_a = endpoint("qq_official", "qa:GroupMessage:a", "a")
        target_b = endpoint("qq_official", "qa:GroupMessage:b", "b")

        request_a = await store.request_binding(source, 60)
        await store.acknowledge(request_a.code, target_a)
        request_b = await store.request_binding(source, 60)
        await store.acknowledge(request_b.code, target_b)

        reloaded = BindingStore(backend.load, backend.save)
        bindings = await reloaded.bindings_for_source(source.unified_msg_origin)
        self.assertEqual({item.binding_id for item in bindings}, {"200001", "200002"})

    async def test_many_to_one(self):
        backend = MemoryBackend()
        request_codes = iter(["3001", "3002"])
        binding_ids = iter(["400001", "400002"])
        store = BindingStore(
            backend.load,
            backend.save,
            request_code_factory=request_codes.__next__,
            binding_id_factory=binding_ids.__next__,
        )
        source_a = endpoint("aiocqhttp", "ob:GroupMessage:1", "1")
        source_b = endpoint("aiocqhttp", "ob:GroupMessage:2", "2")
        target = endpoint("qq_official", "qa:GroupMessage:x", "x")

        await store.acknowledge(
            (await store.request_binding(source_a, 60)).code, target
        )
        await store.acknowledge(
            (await store.request_binding(source_b, 60)).code, target
        )

        self.assertEqual(len(await store.list_bindings()), 2)

    async def test_duplicate_pair_is_idempotent(self):
        backend = MemoryBackend()
        request_codes = iter(["5001", "5002"])
        binding_ids = iter(["600001"])
        store = BindingStore(
            backend.load,
            backend.save,
            request_code_factory=request_codes.__next__,
            binding_id_factory=binding_ids.__next__,
        )
        source = endpoint("aiocqhttp", "ob:GroupMessage:1", "1")
        target = endpoint("qq_official", "qa:GroupMessage:x", "x")

        first, created_first = await store.acknowledge(
            (await store.request_binding(source, 60)).code, target
        )
        second, created_second = await store.acknowledge(
            (await store.request_binding(source, 60)).code, target
        )

        self.assertTrue(created_first)
        self.assertFalse(created_second)
        self.assertEqual(first.binding_id, second.binding_id)

    async def test_expired_request_is_rejected(self):
        backend = MemoryBackend()
        now = [100.0]
        store = BindingStore(
            backend.load,
            backend.save,
            clock=lambda: now[0],
            request_code_factory=lambda: "7001",
        )
        source = endpoint("aiocqhttp", "ob:GroupMessage:1", "1")
        target = endpoint("qq_official", "qa:GroupMessage:x", "x")
        request = await store.request_binding(source, 10)
        now[0] = 111.0

        with self.assertRaises(BindingRequestExpired):
            await store.acknowledge(request.code, target)

    async def test_duplicate_pair_refreshes_endpoint_identity(self):
        backend = MemoryBackend()
        request_codes = iter(["8001", "8002"])
        store = BindingStore(
            backend.load,
            backend.save,
            request_code_factory=request_codes.__next__,
            binding_id_factory=lambda: "900001",
        )
        source = endpoint("aiocqhttp", "ob:GroupMessage:1", "1")
        target = endpoint("qq_official", "qa:GroupMessage:x", "old-openid")
        first, _ = await store.acknowledge(
            (await store.request_binding(source, 60)).code, target
        )
        refreshed_target = Endpoint.from_dict(
            {
                **target.to_dict(),
                "chat_id": "new-openid",
                "address_id": "new-openid",
                "last_message_id": "latest-message",
            }
        )

        refreshed, created = await store.acknowledge(
            (await store.request_binding(source, 60)).code,
            refreshed_target,
        )

        self.assertFalse(created)
        self.assertEqual(refreshed.binding_id, first.binding_id)
        self.assertEqual(refreshed.target.chat_id, "new-openid")
        self.assertEqual(refreshed.target.last_message_id, "latest-message")

    async def test_batch_message_id_update_saves_once(self):
        backend = MemoryBackend()
        request_codes = iter(["8101", "8102"])
        binding_ids = iter(["910001", "910002"])
        store = BindingStore(
            backend.load,
            backend.save,
            request_code_factory=request_codes.__next__,
            binding_id_factory=binding_ids.__next__,
        )
        source = endpoint("aiocqhttp", "ob:GroupMessage:1", "1")
        target_a = endpoint("qq_official", "qa:GroupMessage:a", "a")
        target_b = endpoint("qq_official", "qa:GroupMessage:b", "b")
        await store.acknowledge(
            (await store.request_binding(source, 60)).code, target_a
        )
        await store.acknowledge(
            (await store.request_binding(source, 60)).code, target_b
        )
        saves_before_update = backend.save_count

        await store.update_target_message_ids(
            {"910001": "message-a", "910002": "message-b"}
        )

        self.assertEqual(backend.save_count, saves_before_update + 1)
        bindings = {
            binding.binding_id: binding for binding in await store.list_bindings()
        }
        self.assertEqual(bindings["910001"].target.last_message_id, "message-a")
        self.assertEqual(bindings["910002"].target.last_message_id, "message-b")


if __name__ == "__main__":
    unittest.main()
