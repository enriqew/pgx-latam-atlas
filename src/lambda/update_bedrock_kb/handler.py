"""UpdateBedrockKB Lambda — formats Gold artefacts as text documents and starts
a Bedrock Knowledge Base ingestion job, then polls until completion and reports
the result back to Step Functions via the task token.

Environment variables (set by Terraform):
    LAKE_BUCKET            S3 data-lake bucket; Gold artefacts live under gold/kb-docs/
    KNOWLEDGE_BASE_ID      Bedrock KB identifier (e.g. "ABCDEF1234")
    DATA_SOURCE_ID         Bedrock KB data source identifier
    ATHENA_WORKGROUP       Athena workgroup name
    ATHENA_RESULTS_PREFIX  S3 prefix for Athena query results (e.g. "athena-results")
    GOLD_DATABASE          Athena database for gold tables (e.g. "gold_pgx")
    SILVER_DATABASE        Athena database for silver tables (e.g. "silver_pgx")
    AWS_REGION_NAME        AWS region (e.g. "us-east-1")

Step Functions integration:
    Invoked via arn:aws:states:::lambda:invoke.waitForTaskToken.
    The event payload contains:
        task_token              — passed back to SFN on success/failure
        gold_artifacts_bucket   — override for LAKE_BUCKET (optional)
        knowledge_base_id       — override for KNOWLEDGE_BASE_ID (optional)

Document format (one S3 object per (gene, population, drug) triple):
    Gene: {gene}
    Population: {pop_code} ({country})
    Drug: {drug}
    Phenotype: {phenotype}
    Allele frequency: {freq}%
    Actionability: CPIC {level}
    Clinical implication: {implication}
"""

from __future__ import annotations

import logging
import os
import time
from typing import Any

import boto3

logger = logging.getLogger()
logger.setLevel(logging.INFO)

# ── Environment ───────────────────────────────────────────────────────────────

LAKE_BUCKET = os.environ["LAKE_BUCKET"]
KNOWLEDGE_BASE_ID = os.environ["KNOWLEDGE_BASE_ID"]
DATA_SOURCE_ID = os.environ["DATA_SOURCE_ID"]
ATHENA_WORKGROUP = os.environ["ATHENA_WORKGROUP"]
ATHENA_RESULTS_PREFIX = os.environ.get("ATHENA_RESULTS_PREFIX", "athena-results")
GOLD_DB = os.environ.get("GOLD_DATABASE", "gold_pgx")
SILVER_DB = os.environ.get("SILVER_DATABASE", "silver_pgx")

# S3 prefix where text documents are staged before KB ingestion
KB_DOCS_PREFIX = "gold/kb-docs"

# Polling constants for the ingestion job
_POLL_INTERVAL_SECONDS = 10
_MAX_POLL_ATTEMPTS = 180  # 30 minutes max

# ── Population → country display name mapping ─────────────────────────────────
# 1000 Genomes Phase 3 Latin American / admixed populations.
_POP_COUNTRY: dict[str, str] = {
    "ACB": "Barbados (African Caribbean)",
    "ASW": "USA (African American SW)",
    "CLM": "Colombia",
    "MXL": "Mexico (Los Angeles)",
    "PEL": "Peru",
    "PUR": "Puerto Rico",
    "CEU": "Europe (Utah Residents)",
    "GBR": "Great Britain",
    "FIN": "Finland",
    "IBS": "Spain (Iberian)",
    "TSI": "Italy (Tuscan)",
    "CHB": "China (Han Beijing)",
    "JPT": "Japan (Tokyo)",
    "CHS": "China (Southern Han)",
    "CDX": "China (Dai Xishuangbanna)",
    "KHV": "Vietnam (Kinh Ho Chi Minh)",
    "GIH": "India (Gujarati)",
    "PJL": "Pakistan (Punjabi Lahore)",
    "BEB": "Bangladesh",
    "STU": "Sri Lanka (Tamil UK)",
    "ITU": "India (Telugu UK)",
    "LWK": "Kenya (Luhya Webuye)",
    "MSL": "Sierra Leone (Mende)",
    "GWD": "Gambia (Mandinka)",
    "YRI": "Nigeria (Yoruba Ibadan)",
    "ESN": "Nigeria (Esan)",
}

# ── Athena helpers ─────────────────────────────────────────────────────────────

_ATHENA_POLL_INTERVAL = 2
_ATHENA_MAX_ATTEMPTS = 150  # 5 minutes


def _run_athena_query(client: Any, sql: str) -> list[dict[str, Any]]:
    """Run a synchronous Athena query and return rows as a list of dicts."""
    output_location = f"s3://{LAKE_BUCKET}/{ATHENA_RESULTS_PREFIX}/update-bedrock-kb/"
    response = client.start_query_execution(
        QueryString=sql,
        WorkGroup=ATHENA_WORKGROUP,
        ResultConfiguration={"OutputLocation": output_location},
    )
    execution_id: str = response["QueryExecutionId"]
    logger.info("Athena query started: %s", execution_id)

    for _ in range(_ATHENA_MAX_ATTEMPTS):
        time.sleep(_ATHENA_POLL_INTERVAL)
        status_response = client.get_query_execution(QueryExecutionId=execution_id)
        state = status_response["QueryExecution"]["QueryExecutionStatus"]["State"]
        if state == "SUCCEEDED":
            break
        if state in ("FAILED", "CANCELLED"):
            reason = status_response["QueryExecution"]["QueryExecutionStatus"].get(
                "StateChangeReason", "unknown"
            )
            raise RuntimeError(
                f"Athena query {execution_id} {state}: {reason}\nSQL: {sql[:300]}"
            )
    else:
        timeout_s = _ATHENA_MAX_ATTEMPTS * _ATHENA_POLL_INTERVAL
        raise RuntimeError(f"Athena query {execution_id} timed out after {timeout_s}s")

    rows: list[dict[str, Any]] = []
    paginator = client.get_paginator("get_query_results")
    pages = paginator.paginate(QueryExecutionId=execution_id)
    headers: list[str] = []
    for page in pages:
        result_rows = page["ResultSet"]["Rows"]
        if not headers:
            headers = [col["VarCharValue"] for col in result_rows[0]["Data"]]
            result_rows = result_rows[1:]
        for row in result_rows:
            values = [cell.get("VarCharValue", "") for cell in row["Data"]]
            rows.append(dict(zip(headers, values, strict=False)))

    logger.info("Athena query %s: %d rows returned", execution_id, len(rows))
    return rows


# ── SQL queries ───────────────────────────────────────────────────────────────

_RANKING_SQL = f"""
SELECT
    rank_position,
    drug_name,
    gene_symbol,
    population_code,
    delta_vs_baseline,
    population_affected_pct,
    classification_strength,
    clinical_implication,
    snapshot_date
FROM {GOLD_DB}.actionability_ranking
ORDER BY rank_position
"""

_PHENO_SQL = f"""
SELECT
    gene_symbol,
    population_code,
    phenotype_category,
    phenotype_percentage,
    snapshot_date
FROM {GOLD_DB}.phenotype_distribution_by_population
ORDER BY gene_symbol, population_code, phenotype_category
"""

_AF_SQL = f"""
SELECT
    gene_symbol,
    population_code,
    variant_id,
    allele_frequency,
    snapshot_date
FROM {GOLD_DB}.allele_frequencies_by_population
ORDER BY gene_symbol, population_code, variant_id
"""


# ── Document formatting ───────────────────────────────────────────────────────


def _format_document(
    gene: str,
    pop_code: str,
    drug: str,
    phenotype: str,
    freq_pct: str,
    cpic_level: str,
    implication: str,
) -> str:
    """Render a single PGx knowledge document as structured plain text."""
    country = _POP_COUNTRY.get(pop_code, pop_code)
    return (
        f"Gene: {gene}\n"
        f"Population: {pop_code} ({country})\n"
        f"Drug: {drug}\n"
        f"Phenotype: {phenotype}\n"
        f"Allele frequency: {freq_pct}%\n"
        f"Actionability: CPIC {cpic_level}\n"
        f"Clinical implication: {implication}\n"
    )


def _build_documents(
    ranking_rows: list[dict[str, Any]],
    pheno_rows: list[dict[str, Any]],
    af_rows: list[dict[str, Any]],
) -> dict[str, str]:
    """Return a mapping of S3 key → document text for every (gene, pop, drug) triple."""

    # Build lookup: (gene, pop) → dominant phenotype category
    pheno_lookup: dict[tuple[str, str], str] = {}
    for r in pheno_rows:
        key = (r["gene_symbol"], r["population_code"])
        existing = pheno_lookup.get(key)
        # Keep the phenotype with the highest percentage
        if existing is None:
            pheno_lookup[key] = r["phenotype_category"]
        else:
            # Compare percentages by scanning rows again (simple: last-write wins for max)
            pass
    # Redo with explicit max tracking
    pheno_pct: dict[tuple[str, str], tuple[str, float]] = {}
    for r in pheno_rows:
        key = (r["gene_symbol"], r["population_code"])
        pct = float(r["phenotype_percentage"]) if r.get("phenotype_percentage") else 0.0
        if key not in pheno_pct or pct > pheno_pct[key][1]:
            pheno_pct[key] = (r["phenotype_category"], pct)
    pheno_lookup = {k: v[0] for k, v in pheno_pct.items()}

    # Build lookup: (gene, pop) → mean allele frequency across variants
    af_sum: dict[tuple[str, str], list[float]] = {}
    for r in af_rows:
        key = (r["gene_symbol"], r["population_code"])
        freq = float(r["allele_frequency"]) if r.get("allele_frequency") else 0.0
        af_sum.setdefault(key, []).append(freq)
    af_lookup: dict[tuple[str, str], float] = {
        k: sum(v) / len(v) for k, v in af_sum.items() if v
    }

    documents: dict[str, str] = {}
    for r in ranking_rows:
        gene = r.get("gene_symbol", "")
        pop = r.get("population_code", "")
        drug = r.get("drug_name", "")
        if not gene or not pop or not drug:
            continue

        phenotype = pheno_lookup.get((gene, pop), "Unknown")
        mean_freq = af_lookup.get((gene, pop), 0.0)
        freq_pct = f"{mean_freq * 100:.1f}"
        cpic_level = r.get("classification_strength", "Unknown")
        implication = r.get("clinical_implication", "")

        doc_text = _format_document(gene, pop, drug, phenotype, freq_pct, cpic_level, implication)

        # One file per (gene, pop, drug); sanitise to valid S3 key characters
        safe_drug = drug.replace(" ", "_").replace("/", "-")
        s3_key = f"{KB_DOCS_PREFIX}/{gene}/{pop}/{safe_drug}.txt"
        documents[s3_key] = doc_text

    return documents


# ── S3 upload ─────────────────────────────────────────────────────────────────


def _upload_documents(s3_client: Any, bucket: str, documents: dict[str, str]) -> int:
    """Upload text documents to S3; return count of objects written."""
    uploaded = 0
    for key, text in documents.items():
        s3_client.put_object(
            Bucket=bucket,
            Key=key,
            Body=text.encode("utf-8"),
            ContentType="text/plain",
        )
        uploaded += 1
    logger.info("Uploaded %d KB documents to s3://%s/%s/", uploaded, bucket, KB_DOCS_PREFIX)
    return uploaded


# ── Bedrock KB ingestion ───────────────────────────────────────────────────────


def _start_ingestion(
    bedrock_agent_client: Any,
    knowledge_base_id: str,
    data_source_id: str,
) -> str:
    """Start a Bedrock KB ingestion job and return the job ID."""
    response = bedrock_agent_client.start_ingestion_job(
        knowledgeBaseId=knowledge_base_id,
        dataSourceId=data_source_id,
        description="pgx-latam-atlas pipeline sync",
    )
    job_id: str = response["ingestionJob"]["ingestionJobId"]
    logger.info(
        "Bedrock KB ingestion job started: %s (KB=%s, DS=%s)",
        job_id,
        knowledge_base_id,
        data_source_id,
    )
    return job_id


def _poll_ingestion(
    bedrock_agent_client: Any,
    knowledge_base_id: str,
    data_source_id: str,
    job_id: str,
) -> dict[str, Any]:
    """Poll until the ingestion job reaches a terminal state; return final stats."""
    for attempt in range(_MAX_POLL_ATTEMPTS):
        time.sleep(_POLL_INTERVAL_SECONDS)
        response = bedrock_agent_client.get_ingestion_job(
            knowledgeBaseId=knowledge_base_id,
            dataSourceId=data_source_id,
            ingestionJobId=job_id,
        )
        job = response["ingestionJob"]
        status = job["status"]
        logger.info(
            "Ingestion job %s: status=%s (attempt %d/%d)",
            job_id,
            status,
            attempt + 1,
            _MAX_POLL_ATTEMPTS,
        )
        if status == "COMPLETE":
            stats = job.get("statistics", {})
            logger.info("Ingestion complete — stats: %s", stats)
            return {
                "status": "COMPLETE",
                "ingestion_job_id": job_id,
                "statistics": stats,
            }
        if status in ("FAILED", "STOPPED"):
            failure_reasons = job.get("failureReasons", [])
            raise RuntimeError(
                f"Bedrock KB ingestion job {job_id} {status}: {failure_reasons}"
            )

    timeout_s = _MAX_POLL_ATTEMPTS * _POLL_INTERVAL_SECONDS
    raise RuntimeError(
        f"Bedrock KB ingestion job {job_id} did not complete within {timeout_s}s"
    )


# ── Handler ───────────────────────────────────────────────────────────────────


def handler(event: dict[str, Any], context: Any) -> dict[str, Any]:
    """Entry point invoked by Step Functions (waitForTaskToken pattern).

    The function:
    1. Queries Gold tables to build structured text documents.
    2. Uploads documents to S3 under gold/kb-docs/.
    3. Starts a Bedrock KB ingestion job (S3 → KB).
    4. Polls until the job completes.
    5. Reports success/failure back to Step Functions via the task token.
    """
    task_token: str = event["task_token"]
    bucket = event.get("gold_artifacts_bucket") or LAKE_BUCKET
    kb_id = event.get("knowledge_base_id") or KNOWLEDGE_BASE_ID

    sfn_client = boto3.client("stepfunctions")

    try:
        logger.info(
            "UpdateBedrockKB started — requestId=%s KB=%s bucket=%s",
            context.aws_request_id,
            kb_id,
            bucket,
        )

        athena = boto3.client("athena")
        s3 = boto3.client("s3")
        bedrock_agent = boto3.client("bedrock-agent")

        # 1. Query Gold tables
        logger.info("Querying actionability_ranking")
        ranking_rows = _run_athena_query(athena, _RANKING_SQL)

        logger.info("Querying phenotype_distribution_by_population")
        pheno_rows = _run_athena_query(athena, _PHENO_SQL)

        logger.info("Querying allele_frequencies_by_population")
        af_rows = _run_athena_query(athena, _AF_SQL)

        # 2. Build and upload documents
        documents = _build_documents(ranking_rows, pheno_rows, af_rows)
        uploaded = _upload_documents(s3, bucket, documents)

        # 3. Start Bedrock ingestion
        job_id = _start_ingestion(bedrock_agent, kb_id, DATA_SOURCE_ID)

        # 4. Poll to completion
        result = _poll_ingestion(bedrock_agent, kb_id, DATA_SOURCE_ID, job_id)
        result["documents_uploaded"] = uploaded
        result["knowledge_base_id"] = kb_id

        # 5. Report success back to Step Functions
        import json

        sfn_client.send_task_success(taskToken=task_token, output=json.dumps(result))
        logger.info("UpdateBedrockKB complete — sent task success")
        return result

    except Exception as exc:
        logger.exception("UpdateBedrockKB failed: %s", exc)
        sfn_client.send_task_failure(
            taskToken=task_token,
            error="BedrockKBSyncError",
            cause=str(exc)[:256],
        )
        raise
