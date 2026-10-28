/*
  Lotería Mazahua · Lector RFID + Micro SD (ESP32)

  Protocolo por Serial (115200 baudios), una línea por evento:
    LECTOR_LISTO
    ESTADO:RC522=OK|VERSION=0x92
    ERROR:RC522=SIN_RESPUESTA|VERSION=0x00|DETALLE=...
    ESTADO:SD=OK|TIPO=SDHC|MB=7580          (o ERROR:SD=NO_DETECTADA)
    CARD:<UID>|ES:<texto>|EN:<texto>|MZ:<texto>|SD:IMG=1,ES=1,MZ=0,EN=0

  Comandos que acepta desde la PC (terminados en salto de línea):
    PING            -> PONG
    ESTADO          -> vuelve a diagnosticar RC522 y SD
    SD_INIT         -> reintenta montar la Micro SD
    SD_LS <ruta>    -> lista una carpeta de la SD
    SD_BUSCAR <pal> -> indica qué archivos multimedia hay para una palabra
    GRABAR ES=<t>|EN=<t>|MZ=<t>
                    -> espera 15 s la siguiente tarjeta, graba los tres textos y los verifica:
                       GRABAR_ESPERANDO, luego GRABADO:<UID>|ES:..|EN:..|MZ:..
                       o ERROR:GRABAR=<motivo>|UID=<UID>  (TIEMPO_AGOTADO, AUTENTICACION,
                       ESCRITURA, VERIFICACION, RC522)
    CANCELAR        -> cancela un GRABAR pendiente (GRABAR_CANCELADO)
    Cada texto ocupa un bloque de 16 bytes: se recorta sin partir letras con acento.

  Cableado (bus SPI compartido, un CS por dispositivo):
    Señal   ESP32   RC522   Micro SD
    SCK     18      SCK     SCK
    MISO    19      MISO    MISO
    MOSI    23      MOSI    MOSI
    CS      21      SDA     -
    CS      4       -       CS
    RST     22      RST     -
    Alim.           3.3V    VCC según el módulo (muchos piden 5V)

  Pines que NO se usan a propósito:
    GPIO 6-11          conectados a la memoria flash interna: tocarlos corrompe el arranque.
    GPIO 0, 2, 5, 12, 15  pines de arranque (strapping): un módulo conectado puede impedir
                       que el ESP32 arranque. El GPIO 12 en alto pone la flash a 1.8 V y
                       produce "invalid magic number" / reinicios en bucle.
    GPIO 16, 17        reservados para la PSRAM en placas WROVER.
    GPIO 34-39         solo entrada (no sirven para SCK, MOSI ni CS).

  Si el RC522 deja de responder al conectar la SD, el módulo SD no libera MISO
  (defecto común en módulos baratos). Activa SD_BUS_SEPARADO para darle a la SD
  su propio bus: SCK 25, MISO 26, MOSI 27, CS 33.

  Estructura esperada en la Micro SD (nombres en minúsculas, sin acentos):
    /loteria/img/gato.png          (o .jpg)
    /loteria/audio/es/gato.mp3
    /loteria/audio/mz/gato.mp3
    /loteria/audio/en/gato.mp3
    /loteria/lecturas.csv          (lo crea el ESP32: registro de cada lectura)
*/
#include <SPI.h>
#include <SD.h>
#include <MFRC522.h>

// ===== Pines =====
#define SCK_PIN   18
#define MISO_PIN  19
#define MOSI_PIN  23
#define RC522_CS  21
#define RC522_RST 22
#define SD_CS      4

// #define SD_BUS_SEPARADO   // descomenta si la SD bloquea al RC522 en el bus compartido
#ifdef SD_BUS_SEPARADO
  #define SD_SCK  25
  #define SD_MISO 26
  #define SD_MOSI 27
  #undef  SD_CS
  #define SD_CS   33
  SPIClass spiSD(HSPI);
#endif

// Falla la compilación si algún pin cae en la flash, en un pin de arranque o en uno de solo entrada.
constexpr bool pinSeguro(int p, bool salida) {
  return !(p >= 6 && p <= 11) && p != 0 && p != 2 && p != 5 && p != 12 && p != 15 && !(salida && p >= 34);
}
static_assert(pinSeguro(SCK_PIN, true) && pinSeguro(MOSI_PIN, true) && pinSeguro(MISO_PIN, false), "Pin SPI inseguro");
static_assert(pinSeguro(RC522_CS, true) && pinSeguro(RC522_RST, true) && pinSeguro(SD_CS, true), "Pin CS/RST inseguro");
#ifdef SD_BUS_SEPARADO
static_assert(pinSeguro(SD_SCK, true) && pinSeguro(SD_MOSI, true) && pinSeguro(SD_MISO, false), "Pin SPI de la SD inseguro");
#endif

// ===== Bloques de la tarjeta (sector 1; el bloque 7 es el trailer y no se toca) =====
#define BLOQUE_ES 4
#define BLOQUE_EN 5
#define BLOQUE_MZ 6

// ===== Tiempos (ms) =====
const unsigned long REBOTE_MS        = 2000;   // ignora la misma tarjeta durante este tiempo
const unsigned long CHEQUEO_RC522_MS = 5000;   // revisa que el RC522 siga respondiendo
const unsigned long REINTENTO_MS     = 3000;   // reintento de arranque si el RC522 falla
const unsigned long ESPERA_GRABAR_MS = 15000;  // tiempo para acercar la tarjeta a grabar

MFRC522 rfid(RC522_CS, RC522_RST);
MFRC522::MIFARE_Key llave;

bool rc522Listo = false;
bool sdLista = false;
String ultimoUid = "";
unsigned long ultimoUidMs = 0;
unsigned long ultimoChequeoMs = 0;
String comando = "";

// Grabación pendiente (comando GRABAR): la siguiente tarjeta se escribe en vez de leerse.
bool grabando = false;
unsigned long grabarHastaMs = 0;
String grabarES, grabarEN, grabarMZ;

// ---------- Utilidades ----------
String uidComoTexto() {
  String uid = "";
  for (byte i = 0; i < rfid.uid.size; i++) {
    if (rfid.uid.uidByte[i] < 0x10) uid += "0";
    uid += String(rfid.uid.uidByte[i], HEX);
  }
  uid.toUpperCase();
  return uid;
}

// Quita separadores del protocolo para que un texto nunca rompa la línea.
String limpiar(const String &t) {
  String s = "";
  for (unsigned int i = 0; i < t.length(); i++) {
    char c = t[i];
    if (c != '|' && c != '\r' && c != '\n') s += c;
  }
  return s;
}

// "Plátano" -> "platano": nombre de archivo en la SD (minúsculas, sin acentos UTF-8).
String claveArchivo(const String &palabra) {
  String s = "";
  for (unsigned int i = 0; i < palabra.length(); i++) {
    byte c = palabra[i];
    if (c == 0xC3 && i + 1 < palabra.length()) {  // vocales acentuadas y ñ en UTF-8
      byte d = palabra[++i];
      if (d == 0xA1 || d == 0x81) s += 'a';
      else if (d == 0xA9 || d == 0x89) s += 'e';
      else if (d == 0xAD || d == 0x8D) s += 'i';
      else if (d == 0xB3 || d == 0x93) s += 'o';
      else if (d == 0xBA || d == 0x9A || d == 0xBC || d == 0x9C) s += 'u';
      else if (d == 0xB1 || d == 0x91) s += 'n';
    } else if (isalnum(c)) {
      s += (char)tolower(c);
    } else if (c == ' ' || c == '_' || c == '-') {
      s += '_';
    }
  }
  return s;
}

// Recorta a 16 bytes sin partir un carácter UTF-8 (acentos, ñ, ʉ…).
String recortar16(const String &t) {
  if (t.length() <= 16) return t;
  int corte = 16;
  while (corte > 0 && (((byte)t[corte]) & 0xC0) == 0x80) corte--;
  return t.substring(0, corte);
}

// ---------- Diagnóstico del RC522 ----------
// VersionReg devuelve 0x91/0x92 en chips originales y 0x88/0xB2/0x12 en clones.
// 0x00 o 0xFF significa que no hay comunicación SPI (cableado, alimentación o CS).
bool verificarRC522(bool informar) {
  byte version = rfid.PCD_ReadRegister(MFRC522::VersionReg);
  bool ok = version != 0x00 && version != 0xFF;
  if (informar || ok != rc522Listo) {
    Serial.print(ok ? "ESTADO:RC522=OK|VERSION=0x" : "ERROR:RC522=SIN_RESPUESTA|VERSION=0x");
    if (version < 0x10) Serial.print("0");
    Serial.print(version, HEX);
    if (!ok) Serial.print("|DETALLE=Revisa SCK/MISO/MOSI, SDA(CS)=21, RST=22 y alimentacion 3.3V");
    Serial.println();
  }
  return ok;
}

void iniciarRC522() {
  rfid.PCD_Init();
  delay(10);
  rc522Listo = verificarRC522(true);
  if (rc522Listo) rfid.PCD_SetAntennaGain(rfid.RxGain_max);  // mejor lectura a distancia
}

// ---------- Micro SD ----------
void iniciarSD() {
  SD.end();  // permite reintentar con SD_INIT sin reiniciar el ESP32
#ifdef SD_BUS_SEPARADO
  spiSD.begin(SD_SCK, SD_MISO, SD_MOSI, SD_CS);
  sdLista = SD.begin(SD_CS, spiSD, 4000000);
#else
  sdLista = SD.begin(SD_CS, SPI, 4000000);
#endif
  if (!sdLista || SD.cardType() == CARD_NONE) {
    sdLista = false;
    Serial.println("ERROR:SD=NO_DETECTADA|DETALLE=Revisa la tarjeta, el CS y que este en FAT32");
    return;
  }
  const char *tipo = SD.cardType() == CARD_SDHC ? "SDHC" : SD.cardType() == CARD_MMC ? "MMC" : "SD";
  Serial.printf("ESTADO:SD=OK|TIPO=%s|MB=%llu\n", tipo, SD.cardSize() / (1024ULL * 1024ULL));
  const char *carpetas[] = {"/loteria", "/loteria/img", "/loteria/audio", "/loteria/audio/es",
                            "/loteria/audio/mz", "/loteria/audio/en"};
  for (const char *c : carpetas) {
    if (!SD.exists(c)) SD.mkdir(c);
  }
}

bool existeConExtension(const String &base, const char *const *extensiones, byte n) {
  for (byte i = 0; i < n; i++) {
    if (SD.exists(base + extensiones[i])) return true;
  }
  return false;
}

// Devuelve "IMG=1,ES=1,MZ=0,EN=0" según los archivos que haya para la palabra.
String mediosEnSD(const String &palabra) {
  if (!sdLista || palabra.length() == 0) return "";
  static const char *const img[] = {".png", ".jpg"};
  static const char *const aud[] = {".mp3", ".wav", ".mp4"};
  String c = claveArchivo(palabra);
  String r = "IMG=";
  r += existeConExtension("/loteria/img/" + c, img, 2) ? "1" : "0";
  r += existeConExtension("/loteria/audio/es/" + c, aud, 3) ? ",ES=1" : ",ES=0";
  r += existeConExtension("/loteria/audio/mz/" + c, aud, 3) ? ",MZ=1" : ",MZ=0";
  r += existeConExtension("/loteria/audio/en/" + c, aud, 3) ? ",EN=1" : ",EN=0";
  return r;
}

void registrarLectura(const String &uid, const String &es) {
  if (!sdLista) return;
  File f = SD.open("/loteria/lecturas.csv", FILE_APPEND);
  if (!f) {  // la SD se retiró en caliente
    sdLista = false;
    Serial.println("ERROR:SD=ESCRITURA_FALLIDA|DETALLE=Usa SD_INIT al volver a insertarla");
    return;
  }
  f.printf("%lu,%s,%s\n", millis(), uid.c_str(), es.c_str());
  f.close();
}

void listarSD(String ruta) {
  ruta.trim();
  if (!sdLista) { Serial.println("ERROR:SD=NO_DETECTADA"); return; }
  if (ruta.length() == 0) ruta = "/loteria";
  File dir = SD.open(ruta);
  if (!dir || !dir.isDirectory()) { Serial.println("ERROR:SD=RUTA_INVALIDA|RUTA=" + ruta); return; }
  for (File f = dir.openNextFile(); f; f = dir.openNextFile()) {
    Serial.printf("SD_ARCHIVO:%s|BYTES=%u%s\n", f.name(), (unsigned)f.size(), f.isDirectory() ? "|DIR" : "");
    f.close();
  }
  dir.close();
  Serial.println("SD_FIN");
}

// ---------- Lectura de la tarjeta ----------
// Lee los tres textos del sector 1 con una sola autenticación. Si algo falla
// (tarjeta retirada a medias, tarjeta no MIFARE Classic) deja los textos vacíos,
// pero el UID siempre se reporta.
bool autenticarSector() {
  return rfid.PCD_Authenticate(MFRC522::PICC_CMD_MF_AUTH_KEY_A, BLOQUE_ES, &llave, &(rfid.uid)) == MFRC522::STATUS_OK;
}

void leerTextos(String &es, String &en, String &mz, bool autenticar = true) {
  es = en = mz = "";
  if (autenticar && !autenticarSector()) return;
  const byte bloques[] = {BLOQUE_ES, BLOQUE_EN, BLOQUE_MZ};
  String *destinos[] = {&es, &en, &mz};
  for (byte b = 0; b < 3; b++) {
    byte buf[18];
    byte tam = sizeof(buf);
    if (rfid.MIFARE_Read(bloques[b], buf, &tam) != MFRC522::STATUS_OK) return;
    for (byte i = 0; i < 16 && buf[i] != 0; i++) *destinos[b] += (char)buf[i];
  }
}

// ---------- Escritura de la tarjeta ----------
bool escribirBloque(byte bloque, const String &texto) {
  byte datos[16];
  memset(datos, 0, sizeof(datos));
  for (unsigned int i = 0; i < texto.length() && i < 16; i++) datos[i] = (byte)texto[i];
  return rfid.MIFARE_Write(bloque, datos, 16) == MFRC522::STATUS_OK;
}

// Graba ES/EN/MZ en la tarjeta presente y lo verifica leyéndolo de nuevo.
void grabarTarjeta(const String &uid) {
  grabando = false;
  if (!autenticarSector()) {
    Serial.println("ERROR:GRABAR=AUTENTICACION|UID=" + uid);
    return;
  }
  if (!escribirBloque(BLOQUE_ES, grabarES) || !escribirBloque(BLOQUE_EN, grabarEN) || !escribirBloque(BLOQUE_MZ, grabarMZ)) {
    Serial.println("ERROR:GRABAR=ESCRITURA|UID=" + uid);
    return;
  }
  String es, en, mz;
  leerTextos(es, en, mz, false);  // la sesión sigue autenticada
  if (es != grabarES || en != grabarEN || mz != grabarMZ) {
    Serial.println("ERROR:GRABAR=VERIFICACION|UID=" + uid);
    return;
  }
  Serial.println("GRABADO:" + uid + "|ES:" + es + "|EN:" + en + "|MZ:" + mz);
}

// "GRABAR ES=gato|EN=cat|MZ=mits'i": guarda los textos y espera la tarjeta.
void prepararGrabacion(const String &datos) {
  if (!rc522Listo) { Serial.println("ERROR:GRABAR=RC522"); return; }
  grabarES = grabarEN = grabarMZ = "";
  int inicio = 0;
  while (inicio <= (int)datos.length()) {
    int fin = datos.indexOf('|', inicio);
    if (fin < 0) fin = datos.length();
    String campo = datos.substring(inicio, fin);
    String valor = recortar16(campo.substring(3));
    if (campo.startsWith("ES=")) grabarES = valor;
    else if (campo.startsWith("EN=")) grabarEN = valor;
    else if (campo.startsWith("MZ=")) grabarMZ = valor;
    inicio = fin + 1;
  }
  grabando = true;
  grabarHastaMs = millis() + ESPERA_GRABAR_MS;
  Serial.println("GRABAR_ESPERANDO");
}

void procesarTarjeta() {
  if (!rfid.PICC_IsNewCardPresent() || !rfid.PICC_ReadCardSerial()) return;
  String uid = uidComoTexto();
  unsigned long ahora = millis();
  bool repetida = uid == ultimoUid && ahora - ultimoUidMs < REBOTE_MS;
  if (grabando) {
    grabarTarjeta(uid);  // el rebote evita que la misma tarjeta se reporte como lectura justo después
  } else if (!repetida) {
    String es, en, mz;
    leerTextos(es, en, mz);
    Serial.print("CARD:" + uid + "|ES:" + limpiar(es) + "|EN:" + limpiar(en) + "|MZ:" + limpiar(mz));
    String sd = mediosEnSD(es);
    if (sd.length()) Serial.print("|SD:" + sd);
    Serial.println();
    registrarLectura(uid, limpiar(es));
  }
  ultimoUid = uid;
  ultimoUidMs = ahora;
  // Siempre se libera la tarjeta, incluso si la lectura falló: evita que el lector se quede "pegado".
  rfid.PICC_HaltA();
  rfid.PCD_StopCrypto1();
  ultimoChequeoMs = ahora;  // hubo comunicación: el RC522 está vivo
}

// ---------- Comandos desde la PC ----------
void ejecutarComando(String c) {
  c.trim();
  if (c == "PING") {
    Serial.println("PONG");
  } else if (c == "ESTADO") {
    rc522Listo = verificarRC522(true);
    Serial.println(sdLista ? "ESTADO:SD=OK" : "ERROR:SD=NO_DETECTADA");
  } else if (c == "SD_INIT") {
    iniciarSD();
  } else if (c.startsWith("SD_LS")) {
    listarSD(c.substring(5));
  } else if (c.startsWith("SD_BUSCAR ")) {
    String palabra = c.substring(10);
    Serial.println("SD_MEDIOS:" + claveArchivo(palabra) + "|" + (sdLista ? mediosEnSD(palabra) : String("SD=NO_DETECTADA")));
  } else if (c.startsWith("GRABAR ")) {
    prepararGrabacion(c.substring(7));
  } else if (c == "CANCELAR") {
    grabando = false;
    Serial.println("GRABAR_CANCELADO");
  } else if (c.length()) {
    Serial.println("ERROR:COMANDO_DESCONOCIDO|" + c);
  }
}

// Lectura no bloqueante: acumula caracteres hasta el salto de línea.
void atenderSerial() {
  while (Serial.available()) {
    char ch = Serial.read();
    if (ch == '\n' || ch == '\r') {
      if (comando.length()) ejecutarComando(comando);
      comando = "";
    } else if (comando.length() < 200) {
      comando += ch;
    }
  }
}

void setup() {
  Serial.begin(115200);
  delay(200);
  // Ambos CS en alto antes de iniciar nada: ningún dispositivo debe ocupar el bus.
  pinMode(RC522_CS, OUTPUT); digitalWrite(RC522_CS, HIGH);
  pinMode(SD_CS, OUTPUT);    digitalWrite(SD_CS, HIGH);
  SPI.begin(SCK_PIN, MISO_PIN, MOSI_PIN);
  for (byte i = 0; i < 6; i++) llave.keyByte[i] = 0xFF;  // llave de fábrica

  iniciarRC522();
  iniciarSD();
  // Si montar la SD rompió la comunicación del RC522, el bus compartido no es viable.
  if (rc522Listo && !verificarRC522(false)) {
    rc522Listo = false;
    Serial.println("ERROR:RC522=BLOQUEADO_POR_SD|DETALLE=Activa SD_BUS_SEPARADO en el sketch");
  }
  ultimoChequeoMs = millis();
  Serial.println("LECTOR_LISTO");
}

void loop() {
  atenderSerial();
  unsigned long ahora = millis();
  if (!rc522Listo) {
    // Reintento sin bloquear: los comandos siguen respondiendo mientras tanto.
    if (ahora - ultimoChequeoMs >= REINTENTO_MS) {
      ultimoChequeoMs = ahora;
      iniciarRC522();
    }
    delay(5);
    return;
  }
  if (grabando && (long)(ahora - grabarHastaMs) >= 0) {
    grabando = false;
    Serial.println("ERROR:GRABAR=TIEMPO_AGOTADO");
  }
  procesarTarjeta();
  // Vigilancia: un micro-corte puede dejar el RC522 sin responder; se reinicia solo.
  if (millis() - ultimoChequeoMs >= CHEQUEO_RC522_MS) {
    ultimoChequeoMs = millis();
    if (!verificarRC522(false)) {
      rc522Listo = false;
      iniciarRC522();
    }
  }
  delay(5);  // cede tiempo al RTOS y evita disparar el watchdog
}
