cat SensorCollector.kt
package com.tuapp.motoiot

import android.Manifest
import android.content.Context
import android.content.pm.PackageManager
import android.hardware.Sensor
import android.hardware.SensorEvent
import android.hardware.SensorEventListener             import android.hardware.SensorManager
import android.os.BatteryManager
import android.os.Looper
import androidx.core.content.ContextCompat
import com.google.android.gms.location.*
import kotlinx.coroutines.*
import kotlinx.coroutines.channels.awaitClose
import kotlinx.coroutines.flow.Flow
import kotlinx.coroutines.flow.callbackFlow
import org.json.JSONObject                              import kotlin.math.sqrt
                                                        class SensorCollector(
    private val context: Context,                           private val awsHelper: AWSIoTHelper
) {

    private lateinit var fusedLocationClient: FusedLocationProviderClient
    private lateinit var locationRequest: LocationRequest
    private lateinit var locationCallback: LocationCallback

    private val sensorManager = context.getSystemService(Context.SENSOR_SERVICE) as SensorManager

    // Últimos valores de sensores
    private var lastLocation: Location? = null
    private var lastAccel = FloatArray(3)
    private var lastGyro = FloatArray(3)
    private var lastGravity = FloatArray(3)
    private var lastMagnet = FloatArray(3)

    // Calculados
    private var inclination = 0f
    private var accelerationMagnitude = 0f

    private var isCollecting = false
    private var collectJob: Job? = null

    // Flujo para datos combinados en tiempo real
    val sensorDataFlow: Flow<JSONObject> = callbackFlow {
        if (!isCollecting) {
            startCollecting()
        }

        // Emitir datos cada 2 segundos
        val job = launch {
            while (isActive) {
                val data = buildSensorData()
                trySend(data)
                delay(2000) // 2 segundos
            }
        }

        awaitClose {
            job.cancel()
            stopCollecting()
        }
    }

    fun startCollecting() {
        if (isCollecting) return
        isCollecting = true

        setupLocationUpdates()
        setupSensors()
    }

    fun stopCollecting() {
        isCollecting = false
        fusedLocationClient?.removeLocationUpdates(locationCallback)
        sensorManager.unregisterListener(sensorEventListener)
    }

    private fun setupLocationUpdates() {
        fusedLocationClient = LocationServices.getFusedLocationProviderClient(context)

        locationRequest = LocationRequest.Builder(
            Priority.PRIORITY_HIGH_ACCURACY,
            1000L // 1 segundo
        ).apply {
            setMinUpdateIntervalMillis(500L)
            setMaxUpdateDelayMillis(2000L)
        }.build()

        locationCallback = object : LocationCallback() {
            override fun onLocationResult(result: LocationResult) {
                lastLocation = result.lastLocation
            }
        }

        if (ContextCompat.checkSelfPermission(
                context,
                Manifest.permission.ACCESS_FINE_LOCATION
            ) == PackageManager.PERMISSION_GRANTED
        ) {
            fusedLocationClient.requestLocationUpdates(
                locationRequest,
                locationCallback,
                Looper.getMainLooper()
            )
        }
    }

    private fun setupSensors() {
        // Acelerómetro
        sensorManager.getDefaultSensor(Sensor.TYPE_ACCELEROMETER)?.let {
            sensorManager.registerListener(sensorEventListener, it, SensorManager.SENSOR_DELAY_UI)
        }

        // Giroscopio
        sensorManager.getDefaultSensor(Sensor.TYPE_GYROSCOPE)?.let {
            sensorManager.registerListener(sensorEventListener, it, SensorManager.SENSOR_DELAY_UI)
        }

        // Gravedad (para inclinación)
        sensorManager.getDefaultSensor(Sensor.TYPE_GRAVITY)?.let {
            sensorManager.registerListener(sensorEventListener, it, SensorManager.SENSOR_DELAY_UI)
        }

        // Magnetómetro (para brújula)
        sensorManager.getDefaultSensor(Sensor.TYPE_MAGNETIC_FIELD)?.let {
            sensorManager.registerListener(sensorEventListener, it, SensorManager.SENSOR_DELAY_UI)
        }
    }

    private val sensorEventListener = object : SensorEventListener {
        override fun onSensorChanged(event: SensorEvent) {
            when (event.sensor.type) {
                Sensor.TYPE_ACCELEROMETER -> {
                    lastAccel = event.values.clone()
                    accelerationMagnitude = sqrt(
                        lastAccel[0] * lastAccel[0] +
                        lastAccel[1] * lastAccel[1] +
                        lastAccel[2] * lastAccel[2]
                    )
                }
                Sensor.TYPE_GYROSCOPE -> {
                    lastGyro = event.values.clone()
                }
                Sensor.TYPE_GRAVITY -> {
                    lastGravity = event.values.clone()
                    // Calcular inclinación (ángulo en eje X)
                    inclination = Math.toDegrees(
                        Math.atan2(lastGravity[0].toDouble(), lastGravity[2].toDouble())
                    ).toFloat()
                }
                Sensor.TYPE_MAGNETIC_FIELD -> {
                    lastMagnet = event.values.clone()
                }
            }
        }
        override fun onAccuracyChanged(sensor: Sensor?, accuracy: Int) {}
    }

    private fun getBatteryStatus(): JSONObject {
        val batteryManager = context.getSystemService(Context.BATTERY_SERVICE) as BatteryManager
        val level = batteryManager.getIntProperty(BatteryManager.BATTERY_PROPERTY_CAPACITY)
        val temperature = batteryManager.getIntProperty(
            BatteryManager.BATTERY_PROPERTY_TEMPERATURE
        ) / 10f
        val voltage = batteryManager.getIntProperty(
            BatteryManager.BATTERY_PROPERTY_VOLTAGE
        ) / 1000f

        return JSONObject().apply {
            put("level", level)
            put("temperature_celsius", temperature)
            put("voltage", voltage)
            put("is_charging", batteryManager.isCharging())
        }
    }

    private fun buildSensorData(): JSONObject {
        return JSONObject().apply {
            // GPS
            put("gps_lat", lastLocation?.latitude ?: 0.0)
            put("gps_lon", lastLocation?.longitude ?: 0.0)
            put("gps_speed_kmh", (lastLocation?.speed ?: 0f) * 3.6f)
            put("gps_altitude", lastLocation?.altitude ?: 0.0)
            put("gps_bearing", lastLocation?.bearing ?: 0f)
            put("gps_accuracy", lastLocation?.accuracy ?: 0f)

            // Acelerómetro
            put("accel_x", lastAccel[0])
            put("accel_y", lastAccel[1])
            put("accel_z", lastAccel[2])
            put("accel_magnitude", accelerationMagnitude)

            // Giroscopio
            put("gyro_x", lastGyro[0])
            put("gyro_y", lastGyro[1])
            put("gyro_z", lastGyro[2])

            // Gravedad e inclinación
            put("gravity_x", lastGravity[0])
            put("gravity_y", lastGravity[1])
            put("gravity_z", lastGravity[2])
            put("inclination_degrees", inclination)

            // Magnetómetro
            put("mag_x", lastMagnet[0])
            put("mag_y", lastMagnet[1])
            put("mag_z", lastMagnet[2])

            // Batería del celular
            put("battery", getBatteryStatus())
        }
    }
}
