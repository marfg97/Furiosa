"""
L4: voice-command-handler
Procesa comandos de voz desde Android o web dashboard.
Usa Bedrock (Claude) para entender intención y ejecutar acción.

Trigger: API Gateway → Lambda
Input:   { "text": "...", "device_id": "...", "mode": "riding|dashboard" }
Output:  { "response_text": "...", "action": "...", "data": {...} }
"""

import boto3
import json
import time
from datetime import datetime

bedrock      = boto3.client("bedrock-runtime", region_name="us-east-1")
dynamodb     = boto3.resource("dynamodb",       region_name="us-east-1")
lambda_client= boto3.client("lambda",           region_name="us-east-1")
s3_client    = boto3.client("s3",               region_name="us-east-1")

TABLE_SESSIONS     = dynamodb.Table("Furiosa_Sessions")
TABLE_MAINTENANCE  = dynamodb.Table("Furiosa_Maintenance")
TABLE_PREDICTIONS  = dynamodb.Table("Furiosa_Predictions")
TABLE_STATE        = dynamodb.Table("Furiosa_DeviceState")
TABLE_SESSION_STATE= dynamodb.Table("Furiosa_Session_State")

BUCKET = "furiosa-data"

# ─── System prompt para el agente ────────────────────────────
SYSTEM_PROMPT = """Eres el asistente inteligente de una motocicleta llamada Furiosa.
Tienes acceso a datos en tiempo real de sensores, historial de sesiones y predicciones de mantenimiento.

CONTEXTO DEL SISTEMA:
{context}

MODO: {mode}

REGLAS SEGÚN MODO:
- riding (conduciendo): Respuestas MUY cortas (máximo 2 oraciones). Directas. Sin listas.
- dashboard: Respuestas completas, puedes dar detalles y análisis.

IDIOMA: Detecta el idioma del usuario y responde en el mismo (español o inglés).

INTENCIONES QUE PUEDES MANEJAR:
1. QUERY - Consulta de datos: "¿cómo está el motor?", "cuál es mi velocidad promedio"
2. COMMAND - Acción: "inicia grabación", "marca este punto", "cambié el aceite"
3. MAINTENANCE - Mantenimiento: "¿cuándo le toca servicio?", "qué necesita la moto"
4. STATUS - Estado general: "¿cómo está la moto?", "resumen de hoy"
5. HISTORY - Historial: "cómo conduje ayer", "mejor sesión del mes"

Responde SIEMPRE en este formato JSON exacto:
{
  "intent": "QUERY|COMMAND|MAINTENANCE|STATUS|HISTORY",
  "response_text": "Tu respuesta al usuario",
  "action": "none|start_recording|stop_recording|mark_waypoint|reset_oil|reset_brake_front|reset_brake_rear|reset_chain|reset_tire_front|reset_tire_rear",
  "action_params": {},
  "language": "es|en"
}"""


def get_context(device_id):
    """Obtiene contexto actual del dispositivo para el agente."""
    context = {}

    # Estado actual del dispositivo
    try:
        response = TABLE_STATE.get_item(Key={"device_id": device_id})
        state = response.get("Item", {})
        context["current"] = {
            "engine_temp_c": state.get("engine_temp", "N/A"),
            "rpm":           state.get("rpm", "N/A"),
            "speed_kmh":     state.get("speed", "N/A"),
            "voltage":       state.get("voltage", "N/A"),
            "last_seen":     state.get("last_seen", "N/A"),
        }
    except Exception as e:
        print(f"Error getting device state: {e}")
        context["current"] = {}

    # Predicciones de mantenimiento más recientes
    try:
        response = TABLE_MAINTENANCE.query(
            KeyConditionExpression="device_id = :d",
            ExpressionAttributeValues={":d": device_id},
            ScanIndexForward=False,
            Limit=1,
        )
        items = response.get("Items", [])
        if items:
            m = items[0]
            context["maintenance"] = {
                "aceite_km":         m.get("remaining_km_oil", "N/A"),
                "freno_del_km":      m.get("remaining_km_brake_front", "N/A"),
                "freno_tra_km":      m.get("remaining_km_brake_rear", "N/A"),
                "cadena_km":         m.get("remaining_km_chain", "N/A"),
                "llanta_del_km":     m.get("remaining_km_tire_front", "N/A"),
                "llanta_tra_km":     m.get("remaining_km_tire_rear", "N/A"),
                "urgencia":          m.get("urgency", "ok"),
                "componente_critico": m.get("most_critical_component", "ninguno"),
            }
    except Exception as e:
        print(f"Error getting maintenance: {e}")
        context["maintenance"] = {}

    # Última sesión
    try:
        response = TABLE_SESSIONS.scan(
            FilterExpression="device_id = :d",
            ExpressionAttributeValues={":d": device_id},
            Limit=5,
        )
        items = sorted(response.get("Items", []),
                       key=lambda x: x.get("timestamp", "0"), reverse=True)
        if items:
            s = items[0]
            context["last_session"] = {
                "fecha":        s.get("date", "N/A"),
                "distancia_km": s.get("distance_km", "N/A"),
                "duracion_min": s.get("duration_min", "N/A"),
            }
    except Exception as e:
        print(f"Error getting sessions: {e}")
        context["last_session"] = {}

    return context


def call_bedrock(text, context, mode):
    """Llama a Claude via Bedrock para procesar el comando."""
    system = SYSTEM_PROMPT.format(
        context=json.dumps(context, indent=2, ensure_ascii=False),
        mode=mode
    )

    response = bedrock.invoke_model(
        modelId="anthropic.claude-3-5-sonnet-20241022-v2:0",
        body=json.dumps({
            "anthropic_version": "bedrock-2023-05-31",
            "max_tokens": 512,
            "system": system,
            "messages": [{"role": "user", "content": text}],
        }),
        contentType="application/json",
        accept="application/json",
    )

    result = json.loads(response["body"].read())
    raw_text = result["content"][0]["text"]

    # Parsear JSON de la respuesta
    try:
        # Limpiar posibles backticks
        clean = raw_text.strip().strip("```json").strip("```").strip()
        return json.loads(clean)
    except Exception:
        return {
            "intent":        "QUERY",
            "response_text": raw_text,
            "action":        "none",
            "action_params": {},
            "language":      "es",
        }


def execute_action(action, action_params, device_id):
    """Ejecuta la acción indicada por el agente."""
    result = {"executed": False, "message": ""}

    if action == "none":
        return result

    if action == "start_recording":
        # Activar grabación de ruta en el estado de sesión
        TABLE_SESSION_STATE.update_item(
            Key={"device_id": device_id},
            UpdateExpression="SET recording = :r",
            ExpressionAttributeValues={":r": "true"},
        )
        result = {"executed": True, "message": "Grabación iniciada"}

    elif action == "stop_recording":
        TABLE_SESSION_STATE.update_item(
            Key={"device_id": device_id},
            UpdateExpression="SET recording = :r",
            ExpressionAttributeValues={":r": "false"},
        )
        result = {"executed": True, "message": "Grabación detenida"}

    elif action == "mark_waypoint":
        tag = action_params.get("tag", "waypoint")
        # Guardar waypoint en S3
        waypoint = {
            "device_id":  device_id,
            "timestamp":  str(int(time.time())),
            "tag":        tag,
            "created_at": datetime.utcnow().isoformat(),
        }
        s3_client.put_object(
            Bucket=BUCKET,
            Key=f"waypoints/{device_id}/{int(time.time())}_{tag}.json",
            Body=json.dumps(waypoint),
        )
        result = {"executed": True, "message": f"Waypoint '{tag}' marcado"}

    elif action.startswith("reset_"):
        # Resetear contador de km desde último servicio
        component = action.replace("reset_", "")
        component_names = {
            "oil":         "aceite",
            "brake_front": "freno delantero",
            "brake_rear":  "freno trasero",
            "chain":       "cadena",
            "tire_front":  "llanta delantera",
            "tire_rear":   "llanta trasera",
        }
        name_es = component_names.get(component, component)

        # Guardar reset en DynamoDB
        dynamodb.Table("Furiosa_Maintenance_Resets").put_item(Item={
            "device_id":   device_id,
            "timestamp":   str(int(time.time())),
            "component":   component,
            "reset_date":  datetime.utcnow().strftime("%Y-%m-%d"),
            "reset_by":    "voice_command",
        })
        result = {"executed": True, "message": f"Contador de {name_es} reiniciado"}

    print(f"⚡ Acción ejecutada: {action} → {result}")
    return result


def handler(event, context):
    body = event
    if isinstance(event.get("body"), str):
        body = json.loads(event["body"])

    text      = body.get("text", "")
    device_id = body.get("device_id", "furiosa_01")
    mode      = body.get("mode", "dashboard")  # riding | dashboard

    if not text:
        return {
            "statusCode": 400,
            "body": json.dumps({"error": "text requerido"}),
        }

    print(f"🎙️  [{mode}] {device_id}: '{text}'")

    # Obtener contexto del dispositivo
    ctx = get_context(device_id)

    # Procesar con Bedrock
    agent_response = call_bedrock(text, ctx, mode)

    # Ejecutar acción si hay
    action_result = execute_action(
        agent_response.get("action", "none"),
        agent_response.get("action_params", {}),
        device_id,
    )

    response_text = agent_response.get("response_text", "")
    print(f"💬 Respuesta: {response_text}")

    return {
        "statusCode": 200,
        "headers":    {"Content-Type": "application/json",
                       "Access-Control-Allow-Origin": "*"},
        "body": json.dumps({
            "response_text":  response_text,
            "intent":         agent_response.get("intent"),
            "action":         agent_response.get("action", "none"),
            "action_executed": action_result.get("executed", False),
            "language":       agent_response.get("language", "es"),
            "mode":           mode,
        }, ensure_ascii=False),
    }
