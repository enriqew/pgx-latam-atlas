"""Download CPIC guidelines and write Parquet to data/bronze/cpic_guidelines_raw/.

Source:  https://cpicpgx.org/guidelines/  —  API: https://api.cpicpgx.org/v1/
License: CC BY 4.0  (https://creativecommons.org/licenses/by/4.0/)
Cite:    Relling MV, Klein TE. Clin Pharmacol Ther 2011. PMID 21270786

The CPIC API is a PostgREST endpoint. We fetch recommendations (the atomic unit of
clinical guidance) and join them with guideline metadata and drug names to produce
one row per (recommendation, gene_symbol, drug_name) combination.
"""

from __future__ import annotations

import logging
from datetime import date, datetime
from typing import Any

import pandas as pd
import requests
from tenacity import (
    retry,
    retry_if_exception_type,
    stop_after_attempt,
    wait_exponential,
)

from pgx_latam.config import Settings, get_settings
from pgx_latam.utils.parquet_io import write_bronze_partition

logger = logging.getLogger(__name__)

_CPIC_API = "https://api.cpicpgx.org/v1"
_REQUEST_TIMEOUT = 30
_PAGE_LIMIT = 500


@retry(
    retry=retry_if_exception_type(requests.RequestException),
    wait=wait_exponential(multiplier=2, min=4, max=60),
    stop=stop_after_attempt(4),
    reraise=True,
)
def _get_json(url: str, params: dict[str, Any] | None = None) -> list[dict[str, Any]]:
    response = requests.get(url, params=params, timeout=_REQUEST_TIMEOUT)
    if response.status_code not in (200, 206):
        raise RuntimeError(
            f"CPIC API request failed: GET {url} → HTTP {response.status_code}. "
            "Check https://cpicpgx.org for service status."
        )
    return response.json()  # type: ignore[no-any-return]


def _fetch_all_pages(endpoint: str, select: str | None = None) -> list[dict[str, Any]]:
    url = f"{_CPIC_API}/{endpoint}"
    params: dict[str, Any] = {"limit": _PAGE_LIMIT, "offset": 0}
    if select:
        params["select"] = select

    results: list[dict[str, Any]] = []
    while True:
        page = _get_json(url, params)
        if not page:
            break
        results.extend(page)
        logger.debug("Fetched %d/%d records from %s", len(results), "?", endpoint)
        if len(page) < _PAGE_LIMIT:
            break
        params["offset"] += _PAGE_LIMIT

    logger.info("Fetched %d total records from /%s", len(results), endpoint)
    return results


def _fetch_guidelines() -> dict[str, dict[str, Any]]:
    # "drugs" was removed from guideline in CPIC API v2026 — drug is now on recommendation
    raw = _fetch_all_pages("guideline", select="id,name,genes,url,version")
    return {g["id"]: g for g in raw}


def _fetch_drugs() -> dict[str, str]:
    """Return mapping of drugid → drug name."""
    raw = _fetch_all_pages("drug", select="drugid,name")
    return {d["drugid"]: d["name"] for d in raw if d.get("drugid") and d.get("name")}


def _fetch_recommendations() -> list[dict[str, Any]]:
    # "drugid" added to recommendation in CPIC API v2026
    return _fetch_all_pages(
        "recommendation",
        select="id,guidelineid,drugid,drugrecommendation,classification,phenotypes,activityscore,comments",
    )


def _flatten_recommendations(
    recommendations: list[dict[str, Any]],
    guidelines: dict[str, dict[str, Any]],
    drug_names: dict[str, str],
) -> list[dict[str, Any]]:
    """Explode recommendations into (recommendation, gene_symbol, drug_name) rows."""
    rows: list[dict[str, Any]] = []
    missing_guideline_ids: set[str] = set()

    for rec in recommendations:
        guideline_id = rec.get("guidelineid") or ""
        guideline = guidelines.get(guideline_id)
        if guideline is None:
            missing_guideline_ids.add(guideline_id)
            continue

        guideline_genes: list[str] = guideline.get("genes") or []

        # Drug is now on the recommendation directly (CPIC API v2026).
        # Fall back to empty string so the row is still emitted without a drug name.
        drug_id: str = rec.get("drugid") or ""
        drug_name: str = drug_names.get(drug_id, drug_id)

        phenotypes: dict[str, str] = rec.get("phenotypes") or {}
        activity_scores: dict[str, str] = rec.get("activityscore") or {}
        recommendation_text: str = rec.get("drugrecommendation") or ""
        classification: str = rec.get("classification") or ""
        version: str = str(guideline.get("version") or "")
        rec_id: str = str(rec.get("id") or "")

        genes_to_emit = guideline_genes if guideline_genes else list(phenotypes.keys())

        for gene_symbol in genes_to_emit:
            phenotype = phenotypes.get(gene_symbol) or phenotypes.get(
                gene_symbol.upper(), ""
            )
            activity_score = str(
                activity_scores.get(gene_symbol)
                or activity_scores.get(gene_symbol.upper(), "")
            )
            rows.append(
                {
                    "guideline_id": f"{guideline_id}:{rec_id}",
                    "gene_symbol": gene_symbol,
                    "drug_name": drug_name,
                    "phenotype": phenotype,
                    "activity_score": activity_score,
                    "recommendation_text": recommendation_text,
                    "classification_strength": classification,
                    "cpic_release_version": version,
                }
            )

    if missing_guideline_ids:
        logger.warning(
            "Could not find guideline metadata for %d guideline IDs: %s",
            len(missing_guideline_ids),
            sorted(missing_guideline_ids)[:10],
        )

    return rows


def run(ingest_date: date | None = None, settings: Settings | None = None) -> str:
    """Fetch all CPIC recommendations and write to bronze Parquet.

    Args:
        ingest_date: Partition date. Defaults to today.
        settings: Application settings. Defaults to ``get_settings()``.

    Returns:
        Table name written.
    """
    effective_date = ingest_date or datetime.utcnow().date()
    cfg = settings or get_settings()

    logger.info("Fetching CPIC guidelines, drugs, and recommendations...")
    guidelines = _fetch_guidelines()
    drug_names = _fetch_drugs()
    recommendations = _fetch_recommendations()

    if not recommendations:
        raise RuntimeError(
            "CPIC API returned zero recommendations. "
            "Source may be unavailable or API contract has changed. "
            "Check https://api.cpicpgx.org/v1/recommendation manually."
        )

    rows = _flatten_recommendations(recommendations, guidelines, drug_names)
    if not rows:
        raise RuntimeError(
            f"Flattening produced zero rows from {len(recommendations)} recommendations. "
            "Guideline metadata join may have failed — check CPIC API response structure."
        )

    df = pd.DataFrame(rows)
    table_name = "cpic_guidelines_raw"
    table_root = cfg.bronze_root / table_name
    write_bronze_partition(df, table_root, effective_date)

    logger.info(
        "Wrote %s: %d rows → %s",
        table_name,
        len(df),
        table_root / f"ingest_date={effective_date.isoformat()}",
    )
    return table_name


def main() -> None:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s — %(message)s",
    )
    table = run()
    print(f"  ✓ {table}")


if __name__ == "__main__":
    main()
