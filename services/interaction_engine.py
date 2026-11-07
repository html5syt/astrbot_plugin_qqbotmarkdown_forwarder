"""通用多轮交互决策与流转引擎（Universal Interaction Engine）。

完全解耦、无场景绑定的交互处理中枢。将按钮回调归一化为四大通用通道：
1. 大模型动态驱动通道（Prompt-driven LLM Generation）
2. 状态机卡片流转通道（Declarative State Machine & Next Layout）
3. 通用规则与判定通道（Generalized Rule & Decision Matching）
4. 即时模板反馈通道（Context-aware Template Reply）

无论应用于客服分流菜单、帮助导航、问卷调研、审批流还是各类互动对决游戏，
底层处理逻辑完全统一、高度泛化。
"""

from __future__ import annotations

import random
from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True, slots=True)
class InteractionDecision:
    """交互决策的标准结果对象。"""

    text: str = ""
    next_layout: dict[str, Any] | list[Any] | None = None
    use_llm: bool = False
    prompt: str = ""
    system_prompt: str = ""


class InteractionEngine:
    """通用多轮交互决策引擎。"""

    # 预置通用零和对决规则表（用于猜拳等泛化对称比对）
    RPS_MAP = {
        "rock": "✊ 石头",
        "石头": "✊ 石头",
        "scissors": "✌️ 剪刀",
        "剪刀": "✌️ 剪刀",
        "paper": "🖐️ 布",
        "布": "🖐️ 布",
    }
    DICE_ICONS = {1: "⚀", 2: "⚁", 3: "⚂", 4: "⚃", 5: "⚄", 6: "⚅"}

    def evaluate(
        self,
        action_id: str,
        data: dict[str, Any],
        *,
        user_name: str = "",
        user_id: str = "",
    ) -> InteractionDecision:
        """多轮交互通用决策管线。按优先级进行多通道分流评估。"""

        # Stage 1: 归一化提取上下文变量池
        context = self._build_context(action_id, data, user_name, user_id)

        # Stage 2: 通道 1 - 声明式大模型 Prompt 动态接管通道
        raw_prompt = data.get("prompt")
        if raw_prompt:
            formatted_prompt = self._safe_format(str(raw_prompt), context)
            return InteractionDecision(
                use_llm=True,
                prompt=formatted_prompt,
                system_prompt=str(data.get("system_prompt") or ""),
                next_layout=data.get("next_layout"),
            )

        # Stage 3: 通道 2 - 声明式多轮卡片状态流转通道（next_layout）
        next_layout = data.get("next_layout")
        has_specific_rule = any(
            k in data for k in ("rule", "game", "verify", "compare", "pool")
        )
        if next_layout and not has_specific_rule:
            msg = str(
                data.get("reply")
                or data.get("text")
                or f"已处理操作：{context.get('action')}"
            )
            formatted_msg = self._safe_format(msg, context)
            return InteractionDecision(text=formatted_msg, next_layout=next_layout)

        # Stage 4: 通道 3 - 通用规则判定通道（零和博弈、比大小、答题校验、随机池）
        rule_decision = self._evaluate_rule_channel(action_id, data, context)
        if rule_decision is not None:
            return rule_decision

        # Stage 5: 通道 4 - 即时模板反馈通道
        reply_template = data.get("reply") or data.get("text")
        if reply_template:
            formatted_reply = self._safe_format(str(reply_template), context)
            return InteractionDecision(
                text=formatted_reply, next_layout=next_layout
            )

        # Stage 6: 通道 5 - 通用兜底（无确定行为时自动构造上下文 Prompt 唤醒 Bot）
        fallback_prompt = (
            f"用户 {context.get('user_name')} 在对话中点击了交互按钮"
            f"【{context.get('label') or action_id}】"
            f"（操作标识: {action_id}，携带数据: {data or '无'}）。"
            "请作为智能助理，根据上下文做出自然、契合情境的回应。"
        )
        return InteractionDecision(
            use_llm=True,
            prompt=fallback_prompt,
            next_layout=next_layout,
        )

    def _build_context(
        self,
        action_id: str,
        data: dict[str, Any],
        user_name: str,
        user_id: str,
    ) -> dict[str, str]:
        """构建平铺的上下文参数池，供模板与 Prompt 自由插值引用。"""
        context: dict[str, str] = {
            "user_name": user_name or "用户",
            "user_id": user_id or "",
            "action_id": action_id,
            "action": str(data.get("action") or action_id),
            "label": str(data.get("label") or data.get("text") or ""),
            "choice": str(data.get("choice") or data.get("selected") or ""),
            "value": str(data.get("value") or ""),
        }
        for k, v in data.items():
            if isinstance(v, (str, int, float, bool)) and k not in context:
                context[k] = str(v)
        return context

    def _safe_format(self, template: str, context: dict[str, str]) -> str:
        """安全模板变量替换，自动替换 {var} 占位符。"""
        result = template
        for k, v in context.items():
            result = result.replace(f"{{{k}}}", v)
        return result

    def _evaluate_rule_channel(
        self, action_id: str, data: dict[str, Any], context: dict[str, str]
    ) -> InteractionDecision | None:
        """通用规则计算器：将猜拳、掷骰、答题、抽签等归一化为规则运算。"""
        mode = str(data.get("rule") or data.get("game") or "").lower()

        # 3.1 零和对称博弈规则（猜拳/RPS，支持显式规则或 action_id 智能模糊识别）
        rps_choice = self._extract_rps_choice(action_id, data)
        if rps_choice or mode in {"rps", "caiquan", "guess", "match"}:
            return self._handle_rps_rule(data, rps_choice)

        # 3.2 离散随机/掷骰规则
        if mode in {"dice", "roll", "touzi"} or "dice" in action_id.lower():
            return self._handle_dice_rule(data)

        # 3.3 条件等值校验规则（答题自测、表单确认、验证比对）
        if mode in {"verify", "quiz", "question", "check", "dati"}:
            return self._handle_verify_rule(data, context)

        # 3.4 随机池抽取规则（分派专员、随机分支、抽签抽奖）
        if mode in {"pick", "draw", "lottery", "random", "assign", "chouka"}:
            return self._handle_pick_rule(data, context)

        # 3.5 数值比较规则
        if mode in {"compare", "bidaxiao"}:
            return self._handle_compare_rule(data)

        return None

    def _extract_rps_choice(
        self, action_id: str, data: dict[str, Any]
    ) -> str | None:
        """从 action_id 或 data 中模糊匹配对决手势（石头/剪刀/布）。"""
        candidates = [
            str(data.get("choice") or ""),
            str(data.get("user_choice") or ""),
            str(data.get("action") or ""),
            str(data.get("data") or ""),
            str(data.get("command") or ""),
            str(data.get("game") or ""),
            action_id,
        ]
        for c in candidates:
            low = c.lower()
            if any(k in low for k in ("rock", "石头", "shitou", "👊", "✊")):
                return "rock"
            if any(k in low for k in ("scissor", "剪刀", "jiandao", "✌", "✂")):
                return "scissors"
            if any(k in low for k in ("paper", "布", "bu", "🖐", "✋")):
                return "paper"
        return None

    def _handle_rps_rule(
        self, data: dict[str, Any], choice_key: str | None
    ) -> InteractionDecision:
        user_choice = str(
            choice_key or data.get("choice") or data.get("user_choice") or "石头"
        ).lower()
        user_opt = self.RPS_MAP.get(user_choice, "✊ 石头")
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

        # 自动附带再来一局的连续交互卡片
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

    def _handle_dice_rule(self, data: dict[str, Any]) -> InteractionDecision:
        count = max(1, min(int(data.get("count", 1)), 6))
        sides = max(2, min(int(data.get("sides", 6)), 100))

        u_rolls = [random.randint(1, sides) for _ in range(count)]
        u_tot = sum(u_rolls)
        b_rolls = [random.randint(1, sides) for _ in range(count)]
        b_tot = sum(b_rolls)

        if sides == 6:
            u_str = "".join(self.DICE_ICONS.get(r, str(r)) for r in u_rolls)
            b_str = "".join(self.DICE_ICONS.get(r, str(r)) for r in b_rolls)
        else:
            u_str, b_str = str(u_rolls), str(b_rolls)

        title = str(data.get("title") or f"掷骰对决 ({count}D{sides})")
        lines = [
            f"🎲 **{title}**",
            f"你的点数：{u_str}（总计 {u_tot}）",
            f"Bot 点数：{b_str}（总计 {b_tot}）",
        ]
        if u_tot > b_tot:
            lines.append("🏆 **恭喜你取得了胜利！**")
        elif u_tot < b_tot:
            lines.append("😢 **Bot 点数更高，你输掉了这局！**")
        else:
            lines.append("🤝 **点数相同，平分秋色！**")

        return InteractionDecision(
            text="\n".join(lines), next_layout=data.get("next_layout")
        )

    def _handle_verify_rule(
        self, data: dict[str, Any], context: dict[str, str]
    ) -> InteractionDecision:
        selected = str(data.get("selected") or data.get("choice") or "").strip()
        correct = str(data.get("correct") or data.get("answer") or "").strip()
        explanation = str(data.get("explanation") or "")
        score = data.get("score")

        is_ok = selected.upper() == correct.upper() if selected and correct else False

        lines = []
        if is_ok:
            score_txt = f"（+{score} 分）" if score is not None else ""
            lines.append(f"✅ **校验/回答正确！{score_txt}**")
            lines.append(f"你的选择：`{selected}`")
        else:
            lines.append("❌ **校验/回答未通过！**")
            lines.append(f"你的选择：`{selected}` | 预期项：`{correct}`")

        if explanation:
            lines.append(f"💡 **解析说明**：{explanation}")

        return InteractionDecision(
            text="\n".join(lines), next_layout=data.get("next_layout")
        )

    def _handle_pick_rule(
        self, data: dict[str, Any], context: dict[str, str]
    ) -> InteractionDecision:
        pool = data.get("pool") or data.get("items") or data.get("options")
        title = str(data.get("title") or "抽取/分派结果")

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

    def _handle_compare_rule(self, data: dict[str, Any]) -> InteractionDecision:
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


# 向后兼容导出
InteractionDecisionEngine = InteractionEngine
InteractiveDecisionEngine = InteractionEngine
InteractiveGameEngine = InteractionEngine