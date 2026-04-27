"""YAML 配置加载"""

from pathlib import Path

import yaml


DEFAULT_CONFIG_PATH = Path(__file__).parent.parent.parent / "config.yaml"


def load_config(path: str | Path | None = None) -> dict:
    """加载 YAML 配置文件"""
    if path is None:
        path = DEFAULT_CONFIG_PATH
    path = Path(path)
    if not path.exists():
        raise FileNotFoundError(f"Config file not found: {path}")
    with open(path, "r") as f:
        return yaml.safe_load(f)


def get_game_config(config: dict) -> dict:
    """提取游戏配置部分"""
    return config.get("game", {})


def get_rules(config: dict) -> dict:
    """提取规则配置"""
    return config.get("game", {}).get("rules", {})


def get_gm_config(config: dict) -> dict:
    """提取 GM 模型配置"""
    return config.get("game", {}).get("gm", {})


def get_summarizer_config(config: dict) -> dict:
    """提取摘要模型配置"""
    return config.get("game", {}).get("summarizer", {})


def get_players_config(config: dict) -> dict[int, dict]:
    """提取玩家配置（返回 {player_id: cfg}）"""
    return config.get("players", {})


def get_roles(config: dict) -> list[str]:
    """提取角色分配列表"""
    return config.get("game", {}).get("roles", [])


def get_summary_threshold(config: dict) -> int:
    """提取摘要阈值"""
    return config.get("game", {}).get("summary_threshold", 15)