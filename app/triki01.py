import pygame
import time
import math
from collections import deque
from app.hardware.trill_lib import TrillLib

# ============================================================
# TRILL CONFIG
# ============================================================

trill = TrillLib(1, "bar", 0x20)
trill.setMode("CENTROID")
trill.setPrescaler(4)
trill.setNoiseThreshold(0.004)
trill.updateBaseLine()

# ============================================================
# PYGAME CONFIG
# ============================================================

pygame.init()
pygame.mixer.init(frequency=44100, size=-16, channels=2, buffer=512)

info = pygame.display.Info()
WIDTH, HEIGHT = info.current_w, info.current_h
screen = pygame.display.set_mode((WIDTH, HEIGHT), pygame.FULLSCREEN)
clock = pygame.time.Clock()

FONT_BIG = pygame.font.SysFont("Arial", int(WIDTH * 0.08))
FONT_MED = pygame.font.SysFont("Arial", int(WIDTH * 0.05))
FONT_SMALL = pygame.font.SysFont("Arial", int(WIDTH * 0.03))

# ============================================================
# AUDIO
# ============================================================

def load_sound(path, volume=0.7):
    try:
        s = pygame.mixer.Sound(path)
        s.set_volume(volume)
        return s
    except Exception as e:
        print(f"[WARN] No se pudo cargar {path}: {e}")
        return None

S_HIT   = load_sound("sounds/hit.wav", 0.6)
S_PLACE = load_sound("sounds/place.wav", 0.8)
S_WIN   = load_sound("sounds/win.wav", 0.9)
S_DRAW  = load_sound("sounds/draw.wav", 0.9)

# ============================================================
# GAME STATE
# ============================================================

board = [""] * 9
turn = "X"
game_over = False
winner = None
win_line = None
state = "MENU"  # MENU / PLAY / END

# animaciones por celda (escala 0..1)
cell_anim = [0.0] * 9
cell_anim_speed = 8.0

# línea ganadora anim
win_anim_t = 0.0  # 0..1

# pulso menú
menu_pulse_t = 0.0

# ============================================================
# GRID
# ============================================================

def get_grid():
    cw = WIDTH // 3
    ch = HEIGHT // 3
    centers = {}
    rects = {}
    for i in range(9):
        r = i // 3
        c = i % 3
        x = c * cw + cw // 2
        y = r * ch + ch // 2
        centers[i] = (x, y)
        rects[i] = pygame.Rect(c*cw, r*ch, cw, ch)
    return centers, rects

# ============================================================
# INPUT TRILL (filtro + cooldown)
# ============================================================

last_touch_time = 0
cooldown = 0.6
pos_buffer = deque(maxlen=4)

def detectar_toque():
    global last_touch_time

    trill.readTrill()
    n = trill.getNumTouches()
    if n == 0:
        return None

    size = trill.touchSize(0)
    if size < 0.02:
        return None

    now = time.time()
    if now - last_touch_time < cooldown:
        return None

    pos = trill.touchLocation(0)
    pos_buffer.append(pos)
    pos_f = sum(pos_buffer) / len(pos_buffer)

    col = int(max(0, min(0.999, pos_f)) * 3)
    col = min(col, 2)

    last_touch_time = now
    if S_HIT: S_HIT.play()
    return col

# ============================================================
# GAME LOGIC
# ============================================================

def reset_game():
    global board, turn, game_over, winner, win_line, cell_anim, win_anim_t
    board = [""] * 9
    turn = "X"
    game_over = False
    winner = None
    win_line = None
    cell_anim = [0.0] * 9
    win_anim_t = 0.0

def registrar_jugada(col):
    global turn
    for row in range(3):
        idx = row * 3 + col
        if board[idx] == "":
            board[idx] = turn
            cell_anim[idx] = 0.01  # dispara animación
            if S_PLACE: S_PLACE.play()
            turn = "O" if turn == "X" else "X"
            return idx
    return None

def check_winner():
    global winner, game_over, win_line
    lines = [
        (0,1,2),(3,4,5),(6,7,8),
        (0,3,6),(1,4,7),(2,5,8),
        (0,4,8),(2,4,6)
    ]
    for a,b,c in lines:
        if board[a] != "" and board[a] == board[b] == board[c]:
            winner = board[a]
            game_over = True
            win_line = (a,b,c)
            return
    if "" not in board:
        game_over = True

# ============================================================
# DRAW HELPERS
# ============================================================

def draw_glow_circle(surface, pos, radius, color, layers=4):
    for i in range(layers, 0, -1):
        alpha = int(30 * (i / layers))
        r = int(radius * (1 + i*0.15))
        glow = pygame.Surface((r*2, r*2), pygame.SRCALPHA)
        pygame.draw.circle(glow, (*color, alpha), (r, r), r)
        surface.blit(glow, (pos[0]-r, pos[1]-r))

def draw_grid_lines():
    cw = WIDTH // 3
    ch = HEIGHT // 3
    for i in range(1,3):
        pygame.draw.line(screen, (255,255,255), (i*cw, 0), (i*cw, HEIGHT), 6)
        pygame.draw.line(screen, (255,255,255), (0, i*ch), (WIDTH, i*ch), 6)

def draw_symbol(i, val, center, dt):
    # animación de escala tipo "pop"
    if cell_anim[i] > 0 and cell_anim[i] < 1.0:
        cell_anim[i] = min(1.0, cell_anim[i] + cell_anim_speed * dt)

    scale = 1.0 + 0.4 * math.sin(cell_anim[i] * math.pi)  # overshoot suave
    base_size = int(WIDTH * 0.08)
    size = int(base_size * scale)

    color = (0,255,0) if val == "X" else (0,150,255)

    text = pygame.font.SysFont("Arial", size).render(val, True, color)
    rect = text.get_rect(center=center)

    # glow
    draw_glow_circle(screen, center, int(size*0.6), color, layers=3)

    screen.blit(text, rect)

def draw_win_line(centers, dt):
    global win_anim_t
    if not win_line: return
    a,b,c = win_line
    x1,y1 = centers[a]
    x2,y2 = centers[c]

    win_anim_t = min(1.0, win_anim_t + 1.5 * dt)
    xe = x1 + (x2 - x1) * win_anim_t
    ye = y1 + (y2 - y1) * win_anim_t

    pygame.draw.line(screen, (255,0,0), (x1,y1), (xe,ye), 14)

# ============================================================
# SCREENS
# ============================================================

def draw_menu(dt):
    global menu_pulse_t
    screen.fill((0,0,0))

    menu_pulse_t += dt * 2.0
    pulse = 0.5 + 0.5 * math.sin(menu_pulse_t)

    title = FONT_BIG.render("TRIQUI INTERACTIVO", True, (0,255,200))
    screen.blit(title, title.get_rect(center=(WIDTH//2, HEIGHT//3)))

    # botón “tap to start” con pulso
    alpha = int(120 + 120 * pulse)
    msg = FONT_MED.render("Toque la barra para iniciar", True, (255,255,255))
    surf = pygame.Surface(msg.get_size(), pygame.SRCALPHA)
    surf.fill((255,255,255,0))
    surf.blit(msg, (0,0))
    surf.set_alpha(alpha)
    screen.blit(surf, surf.get_rect(center=(WIDTH//2, HEIGHT//2)))

def draw_game(dt):
    screen.fill((0,0,0))
    draw_grid_lines()
    centers, _ = get_grid()

    for i, val in enumerate(board):
        if val != "":
            draw_symbol(i, val, centers[i], dt)

    draw_win_line(centers, dt)

def draw_end(dt):
    draw_game(dt)

    if winner:
        msg = f"Gana {winner}"
    else:
        msg = "Empate"

    t1 = FONT_MED.render(msg, True, (255,255,0))
    screen.blit(t1, t1.get_rect(center=(WIDTH//2, HEIGHT//8)))

    t2 = FONT_SMALL.render("Toque para reiniciar", True, (255,255,255))
    screen.blit(t2, t2.get_rect(center=(WIDTH//2, HEIGHT//8 + 60)))

# ============================================================
# MAIN LOOP
# ============================================================

running = True
prev_time = time.time()

while running:
    now = time.time()
    dt = now - prev_time
    prev_time = now

    for event in pygame.event.get():
        if event.type == pygame.QUIT:
            running = False

    touch = detectar_toque()

    if state == "MENU":
        if touch is not None:
            reset_game()
            state = "PLAY"

    elif state == "PLAY":
        if not game_over and touch is not None:
            idx = registrar_jugada(touch)
            if idx is not None:
                check_winner()
                if game_over:
                    if winner and S_WIN: S_WIN.play()
                    if (not winner) and S_DRAW: S_DRAW.play()

        if game_over:
            state = "END"

    elif state == "END":
        if touch is not None:
            reset_game()
            state = "MENU"

    # draw
    if state == "MENU":
        draw_menu(dt)
    elif state == "PLAY":
        draw_game(dt)
    elif state == "END":
        draw_end(dt)

    pygame.display.flip()
    clock.tick(60)

pygame.quit()
