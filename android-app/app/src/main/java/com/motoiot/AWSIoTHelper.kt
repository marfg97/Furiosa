package com.motoiot

import android.content.Context
import com.amazonaws.auth.CognitoCachingCredentialsProvider
import com.amazonaws.mobileconnectors.iot.*
import com.amazonaws.regions.Regions
import kotlinx.coroutines.channels.awaitClose
import kotlinx.coroutines.flow.callbackFlow
import kotlinx.coroutines.flow.Flow
import org.json.JSONObject

class AWSIoTHelper(private val context: Context) {
    
    companion object {
        // ======== CONFIGURACIÓN  ========
        private const val COGNITO_POOL_ID = "us-east-1:XXXXXXXX-XXXX-XXXX-XXXX-XXXXXXXXXXXX"
        private const val AWS_REGION = Regions.US_EAST_1
        private const val IOT_ENDPOINT = "a2tqmj5n6nkz0y-ats.iot.us-east-1.amazonaws.com"
        private const val CLIENT_ID = "android_moto_180cc"
        private const val TOPIC_PUBLISH = "moto/data"
        // =====================================================
        
        private const val KEYSTORE_NAME = "iot_keystore"
        private const val KEYSTORE_PASSWORD = "TuContraseñaSegura"
        private const val CERT_ALIAS = "moto_cert"
    }
    
    private var mqttManager: AWSIotMqttManager? = null
    private var credentialsProvider: CognitoCachingCredentialsProvider? = null
    private var isConnected = false
    
    // Flujo para escuchar mensajes entrantes (comandos desde la nube)
    val incomingMessages = callbackFlow {
        if (mqttManager == null) {
            // Inicializar si no está creado
            setup()
        }
        
        // Suscribirse a tópico de comandos
        mqttManager?.subscribeToTopic(
            "moto/comandos",
            AWSIotMqttQos.QOS1,
            { topic, data ->
                val message = String(data)
                trySend(message)
            }
        )
        
        awaitClose {
            mqttManager?.unsubscribeTopic("moto/comandos")
        }
    }
    
    fun setup() {
        // 1. Crear proveedor de credenciales Cognito
        credentialsProvider = CognitoCachingCredentialsProvider(
            context.applicationContext,
            COGNITO_POOL_ID,
            AWS_REGION
        )
        
        // 2. Crear MQTT Manager con WebSockets (puerto 443)
        mqttManager = AWSIotMqttManager(CLIENT_ID, IOT_ENDPOINT)
        mqttManager?.apply {
            setCleanSession(true)
            setKeepAlive(300) // 5 minutos, ahorra batería
        }
    }
    
    fun connect(onSuccess: () -> Unit, onFailure: (Exception) -> Unit) {
        if (isConnected) {
            onSuccess()
            return
        }
        
        // Verificar si ya tenemos Keystore con certificado
        val keystorePath = context.filesDir.absolutePath
        val keystoreExists = AWSIotKeystoreHelper.isKeystorePresent(keystorePath, KEYSTORE_NAME)
        
        if (keystoreExists) {
            // Usar certificado existente
            val keyStore = AWSIotKeystoreHelper.getIotKeystore(
                CERT_ALIAS, keystorePath, KEYSTORE_NAME, KEYSTORE_PASSWORD
            )
            connectWithKeystore(keyStore, onSuccess, onFailure)
        } else {
            // Generar nuevo certificado (solo primera vez)
            generateAndStoreCertificate(keystorePath, onSuccess, onFailure)
        }
    }
    
    
// cargar certificados desde res/raw/
private fun generateAndStoreCertificate(
    keystorePath: String,
    onSuccess: () -> Unit,
    onFailure: (Exception) -> Unit
) {
    try {
        // Cargar certificados desde res/raw/
        val certInputStream = context.resources.openRawResource(R.raw.certificate)
        val privateKeyInputStream = context.resources.openRawResource(R.raw.private_key)
        
        val certString = certInputStream.bufferedReader().use { it.readText() }
        val privateKeyString = privateKeyInputStream.bufferedReader().use { it.readText() }
        
        // Guardar en Keystore
        AWSIotKeystoreHelper.saveCertificateAndPrivateKey(
            CERT_ALIAS,
            certString,
            privateKeyString,
            keystorePath,
            KEYSTORE_NAME,
            KEYSTORE_PASSWORD
        )
        
        // Conectar con el nuevo Keystore
        val keyStore = AWSIotKeystoreHelper.getIotKeystore(
            CERT_ALIAS, keystorePath, KEYSTORE_NAME, KEYSTORE_PASSWORD
        )
        connectWithKeystore(keyStore, onSuccess, onFailure)
        
    } catch (e: Exception) {
        onFailure(Exception("Error al cargar certificados: ${e.message}"))
    }
}
    
    private fun connectWithKeystore(
    keyStore: java.security.KeyStore,
    onSuccess: () -> Unit,
    onFailure: (Exception) -> Unit
) {
    mqttManager?.connect(keyStore, object : AWSIotMqttClientStatusCallback {
        override fun onStatusChanged(status: AWSIotMqttClientStatus, throwable: Throwable?) {
            if (throwable != null) {
                onFailure(Exception(throwable))
                return
            }
            
            when (status) {
                AWSIotMqttClientStatus.Connected -> {
                    isConnected = true
                    onSuccess()
                }
                else -> {
                    onFailure(Exception("Error de conexión: $status"))
                }
            }
        }
    })
}
    
    fun publishData(data: JSONObject) {
        if (!isConnected) {
            Log.W("AWSiotHelper","❌ No conectado a AWS IoT")
            return
        }
        
        // Agregar metadata
        data.put("timestamp", System.currentTimeMillis())
        data.put("client_id", CLIENT_ID)
        
        mqttManager?.publishString(
            data.toString(),
            TOPIC_PUBLISH,
            AWSIotMqttQos.QOS1
        ) { throwable ->
            throwable?.printStackTrace()
        }
    }
    
    fun disconnect() {
        mqttManager?.disconnect()
        isConnected = false
    }
}
