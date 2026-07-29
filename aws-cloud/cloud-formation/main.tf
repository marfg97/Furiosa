terraform {
  required_providers {
    aws = {
      source  = "hashicorp/aws"
      version = "~> 5.0"
    }
  }
}

provider "aws" {
  region = var.aws_region
}

# ─────────────────────────────────────────
# VARIABLES
# ─────────────────────────────────────────
variable "aws_region"   { default = "us-east-1" }
variable "device_name"  { default = "moto_android_01" }
variable "project_name" { default = "moto-telemetry" }

# ─────────────────────────────────────────
# IoT THING (representa el Android)
# ─────────────────────────────────────────
resource "aws_iot_thing" "android_dashboard" {
  name = var.device_name

  attributes = {
    type    = "android_dashboard"
    project = var.project_name
  }
}

# ─────────────────────────────────────────
# CERTIFICADO X.509 (genera Terraform, descarga manualmente)
# ─────────────────────────────────────────
resource "aws_iot_certificate" "device_cert" {
  active = true
}

output "certificate_pem" {
  value     = aws_iot_certificate.device_cert.certificate_pem
  sensitive = true
}

output "private_key_pem" {
  value     = aws_iot_certificate.device_cert.private_key
  sensitive = true
}

# Adjuntar certificado al Thing
resource "aws_iot_thing_principal_attachment" "attach" {
  principal = aws_iot_certificate.device_cert.arn
  thing     = aws_iot_thing.android_dashboard.name
}

# ─────────────────────────────────────────
# IoT POLICY — permisos MQTT
# ─────────────────────────────────────────
resource "aws_iot_policy" "device_policy" {
  name = "${var.project_name}-device-policy"

  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Effect   = "Allow"
        Action   = ["iot:Connect"]
        Resource = "arn:aws:iot:${var.aws_region}:*:client/${var.device_name}"
      },
      {
        Effect   = "Allow"
        Action   = ["iot:Publish"]
        Resource = [
          "arn:aws:iot:${var.aws_region}:*:topic/moto/${var.device_name}/telemetry",
          "arn:aws:iot:${var.aws_region}:*:topic/moto/${var.device_name}/gps",
          "arn:aws:iot:${var.aws_region}:*:topic/moto/${var.device_name}/imu"
        ]
      },
      {
        Effect   = "Allow"
        Action   = ["iot:Subscribe", "iot:Receive"]
        Resource = "arn:aws:iot:${var.aws_region}:*:topic/moto/${var.device_name}/commands"
      }
    ]
  })
}

resource "aws_iot_policy_attachment" "attach_policy" {
  policy = aws_iot_policy.device_policy.name
  target = aws_iot_certificate.device_cert.arn
}

# ─────────────────────────────────────────
# S3 — Data Lake (raw Parquet)
# ─────────────────────────────────────────
resource "aws_s3_bucket" "data_lake" {
  bucket = "${var.project_name}-data-lake-${random_id.suffix.hex}"
}

resource "random_id" "suffix" {
  byte_length = 4
}

resource "aws_s3_bucket_versioning" "versioning" {
  bucket = aws_s3_bucket.data_lake.id
  versioning_configuration { status = "Enabled" }
}

resource "aws_s3_bucket_server_side_encryption_configuration" "encryption" {
  bucket = aws_s3_bucket.data_lake.id
  rule {
    apply_server_side_encryption_by_default {
      sse_algorithm = "AES256"
    }
  }
}

# ─────────────────────────────────────────
# KINESIS FIREHOSE → S3
# ─────────────────────────────────────────
resource "aws_iam_role" "firehose_role" {
  name = "${var.project_name}-firehose-role"
  assume_role_policy = jsonencode({
    Version = "2012-10-17"
    Statement = [{
      Action    = "sts:AssumeRole"
      Effect    = "Allow"
      Principal = { Service = "firehose.amazonaws.com" }
    }]
  })
}

resource "aws_iam_role_policy" "firehose_policy" {
  role = aws_iam_role.firehose_role.id
  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [{
      Effect   = "Allow"
      Action   = ["s3:PutObject", "s3:GetBucketLocation"]
      Resource = [
        aws_s3_bucket.data_lake.arn,
        "${aws_s3_bucket.data_lake.arn}/*"
      ]
    }]
  })
}

resource "aws_kinesis_firehose_delivery_stream" "telemetry_stream" {
  name        = "${var.project_name}-firehose"
  destination = "extended_s3"

  extended_s3_configuration {
    role_arn   = aws_iam_role.firehose_role.arn
    bucket_arn = aws_s3_bucket.data_lake.arn

    prefix              = "raw/year=!{timestamp:yyyy}/month=!{timestamp:MM}/day=!{timestamp:dd}/"
    error_output_prefix = "errors/!{firehose:error-output-type}/year=!{timestamp:yyyy}/"

    buffering_interval = 60   # segundos
    buffering_size     = 5    # MB

    compression_format = "GZIP"
  }
}

# ─────────────────────────────────────────
# IoT RULE → Firehose (enruta todos los topics de telemetría)
# ─────────────────────────────────────────
resource "aws_iam_role" "iot_rule_role" {
  name = "${var.project_name}-iot-rule-role"
  assume_role_policy = jsonencode({
    Version = "2012-10-17"
    Statement = [{
      Action    = "sts:AssumeRole"
      Effect    = "Allow"
      Principal = { Service = "iot.amazonaws.com" }
    }]
  })
}

resource "aws_iam_role_policy" "iot_rule_policy" {
  role = aws_iam_role.iot_rule_role.id
  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [{
      Effect   = "Allow"
      Action   = ["firehose:PutRecord", "firehose:PutRecordBatch"]
      Resource = aws_kinesis_firehose_delivery_stream.telemetry_stream.arn
    }]
  })
}

resource "aws_iot_topic_rule" "telemetry_to_firehose" {
  name        = replace("${var.project_name}_to_firehose", "-", "_")
  enabled     = true
  sql         = "SELECT *, topic() as mqtt_topic, timestamp() as ingest_time FROM 'moto/+/+'"
  sql_version = "2016-03-23"

  firehose {
    delivery_stream_name = aws_kinesis_firehose_delivery_stream.telemetry_stream.name
    role_arn             = aws_iam_role.iot_rule_role.arn
    separator            = "\n"
  }
}

# ─────────────────────────────────────────
# OUTPUTS útiles
# ─────────────────────────────────────────
output "iot_endpoint" {
  description = "AWS IoT endpoint — usarlo en la app Android"
  value       = "Ejecuta: aws iot describe-endpoint --endpoint-type iot:Data-ATS"
}

output "s3_bucket_name" {
  value = aws_s3_bucket.data_lake.bucket
}

output "firehose_stream_name" {
  value = aws_kinesis_firehose_delivery_stream.telemetry_stream.name
}
