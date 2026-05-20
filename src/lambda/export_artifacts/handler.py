"""ExportArtifacts Lambda — queries Athena gold tables, commits JSON to GitHub.

Environment variables (set by Terraform):
    LAKE_BUCKET            S3 bucket containing gold tables and Athena results
    ATHENA_WORKGROUP       Athena workgroup name
    ATHENA_RESULTS_PREFIX  S3 key prefix for Athena query output (e.g. "athena-results")
    GOLD_DATABASE          Athena database for gold tables (e.g. "gold_pgx")
    SILVER_DATABASE        Athena database for silver tables (e.g. "silver_pgx")
    GITHUB_REPO            owner/repo for artifact commits (e.g. "enriqew/pgx-latam-atlas")

Secrets Manager (IAM policy grants read):
    pgx-latam/github-pat   {"token": "<PAT>"} — contents:write scope on GITHUB_REPO

Artifact delivery:
    allele_frequencies.json        — key pharmacogene variant positions only (< 200 KB)
    phenotype_distribution.json    — all 58 rows
    drug_impact_summary.json       — all 481 rows
    actionability_ranking.json     — top 50 rows
    metadata.json                  — pipeline run metadata
"""

from __future__ import annotations

import base64
import json
import logging
import os
import time
from typing import Any

import boto3
import requests

logger = logging.getLogger()
logger.setLevel(logging.INFO)

# ── Environment ───────────────────────────────────────────────────────────────

LAKE_BUCKET = os.environ["LAKE_BUCKET"]
ATHENA_WORKGROUP = os.environ["ATHENA_WORKGROUP"]
ATHENA_RESULTS_PREFIX = os.environ.get("ATHENA_RESULTS_PREFIX", "athena-results")
GOLD_DB = os.environ.get("GOLD_DATABASE", "gold_pgx")
SILVER_DB = os.environ.get("SILVER_DATABASE", "silver_pgx")
GITHUB_REPO = os.environ.get("GITHUB_REPO", "enriqew/pgx-latam-atlas")
GITHUB_PAT_SECRET = "pgx-latam/github-pat"
GITHUB_API_BASE = "https://api.github.com"

# ── Key pharmacogenomic variant positions (GRCh37, positional format) ────────
# Subset committed to GitHub — the full 182k-row table lives in S3.
# Positions confirmed present in the 1000G Phase 3 bronze layer.

_KEY_POSITIONS = (
    "chr10:96521657",
    "chr10:96540410",  # CYP2C19 *2 (rs4244285), *3 (rs4986893)
    "chr10:96741053",  # CYP2C9 *2 (rs1799853)
    "chr12:21331546",  # SLCO1B1 *5 (rs4149056)
    "chr16:31093954",  # VKORC1 -1639G>A proxy (rs9923231 LD; GRCh37 positional ID)
    "chr7:99251073",   # CYP3A5 *3 proxy (rs776746 LD; GRCh37 positional ID)
    "chr2:234578428",  # UGT1A9 *3 (rs17868320, c.98T>C; ALT=T non-functional)
    "chr6:18131419",   # TPMT *3B (rs1800460)
    "chr1:97981343",
    "chr1:97915614",
    "chr1:97981395",  # DPYD *2A, HapB3, *13
    "chrX:153763492",
    "chrX:153764217",  # G6PD Ser188Phe, Glu202Lys
)

_KEY_POSITIONS_SQL = ", ".join(f"'{p}'" for p in _KEY_POSITIONS)

# ── Athena helpers ────────────────────────────────────────────────────────────

_POLL_INTERVAL_SECONDS = 2
_MAX_POLL_ATTEMPTS = 150  # 5 minutes


def _run_athena_query(client: Any, sql: str) -> list[dict[str, Any]]:
    """Execute a synchronous Athena query and return rows as a list of dicts."""
    output_location = f"s3://{LAKE_BUCKET}/{ATHENA_RESULTS_PREFIX}/export-artifacts/"
    response = client.start_query_execution(
        QueryString=sql,
        WorkGroup=ATHENA_WORKGROUP,
        ResultConfiguration={"OutputLocation": output_location},
    )
    execution_id: str = response["QueryExecutionId"]
    logger.info("Athena query started: %s", execution_id)

    for _ in range(_MAX_POLL_ATTEMPTS):
        time.sleep(_POLL_INTERVAL_SECONDS)
        status_response = client.get_query_execution(QueryExecutionId=execution_id)
        state = status_response["QueryExecution"]["QueryExecutionStatus"]["State"]
        if state == "SUCCEEDED":
            break
        if state in ("FAILED", "CANCELLED"):
            reason = status_response["QueryExecution"]["QueryExecutionStatus"].get(
                "StateChangeReason", "unknown"
            )
            raise RuntimeError(f"Athena query {execution_id} {state}: {reason}\nSQL: {sql[:300]}")
    else:
        timeout_s = _MAX_POLL_ATTEMPTS * _POLL_INTERVAL_SECONDS
        raise RuntimeError(f"Athena query {execution_id} timed out after {timeout_s}s")

    rows: list[dict[str, Any]] = []
    paginator = client.get_paginator("get_query_results")
    pages = paginator.paginate(QueryExecutionId=execution_id)

    headers: list[str] = []
    for page in pages:
        result_rows = page["ResultSet"]["Rows"]
        if not headers:
            headers = [col["VarCharValue"] for col in result_rows[0]["Data"]]
            result_rows = result_rows[1:]  # skip header row
        for row in result_rows:
            values = [cell.get("VarCharValue", "") for cell in row["Data"]]
            rows.append(dict(zip(headers, values, strict=False)))

    logger.info("Athena query %s: %d rows returned", execution_id, len(rows))
    return rows


def _cast_row(
    row: dict[str, Any],
    int_cols: tuple[str, ...],
    float_cols: tuple[str, ...],
    bool_cols: tuple[str, ...],
) -> dict[str, Any]:
    """Cast Athena string values to their proper Python types."""
    result: dict[str, Any] = {}
    for k, v in row.items():
        if k in int_cols:
            result[k] = int(v) if v else None
        elif k in float_cols:
            result[k] = round(float(v), 6) if v else None
        elif k in bool_cols:
            result[k] = v.lower() == "true" if v else False
        else:
            result[k] = v if v else None
    return result


# ── Query definitions ─────────────────────────────────────────────────────────

_AF_SQL = f"""
SELECT
    variant_id, gene_symbol, chromosome, position, population_code, superpopulation,
    allele_count, total_alleles, allele_frequency,
    ci_lower_wilson, ci_upper_wilson, delta_vs_ceu, is_actionable, snapshot_date
FROM {GOLD_DB}.allele_frequencies_by_population
WHERE variant_id IN ({_KEY_POSITIONS_SQL})
ORDER BY gene_symbol, population_code, variant_id
"""

_PHENO_SQL = f"""
SELECT
    gene_symbol, population_code, superpopulation, phenotype_category,
    individual_count, population_total, phenotype_percentage,
    ci_lower_wilson, ci_upper_wilson, snapshot_date
FROM {GOLD_DB}.phenotype_distribution_by_population
ORDER BY gene_symbol, population_code, phenotype_category
"""

_IMPACT_SQL = f"""
SELECT
    drug_name, gene_symbol, population_code, population_total,
    individuals_requiring_change, percentage_requiring_change,
    baseline_ceu_percentage, delta_vs_baseline, classification_strength, snapshot_date
FROM {GOLD_DB}.drug_impact_summary
ORDER BY drug_name, gene_symbol, population_code
"""

_RANKING_SQL = f"""
SELECT
    rank_position, drug_name, gene_symbol, population_code,
    delta_vs_baseline, population_affected_pct, classification_strength,
    clinical_implication, snapshot_date
FROM {GOLD_DB}.actionability_ranking
ORDER BY rank_position
"""

_POPULATIONS_SQL = f"""
SELECT population_code, population_name, superpopulation, region, sample_size
FROM {SILVER_DB}.populations
ORDER BY population_code
"""


def _cast_af_rows(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return [
        _cast_row(
            r,
            ("position", "allele_count", "total_alleles"),
            ("allele_frequency", "ci_lower_wilson", "ci_upper_wilson", "delta_vs_ceu"),
            ("is_actionable",),
        )
        for r in rows
    ]


def _cast_pheno_rows(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return [
        _cast_row(
            r,
            ("individual_count", "population_total"),
            ("phenotype_percentage", "ci_lower_wilson", "ci_upper_wilson"),
            (),
        )
        for r in rows
    ]


def _cast_impact_rows(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return [
        _cast_row(
            r,
            ("population_total", "individuals_requiring_change"),
            ("percentage_requiring_change", "baseline_ceu_percentage", "delta_vs_baseline"),
            (),
        )
        for r in rows
    ]


def _cast_ranking_rows(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return [
        _cast_row(r, ("rank_position",), ("delta_vs_baseline", "population_affected_pct"), ())
        for r in rows
    ]


def _cast_pop_rows(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return [_cast_row(r, ("sample_size",), (), ()) for r in rows]


# ── GitHub helpers ─────────────────────────────────────────────────────────────


def _get_github_pat() -> str:
    sm = boto3.client("secretsmanager")
    secret = sm.get_secret_value(SecretId=GITHUB_PAT_SECRET)
    raw = secret["SecretString"]
    try:
        return json.loads(raw)["token"]
    except (json.JSONDecodeError, KeyError):
        return raw.strip()


def _commit_artifact(pat: str, path: str, content_bytes: bytes, run_date: str) -> None:
    """Create or update a file in the GitHub repo via the Contents API."""
    headers = {
        "Authorization": f"Bearer {pat}",
        "Accept": "application/vnd.github.v3+json",
        "X-GitHub-Api-Version": "2022-11-28",
    }
    url = f"{GITHUB_API_BASE}/repos/{GITHUB_REPO}/contents/{path}"

    existing_sha: str | None = None
    get_resp = requests.get(url, headers=headers, timeout=30)
    if get_resp.status_code == 200:
        existing_sha = get_resp.json()["sha"]
    elif get_resp.status_code != 404:
        raise RuntimeError(f"GitHub GET {path} → {get_resp.status_code}: {get_resp.text[:300]}")

    body: dict[str, Any] = {
        "message": f"chore: update {path.split('/')[-1]} — pipeline run {run_date}",
        "committer": {"name": "pgx-latam pipeline", "email": "pipeline@pgx-latam-atlas"},
        "content": base64.b64encode(content_bytes).decode(),
    }
    if existing_sha:
        body["sha"] = existing_sha

    put_resp = requests.put(url, headers=headers, json=body, timeout=60)
    if put_resp.status_code not in (200, 201):
        raise RuntimeError(f"GitHub PUT {path} → {put_resp.status_code}: {put_resp.text[:300]}")

    action = "updated" if existing_sha else "created"
    logger.info("GitHub %s: %s (%d bytes)", action, path, len(content_bytes))


# ── Handler ───────────────────────────────────────────────────────────────────


def handler(event: dict[str, Any], context: Any) -> dict[str, Any]:
    logger.info("ExportArtifacts started — requestId=%s", context.aws_request_id)

    athena = boto3.client("athena")

    logger.info("Querying allele_frequencies (key variants only)")
    af_rows = _cast_af_rows(_run_athena_query(athena, _AF_SQL))

    logger.info("Querying phenotype_distribution")
    pheno_rows = _cast_pheno_rows(_run_athena_query(athena, _PHENO_SQL))

    logger.info("Querying drug_impact_summary")
    impact_rows = _cast_impact_rows(_run_athena_query(athena, _IMPACT_SQL))

    logger.info("Querying actionability_ranking")
    ranking_rows = _cast_ranking_rows(_run_athena_query(athena, _RANKING_SQL))

    logger.info("Querying populations")
    pop_rows = _cast_pop_rows(_run_athena_query(athena, _POPULATIONS_SQL))

    snapshot_date = pheno_rows[0]["snapshot_date"] if pheno_rows else ""
    pop_sizes = {r["population_code"]: r["sample_size"] for r in pop_rows if r["population_code"]}

    metadata = {
        "schema_version": "1.0.0",
        "snapshot_date": snapshot_date,
        "source_versions": {
            "thousand_genomes": "Phase 3 release/20130502",
            "pharmgkb": f"downloaded {snapshot_date}",
            "cpic": "PostgREST API v2026",
        },
        "populations": pop_sizes,
        "total_variants_analyzed": None,
        "pipeline_run_id": context.aws_request_id,
    }

    artifacts: dict[str, Any] = {
        "artifacts/allele_frequencies.json": af_rows,
        "artifacts/phenotype_distribution.json": pheno_rows,
        "artifacts/drug_impact_summary.json": impact_rows,
        "artifacts/actionability_ranking.json": ranking_rows,
        "artifacts/metadata.json": metadata,
    }

    pat = _get_github_pat()
    run_date = snapshot_date or "unknown"

    for path, payload in artifacts.items():
        content_bytes = json.dumps(payload, separators=(",", ":")).encode()
        _commit_artifact(pat, path, content_bytes, run_date)

    committed = list(artifacts.keys())
    logger.info("ExportArtifacts complete — %d files committed to %s", len(committed), GITHUB_REPO)
    return {"status": "success", "artifacts_committed": committed, "repo": GITHUB_REPO}
