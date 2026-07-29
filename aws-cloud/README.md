# 🏍️ Moto Telemetry — Fase 1: Android → AWS IoT Core

## Arquitectura de esta fase

```
Android (sensores nativos)
    │
    ├── Acelerómetro  (ax, ay, az)
    ├── Giroscopio    (gx, gy, gz)
    ├── Magnetómetro  (mx, my, mz)
    ├── Vector rotación → roll, pitch, yaw
    ├── Barómetro     (presión hPa)
    ├── Termómetro    (temperatura ambiente °C)
    ├── Luz           (lux)
    ├── Proximidad    (cm)
    ├── GPS           (lat, lng, alt, speed, bearing)
    └── Batería       (%, cargando?)
         │
         │  MQTT / TLS (puerto 8883)
         ▼
   AWS IoT Core
         │
         │  IoT Rules Engine
         ▼
   Kinesis Firehose
         │
         │  GZIP / 60s buffer
         ▼
   S3 Data Lake  (raw/year=.../month=.../day=.../...)
```

---

## Paso 1 — Infraestructura AWS (Terraform)

```bash
cd aws-iot-infra/

# Inicializar
terraform init

# Ver qué se va a crear
terraform plan

# Crear recursos
terraform apply

# Guardar el certificado y la clave privada
terraform output -raw certificate_pem > certificate.pem.crt
terraform output -raw private_key_pem  > private.pem.key
```

> **Nota:** El endpoint de IoT lo obtienes con:
> ```bash
> aws iot describe-endpoint --endpoint-type iot:Data-ATS
> # → xxxxxxxxxxxx-ats.iot.us-east-1.amazonaws.com
> ```

---

## Paso 2 — Generar el keystore para Android

```bash
# Descargar Bouncy Castle JAR
curl -O https://repo1.maven.org/maven2/org/bouncycastle/bcprov-jdk15on/1.70/bcprov-jdk15on-1.70.jar

# Generar keystores BKS
bash generate_keystore.sh moto_android_01

# Copiar al proyecto Android
cp moto_android_01.bks  android/app/src/main/assets/
cp aws_root_ca.bks      android/app/src/main/assets/
```

---

## Paso 3 — Proyecto Android (Kotlin)

### build.gradle.kts (app)
```kotlin
dependencies {
    // AWS IoT SDK
    implementation("com.amazonaws:aws-android-sdk-iot:2.73.0")
    implementation("com.amazonaws:aws-android-sdk-core:2.73.0")

    // GPS
    implementation("com.google.android.gms:play-services-location:21.2.0")

    // Coroutines
    implementation("org.jetbrains.kotlinx:kotlinx-coroutines-android:1.7.3")
}
```

### AndroidManifest.xml — permisos necesarios
```xml
<!-- Internet y red -->
<uses-permission android:name="android.permission.INTERNET" />
<uses-permission android:name="android.permission.ACCESS_NETWORK_STATE" />

<!-- GPS -->
<uses-permission android:name="android.permission.ACCESS_FINE_LOCATION" />
<uses-permission android:name="android.permission.ACCESS_COARSE_LOCATION" />
<uses-permission android:name="android.permission.ACCESS_BACKGROUND_LOCATION" />

<!-- Servicio en foreground (Android 9+) -->
<uses-permission android:name="android.permission.FOREGROUND_SERVICE" />
<uses-permission android:name="android.permission.FOREGROUND_SERVICE_LOCATION" />

<!-- Batería -->
<uses-permission android:name="android.permission.BATTERY_STATS" />

<!-- Declarar el servicio -->
<service
    android:name=".MotoTelemetryService"
    android:foregroundServiceType="location"
    android:exported="false" />
```

### MainActivity.kt — arrancar el servicio
```kotlin
class MainActivity : AppCompatActivity() {

    private val PERMISSIONS = arrayOf(
        Manifest.permission.ACCESS_FINE_LOCATION,
        Manifest.permission.ACCESS_BACKGROUND_LOCATION
    )

    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)

        if (hasPermissions()) {
            startTelemetry()
        } else {
            ActivityCompat.requestPermissions(this, PERMISSIONS, 100)
        }
    }

    private fun hasPermissions() = PERMISSIONS.all {
        ContextCompat.checkSelfPermission(this, it) == PackageManager.PERMISSION_GRANTED
    }

    private fun startTelemetry() {
        val intent = Intent(this, MotoTelemetryService::class.java)
        ContextCompat.startForegroundService(this, intent)
    }

    override fun onRequestPermissionsResult(
        requestCode: Int, permissions: Array<String>, grantResults: IntArray
    ) {
        super.onRequestPermissionsResult(requestCode, permissions, grantResults)
        if (requestCode == 100 && grantResults.all { it == PackageManager.PERMISSION_GRANTED }) {
            startTelemetry()
        }
    }
}
```

---

## Paso 4 — Verificar en AWS

### Verificar mensajes llegando (AWS Console)
1. **IoT Core** → **Test** → **MQTT test client**
2. Suscribirse al topic: `moto/moto_android_01/#`
3. Deberías ver mensajes cada 500ms

### Verificar datos en S3
```bash
# Ver archivos llegando al bucket
aws s3 ls s3://moto-telemetry-data-lake-xxxx/raw/ --recursive

# Descargar y ver un archivo
aws s3 cp s3://moto-telemetry-data-lake-xxxx/raw/year=2026/month=06/day=09/data.gz .
gunzip data.gz && cat data | head -5 | python3 -m json.tool
```

---

## Payload de ejemplo — Topic: moto/moto_android_01/telemetry

```json
{
  "device_id": "moto_android_01",
  "timestamp": 1749500000000,
  "source": "android_native",
  "imu": {
    "ax": 0.123, "ay": -0.045, "az": 9.812,
    "gx": 0.012, "gy": -0.003, "gz": 0.001,
    "mx": 22.4,  "my": -8.1,   "mz": 44.2,
    "roll": 1.2, "pitch": -0.8, "yaw": 245.6
  },
  "environment": {
    "pressure_hpa": 1013.25,
    "temperature_c": 28.4,
    "light_lux": 4200.0,
    "proximity_cm": 5.0
  },
  "gps": {
    "lat": 19.4326,
    "lng": -99.1332,
    "alt_m": 2240.0,
    "speed_kmh": 72.4,
    "bearing": 90.0,
    "accuracy_m": 3.2,
    "provider": "fused"
  },
  "device": {
    "battery_pct": 87,
    "is_charging": true,
    "android_sdk": 34,
    "model": "Pixel 7"
  }
}
```

---

## Fase 2 (próxima) — Agregar Arduino Mega por USB OTG

```
Arduino Mega
    ├── Sensor RPM      (interrupción digital pin 2)
    ├── Sensor velocidad (Hall effect + reed switch)
    └── Odómetro        (contador de pulsos acumulado)
         │
         │  USB OTG / Serial 115200 baud
         │  Protocolo: JSON por línea (\n delimitado)
         ▼
    Android App
    (UsbManager + UsbSerialLibrary)
         │
         │  Se fusiona con datos de sensores nativos
         ▼
    AWS IoT Core (mismo pipeline)
```

---

## Troubleshooting

| Problema | Solución |
|---|---|
| `Connection refused` | Verificar que el endpoint en el .kt sea correcto |
| `Certificate error` | Regenerar el .bks con el script |
| `GPS null` | Asegurar que `ACCESS_BACKGROUND_LOCATION` está concedido |
| Firehose sin datos | Revisar la IoT Rule en la consola → CloudWatch Logs |
| App se mata en background | Agregar `android:persistent="true"` o usar WorkManager |
