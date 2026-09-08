"""
L2: session-detector
Detecta inicio y fin de sesión de manejo.
Cuando detecta fin de sesión invoca el Glue Job raw-to-stage.

Trigger: IoT Rule → Lambda (cada mensaje)
Input:   Payload raw
Output:  DynamoDB Furiosa_Sessions_State + dispara Glue Job
"""

import boto3
import json
import time
import os
from datetime import datetime

dynamodb     = boto3.resource("dynamodb", region_name="us-east-1")
glue_client  = boto3.client("glue",      region_name="us-east-1")
lambda_client= boto3.client("lambda",    region_name="us-east-1")

TABLE_SESSION_STATE = dynamodb.Table("Furiosa_Session_State")
TABLE_SESSIONS      = dynamodb.Table("Furiosa_Sessions")

# ─── Config ───────────────────────────────────────────────────
ENGINE_OFF_TIMEOUT_SEC = 120   # 2 min sin datos o engine_on=false → sesión terminada
MIN_SESSION_DISTANCE   = 0.5   # km mínimos para considerar sesión válida
GLUE_JOB_NAME          = "furiosa-raw-to-stage"


def get_session_state(device_id):
    """Obtiene el estado actual de sesión del dispositivo."""
    try:
        response = TABLE_SESSION_STATE.get_item(
            Key={"device_id": device_id}
        )
        return response.get("Item")
    except Exception as e:
        print(f"Error getting session state: {e}")
        return None


def save_session_state(state):
    """Guarda el estado de sesión."""
    try:
        TABLE_SESSION_STATE.put_item(Item=state)
    except Exception as e:
        print(f"Error saving session state: {e}")


def close_session(device_id, state, last_payload):
    """Cierra la sesión actual y dispara el procesamiento."""
    session_id  = state["session_id"]
    start_ts    = int(state["session_start_ts"])
    end_ts      = int(time.time())
    duration_min= (end_ts - start_ts) / 60

    # Calcular distancia acumulada
    distance_km = float(state.get("distance_km_accum", 0))

    print(f"🏁 Cerrando sesión {session_id} — {round(distance_km, 2)} km — {round(duration_min, 1)} min")

    if distance_km < MIN_SESSION_DISTANCE:
        print(f"⚠️  Sesión descartada (distancia < {MIN_SESSION_DISTANCE} km)")
        clear_session_state(device_id)
        return

    # Guardar sesión en DynamoDB
    session_record = {
        "session_id":        session_id,
        "device_id":         device_id,
        "timestamp":         str(end_ts),
        "session_start_ts":  str(start_ts),
        "session_end_ts":    str(end_ts),
        "duration_min":      str(round(duration_min, 2)),
        "distance_km":       str(round(distance_km, 2)),
        "odometer_start_km": str(state.get("odometer_start_km", 0)),
        "odometer_end_km":   str(last_payload.get("odometer_km", 0)),
        "date":              datetime.utcfromtimestamp(start_ts).strftime("%Y-%m-%d"),
        "year":              str(datetime.utcfromtimestamp(start_ts).year),
        "month":             str(datetime.utcfromtimestamp(start_ts).month),
        "day":               str(datetime.utcfromtimestamp(start_ts).day),
        "status":            "closed",
        "glue_triggered":    "false",
    }
    TABLE_SESSIONS.put_item(Item=session_record)

    # Disparar Glue Job para calcular métricas stage
    trigger_glue_job(session_id, device_id, start_ts, end_ts)

    # Limpiar estado
    clear_session_state(device_id)


def clear_session_state(device_id):
    """Limpia el estado de sesión activa."""
    TABLE_SESSION_STATE.put_item(Item={
        "device_id":    device_id,
        "active":       "false",
        "session_id":   "none",
        "last_updated": str(int(time.time())),
    })


def trigger_glue_job(session_id, device_id, start_ts, end_ts):
    """Dispara el Glue Job raw-to-stage para esta sesión."""
    try:
        response = glue_client.start_job_run(
            JobName=GLUE_JOB_NAME,
            Arguments={
                "--session_id":  session_id,
                "--device_id":   device_id,
                "--start_ts":    str(start_ts),
                "--end_ts":      str(end_ts),
                "--bucket":      "furiosa-data",
            }
        )
        run_id = response["JobRunId"]
        print(f"✅ Glue Job iniciado: {run_id}")

        # Actualizar sesión con el run_id del Glue Job
        TABLE_SESSIONS.update_item(
            Key={"session_id": session_id, "timestamp": str(end_ts)},
            UpdateExpression="SET glue_run_id = :r, glue_triggered = :t",
            ExpressionAttributeValues={":r": run_id, ":t": "true"},
        )
    except Exception as e:
        print(f"Error triggering Glue Job: {e}")


def calculate_distance(lat1, lon1, lat2, lon2):
    """Haversine — distancia en km entre dos coordenadas GPS."""
    import math
    R = 6371
    dlat = math.radians(lat2 - lat1)
    dlon = math.radians(lon2 - lon1)
    a = (math.sin(dlat/2)**2 +
         math.cos(math.radians(lat1)) * math.cos(math.radians(lat2)) * math.sin(dlon/2)**2)
    return R * 2 * math.asin(math.sqrt(a))


def handler(event, context):
    device_id  = event.get("device_id", "furiosa_01")
    engine_on  = event.get("engine_on", False)
    timestamp  = int(str(event.get("timestamp", int(time.time()))).replace('"', ''))
    now        = int(time.time())

    gps_lat    = float(event.get("gps_lat", 0))
    gps_lon    = float(event.get("gps_lon", 0))
    odometer   = float(event.get("odometer_km", 0))

    state = get_session_state(device_id)

    # ── CASO 1: No hay sesión activa ─────────────────────────
    if not state or state.get("active") != "true":
        if engine_on:
            # Iniciar nueva sesión
            session_num = int(state.get("session_count", 0)) + 1 if state else 1
            session_id  = f"{device_id}_{datetime.utcnow().strftime('%Y%m%d')}_{session_num:03d}"

            new_state = {
                "device_id":          device_id,
                "active":             "true",
                "session_id":         session_id,
                "session_start_ts":   str(now),
                "last_seen_ts":       str(now),
                "last_lat":           str(gps_lat),
                "last_lon":           str(gps_lon),
                "odometer_start_km":  str(odometer),
                "distance_km_accum":  "0",
                "session_count":      str(session_num),
                "last_updated":       str(now),
            }
            save_session_state(new_state)
            print(f"🟢 Sesión iniciada: {session_id}")
        return {"statusCode": 200, "action": "no_active_session"}

    # ── CASO 2: Sesión activa ────────────────────────────────
    last_seen = int(state.get("last_seen_ts", now))
    elapsed   = now - last_seen

    # ¿Sesión terminó? (motor apagado o timeout)
    if not engine_on or elapsed > ENGINE_OFF_TIMEOUT_SEC:
        close_session(device_id, state, event)
        return {"statusCode": 200, "action": "session_closed"}

    # Acumular distancia
    last_lat    = float(state.get("last_lat", gps_lat))
    last_lon    = float(state.get("last_lon", gps_lon))
    delta_km    = calculate_distance(last_lat, last_lon, gps_lat, gps_lon)
    accum_km    = float(state.get("distance_km_accum", 0)) + delta_km

    # Actualizar estado
    state.update({
        "last_seen_ts":      str(now),
        "last_lat":          str(gps_lat),
        "last_lon":          str(gps_lon),
        "distance_km_accum": str(round(accum_km, 4)),
        "last_updated":      str(now),
    })
    save_session_state(state)

    return {
        "statusCode":  200,
        "action":      "session_updated",
        "session_id":  state["session_id"],
        "distance_km": round(accum_km, 2),
    }
