import tkinter as tk
import time
from collections import deque
from app.hardware.trill_lib import TrillLib

# ============================================================
# ADAPTADOR REAL PARA TU TRILL (YA FUNCIONANDO)
# ============================================================

class TrillAdapter:
    def __init__(self):
        # I2C bus 1, tipo bar, dirección 0x20
        self.device = TrillLib(1, "bar", 0x20)

        # Configuración igual a tu código funcional
        #self.device.setMode("CENTROID")
        #self.device.setPrescaler(2)
        #self.device.updateBaseLine()
        self.device.setMode("CENTROID")
        self.device.setPrescaler(4)          # ↑ reduce ruido
        self.device.setNoiseThreshold(0.004)  # 🔥 clave
        self.device.updateBaseLine()

    def read_trill(self):
        touches = []

        self.device.readTrill()
        n = self.device.getNumTouches()

        for i in range(n):
            pos = self.device.touchLocation(i)
            size = self.device.touchSize(i)

            touches.append({
                "pos": pos,
                "size": size
            })

        return touches


# ============================================================
# INTERFAZ GRÁFICA
# ============================================================

class TrillBarGUI:
    def __init__(self, root, adapter):
        self.root = root
        self.adapter = adapter

        self.root.title("Trill Bar Monitor")
        self.root.geometry("1100x420")
        self.root.configure(bg="#111111")

        self.canvas = tk.Canvas(
            self.root,
            width=1100,
            height=420,
            bg="#111111",
            highlightthickness=0
        )
        self.canvas.pack(fill="both", expand=True)

        self.bar_left = 100
        self.bar_top = 150
        self.bar_width = 900
        self.bar_height = 60
        self.bar_right = self.bar_left + self.bar_width
        self.bar_bottom = self.bar_top + self.bar_height

        self.trail = deque(maxlen=200)

        self.info_var = tk.StringVar(value="Esperando datos del Trill...")
        self.info_label = tk.Label(
            self.root,
            textvariable=self.info_var,
            bg="#111111",
            fg="#DDDDDD",
            font=("Arial", 12)
        )
        self.info_label.place(x=20, y=20)

        self.clear_button = tk.Button(
            self.root,
            text="Limpiar rastro",
            command=self.clear_trail,
            font=("Arial", 11)
        )
        self.clear_button.place(x=20, y=60)

        self.update_ui()

    def clear_trail(self):
        self.trail.clear()

    def pos_to_x(self, pos):
        pos = max(0.0, min(1.0, pos))
        return self.bar_left + pos * self.bar_width

    def size_to_radius(self, size):
        # Ajustado a tu librería (valores pequeños)
        return max(8, min(35, size * 8 + 5))

    def draw_base(self):
        self.canvas.delete("all")

        self.canvas.create_text(
            550, 120,
            text="TRILL BAR",
            fill="#DDDDDD",
            font=("Arial", 18, "bold")
        )

        self.canvas.create_rectangle(
            self.bar_left,
            self.bar_top,
            self.bar_right,
            self.bar_bottom,
            fill="#1E1E1E",
            outline="#666666",
            width=2
        )

    def draw_trail(self):
        for item in self.trail:
            self.canvas.create_oval(
                item["x"] - item["r"],
                item["y"] - item["r"],
                item["x"] + item["r"],
                item["y"] + item["r"],
                fill="#2E8B2E",
                outline=""
            )

    def draw_current_touches(self, touches):
        text_parts = []

        for idx, touch in enumerate(touches):
            pos = touch["pos"]
            size = touch["size"]

            x = self.pos_to_x(pos)
            y = (self.bar_top + self.bar_bottom) / 2
            r = self.size_to_radius(size)

            # Guardar rastro
            self.trail.append({
                "x": x,
                "y": y,
                "r": r * 0.5
            })

            # Punto actual
            self.canvas.create_oval(
                x - r, y - r, x + r, y + r,
                fill="#00FF66",
                outline="#CCFFDD",
                width=2
            )

            # Línea vertical
            self.canvas.create_line(
                x, self.bar_top - 20,
                x, self.bar_bottom + 20,
                fill="#55FFAA",
                width=2
            )

            text_parts.append(
                f"Touch {idx}: pos={pos:.3f}, size={size:.3f}"
            )

        if text_parts:
            self.info_var.set(" | ".join(text_parts))
        else:
            self.info_var.set("Sin toque detectado")

    def update_ui(self):
        self.draw_base()

        try:
            touches = self.adapter.read_trill()
        except Exception as e:
            touches = []
            self.info_var.set(f"Error: {e}")

        self.draw_trail()
        self.draw_current_touches(touches)

        self.root.after(20, self.update_ui)


# ============================================================
# MAIN
# ============================================================

def main():
    root = tk.Tk()
    adapter = TrillAdapter()
    app = TrillBarGUI(root, adapter)
    root.mainloop()


if __name__ == "__main__":
    main()
