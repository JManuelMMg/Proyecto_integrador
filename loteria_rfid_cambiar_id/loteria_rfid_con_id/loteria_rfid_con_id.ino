#include <SPI.h>
#include <MFRC522.h>

// ===== Pines (ESP32) =====
#define SS_PIN   5   // SDA
#define RST_PIN  22
#define SCK_PIN  18
#define MISO_PIN 19
#define MOSI_PIN 23

// Bloques de datos del sector 1 (el bloque 7 es el trailer, NO se toca)
#define BLOQUE_ES 4   // Espanol
#define BLOQUE_EN 5   // English
#define BLOQUE_MZ 6   // Mazahua

// ID propio de la tarjeta: sector 2 (el bloque 11 es el trailer, NO se toca)
#define BLOQUE_ID 8

MFRC522 rfid(SS_PIN, RST_PIN);
MFRC522::MIFARE_Key key;

// ---------- Utilidades ----------
String leerLinea() {
  String s = "";
  while (true) {
    while (Serial.available()) {
      char c = Serial.read();
      if (c == '\n' || c == '\r') {
        if (s.length() > 0) return s;
      } else {
        s += c;
      }
    }
    delay(5);
  }
}

bool esperarTarjeta(unsigned long timeoutMs = 15000) {
  unsigned long inicio = millis();
  while (millis() - inicio < timeoutMs) {
    if (rfid.PICC_IsNewCardPresent() && rfid.PICC_ReadCardSerial()) {
      return true;
    }
    delay(30);
  }
  Serial.println("ERROR: tiempo agotado, no se detecto tarjeta.");
  return false;
}

void terminarTarjeta() {
  rfid.PICC_HaltA();
  rfid.PCD_StopCrypto1();
}

String uidComoTexto() {
  String uid = "";
  for (byte i = 0; i < rfid.uid.size; i++) {
    if (rfid.uid.uidByte[i] < 0x10) uid += "0";
    uid += String(rfid.uid.uidByte[i], HEX);
  }
  uid.toUpperCase();
  return uid;
}

bool autenticar(byte bloque) {
  MFRC522::StatusCode st = rfid.PCD_Authenticate(
      MFRC522::PICC_CMD_MF_AUTH_KEY_A, bloque, &key, &(rfid.uid));
  if (st != MFRC522::STATUS_OK) {
    Serial.print("ERROR de autenticacion: ");
    Serial.println(rfid.GetStatusCodeName(st));
    return false;
  }
  return true;
}

bool leerBloque(byte bloque, byte *datos) {
  byte buf[18];
  byte tam = sizeof(buf);
  if (!autenticar(bloque)) return false;
  MFRC522::StatusCode st = rfid.MIFARE_Read(bloque, buf, &tam);
  if (st != MFRC522::STATUS_OK) {
    Serial.print("ERROR de lectura: ");
    Serial.println(rfid.GetStatusCodeName(st));
    return false;
  }
  memcpy(datos, buf, 16);
  return true;
}

bool escribirBloque(byte bloque, const byte *datos) {
  if (!autenticar(bloque)) return false;
  MFRC522::StatusCode st = rfid.MIFARE_Write(bloque, (byte *)datos, 16);
  if (st != MFRC522::STATUS_OK) {
    Serial.print("ERROR de escritura: ");
    Serial.println(rfid.GetStatusCodeName(st));
    return false;
  }
  return true;
}

// Convierte el bloque a texto (UTF-8) hasta el primer byte 0
String bloqueComoTexto(const byte *datos) {
  String s = "";
  for (byte i = 0; i < 16 && datos[i] != 0; i++) s += (char)datos[i];
  return s;
}

// Recorta a 16 bytes sin partir un caracter UTF-8 (acentos, ñ, ʉ, etc.)
String recortar16(String t) {
  if (t.length() <= 16) return t;
  int corte = 16;
  while (corte > 0 && (((byte)t[corte]) & 0xC0) == 0x80) corte--;
  return t.substring(0, corte);
}

// Pide la tarjeta, guarda el texto en el bloque y lo verifica
void guardarTexto(const char *nombre, byte bloque, String t) {
  String r = recortar16(t);
  if (r.length() != t.length()) {
    Serial.print("Texto recortado a: ");
    Serial.println(r);
  }

  byte datos[16];
  memset(datos, 0, 16);
  for (byte i = 0; i < r.length(); i++) datos[i] = (byte)r[i];

  Serial.println("Acerca la tarjeta para escribir...");
  if (!esperarTarjeta()) return;

  if (escribirBloque(bloque, datos)) {
    byte verif[16];
    if (leerBloque(bloque, verif) && memcmp(datos, verif, 16) == 0) {
      Serial.print("OK: guardado y verificado (");
      Serial.print(nombre);
      Serial.print(") en tarjeta ");
      String uid = uidComoTexto();
      Serial.println(uid);

      // Evento que registrar_loteria.py recibe y guarda en MySQL.
      Serial.print("WRITE:");
      Serial.print(uid);
      Serial.print("|");
      if (bloque == BLOQUE_ID) Serial.print("ID");
      else if (bloque == BLOQUE_ES) Serial.print("ES");
      else if (bloque == BLOQUE_EN) Serial.print("EN");
      else Serial.print("MZ");
      Serial.print("|");
      for (unsigned int i = 0; i < r.length(); i++) {
        char c = r[i];
        if (c != '|' && c != '\r' && c != '\n') Serial.print(c);
      }
      Serial.println();
    } else {
      Serial.println("ERROR: la verificacion fallo.");
    }
  }
  terminarTarjeta();
}

// ---------- Menu principal ----------
void mostrarMenu() {
  Serial.println();
  Serial.println("===== MENU LOTERIA RFID =====");
  Serial.println("1. Leer UID y tipo de tarjeta");
  Serial.println("2. Leer datos guardados");
  Serial.println("3. Escribir datos (Espanol / English / Mazahua / ID)");
  Serial.println("4. Borrar datos de la tarjeta");
  Serial.println("=============================");
  Serial.print("Elige una opcion: ");
}

// ---------- Opcion 1 ----------
void opcionLeerUID() {
  Serial.println("Acerca la tarjeta...");
  if (!esperarTarjeta()) return;
  MFRC522::PICC_Type tipo = rfid.PICC_GetType(rfid.uid.sak);
  Serial.print("UID: ");
  Serial.println(uidComoTexto());
  Serial.print("Tipo: ");
  Serial.println(rfid.PICC_GetTypeName(tipo));
  terminarTarjeta();
}

// ---------- Opcion 2 ----------
void imprimirCampo(const char *nombre, byte bloque) {
  byte datos[16];
  Serial.print(nombre);
  Serial.print(": ");
  if (leerBloque(bloque, datos)) {
    String t = bloqueComoTexto(datos);
    Serial.println(t.length() ? t : "(vacio)");
  }
}

void opcionLeerDatos() {
  Serial.println("Acerca la tarjeta...");
  if (!esperarTarjeta()) return;
  Serial.print("UID: ");
  Serial.println(uidComoTexto());
  imprimirCampo("ID", BLOQUE_ID);
  imprimirCampo("Espanol", BLOQUE_ES);
  imprimirCampo("English", BLOQUE_EN);
  imprimirCampo("Mazahua", BLOQUE_MZ);
  terminarTarjeta();
}

// ---------- Opcion 3 ----------
void escribirIdioma(const char *nombre, byte bloque) {
  Serial.print("Escribe el texto en ");
  Serial.print(nombre);
  Serial.println(" (max 16 bytes; letras con acento o especiales ocupan 2):");
  String t = leerLinea();
  Serial.println(t);
  guardarTexto(nombre, bloque, t);
}

void escribirID() {
  Serial.println("Escribe el ID que quieres darle a la tarjeta (ej. 1, 2, 3 o A001; max 16 caracteres):");
  String t = leerLinea();
  t.trim();
  Serial.println(t);
  if (t.length() == 0) {
    Serial.println("ERROR: el ID no puede estar vacio.");
    return;
  }
  guardarTexto("ID", BLOQUE_ID, t);
}

void opcionEscribir() {
  Serial.println();
  Serial.println("--- Escribir en ---");
  Serial.println("1. Espanol");
  Serial.println("2. English");
  Serial.println("3. Mazahua");
  Serial.println("4. ID de la tarjeta");
  Serial.println("5. Volver");
  Serial.print("Elige una opcion: ");
  String op = leerLinea();
  Serial.println(op);

  switch (op.toInt()) {
    case 1: escribirIdioma("Espanol", BLOQUE_ES); break;
    case 2: escribirIdioma("English", BLOQUE_EN); break;
    case 3: escribirIdioma("Mazahua", BLOQUE_MZ); break;
    case 4: escribirID(); break;
    case 5: break;
    default: Serial.println("Opcion no valida."); break;
  }
}

// ---------- Opcion 4 ----------
void opcionBorrar() {
  Serial.println("Acerca la tarjeta para borrar...");
  if (!esperarTarjeta()) return;
  byte vacio[16];
  memset(vacio, 0, 16);
  bool ok = escribirBloque(BLOQUE_ID, vacio) &&
            escribirBloque(BLOQUE_ES, vacio) &&
            escribirBloque(BLOQUE_EN, vacio) &&
            escribirBloque(BLOQUE_MZ, vacio);
  if (ok) Serial.println("OK: datos borrados (ID, Espanol, English y Mazahua).");
  terminarTarjeta();
}

// ---------- Arduino ----------
void setup() {
  Serial.begin(115200);
  SPI.begin(SCK_PIN, MISO_PIN, MOSI_PIN, SS_PIN);
  rfid.PCD_Init();

  // Llave por defecto de fabrica
  for (byte i = 0; i < 6; i++) key.keyByte[i] = 0xFF;

  Serial.println("LOTERIA_RFID_LISTA");
  mostrarMenu();
}

void loop() {
  String op = leerLinea();
  Serial.println(op);

  switch (op.toInt()) {
    case 1: opcionLeerUID(); break;
    case 2: opcionLeerDatos(); break;
    case 3: opcionEscribir(); break;
    case 4: opcionBorrar(); break;
    default: Serial.println("Opcion no valida."); break;
  }
  mostrarMenu();
}
