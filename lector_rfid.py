"""Lectura del lector RFID (ESP32 + MFRC522) por puerto serie.

El sketch ``loteria_mazahua_lector.ino`` imprime una línea por tarjeta:
    CARD:<UID>|ES:<texto>|EN:<texto>|MZ:<texto>

``LectorRFID`` corre en un hilo y entrega cada lectura a un ``callback``.
No toca SQLite (las conexiones no se comparten entre hilos): la interfaz
recibe el evento y consulta la base en su propio hilo.
"""
from __future__ import annotations

import threading
from typing import Callable

from base_datos import normalizar_uid

BAUDIOS = 115200


def parsear_linea(linea: str) -> dict[str, str] | None:
    """Convierte una línea serial en ``{uid, espanol, mazahua, ingles}``.

    Devuelve None para cualquier línea que no sea una lectura (p. ej. LECTOR_LISTO).
    """
    linea = linea.strip()
    if not linea.startswith("CARD:"):
        return None
    campos = {}
    for parte in linea.split("|"):
        etiqueta, _, valor = parte.partition(":")
        campos[etiqueta] = valor.strip()
    try:
        uid = normalizar_uid(campos["CARD"])
    except (KeyError, ValueError):
        return None
    return {"uid": uid, "espanol": campos.get("ES", ""), "mazahua": campos.get("MZ", ""), "ingles": campos.get("EN", "")}


def listar_puertos() -> list[str]:
    try:
        from serial.tools import list_ports
    except ImportError:
        return []
    return [p.device for p in list_ports.comports()]


class LectorRFID(threading.Thread):
    """Hilo que lee el puerto serie y llama ``callback(lectura)`` por cada tarjeta."""

    def __init__(self, puerto: str, callback: Callable[[dict[str, str]], None],
                 on_error: Callable[[str], None] | None = None, baudios: int = BAUDIOS) -> None:
        super().__init__(daemon=True)
        self.puerto, self.baudios = puerto, baudios
        self.callback, self.on_error = callback, on_error
        self._detener = threading.Event()

    def run(self) -> None:
        try:
            import serial  # pyserial; se importa aquí para que la app abra sin él
            with serial.Serial(self.puerto, self.baudios, timeout=0.5) as conexion:
                while not self._detener.is_set():
                    linea = conexion.readline().decode("utf-8", errors="replace")
                    lectura = parsear_linea(linea)
                    if lectura:
                        self.callback(lectura)
        except Exception as error:  # puerto ocupado, cable desconectado, falta pyserial…
            if self.on_error:
                self.on_error(f"Lector RFID: {error}")

    def detener(self) -> None:
        self._detener.set()
