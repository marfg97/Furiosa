#!/bin/bash
# ─────────────────────────────────────────────────────────────
# generate_keystore.sh
# Convierte los certificados X.509 de AWS IoT Core al formato
# BKS que necesita el SDK de AWS para Android.
#
# PRE-REQUISITOS:
#   - Java instalado (keytool)
#   - openssl instalado
#   - Descargar Bouncy Castle provider JAR:
#     https://repo1.maven.org/maven2/org/bouncycastle/bcprov-jdk15on/1.70/bcprov-jdk15on-1.70.jar
#
# INPUTS (genera Terraform o descarga desde IoT Core console):
#   - certificate.pem.crt   → certificado del dispositivo
#   - private.pem.key       → llave privada
#   - AmazonRootCA1.pem     → CA raíz de AWS
#
# USO: bash generate_keystore.sh moto_android_01
# ─────────────────────────────────────────────────────────────

DEVICE_ID=${1:-"moto_android_01"}
KEYSTORE_PASS="moto123"
BC_JAR="bcprov-jdk15on-1.70.jar"

echo "🔧 Generando keystore para dispositivo: $DEVICE_ID"

# ── 1. Descargar CA raíz de AWS si no existe ──────────────────
if [ ! -f "AmazonRootCA1.pem" ]; then
    echo "📥 Descargando Amazon Root CA 1..."
    curl -s https://www.amazontrust.com/repository/AmazonRootCA1.pem -o AmazonRootCA1.pem
fi

# ── 2. Convertir certificado + clave a PKCS12 ─────────────────
echo "🔄 Convirtiendo a PKCS12..."
openssl pkcs12 -export \
    -in certificate.pem.crt \
    -inkey private.pem.key \
    -out device_cert.p12 \
    -name "${DEVICE_ID}" \
    -passout pass:${KEYSTORE_PASS}

# ── 3. Crear BKS con el certificado del dispositivo ───────────
echo "🔑 Creando BKS keystore del dispositivo..."
keytool -importkeystore \
    -srckeystore device_cert.p12 \
    -srcstoretype PKCS12 \
    -srcstorepass ${KEYSTORE_PASS} \
    -destkeystore ${DEVICE_ID}.bks \
    -deststoretype BKS \
    -deststorepass ${KEYSTORE_PASS} \
    -provider org.bouncycastle.jce.provider.BouncyCastleProvider \
    -providerpath ${BC_JAR} \
    -noprompt

# ── 4. Crear BKS con la CA raíz de AWS ───────────────────────
echo "🔑 Creando BKS truststore con AWS Root CA..."
keytool -import \
    -alias AmazonRootCA \
    -file AmazonRootCA1.pem \
    -keystore aws_root_ca.bks \
    -storetype BKS \
    -storepass ${KEYSTORE_PASS} \
    -provider org.bouncycastle.jce.provider.BouncyCastleProvider \
    -providerpath ${BC_JAR} \
    -noprompt

# ── 5. Verificar ──────────────────────────────────────────────
echo ""
echo "✅ Keystores generados:"
echo "   ${DEVICE_ID}.bks  → copiar a android/app/src/main/assets/"
echo "   aws_root_ca.bks   → copiar a android/app/src/main/assets/"
echo ""
echo "📋 Contenido del keystore del dispositivo:"
keytool -list -keystore ${DEVICE_ID}.bks \
    -storetype BKS \
    -storepass ${KEYSTORE_PASS} \
    -provider org.bouncycastle.jce.provider.BouncyCastleProvider \
    -providerpath ${BC_JAR}

# ── 6. Obtener el endpoint de IoT ─────────────────────────────
echo ""
echo "📡 Tu endpoint de AWS IoT Core:"
aws iot describe-endpoint --endpoint-type iot:Data-ATS --query 'endpointAddress' --output text

echo ""
echo "🎯 PRÓXIMOS PASOS:"
echo "   1. Copia los .bks a:  android/app/src/main/assets/"
echo "   2. Actualiza AWS_IOT_ENDPOINT en MotoTelemetryService.kt"
echo "   3. Agrega permisos en AndroidManifest.xml (ver SETUP.md)"
