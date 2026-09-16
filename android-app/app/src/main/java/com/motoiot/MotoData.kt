package com.motoiot

import org.json.JSONObject

data class MotoData(
    // Desde Arduino (Bluetooth)
    val rpm: Int = 0,
    val engineTempC: Float = 0f,
    val voltageBike: Float = 0f,
    val speedSensorKmh: Float = 0f,
    val odometerKm: Float = 0f,
    val fuelLevelPct: Float = 0f,
    val engineOn: Boolean = false,
    val engineOnSeconds: Long = 0,
    val throttlePositionPct: Float = 0f,

    // Desde Celular (GPS + Sensores)
    val gpsLat: Double = 0.0,
    val gpsLon: Double = 0.0,
    val gpsSpeedKmh: Float = 0f,
    val gpsAltitudeM: Float = 0f,
    val gpsBearingDeg: Float = 0f,

    val accelX: Float = 0f,
    val accelY: Float = 0f,
    val accelZ: Float = 0f,
    val gyroX: Float = 0f,
    val gyroY: Float = 0f,
    val gyroZ: Float = 0f,

    val rotationRollDeg: Float = 0f,
    val rotationPitchDeg: Float = 0f,
    val rotationYawDeg: Float = 0f,

    val batteryCelPercent: Int = 0,
    val batteryCelCharging: Boolean = false,

    // Metadata
    val timestamp: Long = System.currentTimeMillis() / 1000
) {
    fun toJSON(): JSONObject = JSONObject().apply {
        put("device_id", "furiosa_01")
        put("timestamp", timestamp)
        put("year", 2026); put("month", 8); put("day", 31)

        // Arduino
        put("rpm", rpm)
        put("engine_temp_c", engineTempC)
        put("voltage_bike", voltageBike)
        put("speed_sensor_kmh", speedSensorKmh)
        put("odometer_km", odometerKm)
        put("fuel_level_pct", fuelLevelPct)
        put("engine_on", engineOn)
        put("engine_on_seconds", engineOnSeconds)
        put("throttle_position_pct", throttlePositionPct)

        // Celular
        put("gps_lat", gpsLat)
        put("gps_lon", gpsLon)
        put("gps_speed_kmh", gpsSpeedKmh)
        put("gps_altitude_m", gpsAltitudeM)
        put("gps_bearing_deg", gpsBearingDeg)
        put("accel_x", accelX); put("accel_y", accelY); put("accel_z", accelZ)
        put("gyro_x", gyroX); put("gyro_y", gyroY); put("gyro_z", gyroZ)
        put("rotation_roll_deg", rotationRollDeg)
        put("rotation_pitch_deg", rotationPitchDeg)
        put("rotation_yaw_deg", rotationYawDeg)
        put("battery_cel_percent", batteryCelPercent)
        put("battery_cel_charging", batteryCelCharging)
    }
}