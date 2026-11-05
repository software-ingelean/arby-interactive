import pygame
import time
from app.hardware.trill_lib import TrillLib

# ============================================================
# TRILL CONFIG
# ============================================================

trill = TrillLib(1, "bar", 0x20)
trill.setMode("CENTROID")
trill.setPrescaler(4)
trill.setNoiseThreshold(0.02)
trill.updateBaseLine()

# ============================================================
# PYGAME CONFIG
# ============================================================

pygame.init()
screen = pygame.display.set_mode((800, 600), pygame.FULLSCREEN)
clock = pygame.time.Clock()

font = pygame.font.SysFont("Arial", 100)
font_small = pygame.font.SysFont("Arial", 50)

# ============================================================
# GAME STATE
# ============================================================

board = [""] * 9
turn = "X"
game_over = False
winner = None
win_line = None

# posiciones
grid = {
    0: (133, 100), 1: (400, 100), 2: (666, 100),
    3: (133, 300), 4: (400, 300), 5: (666, 300),
    6: (133, 500), 7: (400, 500), 8: (666, 500),
}

# ============================================================
# ANTI-RUIDO
# ============================================================

last_touch_time = 0
cooldown = 0.6

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

    last_touch_time = now

    pos = trill.touchLocation(0)
    col = int(pos * 3)
    col = min(col, 2)

    return col

# ============================================================
# LOGICA JUEGO
# ============================================================

def registrar_jugada(col):
    global turn

    for row in range(3):
        idx = row * 3 + col
        if board[idx] == "":
            board[idx] = turn
            turn = "O" if turn == "X" else "X"
            return

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
# DIBUJO
# ============================================================

def draw():
    screen.fill((0, 0, 0))

    # grid
    pygame.draw.line(screen, (255,255,255), (266, 0), (266, 600), 4)
    pygame.draw.line(screen, (255,255,255), (533, 0), (533, 600), 4)
    pygame.draw.line(screen, (255,255,255), (0, 200), (800, 200), 4)
    pygame.draw.line(screen, (255,255,255), (0, 400), (800, 400), 4)

    # dibujar fichas
    for i, val in enumerate(board):
        if val != "":
            x, y = grid[i]

            if val == "X":
                color = (0, 255, 0)   # verde
            else:
                color = (0, 150, 255) # azul

            text = font.render(val, True, color)
            rect = text.get_rect(center=(x, y))
            screen.blit(text, rect)

    # línea ganadora
    if win_line:
        a, b, c = win_line
        x1, y1 = grid[a]
        x2, y2 = grid[c]
        pygame.draw.line(screen, (255, 0, 0), (x1, y1), (x2, y2), 10)

    # mensaje final
    if game_over:
        if winner:
            msg = f"Gana {winner}"
        else:
            msg = "Empate"

        text = font_small.render(msg, True, (255,255,0))
        rect = text.get_rect(center=(400, 50))
        screen.blit(text, rect)

    pygame.display.flip()

# ============================================================
# MAIN LOOP
# ============================================================

running = True

while running:
    for event in pygame.event.get():
        if event.type == pygame.QUIT:
            running = False

    if not game_over:
        col = detectar_toque()

        if col is not None:
            registrar_jugada(col)
            check_winner()

    draw()
    clock.tick(30)

pygame.quit()
