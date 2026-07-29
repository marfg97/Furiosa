/*
 * Moto IoT - Telemetría para Ssenda Patagonia 169
 * 
 * Sensores:
 * - RPM (señal de la bobina)
 * - Voltaje de batería (12V)
 * - Temperatura de aceite/motor
 * - Detección de motor encendido
 * - RTC DS3231 (fecha/hora)
 * - Registro en SD Card
 * - Pantalla OLED (opcional)
 * 
 * Comunicación: USB Serial a 9600 baudios
 * Formato: DATA:timestamp,RPM,voltaje,porcentaje,temperatura,encendido,horas,fecha,hora
 * 
 * 
 * Licencia: GPL-3.0
 */

#include <Wire.h>
#include <RTClib.h>
#include <SPI.h>
#include <SD.h>
#include <OneWire.h>        // Para DS18B20
#include <DallasTemperature.h>

// =============================================
//  CONFIGURACIÓN DE PINES
// =============================================
#define PIN_RPM          2      // Interrupción para RPM
#define PIN_VOLT         A0     // Divisor de voltaje de batería
#define PIN_IGNITION     A1     // Detección de motor encendido (12V con llave)
#define PIN_TEMP         A2     // Sensor NTC (opcional) o DS18B20 en pin digital
#define PIN_LED          13     // LED indicador de motor encendido

// SD Card (SPI)
#define PIN_SD_CS        10     // Chip Select para SD Card

// =============================================
//  CONFIGURACIÓN DE CONSTANTES
// =============================================
// Divisor de voltaje: (R1=10kΩ, R2=4.7kΩ)
#define FACTOR_DIVISOR   3.13   // (R1+R2)/R2
#define VOLT_MAX         12.7   // Batería 100% (en reposo)
#define VOLT_MIN         11.8   // Batería 0% (no bajar de aquí)

// Sensor de temperatura NTC (parámetros de la ecuación de Steinhart-Hart)
#define NTC_SERIES_RES   10000.0  // Resistencia en serie (10kΩ)
#define NTC_NOMINAL      10000.0  // Resistencia nominal a 25°C (10kΩ)
#define NTC_BETA         3950.0   // Coeficiente Beta del termistor
#define NTC_TEMP_NOMINAL 25.0     // Temperatura nominal (°C)

// Constantes para cálculo de RPM
#define PULSOS_POR_REVOLUCION 1   // Para motor de 1 cilindros

// =============================================
//  VARIABLES GLOBALES
// =============================================
// RPM
volatile unsigned long pulsosRPM = 0;
unsigned long rpm = 0;
unsigned long ultimoTiempoRPM = 0;

// Voltaje
float voltajeBateria = 0.0;
int porcentajeBateria = 0;

// Temperatura
float temperaturaMotor = 0.0;

// Motor encendido
bool motorEncendido = false;
unsigned long tiempoArranque = 0;
unsigned long tiempoEncendidoSegundos = 0;

// RTC
RTC_DS3231 rtc;
DateTime now;

// SD Card
File archivoLog;

// DS18B20
// #define PIN_DS18B20 3
// OneWire oneWire(PIN_DS18B20);
// DallasTemperature sensors(&oneWire);

// =============================================
//  SETUP
// =============================================
void setup() {
  Serial.begin(9600);
  
  // Configurar pines
  pinMode(PIN_RPM, INPUT_PULLUP);
  pinMode(PIN_VOLT, INPUT);
  pinMode(PIN_IGNITION, INPUT);
  pinMode(PIN_LED, OUTPUT);
  
  // Interrupción para RPM
  attachInterrupt(digitalPinToInterrupt(PIN_RPM), contarPulso, RISING);
  
  // Inicializar RTC
  if (!rtc.begin()) {
    Serial.println("ERROR: RTC no detectado");
  } else {
    if (rtc.lostPower()) {
      Serial.println("RTC sin hora. Configurando con tiempo de compilación...");
      rtc.adjust(DateTime(F(__DATE__), F(__TIME__)));
    }
  }
  
  // Inicializar SD Card
  if (!SD.begin(PIN_SD_CS)) {
    Serial.println("ERROR: SD Card no detectada");
  } else {
    Serial.println("SD Card lista");
    // Crear archivo de log si no existe
    if (!SD.exists("/LOG.TXT")) {
      archivoLog = SD.open("/LOG.TXT", FILE_WRITE);
      if (archivoLog) {
        archivoLog.println("=== REGISTRO MOTO IoT ===");
        archivoLog.println("FECHA,HORA,RPM,VOLTAJE(%),TEMP(°C),ENCENDIDO(HORAS)");
        archivoLog.close();
      }
    }
  }
  
  // Inicializar DS18B20 (opcional)
  // sensors.begin();
  
  Serial.println("Sistema Moto IoT iniciado");
  Serial.println("Formato: DATA:timestamp,RPM,voltaje,%,temp,on,horas,fecha,hora");
}

// =============================================
//  LOOP PRINCIPAL
// =============================================
void loop() {
  // 1. Leer voltaje de batería (cada 500ms)
  static unsigned long ultimoVoltaje = 0;
  if (millis() - ultimoVoltaje >= 500) {
    leerVoltajeBateria();
    ultimoVoltaje = millis();
  }
  
  // 2. Leer temperatura (cada 1 segundo)
  static unsigned long ultimaTemp = 0;
  if (millis() - ultimaTemp >= 1000) {
    leerTemperatura();
    ultimaTemp = millis();
  }
  
  // 3. Detectar motor encendido
  motorEncendido = digitalRead(PIN_IGNITION) == HIGH;
  digitalWrite(PIN_LED, motorEncendido ? HIGH : LOW);
  
  // 4. Calcular RPM (cada 200ms para mejor respuesta)
  static unsigned long ultimoRPM = 0;
  if (millis() - ultimoRPM >= 200) {
    calcularRPM();
    ultimoRPM = millis();
  }
  
  // 5. Actualizar tiempo de encendido
  actualizarTiempoEncendido();
  
  // 6. Enviar datos por USB (cada 500ms)
  static unsigned long ultimoEnvio = 0;
  if (millis() - ultimoEnvio >= 500) {
    enviarDatosPorUSB();
    ultimoEnvio = millis();
  }
  
  // 7. Guardar en SD Card (cada 10 segundos, solo si motor encendido)
  static unsigned long ultimoLog = 0;
  if (motorEncendido && (millis() - ultimoLog >= 10000)) {
    guardarLogSD();
    ultimoLog = millis();
  }
  
 
  delay(50);  // Pequeño delay para evitar saturar el bucle
}

// =============================================
//  FUNCIONES DE LECTURA DE SENSORES
// =============================================

/*
 * Interrupción para contar pulsos de RPM
 */
void contarPulso() {
  pulsosRPM++;
}

/*
 * Leer voltaje de la batería y calcular porcentaje
 */
void leerVoltajeBateria() {
  int lectura = analogRead(PIN_VOLT);
  float voltajePin = (lectura / 1023.0) * 5.0;
  voltajeBateria = voltajePin * FACTOR_DIVISOR;
  
  // Convertir a porcentaje (batería plomo-ácido 12V)
  if (voltajeBateria >= VOLT_MAX) {
    porcentajeBateria = 100;
  } else if (voltajeBateria <= VOLT_MIN) {
    porcentajeBateria = 0;
  } else {
    porcentajeBateria = (int)((voltajeBateria - VOLT_MIN) / (VOLT_MAX - VOLT_MIN) * 100);
  }
}

/*
 * Leer temperatura del motor (NTC o DS18B20)
 */
void leerTemperatura() {
  // Opción 1: NTC en pin analógico A2
  int lectura = analogRead(PIN_TEMP);
  float resistencia = NTC_SERIES_RES * (1023.0 / lectura - 1.0);
  
  // Ecuación de Steinhart-Hart para NTC
  float temperaturaK = 1.0 / (1.0/NTC_TEMP_NOMINAL + log(resistencia/NTC_NOMINAL)/NTC_BETA + 273.15);
  temperaturaMotor = temperaturaK - 273.15;
  
  // Opción 2: DS18B20 (descomentar si se usa)
  // sensors.requestTemperatures();
  // temperaturaMotor = sensors.getTempCByIndex(0);
}

/*
 * Calcular RPM a partir de los pulsos contados
 */
void calcularRPM() {
  noInterrupts();
  unsigned long pulsos = pulsosRPM;
  pulsosRPM = 0;
  interrupts();
  
  // RPM = (pulsos por segundo * 60) / pulsos por revolución
  rpm = (pulsos * 60) / PULSOS_POR_REVOLUCION;
}

/*
 * Actualizar tiempo de encendido del motor
 */
void actualizarTiempoEncendido() {
  if (motorEncendido) {
    if (tiempoArranque == 0) {
      tiempoArranque = millis();
    }
    tiempoEncendidoSegundos = (millis() - tiempoArranque) / 1000;
  } else {
    tiempoArranque = 0;
    tiempoEncendidoSegundos = 0;
  }
}

// =============================================
//  FUNCIONES DE SALIDA DE DATOS
// =============================================

/*
 * Enviar datos por USB al celular
 * Formato: DATA:timestamp,RPM,voltaje,%,temp,on,horas,fecha,hora
 */
void enviarDatosPorUSB() {
  now = rtc.now();
  
  // Obtener timestamp (segundos desde epoch)
  unsigned long timestamp = now.unixtime();
  
  // Construir la línea de datos
  Serial.print("DATA:");
  Serial.print(timestamp);
  Serial.print(",");
  Serial.print(rpm);
  Serial.print(",");
  Serial.print(voltajeBateria, 1);
  Serial.print(",");
  Serial.print(porcentajeBateria);
  Serial.print(",");
  Serial.print(temperaturaMotor, 1);
  Serial.print(",");
  Serial.print(motorEncendido ? 1 : 0);
  Serial.print(",");
  Serial.print(tiempoEncendidoSegundos);
  Serial.print(",");
  Serial.print(now.year());
  Serial.print("-");
  Serial.print(now.month());
  Serial.print("-");
  Serial.print(now.day());
  Serial.print(" ");
  Serial.print(now.hour());
  Serial.print(":");
  Serial.print(now.minute());
  Serial.print(":");
  Serial.println(now.second());
}

/*
 * Guardar datos en la tarjeta SD
 */
void guardarLogSD() {
  now = rtc.now();
  String fecha = String(now.year()) + "-" + String(now.month()) + "-" + String(now.day());
  String hora = String(now.hour()) + ":" + String(now.minute()) + ":" + String(now.second());
  
  archivoLog = SD.open("/LOG.TXT", FILE_WRITE);
  if (archivoLog) {
    archivoLog.print(fecha);
    archivoLog.print(",");
    archivoLog.print(hora);
    archivoLog.print(",");
    archivoLog.print(rpm);
    archivoLog.print(",");
    archivoLog.print(porcentajeBateria);
    archivoLog.print(",");
    archivoLog.print(temperaturaMotor, 1);
    archivoLog.print(",");
    archivoLog.println(tiempoEncendidoSegundos / 3600.0, 2);
    archivoLog.close();
  }
}

