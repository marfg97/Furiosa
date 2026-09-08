"""
L3: maintenance-predict
Invocado por el Glue Job al terminar de procesar una sesión.
Llama a los 7 endpoints de SageMaker y guarda predicciones.

Trigger: Glue Job → Lambda (al terminar raw-to-stage)
Input:   session_id + métricas de stage
Output:  DynamoDB Furiosa_Predictions + SNS si urgencia crítica
"""

import boto3
import json
import time
from datetime import datetime

sm_runtime   = boto3.client("sagemaker-runtime", region_name="us-east-1")
dynamodb     = boto3.resource("dynamodb",         region_name="us-east-1")
sns_client   = boto3.client("sns",                region_name="us-east-1")
lambda_client= boto3.client("lambda",             region_name="us-east-1")

TABLE_PREDICTIONS  = dynamodb.Table("Furiosa_Predictions")
TABLE_MAINTENANCE  = dynamodb.Table("Furiosa_Maintenance")
TABLE_SESSIONS     = dynamodb.Table("Furiosa_Sessions")

SNS_TOPIC_ARN = "arn:aws:sns:us-east-1:329068432517:furiosa-alerts"

# ─── Endpoints por componente ─────────────────────────────────
ENDPOINTS = {
    "oil":          "furiosa-maintenance-oil",
    "brake_front":  "furiosa-maintenance-brake-front",
    "brake_rear":   "furiosa-maintenance-brake-rear",
    "chain":        "furiosa-maintenance-chain",
    "tire_front":   "furiosa-maintenance-tire-front",
    "tire_rear":    "furiosa-maintenance-tire-rear",
    "urgency":      "furiosa-maintenance-urgency",
}

URGENCY_MAP   = {0: "ok", 1: "watch", 2: "soon", 3: "critical"}
URGENCY_EMOJI = {"ok": "✅", "watch": "🟡", "soon": "⚠️", "critical": "🔴"}
ROUTE_MAP     = {"urbana": 0, "carretera": 1, "montana": 2, "mixta": 3}

COMPONENT_NAMES_ES = {
    "oil":         "Aceite",
    "brake_front": "Freno delantero",
    "brake_rear":  "Freno trasero",
    "chain":       "Cadena",
    "tire_front":  "Llanta delantera",
    "tire_rear":   "Llanta trasera",
}


def build_feature_vector(session):
    """Construye el vector de features para SageMaker."""
    route_enc = ROUTE_MAP.get(session.get("route_type", "mixta"), 3)

    return [
        session.get("distance_km", 0),
        session.get("duration_min", 0),
        session.get("speed_avg_kmh", 0),
        session.get("speed_max_kmh", 0),
        session.get("rpm_avg", 0),
        session.get("rpm_max", 0),
        session.get("rpm_redzone_pct", 0),
        session.get("rpm_redzone_time_min", 0),
        session.get("engine_temp_avg_c", 0),
        session.get("engine_temp_max_c", 0),
        session.get("engine_temp_over90_min", 0),
        session.get("engine_temp_over95_min", 0),
        session.get("oil_temp_avg_c", 0),
        session.get("oil_temp_max_c", 0),
        session.get("brake_temp_front_max_c", 0),
        session.get("brake_temp_rear_max_c", 0),
        session.get("hard_brake_events", 0),
        session.get("hard_accel_events", 0),
        session.get("lean_over30_time_min", 0),
        session.get("lean_over40_time_min", 0),
        session.get("tire_temp_front_max_c", 0),
        session.get("tire_temp_rear_max_c", 0),
        session.get("tire_pressure_front_avg_psi", 32),
        session.get("tire_pressure_rear_avg_psi", 36),
        session.get("vibration_avg", 0),
        session.get("vibration_max", 0),
        session.get("voltage_drop", 0),
        session.get("current_avg_amp", 0),
        session.get("energy_consumed_wh", 0),
        session.get("fuel_consumed_pct", 0),
        session.get("throttle_avg_pct", 0),
        session.get("throttle_over80_time_min", 0),
        session.get("km_since_brake_front", 0),
        session.get("km_since_brake_rear", 0),
        session.get("km_since_oil", 0),
        session.get("km_since_chain", 0),
        session.get("km_since_tire_front", 0),
        session.get("km_since_tire_rear", 0),
        route_enc,
    ]


def invoke_endpoints(feature_vector):
    """Llama a todos los endpoints de SageMaker."""
    csv_payload = ",".join(map(str, feature_vector))
    predictions = {}

    for component, endpoint_name in ENDPOINTS.items():
        try:
            response = sm_runtime.invoke_endpoint(
                EndpointName=endpoint_name,
                ContentType="text/csv",
                Body=csv_payload,
            )
            result = float(response["Body"].read().decode("utf-8").strip())

            if component == "urgency":
                predictions["urgency"] = URGENCY_MAP.get(int(result), "ok")
            else:
                predictions[f"remaining_km_{component}"] = round(max(0, result), 1)

        except Exception as e:
            print(f"Error endpoint {component}: {e}")
            if component == "urgency":
                predictions["urgency"] = "unknown"
            else:
                predictions[f"remaining_km_{component}"] = -1

    # Componente más crítico
    km_preds = {k: v for k, v in predictions.items()
                if k.startswith("remaining_km_") and v >= 0}
    if km_preds:
        most_critical_key = min(km_preds, key=km_preds.get)
        predictions["most_critical_component"] = most_critical_key.replace("remaining_km_", "")
        predictions["most_critical_remaining_km"] = km_preds[most_critical_key]

    return predictions


def save_predictions(session_id, device_id, timestamp, predictions):
    """Guarda predicciones en DynamoDB."""
    item = {
        "session_id":  session_id,
        "timestamp":   str(timestamp),
        "device_id":   device_id,
        "date":        datetime.utcnow().strftime("%Y-%m-%d"),
        "predicted_at": str(int(time.time())),
        **{k: str(v) for k, v in predictions.items()}
    }
    TABLE_PREDICTIONS.put_item(Item=item)

    # Actualizar tabla de mantenimiento acumulado
    TABLE_MAINTENANCE.put_item(Item={
        "device_id":                    device_id,
        "timestamp":                    str(timestamp),
        "remaining_km_oil":             str(predictions.get("remaining_km_oil", 0)),
        "remaining_km_brake_front":     str(predictions.get("remaining_km_brake_front", 0)),
        "remaining_km_brake_rear":      str(predictions.get("remaining_km_brake_rear", 0)),
        "remaining_km_chain":           str(predictions.get("remaining_km_chain", 0)),
        "remaining_km_tire_front":      str(predictions.get("remaining_km_tire_front", 0)),
        "remaining_km_tire_rear":       str(predictions.get("remaining_km_tire_rear", 0)),
        "most_critical_component":      predictions.get("most_critical_component", ""),
        "most_critical_remaining_km":   str(predictions.get("most_critical_remaining_km", 0)),
        "urgency":                      predictions.get("urgency", "ok"),
    })


def notify_if_critical(device_id, predictions):
    """Envía notificación push si hay componente crítico o soon."""
    urgency = predictions.get("urgency", "ok")

    if urgency not in ["critical", "soon"]:
        return

    most_critical = predictions.get("most_critical_component", "")
    remaining_km  = predictions.get("most_critical_remaining_km", 0)
    component_es  = COMPONENT_NAMES_ES.get(most_critical, most_critical)
    emoji         = URGENCY_EMOJI.get(urgency, "⚠️")

    message = (
        f"{emoji} MANTENIMIENTO {urgency.upper()}\n"
        f"Componente: {component_es}\n"
        f"Km restantes: {remaining_km:.0f} km\n\n"
        f"Resumen completo:\n"
    )

    for comp, name_es in COMPONENT_NAMES_ES.items():
        km = predictions.get(f"remaining_km_{comp}", 0)
        urg_emoji = "🔴" if km < 500 else "🟡" if km < 1500 else "✅"
        message += f"  {urg_emoji} {name_es}: {km:.0f} km\n"

    # Enviar por SNS → push Android
    try:
        sns_client.publish(
            TopicArn=SNS_TOPIC_ARN,
            Subject=f"Furiosa — Mantenimiento {urgency.upper()}",
            Message=message,
            MessageAttributes={
                "device_id": {"DataType": "String", "StringValue": device_id},
                "urgency":   {"DataType": "String", "StringValue": urgency},
            }
        )
        print(f"📲 Notificación enviada: {urgency}")
    except Exception as e:
        print(f"Error SNS: {e}")

    # También invocar L5 para alerta de voz si es crítico
    if urgency == "critical":
        try:
            lambda_client.invoke(
                FunctionName="furiosa-alert-dispatcher",
                InvocationType="Event",
                Payload=json.dumps({
                    "device_id": device_id,
                    "alert": {
                        "metric":  f"maintenance_{most_critical}",
                        "level":   "critical",
                        "message": f"Mantenimiento crítico: {component_es} necesita atención en {remaining_km:.0f} km",
                    },
                    "mode": "dashboard",
                }).encode(),
            )
        except Exception as e:
            print(f"Error invocando alert-dispatcher: {e}")


def handler(event, context):
    session_id = event.get("session_id")
    device_id  = event.get("device_id", "furiosa_01")
    timestamp  = event.get("timestamp", str(int(time.time())))
    session    = event.get("session_data", event)

    if not session_id:
        return {"statusCode": 400, "error": "session_id requerido"}

    print(f"🤖 Prediciendo mantenimiento para sesión: {session_id}")

    feature_vector = build_feature_vector(session)
    predictions    = invoke_endpoints(feature_vector)

    save_predictions(session_id, device_id, timestamp, predictions)
    notify_if_critical(device_id, predictions)

    print(f"✅ Predicciones guardadas — urgencia: {predictions.get('urgency')}")
    print(f"   Componente crítico: {predictions.get('most_critical_component')} "
          f"({predictions.get('most_critical_remaining_km', 0):.0f} km)")

    return {
        "statusCode":  200,
        "session_id":  session_id,
        "predictions": predictions,
    }
