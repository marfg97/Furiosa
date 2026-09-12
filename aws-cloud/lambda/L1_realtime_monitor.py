"""
L1: realtime-monitor
Triggered by IoT Core Rule every message (moto/data)
Evalúa umbrales en tiempo real y dispara alertas.

Trigger: IoT Rule → Lambda
Input:   Payload raw de moto/data
Output:  Invoca L5 alert-dispatcher si hay alerta
"""

import boto3
import json
import os
import time
from datetime import datetime

lambda_client = boto3.client("lambda",    region_name="us-east-1")
dynamodb      = boto3.resource("dynamodb", region_name="us-east-1")

TABLE_ALERTS   = dynamodb.Table("Furiosa_Alerts")
TABLE_STATE    = dynamodb.Table("Furiosa_DeviceState")

# ─── Umbrales configurables ───────────────────────────────────
THRESHOLDS = {
    "engine_temp_c": {
        "warn":     90,
        "critical": 95,
        "message_warn":     "Temperatura del motor en {val}°C, PRECAUCIÓN!",
        "message_critical": "Temperatura del motor crítica en {val}°C, PARAR LA MOTO!",
    },
    "oil_temp_c": {
        "warn":     95,
        "critical": 105,
        "message_warn":     "Temperatura del aceite en {val}°C",
        "message_critical": "Aceite sobrecalentado en {val}°C, para inmediatamente",
    },
    "voltage_bike": {
        "warn":     12.0,
        "critical": 11.5,
        "mode":     "below",
        "message_warn":     "Voltaje bajo en {val}V, REVISAR BATERÍA",
        "message_critical": "Voltaje crítico en {val}V, RIESGO BATERIA",
    },
    "battery_cel_percent": {
        "warn":     20,
        "critical": 10,
        "mode":     "below",
        "message_warn":     "Batería del celular al {val}%, conéctalo pronto",
        "message_critical": "Batería del celular al {val}%, se apagará pronto",
    },
    "tire_pressure_front_psi": {
        "warn":     28,
        "critical": 25,
        "mode":     "below",
        "message_warn":     "Presión delantera baja en {val} PSI",
        "message_critical": "Presión delantera crítica en {val} PSI, para ahora",
    },
    "tire_pressure_rear_psi": {
        "warn":     30,
        "critical": 27,
        "mode":     "below",
        "message_warn":     "Presión trasera baja en {val} PSI",
        "message_critical": "Presión trasera crítica en {val} PSI, para ahora",
    },
    "vibration_max": {
        "warn":     0.5,
        "critical": 0.8,
        "message_warn":     "Vibración inusual detectada, REVISAR!",
        "message_critical": "Vibración crítica detectada, ¡PARA LA MOTO!",
    },
    "rpm": {
        "warn":     7000,
        "critical": 8000,
        "message_warn":     "RPM en zona de advertencia: {val}",
        "message_critical": "RPM crítico: {val}, reduce velocidad",
    },
}

# ─── Cooldown por alerta (segundos) ──────────────────────────
ALERT_COOLDOWN = {
    "warn":     120,   # 2 minutos entre alertas del mismo tipo
    "critical":  30,   # 30 segundos para críticas
}

# Cache en memoria para cooldown (se resetea por cold start)
_last_alert_time = {}


def check_threshold(metric, value, last_state):
    """Evalúa si un valor supera umbrales y devuelve nivel de alerta."""
    if metric not in THRESHOLDS:
        return None

    cfg  = THRESHOLDS[metric]
    mode = cfg.get("mode", "above")  # above=mayor, below=menor

    level = None
    if mode == "above":
        if value >= cfg.get("critical", float("inf")):
            level = "critical"
        elif value >= cfg.get("warn", float("inf")):
            level = "warn"
    else:  # below
        if value <= cfg.get("critical", float("-inf")):
            level = "critical"
        elif value <= cfg.get("warn", float("-inf")):
            level = "warn"

    if level is None:
        return None

    # Cooldown — no spammear la misma alerta
    cache_key = f"{metric}_{level}"
    now = time.time()
    if cache_key in _last_alert_time:
        elapsed = now - _last_alert_time[cache_key]
        if elapsed < ALERT_COOLDOWN[level]:
            return None

    _last_alert_time[cache_key] = now

    msg_key = f"message_{level}"
    message = cfg[msg_key].format(val=round(value, 1))

    return {
        "metric":  metric,
        "value":   value,
        "level":   level,
        "message": message,
    }


def detect_anomalies(payload):
    """Detecta anomalías combinadas que ningún umbral individual captura."""
    anomalies = []

    # Caída de voltaje brusca (> 0.3V en un mensaje)
    voltage = payload.get("voltage_bike", 0)
    prev_voltage = payload.get("_prev_voltage", voltage)
    if prev_voltage - voltage > 0.3:
        anomalies.append({
            "metric":  "voltage_drop_sudden",
            "value":   round(prev_voltage - voltage, 3),
            "level":   "critical",
            "message": f"Caída brusca de voltaje: {round(prev_voltage - voltage, 2)}V",
        })

    # Motor caliente + RPM alto + mucho tiempo
    engine_temp = payload.get("engine_temp_c", 0)
    rpm         = payload.get("rpm", 0)
    if engine_temp > 88 and rpm > 5500:
        anomalies.append({
            "metric":  "engine_stress",
            "value":   engine_temp,
            "level":   "warn",
            "message": f"Motor estresado: {engine_temp}°C a {rpm} RPM",
        })

    # Inclinación extrema
    roll = abs(payload.get("rotation_roll_deg", 0))
    if roll > 45:
        anomalies.append({
            "metric":  "extreme_lean",
            "value":   roll,
            "level":   "warn",
            "message": f"Inclinación extrema: {round(roll, 1)}°",
        })

    return anomalies


def save_alert(device_id, alert, timestamp):
    """Guarda la alerta en DynamoDB."""
    try:
        TABLE_ALERTS.put_item(Item={
            "device_id":   device_id,
            "timestamp":   str(timestamp),
            "metric":      alert["metric"],
            "value":       str(alert["value"]),
            "level":       alert["level"],
            "message":     alert["message"],
            "date":        datetime.utcnow().strftime("%Y-%m-%d"),
        })
    except Exception as e:
        print(f"Error guardando alerta: {e}")


def dispatch_alert(device_id, alert):
    """Invoca L5 alert-dispatcher para enviar la alerta al usuario."""
    try:
        lambda_client.invoke(
            FunctionName="furiosa-alert-dispatcher",
            InvocationType="Event",  # asíncrono
            Payload=json.dumps({
                "device_id": device_id,
                "alert":     alert,
                "mode":      "riding",  # voz corta
            }).encode(),
        )
    except Exception as e:
        print(f"Error dispatching alert: {e}")


def handler(event, context):
    device_id = event.get("device_id", "furiosa_01")
    timestamp = event.get("timestamp", str(int(time.time())))
    alerts    = []

    # Evaluar cada métrica contra umbrales
    metrics_to_check = {
        "engine_temp_c":           event.get("engine_temp_c"),
        "oil_temp_c":              event.get("oil_temp_c"),
        "voltage_bike":            event.get("voltage_bike"),
        "battery_cel_percent":     event.get("battery_cel_percent"),
        "tire_pressure_front_psi": event.get("tire_pressure_front_psi"),
        "tire_pressure_rear_psi":  event.get("tire_pressure_rear_psi"),
        "vibration_max":           event.get("vibration_max"),
        "rpm":                     event.get("rpm"),
    }

    for metric, value in metrics_to_check.items():
        if value is None:
            continue
        alert = check_threshold(metric, float(value), {})
        if alert:
            alerts.append(alert)
            save_alert(device_id, alert, timestamp)
            dispatch_alert(device_id, alert)

    # Detectar anomalías combinadas
    anomalies = detect_anomalies(event)
    for anomaly in anomalies:
        alerts.append(anomaly)
        save_alert(device_id, anomaly, timestamp)
        dispatch_alert(device_id, anomaly)

    # Actualizar estado del dispositivo en DynamoDB
    try:
        TABLE_STATE.put_item(Item={
            "device_id":   device_id,
            "timestamp":   str(timestamp),
            "last_seen":   str(int(time.time())),
            "engine_temp": str(event.get("engine_temp_c", 0)),
            "rpm":         str(event.get("rpm", 0)),
            "speed":       str(event.get("gps_speed_kmh", 0)),
            "voltage":     str(event.get("voltage_bike", 0)),
            "alerts_count": str(len(alerts)),
        })
    except Exception as e:
        print(f"Error actualizando estado: {e}")

    print(f"✅ {device_id} — {len(alerts)} alertas generadas")
    return {"statusCode": 200, "alerts": alerts}
