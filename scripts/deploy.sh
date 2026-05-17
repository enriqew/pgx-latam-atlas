#!/usr/bin/env bash
# Deploy Terraform infrastructure and upload Glue scripts to S3.
# Usage: bash scripts/deploy.sh [--env dev|staging|prod]
set -euo pipefail

ENV="${1:-dev}"
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "${SCRIPT_DIR}/.." && pwd)"

echo "[deploy] Environment: ${ENV}"
echo "[deploy] Uploading Glue scripts..."

LAKE_BUCKET=$(cd "${REPO_ROOT}/infra/terraform" && terraform output -raw lake_bucket_name)

aws s3 cp "${REPO_ROOT}/src/glue_jobs/ingest_genomes_bronze.py" \
    "s3://${LAKE_BUCKET}-glue-scripts/jobs/ingest_genomes_bronze.py"

aws s3 cp "${REPO_ROOT}/src/glue_jobs/build_silver_variants.py" \
    "s3://${LAKE_BUCKET}-glue-scripts/jobs/build_silver_variants.py"

echo "[deploy] Done."
