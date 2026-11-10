"""Pygame preview of animated eyes and the LED strip."""

from libraries.simulation.arby_memory_pixels import MemoryPixels


class Preview:
    def __init__(self, count):
        import pygame
        self.pg = pygame
        pygame.display.init()
        pygame.font.init()
        try:
            self.screen = pygame.display.set_mode((760, 490))
        except Exception:
            pygame.quit()
            raise
        pygame.display.set_caption("Arby / ojos y tira LED")
        self.font = pygame.font.Font(None, 28)
        self.small = pygame.font.Font(None, 22)
        self.count = count

    def requested_stop(self):
        return any(event.type == self.pg.QUIT or
                   (event.type == self.pg.KEYDOWN and event.key == self.pg.K_ESCAPE)
                   for event in self.pg.event.get())

    def show(self, frame, visual, pixels, *, physical_strip):
        pg = self.pg
        self.screen.fill((12, 18, 26))
        title = f"Arby / {visual.matrix_state} / RGB {visual.color}"
        self.screen.blit(self.font.render(title, True, (180, 235, 255)), (35, 24))
        for side, x in enumerate((76, 428)):
            panel = frame.crop((side*32, 0, side*32+32, 32))
            surface = pg.image.fromstring(panel.tobytes(), panel.size, "RGB")
            self.screen.blit(pg.transform.scale(surface, (256, 256)), (x, 85))
        label = "Tira física activa" if physical_strip else "Tira simulada"
        self.screen.blit(self.small.render(f"{label} / {visual.phase}", True,
                                         (170, 190, 205)), (76, 365))
        # Physical NeoPixel does not expose a plain RGB buffer; show its base RGB.
        colors = pixels.values if isinstance(pixels, MemoryPixels) else [visual.color] * self.count
        step = 608 / self.count
        for i, color in enumerate(colors):
            pg.draw.rect(self.screen, color, (76 + i*step, 400, max(1, step-2), 18))
        self.screen.blit(self.small.render("Escribe en la consola / Esc o cerrar: salir", True,
                                         (170, 190, 205)), (76, 451))
        pg.display.flip()

    def close(self):
        self.pg.quit()
