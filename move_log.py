"""
move_log.py — 棋谱记录模块（§14）
MoveEntry: 单条棋谱条目
MoveLog:   棋谱管理器，支持实时追加、回溯模式
"""

from __future__ import annotations
from dataclasses import dataclass, field
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from engine import Side, PieceType


# 棋子中文名映射（§14.3）
PIECE_NAMES: dict[int, str] = {
    0:  "士兵",
    1:  "大臣",
    2:  "军官",
    3:  "骑士",
    4:  "刺客",
    5:  "铁卫",
    6:  "总督",
    7:  "教主",
    8:  "亲信",
    9:  "御史",
    10: "领主",
}


def _pos_str(pos: "tuple[int, int] | None") -> str:
    """将逻辑坐标 (x, y) 转为棋盘记谱格式 A1~I9"""
    if pos is None:
        return "?"
    x, y = pos
    return f"{chr(ord('A') + x)}{y + 1}"


@dataclass
class MoveEntry:
    """单条棋谱条目（§14.5）"""
    turn:           int                              # 回合号（1, 2, 3...）
    side:           "Side"                           # RED=0 / BLUE=1
    piece_type:     "PieceType | None"               # 移动棋子的类型；揭露间谍时为 None
    from_pos:       "tuple[int, int] | None"         # 起点坐标；揭露间谍时为 None
    to_pos:         "tuple[int, int] | None"         # 终点坐标
    is_capture:     bool = False                     # 是否吃子
    captured_type:  "PieceType | None" = None        # 被吃棋子类型
    promotion:      "PieceType | None" = None        # 晋升后的类型
    spy_reveal:     bool = False                     # 是否为揭露间谍行动
    spy_count:      int  = 0                         # 揭露时倒戈棋子数量
    fortress_enter: bool = False                     # 是否进入堡垒
    fortress_exit:  bool = False                     # 是否离开堡垒
    notation:       str  = field(default="")         # 自动生成的显示字符串（add 时填充）

    # board_snapshot 不保存在 MoveEntry 里，回溯用 engine.history[N].board_snapshot
    # 此处只需 notation 用于 UI 渲染


class MoveLog:
    """
    棋谱管理器（§14.6）

    - add():          追加新条目（apply_move 后调用）
    - get_current():  返回当前高亮条目
    - set_review():   进入回溯模式（点击历史条目）
    - exit_review():  退出回溯模式（回到最新）
    - to_text():      导出纯文本棋谱
    """

    def __init__(self) -> None:
        self.entries:        list[MoveEntry] = []
        self._current_index: int = -1        # 当前高亮条目索引；-1 = 空
        self._review_mode:   bool = False    # 是否处于回溯模式

    # ── 追加 ──────────────────────────────────

    def add(self, entry: MoveEntry) -> None:
        """apply_move() 后调用，追加新条目（§14.7）"""
        entry.notation = self.auto_notation(entry)
        self.entries.append(entry)
        self._current_index = len(self.entries) - 1
        # 追加时若不在回溯模式则始终跟随最新
        if not self._review_mode:
            self._current_index = len(self.entries) - 1

    # ── 查询 ──────────────────────────────────

    def get_current(self) -> "MoveEntry | None":
        """返回当前高亮条目"""
        if not self.entries or self._current_index < 0:
            return None
        return self.entries[self._current_index]

    @property
    def current_index(self) -> int:
        return self._current_index

    @property
    def review_mode(self) -> bool:
        return self._review_mode

    @property
    def count(self) -> int:
        return len(self.entries)

    # ── 回溯模式 ──────────────────────────────

    def set_review(self, index: int) -> None:
        """进入回溯模式，高亮第 index 条（§14.8）"""
        if 0 <= index < len(self.entries):
            self._current_index = index
            self._review_mode = True

    def exit_review(self) -> None:
        """退出回溯模式，回到最新条目（§14.8）"""
        self._review_mode = False
        self._current_index = len(self.entries) - 1

    # ── 导出 ──────────────────────────────────

    def to_text(self) -> str:
        """导出为纯文本棋谱（§14.10）"""
        from datetime import date
        header = (
            "=== 代号 FunnyPitch 棋谱 ===\n"
            "红方 vs 蓝方\n"
            f"日期: {date.today()}\n\n"
        )
        return header + "\n".join(e.notation for e in self.entries)

    # ── 自动生成 notation ─────────────────────

    @staticmethod
    def auto_notation(entry: MoveEntry) -> str:
        """根据 MoveEntry 内容自动生成 notation 字符串（§14.6）"""
        from engine import Side  # 延迟导入避免循环依赖

        color = "🔴" if int(entry.side) == int(Side.RED) else "🔵"

        # 揭露间谍特殊处理
        if entry.spy_reveal:
            if entry.spy_count > 0:
                return (
                    f"{entry.turn}. {color} "
                    f"👁️ 揭露间谍 → {entry.spy_count} 枚棋子倒戈"
                )
            else:
                return f"{entry.turn}. {color} 👁️ 揭露间谍 → 间谍已全军覆没"

        # 普通移动 / 吃子
        name = PIECE_NAMES.get(int(entry.piece_type), "?") if entry.piece_type is not None else "?"
        from_s = _pos_str(entry.from_pos)
        to_s   = _pos_str(entry.to_pos)

        flags: list[str] = []
        if entry.is_capture and entry.captured_type is not None:
            cap_name = PIECE_NAMES.get(int(entry.captured_type), "?")
            flags.append(f"🔥吃{cap_name}")
        if entry.promotion is not None:
            promo_name = PIECE_NAMES.get(int(entry.promotion), "?")
            flags.append(f"⭐→{promo_name}")
        if entry.fortress_enter:
            flags.append("🏰进堡垒")
        if entry.fortress_exit:
            flags.append("🚪出堡垒")

        flag_str = " [" + " ".join(flags) + "]" if flags else ""
        return f"{entry.turn}. {color} {name} {from_s} → {to_s}{flag_str}"
