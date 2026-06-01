"""
replay.py — 棋谱重播控制器
通过逐步重放 MoveRecord 还原每一步棋盘状态。
"""

from __future__ import annotations
from typing import Optional
from engine import GameState, MoveRecord, new_game
from save_load import load_replay


class ReplayController:
    """
    棋谱重播器。
    持有初始 GameState 的副本，逐步前进/后退。
    """

    def __init__(self, records: list[MoveRecord]) -> None:
        self._records = records
        self._gs = new_game()
        # 跳过选间谍阶段，直接进入 PLAYING
        from engine import Phase
        self._gs.phase = Phase.PLAYING
        self._gs.turn_number = 1
        self._cursor = 0          # 当前已执行到第几步（0 = 初始状态）
        self._snapshots: list[GameState] = []  # 每步前的快照（用于后退）

    @classmethod
    def from_file(cls, path: str) -> "ReplayController":
        return cls(load_replay(path))

    @property
    def total_steps(self) -> int:
        return len(self._records)

    @property
    def current_step(self) -> int:
        return self._cursor

    @property
    def state(self) -> GameState:
        return self._gs

    def step_forward(self) -> Optional[MoveRecord]:
        """前进一步，返回本步 MoveRecord，已到末尾返回 None"""
        if self._cursor >= len(self._records):
            return None
        record = self._records[self._cursor]

        # 保存快照
        import copy
        self._snapshots.append(copy.deepcopy(self._gs))

        # 执行这一步
        piece = self._gs.board.get_piece_by_id(record.piece_id)
        if piece:
            self._gs.do_move(piece, record.to_x, record.to_y)
        self._cursor += 1
        return record

    def step_backward(self) -> bool:
        """后退一步，返回是否成功"""
        if self._cursor == 0 or not self._snapshots:
            return False
        import copy
        self._gs = self._snapshots.pop()
        self._cursor -= 1
        return True

    def jump_to(self, step: int) -> None:
        """跳转到指定步数（0=初始）"""
        if step < 0:
            step = 0
        if step > self.total_steps:
            step = self.total_steps

        if step < self._cursor:
            # 后退：用快照还原
            diff = self._cursor - step
            for _ in range(diff):
                self.step_backward()
        else:
            # 前进
            while self._cursor < step:
                self.step_forward()

    def reset(self) -> None:
        self.__init__(self._records)
