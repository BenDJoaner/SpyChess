"""
engine.py — 间谍象棋核心逻辑层
纯逻辑，不依赖任何 UI/渲染库。
交互层和 AI 层均通过此层接口操作棋盘。
"""

from __future__ import annotations
from dataclasses import dataclass, field
from enum import IntEnum
from typing import Optional
import random
import copy


# ──────────────────────────────────────────────
# 枚举定义
# ──────────────────────────────────────────────

class PieceType(IntEnum):
    SOLDIER     = 0
    MINISTER    = 1
    OFFICER     = 2
    KNIGHT      = 3
    ASSASSIN    = 4
    IRON_GUARD  = 5
    CHAMBERLAIN = 6
    PRIEST      = 7
    LOYALIST    = 8
    CENSOR      = 9
    LORD        = 10


class Side(IntEnum):
    RED  = 0
    BLUE = 1

    def opposite(self) -> "Side":
        return Side.BLUE if self == Side.RED else Side.RED


class Phase(IntEnum):
    SELECTING_SPY = 0
    PLAYING       = 1
    GAME_OVER     = 2


# ──────────────────────────────────────────────
# 棋子元数据
# ──────────────────────────────────────────────

PIECE_INFO: dict[int, dict] = {
    # ring: (颜色, 圈数, 线宽)  — 颜色避开红蓝（阵营色），用独立色系
    0:  {"name": "士兵", "tier": 0, "promotable": True,  "symbol": "S", "char": "兵", "ring": ((200, 200, 200), 1, 1)},  # 白灰  1细
    1:  {"name": "大臣", "tier": 1, "promotable": True,  "symbol": "M", "char": "臣", "ring": ((240, 220,  60), 2, 1)},  # 黄    2细
    2:  {"name": "军官", "tier": 1, "promotable": True,  "symbol": "O", "char": "官", "ring": ((  0, 220, 180), 2, 1)},  # 青绿  2细
    3:  {"name": "骑士", "tier": 2, "promotable": False, "symbol": "N", "char": "骑", "ring": ((255, 140,   0), 1, 4)},  # 橙    1粗
    4:  {"name": "刺客", "tier": 2, "promotable": False, "symbol": "A", "char": "刺", "ring": ((255, 140,   0), 1, 4)},  # 橙    1粗
    5:  {"name": "铁卫", "tier": 2, "promotable": False, "symbol": "I", "char": "卫", "ring": ((255, 140,   0), 1, 4)},  # 橙    1粗
    6:  {"name": "总督", "tier": 2, "promotable": False, "symbol": "C", "char": "督", "ring": ((210, 160, 255), 1, 4)},  # 浅紫  1粗
    7:  {"name": "教主", "tier": 2, "promotable": False, "symbol": "P", "char": "教", "ring": ((210, 160, 255), 1, 4)},  # 浅紫  1粗
    8:  {"name": "亲信", "tier": 3, "promotable": False, "symbol": "Y", "char": "亲", "ring": ((255, 230, 100), 2, 1)},  # 亮金  2细
    9:  {"name": "御史", "tier": 3, "promotable": False, "symbol": "E", "char": "御", "ring": ((255, 230, 100), 2, 1)},  # 亮金  2细
    10: {"name": "领主", "tier": 4, "promotable": False, "symbol": "L", "char": "主", "ring": ((255, 200,   0), 1, 4)},  # 纯金  1粗
}

# 方向向量
DIRS_8          = [(-1,-1),(-1,0),(-1,1),(0,-1),(0,1),(1,-1),(1,0),(1,1)]
DIRS_4_STRAIGHT = [(0,-1),(0,1),(-1,0),(1,0)]
DIRS_4_DIAGONAL = [(-1,-1),(-1,1),(1,-1),(1,1)]
KNIGHT_JUMPS    = [(-2,-1),(-2,1),(2,-1),(2,1),(-1,-2),(-1,2),(1,-2),(1,2)]

# 堡垒格坐标
FORTRESS_CELLS = {(2, 4), (6, 4)}


# ──────────────────────────────────────────────
# 数据类
# ──────────────────────────────────────────────

@dataclass
class Piece:
    id:   int
    type: PieceType
    side: Side
    x:    int
    y:    int
    promoted_this_turn: bool = False

    def symbol(self) -> str:
        return PIECE_INFO[int(self.type)]["symbol"]

    def name(self) -> str:
        return PIECE_INFO[int(self.type)]["name"]

    def tier(self) -> int:
        return PIECE_INFO[int(self.type)]["tier"]


@dataclass
class MoveRecord:
    piece_id:      int
    from_x:        int
    from_y:        int
    to_x:          int
    to_y:          int
    captured_id:   Optional[int]
    captured_type: Optional[PieceType]
    captured_side: Optional[Side]
    captured_x:    Optional[int]
    captured_y:    Optional[int]
    promoted_to:   Optional[PieceType]
    prev_type:     Optional[PieceType]           # 移动前棋子类型（悔棋还原用）
    was_spy_reveal: bool = False
    fortress_entered: bool = False               # 是否进入堡垒格
    fortress_exited:  bool = False               # 是否离开堡垒格
    prev_fortress_cooldown: dict = field(default_factory=dict)  # 悔棋用
    board_snapshot: Optional[list] = field(default=None, repr=False)
    # board_snapshot: apply_move 后的完整棋盘深拷贝，用于回溯


# ──────────────────────────────────────────────
# 间谍管理
# ──────────────────────────────────────────────

@dataclass
class SpyManager:
    """
    red_spies:  红方控制的间谍 ID 列表（实际是蓝方棋子，显示为红方）
    blue_spies: 蓝方控制的间谍 ID 列表（实际是红方棋子，显示为蓝方）
    """
    red_spies:  list[int] = field(default_factory=list)
    blue_spies: list[int] = field(default_factory=list)

    def display_side(self, piece_id: int, actual_side: Side) -> Side:
        """
        对外显示的阵营。
        间谍在揭露前维持原始阵营外观（不暴露身份）；
        揭露后 piece.side 已被 reveal_spies() 直接修改，此处直接返回 actual_side 即可。
        """
        return actual_side

    def is_spy(self, piece_id: int) -> bool:
        return piece_id in self.red_spies or piece_id in self.blue_spies

    def get_spies_of(self, side: Side) -> list[int]:
        """返回 side 方控制的间谍 ID 列表"""
        return self.red_spies if side == Side.RED else self.blue_spies

    def remove_piece(self, piece_id: int) -> None:
        """棋子被吃后从间谍列表移除"""
        if piece_id in self.red_spies:
            self.red_spies.remove(piece_id)
        if piece_id in self.blue_spies:
            self.blue_spies.remove(piece_id)


# ──────────────────────────────────────────────
# 棋盘与规则引擎
# ──────────────────────────────────────────────

class Board:
    """棋盘状态与所有规则计算。不含任何 UI 代码。"""

    def __init__(self) -> None:
        self.grid: list[list[Optional[Piece]]] = [[None]*9 for _ in range(9)]
        self._piece_map: dict[int, Piece] = {}   # id → Piece（快速查找）
        self._next_id = 0

    # ── 工厂方法 ──────────────────────────────

    @classmethod
    def new_game(cls) -> "Board":
        """按初始布局生成棋盘"""
        b = cls()
        layout = _initial_layout()
        for (x, y, t, s) in layout:
            b._place(t, s, x, y)
        return b

    def _place(self, ptype: PieceType, side: Side, x: int, y: int) -> Piece:
        p = Piece(id=self._next_id, type=ptype, side=side, x=x, y=y)
        self._next_id += 1
        self.grid[y][x] = p
        self._piece_map[p.id] = p
        return p

    # ── 查询辅助 ─────────────────────────────

    def get(self, x: int, y: int) -> Optional[Piece]:
        if 0 <= x <= 8 and 0 <= y <= 8:
            return self.grid[y][x]
        return None

    def in_bounds(self, x: int, y: int) -> bool:
        return 0 <= x <= 8 and 0 <= y <= 8

    def all_pieces(self) -> list[Piece]:
        return list(self._piece_map.values())

    def pieces_of(self, side: Side) -> list[Piece]:
        return [p for p in self._piece_map.values() if p.side == side]

    def pieces_of_type(self, ptype: PieceType, side: Side) -> list[Piece]:
        return [p for p in self._piece_map.values()
                if p.type == ptype and p.side == side]

    def get_piece_by_id(self, pid: int) -> Optional[Piece]:
        return self._piece_map.get(pid)

    # ── 移动计算（AI & UI 共用接口）──────────

    def get_moves(self, piece: Piece, fortress_cooldown: dict[int, int]) -> tuple[list[tuple], list[tuple]]:
        """
        返回 (movable_positions, capturable_positions)
        movable:    可走空格坐标列表
        capturable: 可吃子坐标列表
        堡垒格内的对方棋子不可被吃。
        棋子当前在堡垒格时，只能移动到周围8格空格，不能吃子。
        """
        # 堡垒格出口规则：覆盖所有棋子类型
        if (piece.x, piece.y) in FORTRESS_CELLS:
            return self._moves_fortress_exit(piece)

        t = piece.type
        if t == PieceType.SOLDIER:
            return self._moves_soldier(piece)
        if t == PieceType.MINISTER:
            return self._moves_sliding(piece, DIRS_4_STRAIGHT, 1)
        if t == PieceType.OFFICER:
            return self._moves_officer(piece)
        if t == PieceType.KNIGHT:
            return self._moves_knight(piece)
        if t == PieceType.ASSASSIN:
            return self._moves_assassin(piece)
        if t == PieceType.IRON_GUARD:
            return self._moves_sliding(piece, DIRS_4_STRAIGHT, 99)
        if t == PieceType.CHAMBERLAIN:
            return self._moves_sliding(piece, DIRS_4_DIAGONAL, 99)
        if t == PieceType.PRIEST:
            return self._moves_priest(piece)
        if t == PieceType.LOYALIST:
            return self._moves_loyalist(piece)
        if t == PieceType.CENSOR:
            return self._moves_sliding(piece, DIRS_8, 99)
        if t == PieceType.LORD:
            return self._moves_lord(piece)
        return [], []

    def _is_fortress_piece(self, x: int, y: int) -> bool:
        """该位置是堡垒格且有棋子"""
        return (x, y) in FORTRESS_CELLS and self.grid[y][x] is not None

    def _filter_fortress_capture(self, targets: list[tuple]) -> list[tuple]:
        """从可吃列表中移除堡垒格内的棋子"""
        return [(x, y) for (x, y) in targets if not self._is_fortress_piece(x, y)]

    def _moves_fortress_exit(self, p: Piece) -> tuple[list, list]:
        """
        堡垒格出口规则：
        - 只能移动到周围8格的空格，不能吃子
        - 不受原棋子类型移动规则约束（含士兵方向限制）
        - 若周围8格全被占则返回空列表（困死）
        """
        moves = []
        for dx, dy in DIRS_8:
            nx, ny = p.x + dx, p.y + dy
            if self.in_bounds(nx, ny) and self.grid[ny][nx] is None:
                moves.append((nx, ny))
        return moves, []   # capturable 始终为空

    def _moves_soldier(self, p: Piece) -> tuple[list, list]:
        fwd = 1 if p.side == Side.RED else -1   # 红方向y增大（对方阵地），蓝方向y减小
        moves, captures = [], []
        # 前进1格（仅空格）
        nx, ny = p.x, p.y + fwd
        if self.in_bounds(nx, ny) and self.grid[ny][nx] is None:
            moves.append((nx, ny))
        # 斜前方吃子
        for dx in (-1, 1):
            nx, ny = p.x + dx, p.y + fwd
            if self.in_bounds(nx, ny):
                target = self.grid[ny][nx]
                if target and target.side != p.side:
                    captures.append((nx, ny))
        return moves, self._filter_fortress_capture(captures)

    def _moves_sliding(self, p: Piece, dirs: list, max_dist: int) -> tuple[list, list]:
        moves, captures = [], []
        for dx, dy in dirs:
            for dist in range(1, max_dist + 1):
                nx, ny = p.x + dx * dist, p.y + dy * dist
                if not self.in_bounds(nx, ny):
                    break
                target = self.grid[ny][nx]
                if target is None:
                    moves.append((nx, ny))
                elif target.side == p.side:
                    break
                else:
                    captures.append((nx, ny))
                    break
        return moves, self._filter_fortress_capture(captures)

    def _moves_officer(self, p: Piece) -> tuple[list, list]:
        """
        军官移动规则：
        - 己方阵地（含中立区）：左前、正前、右前 3 方向各1步，可移动+可吃子
        - 对方阵地：额外增加正后方1步，共4方向
        - 红方己方阵地: y<=3，对方阵地: y>=5
        - 蓝方己方阵地: y>=5，对方阵地: y<=3
        - y=4 中立行不属于任何一方
        """
        fwd = 1 if p.side == Side.RED else -1   # 红方前进=y+1，蓝方前进=y-1
        in_enemy_territory = (
            p.y >= 5 if p.side == Side.RED else p.y <= 3
        )
        # 基础3方向：左前(dx=-1,dy=fwd)、正前(dx=0,dy=fwd)、右前(dx=1,dy=fwd)
        directions = [(-1, fwd), (0, fwd), (1, fwd)]
        # 对方阵地额外增加正后方
        if in_enemy_territory:
            directions.append((0, -fwd))

        moves, captures = [], []
        for dx, dy in directions:
            nx, ny = p.x + dx, p.y + dy
            if not self.in_bounds(nx, ny):
                continue
            target = self.grid[ny][nx]
            if target is None:
                moves.append((nx, ny))
            elif target.side != p.side:
                captures.append((nx, ny))
        return moves, self._filter_fortress_capture(captures)

    def _moves_knight(self, p: Piece) -> tuple[list, list]:
        moves, captures = [], []
        for dx, dy in KNIGHT_JUMPS:
            nx, ny = p.x + dx, p.y + dy
            if not self.in_bounds(nx, ny):
                continue
            target = self.grid[ny][nx]
            if target is None:
                moves.append((nx, ny))
            elif target.side != p.side:
                captures.append((nx, ny))
        return moves, self._filter_fortress_capture(captures)

    def _moves_assassin(self, p: Piece) -> tuple[list, list]:
        """
        刺客移动规则：
        - 普通移动：上下左右4方向直行，不限制格数，只能走空格，不可吃子（同中国象棋"车"）
        - 吃子：炮击——上下左右4方向，隔一个棋子（不分敌我）炮击对方棋子（同中国象棋"炮"）
        """
        # 普通移动：4方向直行，仅空格，遇子停止（同 _moves_sliding 的直线移动逻辑）
        moves = []
        for dx, dy in DIRS_4_STRAIGHT:
            for dist in range(1, 9):
                nx, ny = p.x + dx * dist, p.y + dy * dist
                if not self.in_bounds(nx, ny):
                    break
                target = self.grid[ny][nx]
                if target is None:
                    moves.append((nx, ny))
                else:
                    break  # 遇到任何棋子停止（不能吃子）
        # 炮击吃子
        cannon_captures = self._assassin_cannon(p.x, p.y, p.side)
        return moves, self._filter_fortress_capture(cannon_captures)

    def _assassin_cannon(self, x: int, y: int, side: Side) -> list[tuple]:
        results = []
        for dx, dy in DIRS_4_STRAIGHT:
            dist = 1
            cannon_pos = None
            while True:
                nx, ny = x + dx * dist, y + dy * dist
                if not self.in_bounds(nx, ny):
                    break
                if self.grid[ny][nx] is not None:
                    cannon_pos = (nx, ny)
                    break
                dist += 1
            if cannon_pos is None:
                continue
            target_dist = dist + 1
            while True:
                tx, ty = x + dx * target_dist, y + dy * target_dist
                if not self.in_bounds(tx, ty):
                    break
                target = self.grid[ty][tx]
                if target is not None:
                    if target.side != side:
                        results.append((tx, ty))
                    break
                target_dist += 1
        return results

    def _moves_priest(self, p: Piece) -> tuple[list, list]:
        # 常规8方向1步
        moves, captures = self._moves_sliding(p, DIRS_8, 1)
        # 翻越移动
        for dx, dy in DIRS_8:
            nx, ny = p.x + dx, p.y + dy
            if not self.in_bounds(nx, ny):
                continue
            # 相邻格必须有棋子才能触发翻越
            if self.grid[ny][nx] is None:
                continue
            # 沿同方向继续，跳过所有连续棋子
            dist = 2
            while True:
                cx, cy = p.x + dx * dist, p.y + dy * dist
                if not self.in_bounds(cx, cy):
                    break
                if self.grid[cy][cx] is None:
                    # 空格，可落下
                    if (cx, cy) not in moves:
                        moves.append((cx, cy))
                    break
                dist += 1
        return moves, self._filter_fortress_capture(captures)

    def _moves_loyalist(self, p: Piece) -> tuple[list, list]:
        """
        亲信移动规则：
        - 移动：8方向无限滑行，遇己方棋子或边界停止，不可进入 y=4 中立行
        - 吃子：只限周围8格内（1步范围）的对方棋子，同样受活动范围限制
        - 红方活动范围：y<=3；蓝方活动范围：y>=5
        """
        moves, captures = [], []

        # 无限滑行移动
        for dx, dy in DIRS_8:
            for dist in range(1, 9):
                nx, ny = p.x + dx * dist, p.y + dy * dist
                if not self.in_bounds(nx, ny):
                    break
                # 不可进入 y=4 中立行
                if ny == 4:
                    break
                target = self.grid[ny][nx]
                if target is None:
                    moves.append((nx, ny))
                else:
                    break  # 遇到任何棋子（敌我）停止滑行

        # 吃子：仅限周围8格1步
        for dx, dy in DIRS_8:
            nx, ny = p.x + dx, p.y + dy
            if not self.in_bounds(nx, ny):
                continue
            if ny == 4:  # 不可进入 y=4 中立行
                continue
            target = self.grid[ny][nx]
            if target is not None and target.side != p.side:
                captures.append((nx, ny))

        return moves, self._filter_fortress_capture(captures)

    def _moves_lord(self, p: Piece) -> tuple[list, list]:
        """领主：x==4 中立区禁止进入，8方向1步+直杀"""
        moves, captures = [], []
        for dx, dy in DIRS_8:
            nx, ny = p.x + dx, p.y + dy
            if not self.in_bounds(nx, ny):
                continue
            if ny == 4:  # 中立区禁止（y=4 中立行）
                continue
            target = self.grid[ny][nx]
            if target is None:
                moves.append((nx, ny))
            elif target.side != p.side:
                captures.append((nx, ny))
        # 直杀规则
        direct_kills = self._lord_direct_kills(p.x, p.y, p.side)
        captures += [c for c in direct_kills if c not in captures]
        return moves, self._filter_fortress_capture(captures)

    def _lord_direct_kills(self, x: int, y: int, side: Side) -> list[tuple]:
        """领主直杀：同直线/斜线且中间无子"""
        results = []
        enemy_lords = self.pieces_of_type(PieceType.LORD, side.opposite())
        for ep in enemy_lords:
            ex, ey = ep.x, ep.y
            dx, dy = ex - x, ey - y
            if dx == 0 or dy == 0 or abs(dx) == abs(dy):
                sx = 0 if dx == 0 else (1 if dx > 0 else -1)
                sy = 0 if dy == 0 else (1 if dy > 0 else -1)
                cx, cy = x + sx, y + sy
                blocked = False
                while (cx, cy) != (ex, ey):
                    if self.grid[cy][cx] is not None:
                        blocked = True
                        break
                    cx += sx
                    cy += sy
                if not blocked:
                    results.append((ex, ey))
        return results

    # ── 执行移动（AI & UI 共用接口）──────────

    def apply_move(
        self,
        piece: Piece,
        to_x: int,
        to_y: int,
        fortress_cooldown: dict[int, int],
        spy_manager: SpyManager,
    ) -> MoveRecord:
        """
        执行一步移动，返回 MoveRecord（含晋升信息）。
        调用方负责回合切换和胜负检测。
        """
        from_x, from_y = piece.x, piece.y
        captured_piece = self.grid[to_y][to_x]

        # 记录移动前状态（用于悔棋）
        prev_type = piece.type
        prev_fortress = dict(fortress_cooldown)

        # 执行移动
        self.grid[from_y][from_x] = None
        if captured_piece:
            del self._piece_map[captured_piece.id]
            spy_manager.remove_piece(captured_piece.id)

        piece.x, piece.y = to_x, to_y
        self.grid[to_y][to_x] = piece

        # 堡垒格判定
        entered_fortress = (to_x, to_y) in FORTRESS_CELLS
        if entered_fortress:
            fortress_cooldown[piece.id] = 1

        # 晋升判定
        promoted_to = None
        if not piece.promoted_this_turn:
            promo = _check_promotion(piece, captured_piece)
            if promo is not None:
                piece.type = promo
                piece.promoted_this_turn = True
                promoted_to = promo

        record = MoveRecord(
            piece_id=piece.id,
            from_x=from_x, from_y=from_y,
            to_x=to_x, to_y=to_y,
            captured_id=captured_piece.id if captured_piece else None,
            captured_type=captured_piece.type if captured_piece else None,
            captured_side=captured_piece.side if captured_piece else None,
            captured_x=captured_piece.x if captured_piece else None,
            captured_y=captured_piece.y if captured_piece else None,
            promoted_to=promoted_to,
            prev_type=prev_type,
            fortress_entered=entered_fortress,
            prev_fortress_cooldown=prev_fortress,
        )
        # §6.1 / §12.2.9：apply_move 末尾保存完整棋盘快照
        record.board_snapshot = copy.deepcopy(self.grid)
        return record

    def undo_move(self, record: MoveRecord, fortress_cooldown: dict[int, int]) -> None:
        """撤销一步移动（悔棋用）"""
        piece = self._piece_map[record.piece_id]

        # 还原棋子位置
        self.grid[record.to_y][record.to_x] = None
        piece.x, piece.y = record.from_x, record.from_y
        self.grid[record.from_y][record.from_x] = piece

        # 还原晋升
        if record.promoted_to is not None:
            piece.type = record.prev_type
        piece.promoted_this_turn = False

        # 还原被吃棋子
        if record.captured_id is not None:
            captured = Piece(
                id=record.captured_id,
                type=record.captured_type,
                side=record.captured_side,
                x=record.captured_x,
                y=record.captured_y,
            )
            self.grid[record.captured_y][record.captured_x] = captured
            self._piece_map[captured.id] = captured

        # 还原 fortress_cooldown
        fortress_cooldown.clear()
        fortress_cooldown.update(record.prev_fortress_cooldown)

    # ── 胜负检测 ──────────────────────────────

    def check_winner(self) -> Optional[Side]:
        """若某方没有 LORD 则返回胜者（对方），否则返回 None"""
        for side in (Side.RED, Side.BLUE):
            if not self.pieces_of_type(PieceType.LORD, side):
                return side.opposite()
        return None

    # ── 工具：序列化（用于存档）───────────────

    def to_dict(self) -> dict:
        pieces = []
        for p in self._piece_map.values():
            pieces.append({
                "id": p.id,
                "type": int(p.type),
                "side": int(p.side),
                "x": p.x,
                "y": p.y,
            })
        return {"pieces": pieces, "next_id": self._next_id}

    @classmethod
    def from_dict(cls, data: dict) -> "Board":
        b = cls()
        b._next_id = data["next_id"]
        for pd in data["pieces"]:
            p = Piece(
                id=pd["id"],
                type=PieceType(pd["type"]),
                side=Side(pd["side"]),
                x=pd["x"],
                y=pd["y"],
            )
            b.grid[p.y][p.x] = p
            b._piece_map[p.id] = p
        return b


# ──────────────────────────────────────────────
# 晋升规则
# ──────────────────────────────────────────────

def _capture_category(t: PieceType) -> str:
    t = int(t)
    if t == 0:        return "T0"
    if t in (2,3,4,5): return "OFFICER_TYPE"
    if t in (1,6,7):   return "MINISTER_TYPE"
    if t in (8,9):     return "T3"
    return "UNKNOWN"


def _check_promotion(piece: Piece, captured: Optional[Piece]) -> Optional[PieceType]:
    """
    返回晋升后类型，或 None。
    仅 SOLDIER / MINISTER / OFFICER 可晋升。
    """
    t = piece.type

    if t == PieceType.SOLDIER:
        if captured is not None:
            return PieceType.OFFICER
        # 走到底线升大臣（无吃子）
        # 注意：底线判定在此处不检查，由 apply_move 外层处理
        return None

    if t == PieceType.MINISTER and captured is not None:
        cat = _capture_category(captured.type)
        if cat in ("T0", "OFFICER_TYPE"):
            return PieceType.CHAMBERLAIN
        if cat == "MINISTER_TYPE":
            return PieceType.PRIEST
        if cat == "T3":
            return PieceType.CENSOR

    if t == PieceType.OFFICER and captured is not None:
        cat = _capture_category(captured.type)
        if cat == "T0":
            return PieceType.IRON_GUARD
        if cat == "OFFICER_TYPE":
            return PieceType.KNIGHT
        if cat == "MINISTER_TYPE":
            return PieceType.ASSASSIN
        if cat == "T3":
            return PieceType.CENSOR

    return None


def check_soldier_baseline(piece: Piece) -> bool:
    """士兵到达对方底线（走路，非吃子）→ 升大臣。红方底线y=8，蓝方底线y=0"""
    if piece.type != PieceType.SOLDIER:
        return False
    if piece.side == Side.RED and piece.y == 8:    # 红方前进到y=8
        return True
    if piece.side == Side.BLUE and piece.y == 0:   # 蓝方前进到y=0
        return True
    return False


# ──────────────────────────────────────────────
# 完整 GameState
# ──────────────────────────────────────────────

@dataclass
class GameState:
    phase:            Phase
    board:            Board
    current_side:     Side
    turn_number:      int
    spy_manager:      SpyManager
    history:          list[MoveRecord]
    winner:           Optional[Side]
    fortress_cooldown: dict[int, int]   # piece_id → 剩余冷却回合数
    spy_select_step:  int = 0           # 0~1，选间谍阶段进度（0=RED选，1=BLUE选）
    can_undo:         bool = True       # 揭露间谍后置 False
    moved_this_turn:  bool = False      # §7.4：本回合已移动则不可揭露间谍
    move_log: object = field(default=None)  # MoveLog 实例，由外部注入


    # ── 选间谍阶段 ────────────────────────────

    def spy_select_current_side(self) -> Side:
        """当前选间谍方：step=0→RED，step=1→BLUE"""
        return Side.RED if self.spy_select_step == 0 else Side.BLUE

    def do_spy_pick_minister(self, minister_id: int) -> bool:
        """
        当前方选择指定对方 MINISTER 为间谍（二选一中的"指定大臣"）。
        成功后推进 spy_select_step，返回是否成功。
        """
        if self.phase != Phase.SELECTING_SPY:
            return False
        sel_side = self.spy_select_current_side()
        piece = self.board.get_piece_by_id(minister_id)
        if piece is None or piece.type != PieceType.MINISTER:
            return False
        if piece.side == sel_side:          # 必须选对方的
            return False
        spies = self.spy_manager.get_spies_of(sel_side)
        if minister_id not in spies:
            spies.append(minister_id)
        turn = self.spy_select_step + 1     # step=0→回合1，step=1→回合2
        self.spy_select_step += 1
        self._log_spy_select(sel_side, turn)
        self._check_spy_phase_complete()
        return True

    def do_spy_random_soldier(self) -> list[int]:
        """
        当前方随机选2枚对方 SOLDIER 为间谍（二选一中的"随机士兵"）。
        成功后推进 spy_select_step，返回被选中的 piece_id 列表。
        """
        if self.phase != Phase.SELECTING_SPY:
            return []
        sel_side = self.spy_select_current_side()
        enemy_soldiers = [
            p for p in self.board.pieces_of(sel_side.opposite())
            if p.type == PieceType.SOLDIER
        ]
        k = min(2, len(enemy_soldiers))
        chosen = random.sample(enemy_soldiers, k)
        spies = self.spy_manager.get_spies_of(sel_side)
        ids = []
        for p in chosen:
            if p.id not in spies:
                spies.append(p.id)
            ids.append(p.id)
        turn = self.spy_select_step + 1     # step=0→回合1，step=1→回合2
        self.spy_select_step += 1
        self._log_spy_select(sel_side, turn)
        self._check_spy_phase_complete()
        return ids

    def _log_spy_select(self, side: "Side", turn: int) -> None:
        """向 move_log 写入含糊的间谍选择条目（不泄露具体目标）"""
        if self.move_log is None:
            return
        from move_log import MoveEntry
        entry = MoveEntry(
            turn=turn,
            side=side,
            piece_type=None,
            from_pos=None,
            to_pos=None,
            spy_reveal=False,
        )
        # 覆盖 notation：含糊表达，不记录具体棋子
        entry.notation = None   # 先置 None，让 add() 调用 auto_notation 前我们手动赋值
        from move_log import MoveLog as _ML
        color = "🔴" if int(side) == 0 else "🔵"
        entry.notation = f"{turn}. {color} 已选择间谍"
        self.move_log.entries.append(entry)
        self.move_log._current_index = len(self.move_log.entries) - 1

    def _check_spy_phase_complete(self) -> None:
        """step=2（双方均完成）→ 进入PLAYING，回合从3开始"""
        if self.spy_select_step >= 2:
            self.phase = Phase.PLAYING
            self.turn_number = 3            # 回合1=红方选谍，回合2=蓝方选谍，回合3起正式对局

    # ── 揭露间谍 ──────────────────────────────

    def reveal_spies(self) -> list[int]:
        """
        揭露当前方所有间谍：
        - 前置：本回合尚未移动棋子（§7.4 互斥）
        - 将间谍棋子 side 改为 current_side，清空列表
        - 回合切换（消耗当前回合）
        - 清空 history，之后不可悔棋
        返回被转化的 piece_id 列表。
        """
        spies = self.spy_manager.get_spies_of(self.current_side)
        converted = []
        for pid in list(spies):
            p = self.board.get_piece_by_id(pid)
            if p:
                p.side = self.current_side
                converted.append(pid)
        spies.clear()
        # 揭露后不可悔棋
        self.history.clear()
        self.can_undo = False
        # 写 MoveLog
        if self.move_log is not None:
            from move_log import MoveEntry
            entry = MoveEntry(
                turn=self.turn_number,
                side=self.current_side,
                piece_type=None,
                from_pos=None,
                to_pos=None,
                spy_reveal=True,
                spy_count=len(converted),
            )
            self.move_log.add(entry)
        # 揭露消耗当前回合，立即切换
        self._next_turn()
        return converted

    # ── 执行移动 ──────────────────────────────

    def do_move(self, piece: Piece, to_x: int, to_y: int) -> MoveRecord:
        """
        执行移动，更新状态，返回 MoveRecord。
        包含：堡垒格处理、晋升、士兵底线升职、胜负检测、回合切换。
        """
        record = self.board.apply_move(
            piece, to_x, to_y, self.fortress_cooldown, self.spy_manager
        )

        # 士兵底线升大臣（非吃子时）
        if (piece.type == PieceType.SOLDIER
                and record.captured_id is None
                and not piece.promoted_this_turn):
            if check_soldier_baseline(piece):
                piece.type = PieceType.MINISTER
                piece.promoted_this_turn = True
                record.promoted_to = PieceType.MINISTER
                record.prev_type = PieceType.SOLDIER
                # 底线晋升后快照需重新拍（升职后状态）
                record.board_snapshot = copy.deepcopy(self.board.grid)

        self.history.append(record)
        self.can_undo = True
        self.moved_this_turn = True

        # §6.1：apply_move 后同步写 MoveLog
        if self.move_log is not None:
            from move_log import MoveEntry
            entry = MoveEntry(
                turn=self.turn_number,
                side=self.current_side,
                piece_type=record.prev_type if record.promoted_to else piece.type,
                from_pos=(record.from_x, record.from_y),
                to_pos=(record.to_x, record.to_y),
                is_capture=record.captured_id is not None,
                captured_type=record.captured_type,
                promotion=record.promoted_to,
                fortress_enter=record.fortress_entered,
                fortress_exit=record.fortress_exited,
            )
            self.move_log.add(entry)

        # 胜负检测
        winner = self.board.check_winner()
        if winner is not None:
            self.winner = winner
            self.phase = Phase.GAME_OVER
            return record

        self._next_turn()
        return record

    def do_fortress_exit(self, piece: Piece, to_x: int, to_y: int) -> None:
        """
        堡垒格移出动作：不触发回合切换，仅解除锁定。
        """
        self.board.grid[piece.y][piece.x] = None
        piece.x, piece.y = to_x, to_y
        self.board.grid[to_y][to_x] = piece
        if piece.id in self.fortress_cooldown:
            del self.fortress_cooldown[piece.id]

    def undo(self) -> Optional[MoveRecord]:
        """
        悔棋1步。揭露间谍后不可悔棋。
        返回被撤销的 MoveRecord，或 None。
        """
        if not self.can_undo or not self.history:
            return None
        record = self.history.pop()
        if record.was_spy_reveal:
            # 不应存在（揭露后已清空），保险起见
            self.history.clear()
            return None
        self.board.undo_move(record, self.fortress_cooldown)
        # 切回上一方
        self.current_side = self.current_side.opposite()
        if self.current_side == Side.BLUE:
            self.turn_number = max(1, self.turn_number - 1)
        # 重置 promoted_this_turn
        for p in self.board.all_pieces():
            p.promoted_this_turn = False
        return record

    # ── 堡垒格状态查询 ────────────────────────

    def get_fortress_locked_piece(self) -> Optional[Piece]:
        """
        当前方是否有棋子被堡垒格锁定（cooldown > 0）。
        有则返回该棋子，否则返回 None。
        """
        for pid, cd in self.fortress_cooldown.items():
            if cd > 0:
                p = self.board.get_piece_by_id(pid)
                if p and p.side == self.current_side:
                    return p
        return None

    def get_fortress_exit_moves(self, piece: Piece) -> list[tuple]:
        """堡垒格内棋子可移动到的周围8格（空格）"""
        moves = []
        for dx, dy in DIRS_8:
            nx, ny = piece.x + dx, piece.y + dy
            if self.board.in_bounds(nx, ny) and self.board.grid[ny][nx] is None:
                moves.append((nx, ny))
        return moves

    # ── AI 接口 ───────────────────────────────

    def clone(self) -> "GameState":
        """
        返回当前局面的深拷贝，供 Minimax 搜索树使用。
        move_log 不拷贝（搜索过程不需要记谱）。
        """
        import copy
        gs = GameState(
            phase             = self.phase,
            board             = copy.deepcopy(self.board),
            current_side      = self.current_side,
            turn_number       = self.turn_number,
            spy_manager       = copy.deepcopy(self.spy_manager),
            history           = [],          # 搜索树不需要悔棋历史
            winner            = self.winner,
            fortress_cooldown = dict(self.fortress_cooldown),
            spy_select_step   = self.spy_select_step,
            can_undo          = False,
            moved_this_turn   = self.moved_this_turn,
            move_log          = None,        # 搜索树不记谱
        )
        return gs

    def get_all_legal_moves(self) -> list[tuple]:
        """
        返回当前方所有合法动作列表，供 AI 枚举。

        格式：
          ('move',   piece, to_x, to_y)  普通走棋（包含吃子）
          ('exit',   piece, to_x, to_y)  堡垒格移出
          ('reveal',)                    揭露间谍（本回合未移动时可用）

        堡垒锁定优先：当前方有棋子被堡垒锁定时，只返回 exit 动作。
        """
        if self.phase != Phase.PLAYING:
            return []

        actions: list[tuple] = []

        # 堡垒锁定优先：必须先移出
        locked = self.get_fortress_locked_piece()
        if locked is not None:
            for tx, ty in self.get_fortress_exit_moves(locked):
                actions.append(('exit', locked, tx, ty))
            return actions

        # 普通走棋动作
        for piece in self.board.pieces_of(self.current_side):
            moves, captures = self.board.get_moves(piece, self.fortress_cooldown)
            for tx, ty in moves + captures:
                actions.append(('move', piece, tx, ty))

        # 揭露间谍（本回合尚未移动且有存活间谍时可用）
        if not self.moved_this_turn:
            if self.count_alive_spies(self.current_side) > 0:
                actions.append(('reveal',))

        return actions

    def count_alive_spies(self, side: Side) -> int:
        """
        返回 side 方存活的间谍数量。
        存活条件：piece 仍在棋盘上（未被吃）且尚未揭露（side 仍是对方阵营）。
        """
        spies = self.spy_manager.get_spies_of(side)
        count = 0
        for pid in spies:
            p = self.board.get_piece_by_id(pid)
            if p is not None:
                # 未揭露前间谍显示为对方阵营；揭露后 p.side 已翻转
                # 只要棋子还在棋盘上即算存活
                count += 1
        return count

    # ── 内部辅助 ──────────────────────────────

    def _next_turn(self) -> None:
        self.current_side = self.current_side.opposite()
        if self.current_side == Side.RED:
            self.turn_number += 1
        # 重置 moved_this_turn（§7.4）
        self.moved_this_turn = False
        # 重置 promoted_this_turn
        for p in self.board.all_pieces():
            p.promoted_this_turn = False
        # 更新 fortress_cooldown（回合开始时减1）
        for pid in list(self.fortress_cooldown.keys()):
            self.fortress_cooldown[pid] -= 1
            if self.fortress_cooldown[pid] <= 0:
                del self.fortress_cooldown[pid]

    # ── 序列化 ────────────────────────────────

    def to_dict(self) -> dict:
        return {
            "version": 1,
            "phase": int(self.phase),
            "board": self.board.to_dict(),
            "current_side": int(self.current_side),
            "turn_number": self.turn_number,
            "spy_manager": {
                "red_spies": self.spy_manager.red_spies,
                "blue_spies": self.spy_manager.blue_spies,
            },
            "winner": int(self.winner) if self.winner is not None else None,
            "fortress_cooldown": {str(k): v for k, v in self.fortress_cooldown.items()},
            "spy_select_step": self.spy_select_step,
        }

    @classmethod
    def from_dict(cls, data: dict) -> "GameState":
        sm = SpyManager(
            red_spies=data["spy_manager"]["red_spies"],
            blue_spies=data["spy_manager"]["blue_spies"],
        )
        gs = cls(
            phase=Phase(data["phase"]),
            board=Board.from_dict(data["board"]),
            current_side=Side(data["current_side"]),
            turn_number=data["turn_number"],
            spy_manager=sm,
            history=[],
            winner=Side(data["winner"]) if data["winner"] is not None else None,
            fortress_cooldown={int(k): v for k, v in data["fortress_cooldown"].items()},
            spy_select_step=data.get("spy_select_step", 0),
        )
        return gs


# ──────────────────────────────────────────────
# 初始布局
# ──────────────────────────────────────────────

def _initial_layout() -> list[tuple[int, int, PieceType, Side]]:
    """
    返回 (x, y, PieceType, Side) 列表。
    布局依据设计文档 §3（2025版）：
      底线: L在x=4，G在x=3/5，M在x=0/1/2/6/7/8
      士兵: 锯齿两排，红方 y=3(x偶)+y=2(x奇)，蓝方镜像
      堡垒格 (2,4)(6,4) 初始为空
    """
    layout = []

    # ── 红方 (Side=RED)，共 18 枚 ──
    R = Side.RED
    # 底线 y=0
    layout.append((4, 0, PieceType.LORD,     R))           # 领主
    layout.append((3, 0, PieceType.LOYALIST, R))           # 亲信
    layout.append((5, 0, PieceType.LOYALIST, R))           # 亲信
    for x in (0, 1, 2, 6, 7, 8):                          # 大臣 ×6
        layout.append((x, 0, PieceType.MINISTER, R))
    # 士兵 y=3：x=0,2,4,6,8（5枚）
    for x in (0, 2, 4, 6, 8):
        layout.append((x, 3, PieceType.SOLDIER, R))
    # 士兵 y=2：x=1,3,5,7（4枚）
    for x in (1, 3, 5, 7):
        layout.append((x, 2, PieceType.SOLDIER, R))

    # ── 蓝方 (Side=BLUE)，镜像 x'=8-x, y'=8-y，共 18 枚 ──
    B = Side.BLUE
    # 底线 y=8
    layout.append((4, 8, PieceType.LORD,     B))           # 领主
    layout.append((5, 8, PieceType.LOYALIST, B))           # 亲信
    layout.append((3, 8, PieceType.LOYALIST, B))           # 亲信
    for x in (8, 7, 6, 2, 1, 0):                          # 大臣 ×6
        layout.append((x, 8, PieceType.MINISTER, B))
    # 士兵 y=5：x=0,2,4,6,8（5枚）
    for x in (0, 2, 4, 6, 8):
        layout.append((x, 5, PieceType.SOLDIER, B))
    # 士兵 y=6：x=1,3,5,7（4枚）
    for x in (1, 3, 5, 7):
        layout.append((x, 6, PieceType.SOLDIER, B))

    return layout


def new_game() -> GameState:
    """工厂函数：创建新游戏状态"""
    return GameState(
        phase=Phase.SELECTING_SPY,
        board=Board.new_game(),
        current_side=Side.RED,
        turn_number=0,
        spy_manager=SpyManager(),
        history=[],
        winner=None,
        fortress_cooldown={},
        spy_select_step=0,
    )
