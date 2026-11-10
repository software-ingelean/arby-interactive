#!/usr/bin/env python3
"""Control de 55 NeoPixel en GPIO12. Usa las librerías del script original.
Ejecutar con el Python del entorno donde están instaladas board y neopixel.
Ctrl+C detiene un efecto; 0 sale y apaga la tira.
"""
import argparse
import colorsys
import math
import time

COLORES = {
    'rojo': (255, 0, 0), 'verde': (0, 255, 0),
    'azul': (0, 0, 255), 'blanco': (255, 255, 255),
    'amarillo': (255, 255, 0), 'cian': (0, 255, 255),
    'magenta': (255, 0, 255), 'naranja': (255, 80, 0),
    'morado': (128, 0, 255), 'apagado': (0, 0, 0),
}


def numero(texto, minimo, maximo):
    while True:
        try:
            valor = int(input(texto))
            if minimo <= valor <= maximo:
                return valor
        except ValueError:
            pass
        print(f'Ingresa un entero entre {minimo} y {maximo}.')


def elegir_color():
    print('Colores: ' + ', '.join(COLORES))
    while True:
        entrada = input('Nombre o RGB (ejemplo: 255,80,0): ').strip().lower()
        if entrada in COLORES:
            return COLORES[entrada]
        try:
            rgb = tuple(int(v) for v in entrada.replace(',', ' ').split())
            if len(rgb) == 3 and all(0 <= v <= 255 for v in rgb):
                return rgb
        except ValueError:
            pass
        print('Color inválido. Cada componente RGB debe estar entre 0 y 255.')


def expansion(pixels, paso, color, estela=0):
    """Un frente simétrico desde el centro; admite cantidades pares e impares.

    estela=0: center out, sin dejar LED anteriores encendidos.
    estela>0: ripple, con una cola de intensidad decreciente.
    Incluye un cuadro apagado entre expansiones.
    """
    centro_izq = (len(pixels) - 1) // 2
    centro_der = len(pixels) // 2
    radio_max = centro_izq
    radio = paso % (radio_max + estela + 2)
    pixels.fill((0, 0, 0))
    for i in range(len(pixels)):
        distancia = min(abs(i - centro_izq), abs(i - centro_der))
        retraso = radio - distancia
        if 0 <= retraso <= estela:
            factor = (1 - retraso / (estela + 1)) ** 2
            pixels[i] = tuple(round(c * factor) for c in color)


def efecto(pixels, tipo, color, pausa):
    print('Efecto activo. Presiona Ctrl+C para volver al menú.')
    paso = 0
    try:
        while True:
            if tipo == '4':  # Parpadeo
                pixels.fill(color if paso % 2 == 0 else (0, 0, 0))
            elif tipo == '5':  # Punto con cola y rebote
                pixels.fill((0, 0, 0))
                recorrido = max(1, 2 * (len(pixels) - 1))
                fase = paso % recorrido
                posicion = fase if fase < len(pixels) else recorrido - fase
                for i in range(len(pixels)):
                    factor = max(0, 1 - abs(i - posicion) / 5)
                    pixels[i] = tuple(round(c * factor) for c in color)
            elif tipo == '6':  # Arcoíris
                for i in range(len(pixels)):
                    rgb = colorsys.hsv_to_rgb((i / len(pixels) + paso / 256) % 1, 1, 1)
                    pixels[i] = tuple(round(c * 255) for c in rgb)
            elif tipo == '7':  # Respiración sin modificar el brillo configurado
                factor = (1 - math.cos(paso * math.pi / 50)) / 2
                pixels.fill(tuple(round(c * factor) for c in color))
            elif tipo == '10':  # Center out, dos frentes sin estela
                expansion(pixels, paso, color)
            elif tipo == '11':  # Ripple, onda con desvanecimiento
                expansion(pixels, paso, color, estela=5)
            pixels.show()
            paso += 1
            time.sleep(pausa)
    except KeyboardInterrupt:
        pixels.fill((0, 0, 0))
        pixels.show()
        print('\nEfecto detenido.')


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--leds', type=int, default=55, help='Cantidad de LED (55)')
    parser.add_argument('--gpio', type=int, default=12, help='GPIO BCM de datos (12)')
    parser.add_argument('--brillo', type=int, default=20, help='Brillo inicial 0–100 (20)')
    args = parser.parse_args()
    if args.leds < 1 or not 0 <= args.brillo <= 100 or args.gpio < 0:
        parser.error('Cantidad > 0, GPIO >= 0 y brillo entre 0 y 100.')

    pixels = None
    try:
        import board
        import neopixel
        pin = getattr(board, f'D{args.gpio}', None)
        if pin is None:
            raise ValueError(f'GPIO {args.gpio} no disponible en board.')
        pixels = neopixel.NeoPixel(pin, args.leds, brightness=args.brillo / 100,
                                  auto_write=False, pixel_order=neopixel.GRB)
        pixels.fill((0, 0, 0))
        pixels.show()
        color = (0, 255, 0)
        pausa = 0.04
        while True:
            print(f'\n--- TIRA LED | GPIO{args.gpio} | {args.leds} LED ---')
            print(f'Brillo: {pixels.brightness * 100:.0f}% | Color: {color}')
            print('1. Color fijo / encender\n2. Cambiar brillo\n3. Controlar un LED')
            print('4. Parpadeo\n5. Punto con rebote\n6. Arcoíris\n7. Respiración')
            print('8. Cambiar velocidad\n9. Apagar')
            print('10. Center out (centro hacia extremos)\n11. Ripple (onda con estela)')
            print('0. Salir y apagar')
            opcion = input('Opción: ').strip()
            if opcion == '0':
                break
            if opcion == '1':
                color = elegir_color()
                pixels.fill(color)
                pixels.show()
            elif opcion == '2':
                pixels.brightness = numero('Brillo (0–100): ', 0, 100) / 100
                pixels.show()
            elif opcion == '3':
                indice = numero(f'Número de LED (1–{args.leds}): ', 1, args.leds) - 1
                pixels[indice] = elegir_color()
                pixels.show()
            elif opcion in ('4', '5', '6', '7', '10', '11'):
                if opcion != '6':
                    color = elegir_color()
                efecto(pixels, opcion, color, pausa)
            elif opcion == '8':
                pausa = numero('Intervalo por paso en ms (10–2000): ', 10, 2000) / 1000
            elif opcion == '9':
                pixels.fill((0, 0, 0))
                pixels.show()
            else:
                print('Opción inválida.')
    except (KeyboardInterrupt, EOFError):
        print('\nCerrando...')
    except ImportError as exc:
        print(f'Falta una dependencia: {exc}. Usa el entorno de tu script original.')
        return 1
    except (OSError, RuntimeError, ValueError) as exc:
        print(f'No se pudo controlar la tira: {exc}')
        print('Si aparece "Operation not permitted" o "mailbox", ejecuta con sudo')
        print('usando la ruta completa al Python de tu entorno virtual.')
        return 1
    finally:
        if pixels is not None:
            try:
                pixels.fill((0, 0, 0))
                pixels.show()
            finally:
                pixels.deinit()
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
