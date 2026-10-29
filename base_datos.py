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
    # Los audios recibidos están dentro de esta subcarpeta. Sus nombres pueden
    # contener ambos idiomas (por ejemplo ``gato_cat.mp3``).
    "inglés": RAIZ / "audios_ingles" / "audios_ingles",
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
               manual INTEGER NOT NULL DEFAULT 0,  -- creada desde la interfaz
               creado_en TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
           )"""
    )
    # Migración de bases anteriores: palabras en mazahua/inglés.
    columnas = {fila["name"] for fila in conexion.execute("PRAGMA table_info(carta)")}
    for columna in ("mazahua", "ingles", "manual"):
        if columna not in columnas:
            if columna == "manual":
                conexion.execute("ALTER TABLE carta ADD COLUMN manual INTEGER NOT NULL DEFAULT 0")
            else:
                conexion.execute(f"ALTER TABLE carta ADD COLUMN {columna} TEXT NOT NULL DEFAULT ''")
    if "uid_rfid" not in columnas:
        conexion.execute("ALTER TABLE carta ADD COLUMN uid_rfid TEXT")
    # Una tarjeta solo puede pertenecer a una carta (varias cartas pueden no tener tarjeta).
    conexion.execute("CREATE UNIQUE INDEX IF NOT EXISTS carta_uid_rfid ON carta(uid_rfid)")
    # Historial: cada tarjeta que pasa por el lector queda guardada, aunque no esté ligada a ninguna carta.
    conexion.execute(
        """CREATE TABLE IF NOT EXISTS lectura (
               id INTEGER PRIMARY KEY,
               uid_rfid TEXT NOT NULL,
               carta_id INTEGER REFERENCES carta(id) ON DELETE SET NULL,
               estado TEXT NOT NULL,
               palabra TEXT NOT NULL DEFAULT '',
               leida_en TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
           )"""
    )
    conexion.execute("CREATE INDEX IF NOT EXISTS lectura_uid ON lectura(uid_rfid)")
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


# Mapeo de nombres de archivos en inglés a nombres canónicos en español
MAPEO_INGLES = {
    "Almohada — Pillow.mp3": "almohada",
    "Cobija — Blanket.mp3": "cobija",
    "Cuchara — Spoon.mp3": "cuchara",
    "Cuchillo — Knife.mp3": "cuchillo",
    "Espejo — Mirror.mp3": "espejo",
    "Mesa — Table.mp3": "mesa",
    "Puerta — Door.mp3": "puerta",
    "Refrigerador — fridge.mp3": "refrigerador",
    "Silla — Chair.mp3": "silla",
    "Tenedor — Fork.mp3": "tenedor",
    "Ventana — Window.mp3": "ventana",
    "aguacate-avocado.mp3": "aguacate",
    "banana.mp3": "plátano",
    "blue.mp3": "azul",
    "bosque-forest.mp3": "bosque",
    "brother.mp3": "hermano",
    "cama-bed.mp3": "cama",
    "cempasuchil-marigold.mp3": "cempasúchil",
    "chamarra-jacket.mp3": "chamarra",
    "chapulin-grasshoper.mp3": "chapulín",
    "chayote-squash.mp3": "chayote",
    "chili peper.mp3": "chile",
    "corazon-heart.mp3": "corazón",
    "cuervo-raven.mp3": "cuervo",
    "dad.mp3": "papá",
    "escalera-ladder.mp3": "escalera",
    "espinaca-spinach.mp3": "espinaca",
    "flower.mp3": "flor",
    "fresa-strawberry.mp3": "fresa",
    "gallina-hen.mp3": "gallina",
    "gallo-rooster.mp3": "gallo",
    "gato_cat.mp3": "gato",
    "guajolote-turkey.mp3": "guajolote",
    "jitomate-tomato.mp3": "jitomate",
    "lagartija-lizard.mp3": "lagartija",
    "lapiz-pencil.mp3": "lápiz",
    "lluvia-rain.mp3": "lluvia",
    "mano-hand.mp3": "mano",
    "mom.mp3": "mamá",
    "moon.mp3": "luna",
    "notebook.mp3": "cuaderno",
    "ojo-eye.mp3": "ojo",
    "orange.mp3": "naranja",
    "paloma-pigeon.mp3": "paloma",
    "pato-duck.mp3": "pato",
    "perro-dog.mp3": "perro",
    "pig.mp3": "cerdo",
    "rana-frog.mp3": "rana",
    "raton-mouse.mp3": "ratón",
    "rio-river.mp3": "río",
    "sol-sun.mp3": "sol",
    "spider.mp3": "araña",
    "star.mp3": "estrella",
    "teacher.mp3": "maestro",
    "temazcal.mp3": "temazcal",
    "water.mp3": "agua",
    "watermelon.mp3": "sandía",
    "zorrillo-skunk.mp3": "zorrillo",
}


def _nombre_de_archivo(tipo: str, archivo: Path) -> str:
    """Devuelve el nombre canónico de la carta para un archivo de origen."""
    if tipo == "inglés":
        # Los audios en inglés no siguen todos el mismo patrón de nombre.
        # El mapeo conserva una asociación explícita y segura con la carta.
        return MAPEO_INGLES.get(archivo.name, nombre_canonico(archivo.name))
    return nombre_canonico(archivo.name)


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
                nombre = _nombre_de_archivo(tipo, archivo)
                conexion.execute("INSERT OR IGNORE INTO carta(nombre) VALUES (?)", (nombre,))
                carta_id = conexion.execute(
                    "SELECT id FROM carta WHERE nombre = ? COLLATE NOCASE", (nombre,)
                ).fetchone()[0]
            _guardar_bytes(conexion, carta_id, tipo, archivo, manual=False)
            totales[tipo] += 1
    conexion.execute(
        "DELETE FROM carta WHERE uid_rfid IS NULL AND manual = 0 "
        "AND id NOT IN (SELECT carta_id FROM medio)"
    )
    conexion.commit()
    return totales


def importar_audios_ingles(conexion: sqlite3.Connection) -> int:
    """Importa o actualiza únicamente los audios en inglés disponibles."""
    crear_esquema(conexion)
    carpeta = FUENTES["inglés"]
    if not carpeta.exists():
        return 0

    total = 0
    for archivo in carpeta.iterdir():
        if not archivo.is_file() or archivo.suffix.lower() not in EXTENSIONES["audio"]:
            continue
        previo = conexion.execute(
            "SELECT carta_id FROM medio WHERE tipo = ? AND nombre_original = ?",
            ("inglés", archivo.name),
        ).fetchone()
        if previo:
            carta_id = previo["carta_id"]
        else:
            nombre = _nombre_de_archivo("inglés", archivo)
            conexion.execute("INSERT OR IGNORE INTO carta(nombre) VALUES (?)", (nombre,))
            carta_id = conexion.execute(
                "SELECT id FROM carta WHERE nombre = ? COLLATE NOCASE", (nombre,)
            ).fetchone()["id"]
        _guardar_bytes(conexion, carta_id, "inglés", archivo, manual=False)
        total += 1
    conexion.commit()
    return total


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


def crear_carta(conexion: sqlite3.Connection, nombre: str) -> int:
    """Crea una carta vacía desde la interfaz, lista para cargar sus recursos."""
    nombre = nombre.strip()
    if not nombre:
        raise ValueError("Escribe primero la palabra en español.")
    try:
        cursor = conexion.execute("INSERT INTO carta(nombre, manual) VALUES (?, 1)", (nombre,))
    except sqlite3.IntegrityError:
        raise ValueError(f"Ya existe una carta llamada «{nombre}».") from None
    conexion.commit()
    return cursor.lastrowid


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


def reasignar_uid(conexion: sqlite3.Connection, carta_id: int, uid: str) -> str | None:
    """Liga la tarjeta a la carta aunque perteneciera a otra (se acaba de regrabar físicamente).

    Devuelve el nombre de la carta que la tenía antes, o None.
    """
    anterior = carta_por_uid(conexion, uid)
    if anterior and anterior["id"] != carta_id:
        conexion.execute("UPDATE carta SET uid_rfid = NULL WHERE id = ?", (anterior["id"],))
    conexion.execute("UPDATE carta SET uid_rfid = NULL WHERE id = ?", (carta_id,))  # suelta su tarjeta previa
    asignar_uid(conexion, carta_id, uid)
    return anterior["nombre"] if anterior and anterior["id"] != carta_id else None


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


def eliminar_carta(conexion: sqlite3.Connection, carta_id: int) -> None:
    """Elimina una carta y todos sus medios asociados de la base de datos."""
    conexion.execute("DELETE FROM carta WHERE id = ?", (carta_id,))
    conexion.commit()


def registrar_lectura(conexion: sqlite3.Connection, uid: str, carta_id: int | None, estado: str, palabra: str) -> None:
    conexion.execute(
        "INSERT INTO lectura(uid_rfid, carta_id, estado, palabra) VALUES (?, ?, ?, ?)",
        (normalizar_uid(uid), carta_id, estado, palabra),
    )
    conexion.commit()


def emparejar_lectura(conexion: sqlite3.Connection, uid: str, palabras: list[str]) -> tuple[sqlite3.Row | None, str]:
    """Empareja la tarjeta con la base y deja la lectura registrada en la tabla ``lectura``."""
    carta, estado = _emparejar(conexion, uid, palabras)
    registrar_lectura(conexion, uid, carta["id"] if carta else None, estado, next((p for p in palabras if p), ""))
    return carta, estado


def _emparejar(conexion: sqlite3.Connection, uid: str, palabras: list[str]) -> tuple[sqlite3.Row | None, str]:
    """Decide qué hacer con una tarjeta leída. ``palabras`` son los textos grabados en ella (ES, MZ, EN).

    Estados devueltos junto con la carta:
      - ``"valida"``   el UID ya está en la base y coincide con la palabra (o la tarjeta no trae palabra).
      - ``"distinta"`` el UID pertenece a una carta, pero la tarjeta dice otra palabra (se usa la base).
      - ``"asociada"`` el UID era nuevo y la palabra existía sin tarjeta: se asoció automáticamente.
      - ``"ocupada"``  el UID es nuevo, pero la carta de esa palabra ya tiene otra tarjeta (no se cambia).
      - ``"creada"``   ni el UID ni la palabra estaban: se creó la carta con los textos de la tarjeta.
      - ``"nueva"``    UID desconocido y la tarjeta no trae palabra en español (carta = None).
    """
    uid = normalizar_uid(uid)
    por_palabra = next((c for c in (carta_por_palabra(conexion, p) for p in palabras if p) if c), None)
    por_uid = carta_por_uid(conexion, uid)
    if por_uid:
        if por_palabra and por_palabra["id"] != por_uid["id"]:
            return por_uid, "distinta"
        return por_uid, "valida"
    if por_palabra is None:
        espanol, mazahua, ingles = (list(palabras) + ["", "", ""])[:3]
        if not espanol:
            return None, "nueva"
        nombre = nombre_canonico(f"{espanol}.x")
        cursor = conexion.execute(
            "INSERT INTO carta(nombre, mazahua, ingles, uid_rfid) VALUES (?, ?, ?, ?)", (nombre, mazahua, ingles, uid)
        )
        conexion.commit()
        return obtener_carta(conexion, cursor.lastrowid), "creada"
    if por_palabra["uid_rfid"]:
        return por_palabra, "ocupada"
    asignar_uid(conexion, por_palabra["id"], uid)
    return obtener_carta(conexion, por_palabra["id"]), "asociada"
