"""
ai.py — 间谍象棋 AI 模块

结构：
  AIConfig       难度配置（搜索深度 / Human-Like 窗口 / 战术偏好）
  AITactics      战术系统（8个预设 + 开局/中盘/残局阶段混合）
  AIEvaluator    局面估值（特征提取 + 评分公式 + 走法排序分）
  AIMinimax      搜索核心（FindBestMove / SearchState / Alpha-Beta）
  AIController   调度入口（选间谍 / 走棋 / 揭露决策）

信息对称原则：
  - 大臣间谍：AI 知道具体 piece_id（选的时候记录）
  - 士兵间谍：AI 不知道具体哪枚，_known_spy_ids 里不存入，和人类感知一致
"""

from __future__ import annotations
import random
import copy
import time
import threading
from dataclasses import dataclass, field
from typing import Optional, TYPE_CHECKING

from engine import (
    GameState, Piece, PieceType, Side, Phase,
    FORTRESS_CELLS,
)


# ──────────────────────────────────────────────
# 棋子基础价值（与文档 Section 11.3 一致）
# ──────────────────────────────────────────────

PIECE_VALUE: dict[PieceType, float] = {
    PieceType.SOLDIER:     2.0,
    PieceType.MINISTER:    5.0,
    PieceType.OFFICER:     4.0,
    PieceType.KNIGHT:      6.0,
    PieceType.ASSASSIN:    6.0,
    PieceType.IRON_GUARD:  5.0,
    PieceType.CHAMBERLAIN: 5.0,
    PieceType.PRIEST:      5.0,
    PieceType.LOYALIST:    8.0,
    PieceType.CENSOR:      7.0,
    PieceType.LORD:      100.0,
}


# ──────────────────────────────────────────────
# AIConfig — 难度配置
# ──────────────────────────────────────────────

@dataclass
class AIConfig:
    search_depth:          int   = 2      # 迭代加深最大深度上限（安全阀）
    time_budget:           float = 1.0    # 每步最大思考时间（秒）
    top_candidate_count:   int   = 3      # Human-Like 候选短名单上限
    human_like_window:     float = 2.25   # 评分差在此范围内的走法均可入选
    prefer_minister_spy:   bool  = True   # 选间谍时优先选大臣
    can_reveal_spy:        bool  = True   # 是否允许揭露间谍
    think_delay:           float = 0.6    # AI 思考延迟（秒），UI 层使用

    # 揭露阈值 Phase 1（向后兼容，use_phase2=False 时生效）
    reveal_gain_threshold:       float = 1.5    # 普通揭露增益阈值
    reveal_multi_spy_step:       int   = 16     # 多间谍触发步数
    reveal_multi_spy_threshold:  float = -0.75  # 多间谍揭露阈值
    reveal_late_step:            int   = 22     # 后期揭露步数
    reveal_late_threshold:       float = -2.0   # 后期揭露阈值

    # 揭露阈值 Phase 2（默认启用：三层防线 + 对称搜索）
    use_phase2_reveal:            bool  = True  # True=Phase2，False=Phase1
    reveal_freeze_steps:          int   = 6     # 前 N 步绝不揭露（立即吃将军例外）
    reveal_threshold_early:       float = 3.5   # 步数 <10 时的阈值（最严格）
    reveal_threshold_mid:         float = 2.5   # 步数 10~21 时的阈值
    reveal_threshold_late:        float = 1.5   # 步数 >=22 时的阈值（放宽）


# 预设难度
def ai_config_easy() -> AIConfig:
    return AIConfig(
        search_depth=4,         time_budget=0.5,
        human_like_window=4.0,  think_delay=0.3,
        reveal_freeze_steps=3,
        reveal_threshold_early=2.0, reveal_threshold_mid=1.5, reveal_threshold_late=1.0,
    )

def ai_config_normal() -> AIConfig:
    return AIConfig(
        search_depth=6,         time_budget=1.0,
        human_like_window=2.0,  think_delay=0.6,
        reveal_freeze_steps=6,
        reveal_threshold_early=3.5, reveal_threshold_mid=2.5, reveal_threshold_late=1.5,
    )

def ai_config_hard() -> AIConfig:
    return AIConfig(
        search_depth=8,         time_budget=5.0,
        human_like_window=0.8,  think_delay=0.8,
        reveal_freeze_steps=8,
        reveal_threshold_early=4.5, reveal_threshold_mid=3.5, reveal_threshold_late=2.5,
    )

def ai_config_hell() -> AIConfig:
    return AIConfig(
        search_depth=12,        time_budget=10.0,
        human_like_window=0.0,  think_delay=1.0,
        reveal_freeze_steps=10,
        reveal_threshold_early=5.5, reveal_threshold_mid=4.0, reveal_threshold_late=3.0,
    )


# ──────────────────────────────────────────────
# AITactics — 战术系统
# ──────────────────────────────────────────────

@dataclass
class TacticProfile:
    name:            str
    aggression:      float = 0.0
    spy_focus:       float = 0.0
    center_control:  float = 0.0
    fortress_ctrl:   float = 0.0
    trade_value:     float = 0.0
    lord_protection: float = 0.0
    mobility:        float = 0.0
    prefer_minister_spy_chance: float = 0.5


# 8 个预设战术库（与文档 Section 4.2 一致）
PRESET_TACTICS: list[TacticProfile] = [
    TacticProfile("猛攻",  aggression=+1.5, spy_focus=-0.5, center_control=+0.5, fortress_ctrl= 0.0, trade_value=+1.2, lord_protection=-0.5, mobility=+0.8, prefer_minister_spy_chance=0.4),
    TacticProfile("稳守",  aggression=-0.8, spy_focus= 0.0, center_control=+0.3, fortress_ctrl=+0.5, trade_value=-0.5, lord_protection=+1.5, mobility=-0.3, prefer_minister_spy_chance=0.6),
    TacticProfile("暗流",  aggression= 0.0, spy_focus=+2.0, center_control= 0.0, fortress_ctrl= 0.0, trade_value=+0.3, lord_protection=+0.2, mobility=+0.5, prefer_minister_spy_chance=0.8),
    TacticProfile("速决",  aggression=+1.0, spy_focus=-1.0, center_control=+0.8, fortress_ctrl= 0.0, trade_value=+1.0, lord_protection=-0.3, mobility=+1.5, prefer_minister_spy_chance=0.3),
    TacticProfile("蚕食",  aggression=+0.5, spy_focus= 0.0, center_control=+0.4, fortress_ctrl= 0.0, trade_value=+1.5, lord_protection=+0.5, mobility=-0.2, prefer_minister_spy_chance=0.5),
    TacticProfile("控中",  aggression= 0.0, spy_focus= 0.0, center_control=+2.0, fortress_ctrl=+0.3, trade_value= 0.0, lord_protection=+0.5, mobility= 0.0, prefer_minister_spy_chance=0.5),
    TacticProfile("奇袭",  aggression=+1.3, spy_focus=+0.5, center_control=-1.0, fortress_ctrl=-0.5, trade_value=+0.8, lord_protection=-0.8, mobility=+1.5, prefer_minister_spy_chance=0.7),
    TacticProfile("固垒",  aggression=-0.5, spy_focus= 0.0, center_control=-0.3, fortress_ctrl=+2.0, trade_value=-0.3, lord_protection=+1.0, mobility=-0.5, prefer_minister_spy_chance=0.5),
]


def _blend(main: TacticProfile, aux: TacticProfile, ratio: float) -> TacticProfile:
    """按比例混合两个战术（ratio = main 权重）"""
    r = ratio
    a = 1.0 - ratio
    return TacticProfile(
        name             = f"{main.name}+{aux.name}",
        aggression       = main.aggression      * r + aux.aggression      * a,
        spy_focus        = main.spy_focus       * r + aux.spy_focus       * a,
        center_control   = main.center_control  * r + aux.center_control  * a,
        fortress_ctrl    = main.fortress_ctrl   * r + aux.fortress_ctrl   * a,
        trade_value      = main.trade_value     * r + aux.trade_value     * a,
        lord_protection  = main.lord_protection * r + aux.lord_protection * a,
        mobility         = main.mobility        * r + aux.mobility        * a,
        prefer_minister_spy_chance = (
            main.prefer_minister_spy_chance * r + aux.prefer_minister_spy_chance * a
        ),
    )


class AITactics:
    """
    战术管理器：开局随机选主/辅战术，按步数切换开局/中盘/残局阶段。
    """

    def __init__(self) -> None:
        main = random.choice(PRESET_TACTICS)
        aux  = random.choice([t for t in PRESET_TACTICS if t is not main])
        self._main = main
        self._aux  = aux
        self.blended: TacticProfile = _blend(main, aux, 0.7)  # 开局默认
        self._phase = "opening"

    def update(self, step_count: int) -> None:
        """根据步数更新战术阶段"""
        if step_count <= 12:
            phase = "opening"
        elif step_count <= 25:
            phase = "midgame"
        else:
            phase = "endgame"

        if phase == self._phase:
            return
        self._phase = phase

        if phase == "opening":
            self.blended = _blend(self._main, self._aux, 0.7)
        elif phase == "midgame":
            self.blended = copy.copy(self._main)
        else:  # endgame
            b = copy.copy(self._main)
            bonus = 0.3 + min((step_count - 26) * 0.05, 0.5)
            b.aggression      += bonus
            b.lord_protection += bonus
            self.blended = b

    def get_tactic_bonus(
        self,
        action: tuple,
        gs: GameState,
        enemy_lord: Optional[Piece],
        own_lord: Optional[Piece],
    ) -> float:
        """计算走法的战术奖励分（叠加在基础排序分上）"""
        if action[0] != 'move':
            return 0.0

        _, piece, tx, ty = action
        t = self.blended
        bonus = 0.0

        # aggression：逼近敌方将军 + 吃子
        if t.aggression != 0 and enemy_lord:
            dist = abs(tx - enemy_lord.x) + abs(ty - enemy_lord.y)
            bonus += t.aggression * max(0.0, (8 - dist) * 0.5)
            target = gs.board.get(tx, ty)
            if target and target.side != piece.side:
                bonus += t.aggression * PIECE_VALUE.get(target.type, 0) * 0.6

        # spy_focus：远离己方将军（间谍保护）
        if t.spy_focus != 0 and own_lord:
            dist = abs(tx - own_lord.x) + abs(ty - own_lord.y)
            bonus += t.spy_focus * max(0.0, dist - 3) * 0.3

        # center_control：抢占棋盘中心
        if t.center_control != 0:
            center_dist = abs(tx - 4) + abs(ty - 4)
            bonus += t.center_control * max(0.0, 5 - center_dist) * 0.6

        # fortress_ctrl：进入堡垒
        if t.fortress_ctrl != 0 and (tx, ty) in FORTRESS_CELLS:
            bonus += t.fortress_ctrl * 3.0

        # trade_value：兑子意愿
        if t.trade_value != 0:
            target = gs.board.get(tx, ty)
            if target and target.side != piece.side:
                tv = PIECE_VALUE.get(target.type, 0)
                pv = PIECE_VALUE.get(piece.type, 0)
                ratio = tv / max(1.0, pv)
                bonus += t.trade_value * (ratio - 0.8) * 3.0

        # lord_protection：护将
        if t.lord_protection != 0 and own_lord:
            dist = abs(tx - own_lord.x) + abs(ty - own_lord.y)
            bonus += t.lord_protection * max(0.0, 5 - dist) * 0.5

        # mobility：远距离移动
        if t.mobility != 0:
            move_dist = abs(tx - piece.x) + abs(ty - piece.y)
            bonus += t.mobility * move_dist * 0.4

        return bonus


# ──────────────────────────────────────────────
# AIEvaluator — 局面估值
# ──────────────────────────────────────────────

class AIEvaluator:
    """
    纯函数局面估值器（无状态）。
    所有方法均为静态方法，可单独调用。
    """

    # ── 辅助几何 ──────────────────────────────

    @staticmethod
    def center_distance(x: int, y: int) -> float:
        return abs(x - 4) + abs(y - 4)

    @staticmethod
    def advance_score(side: Side, y: int) -> float:
        """棋子距对方底线的推进分（红方 y 越大越好，蓝方 y 越小越好）"""
        if side == Side.RED:
            return float(y)       # y=0 最后方，y=8 底线
        else:
            return float(8 - y)   # y=8 最后方，y=0 底线

    @staticmethod
    def lord_guard_bonus(piece: Piece, lord: Optional[Piece]) -> float:
        """棋子距己方将军越近，护将奖励越高"""
        if lord is None:
            return 0.0
        dist = abs(piece.x - lord.x) + abs(piece.y - lord.y)
        return max(0.0, 6.0 - dist)

    @staticmethod
    def get_lord(gs: GameState, side: Side) -> Optional[Piece]:
        lords = gs.board.pieces_of_type(PieceType.LORD, side)
        return lords[0] if lords else None

    # ── 间谍威胁分 ────────────────────────────

    @staticmethod
    def hidden_spy_potential(
        gs: GameState,
        actor_side: Side,
        known_spy_ids: set[int],
    ) -> float:
        """
        actor_side 方未揭露的间谍潜在威胁分。
        known_spy_ids：AI 层已知的间谍 id（仅大臣间谍），士兵间谍不在此集合。
        揭露后返回 0（威胁已实现，不再是隐藏价值）。
        """
        spies = gs.spy_manager.get_spies_of(actor_side)
        if not spies:
            return 0.0

        enemy_lord = AIEvaluator.get_lord(gs, actor_side.opposite())
        total = 0.0
        for pid in spies:
            p = gs.board.get_piece_by_id(pid)
            if p is None:
                continue
            score = PIECE_VALUE.get(p.type, 0) * 1.25
            if enemy_lord:
                dist = abs(p.x - enemy_lord.x) + abs(p.y - enemy_lord.y)
                score += max(0.0, 8.0 - dist)
            total += score
        return total

    @staticmethod
    def has_immediate_lord_capture(gs: GameState, side: Side) -> bool:
        """side 方本回合是否能直接吃对方将军"""
        enemy_lords = gs.board.pieces_of_type(PieceType.LORD, side.opposite())
        if not enemy_lords:
            return False
        lord_pos = {(p.x, p.y) for p in enemy_lords}
        for piece in gs.board.pieces_of(side):
            _, caps = gs.board.get_moves(piece, gs.fortress_cooldown)
            if any(pos in lord_pos for pos in caps):
                return True
        return False

    # ── 主评估函数 ────────────────────────────

    @staticmethod
    def evaluate(
        gs: GameState,
        perspective: Side,
        known_spy_ids: set[int],
        soldier_spy_count: int,   # 对方视角：对方未揭露士兵间谍数量（用于吃子惩罚）
    ) -> float:
        """
        从 perspective 方视角对 gs 评分。
        正值 = 对 perspective 方有利。
        """
        enemy = perspective.opposite()

        own_lord   = AIEvaluator.get_lord(gs, perspective)
        enemy_lord = AIEvaluator.get_lord(gs, enemy)

        if own_lord is None and enemy_lord is None:
            return 0.0
        if own_lord is None:
            return -100000.0
        if enemy_lord is None:
            return  100000.0

        score = 0.0

        # 棋子价值净差
        for p in gs.board.all_pieces():
            sign = 1.0 if p.side == perspective else -1.0
            score += PIECE_VALUE.get(p.type, 0) * sign

        # 推进奖励（士兵 / 大臣 / 御史）
        for p in gs.board.all_pieces():
            sign = 1.0 if p.side == perspective else -1.0
            adv  = AIEvaluator.advance_score(p.side, p.y)
            if p.type == PieceType.SOLDIER:
                score += adv * 0.15 * sign
            elif p.type == PieceType.MINISTER:
                score += adv * 0.10 * sign
            elif p.type == PieceType.CENSOR:
                score += adv * 0.12 * sign
            elif p.type == PieceType.OFFICER:
                score += adv * 0.08 * sign

        # 中心控制（大臣/刺客/骑士/铁卫/总督/教主/御史）
        CENTER_TYPES = {
            PieceType.MINISTER, PieceType.ASSASSIN, PieceType.KNIGHT,
            PieceType.IRON_GUARD, PieceType.CHAMBERLAIN, PieceType.PRIEST,
            PieceType.CENSOR,
        }
        for p in gs.board.all_pieces():
            if p.type not in CENTER_TYPES:
                continue
            sign = 1.0 if p.side == perspective else -1.0
            cd   = AIEvaluator.center_distance(p.x, p.y)
            score += max(0.0, 4.5 - cd) * 0.08 * sign

        # 护将奖励
        own_lord_p   = own_lord
        enemy_lord_p = enemy_lord
        for p in gs.board.all_pieces():
            sign = 1.0 if p.side == perspective else -1.0
            lord = own_lord_p if p.side == perspective else enemy_lord_p
            if p.type == PieceType.LOYALIST:
                score += AIEvaluator.lord_guard_bonus(p, lord) * 0.3 * sign
            elif p.type == PieceType.LORD:
                # 将军推进惩罚
                adv = AIEvaluator.advance_score(p.side, p.y)
                score -= adv * 0.15 * sign

        # 堡垒将军奖励
        for p in gs.board.all_pieces():
            if p.type == PieceType.LORD and (p.x, p.y) in FORTRESS_CELLS:
                sign = 1.0 if p.side == perspective else -1.0
                score += 1.5 * sign

        # 隐藏间谍威胁分
        own_spy_potential   = AIEvaluator.hidden_spy_potential(gs, perspective, known_spy_ids)
        enemy_spy_potential = AIEvaluator.hidden_spy_potential(gs, enemy, set())
        score += own_spy_potential   * 0.4
        score -= enemy_spy_potential * 0.4

        # 即时将军奖励/惩罚
        if AIEvaluator.has_immediate_lord_capture(gs, perspective):
            score += 8.0
        if AIEvaluator.has_immediate_lord_capture(gs, enemy):
            score -= 8.0

        return score

    # ── 走法排序分 ────────────────────────────

    @staticmethod
    def score_move_ordering(
        action: tuple,
        gs: GameState,
        enemy_lord: Optional[Piece],
        soldier_spy_count: int,
    ) -> float:
        """
        为走法打排序分（越高越优先展开，让 Alpha-Beta 更高效）。
        soldier_spy_count：对方未揭露士兵间谍数（用于吃士兵犹豫惩罚）。
        """
        if action[0] in ('exit', 'reveal'):
            return 5.0   # 堡垒移出 / 揭露：中等优先

        _, piece, tx, ty = action
        target = gs.board.get(tx, ty)

        # 吃将军：最高优先
        if target and target.type == PieceType.LORD:
            return 100000.0

        score = 0.0

        if target:
            tv = PIECE_VALUE.get(target.type, 0)
            pv = PIECE_VALUE.get(piece.type, 0)
            score += tv * 1.2           # 吃子得分
            score -= pv * 0.3           # 自身价值风险
            # 吃士兵犹豫惩罚（对方可能有士兵间谍揭露反制）
            if target.type == PieceType.SOLDIER and soldier_spy_count > 0:
                score -= soldier_spy_count * 0.2

        # 进入堡垒
        if (tx, ty) in FORTRESS_CELLS:
            score += 1.0

        # 逼近敌方将军
        if enemy_lord:
            dist = abs(tx - enemy_lord.x) + abs(ty - enemy_lord.y)
            score += max(0.0, 6.0 - dist) * 0.4

        # 中心控制
        cd = abs(tx - 4) + abs(ty - 4)
        score += max(0.0, 5.0 - cd) * 0.2

        # 推进
        score += AIEvaluator.advance_score(piece.side, ty) * 0.1

        # 士兵走棋小奖励
        if piece.type == PieceType.SOLDIER:
            score += 0.3

        # 将军移动惩罚
        if piece.type == PieceType.LORD:
            score -= 1.5

        return score


# ──────────────────────────────────────────────
# AIMinimax — 搜索核心
# ──────────────────────────────────────────────

class _Timeout(Exception):
    """搜索超时信号，由 _search 内部抛出，find_best_move 捕获"""
    pass


class AIMinimax:
    """
    Minimax + Alpha-Beta 剪枝搜索。
    每次递归对 gs.clone() 操作，不修改原始局面。
    """

    def __init__(
        self,
        config: AIConfig,
        tactics: AITactics,
        known_spy_ids: set[int],
    ) -> None:
        self.config        = config
        self.tactics       = tactics
        self.known_spy_ids = known_spy_ids

    # ── 应用动作到克隆局面 ─────────────────────

    @staticmethod
    def apply_action(gs: GameState, action: tuple) -> GameState:
        """在 gs 的克隆上执行 action，返回新局面"""
        ngs = gs.clone()
        if action[0] == 'move':
            _, piece, tx, ty = action
            # 在克隆里找对应棋子
            p = ngs.board.get_piece_by_id(piece.id)
            if p:
                ngs.do_move(p, tx, ty)
        elif action[0] == 'exit':
            _, piece, tx, ty = action
            p = ngs.board.get_piece_by_id(piece.id)
            if p:
                ngs.do_fortress_exit(p, tx, ty)
                ngs._next_turn()
        elif action[0] == 'reveal':
            ngs.reveal_spies()
        return ngs

    # ── 生成并排序走法 ────────────────────────

    def _generate_sorted_actions(
        self,
        gs: GameState,
        soldier_spy_count: int,
    ) -> list[tuple]:
        actions = gs.get_all_legal_moves()
        if not actions:
            return []

        enemy_lord = AIEvaluator.get_lord(gs, gs.current_side.opposite())
        own_lord   = AIEvaluator.get_lord(gs, gs.current_side)

        scored = []
        for a in actions:
            base   = AIEvaluator.score_move_ordering(a, gs, enemy_lord, soldier_spy_count)
            tactic = self.tactics.get_tactic_bonus(a, gs, enemy_lord, own_lord)
            scored.append((base + tactic, a))

        scored.sort(key=lambda x: x[0], reverse=True)
        return [a for _, a in scored]

    # ── Minimax 递归 ──────────────────────────

    def _search(
        self,
        gs: GameState,
        depth: int,
        alpha: float,
        beta: float,
        ai_side: Side,
        soldier_spy_count: int,
        deadline: float,
    ) -> float:
        # 超时检查（每个节点都检查，开销极低）
        if time.monotonic() > deadline:
            raise _Timeout()

        # 终止条件：游戏结束
        if gs.phase == Phase.GAME_OVER:
            if gs.winner == ai_side:
                return 100000.0
            elif gs.winner is not None:
                return -100000.0
            return 0.0

        # 叶节点：静态估值
        if depth == 0:
            return AIEvaluator.evaluate(gs, ai_side, self.known_spy_ids, soldier_spy_count)

        actions = self._generate_sorted_actions(gs, soldier_spy_count)
        if not actions:
            # 无合法走法：被困
            penalty = 1.5
            base    = AIEvaluator.evaluate(gs, ai_side, self.known_spy_ids, soldier_spy_count)
            return (base - penalty) if gs.current_side == ai_side else (base + penalty)

        is_maximizing = (gs.current_side == ai_side)

        if is_maximizing:
            val = -float('inf')
            for action in actions:
                ngs   = self.apply_action(gs, action)
                score = self._search(ngs, depth - 1, alpha, beta, ai_side, soldier_spy_count, deadline)
                val   = max(val, score)
                alpha = max(alpha, val)
                if alpha >= beta:
                    break   # Beta 剪枝
            return val
        else:
            val = float('inf')
            for action in actions:
                ngs   = self.apply_action(gs, action)
                score = self._search(ngs, depth - 1, alpha, beta, ai_side, soldier_spy_count, deadline)
                val   = min(val, score)
                beta  = min(beta, val)
                if alpha >= beta:
                    break   # Alpha 剪枝
            return val

    # ── 根节点选步 ────────────────────────────

    def find_best_move(
        self,
        gs: GameState,
        ai_side: Side,
        soldier_spy_count: int,
        step_count: int = 999,
    ) -> Optional[tuple]:
        """
        迭代加深搜索，在 time_budget 秒内尽量搜深。
        每完成一层深度就保存当前最优结果；超时时返回上一层完成的结果。
        """
        actions = self._generate_sorted_actions(gs, soldier_spy_count)
        # 冻结期内根节点排除 reveal
        if step_count < self.config.reveal_freeze_steps:
            actions = [a for a in actions if a[0] != 'reveal']
        if not actions:
            return None

        deadline    = time.monotonic() + self.config.time_budget
        max_depth   = self.config.search_depth
        best_action = actions[0]   # 兜底：至少返回排序第一的走法

        for depth in range(1, max_depth + 1):
            inner_depth = max(0, depth - 1)
            scored: list[tuple[float, tuple]] = []
            try:
                for action in actions:
                    ngs = self.apply_action(gs, action)
                    if ngs.phase == Phase.GAME_OVER and ngs.winner == ai_side:
                        scored.append((100000.0, action))
                    else:
                        score = self._search(
                            ngs, inner_depth,
                            -float('inf'), float('inf'),
                            ai_side, soldier_spy_count, deadline,
                        )
                        scored.append((score, action))
            except _Timeout:
                # 本层未完成，用上一层结果
                break

            # 本层完整跑完，更新最优结果
            scored.sort(key=lambda x: x[0], reverse=True)
            best_score = scored[0][0]

            # 构建 Human-Like 候选短名单
            window    = self.config.human_like_window
            max_cands = self.config.top_candidate_count
            shortlist: list[tuple[float, tuple]] = []
            for score, action in scored:
                if len(shortlist) >= max_cands:
                    break
                if shortlist and (best_score - score) > window:
                    break
                shortlist.append((score, action))

            # 加权随机选一个作为本层最优
            if window <= 0.0:
                # 地狱难度：直接取最优，不随机
                best_action = scored[0][1]
            else:
                weights = [max(0.05, window - (best_score - s) + 0.4) for s, _ in shortlist]
                total   = sum(weights)
                r       = random.uniform(0, total)
                cumul   = 0.0
                for w, (_, action) in zip(weights, shortlist):
                    cumul += w
                    if r <= cumul:
                        best_action = action
                        break
                else:
                    best_action = shortlist[-1][1]

            # 走法已排序供下一层优先展开（移动排序继承）
            actions = [a for _, a in scored]

        return best_action

    # ── 揭露决策 ──────────────────────────────

    def should_reveal_spy(
        self,
        gs: GameState,
        ai_side: Side,
        step_count: int,
        soldier_spy_count: int,
    ) -> bool:
        """
        判断当前是否应该揭露间谍。
        Phase 2（默认）：三层防线 + 对称搜索，对应文档 Section 14.5 Phase 2。
        Phase 1（向后兼容）：固定阈值，use_phase2_reveal=False 时生效。
        """
        if not self.config.can_reveal_spy:
            return False
        if gs.count_alive_spies(ai_side) == 0:
            return False

        cfg = self.config

        if cfg.use_phase2_reveal:
            return self._should_reveal_phase2(gs, ai_side, step_count, soldier_spy_count)
        else:
            return self._should_reveal_phase1(gs, ai_side, step_count, soldier_spy_count)

    # ── 揭露风险评估 ─────────────────────────────

    @staticmethod
    def _minister_spy_capture_risk(
        revealed_gs: GameState,
        ai_side: Side,
        converted_ids: list[int],
    ) -> float:
        """
        揭露后，评估己方新转化大臣被敌方下一步直接吃掉的风险惩罚分。

        规则：
        1. 枚举敌方所有可捕获目标格，若某个转化大臣在其中 → 该大臣处于危险
        2. 若己方领主同时处于将军（敌方也可以直接吃领主）→ 敌方有更紧迫任务，
           危险大臣的惩罚减半（敌方可能优先应对领主威胁而顾不上吃大臣）
        3. 危险大臣惩罚 = 大臣价值 * 惩罚系数（默认 1.5，有将军威胁时减为 0.75）

        返回：惩罚分（>=0，0 表示无风险）
        """
        if not converted_ids:
            return 0.0

        enemy = ai_side.opposite()

        # 收集转化大臣的位置
        danger_positions: set[tuple[int, int]] = set()
        for pid in converted_ids:
            p = revealed_gs.board.get_piece_by_id(pid)
            if p is not None:
                danger_positions.add((p.x, p.y))
        if not danger_positions:
            return 0.0

        # 枚举敌方所有可吃格
        enemy_capture_set: set[tuple[int, int]] = set()
        for ep in revealed_gs.board.pieces_of(enemy):
            _, caps = revealed_gs.board.get_moves(ep, revealed_gs.fortress_cooldown)
            enemy_capture_set.update(caps)

        # 找出被威胁的转化大臣
        threatened = danger_positions & enemy_capture_set
        if not threatened:
            return 0.0

        # 判断己方领主是否同时被将军（敌方有更紧迫任务）
        own_lord = AIEvaluator.get_lord(revealed_gs, ai_side)
        lord_under_check = (
            own_lord is not None
            and (own_lord.x, own_lord.y) in enemy_capture_set
        )

        # 被威胁的大臣数量
        n_threatened = len(threatened)
        minister_val = PIECE_VALUE[PieceType.MINISTER]  # 5.0

        if lord_under_check:
            # 己方领主被威胁：敌方优先级可能不在吃大臣，惩罚减半
            penalty = minister_val * 0.75 * n_threatened
        else:
            # 敌方下回合可以专心吃大臣，满额惩罚
            penalty = minister_val * 1.5 * n_threatened

        return penalty

    def _should_reveal_phase2(
        self,
        gs: GameState,
        ai_side: Side,
        step_count: int,
        soldier_spy_count: int,
    ) -> bool:
        """Phase 2：前N步冻结 + 三级分级阈值 + 对称搜索（文档 Section 3 P1）"""
        cfg = self.config
        side_name = "RED" if ai_side == 0 else "BLUE"

        print(f"[AI-REVEAL] side={side_name} turn_number={gs.turn_number} step_count={step_count} "
              f"freeze_steps={cfg.reveal_freeze_steps} alive_spies={gs.count_alive_spies(ai_side)}")

        # 第一层：前 freeze_steps 步绝不揭露
        if step_count < cfg.reveal_freeze_steps:
            print(f"[AI-REVEAL] -> FROZEN (step_count={step_count} < freeze_steps={cfg.reveal_freeze_steps})")
            return False

        # 构建揭露后局面，并记录被转化的大臣 id
        revealed_gs = gs.clone()
        converted_ids = revealed_gs.reveal_spies()   # reveal_spies 返回转化的 piece id 列表

        # 揭露后能立即吃将军 → 直接揭露
        can_kill = AIEvaluator.has_immediate_lord_capture(revealed_gs, ai_side)
        print(f"[AI-REVEAL] -> immediate_lord_capture={can_kill}")
        if can_kill:
            print(f"[AI-REVEAL] -> REVEAL (immediate kill)")
            return True

        # 大臣间谍被吃风险惩罚：施加在 reveal_score 上，让 gain 下降
        minister_risk = self._minister_spy_capture_risk(revealed_gs, ai_side, converted_ids or [])
        print(f"[AI-REVEAL] -> minister_risk_penalty={minister_risk:.2f}")

        # 第二层：分级阈值
        if step_count < 10:
            threshold = cfg.reveal_threshold_early   # 3.5，最严格
        elif step_count < 22:
            threshold = cfg.reveal_threshold_mid     # 2.5
        else:
            threshold = cfg.reveal_threshold_late    # 1.5，放宽

        # 第三层：对称搜索（双方深度相同，避免非对称比较）
        # 揭露决策用较短时间预算（不超过总预算的一半，最多2秒）
        reveal_budget = min(cfg.time_budget * 0.5, 2.0)
        reveal_deadline = time.monotonic() + reveal_budget
        try:
            current_score = self._search(gs,          cfg.search_depth, -float('inf'), float('inf'),
                                         ai_side, soldier_spy_count, reveal_deadline)
            reveal_score  = self._search(revealed_gs, cfg.search_depth, -float('inf'), float('inf'),
                                         ai_side, soldier_spy_count, reveal_deadline)
        except _Timeout:
            # 搜索超时，保守处理：不揭露
            print(f"[AI-REVEAL] -> TIMEOUT, skip reveal")
            return False

        # 将大臣风险惩罚从 reveal_score 中扣除，再比较 gain
        adjusted_reveal_score = reveal_score - minister_risk
        gain = adjusted_reveal_score - current_score
        decision = gain > threshold
        print(f"[AI-REVEAL] -> threshold={threshold:.2f} current={current_score:.3f} "
              f"reveal={reveal_score:.3f} risk_adj={adjusted_reveal_score:.3f} "
              f"gain={gain:.3f} -> {'REVEAL' if decision else 'NO'}")
        return decision

    def _should_reveal_phase1(
        self,
        gs: GameState,
        ai_side: Side,
        step_count: int,
        soldier_spy_count: int,
    ) -> bool:
        """Phase 1：固定阈值（向后兼容，文档 Section 14.5 Phase 1）"""
        cfg = self.config

        revealed_gs = gs.clone()
        revealed_gs.reveal_spies()

        if AIEvaluator.has_immediate_lord_capture(revealed_gs, ai_side):
            return True

        depth = max(0, cfg.search_depth - 1)
        current_score = self._search(gs,          cfg.search_depth, -float('inf'), float('inf'),
                                     ai_side, soldier_spy_count)
        reveal_score  = self._search(revealed_gs, depth,            -float('inf'), float('inf'),
                                     ai_side, soldier_spy_count)

        gain          = reveal_score - current_score
        alive_spy_cnt = gs.count_alive_spies(ai_side)

        if gain > cfg.reveal_gain_threshold:
            return True
        if alive_spy_cnt >= 2 and step_count >= cfg.reveal_multi_spy_step and gain > cfg.reveal_multi_spy_threshold:
            return True
        if step_count >= cfg.reveal_late_step and gain > cfg.reveal_late_threshold:
            return True

        return False


# ──────────────────────────────────────────────
# AIController — 调度入口
# ──────────────────────────────────────────────

class AIController:
    """
    AI 回合调度入口，供 UIController 调用。

    使用方式：
        ai = AIController(Side.BLUE, config=ai_config_normal())
        # 每帧调用 tick()，它会在思考延迟结束后返回需要执行的动作
        action = ai.tick(gs, elapsed_seconds)
        if action: ui.execute_action(action)
    """

    def __init__(self, side: Side, config: Optional[AIConfig] = None) -> None:
        self.side   = side
        self.config = config or ai_config_normal()

        # 信息对称：只有大臣间谍 id 存入，士兵间谍不存
        self._known_spy_ids: set[int] = set()

        self.tactics  = AITactics()
        self._minimax = AIMinimax(self.config, self.tactics, self._known_spy_ids)

        # 思考状态
        self._thinking:       bool            = False
        self._think_start:    float           = 0.0   # 开始思考的墙钟时间
        self._pending_action: Optional[tuple] = None  # 计算结果（线程写入）
        self._thread:         Optional[threading.Thread] = None
        self._result_ready:   bool            = False  # 线程完成标志

    @property
    def think_elapsed(self) -> float:
        """当前已思考的真实秒数（思考中才有意义）"""
        if not self._thinking:
            return 0.0
        return time.monotonic() - self._think_start

    @property
    def difficulty_name(self) -> str:
        """根据 time_budget 返回难度名称"""
        tb = self.config.time_budget
        if tb <= 0.5:
            return "简单"
        elif tb <= 1.0:
            return "普通"
        elif tb <= 5.0:
            return "困难"
        else:
            return "地狱"

    # ── 选间谍阶段 ────────────────────────────

    def decide_spy_selection(self, gs: GameState) -> tuple:
        """
        返回选间谍动作：
          ('spy_minister', minister_id)  — 指定大臣
          ('spy_soldier',)               — 随机士兵
        """
        t = self.tactics.blended
        use_minister = random.random() < t.prefer_minister_spy_chance

        if use_minister:
            # 找对方所有大臣
            enemy = self.side.opposite()
            ministers = gs.board.pieces_of_type(PieceType.MINISTER, enemy)
            if ministers:
                # 选距己方领主最近的大臣（间谍后最有威胁价值）
                own_lord = AIEvaluator.get_lord(gs, self.side)
                if own_lord:
                    ministers.sort(
                        key=lambda p: abs(p.x - own_lord.x) + abs(p.y - own_lord.y)
                    )
                chosen = ministers[0]
                self._known_spy_ids.add(chosen.id)
                return ('spy_minister', chosen.id)

        # 随机士兵：不记录 id（信息对称原则）
        return ('spy_soldier',)

    # ── 走棋阶段（带延迟） ─────────────────────

    def request_move(self, gs: GameState) -> None:
        """触发 AI 开始在后台线程中思考"""
        if self._thinking:
            return
        self._thinking     = True
        self._think_start  = time.monotonic()
        self._result_ready = False
        self._pending_action = None
        # 克隆局面传入线程，避免主线程与搜索线程共享可变状态
        gs_clone = gs.clone()
        self._thread = threading.Thread(
            target=self._run_compute, args=(gs_clone,), daemon=True)
        self._thread.start()

    def _run_compute(self, gs: GameState) -> None:
        """后台线程：计算动作并写入 _pending_action"""
        result = self._compute_action(gs)
        self._pending_action = result
        self._result_ready   = True

    def tick(self, dt: float) -> Optional[tuple]:
        """
        每帧调用。后台计算完成且已过 think_delay 后返回动作，否则返回 None。
        think_delay 保证动作不会瞬间执行（视觉上有"思考感"），
        但对困难/地狱等真实计算超过 think_delay 时，完成即返回。
        """
        if not self._thinking:
            return None
        elapsed = time.monotonic() - self._think_start
        if self._result_ready and elapsed >= self.config.think_delay:
            self._thinking = False
            action = self._pending_action
            self._pending_action = None
            return action
        return None

    # ── 内部：计算动作 ────────────────────────

    def _compute_action(self, gs: GameState) -> Optional[tuple]:
        """同步计算本回合最佳动作"""
        # 游戏实际步数：turn_number 从3开始（前2回合是选间谍），减去起始偏移
        # 每方每回合算1步，双方合计每回合+2；第3回合=第1步
        step_count        = max(0, gs.turn_number - 3)
        soldier_spy_count = gs.count_alive_spies(self.side.opposite())
        side_name = "RED" if self.side == 0 else "BLUE"
        print(f"[AI-ACT] side={side_name} turn_number={gs.turn_number} "
              f"step_count={step_count} moved_this_turn={gs.moved_this_turn}")

        # 更新战术阶段
        self.tactics.update(step_count)

        # 揭露间谍判断（优先于走棋）
        if (not gs.moved_this_turn
                and self._minimax.should_reveal_spy(gs, self.side, step_count, soldier_spy_count)):
            return ('reveal',)

        # 搜索最佳走棋
        return self._minimax.find_best_move(gs, self.side, soldier_spy_count, step_count)
