package com.motoiot

import android.Manifest
import android.bluetooth.BluetoothAdapter
import android.content.pm.PackageManager
import android.os.Bundle
import android.util.Log
import androidx.activity.ComponentActivity
import androidx.activity.compose.setContent
import androidx.compose.material3.MaterialTheme
import androidx.core.app.ActivityCompat
import kotlinx.coroutines.*

class MainActivity : ComponentActivity() {

    private lateinit var btHelper: BluetoothHelper
    private lateinit var awsHelper: AWSIoTHelper
    private lateinit var sensors: SensorCollector

    private var latestArduinoData: MotoData? = null
    private var latestMergedData: MotoData? = null
    private var publishJob: Job? = null

    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)

        // Permisos
        ActivityCompat.requestPermissions(this, arrayOf(
            Manifest.permission.ACCESS_FINE_LOCATION,
            Manifest.permission.BLUETOOTH_CONNECT,
            Manifest.permission.BLUETOOTH_SCAN
        ), 1)

        // Inicializar
        btHelper = BluetoothHelper()
        awsHelper = AWSIoTHelper(this)
        sensors = SensorCollector(this)

        // Configurar Bluetooth
        btHelper.setOnDataReceived { data ->
            latestArduinoData = data
            Log.d("Main", "RPM: ${data.rpm}, Temp: ${data.engineTempC}")
        }

        // Conectar AWS IoT
        awsHelper.connect(
            onSuccess = { Log.i("Main", "AWS conectado") },
            onFailure = { Log.e("Main", "AWS error: ${it.message}") }
        )

        // Iniciar sensores del celular
        sensors.start()

        // Publicar a AWS cada 500ms
        publishJob = CoroutineScope(Dispatchers.IO).launch {
            while (isActive) {
                val merged = sensors.merge(latestArduinoData)
                latestMergedData = merged
                awsHelper.publish(merged)
                delay(500)
            }
        }

        // UI
        setContent {
            MaterialTheme {
                SecondDashboard(latestMergedData)
            }
        }
    }

    override fun onDestroy() {
        super.onDestroy()
        publishJob?.cancel()
        btHelper.disconnect()
        awsHelper.disconnect()
        sensors.stop()
    }
}