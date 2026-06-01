"""
ui.py — 交互状态机
处理鼠标/键盘事件，调用 engine 层执行逻辑。
AI 玩家接口预留：实现 AIPlayer.get_move(gs) 即可接入。
"""

from __future__ import annotations
import pygame
import time
from typing import Optional
from enum import Enum, auto

from engine import (
    GameState, Piece, PieceType, Side, Phase,
    FORTRESS_CELLS, DIRS_8, new_game
)
from renderer import (
    Renderer, WINDOW_W, WINDOW_H,
    CELL_SIZE, BOARD_OFF_X, BOARD_OFF_Y, BOARD_PX, BOARD_PY,
    PANEL_X, PANEL_W,
    LOG_PANEL_W, LOG_PANEL_X,
    C_PANEL_BG, C_PANEL_BORDER, C_TEXT, C_TEXT_DIM,
    C_BTN_NORMAL, C_BTN_HOVER, C_BTN_ACTIVE,
)
from ai import AIController, AIConfig, ai_config_easy, ai_config_normal, ai_config_hard, ai_config_hell
from replay import ReplayController
from save_load import save_replay
from move_log import MoveLog


# ──────────────────────────────────────────────
# 常量
# ──────────────────────────────────────────────

# 侧边按钮
_PANEL_BTN_W  = 150
_PANEL_BTN_H  = 42
_PANEL_BTN_X  = PANEL_X + PANEL_W // 2   # 按钮中心 x
_PANEL_BTN_GAP = 52                        # 按钮间距

# 颜色
_C_OVERLAY      = (0,   0,   0,  160)     # 遮罩（RGBA）
_C_SPY_TITLE_R  = (255, 100, 100)         # 红方标题色
_C_SPY_TITLE_B  = (100, 150, 255)         # 蓝方标题色
_C_HIGHLIGHT_M  = (0,   220, 220)         # 大臣高亮边框
_C_TOGGLE_ON    = (60,  160,  60)         # toggle 激活色


def _btn(cx: int, cy: int, w: int = _PANEL_BTN_W, h: int = _PANEL_BTN_H) -> pygame.Rect:
    return pygame.Rect(cx - w // 2, cy - h // 2, w, h)


# ──────────────────────────────────────────────
# 规则说明数据
# ──────────────────────────────────────────────

# 每种棋子的规则文本：(标题, [行...])
# 用于规则界面右侧面板流式渲染
_PIECE_RULES: dict[PieceType, tuple[str, list[str]]] = {}  # 延迟初始化，见 _init_piece_rules()

def _init_piece_rules() -> None:
    global _PIECE_RULES
    _PIECE_RULES = {
        PieceType.SOLDIER: ("士兵", [
            "【移动】",
            "向正前方移动 1 格（空格）",
            "",
            "【攻击】",
            "攻击斜前方左右各 1 格",
            "（与移动方向不同）",
            "",
            "【晋升】",
            "吃子后 → 晋升为 军官",
            "到达对方底线 → 晋升为 大臣",
        ]),
        PieceType.MINISTER: ("大臣", [
            "【移动 / 攻击】",
            "上下左右 4 方向，每次 1 格",
            "",
            "【晋升（吃子后）】",
            "吃 士兵 / 军官类 → 总督",
            "吃 大臣类 → 教主",
            "吃 亲信 / 御史 → 御史",
        ]),
        PieceType.OFFICER: ("军官", [
            "【移动 / 攻击】",
            "左前、正前、右前 各 1 格",
            "",
            "进入对方阵地后",
            "额外解锁正后方 1 格",
            "",
            "【晋升（吃子后）】",
            "吃 士兵 → 铁卫",
            "吃 军官类 → 骑士",
            "吃 大臣类 → 刺客",
            "吃 亲信 / 御史 → 御史",
        ]),
        PieceType.KNIGHT: ("骑士", [
            "【移动 / 攻击】",
            "马步跳跃（日字形）",
            "8 个方向，可越过棋子",
            "",
            "无方向限制，无晋升",
        ]),
        PieceType.ASSASSIN: ("刺客", [
            "【移动】",
            "8 方向各 1 格（仅空格）",
            "",
            "【攻击（炮击）】",
            "上下左右 4 方向",
            "隔一个棋子（炮架）",
            "可远程攻击对方棋子",
            "",
            "移动与攻击范围完全分离",
        ]),
        PieceType.IRON_GUARD: ("铁卫", [
            "【移动 / 攻击】",
            "上下左右 4 方向",
            "无限滑行（类象棋车）",
            "遇己方棋子停止",
            "遇对方棋子可吃并停止",
        ]),
        PieceType.CHAMBERLAIN: ("总督", [
            "【移动 / 攻击】",
            "斜 4 方向无限滑行",
            "（类国际象棋主教）",
            "遇己方棋子停止",
            "遇对方棋子可吃并停止",
        ]),
        PieceType.PRIEST: ("教主", [
            "【移动】",
            "8 方向各 1 格（空格）",
            "或翻越相邻棋子后",
            "落在连续棋子串末尾空格",
            "",
            "【攻击】",
            "仅 8 方向 1 格内对方棋子",
            "（翻越落点不能吃子）",
        ]),
        PieceType.LOYALIST: ("亲信", [
            "【移动】",
            "8 方向无限滑行",
            "仅限己方半场（红 x≤3，蓝 x≥5）",
            "遇任何棋子立即停止",
            "",
            "【攻击】",
            "周围 8 格 1 步内对方棋子",
            "不可跨越 x=4 中立列",
        ]),
        PieceType.CENSOR: ("御史", [
            "【移动 / 攻击】",
            "8 方向（横竖斜）无限滑行",
            "（类国际象棋后 Queen）",
            "遇己方棋子停止",
            "遇对方棋子可吃并停止",
        ]),
        PieceType.LORD: ("领主", [
            "【移动 / 攻击】",
            "8 方向各 1 格",
            "禁止进入 x=4 中立列",
            "",
            "【直杀】",
            "与对方领主在同一直线",
            "或斜线且中间无棋子时",
            "可直接吃掉对方领主",
            "",
            "被吃 = 游戏结束",
        ]),
    }

_init_piece_rules()


class DialogKind(Enum):
    NONE               = auto()
    PROMOTION          = auto()   # 晋升提示
    SPY_REVEAL_CONFIRM = auto()   # 揭露间谍确认
    SPY_REVEAL_RESULT  = auto()   # 揭露结果
    SPY_EMPTY          = auto()   # 间谍全灭
    RANDOM_SOLDIER     = auto()   # 随机士兵结果
    CONFIRM_RESTART    = auto()   # 重新开始二级确认


class SelectState(Enum):
    IDLE           = auto()
    PIECE_SELECTED = auto()
    FORTRESS_EXIT  = auto()


# ──────────────────────────────────────────────
# 选间谍子状态
# ──────────────────────────────────────────────

class SpySelectSub(Enum):
    CHOOSING    = auto()   # 高亮敌方棋子，右侧显示"随机士兵"按钮，可点击大臣
    CONFIRMING  = auto()   # 已点击某大臣，右侧显示"确认/取消"


# ──────────────────────────────────────────────
# AI 接口预留
# ──────────────────────────────────────────────

# AIController 已从 ai.py 引入，旧 AIPlayer 桩已移除


# ──────────────────────────────────────────────
# 主 UI 控制器
# ──────────────────────────────────────────────

class UIController:
    def __init__(
        self,
        screen: pygame.Surface,
        red_ai:  Optional[AIController] = None,
        blue_ai: Optional[AIController] = None,
    ) -> None:
        self.screen   = screen
        self.renderer = Renderer(screen)
        self.gs: Optional[GameState] = None
        self.red_ai:  Optional[AIController] = red_ai
        self.blue_ai: Optional[AIController] = blue_ai

        # AI 思考计时（dt 累计）
        self._ai_requested: bool = False   # 本回合是否已触发 request_move

        # 棋子选中
        self.select_state    = SelectState.IDLE
        self.selected_piece: Optional[Piece] = None
        self.movable_pos:    set = set()
        self.capturable_pos: set = set()

        # 视觉 toggle
        self.show_last_move = False
        self.show_movable   = True
        self.last_from: Optional[tuple] = None
        self.last_to:   Optional[tuple] = None
        self.hover_cell: Optional[tuple] = None

        # 弹窗
        self.dialog:           DialogKind = DialogKind.NONE
        self.dialog_data:      dict       = {}
        self.dialog_hover_btn: Optional[int] = None

        # 选间谍子状态
        self.spy_sub = SpySelectSub.CHOOSING
        self._spy_pending_piece: Optional[Piece] = None   # CONFIRMING 时待确认的大臣

        # AI 选间谍：独立计时（不走后台线程，选间谍计算量极小）
        self._spy_ai_action:   Optional[tuple] = None   # 已计算好的动作
        self._spy_ai_deadline: float           = 0.0    # 到该时刻才执行

        # 场景
        self.scene:      str            = "main_menu"
        self.menu_hover: Optional[int]  = None
        self.paused      = False

        # 存档
        self.save_files: list[str]     = []
        self.save_hover: Optional[int] = None

        # 重播
        self.replay_ctrl: Optional[ReplayController] = None

        # §14 MoveLog 状态
        self._log_scroll:      int           = 0      # 棋谱面板滚动偏移
        self._review_mode:     bool          = False  # 是否处于回溯模式
        self._review_index:    int           = -1     # 回溯模式当前高亮条目索引
        self._log_hover_index: Optional[int] = None   # 鼠标悬停的条目索引

        # 模式选择状态
        self._ms_mode:        str = "pvp"   # "pvp" | "pve"
        self._ms_player_side: int = 0       # 0=玩家红方, 1=玩家蓝方（PVE）
        self._ms_difficulty:  int = 1       # 0=简单, 1=普通, 2=困难, 3=地狱
        self._ms_hover:       Optional[int] = None

        # 选间谍面板按钮缓存（每帧由 _draw_spy_panel_info 更新）
        self._spy_btn_rects: list[tuple[str, pygame.Rect]] = []

        # 规则说明场景
        self._rules_selected: PieceType = PieceType.SOLDIER  # 当前选中棋子
        self._rules_hover:    Optional[int] = None           # 左侧列表 hover 索引

        # 棋子移动插值动画
        # _anim: {piece_id: (from_sx, from_sy, to_sx, to_sy)} 屏幕像素（格子左上角）
        self._anim: dict[int, tuple[float, float, float, float]] = {}
        self._anim_elapsed: float = 0.0
        self._anim_duration: float = 0.15   # 秒

        # 浮字特效：[(text, cx, cy, elapsed, duration, color), ...]
        # cx/cy 为棋子圆心屏幕坐标
        self._float_texts: list[dict] = []

        # 揭露间谍扩散圆环特效：[(cx, cy, elapsed, duration, color), ...]
        self._reveal_rings: list[dict] = []

    # ── 公开：事件入口 ────────────────────────

    def handle_event(self, event: pygame.event.Event) -> bool:
        """返回 False 表示退出程序"""
        if event.type == pygame.QUIT:
            return False
        mx, my = pygame.mouse.get_pos()
        if event.type == pygame.MOUSEMOTION:
            self._on_mouse_move(mx, my)
        elif event.type == pygame.MOUSEBUTTONDOWN and event.button == 1:
            if not self._anim_playing:
                if not self._on_click(mx, my):
                    return False
        elif event.type == pygame.MOUSEWHEEL:
            # 鼠标在左侧面板上时滚动棋谱
            if mx < LOG_PANEL_W and self.scene == "game":
                self._scroll_log(-event.y)
        elif event.type == pygame.KEYDOWN:
            self._on_key(event.key)
        return True

    # ── 公开：每帧绘制 ────────────────────────

    def draw(self, dt: float = 0.016) -> None:
        self.renderer.tick()
        if self.scene == "main_menu":
            self._draw_main_menu()
        elif self.scene == "mode_select":
            self._draw_mode_select()
        elif self.scene == "rules":
            self._draw_rules()
        elif self.scene == "game":
            self._tick_anim(dt)
            self._draw_game()
            self._tick_draw_effects(dt)
            if self.paused:
                self._draw_pause()
            # AI 驱动（每帧 tick）
            if not self.paused:
                self._tick_ai(dt)
        elif self.scene == "game_over":
            self._draw_game()
            self._tick_draw_effects(dt)
        elif self.scene == "saves":
            self._draw_saves()
        elif self.scene == "replay":
            self._draw_replay()

    # ──────────────────────────────────────────
    # 主菜单
    # ──────────────────────────────────────────

    def _main_menu_buttons(self) -> list[tuple[str, pygame.Rect]]:
        cx = WINDOW_W // 2
        # 标题占 y=80~230，剩余空间 230~676，按钮组居中于该区间
        # 三按钮组高度 = 2*62 + 48 ≈ 172px；中心 y ≈ (230+676)//2 = 453
        btn_w, btn_h = 180, 48
        start_y = 390
        gap     = 62
        return [
            ("开始新游戏", _btn(cx, start_y,          btn_w, btn_h)),
            ("规则说明",   _btn(cx, start_y + gap,     btn_w, btn_h)),
            ("退  出",     _btn(cx, start_y + gap * 2, btn_w, btn_h)),
        ]

    def _draw_main_menu(self) -> None:
        self.renderer.draw_main_menu(self._main_menu_buttons(), self.menu_hover)

    def _click_main_menu(self, mx: int, my: int) -> None:
        for i, (_, rect) in enumerate(self._main_menu_buttons()):
            if rect.collidepoint(mx, my):
                if i == 0: self.scene = "mode_select"
                elif i == 1: self.scene = "rules"
                elif i == 2: pygame.event.post(pygame.event.Event(pygame.QUIT))

    # ──────────────────────────────────────────
    # 模式选择场景
    # ──────────────────────────────────────────

    def _ms_buttons(self) -> list[tuple[str, pygame.Rect, bool]]:
        """
        返回 (label, rect, is_active) 列表。
        三组卡片纵向排列，整体垂直居中：
          模式行 / 阵营行（PVE）/ 难度行（PVE）/ 开始 / 取消
        """
        cx   = WINDOW_W // 2
        is_pve = self._ms_mode == "pve"
        btns: list[tuple[str, pygame.Rect, bool]] = []

        # 计算起始 y，令内容整体垂直居中于标题以下区域
        # 标题占 y=80~148；可用区 148~676 = 528px
        # 每组：标题高(20) + 按钮高(44) + 组后间距(28) = 92px
        # 额外两组（阵营+难度，PVE）= 92 * 2 = 184px
        # 操作行：按钮(48) + 间距(10) + 按钮(40) = 98px
        CONTENT_H_PVP = 92 + 98              # ≈190
        CONTENT_H_PVE = 92 + 92 + 92 + 98   # ≈374
        AVAIL = 676 - 165                    # 511（标题底 165 以下）
        content_h = CONTENT_H_PVE if is_pve else CONTENT_H_PVP
        y = 165 + (AVAIL - content_h) // 2

        # ── 模式行
        btns.append(("双人对战 PVP", _btn(cx - 100, y + 20 + 22, w=170, h=44), self._ms_mode == "pvp"))
        btns.append(("人机对战 PVE", _btn(cx + 100, y + 20 + 22, w=170, h=44), self._ms_mode == "pve"))
        y += 92

        # ── 阵营行（PVE 时显示）
        if is_pve:
            btns.append(("红方（先手）", _btn(cx - 95, y + 20 + 22, w=160, h=44), self._ms_player_side == 0))
            btns.append(("蓝方（后手）", _btn(cx + 95, y + 20 + 22, w=160, h=44), self._ms_player_side == 1))
            y += 92

        # ── 难度行（PVE 时显示）
        if is_pve:
            btns.append(("简  单", _btn(cx - 210, y + 20 + 22, w=100, h=44), self._ms_difficulty == 0))
            btns.append(("普  通", _btn(cx -  70, y + 20 + 22, w=100, h=44), self._ms_difficulty == 1))
            btns.append(("困  难", _btn(cx +  70, y + 20 + 22, w=100, h=44), self._ms_difficulty == 2))
            btns.append(("地  狱", _btn(cx + 210, y + 20 + 22, w=100, h=44), self._ms_difficulty == 3))
            y += 92

        # ── 开始 / 取消
        btns.append(("开始游戏", _btn(cx, y,      w=170, h=48), False))
        btns.append(("取  消",   _btn(cx, y + 62, w=140, h=40), False))

        return btns

    def _draw_mode_select(self) -> None:
        mx, my = pygame.mouse.get_pos()
        self.renderer.draw_mode_select(
            self._ms_mode,
            self._ms_player_side,
            self._ms_difficulty,
            self._ms_buttons(),
            mx, my,
        )

    def _click_mode_select(self, mx: int, my: int) -> None:
        from ai import AIController, ai_config_easy, ai_config_normal, ai_config_hard, ai_config_hell
        btns = self._ms_buttons()
        _DIFF = [ai_config_easy, ai_config_normal, ai_config_hard, ai_config_hell]

        for i, (label, rect, _) in enumerate(btns):
            if not rect.collidepoint(mx, my):
                continue

            if label == "双人对战 PVP":
                self._ms_mode = "pvp"
            elif label == "人机对战 PVE":
                self._ms_mode = "pve"
            elif label == "红方（先手）":
                self._ms_player_side = 0
            elif label == "蓝方（后手）":
                self._ms_player_side = 1
            elif label == "简  单":
                self._ms_difficulty = 0
            elif label == "普  通":
                self._ms_difficulty = 1
            elif label == "困  难":
                self._ms_difficulty = 2
            elif label == "地  狱":
                self._ms_difficulty = 3
            elif label == "开始游戏":
                if self._ms_mode == "pvp":
                    self._start_new_game(red_ai=None, blue_ai=None)
                else:
                    cfg = _DIFF[self._ms_difficulty]()
                    from engine import Side
                    if self._ms_player_side == 0:   # 玩家红方，AI 蓝方
                        self._start_new_game(
                            red_ai=None,
                            blue_ai=AIController(Side.BLUE, config=cfg),
                        )
                    else:                           # 玩家蓝方，AI 红方
                        self._start_new_game(
                            red_ai=AIController(Side.RED, config=cfg),
                            blue_ai=None,
                        )
            elif label == "取  消":
                self.scene = "main_menu"
            return

    # ──────────────────────────────────────────
    # 规则说明场景
    # ──────────────────────────────────────────

    # 所有棋子类型的固定顺序
    _RULES_PIECE_ORDER = [
        PieceType.SOLDIER, PieceType.MINISTER, PieceType.OFFICER,
        PieceType.KNIGHT,  PieceType.ASSASSIN, PieceType.IRON_GUARD,
        PieceType.CHAMBERLAIN, PieceType.PRIEST, PieceType.LOYALIST,
        PieceType.CENSOR,  PieceType.LORD,
    ]

    def _rules_list_rects(self) -> list[tuple[PieceType, pygame.Rect]]:
        """左侧棋子列表各行的 (PieceType, Rect)"""
        from engine import PIECE_INFO
        item_h = 44
        x0, y0, w = 8, 80, 154
        result = []
        for i, pt in enumerate(self._RULES_PIECE_ORDER):
            rect = pygame.Rect(x0, y0 + i * item_h, w, item_h - 4)
            result.append((pt, rect))
        return result

    def _draw_rules(self) -> None:
        self.renderer.draw_rules(
            selected=self._rules_selected,
            hover_idx=self._rules_hover,
            list_rects=self._rules_list_rects(),
            rules_text=_PIECE_RULES,
        )

    def _click_rules(self, mx: int, my: int) -> None:
        # 左侧列表点击 → 切换选中棋子
        for pt, rect in self._rules_list_rects():
            if rect.collidepoint(mx, my):
                self._rules_selected = pt
                return
        # 右下返回按钮
        back_rect = pygame.Rect(WINDOW_W - 170, WINDOW_H - 54, 150, 38)
        if back_rect.collidepoint(mx, my):
            self.scene = "main_menu" if self.gs is None else "game"

    # ──────────────────────────────────────────
    # 游戏场景
    # ──────────────────────────────────────────


    def _start_new_game(
        self,
        red_ai:  Optional[AIController] = None,
        blue_ai: Optional[AIController] = None,
    ) -> None:
        self.red_ai  = red_ai
        self.blue_ai = blue_ai
        self.gs = new_game()
        # §14：注入 MoveLog 实例
        self.gs.move_log = MoveLog()
        self._log_scroll      = 0
        self._review_mode     = False
        self._review_index    = -1
        self._log_hover_index = None
        self.scene = "game"
        self.paused = False
        self._reset_selection()
        self.last_from = self.last_to = None
        self.show_last_move = False
        self.show_movable   = True
        self.dialog = DialogKind.NONE
        self.spy_sub = SpySelectSub.CHOOSING
        self._spy_pending_piece = None
        self._ai_requested = False

    def _restart_game(self) -> None:
        """重新开始：复用当前局的 AI 配置（相同阵营+难度），重置 AI 内部状态"""
        def _rebuild(ai: Optional[AIController]) -> Optional[AIController]:
            if ai is None:
                return None
            return AIController(ai.side, config=ai.config)
        self._start_new_game(
            red_ai=_rebuild(self.red_ai),
            blue_ai=_rebuild(self.blue_ai),
        )

    # ──────────────────────────────────────────
    # 棋子移动插值动画
    # ──────────────────────────────────────────

    @property
    def _anim_playing(self) -> bool:
        return bool(self._anim) and self._anim_elapsed < self._anim_duration

    def _start_anim(self, piece_id: int, fx: int, fy: int, tx: int, ty: int) -> None:
        """登记一枚棋子的移动动画（逻辑坐标 → 屏幕像素）"""
        fsx, fsy = self.renderer.board_to_screen(fx, fy)
        tsx, tsy = self.renderer.board_to_screen(tx, ty)
        self._anim = {piece_id: (float(fsx), float(fsy), float(tsx), float(tsy))}
        self._anim_elapsed = 0.0

    def _tick_anim(self, dt: float) -> None:
        if not self._anim:
            return
        self._anim_elapsed = min(self._anim_elapsed + dt, self._anim_duration)
        if self._anim_elapsed >= self._anim_duration:
            self._anim = {}   # 动画结束，清除

    def _anim_override(self) -> "dict[int, tuple[float, float]] | None":
        """返回当前帧的 {piece_id: (sx, sy)} 插值坐标（格子左上角），动画结束返回 None"""
        if not self._anim:
            return None
        t = self._anim_elapsed / self._anim_duration
        # ease-out quad：快进慢出
        t = 1.0 - (1.0 - t) ** 2
        result = {}
        for pid, (fsx, fsy, tsx, tsy) in self._anim.items():
            result[pid] = (
                fsx + (tsx - fsx) * t,
                fsy + (tsy - fsy) * t,
            )
        return result

    def _draw_game(self) -> None:
        gs = self.gs
        if gs is None:
            return

        # §14.8 回溯模式：临时将棋盘 grid 替换为历史快照
        _snapshot_backup = None
        if self._review_mode and self._review_index >= 0:
            history = gs.history
            if history and self._review_index < len(history):
                snap = history[self._review_index].board_snapshot
                if snap is not None:
                    _snapshot_backup    = gs.board.grid
                    gs.board.grid       = snap
                    # 同步 _piece_map 以防渲染用到（只读，不改写）

        # 选间谍阶段：不显示高亮（遮罩层在后面画）
        in_spy = gs.phase == Phase.SELECTING_SPY
        self.renderer.draw(
            gs=gs,
            selected_piece=self.selected_piece if not in_spy else None,
            movable_pos=self.movable_pos if not in_spy else set(),
            capturable_pos=self.capturable_pos if not in_spy else set(),
            last_from=self.last_from,
            last_to=self.last_to,
            show_last_move=self.show_last_move and not in_spy,
            show_movable=self.show_movable and not in_spy,
            viewing_side=gs.current_side,
            danger_lords=self._get_danger_lords() if not in_spy else set(),
            hover_cell=self.hover_cell,
            move_log=gs.move_log,
            log_scroll=self._log_scroll,
            review_index=self._review_index if self._review_mode else None,
            log_hover_index=self._log_hover_index,
            anim_override=self._anim_override(),
            ai_thinking_info=self._get_ai_thinking_info(),
        )

        # 恢复棋盘 grid
        if _snapshot_backup is not None:
            gs.board.grid = _snapshot_backup

        # 选间谍阶段覆盖层（棋盘高亮，需在按钮之前绘制）
        if in_spy and self.dialog == DialogKind.NONE:
            self._draw_spy_select_overlay()

        # 侧边动态按钮（含选间谍阶段右侧按钮）
        if in_spy and self.dialog == DialogKind.NONE:
            self._spy_btn_rects = self._draw_spy_panel_info()   # 流式绘制并缓存 rect
        self._draw_panel_buttons()

        # 弹窗（优先级最高）
        self._draw_dialog()

    # ──────────────────────────────────────────
    # AI 驱动
    # ──────────────────────────────────────────

    def _current_ai(self) -> Optional[AIController]:
        """返回当前行动方的 AI（玩家方返回 None）"""
        if self.gs is None:
            return None
        if self.gs.current_side == Side.RED:
            return self.red_ai
        return self.blue_ai

    def _tick_ai(self, dt: float) -> None:
        """每帧驱动 AI：触发思考、接收动作、执行"""
        gs = self.gs
        if gs is None or gs.phase == Phase.GAME_OVER:
            return

        # 选间谍阶段：用 spy_select_current_side() 决定该哪个 AI 行动
        # （不能用 _current_ai()，因为 gs.current_side 在 SELECTING_SPY 期间不变）
        if gs.phase == Phase.SELECTING_SPY:
            spy_side = gs.spy_select_current_side()
            ai = self.red_ai if spy_side == Side.RED else self.blue_ai
            if ai is None:
                return  # 当前选间谍方是人类，不驱动
            if not self._ai_requested:
                # 立即计算动作，延迟 think_delay 秒后执行
                self._ai_requested  = True
                self._spy_ai_action  = ai.decide_spy_selection(gs)
                self._spy_ai_deadline = time.monotonic() + ai.config.think_delay
            if self._spy_ai_action is not None and time.monotonic() >= self._spy_ai_deadline:
                action = self._spy_ai_action
                self._spy_ai_action  = None
                self._ai_requested   = False
                self._execute_ai_spy_action(action)
            return

        # 对局阶段
        if gs.phase == Phase.PLAYING:
            ai = self._current_ai()
            if ai is None:
                return
            # 回溯模式、有弹窗、或棋子移动动画未完成时不驱动
            if self._review_mode or self.dialog != DialogKind.NONE or self._anim_playing:
                return
            if not self._ai_requested:
                self._ai_requested = True
                ai.request_move(gs)
            result = ai.tick(dt)
            if result is not None:
                self._ai_requested = False
                self._execute_ai_action(result)

    def _execute_ai_spy_action(self, action: tuple) -> None:
        """执行 AI 的选间谍动作"""
        gs = self.gs
        if gs is None:
            return
        if action[0] == 'spy_minister':
            gs.do_spy_pick_minister(action[1])
        elif action[0] == 'spy_soldier':
            gs.do_spy_random_soldier()
        self.spy_sub = SpySelectSub.CHOOSING
        self._spy_pending_piece = None

    def _execute_ai_action(self, action: tuple) -> None:
        """执行 AI 的走棋 / 揭露动作"""
        gs = self.gs
        if gs is None:
            return
        print(f"[AI-EXEC] action={action[0]} turn_number={gs.turn_number} current_side={gs.current_side}")
        if action[0] == 'move':
            _, piece, tx, ty = action
            p = gs.board.get_piece_by_id(piece.id)
            if p:
                self._do_move(p, tx, ty)
        elif action[0] == 'exit':
            _, piece, tx, ty = action
            p = gs.board.get_piece_by_id(piece.id)
            if p:
                self._start_anim(p.id, p.x, p.y, tx, ty)
                gs.do_fortress_exit(p, tx, ty)
                gs._next_turn()
        elif action[0] == 'reveal':
            converted = gs.reveal_spies()
            self._trigger_reveal_rings(gs, converted)
            self._auto_scroll_to_latest()
            if gs.phase == Phase.GAME_OVER:
                self.scene = "game_over"

    def _get_danger_lords(self) -> set:
        if self.gs is None:
            return set()
        danger = set()
        enemy = self.gs.current_side.opposite()
        for p in self.gs.board.pieces_of(enemy):
            _, caps = self.gs.board.get_moves(p, self.gs.fortress_cooldown)
            for cx, cy in caps:
                target = self.gs.board.get(cx, cy)
                if target and target.type == PieceType.LORD:
                    danger.add((cx, cy))
        return danger

    def _get_ai_thinking_info(self) -> "tuple[str, float] | None":
        """返回 (难度名, 已思考秒数)，当前方 AI 正在思考时才返回，否则 None"""
        ai = self._current_ai()
        if ai is None or not ai._thinking:
            return None
        return (ai.difficulty_name, ai.think_elapsed)

    # ──────────────────────────────────────────
    # 选间谍阶段右侧面板信息
    # ──────────────────────────────────────────

    def _draw_spy_panel_info(self) -> list[tuple[str, pygame.Rect]]:
        """
        在右侧面板绘制选间谍阶段的标题、说明文字和按钮（流式布局）。
        返回可点击按钮的 (label, rect) 列表，供 _click_game 检测。
        AI 回合时只显示标题，不渲染操作提示和按钮。
        """
        gs = self.gs
        if gs is None:
            return []
        side     = gs.spy_select_current_side()
        side_str = "红方" if side == Side.RED else "蓝方"
        step     = getattr(gs, "spy_select_step", 0)
        title_c  = _C_SPY_TITLE_R if side == Side.RED else _C_SPY_TITLE_B

        # 判断当前选间谍方是否是 AI
        spy_ai = self.red_ai if side == Side.RED else self.blue_ai
        is_ai_turn = spy_ai is not None

        px  = PANEL_X - 10
        pw  = PANEL_W + 10
        cx  = px + pw // 2
        bx  = _PANEL_BTN_X

        cursor_y = BOARD_OFF_Y + 20

        # ── 标题 line1
        s1 = self.renderer.font_md.render(f"{side_str}  选间谍", True, title_c)
        self.screen.blit(s1, s1.get_rect(centerx=cx, top=cursor_y))
        cursor_y += s1.get_height() + 4

        # ── 步骤 line2
        s2 = self.renderer.font_sm.render(f"第 {step + 1} / 2 步", True, C_TEXT_DIM)
        self.screen.blit(s2, s2.get_rect(centerx=cx, top=cursor_y))
        cursor_y += s2.get_height() + 10

        # ── 分隔线
        pygame.draw.line(self.screen, C_PANEL_BORDER,
                         (px + 10, cursor_y), (px + pw - 10, cursor_y), 1)
        cursor_y += 12

        # AI 回合：只显示等待提示，不渲染任何操作按钮
        if is_ai_turn:
            hint = self.renderer.font_sm.render("AI 思考中...", True, C_TEXT_DIM)
            self.screen.blit(hint, hint.get_rect(centerx=cx, top=cursor_y))
            return []

        btn_rects: list[tuple[str, pygame.Rect]] = []

        if self.spy_sub == SpySelectSub.CHOOSING:
            hints = [
                "点击棋盘上",
                "绿色大臣 指定间谍",
                "──────────────",
                "或点击下方按钮",
                "随机选2名士兵",
            ]
            for h in hints:
                s = self.renderer.font_sm.render(h, True, C_TEXT_DIM)
                self.screen.blit(s, s.get_rect(centerx=cx, top=cursor_y))
                cursor_y += s.get_height() + 4
            cursor_y += 10   # 文字与按钮间距

            r = _btn(bx, cursor_y + _PANEL_BTN_H // 2)
            self.renderer.draw_button("随机士兵", r)
            btn_rects.append(("随机士兵", r))

        else:  # CONFIRMING
            p = self._spy_pending_piece
            if p is not None:
                s3 = self.renderer.font_sm.render("已选大臣：", True, C_TEXT_DIM)
                self.screen.blit(s3, s3.get_rect(centerx=cx, top=cursor_y))
                cursor_y += s3.get_height() + 4

                s4 = self.renderer.font_md.render(
                    f"({chr(ord('A') + p.x)}{p.y + 1})", True, (60, 220, 80))
                self.screen.blit(s4, s4.get_rect(centerx=cx, top=cursor_y))
                cursor_y += s4.get_height() + 4

            s5 = self.renderer.font_sm.render("确认作为间谍？", True, C_TEXT_DIM)
            self.screen.blit(s5, s5.get_rect(centerx=cx, top=cursor_y))
            cursor_y += s5.get_height() + 10

            r_ok  = _btn(bx, cursor_y + _PANEL_BTN_H // 2)
            r_can = _btn(bx, cursor_y + _PANEL_BTN_H // 2 + _PANEL_BTN_GAP)
            self.renderer.draw_button("确  认", r_ok)
            self.renderer.draw_button("取  消", r_can)
            btn_rects.append(("确  认", r_ok))
            btn_rects.append(("取  消", r_can))

        return btn_rects

    # ──────────────────────────────────────────
    # 侧边动态按钮
    # ──────────────────────────────────────────

    def _panel_buttons(self) -> list[tuple[str, pygame.Rect, bool, bool]]:
        """
        返回 (label, rect, is_toggle_active, is_disabled) 列表。
        """
        gs = self.gs
        if gs is None:
            return []

        bx  = _PANEL_BTN_X
        btns = []

        # ── 游戏结算阶段：只显示两个操作按钮 ────
        if gs.phase == Phase.GAME_OVER:
            # 文字高度固定：font_lg(28)=37px + 8 + font_sm(16)=22px + 8 + 间距12
            top = BOARD_OFF_Y + 16 + 37 + 8 + 22 + 8 + 12   # = 143
            btns.append(("重新开始",   _btn(bx, top),                   False, False))
            btns.append(("返回主菜单", _btn(bx, top + _PANEL_BTN_GAP),  False, False))
            return btns

        # ── 选间谍阶段：按钮由 _draw_spy_panel_info 流式绘制 ──────────
        if gs.phase == Phase.SELECTING_SPY:
            return []

        # ── 普通对局阶段 ────────────────────────
        top = BOARD_OFF_Y + 16
        gap = _PANEL_BTN_GAP

        def add(label: str, active: bool = False, disabled: bool = False) -> None:
            nonlocal top
            btns.append((label, _btn(bx, top), active, disabled))
            top += gap

        # 回溯模式下只显示"回到最新"
        if self._review_mode:
            add("回到最新")
            return btns

        # PVE 模式判断（任意一方有 AI 即为 PVE）
        is_pve = self.red_ai is not None or self.blue_ai is not None

        if gs.phase == Phase.PLAYING:
            spy_disabled = gs.moved_this_turn
            add("揭露间谍", disabled=spy_disabled)
        if not is_pve:
            can_undo = gs.can_undo and bool(gs.history) and gs.phase == Phase.PLAYING
            add("悔  棋", disabled=not can_undo)
            add("最后一步",   active=self.show_last_move)
        add("重新开始")
        add("菜  单")
        return btns

    def _draw_panel_buttons(self) -> None:
        for label, rect, active, disabled in self._panel_buttons():
            self.renderer.draw_button(label, rect, active=active, disabled=disabled)

    def _click_panel_btn_by_label(self, label: str) -> None:
        gs = self.gs
        if gs is None:
            return

        # ── 选间谍阶段专属按钮 ──────────────────
        if label == "随机士兵":
            gs.do_spy_random_soldier()
            self.spy_sub = SpySelectSub.CHOOSING
            self._spy_pending_piece = None
            self._ai_requested = False   # 人类完成，重置以便下一方（可能是AI）触发
            return
        if label == "确  认":
            if self.spy_sub == SpySelectSub.CONFIRMING and self._spy_pending_piece is not None:
                gs.do_spy_pick_minister(self._spy_pending_piece.id)
                self.spy_sub = SpySelectSub.CHOOSING
                self._spy_pending_piece = None
                self._ai_requested = False   # 人类完成，重置以便下一方触发
            return
        if label == "取  消":
            self.spy_sub = SpySelectSub.CHOOSING
            self._spy_pending_piece = None
            return

        # ── 普通对局按钮 ────────────────────────
        if label == "回到最新":
            self._exit_review()
        elif label == "揭露间谍":
            if not gs.moved_this_turn:
                self.dialog = DialogKind.SPY_REVEAL_CONFIRM
        elif label == "悔  棋":
            if gs.can_undo and gs.history:
                gs.undo()
                self._reset_selection()
                self.last_from = self.last_to = None
        elif label == "最后一步":
            self.show_last_move = not self.show_last_move
        elif label == "重新开始":
            self.dialog = DialogKind.CONFIRM_RESTART
        elif label == "返回主菜单":
            self.scene = "main_menu"
        elif label == "菜  单":
            self.paused = True

    # ──────────────────────────────────────────
    # 选间谍覆盖层
    # ──────────────────────────────────────────

    def _draw_spy_select_overlay(self) -> None:
        """
        选间谍阶段覆盖层（无全屏遮罩）：
        - 调暗当前选间谍方自己的棋子
        - 高亮敌方大臣（绿色）和士兵（黄色）
        - CONFIRMING 状态额外高亮待确认大臣（白色选中框）
        右侧面板按钮由 _draw_panel_buttons 负责绘制
        """
        gs = self.gs
        if gs is None:
            return
        side  = gs.spy_select_current_side()   # 当前正在选间谍的一方
        enemy = side.opposite()                 # 被选间谍的一方（高亮目标）

        cs = CELL_SIZE

        # ── 调暗己方棋子（半透明黑色叠加）
        dim_surf = pygame.Surface((cs, cs), pygame.SRCALPHA)
        dim_surf.fill((0, 0, 0, 140))
        for p in gs.board.pieces_of(side):
            sx, sy = self.renderer.board_to_screen(p.x, p.y)
            self.screen.blit(dim_surf, (sx, sy))

        # ── 高亮敌方大臣（绿色边框）
        c_minister = (60, 220, 80)
        for p in gs.board.pieces_of(enemy):
            if p.type == PieceType.MINISTER:
                sx, sy = self.renderer.board_to_screen(p.x, p.y)
                hl = pygame.Surface((cs, cs), pygame.SRCALPHA)
                pygame.draw.rect(hl, (*c_minister, 60), (0, 0, cs, cs))
                pygame.draw.rect(hl, (*c_minister, 220), (0, 0, cs, cs), 3)
                self.screen.blit(hl, (sx, sy))

        # ── 高亮敌方士兵（黄色边框）
        c_soldier = (255, 210, 40)
        for p in gs.board.pieces_of(enemy):
            if p.type == PieceType.SOLDIER:
                sx, sy = self.renderer.board_to_screen(p.x, p.y)
                hl = pygame.Surface((cs, cs), pygame.SRCALPHA)
                pygame.draw.rect(hl, (*c_soldier, 50), (0, 0, cs, cs))
                pygame.draw.rect(hl, (*c_soldier, 200), (0, 0, cs, cs), 3)
                self.screen.blit(hl, (sx, sy))

        # ── CONFIRMING：白色选中框叠加在待确认大臣上
        if self.spy_sub == SpySelectSub.CONFIRMING and self._spy_pending_piece is not None:
            p = self._spy_pending_piece
            sx, sy = self.renderer.board_to_screen(p.x, p.y)
            sel_surf = pygame.Surface((cs, cs), pygame.SRCALPHA)
            pygame.draw.rect(sel_surf, (255, 255, 255, 240), (0, 0, cs, cs), 3)
            self.screen.blit(sel_surf, (sx, sy))

    def _draw_spy_choose_panel(self, side_str: str, title_c: tuple) -> None:
        """已合并进 _draw_spy_select_overlay，此方法保留为空以防残留调用"""
        pass

    def _draw_spy_pick_minister_overlay(self, *args, **kwargs) -> None:
        """已合并进 _draw_spy_select_overlay，此方法保留为空以防残留调用"""
        pass

    # ──────────────────────────────────────────
    # 点击分发
    # ──────────────────────────────────────────

    def _on_click(self, mx: int, my: int) -> bool:
        if self.scene == "main_menu":
            self._click_main_menu(mx, my)
        elif self.scene == "mode_select":
            self._click_mode_select(mx, my)
        elif self.scene == "rules":
            self._click_rules(mx, my)
        elif self.scene == "game":
            if self.paused:
                self._click_pause(mx, my)
            elif self.dialog != DialogKind.NONE:
                self._click_dialog(mx, my)
            else:
                self._click_game(mx, my)
        elif self.scene == "game_over":
            self._click_game(mx, my)
        elif self.scene == "saves":
            self._click_saves(mx, my)
        elif self.scene == "replay":
            self._click_replay(mx, my)
        return True

    def _click_game(self, mx: int, my: int) -> None:
        gs = self.gs
        if gs is None:
            return

        # AI 回合思考中：屏蔽所有棋盘交互（面板按钮仍可用）
        ai_busy = (self._current_ai() is not None and self._current_ai()._thinking)

        # 左侧 MoveLog 面板点击（§14.7/§14.8）
        if mx < LOG_PANEL_W and gs.move_log is not None:
            total = gs.move_log.count
            idx   = self.renderer.log_entry_at_y(my, self._log_scroll, total)
            if idx is not None:
                if self._review_mode and idx == self._review_index:
                    # 双击（或再次点击已高亮）退出回溯
                    self._exit_review()
                else:
                    self._enter_review(idx)
            return

        # 侧边动态按钮（优先）
        if gs.phase == Phase.SELECTING_SPY:
            # 当前选间谍方是 AI，屏蔽所有玩家输入
            spy_side = gs.spy_select_current_side()
            spy_ai = self.red_ai if spy_side == Side.RED else self.blue_ai
            if spy_ai is not None:
                return
            # 优先检测流式面板按钮，命中则处理；否则走棋盘点击
            for label, rect in self._spy_btn_rects:
                if rect.collidepoint(mx, my):
                    self._click_panel_btn_by_label(label)
                    return
            self._click_spy_select(mx, my)
            return

        for label, rect, _, disabled in self._panel_buttons():
            if rect.collidepoint(mx, my) and not disabled:
                self._click_panel_btn_by_label(label)
                return

        # AI 回合思考中：屏蔽棋盘点击
        if ai_busy:
            return

        # 回溯模式下棋盘只读
        if self._review_mode:
            return

        # 普通棋盘点击
        cell = self.renderer.screen_to_board(mx, my)
        if cell:
            self._on_board_click(cell[0], cell[1])

    # ──────────────────────────────────────────
    # 棋盘状态机
    # ──────────────────────────────────────────

    def _on_board_click(self, x: int, y: int) -> None:
        gs = self.gs
        if gs is None or gs.phase != Phase.PLAYING:
            return
        clicked = gs.board.get(x, y)

        if self.select_state == SelectState.IDLE:
            if clicked and clicked.side == gs.current_side:
                self._select(clicked)
            return

        # PIECE_SELECTED
        if (x, y) in self.movable_pos:
            self._do_move(self.selected_piece, x, y)
        elif (x, y) in self.capturable_pos:
            self._do_move(self.selected_piece, x, y)
        elif clicked and clicked.side == gs.current_side:
            self._select(clicked)
        else:
            self._reset_selection()

    def _can_move(self, piece: Piece) -> bool:
        gs = self.gs
        if gs is None:
            return False
        mv, cap = gs.board.get_moves(piece, gs.fortress_cooldown)
        return bool(mv or cap)

    def _select(self, piece: Piece) -> None:
        gs = self.gs
        if gs is None:
            return
        self.selected_piece = piece
        mv, cap = gs.board.get_moves(piece, gs.fortress_cooldown)
        self.movable_pos    = set(mv)
        self.capturable_pos = set(cap)
        self.select_state   = SelectState.PIECE_SELECTED

    def _do_move(self, piece: Piece, to_x: int, to_y: int) -> None:
        gs = self.gs
        if gs is None:
            return
        from_x, from_y = piece.x, piece.y   # 保存移动前坐标（engine 执行后会更新）
        self._start_anim(piece.id, from_x, from_y, to_x, to_y)
        record = gs.do_move(piece, to_x, to_y)
        self.last_from = (record.from_x, record.from_y)
        self.last_to   = (record.to_x,   record.to_y)
        self._reset_selection()
        self._ai_requested = False   # 回合已切换，下一 AI 回合重新触发
        # §14.7：自动滚动到最新条目
        self._auto_scroll_to_latest()

        if record.promoted_to is not None:
            # 浮字特效替代弹窗
            from engine import PIECE_INFO
            from renderer import CELL_SIZE, BOARD_OFF_X, BOARD_OFF_Y
            name = PIECE_INFO[int(record.promoted_to)]["name"]
            # 目标格子圆心屏幕坐标
            sx = BOARD_OFF_X + record.to_x * CELL_SIZE + CELL_SIZE // 2
            sy = BOARD_OFF_Y + (8 - record.to_y) * CELL_SIZE + CELL_SIZE // 2
            self._float_texts.append({
                "text": f"晋级 → {name}",
                "cx": sx, "cy": sy,
                "elapsed": 0.0, "duration": 1.2,
                "color": (255, 210, 40),   # 金色
            })

        if gs.phase == Phase.GAME_OVER:
            self.scene = "game_over"
            if gs.history:
                save_replay(gs.history)

    def _reset_selection(self) -> None:
        self.selected_piece  = None
        self.movable_pos     = set()
        self.capturable_pos  = set()
        self.select_state    = SelectState.IDLE

    # ── 特效：浮字 + 揭露圆环 ─────────────────

    def _trigger_reveal_rings(self, gs, converted: list) -> None:
        """为每个被揭露的棋子登记扩散圆环特效"""
        from renderer import CELL_SIZE, BOARD_OFF_X, BOARD_OFF_Y
        for pid in converted:
            p = gs.board.get_piece_by_id(pid)
            if p is None:
                continue
            cx = BOARD_OFF_X + p.x * CELL_SIZE + CELL_SIZE // 2
            cy = BOARD_OFF_Y + (8 - p.y) * CELL_SIZE + CELL_SIZE // 2
            self._reveal_rings.append({
                "cx": cx, "cy": cy,
                "elapsed": 0.0, "duration": 0.8,
                "color": (220, 60, 60),   # 红色
            })

    def _tick_draw_effects(self, dt: float) -> None:
        """每帧更新并绘制浮字特效和揭露圆环特效"""
        screen = self.renderer.screen
        from renderer import CELL_SIZE

        # ── 浮字特效 ──
        still_alive = []
        for fx in self._float_texts:
            fx["elapsed"] += dt
            t = fx["elapsed"] / fx["duration"]
            if t >= 1.0:
                continue
            alpha = int(255 * (1.0 - t))
            rise  = int(50 * t)             # 上飘像素
            r, g, b = fx["color"]
            surf = self.renderer.font_md.render(fx["text"], True, (r, g, b))
            surf.set_alpha(alpha)
            rect = surf.get_rect(center=(fx["cx"], fx["cy"] - 20 - rise))
            screen.blit(surf, rect)
            still_alive.append(fx)
        self._float_texts = still_alive

        # ── 揭露圆环特效 ──
        r_start = int(CELL_SIZE * 0.38) + 4   # 从棋子边缘开始
        r_end   = int(CELL_SIZE * 0.9)         # 扩散到接近格子边缘
        still_alive = []
        for ring in self._reveal_rings:
            ring["elapsed"] += dt
            t = ring["elapsed"] / ring["duration"]
            if t >= 1.0:
                continue
            # ease-out：快出慢收
            te    = 1.0 - (1.0 - t) ** 2
            radius = int(r_start + (r_end - r_start) * te)
            alpha  = int(220 * (1.0 - t))
            r, g, b = ring["color"]
            # pygame.draw 不支持 alpha，用 Surface 模拟
            size = radius * 2 + 6
            ring_surf = pygame.Surface((size, size), pygame.SRCALPHA)
            pygame.draw.circle(ring_surf, (r, g, b, alpha),
                               (size // 2, size // 2), radius, 3)
            screen.blit(ring_surf,
                        (ring["cx"] - size // 2, ring["cy"] - size // 2))
            still_alive.append(ring)
        self._reveal_rings = still_alive

    # ── §14.8 回溯模式 ────────────────────────

    def _enter_review(self, index: int) -> None:
        """进入回溯模式，显示第 index 步后的棋盘"""
        gs = self.gs
        if gs is None or gs.move_log is None:
            return
        self._review_mode  = True
        self._review_index = index
        self._reset_selection()

    def _exit_review(self) -> None:
        """退出回溯模式，回到最新状态"""
        self._review_mode  = False
        self._review_index = -1
        # 自动滚动到最新条目
        gs = self.gs
        if gs and gs.move_log:
            total      = gs.move_log.count
            from renderer import _LOG_ENTRY_H, _LOG_TITLE_H, WINDOW_H
            list_h     = WINDOW_H - _LOG_TITLE_H - 4
            max_items  = list_h // _LOG_ENTRY_H
            self._log_scroll = max(0, total - max_items)

    def _auto_scroll_to_latest(self) -> None:
        """新条目加入后自动滚动到底部"""
        gs = self.gs
        if gs is None or gs.move_log is None:
            return
        if self._review_mode:
            return
        total = gs.move_log.count
        from renderer import _LOG_ENTRY_H, _LOG_TITLE_H, WINDOW_H
        list_h    = WINDOW_H - _LOG_TITLE_H - 4
        max_items = list_h // _LOG_ENTRY_H
        self._log_scroll = max(0, total - max_items)

    def _scroll_log(self, delta: int) -> None:
        """滚动棋谱面板（delta>0 向下，delta<0 向上）"""
        gs = self.gs
        if gs is None or gs.move_log is None:
            return
        total = gs.move_log.count
        from renderer import _LOG_ENTRY_H, _LOG_TITLE_H, WINDOW_H
        list_h    = WINDOW_H - _LOG_TITLE_H - 4
        max_items = list_h // _LOG_ENTRY_H
        max_scroll = max(0, total - max_items)
        self._log_scroll = max(0, min(self._log_scroll + delta, max_scroll))

    # ──────────────────────────────────────────
    # 选间谍点击
    # ──────────────────────────────────────────

    def _click_spy_select(self, mx: int, my: int) -> None:
        gs = self.gs
        if gs is None:
            return

        # 当前选间谍方是 AI，屏蔽人类点击
        spy_side = gs.spy_select_current_side()
        ai = self.red_ai if spy_side == Side.RED else self.blue_ai
        if ai is not None:
            return

        if self.spy_sub == SpySelectSub.CHOOSING:
            # 点击棋盘上敌方大臣 → 进入 CONFIRMING
            cell = self.renderer.screen_to_board(mx, my)
            if cell is not None:
                x, y  = cell
                piece = gs.board.get(x, y)
                sel   = gs.spy_select_current_side()
                if piece and piece.type == PieceType.MINISTER and piece.side != sel:
                    self._spy_pending_piece = piece
                    self.spy_sub = SpySelectSub.CONFIRMING

        elif self.spy_sub == SpySelectSub.CONFIRMING:
            # 点击棋盘上另一个大臣：直接切换选中目标
            cell = self.renderer.screen_to_board(mx, my)
            if cell is not None:
                x, y  = cell
                piece = gs.board.get(x, y)
                sel   = gs.spy_select_current_side()
                if piece and piece.type == PieceType.MINISTER and piece.side != sel:
                    self._spy_pending_piece = piece

    # ──────────────────────────────────────────
    # 弹窗
    # ──────────────────────────────────────────

    def _dialog_buttons(self) -> list[tuple[str, pygame.Rect]]:
        cx = WINDOW_W // 2
        cy = WINDOW_H // 2 + 70
        d  = self.dialog
        if d == DialogKind.PROMOTION:
            return [("确  认", _btn(cx, cy))]
        if d == DialogKind.SPY_REVEAL_CONFIRM:
            return [("确  认", _btn(cx - 90, cy)), ("取  消", _btn(cx + 90, cy))]
        if d == DialogKind.CONFIRM_RESTART:
            return [("重新开始", _btn(cx - 90, cy)), ("取  消", _btn(cx + 90, cy))]
        if d in (DialogKind.SPY_REVEAL_RESULT,
                 DialogKind.SPY_EMPTY,
                 DialogKind.RANDOM_SOLDIER):
            return [("确  认", _btn(cx, cy))]
        return []

    def _click_dialog(self, mx: int, my: int) -> None:
        for i, (_, rect) in enumerate(self._dialog_buttons()):
            if rect.collidepoint(mx, my):
                self._handle_dialog_btn(i)
                return

    def _handle_dialog_btn(self, idx: int) -> None:
        gs = self.gs
        d  = self.dialog
        if d == DialogKind.PROMOTION:
            self.dialog = DialogKind.NONE

        elif d == DialogKind.SPY_REVEAL_CONFIRM:
            if idx == 0:
                converted = gs.reveal_spies()
                self._trigger_reveal_rings(gs, converted)
                self._auto_scroll_to_latest()
                if converted:
                    names = []
                    for pid in converted:
                        p = gs.board.get_piece_by_id(pid)
                        if p:
                            names.append(f"{p.name()} ({p.x},{p.y})")
                    self.dialog      = DialogKind.SPY_REVEAL_RESULT
                    self.dialog_data = {"names": names}
                else:
                    self.dialog = DialogKind.SPY_EMPTY
            else:
                self.dialog = DialogKind.NONE

        elif d == DialogKind.CONFIRM_RESTART:
            if idx == 0:
                self._restart_game()
            else:
                self.dialog = DialogKind.NONE

        elif d in (DialogKind.SPY_REVEAL_RESULT,
                   DialogKind.SPY_EMPTY):
            self.dialog = DialogKind.NONE

        elif d == DialogKind.RANDOM_SOLDIER:
            # 随机士兵结果确认后，若间谍阶段已结束则无需操作
            self.dialog = DialogKind.NONE

    def _draw_dialog(self) -> None:
        d = self.dialog
        if d == DialogKind.NONE:
            return
        btns = self._dialog_buttons()
        mx, my = pygame.mouse.get_pos()
        hover  = next(
            (i for i, (_, r) in enumerate(btns) if r.collidepoint(mx, my)),
            None,
        )
        if d == DialogKind.PROMOTION:
            name = self.dialog_data.get("name", "")
            self.renderer.draw_dialog("晋升！", [f"晋升为：{name}"], btns, hover)
        elif d == DialogKind.SPY_REVEAL_CONFIRM:
            self.renderer.draw_dialog(
                "揭露间谍",
                ["确认揭露所有间谍？", "揭露后无法悔棋！"],
                btns, hover,
            )
        elif d == DialogKind.SPY_REVEAL_RESULT:
            names = self.dialog_data.get("names", [])
            self.renderer.draw_dialog(
                "间谍转化完成", ["以下棋子已加入己方："] + names, btns, hover)
        elif d == DialogKind.SPY_EMPTY:
            self.renderer.draw_dialog("提示", ["己方间谍已全军覆没"], btns, hover)
        elif d == DialogKind.RANDOM_SOLDIER:
            self.renderer.draw_dialog(
                "随机士兵", ["已随机指定 2 名士兵为间谍", "（双方均不知道具体是谁）"],
                btns, hover)
        elif d == DialogKind.CONFIRM_RESTART:
            self.renderer.draw_dialog(
                "重新开始", ["确认放弃当前对局，重新开始？"], btns, hover)

    # ──────────────────────────────────────────
    # 暂停菜单
    # ──────────────────────────────────────────

    def _pause_buttons(self) -> list[tuple[str, pygame.Rect]]:
        cx = WINDOW_W // 2
        return [
            ("继续游戏",   _btn(cx, 230)),
            ("重新开始",   _btn(cx, 285)),
            ("规则说明",   _btn(cx, 340)),
            ("返回主菜单", _btn(cx, 395)),
        ]

    def _draw_pause(self) -> None:
        self.renderer.draw_pause_menu(self._pause_buttons(), self.menu_hover)

    def _click_pause(self, mx: int, my: int) -> None:
        for i, (_, rect) in enumerate(self._pause_buttons()):
            if rect.collidepoint(mx, my):
                if i == 0: self.paused = False
                elif i == 1: self._restart_game()
                elif i == 2: self.scene = "rules"
                elif i == 3: self.scene = "main_menu"; self.paused = False
                return

    # ──────────────────────────────────────────
    # 游戏结算
    # ──────────────────────────────────────────

    def _game_over_buttons(self) -> list[tuple[str, pygame.Rect]]:
        cx = WINDOW_W // 2
        return [
            ("重新开始",   _btn(cx - 90, WINDOW_H // 2 + 70)),
            ("返回主菜单", _btn(cx + 90, WINDOW_H // 2 + 70)),
        ]

    def _draw_game_over(self) -> None:
        self.renderer.draw_game_over(self.gs, self._game_over_buttons(), self.menu_hover)

    def _click_game_over(self, mx: int, my: int) -> None:
        for i, (_, rect) in enumerate(self._game_over_buttons()):
            if rect.collidepoint(mx, my):
                if i == 0: self._restart_game()
                else:      self.scene = "main_menu"

    # ──────────────────────────────────────────
    # 存档列表
    # ──────────────────────────────────────────

    def _open_saves(self) -> None:
        self.save_files = list_saves()
        self.scene      = "saves"
        self.save_hover = None

    def _saves_buttons(self) -> list[tuple[str, pygame.Rect]]:
        import os
        cx   = WINDOW_W // 2
        btns = []
        for i, path in enumerate(self.save_files[:8]):
            btns.append((os.path.basename(path), _btn(cx, 140 + i * 55, w=300, h=44)))
        btns.append(("返  回", _btn(cx, 600, w=140)))
        return btns

    def _draw_saves(self) -> None:
        self.screen.fill((30, 30, 30))
        surf = self.renderer.font_lg.render("选择存档", True, (255, 220, 80))
        self.screen.blit(surf, surf.get_rect(centerx=WINDOW_W // 2, top=60))
        for i, (label, rect) in enumerate(self._saves_buttons()):
            self.renderer.draw_button(label, rect, hover=(self.save_hover == i))

    def _click_saves(self, mx: int, my: int) -> None:
        btns = self._saves_buttons()
        for i, (_, rect) in enumerate(btns):
            if rect.collidepoint(mx, my):
                if i == len(btns) - 1:
                    self.scene  = "main_menu" if self.gs is None else "game"
                    self.paused = False
                else:
                    self.gs     = load_game(self.save_files[i])
                    self.scene  = "game"
                    self.paused = False
                    self._reset_selection()
                return

    # ──────────────────────────────────────────
    # 棋谱重播
    # ──────────────────────────────────────────

    def open_replay(self, path: str) -> None:
        self.replay_ctrl = ReplayController.from_file(path)
        self.scene       = "replay"

    def _replay_buttons(self) -> list[tuple[str, pygame.Rect]]:
        bar_y = WINDOW_H - 50
        return [
            ("|<",      pygame.Rect(200, bar_y + 8,  36, 34)),
            ("<",       pygame.Rect(248, bar_y + 8,  36, 34)),
            (">",       pygame.Rect(296, bar_y + 8,  36, 34)),
            (">|",      pygame.Rect(344, bar_y + 8,  36, 34)),
            ("退出重播", pygame.Rect(420, bar_y + 8, 100, 34)),
        ]

    def _draw_replay(self) -> None:
        if self.replay_ctrl is None:
            return
        rc = self.replay_ctrl
        self.renderer.draw(
            gs=rc.state,
            selected_piece=None,
            movable_pos=set(), capturable_pos=set(),
            last_from=None, last_to=None,
            show_last_move=False, show_movable=False,
            viewing_side=Side.RED,
            danger_lords=set(),
            hover_cell=None,
        )
        btns = self._replay_buttons()
        self.renderer.draw_replay_overlay(rc.current_step, rc.total_steps, btns, self.menu_hover)

    def _click_replay(self, mx: int, my: int) -> None:
        if self.replay_ctrl is None:
            return
        rc   = self.replay_ctrl
        btns = self._replay_buttons()
        for i, (_, rect) in enumerate(btns):
            if rect.collidepoint(mx, my):
                if i == 0: rc.jump_to(0)
                elif i == 1: rc.step_backward()
                elif i == 2: rc.step_forward()
                elif i == 3: rc.jump_to(rc.total_steps)
                elif i == 4: self.scene = "main_menu"
                return

    # ──────────────────────────────────────────
    # 键盘快捷键
    # ──────────────────────────────────────────

    def _on_key(self, key: int) -> None:
        gs = self.gs
        if key == pygame.K_ESCAPE:
            if self.scene == "mode_select":
                self.scene = "main_menu"
            elif self.scene == "rules":
                self.scene = "main_menu" if gs is None else "game"
            elif self.scene == "game":
                if self.spy_sub == SpySelectSub.CONFIRMING:
                    self.spy_sub = SpySelectSub.CHOOSING
                    self._spy_pending_piece = None
                else:
                    self.paused = not self.paused
            elif self.scene in ("saves", "replay"):
                self.scene = "main_menu" if gs is None else "game"
        elif self.scene == "game" and not self.paused and gs:
            is_pve = self.red_ai is not None or self.blue_ai is not None
            if gs.phase == Phase.PLAYING:
                if key == pygame.K_s:
                    self.dialog = DialogKind.SPY_REVEAL_CONFIRM
                elif key == pygame.K_u and not is_pve and gs.can_undo and gs.history:
                    gs.undo(); self._reset_selection()
                elif key == pygame.K_h and not is_pve:
                    self.show_last_move = not self.show_last_move
            if key in (pygame.K_RETURN, pygame.K_SPACE):
                if self.dialog != DialogKind.NONE:
                    self._handle_dialog_btn(0)

    # ──────────────────────────────────────────
    # 鼠标悬停
    # ──────────────────────────────────────────

    def _on_mouse_move(self, mx: int, my: int) -> None:
        self.hover_cell = self.renderer.screen_to_board(mx, my)

        # §14 MoveLog 悬停检测
        if self.scene == "game" and mx < LOG_PANEL_W:
            gs = self.gs
            if gs and gs.move_log:
                self._log_hover_index = self.renderer.log_entry_at_y(
                    my, self._log_scroll, gs.move_log.count
                )
            else:
                self._log_hover_index = None
        else:
            self._log_hover_index = None

        if self.scene == "main_menu":
            btns = [(l, r) for l, r in self._main_menu_buttons()]
        elif self.scene == "mode_select":
            btns = [(l, r) for l, r, _ in self._ms_buttons()]
        elif self.scene == "rules":
            # rules 界面的 hover 由 _click_rules 自行处理，此处更新列表 hover
            self._rules_hover = None
            for i, (_, rect) in enumerate(self._rules_list_rects()):
                if rect.collidepoint(mx, my):
                    self._rules_hover = i
                    break
            return
        elif self.scene == "game" and self.paused:
            btns = [(l, r) for l, r in self._pause_buttons()]
        elif self.scene == "game_over":
            btns = [(l, r) for l, r, _, _ in self._panel_buttons()]
        elif self.scene == "saves":
            for i, (_, rect) in enumerate(self._saves_buttons()):
                if rect.collidepoint(mx, my):
                    self.save_hover = i; return
            self.save_hover = None; return
        elif self.scene == "replay":
            btns = [(l, r) for l, r in self._replay_buttons()]
        elif self.scene == "game":
            btns = [(l, r) for l, r, _, _ in self._panel_buttons()]
        else:
            btns = []

        self.menu_hover = None
        for i, (_, rect) in enumerate(btns):
            if rect.collidepoint(mx, my):
                self.menu_hover = i; return
