// ─────────────────────────────────────────────────────────────
// MotoTelemetryService.kt
// Servicio en background que recolecta TODOS los sensores
// nativos del Android y publica a AWS IoT Core via MQTT
//
// Dependencias (build.gradle.kts):
//   implementation("software.amazon.awssdk:iot:2.x.x")
//   implementation("com.amazonaws:aws-android-sdk-iot:2.x.x")
//   implementation("org.eclipse.paho:org.eclipse.paho.client.mqttv3:1.2.5")
//   implementation("com.google.android.gms:play-services-location:21.x.x")
// ─────────────────────────────────────────────────────────────

package com.mototelemetry

import android.app.*
import android.content.Context
import android.content.Intent
import android.hardware.*
import android.location.*
import android.os.*
import android.util.Log
import androidx.core.app.NotificationCompat
import com.amazonaws.mobileconnectors.iot.*
import com.amazonaws.regions.Region
import com.amazonaws.regions.Regions
import com.google.android.gms.location.*
import kotlinx.coroutines.*
import org.json.JSONObject
import java.io.InputStream
import java.security.KeyStore
import java.util.concurrent.atomic.AtomicBoolean

// ─── Constantes de configuración ────────────────────────────
private const val TAG = "MotoTelemetry"
private const val CHANNEL_ID = "moto_telemetry_channel"
private const val NOTIFICATION_ID = 1001

// ← Reemplaza con tus valores
private const val AWS_IOT_ENDPOINT = "xxxxxxxxxxxx-ats.iot.us-east-1.amazonaws.com"
private const val DEVICE_ID = "moto_android_01"
private const val CLIENT_ID = DEVICE_ID

// Topics MQTT
private const val TOPIC_TELEMETRY = "moto/$DEVICE_ID/telemetry"
private const val TOPIC_GPS       = "moto/$DEVICE_ID/gps"
private const val TOPIC_IMU       = "moto/$DEVICE_ID/imu"

// Frecuencias de publicación
private const val PUBLISH_INTERVAL_MS   = 500L  // telemetría combinada cada 500ms
private const val GPS_INTERVAL_MS       = 1000L
private const val SENSOR_BATCH_SIZE     = 10    // acumula N muestras IMU antes de publicar

// ─────────────────────────────────────────────────────────────
class MotoTelemetryService : Service(), SensorEventListener {

    // AWS IoT
    private lateinit var iotManager: AWSIotMqttManager
    private val isConnected = AtomicBoolean(false)

    // Sensores
    private lateinit var sensorManager: SensorManager
    private var accelerometer: Sensor? = null
    private var gyroscope: Sensor? = null
    private var magnetometer: Sensor? = null
    private var pressureSensor: Sensor? = null
    private var temperatureSensor: Sensor? = null
    private var lightSensor: Sensor? = null
    private var proximitySensor: Sensor? = null
    private var rotationVector: Sensor? = null

    // GPS
    private lateinit var fusedLocationClient: FusedLocationProviderClient
    private var lastLocation: Location? = null

    // Estado de sensores (thread-safe snapshots)
    @Volatile private var accel  = FloatArray(3)
    @Volatile private var gyro   = FloatArray(3)
    @Volatile private var mag    = FloatArray(3)
    @Volatile private var orient = FloatArray(3) // roll, pitch, yaw
    @Volatile private var pressure    = 0f
    @Volatile private var temperature = 0f
    @Volatile private var light       = 0f
    @Volatile private var proximity   = 0f

    // Coroutines
    private val serviceScope = CoroutineScope(Dispatchers.IO + SupervisorJob())

    // ─── Lifecycle ────────────────────────────────────────────

    override fun onCreate() {
        super.onCreate()
        Log.i(TAG, "Service onCreate")

        createNotificationChannel()
        startForeground(NOTIFICATION_ID, buildNotification("Iniciando..."))

        initSensors()
        initGps()
        connectToAwsIot()
    }

    override fun onStartCommand(intent: Intent?, flags: Int, startId: Int): Int = START_STICKY

    override fun onDestroy() {
        super.onDestroy()
        serviceScope.cancel()
        sensorManager.unregisterListener(this)
        if (isConnected.get()) iotManager.disconnect()
        Log.i(TAG, "Service destroyed")
    }

    override fun onBind(intent: Intent?): IBinder? = null

    // ─── Inicialización de sensores ───────────────────────────

    private fun initSensors() {
        sensorManager = getSystemService(SENSOR_SERVICE) as SensorManager

        // Cada sensor con su frecuencia óptima para moto
        accelerometer   = register(Sensor.TYPE_ACCELEROMETER,      SensorManager.SENSOR_DELAY_GAME)
        gyroscope        = register(Sensor.TYPE_GYROSCOPE,           SensorManager.SENSOR_DELAY_GAME)
        magnetometer     = register(Sensor.TYPE_MAGNETIC_FIELD,      SensorManager.SENSOR_DELAY_UI)
        pressureSensor   = register(Sensor.TYPE_PRESSURE,            SensorManager.SENSOR_DELAY_NORMAL)
        temperatureSensor= register(Sensor.TYPE_AMBIENT_TEMPERATURE, SensorManager.SENSOR_DELAY_NORMAL)
        lightSensor      = register(Sensor.TYPE_LIGHT,               SensorManager.SENSOR_DELAY_NORMAL)
        proximitySensor  = register(Sensor.TYPE_PROXIMITY,           SensorManager.SENSOR_DELAY_NORMAL)
        rotationVector   = register(Sensor.TYPE_ROTATION_VECTOR,     SensorManager.SENSOR_DELAY_GAME)

        Log.i(TAG, "Sensores registrados")
    }

    private fun register(type: Int, delay: Int): Sensor? {
        return sensorManager.getDefaultSensor(type)?.also {
            sensorManager.registerListener(this, it, delay)
        } ?: run {
            Log.w(TAG, "Sensor tipo $type no disponible en este dispositivo")
            null
        }
    }

    // ─── GPS ──────────────────────────────────────────────────

    private fun initGps() {
        fusedLocationClient = LocationServices.getFusedLocationProviderClient(this)

        val request = LocationRequest.Builder(
            Priority.PRIORITY_HIGH_ACCURACY, GPS_INTERVAL_MS
        ).apply {
            setMinUpdateIntervalMillis(GPS_INTERVAL_MS / 2)
            setMinUpdateDistanceMeters(1f)
        }.build()

        try {
            fusedLocationClient.requestLocationUpdates(
                request,
                locationCallback,
                Looper.getMainLooper()
            )
            Log.i(TAG, "GPS iniciado")
        } catch (e: SecurityException) {
            Log.e(TAG, "Permiso GPS no concedido: ${e.message}")
        }
    }

    private val locationCallback = object : LocationCallback() {
        override fun onLocationResult(result: LocationResult) {
            lastLocation = result.lastLocation
            lastLocation?.let { loc ->
                // Publicar GPS en su propio topic dedicado
                if (isConnected.get()) publishGps(loc)
            }
        }
    }

    // ─── AWS IoT Core ─────────────────────────────────────────

    private fun connectToAwsIot() {
        iotManager = AWSIotMqttManager(CLIENT_ID, AWS_IOT_ENDPOINT)

        iotManager.apply {
            keepAlive           = 60
            autoReconnect       = true
            maxAutoReconnectAttempts = 10
            reconnectRetryLimits(1, 128) // backoff exponencial 1s→128s
            setCleanSession(false)       // QoS persistente
        }

        try {
            // Carga el keystore con el certificado del dispositivo
            // Archivo: assets/moto_android_01.bks (genera con el script incluido)
            val keystoreStream: InputStream = assets.open("${DEVICE_ID}.bks")
            val keystore = KeyStore.getInstance("BKS")
            keystore.load(keystoreStream, "moto123".toCharArray())

            iotManager.connect(keystore) { status, throwable ->
                when (status) {
                    AWSIotMqttClientStatusCallback.AWSIotMqttClientStatus.Connected -> {
                        isConnected.set(true)
                        Log.i(TAG, "✅ Conectado a AWS IoT Core")
                        updateNotification("Conectado — publicando datos")
                        startPublishLoop()
                    }
                    AWSIotMqttClientStatusCallback.AWSIotMqttClientStatus.ConnectionLost -> {
                        isConnected.set(false)
                        Log.w(TAG, "⚠️ Conexión perdida, reconectando...")
                        updateNotification("Reconectando...")
                    }
                    else -> Log.d(TAG, "IoT status: $status")
                }
            }
        } catch (e: Exception) {
            Log.e(TAG, "Error conectando a IoT: ${e.message}", e)
        }
    }

    // ─── Loop de publicación ──────────────────────────────────

    private fun startPublishLoop() {
        serviceScope.launch {
            while (isActive) {
                if (isConnected.get()) {
                    publishTelemetry()
                }
                delay(PUBLISH_INTERVAL_MS)
            }
        }
    }

    // ─── Builders de payload JSON ─────────────────────────────

    private fun publishTelemetry() {
        val loc = lastLocation

        val payload = JSONObject().apply {
            put("device_id",  DEVICE_ID)
            put("timestamp",  System.currentTimeMillis())
            put("source",     "android_native")

            // IMU
            put("imu", JSONObject().apply {
                put("ax", accel[0].round3())
                put("ay", accel[1].round3())
                put("az", accel[2].round3())
                put("gx", gyro[0].round3())
                put("gy", gyro[1].round3())
                put("gz", gyro[2].round3())
                put("mx", mag[0].round3())
                put("my", mag[1].round3())
                put("mz", mag[2].round3())
                put("roll",  orient[0].round3())
                put("pitch", orient[1].round3())
                put("yaw",   orient[2].round3())
            })

            // Ambiente
            put("environment", JSONObject().apply {
                put("pressure_hpa",   pressure.round3())
                put("temperature_c",  temperature.round3())
                put("light_lux",      light.round3())
                put("proximity_cm",   proximity.round3())
            })

            // GPS snapshot en telemetría combinada
            if (loc != null) {
                put("gps", JSONObject().apply {
                    put("lat",        loc.latitude)
                    put("lng",        loc.longitude)
                    put("alt_m",      loc.altitude.round3())
                    put("speed_kmh",  (loc.speed * 3.6f).round3())
                    put("bearing",    loc.bearing.round3())
                    put("accuracy_m", loc.accuracy.round3())
                    put("provider",   loc.provider ?: "unknown")
                })
            }

            // Metadata del dispositivo
            put("device", JSONObject().apply {
                put("battery_pct",  getBatteryLevel())
                put("is_charging",  isCharging())
                put("android_sdk",  Build.VERSION.SDK_INT)
                put("model",        Build.MODEL)
            })
        }

        publish(TOPIC_TELEMETRY, payload.toString())
    }

    private fun publishGps(loc: Location) {
        val payload = JSONObject().apply {
            put("device_id",  DEVICE_ID)
            put("timestamp",  System.currentTimeMillis())
            put("lat",        loc.latitude)
            put("lng",        loc.longitude)
            put("alt_m",      loc.altitude.round3())
            put("speed_kmh",  (loc.speed * 3.6f).round3())
            put("bearing",    loc.bearing.round3())
            put("accuracy_m", loc.accuracy.round3())
        }
        publish(TOPIC_GPS, payload.toString())
    }

    private fun publish(topic: String, payload: String) {
        try {
            iotManager.publishString(payload, topic, AWSIotMqttQos.QOS1)
        } catch (e: Exception) {
            Log.e(TAG, "Error publicando en $topic: ${e.message}")
        }
    }

    // ─── SensorEventListener ─────────────────────────────────

    override fun onSensorChanged(event: SensorEvent) {
        when (event.sensor.type) {
            Sensor.TYPE_ACCELEROMETER    -> accel = event.values.clone()
            Sensor.TYPE_GYROSCOPE        -> gyro  = event.values.clone()
            Sensor.TYPE_MAGNETIC_FIELD   -> mag   = event.values.clone()
            Sensor.TYPE_PRESSURE         -> pressure    = event.values[0]
            Sensor.TYPE_AMBIENT_TEMPERATURE -> temperature = event.values[0]
            Sensor.TYPE_LIGHT            -> light     = event.values[0]
            Sensor.TYPE_PROXIMITY        -> proximity = event.values[0]
            Sensor.TYPE_ROTATION_VECTOR  -> {
                val rotMatrix = FloatArray(9)
                SensorManager.getRotationMatrixFromVector(rotMatrix, event.values)
                val orientArr = FloatArray(3)
                SensorManager.getOrientation(rotMatrix, orientArr)
                // Convertir radianes a grados
                orient[0] = Math.toDegrees(orientArr[0].toDouble()).toFloat() // azimuth/yaw
                orient[1] = Math.toDegrees(orientArr[1].toDouble()).toFloat() // pitch
                orient[2] = Math.toDegrees(orientArr[2].toDouble()).toFloat() // roll
            }
        }
    }

    override fun onAccuracyChanged(sensor: Sensor?, accuracy: Int) {
        Log.d(TAG, "Precisión cambiada: ${sensor?.name} → $accuracy")
    }

    // ─── Utilidades ───────────────────────────────────────────

    private fun getBatteryLevel(): Int {
        val bm = getSystemService(BATTERY_SERVICE) as BatteryManager
        return bm.getIntProperty(BatteryManager.BATTERY_PROPERTY_CAPACITY)
    }

    private fun isCharging(): Boolean {
        val bm = getSystemService(BATTERY_SERVICE) as BatteryManager
        return bm.isCharging
    }

    private fun Double.round3() = (Math.round(this * 1000.0) / 1000.0)
    private fun Float.round3()  = (Math.round(this * 1000.0) / 1000.0).toFloat()

    // ─── Notificación Foreground ──────────────────────────────

    private fun createNotificationChannel() {
        val channel = NotificationChannel(
            CHANNEL_ID,
            "Moto Telemetría",
            NotificationManager.IMPORTANCE_LOW
        ).apply {
            description = "Servicio de telemetría en background"
            setShowBadge(false)
        }
        (getSystemService(NOTIFICATION_SERVICE) as NotificationManager)
            .createNotificationChannel(channel)
    }

    private fun buildNotification(status: String): Notification {
        return NotificationCompat.Builder(this, CHANNEL_ID)
            .setContentTitle("Moto Telemetría Activa")
            .setContentText(status)
            .setSmallIcon(android.R.drawable.ic_menu_mylocation)
            .setOngoing(true)
            .setPriority(NotificationCompat.PRIORITY_LOW)
            .build()
    }

    private fun updateNotification(status: String) {
        val nm = getSystemService(NOTIFICATION_SERVICE) as NotificationManager
        nm.notify(NOTIFICATION_ID, buildNotification(status))
    }
}
