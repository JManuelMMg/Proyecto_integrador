# Lotería Mazahua · Aplicación de escritorio

Aplicación nativa de escritorio para consultar las cartas de lotería con su palabra y su audio en **español, mazahua e inglés**. Está hecha con Python y Tkinter, por lo que **no utiliza Node.js ni npm**. Incluye modo **Primaria** y modo **Media superior · Edición**. Tiene temas claro y oscuro, buscador, indicadores de cobertura por idioma y una imagen que se adapta al tamaño de la ventana.

### Uso
- Elige una carta en la lista (o búscala en cualquiera de los tres idiomas). Con los botones **Escuchar** o las teclas **1** (español), **2** (mazahua) y **3** (inglés) se reproduce su audio. La barra espaciadora reproduce el mazahua.
- En **Media superior · Edición**, cada idioma muestra un campo para escribir la palabra y un botón **Cargar audio…**. **Guardar palabras** (o Enter) guarda los textos; **Cambiar imagen…** sustituye la imagen. Todo se guarda en SQLite.
- Los audios en inglés también se pueden dejar en la carpeta `audios_ingles/`, **nombrados con la palabra en español** (`gato.mp3`), y pulsar **Importar recursos**.

## Ejecutar

En Windows, desde esta carpeta:

```powershell
python app_loteria.py
```

La primera apertura importa automáticamente las imágenes y audios a `loteria_mazahua.sqlite3`. Después, todo el catálogo multimedia se consulta desde SQLite, no desde las carpetas de origen. El botón **Importar recursos a SQLite** actualiza la base cuando se agreguen o sustituyan archivos. Los audios MP3 y MP4 se escuchan directamente dentro de la aplicación con `ffpyplayer`; no se abre un reproductor externo. Cada reproducción toma su duración desde los metadatos del archivo, muestra una barra de avance y se detiene automáticamente al finalizar.

En otro equipo instala las dependencias (`ffpyplayer` para el audio, `Pillow` para las imágenes y `pyserial` para el lector) antes de ejecutar: `python -m pip install -r requirements.txt`.

## Diseño de la base de datos

- `carta`: una carta por nombre canónico (la palabra en español), más las palabras `mazahua` e `ingles`.
- `medio`: almacena cada imagen o audio (`imagen`, `español`, `mazahua`, `inglés`) en la columna `contenido` como un BLOB, junto a tipo MIME y extensión. `manual = 1` marca lo cargado desde la aplicación, que **Importar recursos** no borra.

Las bases creadas con versiones anteriores se actualizan solas al abrir la aplicación, sin perder datos.

Las diferencias conocidas se unifican al importar: `temascal`/`temazcal`, `puerco`/`cerdo`, `chapilín`/`saltamontes`, `banana`/`plátano`, tildes y el error `naaranja`. Los nombres originales se conservan en `medio.nombre_original`; los archivos de origen no se borran ni se alteran.

Para escuchar un audio, la aplicación extrae temporalmente el BLOB para el motor interno y lo elimina al detenerse o cerrar la aplicación. La copia oficial permanece en SQLite.

## Tarjetas RFID

Todo vive en **una sola base**, `loteria_mazahua.sqlite3`: cada carta puede tener la tarjeta física ligada en `carta.uid_rfid` (única: una tarjeta no puede pertenecer a dos cartas).

- **Asignar una tarjeta:** en *Media superior · Edición*, selecciona la carta, pulsa **Asignar tarjeta** y pasa la tarjeta por el lector. Si esa tarjeta ya pertenece a otra carta, la app avisa y no la duplica. **Quitar** la desliga. Sin lector conectado, la app pide escribir el UID.
- **Jugar:** pulsa **Conectar lector**. Al pasar una tarjeta, la app muestra su carta (imagen y palabras en los tres idiomas) y reproduce el audio en mazahua (o en español/inglés si no lo hay).
- `lector_rfid.py` solo lee el ESP32 por el puerto serie (`CARD:UID|ES:..|EN:..|MZ:..`); toda la información sale de la base.
