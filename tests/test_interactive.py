import json
import unittest

from services.interactive import (
    ButtonLifecycleManager,
    InteractivePayloadError,
    build_qq_keyboard_payload,
    parse_interactive_payload,
)


class InteractiveBuilderTests(unittest.TestCase):
    def test_parse_structured_object(self):
        payload_data = {
            "markdown": "## 标题\n这是正文内容，包含 $E=mc^2$。",
            "images": ["https://example.com/pic.png"],
            "action_rows": [
                {
                    "action_timeout": 60,
                    "fallback_text": "降级文本",
                    "buttons": [
                        {
                            "id": "btn_cb",
                            "label": "确认",
                            "action": "callback",
                            "style": "primary",
                            "data": {"order_id": 123},
                            "reply": "已确认订单！",
                        },
                        {
                            "id": "btn_link",
                            "label": "官网",
                            "action": "url",
                            "url": "https://example.com",
                        },
                    ],
                }
            ],
        }

        payload = parse_interactive_payload(json.dumps(payload_data))

        self.assertIn("## 标题", payload.full_markdown_text)
        self.assertEqual(len(payload.images), 1)
        self.assertEqual(payload.images[0].url, "https://example.com/pic.png")
        self.assertEqual(len(payload.action_rows), 1)

        row = payload.action_rows[0]
        self.assertEqual(row.action_timeout, 60)
        self.assertEqual(row.fallback_text, "降级文本")
        self.assertEqual(len(row.buttons), 2)

        cb_btn = row.buttons[0]
        self.assertEqual(cb_btn.id, "btn_cb")
        self.assertEqual(cb_btn.action, "callback")
        self.assertEqual(cb_btn.data, {"order_id": 123})
        self.assertEqual(cb_btn.reply, "已确认订单！")

        url_btn = row.buttons[1]
        self.assertEqual(url_btn.id, "btn_link")
        self.assertEqual(url_btn.action, "url")
        self.assertEqual(url_btn.url, "https://example.com")

    def test_top_level_timeout_and_alias_inheritance(self):
        payload_data = {
            "markdown": "测试继承",
            "timeout": 90,
            "action_rows": [
                {
                    "buttons": [{"label": "继承90秒", "action": "callback"}]
                },
                {
                    "expire_seconds": 30,
                    "buttons": [{"label": "自定义30秒", "action": "callback"}]
                },
            ],
        }
        payload = parse_interactive_payload(payload_data)
        self.assertEqual(payload.action_rows[0].action_timeout, 90)
        self.assertEqual(payload.action_rows[1].action_timeout, 30)

    def test_parse_sequential_segments_list(self):
        segments = [
            {"type": "markdown", "content": "前言介绍"},
            {"type": "image", "url": "https://example.com/pic2.png"},
            {
                "type": "action_row",
                "buttons": [
                    {
                        "label": "点我",
                        "action": "callback",
                        "data": {"cmd": "help"},
                    }
                ],
            },
        ]

        payload = parse_interactive_payload(segments)

        self.assertEqual(len(payload.segments), 3)
        self.assertEqual(payload.segments[0].content, "前言介绍")
        self.assertEqual(payload.images[0].url, "https://example.com/pic2.png")
        self.assertTrue(payload.action_rows[0].buttons[0].id.startswith("ob2qb:btn_"))

    def test_markdown_code_fence_stripping(self):
        raw = "```json\n{\"markdown\": \"正文\"}\n```"
        payload = parse_interactive_payload(raw)
        self.assertEqual(payload.full_markdown_text, "正文")

    def test_empty_payload_raises_error(self):
        with self.assertRaises(InteractivePayloadError):
            parse_interactive_payload({})

    def test_build_qq_keyboard_payload(self):
        payload_data = {
            "markdown": "测试",
            "action_rows": [
                {
                    "buttons": [
                        {
                            "id": "b1",
                            "label": "跳转",
                            "action": "url",
                            "url": "https://astrbot.app",
                        },
                        {
                            "id": "b2",
                            "label": "回调",
                            "action": "callback",
                            "data": {"key": "val"},
                            "style": "danger",
                            "reply": "已收到回调",
                        },
                    ]
                }
            ],
        }
        payload = parse_interactive_payload(payload_data)
        kb = build_qq_keyboard_payload(payload)

        self.assertIsNotNone(kb)
        rows = kb["content"]["rows"]
        self.assertEqual(len(rows), 1)
        buttons = rows[0]["buttons"]
        self.assertEqual(len(buttons), 2)

        btn1 = buttons[0]
        self.assertEqual(btn1["action"]["type"], 0)
        self.assertEqual(btn1["action"]["data"], "https://astrbot.app")

        btn2 = buttons[1]
        self.assertEqual(btn2["action"]["type"], 2)
        self.assertEqual(btn2["render_data"]["style"], 2)  # danger
        parsed_data = json.loads(btn2["action"]["data"])
        self.assertEqual(parsed_data["key"], "val")
        self.assertEqual(parsed_data["reply"], "已收到回调")

    def test_lifecycle_manager_debounce_and_reply(self):
        manager = ButtonLifecycleManager()

        self.assertTrue(manager.should_process_click("click_1", debounce_seconds=1.0))
        self.assertFalse(manager.should_process_click("click_1", debounce_seconds=1.0))

        resp1 = manager.resolve_callback_response("btn_1", {"reply": "成功"})
        self.assertEqual(resp1, "成功")

        resp2 = manager.resolve_callback_response("btn_2", {"action": "刷新数据"})
        self.assertEqual(resp2, "已处理操作：刷新数据")

        resp3 = manager.resolve_callback_response("ob2qb:test", {})
        self.assertEqual(resp3, "已触发操作：ob2qb:test")

        resp4 = manager.resolve_callback_response("btn_4", {"command": "/help"})
        self.assertEqual(resp4, "执行指令：/help")


if __name__ == "__main__":
    unittest.main()