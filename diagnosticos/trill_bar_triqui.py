import pygame
import time
from app.hardware.trill_lib import TrillLib

# ============================================================
# CONFIGURACIÓN TRILL BAR
# ============================================================

trill = TrillLib(1, "bar", 0x20)
trill.setMode("CENTROID")
trill.setPrescaler(4)
trill.setNoiseThreshold(0.02)
trill.updateBaseLine()

# ============================================================
# CONFIGURACIÓN JUEGO
# ============================================================

pygame.init()
screen = pygame.display.set_mode((800, 600), pygame.FULLSCREEN)
clock = pygame.time.Clock()

board = [""] * 9
turn = "X"

font = pygame.font.SysFont("Arial", 100)

# posiciones en pantalla
grid = {
    0: (133, 100),
    1: (400, 100),
    2: (666, 100),
    3: (133, 300),
    4: (400, 300),
    5: (666, 300),
    6: (133, 500),
    7: (400, 500),
    8: (666, 500),
}

# ============================================================
# CONTROL DE TOQUES (ANTI-RUIDO)
# ============================================================

last_touch_time = 0
cooldown = 0.6  # segundos entre jugadas

def detectar_toque():
    global last_touch_time

    trill.readTrill()
    n = trill.getNumTouches()

    if n == 0:
        return None

    size = trill.touchSize(0)

    # filtro de ruido
    if size < 0.02:
        return None

    now = time.time()

    # anti rebote (clave para balón)
    if now - last_touch_time < cooldown:
        return None

    last_touch_time = now

    pos = trill.touchLocation(0)

    # convertir a columna
    col = int(pos * 3)
    col = min(col, 2)

    return col


# ============================================================
# LÓGICA DE JUEGO
# ============================================================

current_cell = 0

def registrar_jugada(col):
    global turn, current_cell

    # buscar siguiente celda libre en esa columna
    for row in range(3):
        idx = row * 3 + col
        if board[idx] == "":
            board[idx] = turn
            turn = "O" if turn == "X" else "X"
            return


# ============================================================
# DIBUJO
# ============================================================

def draw():
    screen.fill((0, 0, 0))

    # líneas del tablero
    pygame.draw.line(screen, (255,255,255), (266, 0), (266, 600), 4)
    pygame.draw.line(screen, (255,255,255), (533, 0), (533, 600), 4)
    pygame.draw.line(screen, (255,255,255), (0, 200), (800, 200), 4)
    pygame.draw.line(screen, (255,255,255), (0, 400), (800, 400), 4)

    # dibujar X y O
    for i, val in enumerate(board):
        if val != "":
            x, y = grid[i]
            text = font.render(val, True, (0,255,0))
            rect = text.get_rect(center=(x, y))
            screen.blit(text, rect)

    pygame.display.flip()


# ============================================================
# LOOP PRINCIPAL
# ============================================================

running = True

while running:
    for event in pygame.event.get():
        if event.type == pygame.QUIT:
            running = False

    col = detectar_toque()

    if col is not None:
        registrar_jugada(col)

    draw()
    clock.tick(30)

pygame.quit()
