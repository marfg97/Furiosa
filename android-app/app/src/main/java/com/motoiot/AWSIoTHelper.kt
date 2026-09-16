package com.motoiot

import android.content.Context
import android.util.Log
import com.amazonaws.auth.CognitoCachingCredentialsProvider
import com.amazonaws.mobileconnectors.iot.*
import com.amazonaws.regions.Regions
import org.json.JSONObject
import java.io.InputStream
import java.security.KeyStore
import java.security.cert.CertificateFactory

class AWSIoTHelper(private val context: Context) {

    companion object {
        private const val TAG = "AWSIoTHelper"
        private const val COGNITO_POOL_ID = "us-east-1:XXXXXXXX-XXXX-XXXX-XXXX-XXXXXXXXXXXX"
        private const val IOT_ENDPOINT = "aij2tvc7hzox1-ats.iot.us-east-1.amazonaws.com"
        private const val CLIENT_ID = "furiosa_01"
        private const val TOPIC = "moto/data"
    }

    private var mqttManager: AWSIotMqttManager? = null
    private var isConnected = false

    fun connect(onSuccess: () -> Unit = {}, onFailure: (Exception) -> Unit = {}) {
        try {
            val credentials = CognitoCachingCredentialsProvider(
                context.applicationContext, COGNITO_POOL_ID, Regions.US_EAST_1
            )
            mqttManager = AWSIotMqttManager(CLIENT_ID, IOT_ENDPOINT)
            mqttManager?.setCleanSession(true)
            mqttManager?.setKeepAlive(300)

            // Cargar certificados desde res/raw
            val keyStore = createKeyStore()

            mqttManager?.connect(keyStore) { status, throwable ->
                if (throwable != null) { onFailure(Exception(throwable)); return@connect }
                if (status == AWSIotMqttClientStatusCallback.AWSIotMqttClientStatus.Connected) {
                    isConnected = true
                    Log.i(TAG, "✅ Conectado a AWS IoT")
                    onSuccess()
                }
            }
        } catch (e: Exception) {
            onFailure(e)
        }
    }

    private fun createKeyStore(): KeyStore {
        val certStream: InputStream = context.resources.openRawResource(R.raw.certificate)
        val keyStream: InputStream = context.resources.openRawResource(R.raw.private_key)

        val cert = CertificateFactory.getInstance("X.509").generateCertificate(certStream)
        val keyStore = KeyStore.getInstance("PKCS12")
        keyStore.load(null, null)
        keyStore.setCertificateEntry("cert", cert)
        return keyStore
    }

    fun publish(data: MotoData) {
        if (!isConnected) { connect(); return }
        try {
            mqttManager?.publishString(data.toJSON().toString(), TOPIC, AWSIotMqttQos.QOS1) { t ->
                t?.let { Log.e(TAG, "Error publicando: ${it.message}") }
            }
            Log.d(TAG, "📤 Datos publicados")
        } catch (e: Exception) {
            Log.e(TAG, "Error publish: ${e.message}")
        }
    }

    fun disconnect() {
        mqttManager?.disconnect()
        isConnected = false
    }
}