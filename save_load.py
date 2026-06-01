"""
save_load.py — JSON 存档与棋谱序列化
"""

from __future__ import annotations
import json
import os
from datetime import datetime
from typing import Optional
from engine import GameState, MoveRecord, PieceType, Side


SAVE_DIR = os.path.join(os.path.dirname(__file__), "saves")


def _ensure_save_dir() -> None:
    os.makedirs(SAVE_DIR, exist_ok=True)


def save_game(gs: GameState, filename: Optional[str] = None) -> str:
    """
    保存当前棋盘状态到 JSON 文件。
    返回保存的文件路径。
    """
    _ensure_save_dir()
    if filename is None:
        ts = datetime.now().strftime("%Y%m%d_%H%M%S")
        filename = f"save_{ts}.json"
    if not filename.endswith(".json"):
        filename += ".json"
    path = os.path.join(SAVE_DIR, filename)
    data = gs.to_dict()
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
    return path


def load_game(path: str) -> GameState:
    """从 JSON 文件还原 GameState"""
    with open(path, "r", encoding="utf-8") as f:
        data = json.load(f)
    return GameState.from_dict(data)


def list_saves() -> list[str]:
    """返回存档目录下所有 .json 文件路径（按修改时间倒序）"""
    _ensure_save_dir()
    files = [
        os.path.join(SAVE_DIR, f)
        for f in os.listdir(SAVE_DIR)
        if f.endswith(".json")
    ]
    files.sort(key=os.path.getmtime, reverse=True)
    return files


# ──────────────────────────────────────────────
# 棋谱序列化
# ──────────────────────────────────────────────

def record_to_dict(r: MoveRecord) -> dict:
    return {
        "piece_id":      r.piece_id,
        "from_x":        r.from_x,
        "from_y":        r.from_y,
        "to_x":          r.to_x,
        "to_y":          r.to_y,
        "captured_id":   r.captured_id,
        "captured_type": int(r.captured_type) if r.captured_type is not None else None,
        "captured_side": int(r.captured_side) if r.captured_side is not None else None,
        "captured_x":    r.captured_x,
        "captured_y":    r.captured_y,
        "promoted_to":   int(r.promoted_to) if r.promoted_to is not None else None,
        "prev_type":     int(r.prev_type) if r.prev_type is not None else None,
        "was_spy_reveal":    r.was_spy_reveal,
        "fortress_entered":  r.fortress_entered,
    }


def record_from_dict(d: dict) -> MoveRecord:
    return MoveRecord(
        piece_id=d["piece_id"],
        from_x=d["from_x"],
        from_y=d["from_y"],
        to_x=d["to_x"],
        to_y=d["to_y"],
        captured_id=d["captured_id"],
        captured_type=PieceType(d["captured_type"]) if d["captured_type"] is not None else None,
        captured_side=Side(d["captured_side"]) if d["captured_side"] is not None else None,
        captured_x=d["captured_x"],
        captured_y=d["captured_y"],
        promoted_to=PieceType(d["promoted_to"]) if d["promoted_to"] is not None else None,
        prev_type=PieceType(d["prev_type"]) if d["prev_type"] is not None else None,
        was_spy_reveal=d.get("was_spy_reveal", False),
        fortress_entered=d.get("fortress_entered", False),
    )


def save_replay(records: list[MoveRecord], filename: Optional[str] = None) -> str:
    """保存完整棋谱"""
    _ensure_save_dir()
    if filename is None:
        ts = datetime.now().strftime("%Y%m%d_%H%M%S")
        filename = f"replay_{ts}.json"
    path = os.path.join(SAVE_DIR, filename)
    data = {
        "version": 1,
        "moves": [record_to_dict(r) for r in records],
    }
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
    return path


def load_replay(path: str) -> list[MoveRecord]:
    """载入棋谱，返回 MoveRecord 列表"""
    with open(path, "r", encoding="utf-8") as f:
        data = json.load(f)
    return [record_from_dict(d) for d in data["moves"]]
