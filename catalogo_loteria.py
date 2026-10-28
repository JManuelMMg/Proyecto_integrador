"""Reglas de normalización para el material de la lotería.

Los nombres de archivo no son el nombre que se muestra al usuario: esta tabla
unifica tildes, erratas y sinónimos conocidos al momento de cargar la BD.
"""
from __future__ import annotations

import re
import unicodedata


def clave(nombre: str) -> str:
    """Devuelve una clave segura, sin tildes ni diferencias de mayúsculas."""
    normalizado = unicodedata.normalize("NFD", nombre.casefold())
    sin_tildes = "".join(c for c in normalizado if unicodedata.category(c) != "Mn")
    return re.sub(r"[^a-z0-9]+", "", sin_tildes)


# Clave del archivo original -> nombre español canónico de la carta.
# Se preserva el archivo original como BLOB; sólo se corrige su identificación.
ALIAS = {
    "temascal": "temazcal",
    "temazcal": "temazcal",
    "naaranja": "naranja",
    "cerdo": "cerdo",
    "puerco": "cerdo",
    "chapilin": "chapulín",
    "chapulin": "chapulín",
    "saltamontes": "chapulín",
    "banana": "plátano",
    "platano": "plátano",
    "mama": "mamá",
    "papa": "papá",
    "cempasuchil": "cempasúchil",
    "corazon": "corazón",
    "rio": "río",
}


def nombre_canonico(nombre_archivo: str) -> str:
    """Convierte el nombre base de un archivo a la etiqueta de carta."""
    base = nombre_archivo.rsplit(".", 1)[0]
    return ALIAS.get(clave(base), base.strip().casefold())
