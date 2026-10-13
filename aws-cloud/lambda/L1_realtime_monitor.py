"""
L1: realtime-monitor
Triggered by IoT Core Rule every message (moto/data)

Evalúa umbrales en tiempo real, detecta anomalías combinadas,
guarda alertas en DynamoDB y dispara L5 alert-dispatcher.

Flujo:
  IoT Core -> L1 -> DynamoDB(Furiosa_Alerts / Furiosa_DeviceState) -> L5 -> SNS

"""

import boto3
import json
import os
import time
from datetime import datetime, timezone
from decimal import Decimal

lambda_client = boto3.client("lambda", region_name="us-east-1")
dynamodb = boto3.resource("dynamodb", region_name="us-east-1")

TABLE_ALERTS = dynamodb.Table("Furiosa_Alerts")
TABLE_STATE = dynamodb.Table("Furiosa_DeviceState")
TABLE_SESSION_STATE = dynamodb.Table("Furiosa_Session_State")

L5_FUNCTION_NAME = os.environ.get("ALERT_DISPATCHER_FUNCTION", "L5_alert_dispatcher")

# ─── Umbrales configurables ───────────────────────────────────
THRESHOLDS = {
    "engine_temp_c": {
        "warn": 90, "critical": 95,
        "message_warn": "Temperatura del motor en {val}°C, PRECAUCIÓN!",
        "message_critical": "Temperatura del motor crítica en {val}°C, PARAR LA MOTO!",
    },
    "oil_temp_c": {
        "warn": 95, "critical": 105,
        "message_warn": "Temperatura del aceite en {val}°C",
        "message_critical": "Aceite sobrecalentado en {val}°C, para inmediatamente",
    },
    "voltage_bike": {
        "warn": 12.0, "critical": 11.5, "mode": "below",
        "message_warn": "Voltaje bajo en {val}V, REVISAR BATERÍA",
        "message_critical": "Voltaje crítico en {val}V, RIESGO BATERIA",
    },
    "battery_cel_percent": {
        "warn": 20, "critical": 10, "mode": "below",
        "message_warn": "Batería del celular al {val}%, conéctalo pronto",
        "message_critical": "Batería del celular al {val}%, se apagará pronto",
    },
    "tire_pressure_front_psi": {
        "warn": 28, "critical": 25, "mode": "below",
        "message_warn": "Presión delantera baja en {val} PSI",
        "message_critical": "Presión delantera crítica en {val} PSI, para ahora",
    },
    "tire_pressure_rear_psi": {
        "warn": 30, "critical": 27, "mode": "below",
        "message_warn": "Presión trasera baja en {val} PSI",
        "message_critical": "Presión trasera crítica en {val} PSI, para ahora",
    },
    "vibration_max": {
        "warn": 0.5, "critical": 0.8,
        "message_warn": "Vibración inusual detectada, REVISAR!",
        "message_critical": "Vibración crítica detectada, ¡PARA LA MOTO!",
    },
    "rpm": {
        "warn": 7000, "critical": 8000,
        "message_warn": "RPM en zona de advertencia: {val}",
        "message_critical": "RPM crítico: {val}, reduce velocidad",
    },
}

# ─── Cooldown por alerta (segundos) ──────────────────────────
ALERT_COOLDOWN = {
    "warn": 120,      # 2 minutos entre alertas del mismo tipo
    "critical": 30,   # 30 segundos para críticas
}


# ─── Helpers ─────────────────────────────────────────────────

def to_decimal(value, default=0):
    """Convierte a Decimal de forma segura para DynamoDB."""
    try:
        return Decimal(str(value))
    except Exception:
        return Decimal(str(default))


def get_prev_state(device_id):
    """Lee el estado previo del dispositivo desde DynamoDB."""
    try:
        resp = TABLE_STATE.get_item(Key={"device_id": device_id})
        return resp.get("Item", {})
    except Exception as e:
        print(f"Error leyendo DeviceState: {e}")
        return {}


def is_in_cooldown(device_id, metric, level):
    """
    Verifica si la alerta está en cooldown usando DynamoDB.
    Persiste entre cold starts.
    """
    try:
        key = f"{metric}_{level}"
        resp = TABLE_SESSION_STATE.get_item(Key={"device_id": f"cooldown_{device_id}"})
        item = resp.get("Item", {})
        last_time = float(item.get(key, 0))
        elapsed = time.time() - last_time
        return elapsed < ALERT_COOLDOWN.get(level, 60)
    except Exception:
        return False


def set_cooldown(device_id, metric, level):
    """Marca el timestamp de la última alerta en DynamoDB."""
    try:
        key = f"{metric}_{level}"
        TABLE_SESSION_STATE.update_item(
            Key={"device_id": f"cooldown_{device_id}"},
            UpdateExpression="SET #k = :ts",
            ExpressionAttributeNames={"#k": key},
            ExpressionAttributeValues={":ts": str(time.time())},
        )
    except Exception as e:
        print(f"Error guardando cooldown: {e}")


# ─── Evaluación de umbrales ──────────────────────────────────

def check_threshold(device_id, metric, value):
    """Evalúa si un valor supera umbrales y devuelve alerta si aplica."""
    if metric not in THRESHOLDS or value is None:
        return None

    cfg = THRESHOLDS[metric]
    mode = cfg.get("mode", "above")
    level = None

    if mode == "above":
        if value >= cfg["critical"]:
            level = "critical"
        elif value >= cfg["warn"]:
            level = "warn"
    else:  # below
        if value <= cfg["critical"]:
            level = "critical"
        elif value <= cfg["warn"]:
            level = "warn"

    if level is None:
        return None

    if is_in_cooldown(device_id, metric, level):
        return None

    set_cooldown(device_id, metric, level)

    message = cfg[f"message_{level}"].format(val=round(value, 1))
    return {
        "metric": metric,
        "value": round(value, 2),
        "level": level,
        "message": message,
    }


# ─── Anomalías combinadas ────────────────────────────────────

def detect_anomalies(payload, prev_state):
    """Detecta anomalías combinadas que ningún umbral individual captura."""
    anomalies = []
    device_id = payload.get("device_id", "furiosa_01")

    # 1. Caída de voltaje brusca (> 0.3V vs lectura previa REAL)
    voltage = float(payload.get("voltage_bike", 0) or 0)
    prev_voltage = float(prev_state.get("voltage", voltage))
    if prev_voltage > 0 and (prev_voltage - voltage) > 0.3:
        if not is_in_cooldown(device_id, "voltage_drop_sudden", "critical"):
            set_cooldown(device_id, "voltage_drop_sudden", "critical")
            anomalies.append({
                "metric": "voltage_drop_sudden",
                "value": round(prev_voltage - voltage, 3),
                "level": "critical",
                "message": f"Caída brusca de voltaje: {round(prev_voltage - voltage, 2)}V",
            })

    # 2. Motor estresado (temp alta + RPM alto simultáneo)
    engine_temp = float(payload.get("engine_temp_c", 0) or 0)
    rpm = float(payload.get("rpm", 0) or 0)
    if engine_temp > 88 and rpm > 5500:
        if not is_in_cooldown(device_id, "engine_stress", "warn"):
            set_cooldown(device_id, "engine_stress", "warn")
            anomalies.append({
                "metric": "engine_stress",
                "value": engine_temp,
                "level": "warn",
                "message": f"Motor estresado: {engine_temp}°C a {rpm} RPM",
            })

    # 3. Inclinación extrema (> 45°)
    roll = abs(float(payload.get("rotation_roll_deg", 0) or 0))
    if roll > 45:
        if not is_in_cooldown(device_id, "extreme_lean", "warn"):
            set_cooldown(device_id, "extreme_lean", "warn")
            anomalies.append({
                "metric": "extreme_lean",
                "value": round(roll, 1),
                "level": "warn",
                "message": f"Inclinación extrema: {round(roll, 1)}°",
            })

    return anomalies





def dispatch_alert(device_id, alert):
    """Invoca L5 alert-dispatcher (asíncrono)."""
    try:
        lambda_client.invoke(
            FunctionName=L5_FUNCTION_NAME,
            InvocationType="Event",
            Payload=json.dumps({
                "device_id": device_id,
                "alert": alert,
                "mode": "riding",
            }).encode(),
        )
    except Exception as e:
        print(f"Error dispatch L5: {e}")


def update_device_state(device_id, event, alerts_count):
    """Sobrescribe el estado del dispositivo (un solo item por device)."""
    try:
        TABLE_STATE.put_item(Item={
            "device_id": device_id,
            "timestamp": str(event.get("ingestion_ts", event.get("timestamp", int(time.time())))),
            "last_seen": int(time.time()),
            "engine_temp": to_decimal(event.get("engine_temp_c", 0)),
            "oil_temp": to_decimal(event.get("oil_temp_c", 0)),
            "rpm": int(event.get("rpm", 0) or 0),
            "speed": to_decimal(event.get("gps_speed_kmh", 0)),
            "voltage": to_decimal(event.get("voltage_bike", 0)),
            "battery_cel": int(event.get("battery_cel_percent", 0) or 0),
            "tire_front_psi": to_decimal(event.get("tire_pressure_front_psi", 0)),
            "tire_rear_psi": to_decimal(event.get("tire_pressure_rear_psi", 0)),
            "alerts_count": alerts_count,
            "engine_on": bool(event.get("engine_on", False)),
        })
    except Exception as e:
        print(f"Error actualizando DeviceState: {e}")


# ─── Handler principal ───────────────────────────────────────

def lambda_handler(event, context):
    device_id = event.get("device_id", "furiosa_01")
    timestamp = event.get("ingestion_ts", event.get("timestamp", str(int(time.time()))))

    # Leer estado previo (para anomalías combinadas)
    prev_state = get_prev_state(device_id)

    alerts = []

    # 1. Evaluar umbrales individuales
    metrics_to_check = {
        "engine_temp_c": event.get("engine_temp_c"),
        "oil_temp_c": event.get("oil_temp_c"),
        "voltage_bike": event.get("voltage_bike"),
        "battery_cel_percent": event.get("battery_cel_percent"),
        "tire_pressure_front_psi": event.get("tire_pressure_front_psi"),
        "tire_pressure_rear_psi": event.get("tire_pressure_rear_psi"),
        "vibration_max": event.get("vibration_max"),
        "rpm": event.get("rpm"),
    }

    for metric, value in metrics_to_check.items():
        if value is None:
            continue
        try:
            alert = check_threshold(device_id, metric, float(value))
            if alert:
                alerts.append(alert)
                save_alert(device_id, alert, timestamp)
                dispatch_alert(device_id, alert)
        except (ValueError, TypeError) as e:
            print(f"Valor inválido para {metric}: {value} ({e})")

    # 2. Detectar anomalías combinadas
    anomalies = detect_anomalies(event, prev_state)
    for anomaly in anomalies:
        alerts.append(anomaly)
        save_alert(device_id, anomaly, timestamp)
        dispatch_alert(device_id, anomaly)

    # 3. Actualizar estado del dispositivo
    update_device_state(device_id, event, len(alerts))

    print(f"✅ {device_id} — {len(alerts)} alertas generadas")
    return {"statusCode": 200, "alerts_count": len(alerts), "alerts": alerts}