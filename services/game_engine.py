"""通用多轮交互与状态决策引擎。

不仅适用于各类互动游戏（猜拳、掷骰、答题、抽签等），
更原生支持客服导流、分级帮助菜单、问卷问答、审批工作流等多轮交互场景。
"""

from __future__ import annotations

import random
from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True, slots=True)
class InteractionDecision:
    """交互按钮决策结果。"""

    text: str = ""
    next_layout: dict[str, Any] | list[Any] | None = None
    use_llm: bool = False
    prompt: str = ""
    system_prompt: str = ""


class InteractiveDecisionEngine:
    """处理通用多轮交互、状态机流转与大模型决策。"""

    RPS_SYMBOLS = {
        "石头": "✊ 石头",
        "剪刀": "✌️ 剪刀",
        "布": "🖐️ 布",
        "rock": "✊ 石头",
        "scissors": "✌️ 剪刀",
        "paper": "🖐️ 布",
    }

    DICE_FACES = {1: "⚀", 2: "⚁", 3: "⚂", 4: "⚃", 5: "⚄", 6: "⚅"}

    def evaluate(
        self,
        action_id: str,
        data: dict[str, Any],
        *,
        user_name: str = "",
        user_id: str = "",
    ) -> InteractionDecision:
        """评估用户点击的上下文数据，返回标准交互决策。"""

        # 1. 优先检查是否需要触发大模型 Prompt（适用于客服、智能解答等）
        raw_prompt = data.get("prompt")
        if raw_prompt:
            context_vars = {
                "user_name": user_name or "用户",
                "user_id": user_id or "",
                "action_id": action_id,
                "label": str(data.get("label") or ""),
                "action": str(data.get("action") or action_id),
                "choice": str(data.get("choice") or data.get("selected") or ""),
                "value": str(data.get("value") or ""),
            }
            # 扩展传入的其他标量字段
            for k, v in data.items():
                if isinstance(v, (str, int, float, bool)) and k not in context_vars:
                    context_vars[k] = str(v)

            formatted_prompt = self._safe_format(str(raw_prompt), context_vars)
            return InteractionDecision(
                use_llm=True,
                prompt=formatted_prompt,
                system_prompt=str(data.get("system_prompt") or ""),
                next_layout=data.get("next_layout"),
            )

        # 2. 状态机卡片跳转（适用于多轮菜单、客服分支向导、多步审批、分支剧情等）
        next_layout = data.get("next_layout")
        if next_layout and not any(k in data for k in ("game", "rule")):
            msg = str(
                data.get("reply")
                or data.get("text")
                or f"已选择：{data.get('action') or action_id}"
            )
            return InteractionDecision(text=msg, next_layout=next_layout)

        # 3. 通用规则与多领域决策判定
        mode = str(data.get("game") or data.get("rule") or "").lower()

        # 3.1 猜拳对决
        if mode in {"rps", "caiquan", "guess"}:
            return self._handle_rps(data)

        # 3.2 掷骰子 / 拼点 / 随机数比对
        if mode in {"dice", "roll", "touzi"}:
            return self._handle_dice(data)

        # 3.3 答题闯关 / 表单比对 / 问答考核
        if mode in {"quiz", "question", "verify", "dati"}:
            return self._handle_quiz(data)

        # 3.4 随机分派 / 抽签 / 抽卡 / 奖池
        if mode in {"draw", "lottery", "pick", "assign", "chouka"}:
            return self._handle_draw(data)

        # 3.5 通用数值或条件比对（比大小、积分比对、满意度评价等）
        if mode in {"compare", "bidaxiao"}:
            return self._handle_compare(data)

        # 4. 常规文本反馈回退
        return InteractionDecision(text="")

    def _safe_format(self, template: str, context: dict[str, str]) -> str:
        """安全格式化模板，避免因未知占位符引发 KeyError。"""
        result = template
        for k, v in context.items():
            result = result.replace(f"{{{k}}}", v)
        return result

    def _handle_rps(self, data: dict[str, Any]) -> InteractionDecision:
        """处理猜拳（剪刀石头布）。"""
        user_choice = str(
            data.get("choice") or data.get("user_choice") or "石头"
        ).lower()
        user_opt = self.RPS_SYMBOLS.get(user_choice, "✊ 石头")
        bot_opt = random.choice(["✊ 石头", "✌️ 剪刀", "🖐️ 布"])

        if user_opt == bot_opt:
            result = f"🤝 平局！双方都出了 {user_opt}。"
        elif (
            (user_opt == "✊ 石头" and bot_opt == "✌️ 剪刀")
            or (user_opt == "✌️ 剪刀" and bot_opt == "🖐️ 布")
            or (user_opt == "🖐️ 布" and bot_opt == "✊ 石头")
        ):
            result = f"🎉 恭喜你赢了！你出了 {user_opt}，Bot 出了 {bot_opt}。"
        else:
            result = f"😢 很遗憾你输了！你出了 {user_opt}，Bot 出了 {bot_opt}。"

        next_layout = data.get("next_layout")
        if not next_layout and data.get("replay_button", True):
            next_layout = {
                "markdown": f"{result}\n\n想要再来一局吗？",
                "timeout": 60,
                "action_rows": [
                    {
                        "buttons": [
                            {
                                "id": "ob2qb:rps:rock",
                                "label": "✊ 石头",
                                "action": "callback",
                                "style": "primary",
                                "data": {"game": "rps", "choice": "rock"},
                            },
                            {
                                "id": "ob2qb:rps:scissors",
                                "label": "✌️ 剪刀",
                                "action": "callback",
                                "style": "success",
                                "data": {"game": "rps", "choice": "scissors"},
                            },
                            {
                                "id": "ob2qb:rps:paper",
                                "label": "🖐️ 布",
                                "action": "callback",
                                "style": "danger",
                                "data": {"game": "rps", "choice": "paper"},
                            },
                        ]
                    }
                ],
            }

        return InteractionDecision(text=result, next_layout=next_layout)

    def _handle_dice(self, data: dict[str, Any]) -> InteractionDecision:
        """处理掷骰子比大小对决。"""
        count = max(1, min(int(data.get("count", 1)), 6))
        sides = max(2, min(int(data.get("sides", 6)), 100))

        user_rolls = [random.randint(1, sides) for _ in range(count)]
        user_total = sum(user_rolls)

        bot_rolls = [random.randint(1, sides) for _ in range(count)]
        bot_total = sum(bot_rolls)

        if sides == 6:
            user_icons = "".join(self.DICE_FACES.get(r, str(r)) for r in user_rolls)
            bot_icons = "".join(self.DICE_FACES.get(r, str(r)) for r in bot_rolls)
        else:
            user_icons = str(user_rolls)
            bot_icons = str(bot_rolls)

        title = str(data.get("title") or f"掷骰子对决 ({count}D{sides})")
        lines = [
            f"🎲 **{title}**",
            f"你的点数：{user_icons}（总计 {user_total}）",
            f"Bot 点数：{bot_icons}（总计 {bot_total}）",
        ]

        if user_total > bot_total:
            lines.append("🏆 **恭喜你取得了胜利！**")
        elif user_total < bot_total:
            lines.append("😢 **Bot 点数更高，你输掉了这局！**")
        else:
            lines.append("🤝 **点数相同，平分秋色！**")

        return InteractionDecision(
            text="\n".join(lines), next_layout=data.get("next_layout")
        )

    def _handle_quiz(self, data: dict[str, Any]) -> InteractionDecision:
        """处理答题与答案校验（适用于培训、问卷、通关等）。"""
        selected = str(data.get("selected") or data.get("choice") or "").strip()
        correct = str(data.get("correct") or data.get("answer") or "").strip()
        explanation = str(data.get("explanation") or "")
        score = data.get("score")

        is_correct = (
            selected.upper() == correct.upper()
            if selected and correct
            else False
        )

        lines = []
        if is_correct:
            score_text = f"（+{score} 分）" if score is not None else ""
            lines.append(f"✅ **回答正确！{score_text}**")
            lines.append(f"你的选择：`{selected}`")
        else:
            lines.append("❌ **很遗憾，回答错误！**")
            lines.append(f"你的选择：`{selected}` | 正确项：`{correct}`")

        if explanation:
            lines.append(f"💡 **说明/解析**：{explanation}")

        return InteractionDecision(
            text="\n".join(lines), next_layout=data.get("next_layout")
        )

    def _handle_draw(self, data: dict[str, Any]) -> InteractionDecision:
        """处理随机抽取（适用于分配客服专员、抽卡、幸运抽奖等）。"""
        pool = data.get("pool") or data.get("items") or data.get("options")
        title = str(data.get("title") or "抽取结果")

        if not isinstance(pool, list) or not pool:
            picked = "默认项"
        else:
            picked = str(random.choice(pool))

        lines = [
            f"✨ **{title}**",
            f"结果：【{picked}】",
        ]
        return InteractionDecision(
            text="\n".join(lines), next_layout=data.get("next_layout")
        )

    def _handle_compare(self, data: dict[str, Any]) -> InteractionDecision:
        """处理通用数值/大小比较。"""
        user_val = float(data.get("user_val", 0))
        target_val = float(data.get("target_val", 0))
        title = str(data.get("title") or "比对结果")

        lines = [f"📊 **{title}**"]
        if user_val > target_val:
            lines.append(
                str(data.get("win_reply") or f"数值更高：{user_val} > {target_val}")
            )
        elif user_val < target_val:
            lines.append(
                str(data.get("lose_reply") or f"数值较低：{user_val} < {target_val}")
            )
        else:
            lines.append(
                str(data.get("tie_reply") or f"数值相等：{user_val} == {target_val}")
            )

        return InteractionDecision(
            text="\n".join(lines), next_layout=data.get("next_layout")
        )


# 保持向后兼容别名
InteractiveGameEngine = InteractiveDecisionEngine