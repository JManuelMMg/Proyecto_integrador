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

### Modo Juego · Tarjetas
Tercer modo de la barra superior. Oculta la lista y la edición y muestra solo la tarjeta en grande. Si el ESP32 está enchufado, conecta el lector solo.

- Al pasar una tarjeta aparecen su imagen y sus palabras, y los audios suenan **solos uno tras otro: mazahua → español → inglés** (los que existan). El idioma que está sonando se resalta con su color.
- Cada audio **se detiene solo** al terminar: el reproductor se libera y empieza el siguiente tras una pausa breve. **Detener** corta la secuencia. Los botones **Escuchar** o las teclas 1, 2 y 3 repiten un idioma.

### El UID siempre queda en la base
- **Historial:** cada tarjeta que pasa por el lector se guarda en la tabla `lectura` (UID, carta, resultado, palabra grabada y fecha), aunque no esté ligada a ninguna carta.
- **Cartas nuevas:** si la tarjeta trae una palabra en español que no existe en la base, se **crea la carta** con sus palabras y su UID. Luego, en *Edición*, se le cargan imagen y audios. **Importar recursos** ya no borra las cartas que tienen tarjeta aunque todavía no tengan archivos.

### Emparejamiento automático
Pulsa **Conectar lector** y pasa tarjetas. La app compara el UID y la palabra grabada en la tarjeta (bloques ES/EN/MZ) con la base:

| Situación | Qué hace |
|---|---|
| El UID ya está ligado y la palabra coincide (o la tarjeta no trae palabra) | Muestra la carta y reproduce su audio. |
| El UID es nuevo y la palabra existe en una carta **sin tarjeta** | **Asocia el UID automáticamente** y muestra la carta. |
| El UID es nuevo, pero esa carta ya tiene otra tarjeta | Avisa y no cambia nada. |
| El UID es de una carta pero la tarjeta dice otra palabra | Avisa y usa lo que dice la base. |
| Ni el UID ni la palabra existen | Crea la carta con las palabras de la tarjeta y su UID. Si la tarjeta no trae palabra, solo queda en el historial y se asigna a mano en *Edición*. |

La palabra se compara sin tildes ni mayúsculas, con los alias del catálogo (`banana` → `plátano`) y también contra las palabras en mazahua e inglés.

### Grabar tarjetas
El mismo sketch del lector (`loteria_mazahua_lector.ino`) también graba: ya no hace falta cambiar de sketch.

- **Desde la app:** en *Media superior · Edición*, selecciona la carta y pulsa **Grabar tarjeta**. Acerca una tarjeta en los siguientes 15 s: el ESP32 escribe español, inglés y mazahua, lo verifica leyéndolo y la tarjeta queda ligada a la carta. Si esa tarjeta era de otra carta, se pasa a esta.
- **Por lotes:** `python grabar_tarjetas.py` recorre las cartas sin tarjeta y pide una por una (Enter = grabar, `s` = saltar, `q` = salir). También `python grabar_tarjetas.py gato perro` o `--todas`.
- Cada texto ocupa un bloque de 16 bytes; las palabras más largas se recortan (se avisa) sin partir letras con acento.

### ESP32: RC522 + Micro SD (`loteria_mazahua_lector/`)
- **Diagnóstico al arrancar:** lee el registro de versión del RC522 y reporta `ESTADO:RC522=OK` o `ERROR:RC522=SIN_RESPUESTA`. La app muestra estos avisos en la barra de estado.
- **Robustez:** el bucle no bloquea; ignora rebotes de la misma tarjeta (2 s); siempre libera la tarjeta aunque se retire a medias; cada 5 s comprueba que el RC522 siga respondiendo y lo reinicia solo tras un micro-corte.
- **Micro SD:** comparte el bus SPI con el RC522 (CS 21 para el RC522, CS 4 para la SD; ambos en alto al iniciar). Ningún pin usa la flash (GPIO 6-11) ni los pines de arranque (0, 2, 5, 12, 15); el sketch no compila si alguien los pone por error. Si el módulo SD bloquea el bus, activa `SD_BUS_SEPARADO` (HSPI). Por cada lectura informa qué archivos hay (`SD:IMG=1,ES=1,MZ=0,EN=0`) y la anota en `/loteria/lecturas.csv`.
- **Comandos por Serial:** `PING`, `ESTADO`, `SD_INIT`, `SD_LS /loteria/img`, `SD_BUSCAR gato`.
- **Preparar la SD desde la base:** `python exportar_sd.py E:\` copia imágenes y audios con la estructura `/loteria/img/gato.png`, `/loteria/audio/{es,mz,en}/gato.mp3`.

Requiere las librerías **MFRC522** (miguelbalboa) y el core **ESP32** de Arduino; `SD` y `SPI` vienen con el core.
