"""Prueba mapeos de paneles 32x32 encadenados en procesos independientes."""
import argparse
import subprocess
import sys
import time


def positive_seconds(value):
    seconds = float(value)
    if not 0 < seconds <= 60:
        raise argparse.ArgumentTypeError('Usa un tiempo mayor que 0 y hasta 60 segundos.')
    return seconds


def run_panel(args):
    from rgbmatrix import RGBMatrix, RGBMatrixOptions

    options = RGBMatrixOptions()
    options.rows = 32
    options.cols = 32
    options.chain_length = args.chain_length
    options.parallel = 1
    options.hardware_mapping = args.hardware_mapping
    options.brightness = 10
    options.gpio_slowdown = 4
    options.disable_hardware_pulsing = True
    options.multiplexing = args.mux[0]
    options.row_address_type = args.row_address_type
    if args.panel_type != 'default':
        options.panel_type = args.panel_type
    matrix = RGBMatrix(options=options)
    try:
        for name, color in [('ROJO', (255, 0, 0)),
                            ('VERDE', (0, 255, 0)),
                            ('AZUL', (0, 0, 255))]:
            print('  ' + name, flush=True)
            matrix.Fill(*color)
            time.sleep(args.seconds)
        matrix.Clear()
        # Patrón para reconocer el orden espacial cuando ya hay iluminación.
        print('  CUADRICULA', flush=True)
        for y in range(matrix.height):
            for x in range(matrix.width):
                if (x // 4 + y // 4) % 2 == 0:
                    matrix.SetPixel(x, y, 255, 0, 0)
        time.sleep(args.seconds)
    finally:
        matrix.Clear()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--mux', nargs='+', type=int, default=list(range(18)),
                        help='Mapeos a probar (por defecto: 0 a 17).')
    parser.add_argument('--seconds', type=positive_seconds, default=2,
                        help='Segundos por color y patrón (por defecto: 2).')
    parser.add_argument('--row-address-type', type=int, default=0)
    parser.add_argument('--hardware-mapping', choices=['regular', 'regular-oe5'], default='regular')
    parser.add_argument('--chain-length', type=int, choices=[1, 2], default=1,
                        help='Paneles encadenados por OUT → IN (por defecto: 1).')
    parser.add_argument('--panel-type', choices=['default', 'FM6126A', 'FM6127'],
                        default='default')
    parser.add_argument('--child', action='store_true', help=argparse.SUPPRESS)
    args = parser.parse_args()
    if any(mux < 0 for mux in args.mux) or args.row_address_type < 0:
        parser.error('Los índices deben ser mayores o iguales a cero.')
    try:
        if args.child:
            run_panel(args)
            return
        print(f'Prueba de {args.chain_length} panel(es) encadenados; '
              'Ctrl+C detiene el barrido.', flush=True)
        for mux in args.mux:
            print(f'\n=== multiplexing={mux}, row_address_type={args.row_address_type}, '
                  f'panel_type={args.panel_type} ===', flush=True)
            result = subprocess.run([
                sys.executable, '-m', 'diagnosticos.matrix_scan', '--child',
                '--mux', str(mux), '--seconds', str(args.seconds),
                '--row-address-type', str(args.row_address_type),
                '--chain-length', str(args.chain_length),
                '--hardware-mapping', args.hardware_mapping,
                '--panel-type', args.panel_type,
            ])
            if result.returncode:
                print(f'Configuración fallida (código {result.returncode}); '
                      'revisa el mensaje anterior.', flush=True)
        print('\nBarrido terminado. La iluminación debe verificarse visualmente.', flush=True)
    except KeyboardInterrupt:
        print('\nPrueba detenida.', flush=True)


if __name__ == '__main__':
    main()
