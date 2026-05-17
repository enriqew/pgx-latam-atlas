#!/usr/bin/env bash
# Trigger a pipeline run and pull the resulting artifacts/ from the main branch.
# Assumes Step Functions pipeline has already been deployed (Phase 4+).
# Usage: bash scripts/refresh_artifacts.sh
set -euo pipefail

STATE_MACHINE_ARN=$(cd infra/terraform && terraform output -raw pipeline_state_machine_arn)

echo "[refresh] Starting Step Functions execution..."
EXECUTION_ARN=$(aws stepfunctions start-execution \
    --state-machine-arn "${STATE_MACHINE_ARN}" \
    --query 'executionArn' --output text)

echo "[refresh] Execution ARN: ${EXECUTION_ARN}"
echo "[refresh] Waiting for completion (this may take 20-40 minutes)..."

aws stepfunctions wait execution-complete \
    --execution-arn "${EXECUTION_ARN}" 2>/dev/null || true

STATUS=$(aws stepfunctions describe-execution \
    --execution-arn "${EXECUTION_ARN}" \
    --query 'status' --output text)

echo "[refresh] Final status: ${STATUS}"

if [ "${STATUS}" != "SUCCEEDED" ]; then
    echo "[refresh] ERROR: Pipeline did not succeed. Check Step Functions console."
    exit 1
fi

echo "[refresh] Pipeline succeeded. Pull latest artifacts with:"
echo "  git pull origin main"
