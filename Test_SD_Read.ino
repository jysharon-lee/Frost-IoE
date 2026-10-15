#include "hardware/i2c.h"
#include <LittleFS.h>
#include <SPI.h>
#include <SD.h>
#include <Adafruit_NeoPixel.h>

#define KIT_ID     "K01"
#define AHT20_ADDR 0x38
#define BUTTON_B   1          // GP1, pressed = LOW
#define POLL_MS    5000       // sensor poll interval
#define BUZZER_PIN 21
#define LOG_FILE   "/log.jsonl"   // new name, so old-format rows are ignored

// SD card on SPI0
const int PIN_MISO = 16;      // SDO
const int PIN_CS   = 17;      // CSn
const int PIN_SCK  = 18;      // SCK
const int PIN_MOSI = 19;      // SDI
const char* CSV_NAME = "normal.csv";

#define NOTE_C4 262
#define NOTE_G4 392
#define NOTE_C5 523
#define NOTE_E5 659
#define NOTE_G5 784
#define NOTE_C6 1047
#define NEOPIXEL_PIN   14
#define NEOPIXEL_COUNT 5
#define STATUS_LED     4      // NeoPixel index 4 = power status

bool outage = false;          // true = simulated outage (logging to flash)
unsigned long lastRead = 0;
unsigned long lastPress = 0;
unsigned long seq = 0;        // resets on reboot
bool lastButton = HIGH;

File simFile;
bool sdOk = false;

Adafruit_NeoPixel pixels(NEOPIXEL_COUNT, NEOPIXEL_PIN, NEO_GRB + NEO_KHZ800);

void setNeoPixelColor(uint8_t pixelIndex, uint8_t r, uint8_t g, uint8_t b) {
    if (pixelIndex < NEOPIXEL_COUNT) pixels.setPixelColor(pixelIndex, pixels.Color(r, g, b));
}

void updateStatusLED() {
    if (outage) setNeoPixelColor(STATUS_LED, 255, 0, 0);
    else        setNeoPixelColor(STATUS_LED, 0, 255, 0);
    pixels.show();
}

// ---------- S01: built-in AHT20 ----------
bool readSensor(float &t, float &h) {
    uint8_t trigger[] = {0xAC, 0x33, 0x00};
    uint8_t d[7];
    i2c_write_blocking(i2c0, AHT20_ADDR, trigger, 3, false);
    delay(80);
    if (i2c_read_blocking(i2c0, AHT20_ADDR, d, 7, false) != 7) return false;
    uint32_t hRaw = ((uint32_t)d[1] << 12) | ((uint32_t)d[2] << 4) | (d[3] >> 4);
    uint32_t tRaw = ((uint32_t)(d[3] & 0x0F) << 16) | ((uint32_t)d[4] << 8) | d[5];
    t = tRaw * 200.0f / 1048576.0f - 50.0f;
    h = hRaw * 100.0f / 1048576.0f;
    return true;
}

// ---------- S02: next row of the CSV on the SD card ----------
// CSV columns: tick,S02_temp_c,S02_rh_pct,S02_ok
bool readSimRow(float &t, float &h) {
    if (!sdOk) return false;
    for (int attempt = 0; attempt < 2; attempt++) {
        if (!simFile.available()) {
            simFile.seek(0);
            simFile.readStringUntil('\n');        // skip header
        }
        String line = simFile.readStringUntil('\n');
        line.trim();
        if (line.length() == 0) continue;

        int c1 = line.indexOf(',');
        int c2 = line.indexOf(',', c1 + 1);
        int c3 = line.indexOf(',', c2 + 1);
        if (c1 < 0 || c2 < 0 || c3 < 0) return false;

        String sT  = line.substring(c1 + 1, c2);
        String sH  = line.substring(c2 + 1, c3);
        String sOk = line.substring(c3 + 1);
        sT.trim(); sH.trim(); sOk.trim();

        if (sOk.toInt() != 1 || sT.length() == 0 || sH.length() == 0) return false;
        t = sT.toFloat();
        h = sH.toFloat();
        return true;
    }
    return false;
}

// ---------- packet building ----------
void probeJson(char *buf, size_t n, const char *id, bool ok, float t, float h) {
    if (ok) snprintf(buf, n, "{\"id\":\"%s\",\"temp_c\":%.1f,\"rh_pct\":%.1f,\"ok\":true}", id, t, h);
    else    snprintf(buf, n, "{\"id\":\"%s\",\"temp_c\":null,\"rh_pct\":null,\"ok\":false}", id);
}

void emitPacket(unsigned long up,
                bool ok1, float t1, float h1,
                bool ok2, float t2, float h2) {
    char p1[90], p2[90], buf[400];
    probeJson(p1, sizeof(p1), "S01", ok1, t1, h1);
    probeJson(p2, sizeof(p2), "S02", ok2, t2, h2);
    snprintf(buf, sizeof(buf),
             "{\"v\":1,\"kit_id\":\"%s\",\"seq\":%lu,\"uptime_s\":%lu,\"ts_synced\":false,"
             "\"power_source\":\"%s\",\"buffered\":%s,\"probes\":[%s,%s]}",
             KIT_ID, seq++, up,
             outage ? "battery" : "mains",
             outage ? "true" : "false",
             p1, p2);

    if (outage) {                                   // link down: store locally
        File f = LittleFS.open(LOG_FILE, "a");      // append, never wipe
        if (f) { f.println(buf); f.close(); }
    } else {
        Serial.println(buf);
    }
}

// ---------- buzzer ----------
void playMelody(const int *notes, const int *durs, int len) {
    for (int i = 0; i < len; i++) {
        tone(BUZZER_PIN, notes[i]);
        delay(durs[i]);
        noTone(BUZZER_PIN);
        delay(30);
    }
}
const int outNotes[]  = {NOTE_G5, NOTE_E5, NOTE_C5, NOTE_G4, NOTE_C4};
const int outDurs[]   = {200, 200, 200, 250, 500};
const int backNotes[] = {NOTE_C5, NOTE_E5, NOTE_G5, NOTE_C6};
const int backDurs[]  = {120, 120, 120, 350};

// ---------- backlog ----------
void sendBacklog() {
    Serial.printf("UPTIME,%lu\n", millis() / 1000);   // lets the laptop sync clocks
    Serial.println("---BEGIN---");
    int count = 0;
    File f = LittleFS.open(LOG_FILE, "r");
    if (f) {
        while (f.available()) {
            String line = f.readStringUntil('\n');
            line.trim();
            if (line.length() == 0) continue;
            Serial.println(line);
            count++;
        }
        f.close();
    }
    Serial.printf("---END,%d---\n", count);             // count lets the laptop verify
}

// ---------- input ----------
void checkButton() {
    bool now = digitalRead(BUTTON_B);
    if (lastButton == HIGH && now == LOW && millis() - lastPress > 250) {
        lastPress = millis();
        outage = !outage;
        updateStatusLED();
        if (outage) {
            Serial.println("INFO,OUTAGE START - logging locally");
            playMelody(outNotes, outDurs, sizeof(outNotes) / sizeof(outNotes[0]));
        } else {
            Serial.println("INFO,POWER RESTORED - sending backlog");
            playMelody(backNotes, backDurs, sizeof(backNotes) / sizeof(backNotes[0]));
            sendBacklog();
        }
    }
    lastButton = now;
}

void handleSerial() {
    while (Serial.available()) {
        char c = Serial.read();
        if (c == 'd') sendBacklog();
        else if (c == 'k') {
            LittleFS.remove(LOG_FILE);
            Serial.println("INFO,LOCAL LOG CLEARED");
        }
    }
}

// ---------- main ----------
void setup() {
    Serial.begin(115200);
    delay(2000);

    if (!LittleFS.begin()) {
        Serial.println("INFO,LittleFS mount failed - check Tools > Flash Size");
    }

    pinMode(BUTTON_B, INPUT_PULLUP);
    pinMode(BUZZER_PIN, OUTPUT);

    i2c_init(i2c0, 100 * 1000);
    gpio_set_function(4, GPIO_FUNC_I2C);
    gpio_set_function(5, GPIO_FUNC_I2C);
    gpio_pull_up(4);
    gpio_pull_up(5);

    pixels.begin();
    pixels.setBrightness(50);
    pixels.clear();
    updateStatusLED();

    SPI.setRX(PIN_MISO);
    SPI.setTX(PIN_MOSI);
    SPI.setSCK(PIN_SCK);
    if (SD.begin(PIN_CS)) {
        simFile = SD.open(CSV_NAME);
        if (simFile) {
            simFile.readStringUntil('\n');   // skip header
            sdOk = true;
            Serial.println("INFO,SD ready, S02 simulated");
        } else {
            Serial.println("INFO,SD ok but CSV not found - S02 will report failed");
        }
    } else {
        Serial.println("INFO,SD init failed - S02 will report failed");
    }

    delay(100);
    uint8_t init[] = {0xBE, 0x08, 0x00};
    i2c_write_blocking(i2c0, AHT20_ADDR, init, 3, false);
    delay(10);
}

void loop() {
    handleSerial();
    checkButton();

    if (millis() - lastRead >= POLL_MS) {
        lastRead = millis();
        unsigned long up = millis() / 1000;   // one time reading for the whole cycle

        float t1 = 0, h1 = 0, t2 = 0, h2 = 0;
        bool ok1 = readSensor(t1, h1);        // S01 first
        bool ok2 = readSimRow(t2, h2);        // then S02
        emitPacket(up, ok1, t1, h1, ok2, t2, h2);
    }
}
