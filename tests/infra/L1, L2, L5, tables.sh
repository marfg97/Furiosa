#!/bin/bash
echo "==========================================="
echo "  PRUEBA COMPLETA - L1, L2, L5"
echo "==========================================="

DEVICE="moto_android_01"
REGION="us-east-1"

# --- PRUEBA 1: Lectura normal ---
echo ""
echo "🧪 PRUEBA 1: Lectura normal (sin alertas)"
aws iot-data publish --topic "moto/data" --region $REGION --payload '{
  "device_id": "'$DEVICE'", "timestamp": '$(date +%s)',
  "year": 2026, "month": 10, "day": 16,
  "rpm": 4200, "engine_temp_c": 85.0, "voltage_bike": 13.5,
  "engine_on": true
}'
sleep 5

echo "📊 DeviceState:"
aws dynamodb get-item --table-name Furiosa_DeviceState --key '{"device_id":{"S":"'$DEVICE'"}}' --region $REGION --query "Item.{RPM:rpm.N,Temp:engine_temp.N,LastSeen:last_seen.N}" --output table

# --- PRUEBA 2: Temperatura crítica ---
echo ""
echo "🔥 PRUEBA 2: Temperatura crítica"
aws iot-data publish --topic "moto/data" --region $REGION --payload '{
  "device_id": "'$DEVICE'", "timestamp": '$(date +%s)',
  "year": 2026, "month": 10, "day": 16,
  "rpm": 7500, "engine_temp_c": 97.5, "engine_on": true
}'
sleep 8

echo "⚠️ Alertas generadas:"
aws dynamodb scan --table-name Furiosa_Alerts --limit 5 --region $REGION --query "Items[*].{Metric:metric.S,Level:level.S,Message:message.S}" --output table

# --- PRUEBA 3: Voltaje bajo ---
echo ""
echo "⚡ PRUEBA 3: Voltaje crítico"
aws iot-data publish --topic "moto/data" --region $REGION --payload '{
  "device_id": "'$DEVICE'", "timestamp": '$(date +%s)',
  "year": 2026, "month": 10, "day": 16,
  "rpm": 3000, "voltage_bike": 11.2, "engine_on": true
}'
sleep 8

echo "⚠️ Alertas acumuladas:"
aws dynamodb scan --table-name Furiosa_Alerts --limit 10 --region $REGION --query "Count" --output text

# --- PRUEBA 4: Sesión ---
echo ""
echo "🟢 PRUEBA 4a: Iniciando sesión"
aws iot-data publish --topic "moto/data" --region $REGION --payload '{
  "device_id": "'$DEVICE'", "timestamp": '$(date +%s)',
  "year": 2026, "month": 10, "day": 16, "engine_on": true, "rpm": 1500
}'
sleep 5

echo "📊 Session_State:"
aws dynamodb get-item --table-name Furiosa_Session_State --key '{"device_id":{"S":"'$DEVICE'"}}' --region $REGION

echo ""
echo "🔴 PRUEBA 4b: Cerrando sesión"
sleep 5
aws iot-data publish --topic "moto/data" --region $REGION --payload '{
  "device_id": "'$DEVICE'", "timestamp": '$(date +%s)',
  "year": 2026, "month": 10, "day": 16, "engine_on": false, "rpm": 0
}'
sleep 8

echo ""
echo "==========================================="
echo "  PRUEBA COMPLETADA"
echo "==========================================="