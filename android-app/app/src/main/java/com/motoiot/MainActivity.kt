package com.tuapp.motoiot

import android.Manifest
import android.content.pm.PackageManager
import android.os.Bundle
import androidx.activity.ComponentActivity
import androidx.activity.compose.setContent
import androidx.compose.foundation.layout.*
import androidx.compose.material3.*
import androidx.compose.runtime.*
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.unit.dp
import androidx.core.app.ActivityCompat
import kotlinx.coroutines.launch

class MainActivity : ComponentActivity() {
    
    private lateinit var awsHelper: AWSIoTHelper
    private lateinit var sensorCollector: SensorCollector
    
    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        
        // Solicitar permisos
        requestPermissions()
        
        // Inicializar AWS IoT
        awsHelper = AWSIoTHelper(this)
        awsHelper.setup()
        
        // Conectar a AWS IoT
        awsHelper.connect(
            onSuccess = { println("✅ Conectado a AWS IoT Core") },
            onFailure = { println("❌ Error: ${it.message}") }
        )
        
        // Inicializar sensores
        sensorCollector = SensorCollector(this, awsHelper)
        
        setContent {
            MaterialTheme {
                MotoDashboard(sensorCollector, awsHelper)
            }
        }
    }
    
    private fun requestPermissions() {
        val permissions = arrayOf(
            Manifest.permission.ACCESS_FINE_LOCATION,
            Manifest.permission.ACCESS_COARSE_LOCATION,
            Manifest.permission.ACCESS_BACKGROUND_LOCATION
        )
        if (ActivityCompat.checkSelfPermission(this, permissions[0]) 
            != PackageManager.PERMISSION_GRANTED
        ) {
            ActivityCompat.requestPermissions(this, permissions, 1)
        }
    }
    
    override fun onDestroy() {
        super.onDestroy()
        awsHelper.disconnect()
        sensorCollector.stopCollecting()
    }
}

@Composable
fun MotoDashboard(
    sensorCollector: SensorCollector,
    awsHelper: AWSIoTHelper
) {
    var connectionStatus by remember { mutableStateOf("Conectando...") }
    var lastData by remember { mutableStateOf<JSONObject?>(null) }
    val scope = rememberCoroutineScope()
    
    // Iniciar recolección de datos
    LaunchedEffect(Unit) {
        sensorCollector.startCollecting()
        sensorCollector.sensorDataFlow.collect { data ->
            lastData = data
            awsHelper.publishData(data)
        }
    }
    
    // Escuchar mensajes entrantes (comandos)
    LaunchedEffect(Unit) {
        awsHelper.incomingMessages.collect { message ->
            // Procesar comandos desde la nube
            println("📩 Comando recibido: $message")
        }
    }
    
    Column(
        modifier = Modifier
            .fillMaxSize()
            .padding(16.dp),
        horizontalAlignment = Alignment.CenterHorizontally
    ) {
        Text(
            text = "🏍️ Moto IoT Dashboard",
            style = MaterialTheme.typography.headlineMedium
        )
        
        Spacer(modifier = Modifier.height(16.dp))
        
        // Estado de conexión AWS
        Text(
            text = "🟢 Conectado a AWS IoT",
            color = MaterialTheme.colorScheme.primary,
            style = MaterialTheme.typography.bodyLarge
        )
        
        Spacer(modifier = Modifier.height(24.dp))
        
        if (lastData != null) {
            val data = lastData!!
            
            Card(
                modifier = Modifier.fillMaxWidth(),
                colors = CardDefaults.cardColors(
                    containerColor = MaterialTheme.colorScheme.secondaryContainer
                )
            ) {
                Column(modifier = Modifier.padding(16.dp)) {
                    Text("📍 GPS", style = MaterialTheme.typography.titleMedium)
                    Text("Lat: ${data.optDouble("gps_lat", 0.0)}")
                    Text("Lon: ${data.optDouble("gps_lon", 0.0)}")
                    Text("Vel: ${String.format("%.1f", data.optDouble("gps_speed_kmh", 0.0))} km/h")
                    
                    Spacer(modifier = Modifier.height(8.dp))
                    
                    Text("📳 Sensores", style = MaterialTheme.typography.titleMedium)
                    Text("Inclinación: ${String.format("%.1f", data.optDouble("inclination_degrees", 0.0))}°")
                    Text("Aceleración: ${String.format("%.2f", data.optDouble("accel_magnitude", 0.0))} g")
                    
                    Spacer(modifier = Modifier.height(8.dp))
                    
                    Text("🔋 Batería", style = MaterialTheme.typography.titleMedium)
                    val battery = data.optJSONObject("battery")
                    Text("Nivel: ${battery?.optInt("level", 0)}%")
                    Text("Temp: ${battery?.optDouble("temperature_celsius", 0.0)}°C")
                }
            }
        } else {
            CircularProgressIndicator()
            Text("Esperando datos de sensores...")
        }
        
        Spacer(modifier = Modifier.height(16.dp))
        
        Button(
            onClick = {
                // Probar envío manual
                val testData = JSONObject().apply {
                    put("test", "manual")
                    put("timestamp", System.currentTimeMillis())
                }
                awsHelper.publishData(testData)
            }
        ) {
            Text("📤 Enviar prueba")
        }
    }
}
