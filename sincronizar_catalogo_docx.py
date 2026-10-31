"""Sincroniza las palabras definitivas de un DOCX con la base de Lotería.

Uso:
    python sincronizar_catalogo_docx.py "C:/ruta/Palabras_Mazahua_con_imagenes.docx"

No borra cartas, UID RFID, lecturas ni archivos multimedia. Únicamente actualiza
los tres textos de las cartas que el documento identifica por su palabra española.
"""
from __future__ import annotations

import argparse
from pathlib import Path
import sqlite3
from typing import Iterable
from xml.etree import ElementTree as ET
from zipfile import ZipFile

from base_datos import conectar, crear_esquema
from catalogo_loteria import clave, nombre_canonico

_WORD = "{http://schemas.openxmlformats.org/wordprocessingml/2006/main}"


def _texto(elemento: ET.Element) -> str:
    return "".join(nodo.text or "" for nodo in elemento.iter(f"{_WORD}t")).strip()


def filas_documento(ruta: Path) -> list[dict[str, str]]:
    """Extrae español, inglés y mazahua de la primera tabla de un DOCX."""
    with ZipFile(ruta) as archivo:
        raiz = ET.fromstring(archivo.read("word/document.xml"))
    tablas = raiz.findall(f".//{_WORD}tbl")
    if not tablas:
        raise ValueError("El documento no contiene una tabla de palabras.")
    filas: list[dict[str, str]] = []
    for indice, fila in enumerate(tablas[0].findall(f"{_WORD}tr")):
        celdas = [_texto(celda) for celda in fila.findall(f"{_WORD}tc")]
        if indice == 0 or len(celdas) < 4 or not celdas[1]:
            continue
        filas.append({"español": celdas[1], "inglés": celdas[2], "mazahua": celdas[3]})
    if not filas:
        raise ValueError("No se encontraron palabras válidas en la primera tabla.")
    return filas


def _candidatas(conexion: sqlite3.Connection, palabra: str) -> list[sqlite3.Row]:
    objetivo = clave(palabra)
    alias = clave(nombre_canonico(f"{palabra}.x"))
    # Equivalencias históricas que ya podían existir en una BD anterior.
    equivalencias = {
        "puerco": {"puerco", "cerdo"},
        "chapulin": {"chapulin", "chapilin"},
    }
    claves = {objetivo, alias, *equivalencias.get(objetivo, set())}
    return [
        carta for carta in conexion.execute("SELECT * FROM carta").fetchall()
        if clave(carta["nombre"]) in claves
    ]


def sincronizar(conexion: sqlite3.Connection, filas: Iterable[dict[str, str]]) -> tuple[list[str], list[str]]:
    """Actualiza los textos y devuelve (actualizadas, sin_coincidencia)."""
    crear_esquema(conexion)
    actualizadas, sin_coincidencia = [], []
    usados: set[int] = set()
    for fila in filas:
        candidatas = [c for c in _candidatas(conexion, fila["español"]) if c["id"] not in usados]
        if len(candidatas) != 1:
            sin_coincidencia.append(fila["español"])
            continue
        carta = candidatas[0]
        usados.add(carta["id"])
        nombre = fila["español"].strip().casefold()
        conexion.execute(
            "UPDATE carta SET nombre = ?, mazahua = ?, ingles = ? WHERE id = ?",
            (nombre, fila["mazahua"].strip(), fila["inglés"].strip(), carta["id"]),
        )
        actualizadas.append(nombre)
    conexion.commit()
    return actualizadas, sin_coincidencia


def main() -> None:
    parser = argparse.ArgumentParser(description="Sincroniza el catálogo de palabras desde un DOCX.")
    parser.add_argument("documento", type=Path, help="DOCX con la tabla Imagen, Español, Inglés y Mazahua")
    args = parser.parse_args()
    if not args.documento.is_file():
        raise SystemExit(f"No se encontró el documento: {args.documento}")
    conexion = conectar()
    try:
        actualizadas, sin_coincidencia = sincronizar(conexion, filas_documento(args.documento))
    finally:
        conexion.close()
    print(f"Palabras actualizadas: {len(actualizadas)}")
    print("Sin coincidencia: " + (", ".join(sin_coincidencia) if sin_coincidencia else "ninguna"))


if __name__ == "__main__":
    main()
