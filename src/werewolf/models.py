"""基于 Pydantic v2 的游戏状态数据模型"""

from __future__ import annotations

import enum
from typing import Optional, Protocol, runtime_checkable

from pydantic import BaseModel, Field, field_validator


# ─── 角色 & 状态枚举 ───

class Role(str, enum.Enum):
    WEREWOLF = "werewolf"
    SEER = "seer"
    WITCH = "witch"
    HUNTER = "hunter"
    VILLAGER = "villager"


class Phase(str, enum.Enum):
    NIGHT = "night"
    DAY_SPEECH = "day_speech"
    DAY_VOTE = "day_vote"
    GAME_OVER = "game_over"


class LifeStatus(str, enum.Enum):
    ALIVE = "alive"
    DEAD = "dead"


class DeathCause(str, enum.Enum):
    WEREWOLF_KILL = "werewolf_kill"
    WITCH_POISON = "witch_poison"
    VOTE_OUT = "vote_out"
    HUNTER_SHOOT = "hunter_shoot"


class Faction(str, enum.Enum):
    WEREWOLF = "werewolf"
    GOOD = "good"


class PlayerType(str, enum.Enum):
    LLM = "llm"
    HUMAN = "human"


# ─── 玩家 ───

class Player(BaseModel):
    id: int = Field(..., ge=1, description="玩家编号")
    role: Role
    life_status: LifeStatus = LifeStatus.ALIVE
    personality: str = Field("neutral", description="性格特征")
    death_cause: Optional[DeathCause] = None
    can_shoot: bool = Field(True, description="猎人是否可以开枪（被毒死则不可）")
    player_type: PlayerType = PlayerType.LLM

    @property
    def faction(self) -> Faction:
        return Faction.WEREWOLF if self.role == Role.WEREWOLF else Faction.GOOD

    @property
    def is_alive(self) -> bool:
        return self.life_status == LifeStatus.ALIVE


# ─── 夜晚行动 ───

class WerewolfAction(BaseModel):
    """狼人杀人目标"""
    target_id: int = Field(..., ge=1, description="目标玩家编号")
    reasoning: str = Field("", description="思考过程")


class SeerAction(BaseModel):
    """预言家查验"""
    target_id: int = Field(..., ge=1, description="查验目标编号")
    reasoning: str = Field("", description="思考过程")


class WitchAction(BaseModel):
    """女巫行动"""
    use_save: bool = Field(False, description="是否使用解药救人")
    save_target_id: Optional[int] = None
    use_poison: bool = Field(False, description="是否使用毒药")
    poison_target_id: Optional[int] = None
    reasoning: str = Field("", description="思考过程")


class HunterAction(BaseModel):
    """猎人开枪"""
    shoot_target_id: Optional[int] = None  # None 表示不开枪
    reasoning: str = Field("", description="思考过程")


# ─── 白天行动 ───

class Speech(BaseModel):
    """玩家白天发言"""
    player_id: int
    content: str
    thinking: str = Field("", description="内心思考（不会公开）")


class Vote(BaseModel):
    """玩家投票"""
    voter_id: int = Field(..., ge=1)
    target_id: int = Field(..., ge=1, description="投票淘汰的目标")
    reasoning: str = Field("", description="思考过程")


# ─── GM 裁决结果 ───

class NightResult(BaseModel):
    """GM 对夜晚的裁决结果"""
    killed_by_werewolf: Optional[int] = None
    killed_by_poison: Optional[int] = None
    saved_by_witch: Optional[int] = None
    seer_check_result: Optional[dict] = None
    hunter_shoot: Optional[int] = None


class VoteResult(BaseModel):
    """GM 对投票的裁决结果"""
    eliminated_id: Optional[int] = None
    tie: bool = False
    vote_details: dict[int, int] = Field(default_factory=dict)


# ─── 女巫药品状态 ───

class WitchPotions(BaseModel):
    has_save_potion: bool = True
    has_poison_potion: bool = True


# ─── 游戏状态 ───

class GameState(BaseModel):
    """完整游戏状态（GM 视角）"""
    players: list[Player] = Field(default_factory=list)
    phase: Phase = Phase.NIGHT
    round_number: int = 1
    witch_potions: WitchPotions = WitchPotions()
    public_history: list[str] = Field(default_factory=list, description="公开信息广播列表")
    private_memories: dict[int, list[str]] = Field(
        default_factory=dict, description="每个玩家的私密记忆"
    )
    night_result: Optional[NightResult] = None
    vote_result: Optional[VoteResult] = None

    @property
    def alive_players(self) -> list[Player]:
        return [p for p in self.players if p.is_alive]

    @property
    def alive_werewolves(self) -> list[Player]:
        return [p for p in self.alive_players if p.role == Role.WEREWOLF]

    @property
    def alive_good_players(self) -> list[Player]:
        return [p for p in self.alive_players if p.role != Role.WEREWOLF]

    def get_player(self, player_id: int) -> Player:
        for p in self.players:
            if p.id == player_id:
                return p
        raise ValueError(f"Player {player_id} not found")

    def check_game_over(self) -> Optional[dict]:
        """检查游戏是否结束，返回 {winner, reason} 或 None

        胜负条件（按优先级）：
        - 好人胜：所有狼人被消灭
        - 狼人胜（满足其一即可）：
          1. 所有神职死亡（屠神边）
          2. 所有平民死亡（屠民边）
          3. 狼人数量 ≥ 好人数量（人数优势）
        屠边优先于人数优势判定，因为屠边是更具体的胜利方式。
        """
        ww = len(self.alive_werewolves)
        if ww == 0:
            return {"winner": "good", "reason": "all_werewolves_eliminated"}

        # 屠神边：所有神职（预言家、女巫、猎人）死亡
        alive_gods = [p for p in self.alive_players if p.role in (Role.SEER, Role.WITCH, Role.HUNTER)]
        if not alive_gods:
            return {"winner": "werewolf", "reason": "slaughter_god"}

        # 屠民边：所有平民死亡
        alive_villagers = [p for p in self.alive_players if p.role == Role.VILLAGER]
        if not alive_villagers:
            return {"winner": "werewolf", "reason": "slaughter_villager"}

        # 狼人数量 ≥ 好人数量
        good = len(self.alive_good_players)
        if ww >= good:
            return {"winner": "werewolf", "reason": "werewolf_majority"}

        return None
        alive_villagers = [p for p in self.alive_players if p.role == Role.VILLAGER]
        if not alive_villagers:
            return {"winner": "werewolf", "reason": "slaughter_villager"}

        return None


# ─── WebSocket 通信模型 ───

class WSMessage(BaseModel):
    """WebSocket 消息格式"""
    type: str = Field(..., description="消息类型")
    data: dict = Field(default_factory=dict)


class ActionRequest(BaseModel):
    """向人类玩家请求行动的消息"""
    request_id: str = Field(..., description="唯一请求ID，用于匹配响应")
    action_type: str = Field(..., description="night_action / speech / vote / hunter_shoot")
    role: Role = Field(..., description="玩家角色（仅发给该玩家自己）")
    prompt: str = Field("", description="行动提示文字")
    options: list[int] = Field(default_factory=list, description="可选目标编号列表")
    context: str = Field("", description="上下文信息（GM公告、已有发言等）")


class ActionResponse(BaseModel):
    """人类玩家提交的行动响应"""
    request_id: str = Field(..., description="对应的请求ID")
    action_type: str = Field(..., description="night_action / speech / vote / hunter_shoot")
    data: dict = Field(default_factory=dict, description="行动数据")


# ─── ActionProvider 抽象 ───

@runtime_checkable
class ActionProvider(Protocol):
    """行动提供者抽象——LLM 或人类"""

    async def get_night_action(
        self, player: Player, game_state: GameState, system_prompt: str,
        summary: str | None, private_info: str,
    ) -> dict: ...

    async def get_speech(
        self, player: Player, game_state: GameState, system_prompt: str,
        previous_speeches: list[str], summary: str | None, gm_announcement: str,
        private_memories: list[str] | None = None,
    ) -> dict: ...

    async def get_vote(
        self, player: Player, game_state: GameState, system_prompt: str,
        all_speeches: list[str], summary: str | None, gm_announcement: str,
        private_memories: list[str] | None = None,
    ) -> dict: ...

    async def get_hunter_shoot(
        self, player: Player, game_state: GameState, system_prompt: str,
        summary: str | None, prompt: str,
    ) -> dict: ...