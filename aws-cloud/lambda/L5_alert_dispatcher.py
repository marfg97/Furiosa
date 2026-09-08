"""
L5: alert-dispatcher
Recibe alertas de L1 y L3, las formatea y las envía
via SNS → push Android con TTS.

Trigger: L1 realtime-monitor / L3 maintenance-predict
Input:   { "device_id", "alert": { metric, level, message }, "mode" }
Output:  SNS push + AppSync WebSocket update
"""

import boto3
import json
import time

sns_client    = boto3.client("sns",       region_name="us-east-1")
appsync       = boto3.client("appsync",   region_name="us-east-1")
dynamodb      = boto3.resource("dynamodb", region_name="us-east-1")

TABLE_ALERTS  = dynamodb.Table("Furiosa_Alerts")
SNS_TOPIC_ARN = "arn:aws:sns:us-east-1:329068432517:furiosa-alerts"

# ─── Prioridad de alertas ────────────────────────────────────
PRIORITY = {"critical": 3, "warn": 2, "info": 1}

# Mensajes cortos para modo conducción (TTS Android)
RIDING_MESSAGES = {
    "engine_temp_c_critical":       "¡Motor muy caliente! Para pronto.",
    "engine_temp_c_warn":           "Motor calentándose, reduce RPM.",
    "oil_temp_c_critical":          "¡Aceite sobrecalentado! Para ahora.",
    "voltage_bike_critical":        "¡Voltaje crítico! Revisa alternador.",
    "voltage_bike_warn":            "Voltaje bajo, revisa el alternador.",
    "tire_pressure_front_psi_critical": "¡Presión delantera crítica! Para ya.",
    "tire_pressure_rear_psi_critical":  "¡Presión trasera crítica! Para ya.",
    "vibration_max_critical":       "¡Vibración anormal! Para la moto.",
    "vibration_max_warn":           "Vibración inusual, revisa la cadena.",
    "rpm_critical":                 "RPM muy alto, baja velocidad.",
    "engine_stress_warn":           "Motor estresado, reduce RPM.",
    "extreme_lean_warn":            "Inclinación extrema detectada.",
    "voltage_drop_sudden_critical": "¡Caída brusca de voltaje!",
    "maintenance_oil_critical":     "Aceite urgente, cambia esta semana.",
    "maintenance_chain_critical":   "Cadena crítica, revisa tensión.",
}


def format_riding_message(metric, level):
    """Mensaje corto para TTS mientras conduce."""
    key = f"{metric}_{level}"
    return RIDING_MESSAGES.get(key, f"Alerta: {metric.replace('_', ' ')}")


def format_dashboard_message(alert):
    """Mensaje completo para dashboard."""
    return alert.get("message", f"Alerta {alert.get('level')}: {alert.get('metric')}")


def send_sns(device_id, subject, message, level, metric):
    """Envía push notification via SNS."""
    try:
        sns_client.publish(
            TopicArn=SNS_TOPIC_ARN,
            Subject=subject,
            Message=message,
            MessageAttributes={
                "device_id": {"DataType": "String", "StringValue": device_id},
                "level":     {"DataType": "String", "StringValue": level},
                "metric":    {"DataType": "String", "StringValue": metric},
                "priority":  {"DataType": "Number",
                              "StringValue": str(PRIORITY.get(level, 1))},
            }
        )
        print(f"📲 SNS enviado: {subject}")
        return True
    except Exception as e:
        print(f"Error SNS: {e}")
        return False


def save_dispatched_alert(device_id, alert, mode, message_sent):
    """Guarda el registro de alerta despachada."""
    try:
        TABLE_ALERTS.put_item(Item={
            "device_id":    device_id,
            "timestamp":    str(int(time.time())),
            "metric":       alert.get("metric", ""),
            "level":        alert.get("level", ""),
            "value":        str(alert.get("value", "")),
            "message":      alert.get("message", ""),
            "message_sent": message_sent,
            "mode":         mode,
            "dispatched_at": str(int(time.time())),
        })
    except Exception as e:
        print(f"Error saving alert: {e}")


def handler(event, context):
    device_id = event.get("device_id", "furiosa_01")
    alert     = event.get("alert", {})
    mode      = event.get("mode", "riding")  # riding | dashboard

    metric = alert.get("metric", "")
    level  = alert.get("level",  "warn")
    value  = alert.get("value",  "")

    print(f"🚨 [{mode}] [{level.upper()}] {device_id}: {metric} = {value}")

    # Formato del mensaje según modo
    if mode == "riding":
        # Corto para TTS Android mientras conduce
        message_sent = format_riding_message(metric, level)
        subject      = f"Furiosa [{level.upper()}]"
    else:
        # Completo para dashboard
        message_sent = format_dashboard_message(alert)
        subject      = f"Furiosa — {level.upper()}: {metric.replace('_', ' ').title()}"

    # Enviar SNS
    sns_ok = send_sns(device_id, subject, message_sent, level, metric)

    # Guardar registro
    save_dispatched_alert(device_id, alert, mode, message_sent)

    return {
        "statusCode":   200,
        "sns_sent":     sns_ok,
        "message_sent": message_sent,
        "level":        level,
        "mode":         mode,
    }
