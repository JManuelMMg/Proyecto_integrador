#include <SPI.h>
#include <MFRC522.h>

// ===== Pines (ESP32) =====
#define SS_PIN   5   // SDA
#define RST_PIN  22
#define SCK_PIN  18
#define MISO_PIN 19
#define MOSI_PIN 23

// Bloques donde se guardaron los datos
#define BLOQUE_ES 4   // Espanol
#define BLOQUE_EN 5   // English
#define BLOQUE_MZ 6   // Mazahua

MFRC522 rfid(SS_PIN, RST_PIN);
MFRC522::MIFARE_Key key;

String uidComoTexto() {
  String uid = "";
  for (byte i = 0; i < rfid.uid.size; i++) {
    if (rfid.uid.uidByte[i] < 0x10) uid += "0";
    uid += String(rfid.uid.uidByte[i], HEX);
  }
  uid.toUpperCase();
  return uid;
}

// Lee un bloque y lo devuelve como texto UTF-8 (vacio si falla)
String leerTexto(byte bloque) {
  byte buf[18];
  byte tam = sizeof(buf);

  MFRC522::StatusCode st = rfid.PCD_Authenticate(
      MFRC522::PICC_CMD_MF_AUTH_KEY_A, bloque, &key, &(rfid.uid));
  if (st != MFRC522::STATUS_OK) return "";

  st = rfid.MIFARE_Read(bloque, buf, &tam);
  if (st != MFRC522::STATUS_OK) return "";

  String s = "";
  for (byte i = 0; i < 16 && buf[i] != 0; i++) s += (char)buf[i];
  return s;
}

void setup() {
  Serial.begin(115200);
  SPI.begin(SCK_PIN, MISO_PIN, MOSI_PIN, SS_PIN);
  rfid.PCD_Init();

  // Llave por defecto de fabrica
  for (byte i = 0; i < 6; i++) key.keyByte[i] = 0xFF;

  Serial.println("LECTOR_LISTO");
}

void loop() {
  if (!rfid.PICC_IsNewCardPresent()) return;
  if (!rfid.PICC_ReadCardSerial()) return;

  // Formato en una sola linea: CARD:UID|ES:texto|EN:texto|MZ:texto
  Serial.print("CARD:");
  Serial.print(uidComoTexto());
  Serial.print("|ES:");
  Serial.print(leerTexto(BLOQUE_ES));
  Serial.print("|EN:");
  Serial.print(leerTexto(BLOQUE_EN));
  Serial.print("|MZ:");
  Serial.println(leerTexto(BLOQUE_MZ));

  rfid.PICC_HaltA();
  rfid.PCD_StopCrypto1();

  delay(500);
}
