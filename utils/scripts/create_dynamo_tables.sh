#!/bin/bash
# create-all-tables.sh

REGION="us-east-1"

tables=(
  "Furiosa_Telemetry:device_id:S:timestamp:N"
  "Furiosa_Sessions:session_id:S:device_id:S:start_timestamp:N"
  "Furiosa_Predictions:session_id:S:device_id:S:predict_timestamp:N"
  "Furiosa_Maintenance:device_id:S:component:S:updated_timestamp:N"
  "Furiosa_Alerts:device_id:S:alert_timestamp:N"
)

for table_def in "${tables[@]}"; do
  IFS=':' read -r table_name hash_key hash_type range_key range_type gsi_key gsi_type <<< "$table_def"
  
  echo "📦 Creando tabla: $table_name..."
  
  aws dynamodb create-table \
    --table-name "$table_name" \
    --attribute-definitions \
      AttributeName=$hash_key,AttributeType=$hash_type \
      AttributeName=$range_key,AttributeType=$range_type \
    --key-schema \
      AttributeName=$hash_key,KeyType=HASH \
      AttributeName=$range_key,KeyType=RANGE \
    --billing-mode PAY_PER_REQUEST \
    --region "$REGION"
  
  aws dynamodb wait table-exists --table-name "$table_name" --region "$REGION"
  echo "✅ Tabla $table_name creada"
done