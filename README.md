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

### Emparejamiento automático
Pulsa **Conectar lector** y pasa tarjetas. La app compara el UID y la palabra grabada en la tarjeta (bloques ES/EN/MZ) con la base:

| Situación | Qué hace |
|---|---|
| El UID ya está ligado y la palabra coincide (o la tarjeta no trae palabra) | Muestra la carta y reproduce su audio. |
| El UID es nuevo y la palabra existe en una carta **sin tarjeta** | **Asocia el UID automáticamente** y muestra la carta. |
| El UID es nuevo, pero esa carta ya tiene otra tarjeta | Avisa y no cambia nada. |
| El UID es de una carta pero la tarjeta dice otra palabra | Avisa y usa lo que dice la base. |
| Ni el UID ni la palabra existen | Avisa: asígnala a mano en *Edición* con **Asignar tarjeta**. |

La palabra se compara sin tildes ni mayúsculas, con los alias del catálogo (`banana` → `plátano`) y también contra las palabras en mazahua e inglés.

### ESP32: RC522 + Micro SD (`loteria_mazahua_lector/`)
- **Diagnóstico al arrancar:** lee el registro de versión del RC522 y reporta `ESTADO:RC522=OK` o `ERROR:RC522=SIN_RESPUESTA`. La app muestra estos avisos en la barra de estado.
- **Robustez:** el bucle no bloquea; ignora rebotes de la misma tarjeta (2 s); siempre libera la tarjeta aunque se retire a medias; cada 5 s comprueba que el RC522 siga respondiendo y lo reinicia solo tras un micro-corte.
- **Micro SD:** comparte el bus SPI con el RC522 (CS 5 para el RC522, CS 4 para la SD; ambos en alto al iniciar). Si el módulo SD bloquea el bus, activa `SD_BUS_SEPARADO` (HSPI). Por cada lectura informa qué archivos hay (`SD:IMG=1,ES=1,MZ=0,EN=0`) y la anota en `/loteria/lecturas.csv`.
- **Comandos por Serial:** `PING`, `ESTADO`, `SD_INIT`, `SD_LS /loteria/img`, `SD_BUSCAR gato`.
- **Preparar la SD desde la base:** `python exportar_sd.py E:\` copia imágenes y audios con la estructura `/loteria/img/gato.png`, `/loteria/audio/{es,mz,en}/gato.mp3`.

Requiere las librerías **MFRC522** (miguelbalboa) y el core **ESP32** de Arduino; `SD` y `SPI` vienen con el core.
