"""FastAPI + WebSocket 服务端"""

import asyncio
import json
import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from pathlib import Path

from .config import load_config, get_game_config, get_rules, get_gm_config, get_summarizer_config, get_players_config, get_roles, get_summary_threshold
from .game_engine import GameEngine
from .human_player import HumanActionProvider, WebSocketManager
from .models import PlayerType, Role, Phase, WSMessage

logger = logging.getLogger("werewolf.server")

ws_manager = WebSocketManager()
engine: GameEngine | None = None
game_task: asyncio.Task | None = None
game_running = False


@asynccontextmanager
async def lifespan(app: FastAPI):
    yield
    global engine
    if engine:
        await engine.close()


app = FastAPI(title="Werewolf Multi-Agent Game", lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# 前端静态文件（开发时由 Vite dev server 提供，生产时由此服务）
frontend_dist = Path(__file__).parent.parent.parent / "frontend" / "dist"
if frontend_dist.exists():
    app.mount("/static", StaticFiles(directory=str(frontend_dist)), name="static")


# ─── 事件回调（引擎 → WebSocket 推送）───

async def event_callback(event_type: str, data, state):
    """引擎事件回调：将事件推送到 WebSocket"""
    if isinstance(data, dict):
        event_data = data
    elif hasattr(data, "model_dump"):
        event_data = data.model_dump()
    else:
        event_data = {"raw": str(data)}

    # 构建公开信息（所有人可见）
    public_data = {"event_type": event_type, "data": event_data, "round": state.round_number, "phase": state.phase.value}

    # ── 信息隔离：根据事件类型决定推送策略 ──
    if event_type == "night_result":
        # 夜晚结果：公开公告 + 实际死亡编号，不暴露死因和凶手角色
        # 关键：killed_by_werewolf 只是"被选中"，如果 saved_by_witch == killed_by_werewolf 则未死
        announcement = event_data.get("announcement", "")
        saved = event_data.get("saved_by_witch")
        killed = event_data.get("killed_by_werewolf")
        poisoned = event_data.get("killed_by_poison")
        deaths = []
        # 与引擎逻辑一致：被杀且未被救 → 死亡
        if killed and killed != saved:
            deaths.append(killed)
        if poisoned:
            deaths.append(poisoned)
        broadcast_data = {
            "event_type": event_type,
            "announcement": announcement,
            "deaths": deaths,
            "round": state.round_number,
            "phase": state.phase.value,
        }
        await ws_manager.broadcast_public("night_result", broadcast_data)
        return

    if event_type == "seer_check":
        # 预言家查验结果：只发给预言家本人（如果是人类）
        seer_id = event_data.get("seer_id")
        target = event_data["target"]
        is_ww = event_data["is_werewolf"]
        # 公开广播不暴露查验结果
        await ws_manager.broadcast_public("seer_check_public", {
            "seer_id": seer_id,
            "round": state.round_number,
        })
        # 私密发给预言家
        if seer_id and ws_manager.is_player_connected(seer_id):
            await ws_manager.send_to_player(seer_id, WSMessage(
                type="seer_check_private",
                data={"target": target, "is_werewolf": is_ww},
            ))
        return

    if event_type == "player_speech":
        # 发言：公开广播
        await ws_manager.broadcast_public("player_speech", {
            "player_id": event_data.get("player_id"),
            "content": event_data.get("content", ""),
            "round": state.round_number,
        })
        return

    if event_type == "player_vote":
        # 投票：公开广播
        await ws_manager.broadcast_public("player_vote", {
            "voter": event_data.get("voter"),
            "target": event_data.get("target"),
        })
        return

    if event_type == "vote_result":
        # 投票结果：公开广播（不暴露淘汰者的角色——只在游戏结束后揭示）
        await ws_manager.broadcast_public("vote_result", {
            "eliminated_id": event_data.get("eliminated_id"),
            "announcement": event_data.get("announcement", ""),
            "tie": event_data.get("tie", False),
        })
        return

    if event_type == "hunter_shoot":
        await ws_manager.broadcast_public("hunter_shoot", {
            "hunter": event_data["hunter"],
            "target": event_data["target"],
        })
        return

    if event_type == "game_over":
        winner = event_data.get("winner")
        reason = event_data.get("reason", "")
        # 胜因中文描述
        reason_labels = {
            "all_werewolves_eliminated": "所有狼人被消灭",
            "werewolf_majority": "狼人人数 ≥ 好人人数",
            "slaughter_god": "屠神边——所有神职死亡",
            "slaughter_villager": "屠民边——所有平民死亡",
        }
        reason_text = reason_labels.get(reason, reason)
        # 游戏结束：揭示所有角色
        players_info = []
        for p in state.players:
            players_info.append({
                "id": p.id,
                "role": p.role.value,
                "life_status": p.life_status.value,
                "player_type": p.player_type.value,
            })
        await ws_manager.broadcast_public("game_over", {
            "winner": winner,
            "reason": reason,
            "reason_text": reason_text,
            "players": players_info,
        })
        global game_running
        game_running = False
        return

    # 进度事件：公开广播，让所有人看到游戏进展
    if event_type == "progress":
        await ws_manager.broadcast_public("progress", {
            "message": event_data.get("message", ""),
            "detail": event_data.get("detail", ""),
            "round": state.round_number,
            "phase": state.phase.value,
        })
        return

    # 通用事件：公开广播（仅传递事件类型和基础数据，绝不传递包含角色信息的原始数据）
    safe_broadcast = {
        "event_type": event_type,
        "round": state.round_number,
        "phase": state.phase.value,
    }
    # 只保留已知的非敏感字段
    for key in ["round", "player_id", "voter", "target", "message"]:
        if key in event_data:
            safe_broadcast[key] = event_data[key]
    await ws_manager.broadcast(WSMessage(type=event_type, data=safe_broadcast))


# ─── WebSocket 端点 ───

@app.websocket("/ws/game/{player_id}")
async def websocket_endpoint(websocket: WebSocket, player_id: int):
    """WebSocket 连接：player_id=0 为旁观者，1-9 为人类玩家"""
    if player_id == 0:
        await ws_manager.connect_spectator(websocket)
    elif ws_manager.is_player_connected(player_id):
        # 已有连接，拒绝重复
        await websocket.close(code=4001, reason="Player already connected")
        return
    else:
        await ws_manager.connect_player(player_id, websocket)

    try:
        while True:
            raw = await websocket.receive_text()
            try:
                msg = json.loads(raw)
            except json.JSONDecodeError:
                continue

            # 处理人类玩家响应
            if msg.get("type") == "action_response" and player_id > 0:
                ws_manager.submit_response(player_id, msg.get("data", {}))

    except WebSocketDisconnect:
        await ws_manager.disconnect(player_id=player_id, websocket=websocket)


# ─── HTTP API ───

@app.get("/api/state")
async def get_state():
    """获取当前游戏公开状态"""
    if not engine:
        return {"status": "not_started"}

    state = engine.state
    alive_ids = [p.id for p in state.alive_players]

    # 公开状态——包含角色信息（此系统为开发/旁观工具，角色信息全程可见）
    players_public = []
    for p in state.players:
        players_public.append({
            "id": p.id,
            "role": p.role.value,
            "life_status": p.life_status.value,
            "personality": p.personality,
            "player_type": p.player_type.value,
        })

    return {
        "status": "running" if game_running else "ended",
        "round": state.round_number,
        "phase": state.phase.value,
        "players": players_public,
        "alive_ids": alive_ids,
        "public_history": state.public_history[-5:],  # 最近5条公开信息
    }


@app.get("/api/my-role/{player_id}")
async def get_my_role(player_id: int):
    """获取人类玩家自己的角色信息（私密！必须通过该玩家的 WebSocket 连接才能访问）"""
    if not engine:
        return {"error": "game not started"}
    # 安全检查：只有已通过 WebSocket 连接的玩家才能查询自己的角色
    # 其他人的查询会被拒绝——这是信息隔离的关键防线
    if not ws_manager.is_player_connected(player_id):
        return {"error": "player not connected — must connect via WebSocket first"}

    player = engine.state.get_player(player_id)
    result = {
        "id": player.id,
        "role": player.role.value,
        "faction": player.faction.value,
        "personality": player.personality,
        "is_alive": player.is_alive,
    }

    # 狼人可以看到同伴
    if player.role == Role.WEREWOLF:
        peers = [p.id for p in engine.state.players if p.role == Role.WEREWOLF and p.id != player.id]
        result["werewolf_peers"] = peers

    # 预言家可以看到查验记录
    if player.role == Role.SEER:
        result["seer_checks"] = engine.seer_check_results

    return result


@app.post("/api/game/start")
async def start_game():
    """启动游戏"""
    global engine, game_task, game_running

    if game_running:
        return {"error": "game already running"}

    config = load_config()
    game_cfg = get_game_config(config)
    rules = get_rules(config)
    players_cfg = get_players_config(config)
    roles_list = get_roles(config)

    # 构建人类玩家 provider
    human_providers = {}
    for pid, cfg in players_cfg.items():
        if cfg.get("type") == "human":
            human_providers[pid] = HumanActionProvider(pid, ws_manager)

    engine = GameEngine(
        players_cfg=players_cfg,
        roles=roles_list,
        gm_cfg=get_gm_config(config),
        summarizer_cfg=get_summarizer_config(config),
        rules=rules,
        summary_threshold=get_summary_threshold(config),
        human_providers=human_providers,
    )

    game_running = True
    game_task = asyncio.create_task(engine.run_game(event_callback=event_callback))

    return {"status": "started"}


@app.post("/api/game/stop")
async def stop_game():
    """停止游戏"""
    global game_task, game_running
    if game_task:
        game_task.cancel()
        try:
            await game_task
        except asyncio.CancelledError:
            pass
    game_running = False
    return {"status": "stopped"}


def main():
    """启动服务"""
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)


if __name__ == "__main__":
    main()