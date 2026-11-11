"""Optional adapter for hzeller/rpi-rgb-led-matrix. No GPIO imports in preview."""
class MatrixOutput:
    def __init__(self, *, multiplexing, slowdown=2, brightness=25,
                 row_address_type=0, swap_eyes=False, disable_hardware_pulsing=False,
                 hardware_mapping="regular", rgb_sequence="RGB"):
        if multiplexing is None:
            raise ValueError("El panel 1/8 requiere validar multiplexing con el hardware.")
        if not 1 <= brightness <= 100:
            raise ValueError("brightness debe estar entre 1 y 100")
        from rgbmatrix import RGBMatrix, RGBMatrixOptions
        options = RGBMatrixOptions()
        options.rows = 32
        options.cols = 32
        options.chain_length = 2
        options.parallel = 1
        if hardware_mapping not in ("regular", "regular-oe5"):
            raise ValueError("hardware_mapping debe ser regular o regular-oe5")
        options.hardware_mapping = hardware_mapping
        if rgb_sequence not in ("RGB", "RBG", "GRB", "GBR", "BRG", "BGR"):
            raise ValueError("rgb_sequence debe ser una permutación de RGB")
        options.led_rgb_sequence = rgb_sequence
        options.gpio_slowdown = slowdown
        options.brightness = brightness
        options.multiplexing = multiplexing
        options.row_address_type = row_address_type
        options.disable_hardware_pulsing = disable_hardware_pulsing or hardware_mapping == "regular-oe5"
        self.matrix = RGBMatrix(options=options)
        if self.matrix.width != 64 or self.matrix.height != 32:
            self.matrix.Clear()
            raise ValueError("Se esperaba un lienzo lógico de 64x32.")
        self.canvas = self.matrix.CreateFrameCanvas()
        self.swap_eyes = swap_eyes

    def show(self, frame):
        if frame.size != (64,32) or frame.mode != "RGB":
            raise ValueError("El frame debe ser RGB de 64x32")
        if self.swap_eyes:
            image = frame.copy()
            image.paste(frame.crop((32,0,64,32)),(0,0))
            image.paste(frame.crop((0,0,32,32)),(32,0))
            frame = image
        self.canvas.SetImage(frame)
        self.canvas = self.matrix.SwapOnVSync(self.canvas)

    def close(self):
        self.matrix.Clear()
