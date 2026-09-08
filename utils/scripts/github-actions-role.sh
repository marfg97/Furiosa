#!/bin/bash
# create-role.sh
# Script para crear el rol IAM desde la CLI de AWS

set -e

ACCOUNT_ID="329068432517"
ROLE_NAME="github-actions-furiosa-deploy"
ROLE_DESCRIPTION="GitHub Actions deployment role for Furiosa Moto IoT. Assumed via OIDC to deploy Lambda functions (L1-L5), S3 artifacts, and Glue ETL jobs."

echo "📦 Creando rol IAM para GitHub Actions..."

# 1. Crear la política de confianza (Trust Policy)
cat > /tmp/trust-policy.json << EOF
{
  "Version": "2012-10-17",
  "Statement": [
    {
      "Effect": "Allow",
      "Principal": {
        "Federated": "arn:aws:iam::${ACCOUNT_ID}:oidc-provider/token.actions.githubusercontent.com"
      },
      "Action": "sts:AssumeRoleWithWebIdentity",
      "Condition": {
        "StringEquals": {
          "token.actions.githubusercontent.com:aud": "sts.amazonaws.com"
        },
        "StringLike": {
          "token.actions.githubusercontent.com:sub": "repo:marfg97/Furiosa:*"
        }
      }
    }
  ]
}
EOF

# 2. Crear la política de permisos (Permissions Policy)
cat > /tmp/permissions-policy.json << EOF
{
  "Version": "2012-10-17",
  "Statement": [
    {
      "Effect": "Allow",
      "Action": [
        "lambda:UpdateFunctionCode",
        "lambda:GetFunction",
        "lambda:GetFunctionConfiguration"
      ],
      "Resource": [
        "arn:aws:lambda:us-east-1:${ACCOUNT_ID}:function:L1_realtime_monitor",
        "arn:aws:lambda:us-east-1:${ACCOUNT_ID}:function:L2_session_detector",
        "arn:aws:lambda:us-east-1:${ACCOUNT_ID}:function:L3_maintenance_predict",
        "arn:aws:lambda:us-east-1:${ACCOUNT_ID}:function:L4_voice_command_handler",
        "arn:aws:lambda:us-east-1:${ACCOUNT_ID}:function:L5_alert_dispatcher"
      ]
    },
    {
      "Effect": "Allow",
      "Action": [
        "s3:PutObject",
        "s3:GetObject",
        "s3:ListBucket"
      ],
      "Resource": [
        "arn:aws:s3:::furiosa-data",
        "arn:aws:s3:::furiosa-data/*"
      ]
    },
    {
      "Effect": "Allow",
      "Action": [
        "glue:StartJobRun",
        "glue:GetJobRun"
      ],
      "Resource": "*"
    }
  ]
}
EOF

# 3. Crear el rol
echo "🔄 Creando rol..."
aws iam create-role \
  --role-name "$ROLE_NAME" \
  --description "$ROLE_DESCRIPTION" \
  --assume-role-policy-document file:///tmp/trust-policy.json \
  --region us-east-1

# 4. Adjuntar la política de permisos
echo "🔗 Adjuntando política de permisos..."
aws iam put-role-policy \
  --role-name "$ROLE_NAME" \
  --policy-name "${ROLE_NAME}-policy" \
  --policy-document file:///tmp/permissions-policy.json

# 5. Mostrar el ARN del rol
ROLE_ARN=$(aws iam get-role --role-name "$ROLE_NAME" --query "Role.Arn" --output text)
echo ""
echo "✅ Rol creado exitosamente!"
echo "================================================"
echo "  ARN del rol: $ROLE_ARN"
echo "================================================"
echo ""
echo "📋 Agrega este ARN como secreto en GitHub:"
echo "   Name: AWS_ROLE_TO_ASSUME"
echo "   Value: $ROLE_ARN"
echo ""
echo "🔧 También actualiza el workflow de GitHub Actions"
echo "   con el nombre de este rol."

# 6. Limpieza
rm -f /tmp/trust-policy.json /tmp/permissions-policy.json