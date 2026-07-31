"""
training_job.py
Entrena 6 modelos XGBoost en SageMaker (uno por componente)
+ 1 modelo de clasificación de urgencia.

Uso:
    python training_job.py

Pre-requisitos:
    pip install sagemaker boto3 pandas numpy scikit-learn
    python generate_synthetic_data.py  (genera los CSVs)
"""

import boto3
import sagemaker
import os
import json
import time
from sagemaker.inputs import TrainingInput
from sagemaker.estimator import Estimator

# ─── Configuración ────────────────────────────────────────────
REGION        = "us-east-1"
ACCOUNT_ID    = "329068432517"
BUCKET        = "furiosa-data"
PREFIX        = "ml/maintenance"
ROLE_NAME     = "FuriosaMLRole"
ROLE_ARN      = f"arn:aws:iam::{ACCOUNT_ID}:role/{ROLE_NAME}"

boto_session   = boto3.Session(region_name=REGION)
sagemaker_session = sagemaker.Session(boto_session=boto_session)

s3 = boto3.client("s3", region_name=REGION)

# ─── Modelos a entrenar ───────────────────────────────────────
MODELS = [
    {
        "name":       "oil",
        "csv":        "data/train_remaining_km_oil.csv",
        "s3_key":     f"{PREFIX}/train/remaining_km_oil.csv",
        "objective":  "reg:squarederror",
        "type":       "regression",
        "hyperparams": {
            "max_depth":        "6",
            "eta":              "0.1",
            "n_estimators":     "200",
            "subsample":        "0.8",
            "colsample_bytree": "0.8",
            "min_child_weight": "3",
            "gamma":            "0.1",
            "objective":        "reg:squarederror",
            "eval_metric":      "rmse",
            "num_round":        "200",
        }
    },
    {
        "name":       "brake_front",
        "csv":        "data/train_remaining_km_brake_front.csv",
        "s3_key":     f"{PREFIX}/train/remaining_km_brake_front.csv",
        "objective":  "reg:squarederror",
        "type":       "regression",
        "hyperparams": {
            "max_depth":        "5",
            "eta":              "0.1",
            "subsample":        "0.8",
            "colsample_bytree": "0.7",
            "min_child_weight": "2",
            "objective":        "reg:squarederror",
            "eval_metric":      "rmse",
            "num_round":        "200",
        }
    },
    {
        "name":       "brake_rear",
        "csv":        "data/train_remaining_km_brake_rear.csv",
        "s3_key":     f"{PREFIX}/train/remaining_km_brake_rear.csv",
        "objective":  "reg:squarederror",
        "type":       "regression",
        "hyperparams": {
            "max_depth":        "5",
            "eta":              "0.1",
            "subsample":        "0.8",
            "colsample_bytree": "0.7",
            "min_child_weight": "2",
            "objective":        "reg:squarederror",
            "eval_metric":      "rmse",
            "num_round":        "200",
        }
    },
    {
        "name":       "chain",
        "csv":        "data/train_remaining_km_chain.csv",
        "s3_key":     f"{PREFIX}/train/remaining_km_chain.csv",
        "objective":  "reg:squarederror",
        "type":       "regression",
        "hyperparams": {
            "max_depth":        "4",
            "eta":              "0.1",
            "subsample":        "0.8",
            "colsample_bytree": "0.8",
            "min_child_weight": "3",
            "objective":        "reg:squarederror",
            "eval_metric":      "rmse",
            "num_round":        "150",
        }
    },
    {
        "name":       "tire_front",
        "csv":        "data/train_remaining_km_tire_front.csv",
        "s3_key":     f"{PREFIX}/train/remaining_km_tire_front.csv",
        "objective":  "reg:squarederror",
        "type":       "regression",
        "hyperparams": {
            "max_depth":        "5",
            "eta":              "0.1",
            "subsample":        "0.8",
            "colsample_bytree": "0.8",
            "min_child_weight": "3",
            "objective":        "reg:squarederror",
            "eval_metric":      "rmse",
            "num_round":        "200",
        }
    },
    {
        "name":       "tire_rear",
        "csv":        "data/train_remaining_km_tire_rear.csv",
        "s3_key":     f"{PREFIX}/train/remaining_km_tire_rear.csv",
        "objective":  "reg:squarederror",
        "type":       "regression",
        "hyperparams": {
            "max_depth":        "5",
            "eta":              "0.1",
            "subsample":        "0.8",
            "colsample_bytree": "0.8",
            "min_child_weight": "3",
            "objective":        "reg:squarederror",
            "eval_metric":      "rmse",
            "num_round":        "200",
        }
    },
    {
        "name":       "urgency",
        "csv":        "data/train_urgency.csv",
        "s3_key":     f"{PREFIX}/train/urgency.csv",
        "objective":  "multi:softmax",
        "type":       "classification",
        "hyperparams": {
            "max_depth":        "5",
            "eta":              "0.1",
            "subsample":        "0.8",
            "colsample_bytree": "0.7",
            "min_child_weight": "2",
            "objective":        "multi:softmax",
            "num_class":        "4",   # ok / watch / soon / critical
            "eval_metric":      "merror",
            "num_round":        "150",
        }
    },
]

# ─── Paso 1: Crear IAM Role para SageMaker ───────────────────
def create_sagemaker_role():
    iam = boto3.client("iam", region_name=REGION)

    try:
        role = iam.get_role(RoleName=ROLE_NAME)
        print(f"✅ Role ya existe: {ROLE_ARN}")
        return ROLE_ARN
    except iam.exceptions.NoSuchEntityException:
        pass

    print("🔧 Creando IAM Role para SageMaker...")
    iam.create_role(
        RoleName=ROLE_NAME,
        AssumeRolePolicyDocument=json.dumps({
            "Version": "2012-10-17",
            "Statement": [{
                "Effect": "Allow",
                "Principal": {"Service": "sagemaker.amazonaws.com"},
                "Action": "sts:AssumeRole"
            }]
        })
    )

    iam.attach_role_policy(
        RoleName=ROLE_NAME,
        PolicyArn="arn:aws:iam::aws:policy/AmazonSageMakerFullAccess"
    )
    iam.attach_role_policy(
        RoleName=ROLE_NAME,
        PolicyArn="arn:aws:iam::aws:policy/AmazonS3FullAccess"
    )

    print(f"✅ Role creado: {ROLE_ARN}")
    time.sleep(10)  # propagación IAM
    return ROLE_ARN


# ─── Paso 2: Subir CSVs a S3 ─────────────────────────────────
def upload_datasets():
    print("\n📤 Subiendo datasets a S3...")
    for model in MODELS:
        if os.path.exists(model["csv"]):
            s3.upload_file(model["csv"], BUCKET, model["s3_key"])
            print(f"  ✅ {model['csv']} → s3://{BUCKET}/{model['s3_key']}")
        else:
            print(f"  ❌ No encontrado: {model['csv']} — ejecuta generate_synthetic_data.py")


# ─── Paso 3: Obtener imagen XGBoost de SageMaker ─────────────
def get_xgboost_image():
    return sagemaker.image_uris.retrieve(
        framework="xgboost",
        region=REGION,
        version="1.7-1",
    )


# ─── Paso 4: Entrenar todos los modelos ──────────────────────
def train_all_models(role_arn):
    image_uri = get_xgboost_image()
    print(f"\n🐳 Imagen XGBoost: {image_uri}")

    model_arns = {}

    for model in MODELS:
        print(f"\n{'─'*50}")
        print(f"🚀 Entrenando modelo: {model['name'].upper()}")
        print(f"{'─'*50}")

        job_name = f"furiosa-maintenance-{model['name']}-{int(time.time())}"

        estimator = Estimator(
            image_uri=image_uri,
            role=role_arn,
            instance_count=1,
            instance_type="ml.m5.large",
            volume_size=10,
            max_run=3600,
            output_path=f"s3://{BUCKET}/{PREFIX}/models/{model['name']}/",
            sagemaker_session=sagemaker_session,
            hyperparameters=model["hyperparams"],
            tags=[
                {"Key": "project", "Value": "furiosa"},
                {"Key": "component", "Value": model["name"]},
                {"Key": "type", "Value": "maintenance_predictive"},
            ]
        )

        train_input = TrainingInput(
            s3_data=f"s3://{BUCKET}/{model['s3_key']}",
            content_type="text/csv",
        )

        estimator.fit(
            inputs={"train": train_input},
            job_name=job_name,
            wait=True,
            logs=True,
        )

        model_arns[model["name"]] = estimator.model_data
        print(f"✅ Modelo {model['name']} guardado en: {estimator.model_data}")

    return model_arns


# ─── Paso 5: Guardar ARNs de modelos ─────────────────────────
def save_model_arns(model_arns):
    os.makedirs("data", exist_ok=True)
    with open("data/model_arns.json", "w") as f:
        json.dump(model_arns, f, indent=2)
    print(f"\n💾 ARNs guardados en data/model_arns.json")
    for name, arn in model_arns.items():
        print(f"  {name}: {arn}")


# ─── Main ─────────────────────────────────────────────────────
if __name__ == "__main__":
    print("=" * 60)
    print("  FURIOSA — Entrenamiento Mantenimiento Predictivo")
    print("=" * 60)

    role_arn = create_sagemaker_role()
    upload_datasets()

    print("\n⏳ Iniciando training jobs en SageMaker...")
    print("   Cada job tarda ~5-8 minutos en ml.m5.large")
    print("   7 modelos en total → ~45-55 minutos estimado\n")

    model_arns = train_all_models(role_arn)
    save_model_arns(model_arns)

    print("\n" + "=" * 60)
    print("✅ ENTRENAMIENTO COMPLETO")
    print("   Siguiente paso: python deploy_endpoint.py")
    print("=" * 60)
