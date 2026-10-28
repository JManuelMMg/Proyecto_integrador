"""Graba en tarjetas RFID las palabras de la base, una tras otra, usando el sketch del lector.

Uso:
    python grabar_tarjetas.py                 # cartas que aún no tienen tarjeta
    python grabar_tarjetas.py --todas         # todas las cartas (regraba las que ya tienen)
    python grabar_tarjetas.py gato perro      # solo esas palabras
    python grabar_tarjetas.py --puerto COM5   # si hay varios puertos serie

Por cada carta pide acercar una tarjeta en blanco; el ESP32 graba ES/EN/MZ, lo verifica
y la tarjeta queda ligada a la carta en loteria_mazahua.sqlite3.
"""
from __future__ import annotations

import argparse
import queue
import sys
import time

from base_datos import carta_por_palabra, conectar, crear_esquema, reasignar_uid
from lector_rfid import LectorRFID, comando_grabar, listar_puertos, recortar_16

ESPERA_RESPUESTA_S = 20  # el ESP32 espera 15 s la tarjeta; margen para la respuesta


def esperar_lector(lector: LectorRFID, eventos: queue.Queue) -> bool:
    """Espera a que el puerto abra y el ESP32 (que se reinicia al conectar) confirme el RC522."""
    limite = time.monotonic() + 8
    while time.monotonic() < limite:
        try:
            evento = eventos.get(timeout=0.2)
        except queue.Empty:
            continue
        if "error" in evento:
            print(evento["error"])
            return False
        if "estado" in evento:
            print("ESP32:", evento["estado"])
            if evento["estado"] == "Lector RFID listo":
                return True
            if evento["es_error"] and "RC522" in evento["estado"]:
                return False
    print("El ESP32 no respondió. ¿Subiste loteria_mazahua_lector.ino y es el puerto correcto?")
    return False


def grabar(lector: LectorRFID, eventos: queue.Queue, carta) -> dict | None:
    """Envía GRABAR y espera la respuesta final (ok / error). None si no hubo respuesta."""
    while not eventos.empty():  # descarta lecturas viejas
        eventos.get()
    lector.enviar(comando_grabar(carta["nombre"], carta["mazahua"], carta["ingles"]))
    limite = time.monotonic() + ESPERA_RESPUESTA_S
    while time.monotonic() < limite:
        try:
            evento = eventos.get(timeout=0.2)
        except queue.Empty:
            continue
        if evento.get("grabacion") in ("ok", "error", "cancelado"):
            return evento
        if "error" in evento:
            print(evento["error"])
            return None
    return None


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("palabras", nargs="*", help="palabras a grabar (por defecto, las cartas sin tarjeta)")
    parser.add_argument("--todas", action="store_true", help="incluye cartas que ya tienen tarjeta")
    parser.add_argument("--puerto", help="puerto serie del ESP32 (p. ej. COM3)")
    args = parser.parse_args()
    sys.stdout.reconfigure(errors="replace")  # consolas de Windows sin UTF-8

    conexion = conectar()
    crear_esquema(conexion)
    if args.palabras:
        cartas = []
        for palabra in args.palabras:
            carta = carta_por_palabra(conexion, palabra)
            if carta:
                cartas.append(carta)
            else:
                print(f"«{palabra}» no está en la base; se omite.")
    else:
        filtro = "" if args.todas else "WHERE uid_rfid IS NULL"
        cartas = conexion.execute(f"SELECT * FROM carta {filtro} ORDER BY nombre COLLATE NOCASE").fetchall()
    if not cartas:
        print("No hay cartas por grabar.")
        return 0

    puertos = [args.puerto] if args.puerto else listar_puertos()
    if not puertos:
        print("No se detectó ningún puerto serie. Conecta el ESP32 e instala pyserial.")
        return 1
    eventos: queue.Queue = queue.Queue()
    lector = LectorRFID(puertos[0], eventos.put, lambda msg: eventos.put({"error": msg}),
                        lambda es_error, msg: eventos.put({"estado": msg, "es_error": es_error}))
    lector.start()
    print(f"Conectando con el ESP32 en {puertos[0]}…")
    if not esperar_lector(lector, eventos):
        return 1

    grabadas = 0
    print(f"\n{len(cartas)} carta(s). Enter = grabar · s = saltar · q = salir\n")
    for numero, carta in enumerate(cartas, 1):
        textos = " · ".join(f"{t}" for t in (carta["nombre"], carta["mazahua"], carta["ingles"]) if t)
        actual = f" (ya tiene la tarjeta {carta['uid_rfid']})" if carta["uid_rfid"] else ""
        opcion = input(f"[{numero}/{len(cartas)}] «{textos}»{actual}: ").strip().lower()
        if opcion == "q":
            break
        if opcion == "s":
            continue
        largas = [t for t in (carta["nombre"], carta["mazahua"], carta["ingles"]) if t and recortar_16(t) != t]
        if largas:
            print("   Se recorta a 16 bytes:", ", ".join(largas))
        print("   Acerca la tarjeta al lector…")
        respuesta = grabar(lector, eventos, carta)
        if respuesta is None:
            print("   ⚠ Sin respuesta del ESP32.")
        elif respuesta["grabacion"] == "ok":
            anterior = reasignar_uid(conexion, carta["id"], respuesta["uid"])
            extra = f" (se quitó de «{anterior}»)" if anterior else ""
            print(f"   ✓ Tarjeta {respuesta['uid']} grabada y asignada{extra}. Retírala.")
            grabadas += 1
        else:
            print(f"   ⚠ No se grabó: {respuesta.get('motivo', 'cancelado')}.")
    lector.detener()
    conexion.close()
    print(f"\nListo: {grabadas} tarjeta(s) grabada(s).")
    return 0


if __name__ == "__main__":
    sys.exit(main())
