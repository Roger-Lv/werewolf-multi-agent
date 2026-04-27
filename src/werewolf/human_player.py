"""人类玩家行动提供者 + WebSocket 连接管理"""

import asyncio
import json
import logging
import uuid
from typing import Any

from fastapi import WebSocket

from .models import (
    ActionProvider, ActionRequest, ActionResponse, Player, GameState, Role, WSMessage,
)

logger = logging.getLogger("werewolf.human")


class WebSocketManager:
    """管理所有 WebSocket 连接，区分广播和私密消息"""

    def __init__(self):
        # player_id -> WebSocket 连接
        self.connections: dict[int, WebSocket] = {}
        # player_id -> asyncio.Future（等待人类玩家响应）
        self.pending_responses: dict[int, asyncio.Future] = {}
        # 0号 = 旁观者连接列表
        self.spectator_connections: list[WebSocket] = []

    async def connect_player(self, player_id: int, websocket: WebSocket):
        """人类玩家连接"""
        await websocket.accept()
        self.connections[player_id] = websocket
        logger.info(f"Player {player_id} WebSocket connected")

    async def connect_spectator(self, websocket: WebSocket):
        """旁观者连接"""
        await websocket.accept()
        self.spectator_connections.append(websocket)
        logger.info(f"Spectator WebSocket connected (total: {len(self.spectator_connections)})")

    async def disconnect(self, player_id: int | None = None, websocket: WebSocket | None = None):
        """断开连接"""
        if player_id and player_id in self.connections:
            del self.connections[player_id]
            logger.info(f"Player {player_id} WebSocket disconnected")
        if player_id is None and websocket:
            if websocket in self.spectator_connections:
                self.spectator_connections.remove(websocket)
                logger.info("Spectator disconnected")

    async def broadcast(self, message: WSMessage):
        """广播消息给所有连接（玩家+旁观者）"""
        raw = message.model_dump_json()
        targets = list(self.connections.values()) + self.spectator_connections
        for ws in targets:
            try:
                await ws.send_text(raw)
            except Exception:
                logger.warning(f"Broadcast send failed, may be disconnected")

    async def broadcast_public(self, event_type: str, data: dict):
        """广播公开事件"""
        await self.broadcast(WSMessage(type=event_type, data=data))

    async def send_to_player(self, player_id: int, message: WSMessage):
        """私密消息——只发给特定人类玩家（信息隔离的关键！）"""
        if player_id not in self.connections:
            logger.warning(f"Player {player_id} not connected, cannot send private message")
            return
        ws = self.connections[player_id]
        raw = message.model_dump_json()
        try:
            await ws.send_text(raw)
        except Exception:
            logger.warning(f"Send to player {player_id} failed")

    async def wait_for_response(self, player_id: int, request_id: str, timeout: float = 300.0) -> dict:
        """等待人类玩家的响应"""
        future = asyncio.get_event_loop().create_future()
        self.pending_responses[player_id] = future
        try:
            result = await asyncio.wait_for(future, timeout=timeout)
            return result
        except asyncio.TimeoutError:
            logger.error(f"Player {player_id} response timeout for request {request_id}")
            # 人类超时，返回默认行动
            return {"error": "timeout"}
        finally:
            if player_id in self.pending_responses:
                del self.pending_responses[player_id]

    def submit_response(self, player_id: int, response_data: dict):
        """人类玩家提交响应（从 WebSocket 接收端调用）"""
        if player_id in self.pending_responses:
            future = self.pending_responses[player_id]
            if not future.done():
                future.set_result(response_data)
        else:
            logger.warning(f"No pending response for player {player_id}")

    def is_player_connected(self, player_id: int) -> bool:
        return player_id in self.connections


class HumanActionProvider:
    """人类玩家行动提供者——通过 WebSocket 与前端交互"""

    def __init__(self, player_id: int, ws_manager: WebSocketManager):
        self.player_id = player_id
        self.ws_manager = ws_manager

    def _make_request_id(self) -> str:
        return f"{self.player_id}-{uuid.uuid4().hex[:8]}"

    async def get_night_action(
        self, player: Player, game_state: GameState, system_prompt: str,
        summary: str | None, private_info: str,
    ) -> dict:
        """请求人类玩家的夜晚行动"""
        request_id = self._make_request_id()

        # 构建行动提示
        alive_ids = [p.id for p in game_state.alive_players]
        # 根据角色筛选可选目标
        if player.role == Role.WEREWOLF:
            # 狼人不能杀同伴
            options = [p.id for p in game_state.alive_players if p.role != Role.WEREWOLF]
        elif player.role == Role.SEER:
            # 预言家可以查验任何人
            options = alive_ids
        elif player.role == Role.WITCH:
            # 女巫的目标由前端根据解药/毒药分开选择
            options = alive_ids
        else:
            # 猎人/村民夜晚无行动
            options = []

        prompt = f"第{game_state.round_number}夜，你是{player.role.value}，请选择你的行动。"
        if private_info:
            prompt += f"\n{private_info}"

        request = ActionRequest(
            request_id=request_id,
            action_type="night_action",
            role=player.role,
            prompt=prompt,
            options=options,
            context=private_info,
        )

        # 发送私密请求（只发给该玩家）
        await self.ws_manager.send_to_player(
            self.player_id,
            WSMessage(type="action_request", data=request.model_dump()),
        )

        # 同时广播一个"等待人类行动"的通知（不暴露角色细节）
        await self.ws_manager.broadcast_public("waiting_for_player", {
            "player_id": self.player_id,
            "phase": "night",
        })

        # 等待响应
        return await self.ws_manager.wait_for_response(self.player_id, request_id)

    async def get_speech(
        self, player: Player, game_state: GameState, system_prompt: str,
        previous_speeches: list[str], summary: str | None, gm_announcement: str,
        private_memories: list[str] | None = None,
    ) -> dict:
        """请求人类玩家的白天发言"""
        request_id = self._make_request_id()

        context_parts = []
        if gm_announcement:
            context_parts.append(f"GM公告: {gm_announcement}")
        if previous_speeches:
            context_parts.append("已有发言:\n" + "\n".join(previous_speeches))
        if private_memories:
            context_parts.append("你的私密记忆:\n" + "\n".join(private_memories))

        prompt = f"第{game_state.round_number}天发言阶段，请发表你的观点。"

        request = ActionRequest(
            request_id=request_id,
            action_type="speech",
            role=player.role,
            prompt=prompt,
            options=[],  # 发言不需要选项
            context="\n".join(context_parts),
        )

        await self.ws_manager.send_to_player(
            self.player_id,
            WSMessage(type="action_request", data=request.model_dump()),
        )

        await self.ws_manager.broadcast_public("waiting_for_player", {
            "player_id": self.player_id,
            "phase": "day_speech",
        })

        return await self.ws_manager.wait_for_response(self.player_id, request_id)

    async def get_vote(
        self, player: Player, game_state: GameState, system_prompt: str,
        all_speeches: list[str], summary: str | None, gm_announcement: str,
        private_memories: list[str] | None = None,
    ) -> dict:
        """请求人类玩家的投票"""
        request_id = self._make_request_id()

        alive_ids = [p.id for p in game_state.alive_players if p.id != player.id]
        context_parts = []
        if gm_announcement:
            context_parts.append(f"GM公告: {gm_announcement}")
        if all_speeches:
            context_parts.append("今日发言:\n" + "\n".join(all_speeches))
        if private_memories:
            context_parts.append("你的私密记忆:\n" + "\n".join(private_memories))

        prompt = f"第{game_state.round_number}天投票阶段，请选择你投票淘汰的目标。"

        request = ActionRequest(
            request_id=request_id,
            action_type="vote",
            role=player.role,
            prompt=prompt,
            options=alive_ids,
            context="\n".join(context_parts),
        )

        await self.ws_manager.send_to_player(
            self.player_id,
            WSMessage(type="action_request", data=request.model_dump()),
        )

        # 投票并发，不广播等待
        return await self.ws_manager.wait_for_response(self.player_id, request_id)

    async def get_hunter_shoot(
        self, player: Player, game_state: GameState, system_prompt: str,
        summary: str | None, prompt: str,
    ) -> dict:
        """请求猎人开枪目标"""
        request_id = self._make_request_id()
        alive_ids = [p.id for p in game_state.alive_players]

        request = ActionRequest(
            request_id=request_id,
            action_type="hunter_shoot",
            role=Role.HUNTER,
            prompt="你刚刚死亡，作为猎人可以选择开枪带走一名玩家。",
            options=alive_ids,
            context=prompt,
        )

        await self.ws_manager.send_to_player(
            self.player_id,
            WSMessage(type="action_request", data=request.model_dump()),
        )

        await self.ws_manager.broadcast_public("waiting_for_player", {
            "player_id": self.player_id,
            "phase": "hunter_shoot",
        })

        return await self.ws_manager.wait_for_response(self.player_id, request_id)