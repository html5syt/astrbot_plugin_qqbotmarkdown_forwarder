import unittest

from services.game_engine import (
    InteractiveDecisionEngine,
    InteractiveGameEngine,
)


class InteractiveGameEngineTests(unittest.TestCase):
    def setUp(self):
        self.engine = InteractiveDecisionEngine()

    def test_prompt_evaluation_with_placeholder_formatting(self):
        data = {
            "prompt": (
                "用户 {user_name} (ID: {user_id}) 咨询业务【{service}】，"
                "问题：{issue}。"
            ),
            "service": "退款售后",
            "issue": "未收到商品",
            "system_prompt": "你是一名资深电商客服专家",
        }
        decision = self.engine.evaluate(
            "ob2qb:cs_refund", data, user_name="李四", user_id="888666"
        )

        self.assertTrue(decision.use_llm)
        self.assertIn("用户 李四 (ID: 888666) 咨询业务【退款售后】", decision.prompt)
        self.assertIn("未收到商品", decision.prompt)
        self.assertEqual(decision.system_prompt, "你是一名资深电商客服专家")

    def test_customer_service_submenu_navigation(self):
        submenu_card = {
            "markdown": "## 售后服务中心\n请选择您需要办理的业务：",
            "action_rows": [
                {
                    "buttons": [
                        {
                            "label": "申请退款",
                            "action": "callback",
                            "data": {"type": "refund"},
                        },
                        {
                            "label": "换货服务",
                            "action": "callback",
                            "data": {"type": "exchange"},
                        },
                    ]
                }
            ],
        }
        data = {
            "action": "goto_aftersales",
            "reply": "正在为您跳转至售后服务中心...",
            "next_layout": submenu_card,
        }
        decision = self.engine.evaluate("btn_cs_aftersales", data)

        self.assertFalse(decision.use_llm)
        self.assertEqual(decision.text, "正在为您跳转至售后服务中心...")
        self.assertEqual(decision.next_layout, submenu_card)

    def test_rps_game_determination_and_replay_layout(self):
        data = {"game": "rps", "choice": "rock", "replay_button": True}
        decision = self.engine.evaluate("btn_rock", data)

        self.assertFalse(decision.use_llm)
        self.assertTrue(
            "平局" in decision.text
            or "赢了" in decision.text
            or "输了" in decision.text
        )
        self.assertIsNotNone(decision.next_layout)
        self.assertIn("想要再来一局吗？", decision.next_layout["markdown"])

    def test_rps_fuzzy_detection_by_action_id(self):
        # 兼容 Bot 未写明 game="rps"，只传了 rps_rock 等 ID 的场景
        d1 = self.engine.evaluate("rps_rock", {})
        expected1 = "双方" if "平局" in d1.text else "你出了 ✊ 石头"
        self.assertIn(expected1, d1.text)
        self.assertIsNotNone(d1.next_layout)

        d2 = self.engine.evaluate("rps_scissors", {})
        expected2 = "双方" if "平局" in d2.text else "你出了 ✌️ 剪刀"
        self.assertIn(expected2, d2.text)

        d3 = self.engine.evaluate("rps_paper", {})
        expected3 = "双方" if "平局" in d3.text else "你出了 🖐️ 布"
        self.assertIn(expected3, d3.text)

        d4 = self.engine.evaluate("btn_custom", {"data": "rps:rock"})
        expected4 = "双方" if "平局" in d4.text else "你出了 ✊ 石头"
        self.assertIn(expected4, d4.text)

    def test_dice_game_determination(self):
        data = {"game": "dice", "count": 2, "sides": 6}
        decision = self.engine.evaluate("btn_dice", data)

        self.assertFalse(decision.use_llm)
        self.assertIn("🎲 **掷骰对决", decision.text)
        self.assertIn("你的点数：", decision.text)
        self.assertIn("Bot 点数：", decision.text)

    def test_quiz_game_correct_and_incorrect(self):
        data_correct = {
            "rule": "quiz",
            "selected": "B",
            "correct": "B",
            "explanation": "光速约为 30 万公里每秒。",
            "score": 10,
        }
        dec1 = self.engine.evaluate("btn_q1", data_correct)
        self.assertIn("✅ **校验/回答正确！", dec1.text)
        self.assertIn("+10 分", dec1.text)

        data_wrong = {
            "rule": "verify",
            "selected": "A",
            "correct": "C",
            "explanation": "正确答案应为选项 C。",
        }
        dec2 = self.engine.evaluate("btn_q2", data_wrong)
        self.assertIn("❌ **校验/回答未通过！", dec2.text)
        self.assertIn("预期项：`C`", dec2.text)

    def test_general_comparison_rule(self):
        data_win = {
            "rule": "compare",
            "user_val": 95,
            "target_val": 60,
            "win_reply": "恭喜通过考核！成绩达到优秀标准。",
        }
        decision = self.engine.evaluate("btn_eval", data_win)
        self.assertIn("恭喜通过考核！", decision.text)

    def test_backward_compatibility_alias(self):
        self.assertIs(InteractiveGameEngine, InteractiveDecisionEngine)


if __name__ == "__main__":
    unittest.main()