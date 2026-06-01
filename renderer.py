"""
renderer.py — pygame 渲染层
仅负责绘制，不处理任何游戏逻辑。
"""

from __future__ import annotations
import pygame
import os
from typing import Optional
from engine import (
    GameState, Piece, PieceType, Side, Phase,
    FORTRESS_CELLS, PIECE_INFO, SpyManager
)
from move_log import MoveLog, MoveEntry

# ──────────────────────────────────────────────
# 颜色常量
# ──────────────────────────────────────────────
# ── 暗金风格配色 ──────────────────────────────
C_BG            = (20,  18,  14)    # 近黑背景
C_BOARD_LIGHT   = (62,  54,  42)    # 暗金亮格
C_BOARD_DARK    = (40,  34,  26)    # 暗金暗格
C_NEUTRAL_LINE  = (90, 110, 180)    # 中立区线（淡紫蓝）
C_GRID_LINE     = (28,  22,  14)    # 网格线（深棕）
C_BOARD_BORDER  = (120,  95,  50)   # 棋盘外框（亮金）

# 棋子主色
C_RED_PIECE     = (210,  65,  50)   # 红方主色
C_BLUE_PIECE    = ( 55, 115, 215)   # 蓝方主色
# 棋子高光/阴影层
C_RED_HI        = (240, 120,  90)   # 红方高光
C_RED_SH        = (110,  20,  10)   # 红方阴影
C_RED_BORDER    = ( 80,  10,   5)   # 红方外描边
C_BLUE_HI       = (110, 170, 255)   # 蓝方高光
C_BLUE_SH       = ( 15,  45, 120)   # 蓝方阴影
C_BLUE_BORDER   = (  5,  20,  90)   # 蓝方外描边

C_SPY_MARK      = (255, 220,   0)   # 间谍标记（保留常量，当前不渲染）
C_PIECE_TEXT    = (255, 255, 255)

HL_SELECTED     = (255, 230,  60)   # 选中棋子（亮金）
HL_MOVE         = ( 80, 220,  80)   # 可移动
HL_CAPTURE      = (240,  60,  60)   # 可吃子
HL_FORTRESS     = ( 50,  58,  90)   # 堡垒格底色（深紫蓝）
HL_LAST_FROM    = (180, 160,  60)   # 上一步起点
HL_LAST_TO      = (160,  80, 180)   # 上一步终点
HL_DANGER       = (255,  40,  40)   # 领主危险

C_PANEL_BG      = ( 28,  26,  22)   # 面板背景
C_PANEL_BORDER  = ( 90,  75,  45)   # 面板边框（暗金）
C_TEXT          = (220, 210, 190)   # 主文字（米白）
C_TEXT_DIM      = (110, 100,  80)   # 次要文字
C_BTN_NORMAL    = ( 55,  50,  38)   # 按钮常态
C_BTN_HOVER     = ( 80,  70,  50)   # 按钮悬停
C_BTN_ACTIVE    = ( 50, 100,  50)   # 按钮激活
C_BTN_DISABLED  = ( 38,  35,  28)   # 按钮禁用
C_BTN_TEXT      = (220, 210, 190)

# ──────────────────────────────────────────────
# 配置
# ──────────────────────────────────────────────
CELL_SIZE   = 64
BOARD_COLS  = 9
BOARD_ROWS  = 9
BOARD_PX    = CELL_SIZE * BOARD_COLS   # 576
BOARD_PY    = CELL_SIZE * BOARD_ROWS   # 576

# §14.1 左侧 MoveLog 面板
LOG_PANEL_W  = 220          # 棋谱面板宽度
LOG_PANEL_X  = 0            # 面板左边缘
_LOG_PADDING = 8            # 文字内边距

# 棋盘偏移（左侧面板 + 间距）
BOARD_OFF_X = LOG_PANEL_W + 20
BOARD_OFF_Y = 40

PANEL_X     = BOARD_OFF_X + BOARD_PX + 20
PANEL_W     = 200
WINDOW_W    = PANEL_X + PANEL_W + 20
WINDOW_H    = BOARD_OFF_Y + BOARD_PY + 60

# 棋谱条目行高
_LOG_ENTRY_H  = 22
_LOG_TITLE_H  = 32          # 标题栏高度

FONT_PATH   = None   # None 则使用 pygame 默认字体


def _load_font(size: int) -> pygame.font.Font:
    """
    字体加载优先级：
    1. 项目目录下的 msyh.ttf（微软雅黑，已预提取，确保中文字形正确）
    2. Windows 系统 msyh.ttc（fontNumber=0）
    3. simhei.ttf
    4. pygame 内置 fallback（仅 ASCII）
    """
    import os
    candidates = [
        os.path.join(os.path.dirname(__file__), "msyh.ttf"),
        r"C:\Windows\Fonts\msyh.ttc",
        r"C:\Windows\Fonts\simhei.ttf",
    ]
    for path in candidates:
        if os.path.exists(path):
            try:
                return pygame.font.Font(path, size)
            except Exception:
                pass
    return pygame.font.Font(None, size)


class Renderer:
    def __init__(self, screen: pygame.Surface) -> None:
        self.screen = screen
        self.font_sm  = _load_font(16)
        self.font_md  = _load_font(20)
        self.font_lg  = _load_font(28)
        self.font_xl  = _load_font(38)
        self.font_piece = _load_font(26)   # 棋子名称专用字体
        self._flash_tick = 0   # 用于闪烁效果
        self._shimmer_x: float = 0.0   # 流光扫描位置（横幅宽度归一化 0~1）

    def tick(self) -> None:
        self._flash_tick = (self._flash_tick + 1) % 60
        # 流光每帧推进，约 2.5 秒循环一次（60fps × 2.5 ≈ 150 帧）
        self._shimmer_x = (self._shimmer_x + 1.0 / 150.0) % 1.0

    # ── 坐标转换 ──────────────────────────────

    def board_to_screen(self, x: int, y: int) -> tuple[int, int]:
        """逻辑坐标 (x,y) → 屏幕像素（格子左上角）"""
        # y 轴渲染反向：逻辑 y=0 在底部，屏幕上在下方
        sx = BOARD_OFF_X + x * CELL_SIZE
        sy = BOARD_OFF_Y + (8 - y) * CELL_SIZE
        return sx, sy

    def screen_to_board(self, px: int, py: int) -> Optional[tuple[int, int]]:
        """屏幕像素 → 逻辑棋盘坐标，若在棋盘外返回 None"""
        bx = px - BOARD_OFF_X
        by = py - BOARD_OFF_Y
        if bx < 0 or by < 0 or bx >= BOARD_PX or by >= BOARD_PY:
            return None
        cx = bx // CELL_SIZE
        cy = 8 - (by // CELL_SIZE)
        return cx, cy

    # ── 主绘制入口 ────────────────────────────

    def draw(
        self,
        gs: GameState,
        selected_piece: Optional[Piece],
        movable_pos: set,
        capturable_pos: set,
        last_from: Optional[tuple],
        last_to:   Optional[tuple],
        show_last_move: bool,
        show_movable: bool,
        viewing_side: Side,
        danger_lords: set,
        hover_cell: Optional[tuple],
        move_log: Optional[MoveLog] = None,
        log_scroll: int = 0,
        review_index: Optional[int] = None,
        log_hover_index: Optional[int] = None,
        anim_override: "dict[int, tuple[float, float]] | None" = None,
        ai_thinking_info: "tuple[str, float] | None" = None,
    ) -> None:
        self.screen.fill(C_BG)
        self._draw_board_bg(gs, last_from, last_to, show_last_move)
        self._draw_highlights(movable_pos, capturable_pos, selected_piece, danger_lords)
        if show_movable:
            self._draw_all_movable(gs, viewing_side)
        self._draw_pieces(gs, selected_piece, viewing_side, anim_override)
        self._draw_turn_banner(gs, ai_thinking_info)   # 回合方横幅（棋盘顶部）
        self._draw_panel(gs, viewing_side)
        self._draw_coords()
        # §14：左侧棋谱面板
        self.draw_move_log(
            move_log=move_log,
            scroll=log_scroll,
            review_index=review_index,
            hover_index=log_hover_index,
            gs=gs,
        )

    # ── 回合方横幅 ────────────────────────────

    def _draw_turn_banner(
        self,
        gs: GameState,
        ai_thinking_info: "tuple[str, float] | None" = None,
    ) -> None:
        """棋盘顶部横幅：PLAYING显示回合方，GAME_OVER显示胜利方"""
        bx = BOARD_OFF_X
        by = 4
        bw = BOARD_PX
        bh = BOARD_OFF_Y - 8
        cy = by + bh // 2

        if gs.phase == Phase.GAME_OVER and gs.winner is not None:
            is_red     = gs.winner == Side.RED
            side_color = C_RED_PIECE if is_red else C_BLUE_PIECE
            hi_color   = C_RED_HI   if is_red else C_BLUE_HI
            side_str   = "红方" if is_red else "蓝方"

            # 横幅底色（比 PLAYING 更亮，强调结束）
            banner_surf = pygame.Surface((bw, bh), pygame.SRCALPHA)
            banner_surf.fill((30, 20, 10, 230))
            self.screen.blit(banner_surf, (bx, by))

            # 两端三角
            tri_w = 14
            pygame.draw.polygon(self.screen, side_color, [
                (bx, by), (bx + tri_w, by), (bx, by + bh)])
            pygame.draw.polygon(self.screen, side_color, [
                (bx + bw, by), (bx + bw - tri_w, by), (bx + bw, by + bh)])
            pygame.draw.line(self.screen, side_color,
                             (bx, by), (bx + bw, by), 1)
            pygame.draw.line(self.screen, side_color,
                             (bx, by + bh - 1), (bx + bw, by + bh - 1), 1)

            # 奖杯图标区域（左侧小圆）
            icon_x = bx + tri_w + 20
            icon_r = bh // 2 - 3
            pygame.draw.circle(self.screen,
                               C_RED_BORDER if is_red else C_BLUE_BORDER,
                               (icon_x, cy), icon_r + 2)
            pygame.draw.circle(self.screen, side_color, (icon_x, cy), icon_r)
            hi_s = pygame.Surface((icon_r * 2, icon_r * 2), pygame.SRCALPHA)
            pygame.draw.ellipse(hi_s, (*hi_color, 100),
                                (1, 1, int(icon_r * 0.9), int(icon_r * 0.55)))
            self.screen.blit(hi_s, (icon_x - icon_r, cy - icon_r))

            # 主标签：居中大字
            label_surf = self.font_lg.render(
                f"{side_str} 获胜！", True, side_color)
            self.screen.blit(label_surf, label_surf.get_rect(
                centerx=bx + bw // 2, centery=cy))

            # 右侧小字提示
            hint_surf = self.font_sm.render(
                "点击重新开始或返回主菜单", True, C_TEXT_DIM)
            self.screen.blit(hint_surf, hint_surf.get_rect(
                right=bx + bw - tri_w - 8, centery=cy))
            return

        if gs.phase != Phase.PLAYING:
            return

        is_red    = gs.current_side == Side.RED
        side_color = C_RED_PIECE if is_red else C_BLUE_PIECE
        hi_color   = C_RED_HI   if is_red else C_BLUE_HI
        side_str   = "红方" if is_red else "蓝方"

        # ── 横幅底色（半透明深色）
        banner_surf = pygame.Surface((bw, bh), pygame.SRCALPHA)
        banner_surf.fill((15, 13, 10, 210))
        self.screen.blit(banner_surf, (bx, by))

        # ── 流光扫描效果（仅 AI 思考时显示）
        if ai_thinking_info is not None:
            self._draw_banner_shimmer(bx, by, bw, bh, side_color)

        # ── 左侧三角尖角装饰
        tri_w = 14
        pygame.draw.polygon(self.screen, side_color, [
            (bx,          by),
            (bx + tri_w,  by),
            (bx,          by + bh),
        ])
        # 右侧对称三角
        pygame.draw.polygon(self.screen, side_color, [
            (bx + bw,          by),
            (bx + bw - tri_w,  by),
            (bx + bw,          by + bh),
        ])

        # ── 横幅上下细边线
        pygame.draw.line(self.screen, side_color, (bx, by),        (bx + bw, by),        1)
        pygame.draw.line(self.screen, side_color, (bx, by + bh - 1), (bx + bw, by + bh - 1), 1)

        # ── 棋子小圆图标（左侧）
        icon_x = bx + tri_w + 20
        icon_r = bh // 2 - 3
        pygame.draw.circle(self.screen, C_RED_BORDER if is_red else C_BLUE_BORDER,
                           (icon_x, cy), icon_r + 2)
        pygame.draw.circle(self.screen, side_color, (icon_x, cy), icon_r)
        # 高光点
        hi_s = pygame.Surface((icon_r * 2, icon_r * 2), pygame.SRCALPHA)
        pygame.draw.ellipse(hi_s, (*hi_color, 100),
                            (1, 1, int(icon_r * 0.9), int(icon_r * 0.55)))
        self.screen.blit(hi_s, (icon_x - icon_r, cy - icon_r))

        # ── 回合数字（紧靠图标右侧，小字）
        turn_surf = self.font_sm.render(f"第 {gs.turn_number} 回合", True,
                                        (160, 150, 120))
        self.screen.blit(turn_surf, turn_surf.get_rect(
            left=icon_x + icon_r + 8, centery=cy))

        # ── 主标签（居中，大字，亮色）
        label_surf = self.font_lg.render(f"{side_str} 行动", True, side_color)
        self.screen.blit(label_surf, label_surf.get_rect(
            centerx=bx + bw // 2, centery=cy))

        # ── AI 思考提示（右侧，仅思考中时显示）
        if ai_thinking_info is not None:
            diff_name, elapsed = ai_thinking_info
            # 脉冲省略号：利用 _flash_tick 在 "···" 和 " ·· " 之间切换
            dots = "●●●" if self._flash_tick < 20 else ("○●●" if self._flash_tick < 40 else "○○●")
            think_text = f"AI[{diff_name}] 思考中 {dots}  {elapsed:.1f}s"
            think_surf = self.font_sm.render(think_text, True, (200, 200, 100))
            self.screen.blit(think_surf, think_surf.get_rect(
                right=bx + bw - tri_w - 8, centery=cy))

    def _draw_banner_shimmer(
        self, bx: int, by: int, bw: int, bh: int,
        tint: tuple,
    ) -> None:
        """在横幅区域绘制斜向流光扫描效果（仅 AI 思考时调用）。

        光带为倾斜平行四边形，顶部向右偏移 skew px，产生约 20° 斜角。
        边界锐利：只有极窄的软化过渡区，主体区域保持高亮度。
        """
        skew   = bh // 2        # 顶部相对底部偏移（越大越倾斜）
        beam_w = int(bw * 0.10) # 光带核心宽度（约 10% 横幅宽）
        fade_w = max(4, beam_w // 5)  # 两侧软化区极窄，边界锐利

        total_w = beam_w + fade_w * 2
        # 光带中心 x（基于底边）：从 -total_w 扫到 bw+total_w
        cx_bot = int((bw + total_w * 2) * self._shimmer_x) - total_w

        r, g, b = tint
        shimmer = pygame.Surface((bw, bh), pygame.SRCALPHA)

        # 逐列绘制倾斜光带
        # 对于屏幕 x 列 col（底部坐标），顶部对应 col + skew
        # 光带占据 [cx_bot - total_w//2, cx_bot + total_w//2]（底部坐标）
        left  = cx_bot - total_w // 2
        right = cx_bot + total_w // 2

        for col in range(max(0, left - skew), min(bw, right + 1)):
            # 对于屏幕列 col，计算其在底部坐标系中的位置（垂直方向插值）
            # row=0（顶）对应底部偏移 +skew，row=bh-1（底）对应偏移 0
            # 逐行计算以实现倾斜效果
            for row in range(bh):
                t_row  = row / max(1, bh - 1)          # 0(顶)→1(底)
                bot_x  = col + skew * (1.0 - t_row)    # 该像素对应的底部虚拟坐标
                dist   = abs(bot_x - cx_bot) - beam_w // 2
                if dist <= 0:
                    alpha = 90          # 核心区固定高亮
                elif dist < fade_w:
                    alpha = int(90 * (1.0 - dist / fade_w))  # 线性软化
                else:
                    continue
                shimmer.set_at((col, row), (r, g, b, alpha))

        self.screen.blit(shimmer, (bx, by))

    # ── 棋盘底色 ──────────────────────────────

    def _draw_board_bg(
        self, gs: GameState,
        last_from: Optional[tuple], last_to: Optional[tuple],
        show_last_move: bool,
    ) -> None:
        cs = CELL_SIZE

        for gy in range(9):
            for gx in range(9):
                sx, sy = self.board_to_screen(gx, gy)
                rect = pygame.Rect(sx, sy, cs, cs)

                # ── 基础格子色
                is_fortress = (gx, gy) in FORTRESS_CELLS
                if is_fortress:
                    base_color = HL_FORTRESS
                elif (gx + gy) % 2 == 0:
                    base_color = C_BOARD_LIGHT
                else:
                    base_color = C_BOARD_DARK

                # ── 上一步高亮覆盖基础色
                if show_last_move:
                    if last_from and (gx, gy) == last_from:
                        base_color = HL_LAST_FROM
                    if last_to and (gx, gy) == last_to:
                        base_color = HL_LAST_TO

                pygame.draw.rect(self.screen, base_color, rect)

                # ── 格子内光感渐变（左上亮角，右下暗角）
                if not is_fortress:
                    grad_surf = pygame.Surface((cs, cs), pygame.SRCALPHA)
                    # 左上亮三角
                    pygame.draw.polygon(grad_surf, (255, 255, 255, 18),
                                        [(0, 0), (cs, 0), (0, cs)])
                    # 右下暗三角
                    pygame.draw.polygon(grad_surf, (0, 0, 0, 22),
                                        [(cs, 0), (cs, cs), (0, cs)])
                    self.screen.blit(grad_surf, (sx, sy))

                # ── 堡垒格专属纹理（斜线 + 半透明叠加）
                if is_fortress:
                    fort_surf = pygame.Surface((cs, cs), pygame.SRCALPHA)
                    # 斜线纹理
                    stripe_c = (100, 120, 200, 50)
                    step = 10
                    for i in range(-cs, cs * 2, step):
                        pygame.draw.line(fort_surf, stripe_c,
                                         (i, 0), (i + cs, cs), 1)
                    # 中心菱形装饰
                    half = cs // 2
                    pygame.draw.polygon(fort_surf, (120, 140, 220, 80), [
                        (half,     8),
                        (cs - 8,   half),
                        (half,     cs - 8),
                        (8,        half),
                    ])
                    pygame.draw.polygon(fort_surf, (160, 180, 255, 50), [
                        (half,     8),
                        (cs - 8,   half),
                        (half,     cs - 8),
                        (8,        half),
                    ], 2)
                    self.screen.blit(fort_surf, (sx, sy))

                # ── 中立区竖线（带透明度）
                if gx == 4:
                    nl_surf = pygame.Surface((cs, cs), pygame.SRCALPHA)
                    pygame.draw.rect(nl_surf, (*C_NEUTRAL_LINE, 120),
                                     (0, 0, cs, cs), 2)
                    self.screen.blit(nl_surf, (sx, sy))

                # ── 网格线
                pygame.draw.rect(self.screen, C_GRID_LINE, rect, 1)

                # ── 堡垒格文字标注
                if is_fortress:
                    f_surf = self.font_sm.render("堡垒", True, (160, 180, 255))
                    self.screen.blit(f_surf, f_surf.get_rect(
                        centerx=sx + cs // 2,
                        centery=sy + cs // 2,
                    ))

        # ── 堡垒影响范围（被占用时，周围8格淡蓝半透明叠加）
        fort_range_surf = pygame.Surface((cs, cs), pygame.SRCALPHA)
        pygame.draw.rect(fort_range_surf, (80, 140, 220, 40), (0, 0, cs, cs))
        for (fx, fy) in FORTRESS_CELLS:
            occupant = gs.board.get(fx, fy)
            if occupant is not None:
                for dx in (-1, 0, 1):
                    for dy in (-1, 0, 1):
                        if dx == 0 and dy == 0:
                            continue
                        nx, ny = fx + dx, fy + dy
                        if 0 <= nx < 9 and 0 <= ny < 9:
                            sx, sy = self.board_to_screen(nx, ny)
                            self.screen.blit(fort_range_surf, (sx, sy))

        # ── 棋盘外框（加粗金色边框）
        border_rect = pygame.Rect(
            BOARD_OFF_X, BOARD_OFF_Y, BOARD_PX, BOARD_PY)
        pygame.draw.rect(self.screen, C_BOARD_BORDER, border_rect, 3)

    # ── 高亮覆盖层 ────────────────────────────

    def _draw_highlights(
        self,
        movable_pos: set,
        capturable_pos: set,
        selected_piece: Optional[Piece],
        danger_lords: set,
    ) -> None:
        cs = CELL_SIZE

        # ── 可移动：半透明绿色圆形（占格子40%）
        r_move = int(cs * 0.22)
        move_surf = pygame.Surface((cs, cs), pygame.SRCALPHA)
        pygame.draw.circle(move_surf, (*HL_MOVE, 160),
                           (cs // 2, cs // 2), r_move)
        # 细圆圈外轮廓
        pygame.draw.circle(move_surf, (*HL_MOVE, 80),
                           (cs // 2, cs // 2), r_move + 2, 2)
        for (gx, gy) in movable_pos:
            sx, sy = self.board_to_screen(gx, gy)
            self.screen.blit(move_surf, (sx, sy))

        # ── 可吃子：脉冲红色边框（利用 _flash_tick 在两种粗细间切换）
        pulse = self._flash_tick < 30
        cap_w = 4 if pulse else 2
        cap_alpha = 220 if pulse else 140
        for (gx, gy) in capturable_pos:
            sx, sy = self.board_to_screen(gx, gy)
            # 半透明底色叠加
            cap_bg = pygame.Surface((cs, cs), pygame.SRCALPHA)
            cap_bg.fill((*HL_CAPTURE, 45))
            self.screen.blit(cap_bg, (sx, sy))
            # 边框
            cap_surf = pygame.Surface((cs, cs), pygame.SRCALPHA)
            pygame.draw.rect(cap_surf, (*HL_CAPTURE, cap_alpha),
                             (0, 0, cs, cs), cap_w)
            self.screen.blit(cap_surf, (sx, sy))

        # ── 选中棋子：发光边框（3层由亮到暗，宽度递减）
        if selected_piece:
            sx, sy = self.board_to_screen(selected_piece.x, selected_piece.y)
            glow_layers = [
                ((*HL_SELECTED, 40),  6),
                ((*HL_SELECTED, 120), 3),
                ((*HL_SELECTED, 220), 2),
            ]
            for color_a, width in glow_layers:
                g_surf = pygame.Surface((cs, cs), pygame.SRCALPHA)
                pygame.draw.rect(g_surf, color_a, (0, 0, cs, cs), width)
                self.screen.blit(g_surf, (sx, sy))

        # ── 危险领主：闪烁红色边框
        flash_on = self._flash_tick < 30
        if flash_on:
            for (gx, gy) in danger_lords:
                sx, sy = self.board_to_screen(gx, gy)
                d_surf = pygame.Surface((cs, cs), pygame.SRCALPHA)
                pygame.draw.rect(d_surf, (*HL_DANGER, 200),
                                 (0, 0, cs, cs), 4)
                self.screen.blit(d_surf, (sx, sy))

    def _draw_all_movable(self, gs: GameState, viewing_side: Side) -> None:
        """高亮当前方所有可动棋子（橙色半透明边框）"""
        orange = (255, 160, 30)
        cs = CELL_SIZE
        for p in gs.board.pieces_of(viewing_side):
            mv, cap = gs.board.get_moves(p, gs.fortress_cooldown)
            if mv or cap:
                sx, sy = self.board_to_screen(p.x, p.y)
                o_surf = pygame.Surface((cs, cs), pygame.SRCALPHA)
                pygame.draw.rect(o_surf, (*orange, 160), (0, 0, cs, cs), 2)
                self.screen.blit(o_surf, (sx, sy))

    # ── 棋子绘制 ──────────────────────────────

    def _draw_pieces(
        self, gs: GameState,
        selected_piece: Optional[Piece],
        viewing_side: Side,
        anim_override: "dict[int, tuple[float, float]] | None" = None,
    ) -> None:
        for piece in gs.board.all_pieces():
            self._draw_one_piece(
                piece, gs.spy_manager, viewing_side,
                selected=(selected_piece is not None
                          and piece.id == selected_piece.id),
                screen_pos=anim_override.get(piece.id) if anim_override else None,
            )

    def _draw_one_piece(
        self, piece: Piece, spy: SpyManager,
        viewing_side: Side, selected: bool,
        screen_pos: "tuple[float, float] | None" = None,
    ) -> None:
        if screen_pos is not None:
            # 动画插值坐标（格子左上角，浮点）
            sx, sy = screen_pos
        else:
            sx, sy = self.board_to_screen(piece.x, piece.y)
        cx = int(sx + CELL_SIZE // 2)
        cy = int(sy + CELL_SIZE // 2)
        r = int(CELL_SIZE * 0.38)

        # 显示颜色（始终用 piece.side）
        display = spy.display_side(piece.id, piece.side)
        if display == Side.RED:
            main_c, hi_c, sh_c, bd_c = C_RED_PIECE, C_RED_HI, C_RED_SH, C_RED_BORDER
        else:
            main_c, hi_c, sh_c, bd_c = C_BLUE_PIECE, C_BLUE_HI, C_BLUE_SH, C_BLUE_BORDER

        # ── 投影（左下偏移，暗色大圆）
        pygame.draw.circle(self.screen, bd_c, (cx + 2, cy + 3), r + 3)

        # ── 外描边（深色）
        pygame.draw.circle(self.screen, bd_c, (cx, cy), r + 2)

        # ── 主体（阴影侧：右下用更暗色）
        pygame.draw.circle(self.screen, sh_c, (cx + 2, cy + 2), r)

        # ── 主体（主色）
        pygame.draw.circle(self.screen, main_c, (cx, cy), r)

        # ── 渐变高光：多层半透明圆，偏左上
        hi_surf = pygame.Surface((r * 2, r * 2), pygame.SRCALPHA)
        # 大高光椭圆
        pygame.draw.ellipse(hi_surf, (*hi_c, 70),
                            (2, 2, int(r * 1.1), int(r * 0.7)))
        # 小高光亮点
        pygame.draw.ellipse(hi_surf, (*hi_c, 110),
                            (6, 5, int(r * 0.5), int(r * 0.35)))
        self.screen.blit(hi_surf, (cx - r, cy - r))

        # ── 内圈描边（亮色，增加立体感）
        pygame.draw.circle(self.screen, hi_c, (cx, cy), r, 1)

        # ── 文字阴影 + 文字
        char = PIECE_INFO[int(piece.type)]["char"]
        # 阴影（偏移1px，深色）
        sh_surf = self.font_piece.render(char, True, bd_c)
        self.screen.blit(sh_surf, sh_surf.get_rect(center=(cx + 1, cy + 1)))
        # 正文（白色）
        txt_surf = self.font_piece.render(char, True, C_PIECE_TEXT)
        self.screen.blit(txt_surf, txt_surf.get_rect(center=(cx, cy)))

        # ── 等级圆环（绘制在文字之上，始终在最顶层）
        self._draw_tier_rings(cx, cy, r, int(piece.type))

    def _draw_tier_rings(self, cx: int, cy: int, r: int, piece_type: int) -> None:
        """在棋子内部底部绘制等级/阵营弧线标记。
        弧线位于棋子圆内侧，覆盖下半段，粗线可延伸至文字下方。
        """
        import math
        ring_color, count, width = PIECE_INFO[piece_type]["ring"]

        # 弧线覆盖下半圆：从210°到330°（pygame arc 用弧度，逆时针为正）
        # pygame.draw.arc 的角度：0=右，逆时针增加
        # 下半弧：start_angle=-150°(-5π/6)，stop_angle=-30°(-π/6)
        START = math.radians(-150)
        STOP  = math.radians(-30)

        if count == 1:
            arc_r = r - 4   # 内侧，稍留边距
            rect = pygame.Rect(cx - arc_r, cy - arc_r, arc_r * 2, arc_r * 2)
            pygame.draw.arc(self.screen, ring_color, rect, START, STOP, width)
        else:  # count == 2：内外两条弧，间距4px
            arc_r1 = r - 3   # 外弧（靠近边缘）
            arc_r2 = r - 8   # 内弧
            rect1 = pygame.Rect(cx - arc_r1, cy - arc_r1, arc_r1 * 2, arc_r1 * 2)
            rect2 = pygame.Rect(cx - arc_r2, cy - arc_r2, arc_r2 * 2, arc_r2 * 2)
            pygame.draw.arc(self.screen, ring_color, rect1, START, STOP, width + 1)
            pygame.draw.arc(self.screen, ring_color, rect2, START, STOP, width + 1)

    # ── 右侧面板 ──────────────────────────────

    def _draw_panel(self, gs: GameState, viewing_side: Side) -> None:
        # 仅填充背景色，不画边框，避免与顶部横幅产生视觉冲突
        rect = pygame.Rect(PANEL_X - 10, 0, PANEL_W + 10, WINDOW_H)
        pygame.draw.rect(self.screen, C_PANEL_BG, rect)

        # ── 游戏结算时，在面板顶部显示胜负信息 ──
        if gs.phase == Phase.GAME_OVER and gs.winner is not None:
            cx = PANEL_X + PANEL_W // 2
            is_red    = gs.winner == Side.RED
            win_color = C_RED_PIECE if is_red else C_BLUE_PIECE
            win_str   = "红方获胜！" if is_red else "蓝方获胜！"

            # 分隔线
            sep_y = BOARD_OFF_Y - 4
            pygame.draw.line(self.screen, win_color,
                             (PANEL_X - 8, sep_y), (PANEL_X + PANEL_W + 8, sep_y), 2)

            # 流式排列：大字 → 小字，各留 8px 间距
            y = BOARD_OFF_Y + 16
            w_surf = self.font_lg.render(win_str, True, win_color)
            self.screen.blit(w_surf, w_surf.get_rect(centerx=cx, top=y))
            y += w_surf.get_height() + 8

            t_surf = self.font_sm.render(f"共 {gs.turn_number} 回合", True, C_TEXT_DIM)
            self.screen.blit(t_surf, t_surf.get_rect(centerx=cx, top=y))

    def _draw_text(
        self, text: str, x: int, y: int,
        font: Optional[pygame.font.Font] = None,
        color: tuple = C_TEXT,
    ) -> pygame.Rect:
        if font is None:
            font = self.font_md
        surf = font.render(text, True, color)
        self.screen.blit(surf, (x, y))
        return surf.get_rect(topleft=(x, y))

    def _draw_coords(self) -> None:
        """在棋盘四周绘制坐标标注：X轴用字母A-I，Y轴用数字1-9"""
        for i in range(9):
            # 底部 x 坐标（A-I）
            sx, _ = self.board_to_screen(i, 0)
            label = chr(ord('A') + i)
            surf = self.font_sm.render(label, True, C_TEXT_DIM)
            self.screen.blit(surf, (sx + CELL_SIZE // 2 - 4,
                                    BOARD_OFF_Y + BOARD_PY + 4))
            # 左侧 y 坐标（1-9）
            _, sy = self.board_to_screen(0, i)
            surf = self.font_sm.render(str(i + 1), True, C_TEXT_DIM)
            self.screen.blit(surf, (BOARD_OFF_X - 16,
                                    sy + CELL_SIZE // 2 - 6))

    # ── 左侧棋谱面板（§14）────────────────────

    def draw_move_log(
        self,
        move_log: Optional[MoveLog],
        scroll: int,
        review_index: Optional[int],
        hover_index: Optional[int],
        gs: Optional[GameState],
    ) -> None:
        """绘制左侧 MoveLog 面板（§14.1/§14.9）"""
        panel_rect = pygame.Rect(LOG_PANEL_X, 0, LOG_PANEL_W, WINDOW_H)
        pygame.draw.rect(self.screen, C_PANEL_BG, panel_rect)
        pygame.draw.rect(self.screen, C_PANEL_BORDER, panel_rect, 1)

        # 标题栏
        title_rect = pygame.Rect(LOG_PANEL_X, 0, LOG_PANEL_W, _LOG_TITLE_H)
        pygame.draw.rect(self.screen, (55, 55, 65), title_rect)
        title_surf = self.font_md.render("棋谱记录", True, (255, 220, 80))
        self.screen.blit(title_surf, title_surf.get_rect(
            centerx=LOG_PANEL_X + LOG_PANEL_W // 2,
            centery=_LOG_TITLE_H // 2,
        ))

        # 分隔线
        pygame.draw.line(
            self.screen, C_PANEL_BORDER,
            (LOG_PANEL_X, _LOG_TITLE_H),
            (LOG_PANEL_X + LOG_PANEL_W, _LOG_TITLE_H), 1,
        )

        # 可用显示区域
        list_top  = _LOG_TITLE_H + 4
        list_h    = WINDOW_H - list_top - 4
        max_items = list_h // _LOG_ENTRY_H

        # 空状态
        if move_log is None or move_log.count == 0:
            hint = "等待选择间谍..." if (
                gs is not None and gs.phase == Phase.SELECTING_SPY
            ) else "暂无记录"
            surf = self.font_sm.render(hint, True, C_TEXT_DIM)
            self.screen.blit(surf, surf.get_rect(
                centerx=LOG_PANEL_X + LOG_PANEL_W // 2,
                top=list_top + 20,
            ))
            return

        entries   = move_log.entries
        total     = len(entries)
        # 限制滚动范围
        max_scroll = max(0, total - max_items)
        scroll     = max(0, min(scroll, max_scroll))

        # 回溯模式高亮索引（或最新）
        if review_index is not None:
            highlight = review_index
        else:
            highlight = total - 1

        # 绘制可见条目
        for i in range(max_items):
            idx = i + scroll
            if idx >= total:
                break
            entry    = entries[idx]
            ey       = list_top + i * _LOG_ENTRY_H
            item_rect = pygame.Rect(LOG_PANEL_X + 2, ey,
                                    LOG_PANEL_W - 4, _LOG_ENTRY_H)

            # 背景
            if idx == highlight:
                bg_color = (80, 110, 80)   # 当前/高亮条目
            elif hover_index is not None and idx == hover_index:
                bg_color = (60, 60, 80)    # 悬停
            else:
                bg_color = C_PANEL_BG
            pygame.draw.rect(self.screen, bg_color, item_rect)

            # 条目文字（截断超长文本）
            text  = entry.notation
            color = C_TEXT if idx == highlight else C_TEXT_DIM
            surf  = self.font_sm.render(text, True, color)
            # 裁剪到面板宽度
            clip_w = LOG_PANEL_W - _LOG_PADDING * 2
            if surf.get_width() > clip_w:
                surf = surf.subsurface((0, 0, clip_w, surf.get_height()))
            self.screen.blit(surf, (LOG_PANEL_X + _LOG_PADDING,
                                    ey + (_LOG_ENTRY_H - surf.get_height()) // 2))

        # 右侧滚动条（条目多于可见区时）
        if total > max_items:
            bar_x    = LOG_PANEL_X + LOG_PANEL_W - 6
            bar_top  = list_top
            bar_h    = WINDOW_H - bar_top
            ratio    = max_items / total
            thumb_h  = max(16, int(bar_h * ratio))
            thumb_y  = bar_top + int((bar_h - thumb_h) * scroll / max_scroll) if max_scroll > 0 else bar_top
            pygame.draw.rect(self.screen, (70, 70, 80),
                             (bar_x, bar_top, 4, bar_h))
            pygame.draw.rect(self.screen, (140, 140, 160),
                             (bar_x, thumb_y, 4, thumb_h))

    def log_entry_at_y(self, py: int, scroll: int, total: int) -> Optional[int]:
        """
        根据屏幕 y 坐标返回点击的条目索引（§14.8 点击回溯入口）。
        在面板范围外返回 None。
        """
        if py < _LOG_TITLE_H or py >= WINDOW_H:
            return None
        list_top = _LOG_TITLE_H + 4
        rel_y    = py - list_top
        if rel_y < 0:
            return None
        item_i = rel_y // _LOG_ENTRY_H
        idx    = item_i + scroll
        if 0 <= idx < total:
            return idx
        return None

    # ── 通用按钮绘制 ──────────────────────────

    def draw_button(
        self,
        text: str,
        rect: pygame.Rect,
        hover: bool = False,
        active: bool = False,
        disabled: bool = False,
    ) -> None:
        if disabled:
            color = C_BTN_DISABLED
            text_color = C_TEXT_DIM
        elif active:
            color = C_BTN_ACTIVE
            text_color = C_BTN_TEXT
        elif hover:
            color = C_BTN_HOVER
            text_color = C_BTN_TEXT
        else:
            color = C_BTN_NORMAL
            text_color = C_BTN_TEXT

        pygame.draw.rect(self.screen, color, rect, border_radius=4)
        pygame.draw.rect(self.screen, C_PANEL_BORDER, rect, 1, border_radius=4)
        surf = self.font_md.render(text, True, text_color)
        self.screen.blit(surf, surf.get_rect(center=rect.center))

    # ── 弹窗 ──────────────────────────────────

    def draw_dialog(
        self,
        title: str,
        lines: list[str],
        buttons: list[tuple[str, pygame.Rect]],
        hover_btn: Optional[int] = None,
    ) -> None:
        """通用弹窗（半透明遮罩 + 居中面板）"""
        overlay = pygame.Surface(self.screen.get_size(), pygame.SRCALPHA)
        overlay.fill((0, 0, 0, 160))
        self.screen.blit(overlay, (0, 0))

        # 弹窗背景
        all_rects = [r for _, r in buttons]
        if all_rects:
            min_x = min(r.left for r in all_rects) - 30
            max_x = max(r.right for r in all_rects) + 30
            min_y = (self.screen.get_height() // 2
                     - 40 - 24 * len(lines) - 30)
            max_y = max(r.bottom for r in all_rects) + 20
        else:
            cx = self.screen.get_width() // 2
            min_x, max_x = cx - 200, cx + 200
            min_y = self.screen.get_height() // 2 - 80
            max_y = min_y + 160

        panel = pygame.Rect(min_x, min_y, max_x - min_x, max_y - min_y)
        pygame.draw.rect(self.screen, C_PANEL_BG, panel, border_radius=8)
        pygame.draw.rect(self.screen, C_PANEL_BORDER, panel, 2, border_radius=8)

        # 标题
        surf = self.font_lg.render(title, True, (255, 220, 80))
        self.screen.blit(surf, surf.get_rect(centerx=panel.centerx, top=panel.top + 16))

        # 正文
        ty = panel.top + 56
        for line in lines:
            surf = self.font_md.render(line, True, C_TEXT)
            self.screen.blit(surf, surf.get_rect(centerx=panel.centerx, top=ty))
            ty += 26

        # 按钮
        for i, (label, rect) in enumerate(buttons):
            self.draw_button(label, rect, hover=(hover_btn == i))

    # ── 主菜单 ────────────────────────────────

    def draw_main_menu(
        self,
        buttons: list[tuple[str, pygame.Rect]],
        hover_btn: Optional[int],
    ) -> None:
        self.screen.fill(C_BG)
        cx = WINDOW_W // 2
        # 标题装饰 — 固定在顶部 1/3 区域
        pygame.draw.line(self.screen, (120, 95, 50), (cx - 180, 80), (cx + 180, 80), 1)
        title_surf = self.font_xl.render("间 谍 象 棋", True, (230, 185, 60))
        self.screen.blit(title_surf, title_surf.get_rect(centerx=cx, top=90))
        pygame.draw.line(self.screen, (120, 95, 50), (cx - 180, 148), (cx + 180, 148), 1)
        sub_surf = self.font_md.render("Spy Chess", True, C_TEXT_DIM)
        self.screen.blit(sub_surf, sub_surf.get_rect(centerx=cx, top=158))
        # 按钮
        for i, (label, rect) in enumerate(buttons):
            self.draw_button(label, rect, hover=(hover_btn == i))

    # ── 模式选择界面 ──────────────────────────

    def draw_mode_select(
        self,
        mode: str,
        player_side: int,
        difficulty: int,
        buttons: list[tuple[str, pygame.Rect, bool]],
        mx: int,
        my: int,
    ) -> None:
        """绘制 PVP / PVE 模式选择页（卡片分组纵向居中布局）"""
        self.screen.fill(C_BG)
        cx = WINDOW_W // 2

        # 标题
        pygame.draw.line(self.screen, (120, 95, 50), (cx - 200, 80), (cx + 200, 80), 1)
        title_surf = self.font_xl.render("选 择 游 戏 模 式", True, (230, 185, 60))
        self.screen.blit(title_surf, title_surf.get_rect(centerx=cx, top=90))
        pygame.draw.line(self.screen, (120, 95, 50), (cx - 200, 148), (cx + 200, 148), 1)

        # 从按钮列表中提取各组标题位置（取每组第一个按钮的 top 减去 42 作为标签 y）
        is_pve = mode == "pve"
        CONTENT_H_PVP = 92 + 98
        CONTENT_H_PVE = 92 + 92 + 92 + 98
        AVAIL     = 676 - 165
        content_h = CONTENT_H_PVE if is_pve else CONTENT_H_PVP
        y0 = 165 + (AVAIL - content_h) // 2   # 与 ui.py _ms_buttons 保持一致

        # 小节标签
        def _section_label(text: str, label_y: int) -> None:
            s = self.font_sm.render(text, True, C_TEXT_DIM)
            self.screen.blit(s, s.get_rect(centerx=cx, top=label_y))
            # 分隔线
            pygame.draw.line(self.screen, C_PANEL_BORDER,
                             (cx - 180, label_y + 22), (cx + 180, label_y + 22), 1)

        _section_label("游 戏 模 式", y0)
        y0 += 92
        if is_pve:
            _section_label("玩 家 阵 营", y0)
            y0 += 92
            _section_label("AI  难  度", y0)

        # 按钮
        for label, rect, is_active in buttons:
            is_hover  = rect.collidepoint(mx, my)
            is_action = label in ("开始游戏", "取  消")
            if is_active and not is_action:
                # toggle 激活态：绿色背景
                pygame.draw.rect(self.screen, C_BTN_ACTIVE, rect, border_radius=4)
                pygame.draw.rect(self.screen, (80, 180, 80), rect, 1, border_radius=4)
                text_surf = self.font_md.render(label, True, (200, 255, 200))
                self.screen.blit(text_surf, text_surf.get_rect(center=rect.center))
            else:
                self.draw_button(label, rect, hover=is_hover, active=False)

    # ── 游戏结算画面 ──────────────────────────

    def draw_game_over(
        self,
        gs: GameState,
        buttons: list[tuple[str, pygame.Rect]],
        hover_btn: Optional[int],
    ) -> None:
        overlay = pygame.Surface(self.screen.get_size(), pygame.SRCALPHA)
        overlay.fill((0, 0, 0, 180))
        self.screen.blit(overlay, (0, 0))

        cx = self.screen.get_width() // 2
        cy = self.screen.get_height() // 2

        w_str = "红方获胜！" if gs.winner == Side.RED else "蓝方获胜！"
        c = C_RED_PIECE if gs.winner == Side.RED else C_BLUE_PIECE
        surf = self.font_xl.render(w_str, True, c)
        self.screen.blit(surf, surf.get_rect(center=(cx, cy - 60)))

        turn_surf = self.font_md.render(
            f"共 {gs.turn_number} 回合", True, C_TEXT)
        self.screen.blit(turn_surf, turn_surf.get_rect(center=(cx, cy - 10)))

        for i, (label, rect) in enumerate(buttons):
            self.draw_button(label, rect, hover=(hover_btn == i))

    # ── 暂停菜单 ──────────────────────────────

    def draw_pause_menu(
        self,
        buttons: list[tuple[str, pygame.Rect]],
        hover_btn: Optional[int],
    ) -> None:
        overlay = pygame.Surface(self.screen.get_size(), pygame.SRCALPHA)
        overlay.fill((0, 0, 0, 160))
        self.screen.blit(overlay, (0, 0))

        cx = self.screen.get_width() // 2
        surf = self.font_lg.render("暂  停", True, (255, 220, 80))
        self.screen.blit(surf, surf.get_rect(centerx=cx, top=120))

        for i, (label, rect) in enumerate(buttons):
            self.draw_button(label, rect, hover=(hover_btn == i))

    # ── 规则说明界面 ──────────────────────────

    # 每种棋子的演示配置：
    # demo_piece_pos: (x, y) 主棋子逻辑坐标（红方，y=2或3，向上为前方）
    # extra_pieces: [(PieceType, Side, x, y), ...]  配对棋子列表
    _DEMO_CONFIGS: "dict[int, dict]" = {
        # 士兵：前方空（直走），斜前方1枚蓝方（体现斜吃，不能直吃）
        0:  {"pos": (4, 2), "extras": [(0, 1, 5, 3)]},
        # 大臣：侧面1枚蓝方（体现可横向吃，区别于只能前方的棋子）
        1:  {"pos": (4, 2), "extras": [(0, 1, 5, 2)]},
        # 军官：前方+左前各1枚蓝方（体现前3方向，无侧吃后吃）
        2:  {"pos": (4, 2), "extras": [(0, 1, 4, 3), (0, 1, 3, 3)]},
        # 骑士：1个L形落点放蓝方（体现马跳形状）
        3:  {"pos": (4, 2), "extras": [(0, 1, 6, 3)]},
        # 刺客：纵向炮架(4,4)+靶(4,6)（体现炮击隔子吃）
        4:  {"pos": (4, 2), "extras": [(0, 0, 4, 4), (0, 1, 4, 6)]},
        # 铁卫：正前方远处1枚蓝方（体现无限直线远程）
        5:  {"pos": (4, 2), "extras": [(0, 1, 4, 7)]},
        # 总督：斜前方1枚蓝方（体现斜向无限滑行吃子）
        6:  {"pos": (4, 2), "extras": [(0, 1, 7, 5)]},
        # 教主（翻越）：左上方2枚跳板，翻越落点自动显绿；正右1枚蓝方（体现1步吃子）
        7:  {"pos": (4, 2), "extras": [(0, 0, 3, 3), (0, 0, 2, 4), (0, 1, 5, 2)]},
        # 亲信：右侧1格蓝方（1步内吃子），上方1枚红方（体现滑行被阻）
        8:  {"pos": (4, 2), "extras": [(0, 1, 5, 2), (0, 0, 4, 3)]},
        # 御史：右上方+正前方各1枚蓝方（体现全向无限威胁）
        9:  {"pos": (4, 3), "extras": [(10, 1, 7, 6), (0, 1, 4, 7)]},
        # 领主：正前方飞将(4,7)+右前方1步(5,3)（体现直杀+近身）
        10: {"pos": (4, 2), "extras": [(10, 1, 4, 7), (0, 1, 5, 3)]},
    }

    def draw_rules(
        self,
        selected: PieceType,
        hover_idx: Optional[int],
        list_rects: list[tuple[PieceType, pygame.Rect]],
        rules_text: dict,
    ) -> None:
        """
        三栏布局：
          左栏 (0~168)     — 棋子列表
          中栏 (170~745)   — 演示棋盘（9×9，格子 64px）
          右栏 (765~1055)  — 文字规则说明
        """
        from engine import Board, Piece as _Piece, FORTRESS_CELLS as _FC

        self.screen.fill(C_BG)

        DEMO_CELL = 64
        DEMO_COLS = 9
        DEMO_ROWS = 9
        DEMO_OX   = 170
        DEMO_OY   = (WINDOW_H - DEMO_ROWS * DEMO_CELL) // 2   # 垂直居中

        RIGHT_X = DEMO_OX + DEMO_COLS * DEMO_CELL + 20   # 765
        RIGHT_W = WINDOW_W - RIGHT_X - 10                 # ≈281

        # 逻辑坐标 → 演示棋盘屏幕坐标（y 轴翻转：逻辑 y=0 在底部）
        def demo_to_screen(lx: int, ly: int) -> tuple[int, int]:
            return DEMO_OX + lx * DEMO_CELL, DEMO_OY + (8 - ly) * DEMO_CELL

        # ── 顶部标题
        title = self.font_lg.render("规 则 说 明", True, (230, 185, 60))
        self.screen.blit(title, title.get_rect(centerx=WINDOW_W // 2, top=12))
        pygame.draw.line(self.screen, C_PANEL_BORDER,
                         (10, 46), (WINDOW_W - 10, 46), 1)

        # ── 左栏：棋子列表
        left_bg = pygame.Rect(0, 50, 168, WINDOW_H - 50)
        pygame.draw.rect(self.screen, C_PANEL_BG, left_bg)
        pygame.draw.line(self.screen, C_PANEL_BORDER,
                         (168, 50), (168, WINDOW_H), 1)

        for i, (pt, rect) in enumerate(list_rects):
            info   = PIECE_INFO[int(pt)]
            is_sel = pt == selected
            is_hov = hover_idx == i
            if is_sel:
                pygame.draw.rect(self.screen, C_BTN_ACTIVE, rect, border_radius=4)
            elif is_hov:
                pygame.draw.rect(self.screen, C_BTN_HOVER, rect, border_radius=4)
            else:
                pygame.draw.rect(self.screen, C_BTN_NORMAL, rect, border_radius=4)
            c = (200, 255, 200) if is_sel else C_TEXT
            name_s = self.font_md.render(info["name"], True, c)
            self.screen.blit(name_s, name_s.get_rect(
                centerx=rect.centerx, centery=rect.centery))

        # ── 中栏：演示棋盘网格 ────────────────
        # 1. 绘制所有格子底色
        for row in range(DEMO_ROWS):   # row=0 是屏幕顶（逻辑 y=8），row=8 是屏幕底（逻辑 y=0）
            for col in range(DEMO_COLS):
                lx = col
                ly = 8 - row   # 逻辑 y
                rx = DEMO_OX + col * DEMO_CELL
                ry = DEMO_OY + row * DEMO_CELL
                is_fort = (lx, ly) in _FC
                if is_fort:
                    cell_c = HL_FORTRESS
                elif (row + col) % 2 == 0:
                    cell_c = C_BOARD_LIGHT
                else:
                    cell_c = C_BOARD_DARK
                pygame.draw.rect(self.screen, cell_c,
                                 (rx, ry, DEMO_CELL, DEMO_CELL))
                pygame.draw.rect(self.screen, C_GRID_LINE,
                                 (rx, ry, DEMO_CELL, DEMO_CELL), 1)

        # 2. 对方领地（y=5~8）叠加暗色，体现领主/亲信不可进入
        enemy_zone_surf = pygame.Surface((DEMO_COLS * DEMO_CELL, 4 * DEMO_CELL), pygame.SRCALPHA)
        enemy_zone_surf.fill((0, 0, 0, 90))
        # y=5~8 → 屏幕 row=0~3（顶部4行）
        self.screen.blit(enemy_zone_surf, (DEMO_OX, DEMO_OY))
        # 3. 中立行 y=4 → 屏幕 row=4，绘制淡紫半透明叠加
        nl_surf = pygame.Surface((DEMO_COLS * DEMO_CELL, DEMO_CELL), pygame.SRCALPHA)
        pygame.draw.rect(nl_surf, (*C_NEUTRAL_LINE, 60),
                         (0, 0, DEMO_COLS * DEMO_CELL, DEMO_CELL))
        self.screen.blit(nl_surf, (DEMO_OX, DEMO_OY + 4 * DEMO_CELL))

        # 4. 领地标签
        ally_label  = self.font_sm.render("己方领地", True, (100, 180, 100))
        enemy_label = self.font_sm.render("对方领地", True, (180, 100, 100))
        neutral_label = self.font_sm.render("中立", True, (150, 160, 220))
        self.screen.blit(ally_label,  (DEMO_OX + 2, DEMO_OY + 6 * DEMO_CELL + 2))  # y=0~3 底部区域
        self.screen.blit(enemy_label, (DEMO_OX + 2, DEMO_OY + 0 * DEMO_CELL + 2))  # y=5~8 顶部
        self.screen.blit(neutral_label, (DEMO_OX + 2, DEMO_OY + 4 * DEMO_CELL + 2))

        # 棋盘外框
        pygame.draw.rect(self.screen, C_BOARD_BORDER,
                         (DEMO_OX, DEMO_OY, DEMO_COLS * DEMO_CELL, DEMO_ROWS * DEMO_CELL), 2)

        # ── 构建演示棋盘 ──────────────────────
        cfg     = self._DEMO_CONFIGS.get(int(selected), {"pos": (4, 2), "extras": []})
        pc_lx, pc_ly = cfg["pos"]

        demo_board = Board()
        # 主棋子（红方）
        demo_piece = _Piece(0, selected, Side.RED, pc_lx, pc_ly)
        demo_board.grid[pc_ly][pc_lx] = demo_piece
        demo_board._piece_map[0] = demo_piece

        # 配对棋子
        extra_id = 1
        for (ept, esid, ex, ey) in cfg["extras"]:
            ep = _Piece(extra_id, PieceType(ept), Side(esid), ex, ey)
            demo_board.grid[ey][ex] = ep
            demo_board._piece_map[extra_id] = ep
            extra_id += 1

        # ── 计算合法移动/吃子
        moves, caps = demo_board.get_moves(demo_piece, {})

        # ── 绘制移动高亮（绿色圆点）
        move_hl = pygame.Surface((DEMO_CELL, DEMO_CELL), pygame.SRCALPHA)
        pygame.draw.circle(move_hl, (80, 220, 80, 160),
                           (DEMO_CELL // 2, DEMO_CELL // 2), 13)
        pygame.draw.circle(move_hl, (80, 220, 80, 80),
                           (DEMO_CELL // 2, DEMO_CELL // 2), 15, 2)
        for (tx, ty) in moves:
            rx, ry = demo_to_screen(tx, ty)
            self.screen.blit(move_hl, (rx, ry))

        # ── 绘制吃子高亮（红色边框）
        for (tx, ty) in caps:
            rx, ry = demo_to_screen(tx, ty)
            cap_hl = pygame.Surface((DEMO_CELL, DEMO_CELL), pygame.SRCALPHA)
            pygame.draw.rect(cap_hl, (240, 60, 60, 120), (0, 0, DEMO_CELL, DEMO_CELL))
            pygame.draw.rect(cap_hl, (240, 60, 60, 210), (0, 0, DEMO_CELL, DEMO_CELL), 3)
            self.screen.blit(cap_hl, (rx, ry))

        # ── 绘制所有演示棋子
        # 先绘制配对棋子（作为靶子/炮架）
        for ep in list(demo_board._piece_map.values()):
            if ep.id == 0:
                continue  # 主棋子最后画，保证在顶层
            ex_s, ey_s = demo_to_screen(ep.x, ep.y)
            self._draw_piece_demo(ep, ex_s, ey_s, DEMO_CELL)

        # 主棋子（红方，最顶层）
        sx, sy = demo_to_screen(pc_lx, pc_ly)
        self._draw_piece_demo(demo_piece, sx, sy, DEMO_CELL)

        # ── 图例（棋盘下方）
        legend_y = DEMO_OY + DEMO_ROWS * DEMO_CELL + 6
        dot = pygame.Surface((12, 12), pygame.SRCALPHA)
        pygame.draw.circle(dot, (80, 220, 80, 200), (6, 6), 6)
        self.screen.blit(dot, (DEMO_OX, legend_y + 4))
        self.screen.blit(self.font_sm.render("可移动", True, C_TEXT_DIM), (DEMO_OX + 16, legend_y))
        box = pygame.Surface((12, 12), pygame.SRCALPHA)
        pygame.draw.rect(box, (240, 60, 60, 200), (0, 0, 12, 12))
        self.screen.blit(box, (DEMO_OX + 80, legend_y + 4))
        self.screen.blit(self.font_sm.render("可攻击", True, C_TEXT_DIM), (DEMO_OX + 96, legend_y))
        self.screen.blit(self.font_sm.render("↑ 前方（红方）", True, (80, 200, 80)),
                         (DEMO_OX + 160, legend_y))

        # ── 右栏：文字规则说明
        right_bg = pygame.Rect(RIGHT_X - 8, 50, RIGHT_W + 8, WINDOW_H - 50)
        pygame.draw.rect(self.screen, C_PANEL_BG, right_bg)
        pygame.draw.line(self.screen, C_PANEL_BORDER,
                         (RIGHT_X - 8, 50), (RIGHT_X - 8, WINDOW_H), 1)

        info     = PIECE_INFO[int(selected)]
        cx_r     = RIGHT_X + RIGHT_W // 2
        name_big = self.font_lg.render(info["name"], True, (230, 185, 60))
        self.screen.blit(name_big, name_big.get_rect(centerx=cx_r, top=60))

        cursor_y = 60 + name_big.get_height() + 10
        pygame.draw.line(self.screen, C_PANEL_BORDER,
                         (RIGHT_X, cursor_y), (WINDOW_W - 10, cursor_y), 1)
        cursor_y += 10

        _, lines = rules_text.get(selected, ("", []))
        for line in lines:
            if not line:
                cursor_y += 6
                continue
            if line.startswith("【"):
                s = self.font_md.render(line, True, (160, 190, 255))
            else:
                s = self.font_sm.render(line, True, C_TEXT)
            self.screen.blit(s, (RIGHT_X + 8, cursor_y))
            cursor_y += s.get_height() + 4

        # 返回按钮
        back_rect = pygame.Rect(WINDOW_W - 170, WINDOW_H - 54, 150, 38)
        self.draw_button("返  回", back_rect)

    def _draw_piece_demo(
        self, piece: "Piece", sx: int, sy: int, cell: int,
    ) -> None:
        """在演示棋盘格子内绘制棋子"""
        info   = PIECE_INFO[int(piece.type)]
        char   = info["char"]
        is_red = piece.side == Side.RED
        c_main = C_RED_PIECE  if is_red else C_BLUE_PIECE
        c_hi   = C_RED_HI     if is_red else C_BLUE_HI
        c_sh   = C_RED_SH     if is_red else C_BLUE_SH
        c_bd   = C_RED_BORDER if is_red else C_BLUE_BORDER

        pad  = max(4, cell // 10)
        rect = pygame.Rect(sx + pad, sy + pad, cell - pad * 2, cell - pad * 2)

        sh_r = rect.move(2, 2)
        pygame.draw.ellipse(self.screen, c_sh, sh_r)
        pygame.draw.ellipse(self.screen, c_main, rect)
        hi_r = pygame.Rect(rect.x + rect.w // 5, rect.y + rect.h // 6,
                           rect.w * 2 // 5, rect.h // 4)
        pygame.draw.ellipse(self.screen, c_hi, hi_r)
        pygame.draw.ellipse(self.screen, c_bd, rect, 2)

        font = self.font_piece if cell >= 56 else self.font_sm
        sh_s = font.render(char, True, c_sh)
        self.screen.blit(sh_s, sh_s.get_rect(centerx=rect.centerx + 1,
                                              centery=rect.centery + 1))
        txt_s = font.render(char, True, C_PIECE_TEXT)
        self.screen.blit(txt_s, txt_s.get_rect(center=rect.center))

        # 等级圆环（演示棋盘格子尺寸可变，半径按 rect 计算）
        demo_r = rect.w // 2
        self._draw_tier_rings(rect.centerx, rect.centery, demo_r, int(piece.type))


    def draw_replay_overlay(
        self,
        current_step: int, total_steps: int,
        buttons: list[tuple[str, pygame.Rect]],
        hover_btn: Optional[int],
    ) -> None:
        """在游戏画面底部绘制重播控制条"""
        bar_h = 50
        bar_y = WINDOW_H - bar_h
        bar_rect = pygame.Rect(0, bar_y, WINDOW_W, bar_h)
        pygame.draw.rect(self.screen, C_PANEL_BG, bar_rect)
        pygame.draw.rect(self.screen, C_PANEL_BORDER, bar_rect, 1)

        step_surf = self.font_md.render(
            f"步数: {current_step} / {total_steps}", True, C_TEXT)
        self.screen.blit(step_surf, (20, bar_y + 14))

        for i, (label, rect) in enumerate(buttons):
            self.draw_button(label, rect, hover=(hover_btn == i))
