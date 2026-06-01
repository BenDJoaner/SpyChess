"""
game.py — 间谍象棋主入口
运行：python game.py
"""

import sys
import pygame
from renderer import WINDOW_W, WINDOW_H
from ui import UIController


def main() -> None:
    pygame.init()
    pygame.display.set_caption("间谍象棋 — Spy Chess")
    screen = pygame.display.set_mode((WINDOW_W, WINDOW_H))
    clock  = pygame.time.Clock()

    # AI 配置由主菜单模式选择界面决定
    ui = UIController(screen)

    running = True
    while running:
        dt = clock.tick(60) / 1000.0   # 帧时间（秒）

        for event in pygame.event.get():
            if not ui.handle_event(event):
                running = False
                break

        ui.draw(dt)
        pygame.display.flip()

    pygame.quit()
    sys.exit(0)


if __name__ == "__main__":
    main()
