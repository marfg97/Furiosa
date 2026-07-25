package com.tuapp.motoiot

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
        // ======== CONFIGURACIÓN (CAMBIA ESTOS VALORES) ========
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
    
    private fun generateAndStoreCertificate(
        keystorePath: String,
        onSuccess: () -> Unit,
        onFailure: (Exception) -> Unit
    ) {
        // Esto requiere políticas IAM con permisos para crear certificados
        // Es más sencillo usar el certificado que ya descargaste
        // Por ahora, asumimos que ya existe (lo pones manualmente)
        onFailure(Exception("Certificado no encontrado. Coloca certificate.pem y private.key en res/raw/"))
    }
    
    private fun connectWithKeystore(
        keyStore: java.security.KeyStore,
        onSuccess: () -> Unit,
        onFailure: (Exception) -> Unit
    ) {
        mqttManager?.connect(keyStore) { status, throwable ->
            if (throwable != null) {
                onFailure(throwable)
                return@connect
            }
            
            when (status) {
                AWSIotMqttClientStatusCallback.AWSIotMqttClientStatus.Connected -> {
                    isConnected = true
                    onSuccess()
                }
                else -> {
                    onFailure(Exception("Error de conexión: $status"))
                }
            }
        }
    }
    
    fun publishData(data: JSONObject) {
        if (!isConnected) {
            println("❌ No conectado a AWS IoT")
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
