"""
deploy_endpoint.py
Despliega los modelos entrenados como endpoints de SageMaker
y prueba predicciones en tiempo real.

Uso:
    python deploy_endpoint.py

Pre-requisitos:
    python training_job.py completado
    data/model_arns.json existente
"""

import boto3
import sagemaker
import json
import time
import numpy as np
import os
from sagemaker.xgboost import XGBoostModel
from sagemaker.serializers import CSVSerializer
from sagemaker.deserializers import JSONDeserializer

# ─── Configuración ────────────────────────────────────────────
REGION     = "us-east-1"
ACCOUNT_ID = "329068432517"
BUCKET     = "furiosa-data"
ROLE_ARN   = f"arn:aws:iam::{ACCOUNT_ID}:role/FuriosaMLRole"

boto_session      = boto3.Session(region_name=REGION)
sagemaker_session = sagemaker.Session(boto_session=boto_session)
sm_client         = boto3.client("sagemaker", region_name=REGION)
sm_runtime        = boto3.client("sagemaker-runtime", region_name=REGION)
lambda_client     = boto3.client("lambda", region_name=REGION)
iam_client        = boto3.client("iam", region_name=REGION)

# Features en el mismo orden que en el CSV de entrenamiento
FEATURE_ORDER = [
    "distance_km", "duration_min", "speed_avg_kmh", "speed_max_kmh",
    "rpm_avg", "rpm_max", "rpm_redzone_pct", "rpm_redzone_time_min",
    "engine_temp_avg_c", "engine_temp_max_c", "engine_temp_over90_min", "engine_temp_over95_min",
    "oil_temp_avg_c", "oil_temp_max_c",
    "brake_temp_front_max_c", "brake_temp_rear_max_c",
    "hard_brake_events", "hard_accel_events",
    "lean_over30_time_min", "lean_over40_time_min",
    "tire_temp_front_max_c", "tire_temp_rear_max_c",
    "tire_pressure_front_avg_psi", "tire_pressure_rear_avg_psi",
    "vibration_avg", "vibration_max",
    "voltage_drop", "current_avg_amp", "energy_consumed_wh",
    "fuel_consumed_pct", "throttle_avg_pct", "throttle_over80_time_min",
    "km_since_brake_front", "km_since_brake_rear", "km_since_oil",
    "km_since_chain", "km_since_tire_front", "km_since_tire_rear",
    "route_type_enc",
]

URGENCY_MAP = {0: "ok", 1: "watch", 2: "soon", 3: "critical"}
ROUTE_MAP   = {"urbana": 0, "carretera": 1, "montana": 2, "mixta": 3}


# ─── Paso 1: Desplegar endpoints ─────────────────────────────
def deploy_endpoints():
    with open("data/model_arns.json") as f:
        model_arns = json.load(f)

    endpoints = {}

    for component, model_data in model_arns.items():
        endpoint_name = f"furiosa-maintenance-{component}"

        # Verificar si ya existe
        try:
            sm_client.describe_endpoint(EndpointName=endpoint_name)
            print(f"✅ Endpoint ya existe: {endpoint_name}")
            endpoints[component] = endpoint_name
            continue
        except sm_client.exceptions.ClientError:
            pass

        print(f"\n🚀 Desplegando endpoint: {endpoint_name}")

        model = XGBoostModel(
            model_data=model_data,
            role=ROLE_ARN,
            framework_version="1.7-1",
            sagemaker_session=sagemaker_session,
        )

        predictor = model.deploy(
            initial_instance_count=1,
            instance_type="ml.t2.medium",  # económico para inferencia
            endpoint_name=endpoint_name,
            serializer=CSVSerializer(),
            wait=True,
        )

        endpoints[component] = endpoint_name
        print(f"✅ Endpoint listo: {endpoint_name}")
        time.sleep(5)

    with open("data/endpoints.json", "w") as f:
        json.dump(endpoints, f, indent=2)

    print(f"\n💾 Endpoints guardados en data/endpoints.json")
    return endpoints


# ─── Paso 2: Función de predicción ───────────────────────────
def predict(session_data: dict, endpoints: dict) -> dict:
    """
    Recibe un dict con los datos de stage de una sesión
    y devuelve predicciones de todos los componentes.
    """
    route_enc = ROUTE_MAP.get(session_data.get("route_type", "mixta"), 3)

    features = [
        session_data.get("distance_km", 0),
        session_data.get("duration_min", 0),
        session_data.get("speed_avg_kmh", 0),
        session_data.get("speed_max_kmh", 0),
        session_data.get("rpm_avg", 0),
        session_data.get("rpm_max", 0),
        session_data.get("rpm_redzone_pct", 0),
        session_data.get("rpm_redzone_time_min", 0),
        session_data.get("engine_temp_avg_c", 0),
        session_data.get("engine_temp_max_c", 0),
        session_data.get("engine_temp_over90_min", 0),
        session_data.get("engine_temp_over95_min", 0),
        session_data.get("oil_temp_avg_c", 0),
        session_data.get("oil_temp_max_c", 0),
        session_data.get("brake_temp_front_max_c", 0),
        session_data.get("brake_temp_rear_max_c", 0),
        session_data.get("hard_brake_events", 0),
        session_data.get("hard_accel_events", 0),
        session_data.get("lean_over30_time_min", 0),
        session_data.get("lean_over40_time_min", 0),
        session_data.get("tire_temp_front_max_c", 0),
        session_data.get("tire_temp_rear_max_c", 0),
        session_data.get("tire_pressure_front_avg_psi", 32),
        session_data.get("tire_pressure_rear_avg_psi", 36),
        session_data.get("vibration_avg", 0),
        session_data.get("vibration_max", 0),
        session_data.get("voltage_drop", 0),
        session_data.get("current_avg_amp", 0),
        session_data.get("energy_consumed_wh", 0),
        session_data.get("fuel_consumed_pct", 0),
        session_data.get("throttle_avg_pct", 0),
        session_data.get("throttle_over80_time_min", 0),
        session_data.get("km_since_brake_front", 0),
        session_data.get("km_since_brake_rear", 0),
        session_data.get("km_since_oil", 0),
        session_data.get("km_since_chain", 0),
        session_data.get("km_since_tire_front", 0),
        session_data.get("km_since_tire_rear", 0),
        route_enc,
    ]

    csv_payload = ",".join(map(str, features))
    predictions = {}

    for component, endpoint_name in endpoints.items():
        response = sm_runtime.invoke_endpoint(
            EndpointName=endpoint_name,
            ContentType="text/csv",
            Body=csv_payload,
        )
        result = float(response["Body"].read().decode("utf-8").strip())

        if component == "urgency":
            predictions[component] = URGENCY_MAP.get(int(result), "unknown")
        else:
            predictions[f"remaining_km_{component}"] = round(max(0, result), 1)

    # Determinar componente más crítico
    km_preds = {k: v for k, v in predictions.items() if k.startswith("remaining_km_")}
    if km_preds:
        most_critical_key = min(km_preds, key=km_preds.get)
        most_critical = most_critical_key.replace("remaining_km_", "")
        predictions["most_critical_component"] = most_critical
        predictions["most_critical_remaining_km"] = km_preds[most_critical_key]

    return predictions


# ─── Paso 3: Crear Lambda para inferencia desde pipeline ──────
def create_inference_lambda(endpoints: dict):
    print("\n🔧 Creando Lambda de inferencia...")

    lambda_code = f"""
import boto3
import json

SM_RUNTIME = boto3.client('sagemaker-runtime', region_name='{REGION}')
DYNAMODB   = boto3.resource('dynamodb', region_name='{REGION}')
TABLE      = DYNAMODB.Table('Furiosa_Predictions')

ENDPOINTS = {json.dumps(endpoints)}
URGENCY_MAP = {{"0": "ok", "1": "watch", "2": "soon", "3": "critical"}}
ROUTE_MAP   = {{"urbana": 0, "carretera": 1, "montana": 2, "mixta": 3}}

def handler(event, context):
    session = event.get('session', event)
    route_enc = ROUTE_MAP.get(session.get('route_type', 'mixta'), 3)

    features = [
        session.get('distance_km', 0),
        session.get('duration_min', 0),
        session.get('speed_avg_kmh', 0),
        session.get('speed_max_kmh', 0),
        session.get('rpm_avg', 0),
        session.get('rpm_max', 0),
        session.get('rpm_redzone_pct', 0),
        session.get('rpm_redzone_time_min', 0),
        session.get('engine_temp_avg_c', 0),
        session.get('engine_temp_max_c', 0),
        session.get('engine_temp_over90_min', 0),
        session.get('engine_temp_over95_min', 0),
        session.get('oil_temp_avg_c', 0),
        session.get('oil_temp_max_c', 0),
        session.get('brake_temp_front_max_c', 0),
        session.get('brake_temp_rear_max_c', 0),
        session.get('hard_brake_events', 0),
        session.get('hard_accel_events', 0),
        session.get('lean_over30_time_min', 0),
        session.get('lean_over40_time_min', 0),
        session.get('tire_temp_front_max_c', 0),
        session.get('tire_temp_rear_max_c', 0),
        session.get('tire_pressure_front_avg_psi', 32),
        session.get('tire_pressure_rear_avg_psi', 36),
        session.get('vibration_avg', 0),
        session.get('vibration_max', 0),
        session.get('voltage_drop', 0),
        session.get('current_avg_amp', 0),
        session.get('energy_consumed_wh', 0),
        session.get('fuel_consumed_pct', 0),
        session.get('throttle_avg_pct', 0),
        session.get('throttle_over80_time_min', 0),
        session.get('km_since_brake_front', 0),
        session.get('km_since_brake_rear', 0),
        session.get('km_since_oil', 0),
        session.get('km_since_chain', 0),
        session.get('km_since_tire_front', 0),
        session.get('km_since_tire_rear', 0),
        route_enc,
    ]

    csv_payload = ','.join(map(str, features))
    predictions = {{}}

    for component, endpoint_name in ENDPOINTS.items():
        try:
            response = SM_RUNTIME.invoke_endpoint(
                EndpointName=endpoint_name,
                ContentType='text/csv',
                Body=csv_payload,
            )
            result = float(response['Body'].read().decode('utf-8').strip())
            if component == 'urgency':
                predictions[component] = URGENCY_MAP.get(str(int(result)), 'unknown')
            else:
                predictions[f'remaining_km_{{component}}'] = round(max(0, result), 1)
        except Exception as e:
            predictions[f'error_{{component}}'] = str(e)

    km_preds = {{k: v for k, v in predictions.items() if k.startswith('remaining_km_')}}
    if km_preds:
        most_critical_key = min(km_preds, key=km_preds.get)
        predictions['most_critical_component'] = most_critical_key.replace('remaining_km_', '')
        predictions['most_critical_remaining_km'] = km_preds[most_critical_key]

    item = {{
        'session_id':    session.get('session_id', 'unknown'),
        'device_id':     session.get('device_id', 'furiosa_01'),
        'timestamp':     session.get('timestamp', '0'),
        **{{k: str(v) for k, v in predictions.items()}}
    }}

    TABLE.put_item(Item=item)
    return {{'statusCode': 200, 'predictions': predictions}}
"""

    # Crear ZIP en memoria
    import io
    import zipfile

    zip_buffer = io.BytesIO()
    with zipfile.ZipFile(zip_buffer, "w", zipfile.ZIP_DEFLATED) as zf:
        zf.writestr("lambda_function.py", lambda_code)
    zip_buffer.seek(0)

    # Crear role Lambda si no existe
    try:
        lambda_role = iam_client.get_role(RoleName="FuriosaLambdaMLRole")
        lambda_role_arn = lambda_role["Role"]["Arn"]
    except iam_client.exceptions.NoSuchEntityException:
        lambda_role = iam_client.create_role(
            RoleName="FuriosaLambdaMLRole",
            AssumeRolePolicyDocument=json.dumps({
                "Version": "2012-10-17",
                "Statement": [{"Effect": "Allow",
                               "Principal": {"Service": "lambda.amazonaws.com"},
                               "Action": "sts:AssumeRole"}]
            })
        )
        iam_client.attach_role_policy(RoleName="FuriosaLambdaMLRole",
            PolicyArn="arn:aws:iam::aws:policy/AmazonSageMakerFullAccess")
        iam_client.attach_role_policy(RoleName="FuriosaLambdaMLRole",
            PolicyArn="arn:aws:iam::aws:policy/AmazonDynamoDBFullAccess")
        iam_client.attach_role_policy(RoleName="FuriosaLambdaMLRole",
            PolicyArn="arn:aws:iam::aws:policy/service-role/AWSLambdaBasicExecutionRole")
        lambda_role_arn = lambda_role["Role"]["Arn"]
        time.sleep(10)

    # Crear tabla DynamoDB para predicciones
    dynamo = boto3.client("dynamodb", region_name=REGION)
    try:
        dynamo.create_table(
            TableName="Furiosa_Predictions",
            AttributeDefinitions=[
                {"AttributeName": "session_id", "AttributeType": "S"},
                {"AttributeName": "timestamp",  "AttributeType": "S"},
            ],
            KeySchema=[
                {"AttributeName": "session_id", "KeyType": "HASH"},
                {"AttributeName": "timestamp",  "KeyType": "RANGE"},
            ],
            BillingMode="PAY_PER_REQUEST",
        )
        print("✅ Tabla Furiosa_Predictions creada")
    except dynamo.exceptions.ResourceInUseException:
        print("✅ Tabla Furiosa_Predictions ya existe")

    # Crear/actualizar Lambda
    try:
        lambda_client.create_function(
            FunctionName="furiosa-maintenance-predict",
            Runtime="python3.11",
            Role=lambda_role_arn,
            Handler="lambda_function.handler",
            Code={"ZipFile": zip_buffer.read()},
            Timeout=60,
            MemorySize=256,
            Description="Furiosa — inferencia mantenimiento predictivo",
            Tags={"project": "furiosa"},
        )
        print("✅ Lambda creada: furiosa-maintenance-predict")
    except lambda_client.exceptions.ResourceConflictException:
        zip_buffer.seek(0)
        lambda_client.update_function_code(
            FunctionName="furiosa-maintenance-predict",
            ZipFile=zip_buffer.read(),
        )
        print("✅ Lambda actualizada: furiosa-maintenance-predict")


# ─── Paso 4: Test de predicción ───────────────────────────────
def test_prediction(endpoints: dict):
    print("\n🧪 Test de predicción con sesión de ejemplo...")

    test_session = {
        "session_id":              "furiosa_01_test_001",
        "device_id":               "furiosa_01",
        "route_type":              "mixta",
        "distance_km":             87.4,
        "duration_min":            162.3,
        "speed_avg_kmh":           45.2,
        "speed_max_kmh":           112.0,
        "rpm_avg":                 4200,
        "rpm_max":                 8100,
        "rpm_redzone_pct":         2.9,
        "rpm_redzone_time_min":    4.7,
        "engine_temp_avg_c":       89.4,
        "engine_temp_max_c":       97.5,
        "engine_temp_over90_min":  12.4,
        "engine_temp_over95_min":  3.1,
        "oil_temp_avg_c":          86.2,
        "oil_temp_max_c":          94.1,
        "brake_temp_front_max_c":  112.4,
        "brake_temp_rear_max_c":   89.3,
        "hard_brake_events":       8,
        "hard_accel_events":       6,
        "lean_over30_time_min":    3.8,
        "lean_over40_time_min":    0.4,
        "tire_temp_front_max_c":   52.4,
        "tire_temp_rear_max_c":    58.1,
        "tire_pressure_front_avg_psi": 32.3,
        "tire_pressure_rear_avg_psi":  35.8,
        "vibration_avg":           0.043,
        "vibration_max":           0.312,
        "voltage_drop":            0.5,
        "current_avg_amp":         4.1,
        "energy_consumed_wh":      53.3,
        "fuel_consumed_pct":       26.0,
        "throttle_avg_pct":        38.4,
        "throttle_over80_time_min": 6.2,
        "km_since_brake_front":    4200,
        "km_since_brake_rear":     3800,
        "km_since_oil":            3100,
        "km_since_chain":          5200,
        "km_since_tire_front":     8400,
        "km_since_tire_rear":      6100,
    }

    predictions = predict(test_session, endpoints)

    print("\n" + "═" * 50)
    print("  📊 PREDICCIONES DE MANTENIMIENTO")
    print("═" * 50)
    print(f"  🔴 Componente crítico: {predictions.get('most_critical_component', 'N/A').upper()}")
    print(f"  ⚠️  Urgencia:          {predictions.get('urgency', 'N/A').upper()}")
    print(f"  📍 Km restantes:       {predictions.get('most_critical_remaining_km', 0)} km")
    print()
    print("  Por componente:")
    for key, val in sorted(predictions.items()):
        if key.startswith("remaining_km_"):
            comp = key.replace("remaining_km_", "")
            print(f"    {comp:<20} {val:>8.1f} km restantes")
    print("═" * 50)

    return predictions


# ─── Main ─────────────────────────────────────────────────────
if __name__ == "__main__":
    print("=" * 60)
    print("  FURIOSA — Deploy Endpoints + Lambda")
    print("=" * 60)

    endpoints = deploy_endpoints()
    test_prediction(endpoints)
    create_inference_lambda(endpoints)

    print("\n" + "=" * 60)
    print("✅ DEPLOYMENT COMPLETO")
    print(f"   Endpoints activos: {len(endpoints)}")
    print(f"   Lambda: furiosa-maintenance-predict")
    print(f"   DynamoDB: Furiosa_Predictions")
    print()
    print("   Para invocar desde CLI:")
    print('   aws lambda invoke \\')
    print('     --function-name furiosa-maintenance-predict \\')
    print('     --payload file://data/test_session.json \\')
    print('     --cli-binary-format raw-in-base64-out \\')
    print('     response.json --region us-east-1')
    print("=" * 60)
