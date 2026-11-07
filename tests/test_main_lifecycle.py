import importlib.util
import sys
import types
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock


class Plain:
    def __init__(self, text):
        self.text = text


class FakeLogger:
    def debug(self, _message):
        pass

    def info(self, _message):
        pass

    def warning(self, _message):
        pass


def identity_decorator(*_args, **_kwargs):
    return lambda function: function


def command_group_decorator(*_args, **_kwargs):
    def decorate(function):
        function.command = identity_decorator
        return function

    return decorate


def load_main_module():
    """用最小 AstrBot 接口桩加载插件入口，避免单测依赖完整 AstrBot。"""

    astrbot_module = types.ModuleType("astrbot")
    api_module = types.ModuleType("astrbot.api")
    components_module = types.ModuleType("astrbot.api.message_components")
    event_module = types.ModuleType("astrbot.api.event")
    star_module = types.ModuleType("astrbot.api.star")

    components_module.Plain = Plain
    api_module.AstrBotConfig = dict
    api_module.logger = FakeLogger()
    api_module.message_components = components_module
    event_module.AstrMessageEvent = object
    event_module.filter = SimpleNamespace(
        PlatformAdapterType=SimpleNamespace(
            QQOFFICIAL=1,
            QQOFFICIAL_WEBHOOK=2,
        ),
        EventMessageType=SimpleNamespace(ALL=object()),
        PermissionType=SimpleNamespace(ADMIN=object()),
        command_group=command_group_decorator,
        permission_type=identity_decorator,
        platform_adapter_type=identity_decorator,
        event_message_type=identity_decorator,
        on_decorating_result=identity_decorator,
        llm_tool=identity_decorator,
        button_action=identity_decorator,
    )
    star_module.Context = object
    star_module.Star = object
    astrbot_module.api = api_module

    sys.modules.update(
        {
            "astrbot": astrbot_module,
            "astrbot.api": api_module,
            "astrbot.api.message_components": components_module,
            "astrbot.api.event": event_module,
            "astrbot.api.star": star_module,
        }
    )

    root = Path(__file__).resolve().parents[1]
    package_name = "_ob2qb_lifecycle_test_plugin"
    package = types.ModuleType(package_name)
    package.__path__ = [str(root)]
    sys.modules[package_name] = package

    spec = importlib.util.spec_from_file_location(
        f"{package_name}.main",
        root / "main.py",
    )
    if spec is None or spec.loader is None:
        raise RuntimeError("无法加载插件入口")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


MAIN_MODULE = load_main_module()


class FakeEvent:
    unified_msg_origin = "aiocqhttp:GroupMessage:123456"

    def __init__(self, chain, platform="aiocqhttp"):
        self.result = SimpleNamespace(chain=chain)
        self.stopped = False
        self._platform = platform
        self.extras = {}

    def get_platform_name(self):
        return self._platform

    def get_extra(self, key, default=None):
        return self.extras.get(key, default)

    def set_extra(self, key, value):
        self.extras[key] = value

    def get_result(self):
        return self.result

    def stop_event(self):
        self.stopped = True

    def chain_result(self, chain):
        return SimpleNamespace(chain=chain)

    def plain_result(self, text):
        return SimpleNamespace(text=text)

    def get_sender_name(self):
        return "玩家一号"

    def get_sender_id(self):
        return "999888"


class FakeReport:
    attempts = ()
    success_count = 1
    failure_count = 0

    def __init__(self, intercept):
        self.intercept = intercept

    def should_intercept(self, _policy):
        return self.intercept


def make_plugin(report, enabled=True):
    from services.game_engine import InteractiveGameEngine
    from services.interactive import ButtonLifecycleManager

    fake_provider = SimpleNamespace(
        text_chat=AsyncMock(
            return_value=SimpleNamespace(
                completion_text="这是大模型根据预设 Prompt 生成的回复。"
            )
        )
    )
    context = SimpleNamespace(
        get_using_provider=Mock(return_value=fake_provider)
    )

    return SimpleNamespace(
        context=context,
        settings=SimpleNamespace(
            enabled=enabled,
            only_plain_text=True,
            debug_logging=False,
            intercept_policy="any_success",
        ),
        binding_store=SimpleNamespace(
            bindings_for_source=AsyncMock(return_value=[object()]),
            update_target_message_ids=AsyncMock(),
        ),
        detector=SimpleNamespace(
            detect=Mock(
                return_value=SimpleNamespace(
                    matched=True,
                    regex_hits=1,
                    length_hit=False,
                )
            )
        ),
        forwarder=SimpleNamespace(forward=AsyncMock(return_value=report)),
        button_lifecycle=ButtonLifecycleManager(),
        interaction_engine=InteractiveGameEngine(),
        game_engine=InteractiveGameEngine(),
        _mark_command_result=Mock(),
    )


class MainLifecycleTests(unittest.IsolatedAsyncioTestCase):
    async def test_success_clears_chain_without_stopping_pipeline(self):
        event = FakeEvent([Plain("# Markdown")])
        plugin = make_plugin(FakeReport(intercept=True))

        await MAIN_MODULE.Main.forward_markdown_before_send(plugin, event)

        self.assertEqual(event.result.chain, [])
        self.assertFalse(event.stopped)

    async def test_failed_intercept_policy_preserves_original_chain(self):
        original_chain = [Plain("# Markdown")]
        event = FakeEvent(original_chain.copy())
        plugin = make_plugin(FakeReport(intercept=False))

        await MAIN_MODULE.Main.forward_markdown_before_send(plugin, event)

        self.assertEqual(event.result.chain, original_chain)
        self.assertFalse(event.stopped)

    async def test_satori_platform_forwarding_supported(self):
        event = FakeEvent([Plain("$$E=mc^2$$")], platform="satori")
        plugin = make_plugin(FakeReport(intercept=True))

        await MAIN_MODULE.Main.forward_markdown_before_send(plugin, event)

        self.assertEqual(event.result.chain, [])
        plugin.forwarder.forward.assert_awaited_once()

    async def test_tool_sends_even_when_auto_forwarding_disabled(self):
        event = FakeEvent([], platform="aiocqhttp")
        plugin = make_plugin(FakeReport(intercept=True), enabled=False)

        layout = (
            '{"markdown": "## 报告", "action_rows": [{"buttons": '
            '[{"label": "查看", "action": "url", "url": "https://example.com"}]}]}'
        )

        results = []
        gen = MAIN_MODULE.Main.send_markdown_with_buttons(plugin, event, layout)
        async for item in gen:
            results.append(item)

        plugin.forwarder.forward.assert_awaited_once()
        self.assertTrue(any("已成功将交互式 Markdown" in str(r) for r in results))

    async def test_button_callback_action_handled(self):
        plugin = make_plugin(FakeReport(intercept=True))
        event = FakeEvent([], platform="qq_official")
        event.get_button_interaction = Mock(
            return_value=SimpleNamespace(
                action_id="ob2qb:test_btn",
                data={"reply": "处理成功！"},
            )
        )

        results = []
        async for item in MAIN_MODULE.Main.handle_button_action(plugin, event):
            results.append(item)

        self.assertEqual(len(results), 1)
        self.assertEqual(results[0].text, "处理成功！")

    async def test_button_triggers_llm_prompt(self):
        plugin = make_plugin(FakeReport(intercept=True))
        event = FakeEvent([], platform="qq_official")
        event.get_button_interaction = Mock(
            return_value=SimpleNamespace(
                action_id="ob2qb:prompt_btn",
                data={
                    "prompt": "用户 {user_name} 触发了总结。",
                    "system_prompt": "角色：助手",
                },
            )
        )

        results = []
        async for item in MAIN_MODULE.Main.handle_button_action(plugin, event):
            results.append(item)

        self.assertEqual(len(results), 1)
        self.assertIn("这是大模型根据预设 Prompt", results[0].text)

    async def test_button_rps_game_returns_next_layout_chain(self):
        plugin = make_plugin(FakeReport(intercept=True))
        event = FakeEvent([], platform="qq_official")
        event.get_button_interaction = Mock(
            return_value=SimpleNamespace(
                action_id="ob2qb:rps_rock",
                data={"game": "rps", "choice": "rock", "replay_button": True},
            )
        )

        results = []
        async for item in MAIN_MODULE.Main.handle_button_action(plugin, event):
            results.append(item)

        self.assertEqual(len(results), 2)
        # 确认返回了包含链式组件的交互卡片（结果 + 再来一局按钮）
        self.assertTrue(hasattr(results[1], "chain"))


if __name__ == "__main__":
    unittest.main()