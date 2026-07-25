# 🏍️ Moto IoT - Telemetría Inteligente para Ssenda Patagonia 169

![Estado del proyecto](https://img.shields.io/badge/estado-en%20desarrollo-brightgreen)
![Licencia](https://img.shields.io/badge/licencia-GPL--3.0-blue)
![Plataforma](https://img.shields.io/badge/plataforma-Android%20%7C%20Arduino-orange)
![AWS](https://img.shields.io/badge/AWS-IoT%20Core-yellow)

**Sistema de telemetría y monitoreo en tiempo real para motos, con integración a la nube AWS y análisis de datos.**

---

## 📌 Descripción

**Moto IoT** es un proyecto de hardware y software diseñado para transformar una moto convencional (Ssenda Patagonia 169) en un vehículo conectado e inteligente. El sistema recopila datos críticos de la moto (RPM, voltaje de batería, tiempo de encendido) y del entorno (GPS, aceleración, inclinación) mediante un **Arduino Mega** y un **celular Android**, y los envía a la nube **AWS IoT Core** para su análisis y visualización en tiempo real.

El proyecto integra:
- **Hardware embebido**: Arduino Mega con sensores y módulos (RTC, SD Card, OLED).
- **Aplicación móvil**: App Android nativa en Kotlin que lee sensores del celular (GPS, acelerómetro, batería) y se conecta a AWS IoT.
- **Nube**: AWS IoT Core para ingesta de datos, con posibilidad de análisis con Machine Learning y visualización en dashboards.

---

## 🎯 Objetivos del Proyecto

- ✅ **Monitoreo en tiempo real**: Visualizar RPM, voltaje de batería, GPS, inclinación y aceleración desde el celular.
- ✅ **Registro histórico**: Guardar datos en una tarjeta SD con fecha/hora para análisis posterior.
- ✅ **Conectividad a la nube**: Enviar datos a AWS IoT Core mediante MQTT sobre WebSockets.
- ✅ **Análisis de datos**: Usar los datos recolectados para optimizar el rendimiento de la moto, predecir fallos o mejorar la seguridad.
- ✅ **Segunda pantalla**: El celular actúa como un tablero digital avanzado, mostrando información que el tablero original no incluye (inclinación, batería en %, aceleración).

---

## 🧩 Componentes del Sistema

### 🛠️ Hardware (Moto)

| Componente | Función |
|:---|:---|
| **Arduino Mega** | Procesador central, lee sensores y controla módulos. |
| **Regulador DC-DC LM2596** | Convierte 12V de la batería de la moto a 5V para el Arduino. |
| **Divisor de tensión (10kΩ / 4.7kΩ)** | Mide el voltaje de la batería de la moto. |
| **Divisor de tensión (10kΩ / 10kΩ)** | Acondiciona la señal de RPM para el Arduino. |
| **RTC DS3231** | Reloj en tiempo real para fechas y horas históricas. |
| **Módulo SD Card** | Almacena los datos de forma local (LOG.TXT). |
| **Pantalla OLED 0.96"** | Muestra RPM, batería y tiempo de encendido en vivo (opcional). |
| **Cableado y conectores** | Conexiones eléctricas a la moto (señal de RPM, 12V con llave, GND). |

### 📱 Software (Celular)

| Componente | Función |
|:---|:---|
| **App Android (Kotlin)** | Interfaz de usuario que muestra datos en tiempo real. |
| **AWS IoT SDK** | Conexión segura a AWS IoT Core mediante MQTT sobre WebSockets. |
| **SensorManager** | Lee acelerómetro, giroscopio y gravedad del celular. |
| **LocationManager** | Obtiene GPS (latitud, longitud, velocidad, altitud). |
| **BatteryManager** | Monitorea el nivel y temperatura de la batería del celular. |

### ☁️ Nube (AWS)

| Servicio | Función |
|:---|:---|
| **AWS IoT Core** | Ingestiona y enruta los datos MQTT. |
| **Amazon Cognito** | Autenticación del dispositivo móvil. |
| **AWS Lambda** | Procesa y transforma los datos (opcional). |
| **Amazon Timestream / DynamoDB** | Almacena datos históricos para análisis (opcional). |
| **Amazon QuickSight / Grafana** | Visualización de datos en dashboards (opcional). |

---

## 📊 Datos Recolectados

### Desde la moto (Arduino)
- **RPM** (Revoluciones por minuto)
- **Voltaje de batería** (0-100% de carga)
- **Tiempo de encendido** del motor (en horas)
- **Fecha y hora** (RTC)

### Desde el celular
- **GPS**: Latitud, longitud, velocidad (km/h), altitud
- **Acelerómetro**: Aceleración en 3 ejes (X, Y, Z)
- **Giroscopio**: Rotación en 3 ejes (X, Y, Z)
- **Gravedad**: Para calcular inclinación de la moto
- **Batería del celular**: Nivel (%), temperatura, voltaje

### Datos combinados (en la nube)
Todos los datos se fusionan en un solo JSON y se publican en AWS IoT Core con la siguiente estructura:

```json
{
  "timestamp": 1700000000000,
  "device_id": "moto_180cc",
  "rpm": 3250,
  "battery_moto_voltage": 12.4,
  "battery_moto_percent": 85,
  "engine_on_seconds": 3600,
  "gps_lat": -12.043333,
  "gps_lon": -77.028333,
  "gps_speed_kmh": 65.2,
  "inclination_degrees": 12.5,
  "accel_magnitude": 1.02,
  "battery_cell_level": 85,
  "battery_cell_temp": 32.5
}