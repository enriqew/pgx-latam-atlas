#!/usr/bin/env bash
# Full local pipeline run (Phases 1-3): ingest → silver → gold → artifacts/.
# No AWS required. Data written to data/ (gitignored).
# Usage: bash scripts/run_local_dry_run.sh
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "${SCRIPT_DIR}/.." && pwd)"

echo "[dry-run] Starting local pipeline..."

echo "[dry-run] Phase 1: ingestion"
python -m pgx_latam.ingestion.pharmgkb
python -m pgx_latam.ingestion.cpic
python -m pgx_latam.ingestion.thousand_genomes

echo "[dry-run] Phase 2: silver transformations"
python -m pgx_latam.transformations.silver_variants
python -m pgx_latam.transformations.silver_clinical

echo "[dry-run] Phase 3: gold aggregates + export"
python -m pgx_latam.transformations.gold_aggregates
python -m pgx_latam.exports.portfolio_artifacts

echo "[dry-run] Pipeline complete. Artifacts written to ${REPO_ROOT}/artifacts/"
ls -lh "${REPO_ROOT}/artifacts/"*.json
