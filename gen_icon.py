from PIL import Image, ImageDraw

SZ = 64  # grid size
SCALE = 5  # pixel size
W = H = SZ * SCALE

# Colors
BG = (10, 15, 20)
DARK_SQ = (35, 55, 50)
LIGHT_SQ = (20, 40, 35)
ENEMY = (40, 40, 60)
ENEMY_ACCENT = (60, 60, 100)
BLUE = (50, 100, 220)
BLUE_LIGHT = (80, 140, 255)
RED = (200, 50, 50)
RED_LIGHT = (230, 90, 90)
WHITE = (240, 240, 255)

img = Image.new("RGB", (W, H), BG)
d = ImageDraw.Draw(img)

def px(x, y, color):
    if 0 <= x < SZ and 0 <= y < SZ:
        d.rectangle([x*SCALE, y*SCALE, (x+1)*SCALE-1, (y+1)*SCALE-1], fill=color)

# Draw checkerboard (8x8, each cell 8x8 pixels)
for r in range(8):
    for c in range(8):
        color = DARK_SQ if (r + c) % 2 == 0 else LIGHT_SQ
        base_x = 4 + c * 8
        base_y = 4 + r * 8
        for y in range(8):
            for x in range(8):
                px(base_x + x, base_y + y, color)

# Enemy pieces (8 surrounding pieces, dark bluish-purple)
enemies = [
    (2, 2), (2, 5), (5, 2), (5, 5),
    (1, 3), (1, 4), (3, 1), (4, 1)
]

def draw_piece(x, y, body_color, accent_color=None, half_left=None, half_right=None, qmark=False):
    # base (pedestal)
    for bx in range(x-3, x+4):
        px(bx, y+5, (20,20,30))
    # body circle (radius 5)
    for dy in range(-5, 6):
        for dx in range(-5, 6):
            if dx*dx + dy*dy <= 25:
                col = body_color
                px(x+dx, y+dy, col)
    # accent top (lighter band)
    for dx in range(-4, 4):
        if dx*dx + 2*2 <= 20:
            px(x+dx, y-3, accent_color or (100,100,140))
    # half split
    if half_left and half_right:
        for dy in range(-4, 5):
            px(x-1, y+dy, half_left)
            px(x, y+dy, half_left)
    # question mark
    if qmark:
        for (qx, qy) in [(0,-6),(1,-6),(2,-6),(2,-5),(2,-4),(1,-4),(0,-3),(1,-2),(2,-1),(1,0)]:
            px(x+qx, y+qy, WHITE)
            px(x+qx+1, y+qy, WHITE)
    return

for (r, c) in enemies:
    cx = 4 + c * 8 + 4
    cy = 4 + r * 8 + 4
    draw_piece(cx, cy, ENEMY, ENEMY_ACCENT)

# Center piece (the spy) - slightly larger, more detailed
cx = 4 + 4 * 8 + 4  # col 4 = center
cy = 4 + 4 * 8 + 4  # row 4 = center

# base
for bx in range(cx-4, cx+5):
    px(bx, cy+6, (20,20,30))
# body radius 6
for dy in range(-6, 7):
    for dx in range(-6, 7):
        if dx*dx + dy*dy <= 36:
            col = BLUE if dx <= 0 else RED
            px(cx+dx, cy+dy, col)
# highlight top-left (blue side)
for (hx, hy) in [(-3,-4),(-4,-3),(-3,-3),(-2,-4)]:
    px(cx+hx, cy+hy, BLUE_LIGHT)
# highlight top-right (red side)
for (hx, hy) in [(3,-4),(4,-3),(3,-3),(2,-4)]:
    px(cx+hx, cy+hy, RED_LIGHT)
# white rim on dividing line
for dy in range(-5, 6):
    px(cx-1, cy+dy, WHITE)
    px(cx, cy+dy, WHITE)
# small question mark in center
for (qx, qy) in [(0,-8),(1,-8),(2,-8),(2,-7),(2,-6),(1,-6),(0,-5),(1,-4),(2,-3),(1,-2)]:
    px(cx+qx, cy+qy, WHITE)
    px(cx+qx+1, cy+qy, WHITE)

# Border
for i in range(W):
    d.rectangle([i, 0, i, 0], fill=(0,0,0))
    d.rectangle([i, H-1, i, H-1], fill=(0,0,0))
for i in range(H):
    d.rectangle([0, i, 0, i], fill=(0,0,0))
    d.rectangle([W-1, i, W-1, i], fill=(0,0,0))

img.save("E:\\Mine\\Game\\SpyChess\\spy_chess_icon.png")
print(f"Saved! Size: {W}x{H} pixels")