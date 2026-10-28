"""Prepara la Micro SD del ESP32 con las imágenes y audios guardados en SQLite.

Uso:  python exportar_sd.py E:\\        (la letra de la unidad de la Micro SD)

Crea la estructura que busca ``loteria_mazahua_lector.ino``:
    /loteria/img/gato.png
    /loteria/audio/es/gato.mp3   /loteria/audio/mz/...   /loteria/audio/en/...
"""
from __future__ import annotations

from pathlib import Path
import re
import sys
import unicodedata

from base_datos import conectar, crear_esquema

CARPETAS = {"imagen": "img", "español": "audio/es", "mazahua": "audio/mz", "inglés": "audio/en"}


def clave_archivo(palabra: str) -> str:
    """Igual que ``claveArchivo`` del sketch: minúsculas, sin acentos, espacios como '_'."""
    sin_tildes = "".join(c for c in unicodedata.normalize("NFD", palabra.casefold()) if unicodedata.category(c) != "Mn")
    return re.sub(r"[^a-z0-9_]", "", re.sub(r"[ \-_]", "_", sin_tildes))


def exportar(destino: Path) -> dict[str, int]:
    raiz = destino / "loteria"
    totales = dict.fromkeys(CARPETAS, 0)
    conexion = conectar()
    crear_esquema(conexion)
    filas = conexion.execute(
        "SELECT c.nombre, m.tipo, m.extension, m.contenido FROM medio m JOIN carta c ON c.id = m.carta_id"
    )
    for fila in filas:
        carpeta = raiz / CARPETAS[fila["tipo"]]
        carpeta.mkdir(parents=True, exist_ok=True)
        (carpeta / f"{clave_archivo(fila['nombre'])}{fila['extension']}").write_bytes(fila["contenido"])
        totales[fila["tipo"]] += 1
    conexion.close()
    return totales


if __name__ == "__main__":
    if len(sys.argv) != 2 or not Path(sys.argv[1]).is_dir():
        sys.exit("Uso: python exportar_sd.py <carpeta o unidad de la Micro SD>")
    for tipo, cantidad in exportar(Path(sys.argv[1])).items():
        print(f"{cantidad:3d} archivos de {tipo}")
