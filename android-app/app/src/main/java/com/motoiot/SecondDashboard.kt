package com.motoiot

import androidx.compose.foundation.layout.*
import androidx.compose.material3.*
import androidx.compose.runtime.Composable
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp

@Composable
fun SecondDashboard(data: MotoData?) {
    if (data == null) {
        Box(Modifier.fillMaxSize(), contentAlignment = Alignment.Center) {
            CircularProgressIndicator()
        }
        return
    }

    Column(
        modifier = Modifier.fillMaxSize().padding(12.dp),
        verticalArrangement = Arrangement.spacedBy(8.dp)
    ) {
        // Header
        Text("🏍️ FURIOSA · Segundo Tablero", fontWeight = FontWeight.Bold, fontSize = 18.sp)

        // Card: Arduino data
        Card(Modifier.fillMaxWidth()) {
            Column(Modifier.padding(12.dp)) {
                Text("🔧 Motor", fontWeight = FontWeight.SemiBold)
                Row(Modifier.fillMaxWidth(), Arrangement.SpaceBetween) {
                    Text("RPM: ${data.rpm}")
                    Text("Temp: ${data.engineTempC.toInt()}°C",
                        color = if (data.engineTempC > 95) Color.Red else Color.Green)
                }
                Row(Modifier.fillMaxWidth(), Arrangement.SpaceBetween) {
                    Text("Vel: ${data.speedSensorKmh.toInt()} km/h")
                    Text("Odo: ${data.odometerKm.toInt()} km")
                }
                Row(Modifier.fillMaxWidth(), Arrangement.SpaceBetween) {
                    Text("Voltaje: ${data.voltageBike}V")
                    Text("Gas: ${data.fuelLevelPct.toInt()}%")
                }
            }
        }

        // Card: GPS
        Card(Modifier.fillMaxWidth()) {
            Column(Modifier.padding(12.dp)) {
                Text("📍 GPS", fontWeight = FontWeight.SemiBold)
                Text("Lat: ${"%.5f".format(data.gpsLat)}, Lon: ${"%.5f".format(data.gpsLon)}")
                Text("Vel GPS: ${"%.1f".format(data.gpsSpeedKmh)} km/h · Alt: ${data.gpsAltitudeM.toInt()}m")
            }
        }

        // Card: IMU
        Card(Modifier.fillMaxWidth()) {
            Column(Modifier.padding(12.dp)) {
                Text("📳 Sensores", fontWeight = FontWeight.SemiBold)
                Row(Modifier.fillMaxWidth(), Arrangement.SpaceBetween) {
                    Text("Roll: ${"%.1f".format(data.rotationRollDeg)}°")
                    Text("Pitch: ${"%.1f".format(data.rotationPitchDeg)}°")
                    Text("Yaw: ${"%.1f".format(data.rotationYawDeg)}°")
                }
                Text("Acel: X=${"%.2f".format(data.accelX)} Y=${"%.2f".format(data.accelY)} Z=${"%.2f".format(data.accelZ)}")
            }
        }

        // Card: Batería
        Card(Modifier.fillMaxWidth()) {
            Row(Modifier.padding(12.dp), Arrangement.SpaceBetween) {
                Text("🔋 Batería: ${data.batteryCelPercent}%")
                Text(if (data.batteryCelCharging) "⚡ Cargando" else "🔋 Descargando")
            }
        }

        // Estado motor
        Text(
            if (data.engineOn) "🟢 Motor Encendido · ${data.engineOnSeconds}s" else "🔴 Motor Apagado",
            fontWeight = FontWeight.Bold,
            color = if (data.engineOn) Color.Green else Color.Gray
        )
    }
}