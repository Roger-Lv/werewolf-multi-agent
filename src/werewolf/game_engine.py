"""核心异步游戏引擎——状态机管理 + 并发控制 + ActionProvider 抽象"""

import asyncio
import json
import logging
import random
from collections import Counter
from typing import Any

from .llm_client import LLMClient, call_concurrent
from .models import (
    GameState, Player, Role, Phase, LifeStatus, DeathCause,
    WitchPotions, NightResult, VoteResult, Speech, ActionProvider, PlayerType,
)
from .prompts import (
    build_gm_system_prompt, build_gm_night_messages, build_gm_vote_messages,
    build_player_system_prompt, build_player_night_messages,
    build_player_speech_messages, build_player_vote_messages,
    build_summary_messages, build_seer_private_info, build_witch_private_info,
)

logger = logging.getLogger("werewolf.engine")


class LLMActionProvider:
    """LLM 行动提供者——通过 API 调用获取行动"""

    def __init__(self, client: LLMClient):
        self.client = client

    async def get_night_action(
        self, player: Player, game_state: GameState, system_prompt: str,
        summary: str | None, private_info: str,
    ) -> dict:
        messages = build_player_night_messages(
            player, game_state, system_prompt, summary, private_info,
        )
        return await self.client.call_json(messages, 0.7)

    async def get_speech(
        self, player: Player, game_state: GameState, system_prompt: str,
        previous_speeches: list[str], summary: str | None, gm_announcement: str,
        private_memories: list[str] | None = None,
    ) -> dict:
        messages = build_player_speech_messages(
            player, game_state, system_prompt, previous_speeches, summary, gm_announcement, private_memories,
        )
        return await self.client.call_json(messages, 0.8)

    async def get_vote(
        self, player: Player, game_state: GameState, system_prompt: str,
        all_speeches: list[str], summary: str | None, gm_announcement: str,
        private_memories: list[str] | None = None,
    ) -> dict:
        messages = build_player_vote_messages(
            player, game_state, system_prompt, all_speeches, summary, gm_announcement, private_memories,
        )
        return await self.client.call_json(messages, 0.6)

    async def get_hunter_shoot(
        self, player: Player, game_state: GameState, system_prompt: str,
        summary: str | None, prompt: str,
    ) -> dict:
        messages = build_player_night_messages(
            player, game_state, system_prompt, summary, prompt,
        )
        return await self.client.call_json(messages, 0.7)

    async def close(self):
        await self.client.close()


class GameEngine:
    """狼人杀异步游戏引擎"""

    def __init__(
        self,
        players_cfg: dict[int, dict],
        roles: list[str],
        gm_cfg: dict,
        summarizer_cfg: dict,
        rules: dict,
        summary_threshold: int = 15,
        human_providers: dict[int, ActionProvider] | None = None,
    ):
        # 规则
        self.witch_can_save_self_first_night = rules.get("witch_can_save_self_first_night", True)
        self.tie_vote_rule = rules.get("tie_vote_rule", "random")
        self.werewolf_disagree_rule = rules.get("werewolf_disagree_rule", "random")
        self.hunter_can_shoot_on_poison = rules.get("hunter_can_shoot_on_witch_poison", True)
        self.summary_threshold = summary_threshold

        # 初始化玩家
        self.state = GameState()
        self.providers: dict[int, ActionProvider | None] = {}

        for i, role_str in enumerate(roles, 1):
            cfg = players_cfg[i]
            player_type = PlayerType(cfg.get("type", "llm"))
            player = Player(
                id=i,
                role=Role(role_str),
                personality=cfg.get("personality", "neutral"),
                player_type=player_type,
            )
            self.state.players.append(player)
            self.state.private_memories[i] = []

            # 狼人同伴信息写入私密记忆（确保在发言/投票 prompt 的最近位置再次强调）
            if player.role == Role.WEREWOLF:
                peers = [p.id for p in self.state.players if p.role == Role.WEREWOLF and p.id != i]
                if peers:
                    self.state.private_memories[i].append(
                        f"你是狼人，你的同伴是 {', '.join(str(pid) for pid in peers)}号。"
                    )

            # 设置 ActionProvider
            if player_type == PlayerType.HUMAN and human_providers and i in human_providers:
                self.providers[i] = human_providers[i]
            elif player_type == PlayerType.LLM:
                llm_client = LLMClient(
                    base_url=cfg["base_url"],
                    api_key=cfg["api_key"],
                    model=cfg["model"],
                )
                self.providers[i] = LLMActionProvider(llm_client)
            else:
                logger.warning(f"Player {i} is human but no HumanActionProvider provided")
                self.providers[i] = None

        # GM 客户端
        self.gm_client = LLMClient(
            base_url=gm_cfg["base_url"],
            api_key=gm_cfg["api_key"],
            model=gm_cfg["model"],
        )

        # 摘要客户端
        self.summarizer_client = LLMClient(
            base_url=summarizer_cfg["base_url"],
            api_key=summarizer_cfg["api_key"],
            model=summarizer_cfg["model"],
        )

        # GM prompt
        self.gm_system_prompt = build_gm_system_prompt(
            witch_can_save_self_first_night=self.witch_can_save_self_first_night,
            tie_rule=self.tie_vote_rule,
        )

        # Player system prompts
        self.player_system_prompts: dict[int, str] = {}
        for player in self.state.players:
            werewolf_peers = None
            if player.role == Role.WEREWOLF:
                werewolf_peers = [
                    p.id for p in self.state.players
                    if p.role == Role.WEREWOLF and p.id != player.id
                ]
            self.player_system_prompts[player.id] = build_player_system_prompt(
                player,
                werewolf_peers=werewolf_peers,
                witch_self_save_rule=(
                    "首夜可以自救" if self.witch_can_save_self_first_night else "首夜不能自救"
                ),
            )

        self.seer_check_results: list[dict] = []
        self.raw_history: list[str] = []
        self.current_summary: str | None = None

    # ─── 辅助：发送进度事件 ───

    async def _emit_progress(self, event_callback: Any | None, msg: str, detail: str = ""):
        """发送进度通知到前端"""
        logger.info(f"[PROGRESS] {msg} {detail}")
        if event_callback:
            await event_callback("progress", {
                "message": msg,
                "detail": detail,
            }, self.state)

    # ─── 主循环 ───

    async def run_game(self, event_callback: Any = None) -> dict:
        """运行完整游戏，返回胜方结果 dict"""
        while True:
            result = self.state.check_game_over()
            if result:
                self.state.phase = Phase.GAME_OVER
                if event_callback:
                    await event_callback("game_over", result, self.state)
                return result

            await self._run_night(event_callback)
            result = self.state.check_game_over()
            if result:
                self.state.phase = Phase.GAME_OVER
                if event_callback:
                    await event_callback("game_over", result, self.state)
                return result

            await self._run_day_speech(event_callback)
            await self._run_day_vote(event_callback)
            result = self.state.check_game_over()
            if result:
                self.state.phase = Phase.GAME_OVER
                if event_callback:
                    await event_callback("game_over", result, self.state)
                return result

            self.state.round_number += 1

    # ─── 夜晚阶段 ───

    async def _run_night(self, event_callback: Any = None):
        """夜晚阶段：并发获取狼人+预言家行动，然后串行获取女巫行动"""
        self.state.phase = Phase.NIGHT
        await self._emit_progress(event_callback, f"第 {self.state.round_number} 夜 — 夜幕降临")

        alive = self.state.alive_players
        alive_ids = [p.id for p in alive]

        werewolf_ids = [p.id for p in self.state.alive_werewolves]
        seer = next((p for p in alive if p.role == Role.SEER), None)
        witch = next((p for p in alive if p.role == Role.WITCH), None)
        hunter = next((p for p in alive if p.role == Role.HUNTER), None)

        # 列出所有活跃角色的行动清单
        active_roles = []
        for ww_id in werewolf_ids:
            p = self.state.get_player(ww_id)
            active_roles.append(f"🐺 {ww_id}号狼人({p.personality})")
        if seer:
            active_roles.append(f"🔮 {seer.id}号预言家({seer.personality})")
        if witch:
            active_roles.append(f"🧙 {witch.id}号女巫({witch.personality})")
        if hunter:
            active_roles.append(f"🏹 {hunter.id}号猎人(待命)")
        for p in alive:
            if p.role == Role.VILLAGER:
                active_roles.append(f"👤 {p.id}号村民(睡觉)")
        await self._emit_progress(event_callback, "夜晚行动清单", " | ".join(active_roles))

        summary = await self._get_summary()

        # ── 第一步：并发获取狼人和预言家行动 ──
        await self._emit_progress(event_callback, "狼人与预言家并发行动中...")

        night_tasks: list[tuple[ActionProvider, Player, str, str | None, str]] = []

        for ww_id in werewolf_ids:
            night_tasks.append((
                self.providers[ww_id],
                self.state.get_player(ww_id),
                self.player_system_prompts[ww_id],
                summary,
                "",
            ))

        if seer:
            private_info = build_seer_private_info(self.seer_check_results)
            night_tasks.append((
                self.providers[seer.id],
                seer,
                self.player_system_prompts[seer.id],
                summary,
                private_info,
            ))

        # 并发执行
        results = await asyncio.gather(*[
            provider.get_night_action(player, self.state, sp, s, pi)
            for provider, player, sp, s, pi in night_tasks
        ], return_exceptions=True)

        # 解析结果
        werewolf_targets: list[int] = []
        task_idx = 0

        for ww_id in werewolf_ids:
            result = results[task_idx]
            if isinstance(result, Exception):
                logger.error(f"Werewolf {ww_id} action failed: {result}")
                await self._emit_progress(event_callback, f"❌ {ww_id}号狼人行动失败，随机选目标", str(result)[:80])
                valid_targets = [p.id for p in alive if p.role != Role.WEREWOLF]
                if valid_targets:
                    werewolf_targets.append(random.choice(valid_targets))
            else:
                target = result.get("target_id")
                thinking = result.get("thinking", "")
                await self._emit_progress(event_callback, f"🐺 {ww_id}号狼人选择杀人目标: {target}号", f"思考: {thinking}")
                if target and target in alive_ids and target not in werewolf_ids:
                    werewolf_targets.append(target)
                    self.state.private_memories[ww_id].append(
                        f"第{self.state.round_number}夜: 你选择杀 {target}号"
                    )
                else:
                    valid_targets = [p.id for p in alive if p.role != Role.WEREWOLF]
                    if valid_targets:
                        werewolf_targets.append(random.choice(valid_targets))
            task_idx += 1

        # 预言家
        seer_target = None
        if seer:
            result = results[task_idx]
            if isinstance(result, Exception):
                logger.error(f"Seer action failed: {result}")
                await self._emit_progress(event_callback, f"❌ {seer.id}号预言家行动失败", str(result)[:80])
            else:
                target = result.get("target_id")
                thinking = result.get("thinking", "")
                await self._emit_progress(event_callback, f"🔮 {seer.id}号预言家查验 {target}号", f"思考: {thinking}")
                if target and target in alive_ids:
                    seer_target = target
                    is_werewolf = self.state.get_player(target).role == Role.WEREWOLF
                    self.seer_check_results.append({
                        "target_id": target, "is_werewolf": is_werewolf,
                    })
                    self.state.private_memories[seer.id].append(
                        f"第{self.state.round_number}夜: 你查验 {target}号，结果为{'狼人' if is_werewolf else '好人'}"
                    )
                    result_str = "狼人 🐺" if is_werewolf else "好人 ✅"
                    await self._emit_progress(event_callback, f"🔮 查验结果: {target}号 = {result_str}")
                    if event_callback:
                        await event_callback("seer_check", {
                            "target": target, "is_werewolf": is_werewolf,
                            "seer_id": seer.id,
                        }, self.state)

        # 狼人目标裁决
        if werewolf_targets:
            final_werewolf_target = self._resolve_werewolf_targets(werewolf_targets)
            await self._emit_progress(event_callback, f"🐺 狼人最终目标: {final_werewolf_target}号", f"各狼人选择: {', '.join(str(t) for t in werewolf_targets)}号")
        else:
            valid_targets = [p.id for p in alive if p.role != Role.WEREWOLF]
            final_werewolf_target = random.choice(valid_targets) if valid_targets else None
            await self._emit_progress(event_callback, f"🐺 狼人最终目标: {final_werewolf_target}号(随机)")

        # ── 第二步：女巫行动 ──
        witch_result = None
        if witch:
            save_status = "有解药" if self.state.witch_potions.has_save_potion else "无解药"
            poison_status = "有毒药" if self.state.witch_potions.has_poison_potion else "无毒药"
            await self._emit_progress(event_callback, f"🧙 {witch.id}号女巫行动中...", f"{save_status} · {poison_status} | 被杀: {final_werewolf_target}号")
            witch_private = build_witch_private_info(
                killed_by_werewolf=final_werewolf_target,
                has_save=self.state.witch_potions.has_save_potion,
                has_poison=self.state.witch_potions.has_poison_potion,
                first_night=(self.state.round_number == 1),
                witch_can_save_self=self.witch_can_save_self_first_night,
            )
            try:
                witch_result = await self.providers[witch.id].get_night_action(
                    witch, self.state, self.player_system_prompts[witch.id],
                    summary, witch_private,
                )
                use_save = witch_result.get("use_save", False)
                use_poison = witch_result.get("use_poison", False)
                thinking = witch_result.get("thinking", "")
                action_desc = []
                if use_save:
                    save_id = witch_result.get("save_target_id", final_werewolf_target)
                    action_desc.append(f"解药救 {save_id}号")
                if use_poison:
                    poison_id = witch_result.get("poison_target_id")
                    action_desc.append(f"毒药杀 {poison_id}号")
                if not action_desc:
                    action_desc.append("不使用药品")
                await self._emit_progress(event_callback, f"🧙 {witch.id}号女巫: {', '.join(action_desc)}", f"思考: {thinking}")
            except Exception as e:
                logger.error(f"Witch action failed: {e}")
                await self._emit_progress(event_callback, f"❌ {witch.id}号女巫行动失败", str(e)[:80])
                witch_result = {"error": str(e)}

        # ── 第三步：GM 裁决 ──
        await self._emit_progress(event_callback, "⚖️ GM 裁决夜晚结果...")
        witch_action_dict = None
        if witch_result and "error" not in witch_result:
            witch_action_dict = witch_result

        gm_messages = build_gm_night_messages(
            self.state, self.gm_system_prompt,
            werewolf_targets=werewolf_targets,
            seer_target=seer_target,
            witch_action=witch_action_dict,
            hunter_triggered=False,
        )

        try:
            gm_result = await self.gm_client.call_json(gm_messages, 0.3)
            killed = gm_result.get("killed_by_werewolf")
            saved = gm_result.get("saved_by_witch")
            poisoned = gm_result.get("killed_by_poison")
            summary_parts = []
            if killed and killed != saved:
                summary_parts.append(f"🐺狼人杀 {killed}号")
            if saved:
                summary_parts.append(f"🧙女巫救 {saved}号")
            if poisoned:
                summary_parts.append(f"🧙女巫毒 {poisoned}号")
            if not summary_parts:
                summary_parts.append("平安夜")
            await self._emit_progress(event_callback, f"⚖️ GM裁决完成: {', '.join(summary_parts)}", f"公告: {gm_result.get('announcement', '')[:80]}")
        except Exception as e:
            logger.error(f"GM night ruling failed: {e}")
            await self._emit_progress(event_callback, "⚠️ GM API失败，使用兜底逻辑裁决", str(e)[:80])
            gm_result = self._fallback_night_ruling(
                final_werewolf_target, witch_result, seer_target
            )

        await self._apply_night_result(gm_result, event_callback)

    async def _apply_night_result(self, gm_result: dict, event_callback: Any = None):
        """应用夜晚裁决结果"""
        killed_by_ww = gm_result.get("killed_by_werewolf")
        saved = gm_result.get("saved_by_witch")
        poisoned = gm_result.get("killed_by_poison")
        announcement = gm_result.get("announcement", "")

        witch = next((p for p in self.state.players if p.role == Role.WITCH), None)
        if saved and witch:
            self.state.witch_potions.has_save_potion = False
            if witch.is_alive:
                self.state.private_memories[witch.id].append(
                    f"第{self.state.round_number}夜: 你使用解药救了 {saved}号"
                )

        if poisoned and witch:
            self.state.witch_potions.has_poison_potion = False
            if witch.is_alive:
                self.state.private_memories[witch.id].append(
                    f"第{self.state.round_number}夜: 你使用毒药毒杀了 {poisoned}号"
                )

        deaths_this_night: list[int] = []

        if killed_by_ww and killed_by_ww != saved:
            player = self.state.get_player(killed_by_ww)
            player.life_status = LifeStatus.DEAD
            player.death_cause = DeathCause.WEREWOLF_KILL
            deaths_this_night.append(killed_by_ww)

        if poisoned:
            player = self.state.get_player(poisoned)
            if player.is_alive:
                player.life_status = LifeStatus.DEAD
                player.death_cause = DeathCause.WITCH_POISON
                # 被毒死的猎人不能开枪（除非规则允许）
                if not self.hunter_can_shoot_on_poison:
                    player.can_shoot = False
                deaths_this_night.append(poisoned)

        self.state.public_history.append(announcement)
        self.raw_history.append(f"[第{self.state.round_number}夜] {announcement}")

        if event_callback:
            await event_callback("night_result", gm_result, self.state)

        # 猎人死亡触发
        for d in deaths_this_night:
            dead_player = self.state.get_player(d)
            if dead_player.role == Role.HUNTER and dead_player.can_shoot:
                await self._hunter_shoot(dead_player, event_callback)

    async def _hunter_shoot(self, hunter: Player, event_callback: Any = None):
        """猎人开枪"""
        if not hunter.can_shoot:
            await self._emit_progress(event_callback, f"🏹 猎人{hunter.id}号被毒死，无法开枪")
            return

        alive_ids = [p.id for p in self.state.alive_players]
        if not alive_ids:
            await self._emit_progress(event_callback, f"🏹 猎人{hunter.id}号死亡，但无存活玩家可开枪")
            return

        await self._emit_progress(event_callback, f"🏹 猎人{hunter.id}号死亡，正在选择开枪目标...")

        summary = await self._get_summary()
        prompt = f"你刚刚死亡（死因：{hunter.death_cause.value}），作为猎人你可以开枪带走一名存活玩家。可选目标：{alive_ids}。请选择目标。"

        try:
            result = await self.providers[hunter.id].get_hunter_shoot(
                hunter, self.state, self.player_system_prompts[hunter.id],
                summary, prompt,
            )
            target = result.get("shoot_target_id") or result.get("target_id")
            thinking = result.get("thinking", "") or result.get("reasoning", "")
            await self._emit_progress(event_callback, f"🏹 猎人{hunter.id}号思考: {thinking}")

            if target is None:
                # 猎人可以选择不开枪
                await self._emit_progress(event_callback, f"🏹 猎人{hunter.id}号选择不开枪")
                return

            target_player = self.state.get_player(target)
            if target_player is None or not target_player.is_alive:
                # 目标无效，随机选择一名存活玩家开枪
                fallback = random.choice(self.state.alive_players)
                target = fallback.id
                target_player = fallback
                await self._emit_progress(event_callback, f"🏹 猎人{hunter.id}号目标无效({target})，随机开枪带走了 {target}号")

            target_player.life_status = LifeStatus.DEAD
            target_player.death_cause = DeathCause.HUNTER_SHOOT
            self.raw_history.append(f"  猎人{hunter.id}号开枪带走了 {target}号")
            self.state.public_history.append(f"{hunter.id}号猎人死亡时开枪带走了 {target}号")

            await self._emit_progress(event_callback, f"🏹 猎人{hunter.id}号开枪带走了 {target}号")

            if event_callback:
                await event_callback("hunter_shoot", {"hunter": hunter.id, "target": target}, self.state)

            if target_player.role == Role.HUNTER and target_player.can_shoot:
                await self._hunter_shoot(target_player, event_callback)
        except Exception as e:
            logger.error(f"Hunter shoot failed: {e}")
            await self._emit_progress(event_callback, f"❌ 猎人{hunter.id}号开枪失败", str(e)[:80])

    # ─── 白天发言 ───

    async def _run_day_speech(self, event_callback: Any = None):
        """白天发言：串行请求"""
        self.state.phase = Phase.DAY_SPEECH
        alive = self.state.alive_players
        await self._emit_progress(event_callback, f"☀️ 天亮了 — 第 {self.state.round_number} 天发言阶段开始")

        gm_announcement = ""
        if self.state.public_history:
            gm_announcement = self.state.public_history[-1]

        summary = await self._get_summary()

        # 发言顺序清单
        order_list = []
        for p in alive:
            role_icon = {"werewolf": "🐺", "seer": "🔮", "witch": "🧙", "hunter": "🏹", "villager": "👤"}.get(p.role.value, "👤")
            order_list.append(f"{role_icon}{p.id}号({p.personality})")
        await self._emit_progress(event_callback, f"📝 发言顺序", " → ".join(order_list))

        if gm_announcement:
            await self._emit_progress(event_callback, f"📢 昨夜公告: {gm_announcement[:80]}")

        speeches: list[str] = []

        for player in alive:
            role_icon = {"werewolf": "🐺", "seer": "🔮", "witch": "🧙", "hunter": "🏹", "villager": "👤"}.get(player.role.value, "👤")
            await self._emit_progress(event_callback, f"{role_icon} {player.id}号发言中...", f"{player.personality} | 已听过 {len(speeches)} 人")

            try:
                result = await self.providers[player.id].get_speech(
                    player, self.state, self.player_system_prompts[player.id],
                    speeches, summary, gm_announcement,
                    self.state.private_memories.get(player.id),
                )
                thinking = result.get("thinking", "")
                speech_content = result.get("speech", "")

                speech_obj = Speech(player_id=player.id, content=speech_content, thinking=thinking)
                speeches.append(f"{player.id}号: {speech_content}")
                self.raw_history.append(f"[第{self.state.round_number}天发言] {player.id}号: {speech_content}")

                # 发言摘要：截取前50字作为进度信息
                speech_preview = speech_content[:50] + "..." if len(speech_content) > 50 else speech_content
                await self._emit_progress(event_callback, f"{role_icon} {player.id}号发言完毕", f"摘要: {speech_preview} | 思考: {thinking}")

                if event_callback:
                    await event_callback("player_speech", speech_obj.model_dump(), self.state)

            except Exception as e:
                logger.error(f"Speech failed for player {player.id}: {e}")
                await self._emit_progress(event_callback, f"❌ {player.id}号发言失败（沉默）", str(e)[:80])
                speeches.append(f"{player.id}号: (沉默)")
                self.raw_history.append(f"[第{self.state.round_number}天发言] {player.id}号: (沉默)")

                if event_callback:
                    await event_callback("player_speech", {
                        "player_id": player.id, "content": "(沉默)", "thinking": "",
                    }, self.state)

        await self._emit_progress(event_callback, "✅ 所有玩家发言完毕，即将进入投票阶段")

    # ─── 白天投票 ───

    async def _run_day_vote(self, event_callback: Any = None):
        """投票阶段：并发请求"""
        self.state.phase = Phase.DAY_VOTE
        alive = self.state.alive_players
        alive_ids = [p.id for p in alive]
        await self._emit_progress(event_callback, "🗳️ 进入投票阶段 — 所有存活玩家并发投票")

        gm_announcement = ""
        if self.state.public_history:
            gm_announcement = self.state.public_history[-1]

        day_speeches = [
            line for line in self.raw_history
            if f"第{self.state.round_number}天发言" in line
        ]

        summary = await self._get_summary()

        # 投票人清单
        voter_list = []
        for p in alive:
            role_icon = {"werewolf": "🐺", "seer": "🔮", "witch": "🧙", "hunter": "🏹", "villager": "👤"}.get(p.role.value, "👤")
            voter_list.append(f"{role_icon}{p.id}号")
        await self._emit_progress(event_callback, f"📋 本轮投票人", " | ".join(voter_list))

        # 并发投票
        await self._emit_progress(event_callback, "⏳ 所有玩家思考投票中...")
        results = await asyncio.gather(*[
            self.providers[player.id].get_vote(
                player, self.state, self.player_system_prompts[player.id],
                day_speeches, summary, gm_announcement,
                self.state.private_memories.get(player.id),
            )
            for player in alive
        ], return_exceptions=True)

        vote_details: dict[int, int] = {}
        for i, (player, result) in enumerate(zip(alive, results)):
            role_icon = {"werewolf": "🐺", "seer": "🔮", "witch": "🧙", "hunter": "🏹", "villager": "👤"}.get(player.role.value, "👤")
            if isinstance(result, Exception):
                logger.error(f"Vote error for player {player.id}: {result}")
                valid = [p for p in alive_ids if p != player.id]
                fallback_target = random.choice(valid) if valid else None
                if fallback_target:
                    vote_details[player.id] = fallback_target
                await self._emit_progress(event_callback, f"❌ {player.id}号投票失败，随机投给 {fallback_target}号", str(result)[:80])
                continue

            target = result.get("vote_target")
            thinking = result.get("thinking", "")
            if target and target in alive_ids and target != player.id:
                vote_details[player.id] = target
                await self._emit_progress(event_callback, f"{role_icon} {player.id}号 → {target}号", f"思考: {thinking}")
                if event_callback:
                    await event_callback("player_vote", {
                        "voter": player.id, "target": target,
                        "thinking": result.get("thinking", ""),
                    }, self.state)
            else:
                valid = [p for p in alive_ids if p != player.id]
                fallback_target = random.choice(valid) if valid else None
                if fallback_target:
                    vote_details[player.id] = fallback_target
                    await self._emit_progress(event_callback, f"⚠️ {player.id}号投票无效({target}号)，随机投给 {fallback_target}号")

        # 投票统计汇总
        vote_counter = Counter(vote_details.values())
        tally_lines = []
        for target_id, count in vote_counter.most_common():
            tally_lines.append(f"{target_id}号({count}票)")
        await self._emit_progress(event_callback, f"📊 投票统计", " | ".join(tally_lines))

        await self._emit_progress(event_callback, "⚖️ GM 裁决投票结果...")
        # GM 裁决投票
        gm_messages = build_gm_vote_messages(self.state, self.gm_system_prompt, vote_details)
        try:
            gm_result = await self.gm_client.call_json(gm_messages, 0.3)
            eliminated = gm_result.get("eliminated_id")
            tie = gm_result.get("tie", False)
            ruling_desc = f"淘汰 {eliminated}号" if eliminated else ("平票无人淘汰" if tie else "无人淘汰")
            await self._emit_progress(event_callback, f"⚖️ GM裁决: {ruling_desc}", f"公告: {gm_result.get('announcement', '')[:80]}")
        except Exception as e:
            logger.error(f"GM vote ruling failed: {e}")
            await self._emit_progress(event_callback, "⚠️ GM API失败，使用兜底逻辑裁决", str(e)[:80])
            gm_result = self._fallback_vote_ruling(vote_details)

        eliminated_id = gm_result.get("eliminated_id")
        announcement = gm_result.get("announcement", "")

        if eliminated_id:
            player = self.state.get_player(eliminated_id)
            role_icon = {"werewolf": "🐺", "seer": "🔮", "witch": "🧙", "hunter": "🏹", "villager": "👤"}.get(player.role.value, "👤")
            player.life_status = LifeStatus.DEAD
            player.death_cause = DeathCause.VOTE_OUT
            await self._emit_progress(event_callback, f"💀 {eliminated_id}号被投票淘汰", f"角色: {role_icon}{player.role.value} | {player.personality}")
            self.raw_history.append(f"[第{self.state.round_number}天投票] {eliminated_id}号被投票淘汰")

            if player.role == Role.HUNTER and player.can_shoot:
                await self._hunter_shoot(player, event_callback)

        self.state.public_history.append(announcement)
        self.raw_history.append(announcement)

        if event_callback:
            await event_callback("vote_result", gm_result, self.state)

    # ─── 辅助方法 ───

    def _resolve_werewolf_targets(self, targets: list[int]) -> int:
        if not targets:
            valid = [p.id for p in self.state.alive_players if p.role != Role.WEREWOLF]
            return random.choice(valid) if valid else 1

        counter = Counter(targets)
        max_count = max(counter.values())
        most_voted = [t for t, c in counter.items() if c == max_count]

        if len(most_voted) == 1:
            return most_voted[0]
        if self.werewolf_disagree_rule == "random":
            return random.choice(most_voted)
        return most_voted[0]

    def _fallback_night_ruling(
        self, werewolf_target: int | None, witch_result: dict | None, seer_target: int | None,
    ) -> dict:
        result = {
            "killed_by_werewolf": werewolf_target,
            "saved_by_witch": None,
            "killed_by_poison": None,
            "seer_check_result": None,
            "hunter_shoot": None,
            "announcement": "",
        }

        if werewolf_target:
            if witch_result and witch_result.get("use_save"):
                save_id = witch_result.get("save_target_id", werewolf_target)
                result["saved_by_witch"] = save_id
                result["killed_by_werewolf"] = None
                result["announcement"] = "昨晚无人死亡。"
            else:
                result["announcement"] = f"昨晚 {werewolf_target}号死亡。"

        if witch_result and witch_result.get("use_poison"):
            poison_id = witch_result.get("poison_target_id")
            if poison_id:
                result["killed_by_poison"] = poison_id

        if seer_target:
            is_ww = self.state.get_player(seer_target).role == Role.WEREWOLF
            result["seer_check_result"] = {"target_id": seer_target, "is_werewolf": is_ww}

        return result

    def _fallback_vote_ruling(self, vote_details: dict[int, int]) -> dict:
        target_counter = Counter(vote_details.values())
        if not target_counter:
            return {"eliminated_id": None, "tie": True, "announcement": "无人被淘汰。"}

        max_votes = max(target_counter.values())
        most_voted = [t for t, c in target_counter.items() if c == max_votes]

        if len(most_voted) == 1:
            eliminated = most_voted[0]
            return {"eliminated_id": eliminated, "tie": False, "announcement": f"{eliminated}号被投票淘汰。"}
        if self.tie_vote_rule == "random":
            eliminated = random.choice(most_voted)
            return {"eliminated_id": eliminated, "tie": True, "announcement": f"平票，随机淘汰 {eliminated}号。"}
        return {"eliminated_id": None, "tie": True, "announcement": "平票，无人被淘汰。"}

    async def _get_summary(self) -> str | None:
        if len(self.raw_history) <= self.summary_threshold:
            return None
        if self.current_summary:
            new_lines = self.raw_history[self.summary_threshold:]
            if len(new_lines) > self.summary_threshold:
                try:
                    summary_msg = build_summary_messages(self.raw_history)
                    result = await self.summarizer_client.call_json(summary_msg, 0.3)
                    self.current_summary = result.get("summary", result.get("content", ""))
                    self.raw_history = [f"[历史摘要] {self.current_summary}"]
                except Exception as e:
                    logger.warning(f"Summary generation failed: {e}")
                    self.current_summary = "\n".join(self.raw_history[-self.summary_threshold:])
        return self.current_summary

    async def close(self):
        for provider in self.providers.values():
            if isinstance(provider, LLMActionProvider):
                await provider.close()
        await self.gm_client.close()
        await self.summarizer_client.close()