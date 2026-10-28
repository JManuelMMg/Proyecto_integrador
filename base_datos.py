"""Capa SQLite para la Lotería Mazahua."""
from __future__ import annotations

from pathlib import Path
import mimetypes
import sqlite3

from catalogo_loteria import clave, nombre_canonico

RAIZ = Path(__file__).resolve().parent
RUTA_BD = RAIZ / "loteria_mazahua.sqlite3"
IDIOMAS = ("español", "mazahua", "inglés")
TIPOS = ("imagen", *IDIOMAS)
FUENTES = {
    "imagen": RAIZ / "images" / "imagenes_nitidas",
    "español": RAIZ / "audios_Español" / "Audios",
    "mazahua": RAIZ / "audios_mazahua" / "Audios Mazahua",
    # Los audios en inglés se nombran con la palabra en español (gato.mp3).
    "inglés": RAIZ / "audios_ingles",
}
EXTENSIONES = {
    "imagen": {".png", ".jpg", ".jpeg", ".gif", ".webp", ".bmp"},
    "audio": {".mp3", ".mp4", ".wav", ".ogg", ".m4a"},
}

_SQL_MEDIO = """
    CREATE TABLE {nombre} (
        id INTEGER PRIMARY KEY,
        carta_id INTEGER NOT NULL REFERENCES carta(id) ON DELETE CASCADE,
        tipo TEXT NOT NULL CHECK(tipo IN ('imagen', 'español', 'mazahua', 'inglés')),
        nombre_original TEXT NOT NULL,
        extension TEXT NOT NULL,
        mime TEXT NOT NULL,
        contenido BLOB NOT NULL,
        manual INTEGER NOT NULL DEFAULT 0,  -- 1 = cargado desde la app, no desde una carpeta
        actualizado_en TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
        UNIQUE(carta_id, tipo)
    )"""


def conectar(ruta: Path = RUTA_BD) -> sqlite3.Connection:
    conexion = sqlite3.connect(ruta)
    conexion.row_factory = sqlite3.Row
    conexion.execute("PRAGMA foreign_keys = ON")
    return conexion


def crear_esquema(conexion: sqlite3.Connection) -> None:
    conexion.execute(
        """CREATE TABLE IF NOT EXISTS carta (
               id INTEGER PRIMARY KEY,
               nombre TEXT NOT NULL UNIQUE COLLATE NOCASE,
               mazahua TEXT NOT NULL DEFAULT '',
               ingles TEXT NOT NULL DEFAULT '',
               uid_rfid TEXT,  -- UID de la tarjeta física; opcional
               creado_en TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
           )"""
    )
    # Migración de bases anteriores: palabras en mazahua/inglés.
    columnas = {fila["name"] for fila in conexion.execute("PRAGMA table_info(carta)")}
    for columna in ("mazahua", "ingles"):
        if columna not in columnas:
            conexion.execute(f"ALTER TABLE carta ADD COLUMN {columna} TEXT NOT NULL DEFAULT ''")
    if "uid_rfid" not in columnas:
        conexion.execute("ALTER TABLE carta ADD COLUMN uid_rfid TEXT")
    # Una tarjeta solo puede pertenecer a una carta (varias cartas pueden no tener tarjeta).
    conexion.execute("CREATE UNIQUE INDEX IF NOT EXISTS carta_uid_rfid ON carta(uid_rfid)")
    actual = conexion.execute("SELECT sql FROM sqlite_master WHERE name = 'medio'").fetchone()
    if actual is None:
        conexion.execute(_SQL_MEDIO.format(nombre="medio"))
    elif "inglés" not in actual["sql"]:
        # SQLite no permite cambiar un CHECK: se recrea la tabla conservando los datos.
        conexion.execute(_SQL_MEDIO.format(nombre="medio_nuevo"))
        conexion.execute(
            """INSERT INTO medio_nuevo(id, carta_id, tipo, nombre_original, extension, mime, contenido, actualizado_en)
               SELECT id, carta_id, tipo, nombre_original, extension, mime, contenido, actualizado_en FROM medio"""
        )
        conexion.execute("DROP TABLE medio")
        conexion.execute("ALTER TABLE medio_nuevo RENAME TO medio")
        conexion.commit()
        conexion.execute("VACUUM")  # recupera el espacio de la tabla anterior
    conexion.commit()


def _guardar_bytes(conexion: sqlite3.Connection, carta_id: int, tipo: str, archivo: Path, manual: bool) -> None:
    mime = mimetypes.guess_type(archivo.name)[0] or "application/octet-stream"
    conexion.execute(
        """INSERT INTO medio(carta_id, tipo, nombre_original, extension, mime, contenido, manual)
           VALUES (?, ?, ?, ?, ?, ?, ?)
           ON CONFLICT(carta_id, tipo) DO UPDATE SET
             nombre_original=excluded.nombre_original, extension=excluded.extension,
             mime=excluded.mime, contenido=excluded.contenido, manual=excluded.manual,
             actualizado_en=CURRENT_TIMESTAMP""",
        (carta_id, tipo, archivo.name, archivo.suffix.lower(), mime, archivo.read_bytes(), int(manual)),
    )


def importar_archivos(conexion: sqlite3.Connection) -> dict[str, int]:
    """Carga/actualiza todos los recursos locales como BLOBs en SQLite."""
    crear_esquema(conexion)
    totales = dict.fromkeys(TIPOS, 0)
    for tipo, carpeta in FUENTES.items():
        if not carpeta.exists():
            continue
        archivos = [a for a in carpeta.iterdir() if a.is_file()]
        # Elimina medios cuyo archivo de origen ya no existe (los cargados a mano se respetan).
        nombres = {a.name for a in archivos}
        for fila in conexion.execute(
            "SELECT id, nombre_original FROM medio WHERE tipo = ? AND manual = 0", (tipo,)
        ).fetchall():
            if fila["nombre_original"] not in nombres:
                conexion.execute("DELETE FROM medio WHERE id = ?", (fila["id"],))
        for archivo in archivos:
            # Un archivo ya importado conserva su carta aunque ésta se haya renombrado.
            previo = conexion.execute(
                "SELECT carta_id FROM medio WHERE tipo = ? AND nombre_original = ?",
                (tipo, archivo.name),
            ).fetchone()
            if previo:
                carta_id = previo[0]
            else:
                nombre = nombre_canonico(archivo.name)
                conexion.execute("INSERT OR IGNORE INTO carta(nombre) VALUES (?)", (nombre,))
                carta_id = conexion.execute(
                    "SELECT id FROM carta WHERE nombre = ? COLLATE NOCASE", (nombre,)
                ).fetchone()[0]
            _guardar_bytes(conexion, carta_id, tipo, archivo, manual=False)
            totales[tipo] += 1
    conexion.execute("DELETE FROM carta WHERE id NOT IN (SELECT carta_id FROM medio)")
    conexion.commit()
    return totales


def resumen(conexion: sqlite3.Connection) -> list[sqlite3.Row]:
    return conexion.execute(
        """SELECT c.id, c.nombre, c.mazahua, c.ingles, c.uid_rfid,
                  MAX(m.tipo = 'imagen') AS tiene_imagen,
                  MAX(m.tipo = 'español') AS tiene_espanol,
                  MAX(m.tipo = 'mazahua') AS tiene_mazahua,
                  MAX(m.tipo = 'inglés') AS tiene_ingles
           FROM carta c LEFT JOIN medio m ON m.carta_id = c.id
           GROUP BY c.id ORDER BY c.nombre COLLATE NOCASE"""
    ).fetchall()


def obtener_carta(conexion: sqlite3.Connection, carta_id: int) -> sqlite3.Row | None:
    return conexion.execute("SELECT * FROM carta WHERE id = ?", (carta_id,)).fetchone()


def obtener_medio(conexion: sqlite3.Connection, carta_id: int, tipo: str):
    return conexion.execute(
        "SELECT * FROM medio WHERE carta_id = ? AND tipo = ?", (carta_id, tipo)
    ).fetchone()


def guardar_textos(conexion: sqlite3.Connection, carta_id: int, nombre: str, mazahua: str, ingles: str) -> None:
    """Guarda la palabra en español (nombre de la carta), mazahua e inglés."""
    nombre = nombre.strip()
    if not nombre:
        raise ValueError("El nombre en español no puede estar vacío.")
    try:
        conexion.execute(
            "UPDATE carta SET nombre = ?, mazahua = ?, ingles = ? WHERE id = ?",
            (nombre, mazahua.strip(), ingles.strip(), carta_id),
        )
    except sqlite3.IntegrityError:
        raise ValueError(f"Ya existe otra carta llamada «{nombre}».") from None
    conexion.commit()


def cargar_medio(conexion: sqlite3.Connection, carta_id: int, tipo: str, archivo: Path | str) -> None:
    """Sustituye la imagen o el audio de un idioma con un archivo elegido por el usuario."""
    archivo = Path(archivo)
    familia = "imagen" if tipo == "imagen" else "audio"
    if tipo not in TIPOS:
        raise ValueError(f"Tipo de medio desconocido: {tipo}")
    if archivo.suffix.lower() not in EXTENSIONES[familia]:
        permitidas = ", ".join(sorted(EXTENSIONES[familia]))
        raise ValueError(f"Formato {archivo.suffix or 'sin extensión'} no admitido. Usa: {permitidas}")
    _guardar_bytes(conexion, carta_id, tipo, archivo, manual=True)
    conexion.commit()


def normalizar_uid(uid: str) -> str:
    """'04:a3-bc 1F' -> '04A3BC1F': mayúsculas y sin separadores."""
    limpio = "".join(c for c in uid.upper() if c.isalnum())
    if not limpio:
        raise ValueError("El UID no puede estar vacío.")
    return limpio


def carta_por_uid(conexion: sqlite3.Connection, uid: str) -> sqlite3.Row | None:
    return conexion.execute("SELECT * FROM carta WHERE uid_rfid = ?", (normalizar_uid(uid),)).fetchone()


def asignar_uid(conexion: sqlite3.Connection, carta_id: int, uid: str | None) -> None:
    """Liga una tarjeta RFID a la carta (``uid=None`` la desliga).

    Nunca duplica: si la tarjeta ya pertenece a otra carta, lanza ValueError.
    """
    uid = normalizar_uid(uid) if uid else None
    if uid:
        duena = carta_por_uid(conexion, uid)
        if duena and duena["id"] != carta_id:
            raise ValueError(f"La tarjeta {uid} ya está asignada a «{duena['nombre']}». Quítala de esa carta primero.")
    conexion.execute("UPDATE carta SET uid_rfid = ? WHERE id = ?", (uid, carta_id))
    conexion.commit()


def carta_por_palabra(conexion: sqlite3.Connection, palabra: str) -> sqlite3.Row | None:
    """Busca la carta cuya palabra (español, mazahua o inglés) coincide, sin importar tildes ni alias."""
    objetivo = clave(nombre_canonico(f"{palabra}.x"))  # nombre_canonico espera un nombre de archivo
    if not objetivo:
        return None
    cartas = conexion.execute("SELECT * FROM carta").fetchall()
    for campo in ("nombre", "mazahua", "ingles"):  # el español tiene prioridad
        for carta in cartas:
            if carta[campo] and clave(carta[campo]) == objetivo:
                return carta
    return None


def emparejar_lectura(conexion: sqlite3.Connection, uid: str, palabras: list[str]) -> tuple[sqlite3.Row | None, str]:
    """Decide qué hacer con una tarjeta leída. ``palabras`` son los textos grabados en ella (ES, MZ, EN).

    Estados devueltos junto con la carta:
      - ``"valida"``   el UID ya está en la base y coincide con la palabra (o la tarjeta no trae palabra).
      - ``"distinta"`` el UID pertenece a una carta, pero la tarjeta dice otra palabra (se usa la base).
      - ``"asociada"`` el UID era nuevo y la palabra existía sin tarjeta: se asoció automáticamente.
      - ``"ocupada"``  el UID es nuevo, pero la carta de esa palabra ya tiene otra tarjeta (no se cambia).
      - ``"nueva"``    ni el UID ni la palabra están en la base (carta = None).
    """
    uid = normalizar_uid(uid)
    por_palabra = next((c for c in (carta_por_palabra(conexion, p) for p in palabras if p) if c), None)
    por_uid = carta_por_uid(conexion, uid)
    if por_uid:
        if por_palabra and por_palabra["id"] != por_uid["id"]:
            return por_uid, "distinta"
        return por_uid, "valida"
    if por_palabra is None:
        return None, "nueva"
    if por_palabra["uid_rfid"]:
        return por_palabra, "ocupada"
    asignar_uid(conexion, por_palabra["id"], uid)
    return obtener_carta(conexion, por_palabra["id"]), "asociada"
