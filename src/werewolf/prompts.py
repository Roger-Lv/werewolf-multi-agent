"""GM 与 Player Agent 的提示词逻辑"""

from .models import Role, Player, GameState, Phase


# ─── GM 提示词 ───

GM_SYSTEM_PROMPT = """你是狼人杀游戏的 Game Master (GM)，负责裁决游戏逻辑。你掌握全局信息，但不负责生成玩家的发言。

## 你的职责
1. 夜晚阶段：根据各角色提交的行动，裁决谁被杀、谁被救、预言家查验结果
2. 白天投票阶段：根据玩家投票结果，裁决谁被淘汰
3. 判断游戏胜负条件

## 游戏规则
- 狼人：每晚选择一个非狼人玩家杀死。如果多个狼人目标不一致，取出现最多的目标；仍不一致则随机选择。
- 预言家：每晚查验一个玩家，得知其是否为狼人。
- 女巫：有一瓶解药和一瓶毒药。解药可救当晚被狼人杀死的人；毒药可毒杀任意一名玩家。两种药各只能用一次。同一夜不能同时使用解药和毒药。{witch_self_save_rule}
- 猎人：死亡时可以开枪带走一名玩家。但若被女巫毒死，则不能开枪。
- 平票处理：{tie_rule}
- 胜负条件：狼人全灭则好人胜；狼人数量 ≥ 好人数量则狼人胜。

## 输出格式要求
你必须输出严格的 JSON，不要输出任何其他内容。格式如下：

夜晚裁决：
```json
{{
  "killed_by_werewolf": <被狼人杀死的玩家编号或null>,
  "saved_by_witch": <被女巫救活的玩家编号或null>,
  "killed_by_poison": <被女巫毒死的玩家编号或null>,
  "seer_check_result": {{\"target_id\": <编号>, \"is_werewolf\": <true/false>}} 或 null,
  "hunter_shoot": <猎人开枪目标编号或null>,
  "announcement": "<GM广播给所有人的公开信息，只说明谁死了，不暴露死因和凶手身份>"
}}
```

投票裁决：
```json
{{
  "eliminated_id": <被淘汰的玩家编号或null>,
  "tie": <是否平票true/false>,
  "announcement": "<GM广播的公开信息>"
}}
```
"""

GM_NIGHT_USER_PROMPT = """现在是第 {round_number} 夜晚。以下是各角色提交的行动：

狼人行动（目标编号列表）：{werewolf_targets}
预言家查验目标：{seer_target}
女巫行动：{witch_action}
猎人是否被触发：{hunter_triggered}

当前存活玩家：{alive_players}
女巫药品状态：解药={has_save}, 毒药={has_poison}

请根据以上信息裁决夜晚结果，输出 JSON。"""

GM_VOTE_USER_PROMPT = """现在是第 {round_number} 天投票阶段。以下是各玩家的投票：

{vote_list}

当前存活玩家：{alive_players}

请根据投票结果裁决谁被淘汰，输出 JSON。"""


# ─── Player 提示词 ───

PLAYER_SYSTEM_PROMPT_TEMPLATE = """你是狼人杀游戏中的 {player_id} 号玩家。

## 你的身份
- 角色：{role_name}
- 性格特征：{personality}
{faction_hint}

## 游戏规则
- 狼人阵营：每晚选择杀人目标，白天要伪装自己不被发现
- 预言家：每晚可查验一人是否为狼人
- 女巫：有一瓶解药和一瓶毒药，各只能用一次{witch_self_save_note}
- 猎人：死亡时可开枪带走一人（被毒死不能开枪）
- 村民：无特殊能力，依靠推理和发言
- 胜负条件：狼人全灭好人胜；狼人数量 ≥ 好人数量狼人胜

## 输出格式要求
你必须输出严格的 JSON，不要输出任何其他内容。

夜晚行动时：
{night_action_format}

白天发言时：
```json
{{
  "thinking": "<你的内心思考过程，不会被其他玩家看到>",
  "speech": "<你的公开发言，会被所有人听到>"
}}
```

投票时：
```json
{{
  "thinking": "<你的内心思考过程>",
  "vote_target": <你投票淘汰的玩家编号>
}}
```
"""

ROLE_NAMES = {
    Role.WEREWOLF: "狼人",
    Role.SEER: "预言家",
    Role.WITCH: "女巫",
    Role.HUNTER: "猎人",
    Role.VILLAGER: "村民",
}


def _get_night_action_format(role: Role) -> str:
    formats = {
        Role.WEREWOLF: """```json
{{
  "thinking": "<你的内心思考>",
  "target_id": <你要杀的玩家编号>
}}
```""",
        Role.SEER: """```json
{{
  "thinking": "<你的内心思考>",
  "target_id": <你要查验的玩家编号>
}}
```""",
        Role.WITCH: """```json
{{
  "thinking": "<你的内心思考>",
  "use_save": <是否使用解药true/false>,
  "save_target_id": <解药救谁，编号或null>,
  "use_poison": <是否使用毒药true/false>,
  "poison_target_id": <毒药杀谁，编号或null>
}}
```
注意：同一夜不能同时使用解药和毒药。""",
        Role.HUNTER: """```json
{{
  "thinking": "<你的内心思考（猎人夜晚无特殊行动，只需输出空操作）>",
  "action": "sleep"
}}
```""",
        Role.VILLAGER: """```json
{{
  "thinking": "<你的内心思考（村民夜晚无特殊行动）>",
  "action": "sleep"
}}
```""",
    }
    return formats.get(role, formats[Role.VILLAGER])


def _get_faction_hint(player: Player) -> str:
    """阵营提示——只告诉玩家自己所属阵营和（狼人的）同伴信息"""
    if player.role == Role.WEREWOLF:
        return "\n你属于狼人阵营。你的狼人同伴是：{werewolf_peers}"
    if player.role == Role.SEER:
        return "\n你属于好人阵营。作为预言家，你可以查验他人身份。"
    if player.role == Role.WITCH:
        return "\n你属于好人阵营。"
    if player.role == Role.HUNTER:
        return "\n你属于好人阵营。死亡时可以开枪带走一人。"
    return "\n你属于好人阵营。"


def build_player_system_prompt(
    player: Player,
    werewolf_peers: list[int] | None = None,
    witch_self_save_rule: str = "首夜可以自救",
) -> str:
    """构建玩家的 System Prompt（只包含该玩家自己的信息）"""
    role_name = ROLE_NAMES[player.role]
    faction_hint = _get_faction_hint(player)
    night_fmt = _get_night_action_format(player.role)

    # 狼人同伴替换
    if player.role == Role.WEREWOLF and werewolf_peers is not None:
        peer_names = ", ".join(str(p) for p in werewolf_peers)
        faction_hint = faction_hint.replace("{werewolf_peers}", peer_names + "号")

    # 女巫自救规则
    witch_note = ""
    if player.role == Role.WITCH:
        witch_note = f"（{witch_self_save_rule}）"

    return PLAYER_SYSTEM_PROMPT_TEMPLATE.format(
        player_id=player.id,
        role_name=role_name,
        personality=player.personality,
        faction_hint=faction_hint,
        night_action_format=night_fmt,
        witch_self_save_note=witch_note,
    )


def build_player_night_messages(
    player: Player,
    game_state: GameState,
    system_prompt: str,
    summary: str | None = None,
    private_info: str = "",
) -> list[dict[str, str]]:
    """构建玩家夜晚行动的 messages 列表"""
    messages = [{"role": "system", "content": system_prompt}]

    if summary:
        messages.append({"role": "user", "content": f"以下是之前游戏的历史摘要：\n{summary}"})

    alive_info = f"当前存活玩家：{', '.join(str(p.id) for p in game_state.alive_players)}"
    round_info = f"现在是第 {game_state.round_number} 夜晚。"

    user_content = f"{round_info}\n{alive_info}\n"
    if private_info:
        user_content += f"\n你的私密信息：\n{private_info}\n"
    user_content += "\n请输出你的夜晚行动 JSON。"

    messages.append({"role": "user", "content": user_content})
    return messages


def build_player_speech_messages(
    player: Player,
    game_state: GameState,
    system_prompt: str,
    previous_speeches: list[str],
    summary: str | None = None,
    gm_announcement: str = "",
    private_memories: list[str] | None = None,
) -> list[dict[str, str]]:
    """构建玩家白天发言的 messages 列表"""
    messages = [{"role": "system", "content": system_prompt}]

    if summary:
        messages.append({"role": "user", "content": f"以下是之前游戏的历史摘要：\n{summary}"})

    if gm_announcement:
        messages.append({"role": "user", "content": f"GM广播：{gm_announcement}"})

    # 私密记忆（查验记录、药品使用等）
    if private_memories:
        memories_text = "\n".join(private_memories)
        messages.append({"role": "user", "content": f"你的私密记忆（仅你可见，不要直接暴露具体内容但可以据此做出判断）：\n{memories_text}"})

    # 本次发言历史（当天前面玩家的发言）
    if previous_speeches:
        speeches_text = "\n".join(previous_speeches)
        messages.append({"role": "user", "content": f"以下是今天其他玩家的发言：\n{speeches_text}"})

    alive_info = f"当前存活玩家：{', '.join(str(p.id) for p in game_state.alive_players)}"
    round_info = f"现在是第 {game_state.round_number} 天发言阶段。"

    messages.append({
        "role": "user",
        "content": f"{round_info}\n{alive_info}\n请输出你的发言 JSON（包含 thinking 和 speech）。",
    })
    return messages


def build_player_vote_messages(
    player: Player,
    game_state: GameState,
    system_prompt: str,
    all_speeches: list[str],
    summary: str | None = None,
    gm_announcement: str = "",
    private_memories: list[str] | None = None,
) -> list[dict[str, str]]:
    """构建玩家投票的 messages 列表"""
    messages = [{"role": "system", "content": system_prompt}]

    if summary:
        messages.append({"role": "user", "content": f"以下是之前游戏的历史摘要：\n{summary}"})

    if gm_announcement:
        messages.append({"role": "user", "content": f"GM广播：{gm_announcement}"})

    # 私密记忆（查验记录、药品使用等）
    if private_memories:
        memories_text = "\n".join(private_memories)
        messages.append({"role": "user", "content": f"你的私密记忆（仅你可见，不要直接暴露具体内容但可以据此做出判断）：\n{memories_text}"})

    # 当天所有发言
    speeches_text = "\n".join(all_speeches)
    messages.append({"role": "user", "content": f"以下是今天所有玩家的发言：\n{speeches_text}"})

    alive_info = f"当前存活玩家：{', '.join(str(p.id) for p in game_state.alive_players)}"
    round_info = f"现在是第 {game_state.round_number} 天投票阶段。"

    messages.append({
        "role": "user",
        "content": f"{round_info}\n{alive_info}\n请输出你的投票 JSON（包含 thinking 和 vote_target）。",
    })
    return messages


def build_gm_system_prompt(
    witch_can_save_self_first_night: bool = True,
    tie_rule: str = "随机淘汰",
) -> str:
    """构建 GM 的 System Prompt"""
    self_save = "女巫首夜可以自救。" if witch_can_save_self_first_night else "女巫首夜不能自救。"
    return GM_SYSTEM_PROMPT.format(
        witch_self_save_rule=self_save,
        tie_rule=tie_rule,
    )


def build_gm_night_messages(
    game_state: GameState,
    gm_system_prompt: str,
    werewolf_targets: list[int],
    seer_target: int | None = None,
    witch_action: dict | None = None,
    hunter_triggered: bool = False,
) -> list[dict[str, str]]:
    """构建 GM 夜晚裁决的 messages"""
    messages = [{"role": "system", "content": gm_system_prompt}]

    alive_str = ", ".join(str(p.id) for p in game_state.alive_players)
    has_save = game_state.witch_potions.has_save_potion
    has_poison = game_state.witch_potions.has_poison_potion

    user = GM_NIGHT_USER_PROMPT.format(
        round_number=game_state.round_number,
        werewolf_targets=str(werewolf_targets),
        seer_target=seer_target if seer_target else "无",
        witch_action=str(witch_action) if witch_action else "无",
        hunter_triggered=hunter_triggered,
        alive_players=alive_str,
        has_save=has_save,
        has_poison=has_poison,
    )
    messages.append({"role": "user", "content": user})
    return messages


def build_gm_vote_messages(
    game_state: GameState,
    gm_system_prompt: str,
    vote_details: dict[int, int],
) -> list[dict[str, str]]:
    """构建 GM 投票裁决的 messages"""
    messages = [{"role": "system", "content": gm_system_prompt}]

    alive_str = ", ".join(str(p.id) for p in game_state.alive_players)
    vote_lines = []
    for voter_id, target_id in vote_details.items():
        vote_lines.append(f"{voter_id}号投票给 {target_id}号")
    vote_list = "\n".join(vote_lines)

    user = GM_VOTE_USER_PROMPT.format(
        round_number=game_state.round_number,
        vote_list=vote_list,
        alive_players=alive_str,
    )
    messages.append({"role": "user", "content": user})
    return messages


# ─── 摘要 Prompt ───

SUMMARY_SYSTEM_PROMPT = """你是一个游戏历史摘要生成器。请将以下狼人杀游戏的历史事件压缩为一段简洁的摘要，
保留关键信息（谁死了、谁被怀疑、关键的发言论点），但去除冗余细节。摘要长度控制在200字以内。"""

SUMMARY_USER_TEMPLATE = """请将以下游戏历史压缩为摘要：

{history}"""


def build_summary_messages(history_lines: list[str]) -> list[dict[str, str]]:
    """构建摘要生成的 messages"""
    history_text = "\n".join(history_lines)
    return [
        {"role": "system", "content": SUMMARY_SYSTEM_PROMPT},
        {"role": "user", "content": SUMMARY_USER_TEMPLATE.format(history=history_text)},
    ]


# ─── 预言家私密信息 ───

def build_seer_private_info(seer_check_results: list[dict]) -> str:
    """为预言家构建查验结果的私密信息"""
    if not seer_check_results:
        return ""
    lines = ["你之前的查验结果："]
    for result in seer_check_results:
        target = result["target_id"]
        is_ww = result["is_werewolf"]
        identity = "狼人" if is_ww else "好人"
        lines.append(f"  {target}号玩家：{identity}")
    return "\n".join(lines)


# ─── 女巫私密信息 ───

def build_witch_private_info(
    killed_by_werewolf: int | None,
    has_save: bool,
    has_poison: bool,
    first_night: bool,
    witch_can_save_self: bool,
) -> str:
    """为女巫构建夜晚私密信息"""
    lines = []
    if killed_by_werewolf is not None:
        lines.append(f"今晚 {killed_by_werewolf}号玩家 被狼人杀害。")
    else:
        lines.append("今晚无人被狼人杀害。")
    lines.append(f"你的药品状态：解药={has_save}, 毒药={has_poison}")
    if not has_save and not has_poison:
        lines.append("你已经没有药品了，今晚无需行动。")
    return "\n".join(lines)