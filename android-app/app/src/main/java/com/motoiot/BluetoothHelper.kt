package com.motoiot

import android.bluetooth.BluetoothAdapter
import android.bluetooth.BluetoothDevice
import android.bluetooth.BluetoothSocket
import android.util.Log
import kotlinx.coroutines.*
import java.io.InputStream
import java.io.OutputStream
import java.util.UUID

class BluetoothHelper {
    companion object {
        private const val TAG = "BluetoothHelper"
        private val SPP_UUID: UUID = UUID.fromString("00001101-0000-1000-8000-00805F9B34FB")
    }

    private var socket: BluetoothSocket? = null
    private var inputStream: InputStream? = null
    private var outputStream: OutputStream? = null
    private var readJob: Job? = null

    private var onDataReceived: ((MotoData) -> Unit)? = null

    fun setOnDataReceived(callback: (MotoData) -> Unit) {
        this.onDataReceived = callback
    }

    /**
     * Conectar al Arduino por Bluetooth (HC-05/HC-06)
     * El dispositivo debe estar previamente emparejado
     */
    fun connect(device: BluetoothDevice): Boolean {
        return try {
            socket = device.createRfcommSocketToServiceRecord(SPP_UUID)
            socket?.connect()
            inputStream = socket?.inputStream
            outputStream = socket?.outputStream
            Log.i(TAG, "✅ Conectado a ${device.name}")
            true
        } catch (e: Exception) {
            Log.e(TAG, "❌ Error al conectar: ${e.message}")
            false
        }
    }

    /**
     * Iniciar lectura continua de datos del Arduino
     */
    fun startReading() {
        readJob = CoroutineScope(Dispatchers.IO).launch {
            val buffer = ByteArray(256)
            while (isActive && socket?.isConnected == true) {
                try {
                    val bytes = inputStream?.read(buffer) ?: 0
                    if (bytes > 0) {
                        val line = String(buffer, 0, bytes).trim()
                        parseArduinoLine(line)?.let { data ->
                            withContext(Dispatchers.Main) {
                                onDataReceived?.invoke(data)
                            }
                        }
                    }
                } catch (e: Exception) {
                    Log.e(TAG, "Error leyendo: ${e.message}")
                    break
                }
            }
        }
    }

    /**
     * Parsea la línea enviada por Arduino
     * Formato: RPM,TEMP,VOLT,SPEED,ODO,FUEL,ON,ON_SEC,THROTTLE
     */
    private fun parseArduinoLine(line: String): MotoData? {
        return try {
            val parts = line.split(",")
            if (parts.size < 9) return null
            MotoData(
                rpm = parts[0].toIntOrNull() ?: 0,
                engineTempC = parts[1].toFloatOrNull() ?: 0f,
                voltageBike = parts[2].toFloatOrNull() ?: 0f,
                speedSensorKmh = parts[3].toFloatOrNull() ?: 0f,
                odometerKm = parts[4].toFloatOrNull() ?: 0f,
                fuelLevelPct = parts[5].toFloatOrNull() ?: 0f,
                engineOn = parts[6] == "1",
                engineOnSeconds = parts[7].toLongOrNull() ?: 0L,
                throttlePositionPct = parts[8].toFloatOrNull() ?: 0f
            )
        } catch (e: Exception) {
            null
        }
    }

    fun disconnect() {
        readJob?.cancel()
        try { socket?.close() } catch (_: Exception) {}
        socket = null
    }
}