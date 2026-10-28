"""Lectura del lector RFID (ESP32 + MFRC522 + Micro SD) por puerto serie.

El sketch ``loteria_mazahua_lector.ino`` imprime una línea por evento:
    CARD:<UID>|ES:<texto>|EN:<texto>|MZ:<texto>|SD:IMG=1,ES=1,MZ=0,EN=0
    ESTADO:RC522=OK|VERSION=0x92         (diagnóstico correcto)
    ERROR:RC522=SIN_RESPUESTA|...         (fallo de hardware)
    GRABADO:<UID>|ES:..|EN:..|MZ:..       (respuesta al comando GRABAR)

Para grabar una tarjeta se envía ``comando_grabar(...)`` con ``LectorRFID.enviar``.

``LectorRFID`` corre en un hilo y entrega cada tarjeta a ``callback`` y cada
diagnóstico a ``on_estado``. No toca SQLite (las conexiones no se comparten
entre hilos): la interfaz recibe el evento y consulta la base en su propio hilo.
"""
from __future__ import annotations

import threading
import time
from typing import Callable

from base_datos import normalizar_uid

BAUDIOS = 115200
# Mensajes legibles para los diagnósticos del ESP32.
DIAGNOSTICOS = {
    "RC522=OK": "Lector RFID listo",
    "RC522=SIN_RESPUESTA": "El lector RFID (RC522) no responde: revisa cableado y alimentación 3.3V",
    "RC522=BLOQUEADO_POR_SD": "La Micro SD bloquea al RC522: activa SD_BUS_SEPARADO en el sketch",
    "SD=OK": "Micro SD lista",
    "SD=NO_DETECTADA": "Micro SD no detectada (el lector RFID sigue funcionando)",
    "SD=ESCRITURA_FALLIDA": "Se perdió la Micro SD",
}
MOTIVOS_GRABAR = {
    "TIEMPO_AGOTADO": "no se acercó ninguna tarjeta a tiempo",
    "AUTENTICACION": "la tarjeta no es MIFARE Classic o tiene otra llave",
    "ESCRITURA": "se retiró la tarjeta antes de terminar",
    "VERIFICACION": "lo grabado no coincide al leerlo; vuelve a intentarlo",
    "RC522": "el lector RFID no está listo",
}


def recortar_16(texto: str) -> str:
    """Recorta a 16 bytes UTF-8 (un bloque de la tarjeta) sin partir letras con acento."""
    texto = "".join(c for c in texto.strip() if c not in "|\r\n")
    while len(texto.encode("utf-8")) > 16:
        texto = texto[:-1]
    return texto


def comando_grabar(espanol: str, mazahua: str, ingles: str) -> str:
    """Comando para que el ESP32 grabe los tres textos en la siguiente tarjeta."""
    return f"GRABAR ES={recortar_16(espanol)}|EN={recortar_16(ingles)}|MZ={recortar_16(mazahua)}"


def parsear_grabacion(linea: str) -> dict | None:
    """Respuestas al comando GRABAR -> ``{"grabacion": esperando|ok|error|cancelado, ...}``."""
    linea = linea.strip()
    if linea == "GRABAR_ESPERANDO":
        return {"grabacion": "esperando"}
    if linea == "GRABAR_CANCELADO":
        return {"grabacion": "cancelado"}
    if linea.startswith("GRABADO:"):
        lectura = parsear_linea("CARD:" + linea[len("GRABADO:"):])
        return {"grabacion": "ok", **lectura} if lectura else None
    if linea.startswith("ERROR:GRABAR="):
        campos = dict(p.partition("=")[::2] for p in linea[len("ERROR:"):].split("|"))
        codigo = campos.get("GRABAR", "")
        return {"grabacion": "error", "uid": campos.get("UID", ""), "codigo": codigo,
                "motivo": MOTIVOS_GRABAR.get(codigo, codigo)}
    return None


def parsear_linea(linea: str) -> dict | None:
    """Convierte una línea ``CARD:`` en ``{uid, espanol, mazahua, ingles, sd}``.

    Devuelve None para cualquier línea que no sea una lectura (p. ej. LECTOR_LISTO).
    ``sd`` indica qué archivos encontró el ESP32 en la Micro SD: {"IMG": True, ...}.
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
    sd = {}
    for par in filter(None, campos.get("SD", "").split(",")):
        nombre, _, valor = par.partition("=")
        sd[nombre] = valor == "1"
    return {"uid": uid, "espanol": campos.get("ES", ""), "mazahua": campos.get("MZ", ""),
            "ingles": campos.get("EN", ""), "sd": sd}


def parsear_estado(linea: str) -> tuple[bool, str] | None:
    """``ESTADO:``/``ERROR:`` -> (es_error, mensaje legible). None si no es un diagnóstico."""
    linea = linea.strip()
    tipo, _, resto = linea.partition(":")
    if tipo not in ("ESTADO", "ERROR") or not resto:
        return None
    codigo = resto.split("|")[0]
    return tipo == "ERROR", DIAGNOSTICOS.get(codigo, resto.replace("|", " · "))


def listar_puertos() -> list[str]:
    try:
        from serial.tools import list_ports
    except ImportError:
        return []
    return [p.device for p in list_ports.comports()]


class LectorRFID(threading.Thread):
    """Hilo que lee el puerto serie y reparte tarjetas (``callback``) y diagnósticos (``on_estado``)."""

    def __init__(self, puerto: str, callback: Callable[[dict], None],
                 on_error: Callable[[str], None] | None = None,
                 on_estado: Callable[[bool, str], None] | None = None, baudios: int = BAUDIOS) -> None:
        super().__init__(daemon=True)
        self.puerto, self.baudios = puerto, baudios
        self.callback, self.on_error, self.on_estado = callback, on_error, on_estado
        self._detener = threading.Event()
        self._serial = None
        self._escritura = threading.Lock()

    def enviar(self, comando: str) -> bool:
        """Envía un comando al ESP32 (p. ej. ``comando_grabar(...)``). False si el puerto no está abierto."""
        with self._escritura:
            if self._serial is None:
                return False
            self._serial.write((comando + "\n").encode("utf-8"))
            return True

    def run(self) -> None:
        try:
            import serial  # pyserial; se importa aquí para que la app abra sin él
            with serial.Serial(self.puerto, self.baudios, timeout=0.5) as conexion:
                self._serial = conexion
                # Abrir el puerto reinicia el ESP32; si sus mensajes de arranque se pierden,
                # se pide el diagnóstico de nuevo un momento después.
                pedir_estado = time.monotonic() + 2.5
                while not self._detener.is_set():
                    if pedir_estado and time.monotonic() >= pedir_estado:
                        self.enviar("ESTADO")
                        pedir_estado = 0
                    linea = conexion.readline().decode("utf-8", errors="replace")
                    lectura = parsear_linea(linea)
                    if lectura:
                        self.callback(lectura)
                    elif grabacion := parsear_grabacion(linea):
                        self.callback(grabacion)
                    elif self.on_estado and (estado := parsear_estado(linea)):
                        self.on_estado(*estado)
        except Exception as error:  # puerto ocupado, cable desconectado, falta pyserial…
            self._serial = None
            if self.on_error:
                self.on_error(f"Lector RFID: {error}")

    def detener(self) -> None:
        self._detener.set()
        self._serial = None
