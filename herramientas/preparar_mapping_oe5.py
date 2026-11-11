"""Agrega regular-oe5 al código fuente del controlador, sin modificar regular."""
import argparse
from pathlib import Path
import re


def patch_mapping(source):
    if re.search(r'\.name\s*=\s*"regular-oe5"', source):
        raise ValueError('Ya existe regular-oe5; no se modificó el archivo.')
    match = re.search(r'\{\s*\.name\s*=\s*"regular",.*?\n\s*\},', source, re.S)
    if not match:
        raise ValueError('No se encontró el bloque regular esperado; revisa la versión del controlador.')
    block = match.group()
    block, changed = re.subn(r'(\.output_enable\s*=\s*GPIO_BIT\()18(\))', r'\g<1>5\2', block)
    if changed != 1:
        raise ValueError('OE de regular no es GPIO18; no se modificó el archivo.')
    block = block.replace('"regular"', '"regular-oe5"', 1)
    # Solo una cadena paralela: GPIO5 y GPIO12 quedan fuera de p1/p2.
    block = re.sub(r'^.*\.p[12]_\w+\s*=.*\n', '', block, flags=re.M)
    return source[:match.end()] + '\n  /* Arby: regular con OE en BCM5; parallel=1. */\n  ' + block + source[match.end():]


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('source_dir', type=Path, help='Carpeta del repositorio rpi-rgb-led-matrix')
    args = parser.parse_args()
    path = args.source_dir / 'lib' / 'hardware-mapping.c'
    try:
        source = path.read_text()
        updated = patch_mapping(source)
        backup = path.with_suffix('.c.arby-backup')
        if backup.exists():
            raise ValueError(f'Ya existe el respaldo {backup}; revísalo antes de continuar.')
        backup.write_text(source)
        path.write_text(updated)
    except (OSError, ValueError) as exc:
        parser.exit(1, f'{exc}\n')
    print(f'Mapeo añadido a {path}. Respaldo: {backup}. Falta recompilar e instalar rgbmatrix.')


if __name__ == '__main__':
    main()
