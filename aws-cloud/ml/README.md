# 🤖 Furiosa ML — Mantenimiento Predictivo

## Archivos

| Archivo | Qué hace |
|---|---|
| `generate_synthetic_data.py` | Genera 2000 sesiones sintéticas realistas |
| `training_job.py` | Entrena 7 modelos XGBoost en SageMaker |
| `deploy_endpoint.py` | Despliega endpoints + Lambda + DynamoDB |

## Setup

```bash
pip install sagemaker boto3 pandas numpy scikit-learn
```

## Ejecución en orden

```bash
# 1. Generar datos sintéticos
python generate_synthetic_data.py
# → data/train_remaining_km_oil.csv
# → data/train_remaining_km_brake_front.csv
# → data/train_remaining_km_brake_rear.csv
# → data/train_remaining_km_chain.csv
# → data/train_remaining_km_tire_front.csv
# → data/train_remaining_km_tire_rear.csv
# → data/train_urgency.csv

# 2. Entrenar en SageMaker (~45-55 min)
python training_job.py
# → data/model_arns.json

# 3. Desplegar endpoints y Lambda
python deploy_endpoint.py
# → data/endpoints.json
# → Lambda: furiosa-maintenance-predict
# → DynamoDB: Furiosa_Predictions
```

## Modelos entrenados

| Modelo | Target | Algoritmo | Tipo |
|---|---|---|---|
| `oil` | km restantes aceite | XGBoost | Regresión |
| `brake_front` | km restantes freno delantero | XGBoost | Regresión |
| `brake_rear` | km restantes freno trasero | XGBoost | Regresión |
| `chain` | km restantes cadena | XGBoost | Regresión |
| `tire_front` | km restantes llanta delantera | XGBoost | Regresión |
| `tire_rear` | km restantes llanta trasera | XGBoost | Regresión |
| `urgency` | ok/watch/soon/critical | XGBoost | Clasificación |

## Test desde CLI

```bash
/usr/local/bin/aws lambda invoke \
  --function-name furiosa-maintenance-predict \
  --payload '{"session_id":"test","device_id":"furiosa_01","route_type":"mixta","distance_km":87.4,"rpm_avg":4200,"engine_temp_max_c":97.5,"km_since_oil":3100,"km_since_brake_front":4200}' \
  --cli-binary-format raw-in-base64-out \
  response.json --region us-east-1 && cat response.json
```

## Costos estimados AWS

| Recurso | Costo estimado |
|---|---|
| Training jobs (7 x ml.m5.large ~8min) | ~$0.15 |
| Endpoints (7 x ml.t2.medium) | ~$0.14/hora |
| Lambda invocaciones | ~$0.00001/invocación |
| DynamoDB Furiosa_Predictions | Pay per request |

**Tip:** Apaga los endpoints cuando no los uses:
```bash
aws sagemaker delete-endpoint --endpoint-name furiosa-maintenance-oil --region us-east-1
```
