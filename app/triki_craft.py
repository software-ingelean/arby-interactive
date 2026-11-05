import pygame
import time
import math
from app.hardware.trill_lib import TrillLib

# ============================================================
# TRILL CRAFT CONFIG
# ============================================================

# Usa la dirección I2C que ya te funcionó.
# Normalmente Craft usa 0x30, pero si en tu prueba fue otra, cámbiala aquí.
TRILL_BUS = 1
TRILL_TYPE = "craft"
TRILL_ADDR = 0x30

trill = TrillLib(TRILL_BUS, TRILL_TYPE, TRILL_ADDR)

# Para Trill Craft se recomienda DIFF porque queremos leer
# cambios capacitivos por canal.
trill.setMode("DIFF")

# Ajustes para reducir ruido.
# Si el sensor queda poco sensible, baja prescaler a 4.
# Si sigue con ruido, puedes subirlo a 8.
trill.setPrescaler(2)
trill.setNoiseThreshold(0.01)

print("No tocar los pads. Calibrando Trill Craft...")
time.sleep(1.0)
trill.updateBaseLine()
time.sleep(1.0)
print("Trill Craft listo.")

# ============================================================
# PYGAME CONFIG
# ============================================================

pygame.init()
pygame.mixer.init(frequency=44100, size=-16, channels=2, buffer=512)

info = pygame.display.Info()
WIDTH, HEIGHT = info.current_w, info.current_h

# Pantalla completa
screen = pygame.display.set_mode((WIDTH, HEIGHT), pygame.FULLSCREEN)

# Si quieres probar en ventana, comenta la línea anterior y usa esta:
# WIDTH, HEIGHT = 900, 700
# screen = pygame.display.set_mode((WIDTH, HEIGHT))

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


S_HIT = load_sound("sounds/hit.wav", 0.6)
S_PLACE = load_sound("sounds/place.wav", 0.8)
S_WIN = load_sound("sounds/win.wav", 0.9)
S_DRAW = load_sound("sounds/draw.wav", 0.9)

# ============================================================
# GAME STATE
# ============================================================

board = [""] * 9
turn = "X"
game_over = False
winner = None
win_line = None

state = "MENU"  # MENU / PLAY / END

# Animaciones por celda
cell_anim = [0.0] * 9
cell_anim_speed = 8.0

# Línea ganadora animada
win_anim_t = 0.0

# Pulso menú
menu_pulse_t = 0.0

# Última casilla tocada para resaltar visualmente
last_selected_cell = None
last_selected_time = 0.0

# ============================================================
# TRILL CRAFT INPUT ROBUSTO
# ============================================================

# Mapeo canal físico del Craft -> casilla del tablero.
#
# Tablero:
# 0 | 1 | 2
# 3 | 4 | 5
# 6 | 7 | 8
#
# Si tus pads están conectados en otro orden, cambia este mapa.
CRAFT_CELL_MAP = {
    0: 0,
    1: 1,
    2: 2,

    3: 3,
    4: 4,
    5: 5,

    6: 6,
    7: 7,
    8: 8,
}

# Umbral principal de toque.
# Si hay falsos toques, sube a 0.08 o 0.10.
# Si no detecta bien, baja a 0.04.
TOUCH_THRESHOLD = 0.06

# Umbral para considerar que el usuario ya soltó.
# Debe ser menor que TOUCH_THRESHOLD.
RELEASE_THRESHOLD = 0.025

# Lecturas consecutivas necesarias para validar el toque.
# Más alto = más estable, pero un poco más lento.
CONFIRM_SAMPLES = 4

# Tiempo mínimo entre jugadas válidas.
cooldown = 0.35

last_touch_time = 0.0
touch_active = False

candidate_cell = None
candidate_count = 0

DEBUG_CRAFT = True


def get_channel_value(ch):
    """
    Lee el valor de un canal del Trill Craft intentando varios nombres
    de función/atributo, porque algunas versiones de trill_lib cambian.
    """
    try:
        return float(trill.getRawData(ch))
    except Exception:
        pass

    try:
        return float(trill.rawData[ch])
    except Exception:
        pass

    try:
        return float(trill.rawData(ch))
    except Exception:
        pass

    return 0.0


def detectar_toque():
    """
    Devuelve la casilla tocada 0..8 o None.

    Filtros usados:
    - umbral alto de toque
    - confirmación por varias muestras consecutivas
    - bloqueo hasta que el usuario suelte el pad
    - cooldown entre jugadas
    """
    global last_touch_time
    global touch_active
    global candidate_cell
    global candidate_count
    global last_selected_cell
    global last_selected_time

    trill.readTrill()

    best_cell = None
    best_channel = None
    best_value = 0.0

    # Buscar el canal más fuerte entre los canales usados
    for channel, cell_idx in CRAFT_CELL_MAP.items():
        value = get_channel_value(channel)

        if value > best_value:
            best_value = value
            best_channel = channel
            best_cell = cell_idx

    # Si bajó bastante, consideramos que el usuario soltó el pad
    if best_value < RELEASE_THRESHOLD:
        touch_active = False
        candidate_cell = None
        candidate_count = 0
        return None

    # Si ya se detectó un toque y el dedo sigue encima, no repetir jugada
    if touch_active:
        return None

    # Si no supera el umbral, ignorar
    if best_value < TOUCH_THRESHOLD:
        candidate_cell = None
        candidate_count = 0
        return None

    # Confirmar que la misma casilla se mantiene durante varias lecturas
    if candidate_cell == best_cell:
        candidate_count += 1
    else:
        candidate_cell = best_cell
        candidate_count = 1

    if candidate_count < CONFIRM_SAMPLES:
        return None

    now = time.time()

    if now - last_touch_time < cooldown:
        return None

    last_touch_time = now
    touch_active = True
    candidate_cell = None
    candidate_count = 0

    last_selected_cell = best_cell
    last_selected_time = now

    if DEBUG_CRAFT:
        print(
            f"[CRAFT] Toque válido | canal={best_channel} "
            f"casilla={best_cell} valor={best_value:.4f}"
        )

    if S_HIT:
        S_HIT.play()

    return best_cell

# ============================================================
# GRID
# ============================================================

def get_grid():
    cw = WIDTH // 3
    ch = HEIGHT // 3

    centers = {}
    rects = {}

    for i in range(9):
        row = i // 3
        col = i % 3

        x = col * cw + cw // 2
        y = row * ch + ch // 2

        centers[i] = (x, y)
        rects[i] = pygame.Rect(col * cw, row * ch, cw, ch)

    return centers, rects

# ============================================================
# GAME LOGIC
# ============================================================

def reset_game():
    global board
    global turn
    global game_over
    global winner
    global win_line
    global cell_anim
    global win_anim_t

    board = [""] * 9
    turn = "X"
    game_over = False
    winner = None
    win_line = None
    cell_anim = [0.0] * 9
    win_anim_t = 0.0


def registrar_jugada(idx):
    global turn

    if idx is None:
        return None

    if idx < 0 or idx >= 9:
        return None

    if board[idx] != "":
        return None

    board[idx] = turn
    cell_anim[idx] = 0.01

    if S_PLACE:
        S_PLACE.play()

    turn = "O" if turn == "X" else "X"

    return idx


def check_winner():
    global winner
    global game_over
    global win_line

    lines = [
        (0, 1, 2),
        (3, 4, 5),
        (6, 7, 8),

        (0, 3, 6),
        (1, 4, 7),
        (2, 5, 8),

        (0, 4, 8),
        (2, 4, 6),
    ]

    for a, b, c in lines:
        if board[a] != "" and board[a] == board[b] == board[c]:
            winner = board[a]
            game_over = True
            win_line = (a, b, c)
            return

    if "" not in board:
        game_over = True


def start_new_game_with_first_move(cell_idx):
    global state

    reset_game()
    state = "PLAY"

    idx = registrar_jugada(cell_idx)

    if idx is not None:
        check_winner()

# ============================================================
# DRAW HELPERS
# ============================================================

def draw_glow_circle(surface, pos, radius, color, layers=4):
    for i in range(layers, 0, -1):
        alpha = int(30 * (i / layers))
        r = int(radius * (1 + i * 0.15))

        glow = pygame.Surface((r * 2, r * 2), pygame.SRCALPHA)
        pygame.draw.circle(glow, (*color, alpha), (r, r), r)

        surface.blit(glow, (pos[0] - r, pos[1] - r))


def draw_grid_lines():
    cw = WIDTH // 3
    ch = HEIGHT // 3

    for i in range(1, 3):
        pygame.draw.line(
            screen,
            (255, 255, 255),
            (i * cw, 0),
            (i * cw, HEIGHT),
            6
        )

        pygame.draw.line(
            screen,
            (255, 255, 255),
            (0, i * ch),
            (WIDTH, i * ch),
            6
        )


def draw_selected_cell_highlight():
    if last_selected_cell is None:
        return

    elapsed = time.time() - last_selected_time

    if elapsed > 0.25:
        return

    _, rects = get_grid()
    rect = rects[last_selected_cell]

    alpha = int(120 * (1.0 - elapsed / 0.25))

    surf = pygame.Surface((rect.width, rect.height), pygame.SRCALPHA)
    surf.fill((255, 255, 255, alpha))

    screen.blit(surf, rect.topleft)


def draw_symbol(i, val, center, dt):
    if 0 < cell_anim[i] < 1.0:
        cell_anim[i] = min(1.0, cell_anim[i] + cell_anim_speed * dt)

    scale = 1.0 + 0.4 * math.sin(cell_anim[i] * math.pi)

    base_size = int(WIDTH * 0.08)
    size = int(base_size * scale)

    color = (0, 255, 0) if val == "X" else (0, 150, 255)

    font = pygame.font.SysFont("Arial", size)
    text = font.render(val, True, color)
    rect = text.get_rect(center=center)

    draw_glow_circle(screen, center, int(size * 0.6), color, layers=3)
    screen.blit(text, rect)


def draw_win_line(centers, dt):
    global win_anim_t

    if not win_line:
        return

    a, b, c = win_line

    x1, y1 = centers[a]
    x2, y2 = centers[c]

    win_anim_t = min(1.0, win_anim_t + 1.5 * dt)

    xe = x1 + (x2 - x1) * win_anim_t
    ye = y1 + (y2 - y1) * win_anim_t

    pygame.draw.line(
        screen,
        (255, 0, 0),
        (x1, y1),
        (xe, ye),
        14
    )

# ============================================================
# SCREENS
# ============================================================

def draw_menu(dt):
    global menu_pulse_t

    screen.fill((0, 0, 0))

    menu_pulse_t += dt * 2.0
    pulse = 0.5 + 0.5 * math.sin(menu_pulse_t)

    title = FONT_BIG.render("TRIQUI INTERACTIVO", True, (0, 255, 200))
    screen.blit(
        title,
        title.get_rect(center=(WIDTH // 2, HEIGHT // 3))
    )

    alpha = int(120 + 120 * pulse)

    msg = FONT_MED.render(
        "Toque una casilla para iniciar",
        True,
        (255, 255, 255)
    )

    surf = pygame.Surface(msg.get_size(), pygame.SRCALPHA)
    surf.fill((255, 255, 255, 0))
    surf.blit(msg, (0, 0))
    surf.set_alpha(alpha)

    screen.blit(
        surf,
        surf.get_rect(center=(WIDTH // 2, HEIGHT // 2))
    )

    info = FONT_SMALL.render(
        "Presione ESC para salir",
        True,
        (150, 150, 150)
    )

    screen.blit(
        info,
        info.get_rect(center=(WIDTH // 2, int(HEIGHT * 0.68)))
    )


def draw_game(dt):
    screen.fill((0, 0, 0))

    draw_selected_cell_highlight()
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

    t1 = FONT_MED.render(msg, True, (255, 255, 0))

    screen.blit(
        t1,
        t1.get_rect(center=(WIDTH // 2, HEIGHT // 8))
    )

    t2 = FONT_SMALL.render(
        "Toque una casilla para reiniciar",
        True,
        (255, 255, 255)
    )

    screen.blit(
        t2,
        t2.get_rect(center=(WIDTH // 2, HEIGHT // 8 + 60))
    )

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

        if event.type == pygame.KEYDOWN:
            if event.key == pygame.K_ESCAPE:
                running = False

    touch = detectar_toque()

    if state == "MENU":
        if touch is not None:
            start_new_game_with_first_move(touch)

    elif state == "PLAY":
        if not game_over and touch is not None:
            idx = registrar_jugada(touch)

            if idx is not None:
                check_winner()

                if game_over:
                    if winner and S_WIN:
                        S_WIN.play()

                    if not winner and S_DRAW:
                        S_DRAW.play()

        if game_over:
            state = "END"

    elif state == "END":
        if touch is not None:
            start_new_game_with_first_move(touch)

    if state == "MENU":
        draw_menu(dt)

    elif state == "PLAY":
        draw_game(dt)

    elif state == "END":
        draw_end(dt)

    pygame.display.flip()
    clock.tick(60)

pygame.quit()
