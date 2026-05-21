"""Export gold layer tables to artifacts/ as JSON for portfolio consumption.

Reads:
  data/gold/allele_frequencies_by_population/
  data/gold/phenotype_distribution_by_population/
  data/gold/drug_impact_summary/
  data/gold/actionability_ranking/
  data/silver/populations/

Writes:
  artifacts/allele_frequencies.json
  artifacts/phenotype_distribution.json
  artifacts/drug_impact_summary.json
  artifacts/actionability_ranking.json
  artifacts/metadata.json
"""

from __future__ import annotations

import json
import logging
import uuid
from datetime import date, datetime
from pathlib import Path
from typing import Any

import pandas as pd

from pgx_latam.config import Settings, get_settings
from pgx_latam.utils.parquet_io import read_silver_table

logger = logging.getLogger(__name__)

_SCHEMA_VERSION = "1.0.0"


# ── JSON serialization ────────────────────────────────────────────────────────


def _coerce_value(v: Any) -> Any:
    """Convert numpy/pandas scalars to JSON-serializable Python types."""
    if pd.isna(v) if not isinstance(v, (list, dict)) else False:
        return None
    if isinstance(v, (date, datetime)):
        return v.isoformat()
    if hasattr(v, "item"):
        return v.item()
    return v


def _df_to_records(df: pd.DataFrame) -> list[dict[str, Any]]:
    """Convert DataFrame to list of dicts with JSON-safe values."""
    return [
        {str(k): _coerce_value(v) for k, v in row.items()} for row in df.to_dict(orient="records")
    ]


def _write_artifact(data: Any, path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as fh:
        json.dump(data, fh, indent=2, ensure_ascii=False)
    logger.info("Wrote %s (%d bytes)", path.name, path.stat().st_size)


# ── Per-artifact exporters ────────────────────────────────────────────────────


def export_allele_frequencies(
    gold_root: Path,
    artifacts_root: Path,
) -> int:
    """Export gold allele frequencies to JSON. Returns row count."""
    df = read_silver_table(gold_root / "allele_frequencies_by_population")
    if df.empty:
        logger.warning("allele_frequencies_by_population is empty — writing empty artifact")
        _write_artifact([], artifacts_root / "allele_frequencies.json")
        return 0

    columns = [
        "variant_id",
        "gene_symbol",
        "chromosome",
        "position",
        "reference_allele",
        "alternate_allele",
        "population_code",
        "superpopulation",
        "allele_count",
        "total_alleles",
        "allele_frequency",
        "ci_lower_wilson",
        "ci_upper_wilson",
        "delta_vs_ceu",
        "is_actionable",
        "snapshot_date",
    ]
    available = [c for c in columns if c in df.columns]
    records = _df_to_records(df[available])
    _write_artifact(records, artifacts_root / "allele_frequencies.json")
    return len(records)


def export_phenotype_distribution(
    gold_root: Path,
    artifacts_root: Path,
) -> int:
    """Export gold phenotype distribution to JSON. Returns row count."""
    df = read_silver_table(gold_root / "phenotype_distribution_by_population")
    if df.empty:
        logger.warning("phenotype_distribution_by_population is empty — writing empty artifact")
        _write_artifact([], artifacts_root / "phenotype_distribution.json")
        return 0

    columns = [
        "gene_symbol",
        "population_code",
        "superpopulation",
        "phenotype_category",
        "individual_count",
        "population_total",
        "phenotype_percentage",
        "ci_lower_wilson",
        "ci_upper_wilson",
        "data_source",
        "snapshot_date",
    ]
    available = [c for c in columns if c in df.columns]
    records = _df_to_records(df[available])
    _write_artifact(records, artifacts_root / "phenotype_distribution.json")
    return len(records)


def export_drug_impact_summary(
    gold_root: Path,
    artifacts_root: Path,
) -> int:
    """Export gold drug impact summary to JSON. Returns row count."""
    df = read_silver_table(gold_root / "drug_impact_summary")
    if df.empty:
        logger.warning("drug_impact_summary is empty — writing empty artifact")
        _write_artifact([], artifacts_root / "drug_impact_summary.json")
        return 0

    columns = [
        "drug_name",
        "gene_symbol",
        "population_code",
        "population_total",
        "individuals_requiring_change",
        "percentage_requiring_change",
        "baseline_ceu_percentage",
        "delta_vs_baseline",
        "classification_strength",
        "snapshot_date",
    ]
    available = [c for c in columns if c in df.columns]
    records = _df_to_records(df[available])
    _write_artifact(records, artifacts_root / "drug_impact_summary.json")
    return len(records)


def export_actionability_ranking(
    gold_root: Path,
    artifacts_root: Path,
) -> int:
    """Export gold actionability ranking to JSON. Returns row count."""
    df = read_silver_table(gold_root / "actionability_ranking")
    if df.empty:
        logger.warning("actionability_ranking is empty — writing empty artifact")
        _write_artifact([], artifacts_root / "actionability_ranking.json")
        return 0

    columns = [
        "rank_position",
        "drug_name",
        "gene_symbol",
        "population_code",
        "delta_vs_baseline",
        "population_affected_pct",
        "classification_strength",
        "clinical_implication",
        "snapshot_date",
    ]
    available = [c for c in columns if c in df.columns]
    records = _df_to_records(df[available])
    _write_artifact(records, artifacts_root / "actionability_ranking.json")
    return len(records)


def export_metadata(
    gold_root: Path,
    silver_root: Path,
    artifacts_root: Path,
    snapshot_date: date,
    total_variants: int,
) -> None:
    """Write artifacts/metadata.json describing the pipeline run."""
    populations_df = read_silver_table(silver_root / "populations")

    pop_summary: dict[str, dict[str, Any]] = {}
    if not populations_df.empty:
        for _, row in populations_df.iterrows():
            code = str(row["population_code"])
            pop_summary[code] = {
                "name": _coerce_value(row.get("population_name", code)),
                "region": _coerce_value(row.get("region", "")),
                "superpopulation": _coerce_value(row.get("superpopulation", "")),
                "sample_size": _coerce_value(row.get("sample_size", None)),
            }

    metadata: dict[str, Any] = {
        "schema_version": _SCHEMA_VERSION,
        "snapshot_date": snapshot_date.isoformat(),
        "pipeline_run_id": str(uuid.uuid4()),
        "source_versions": {
            "thousand_genomes": "Phase 3 GRCh37 (20130502)",
            "pharmgkb": "latest at ingest date",
            "cpic": "v4 PostgREST API",
        },
        "populations": pop_summary,
        "total_variants_analyzed": total_variants,
        "generated_at": datetime.utcnow().isoformat() + "Z",
    }
    _write_artifact(metadata, artifacts_root / "metadata.json")


# ── Orchestrator ──────────────────────────────────────────────────────────────


def run(settings: Settings | None = None, snapshot_date: date | None = None) -> None:
    """Export all gold artifacts to artifacts/ directory.

    Args:
        settings: Application settings. Defaults to ``get_settings()``.
        snapshot_date: Snapshot date for metadata. Defaults to today.
    """
    cfg = settings or get_settings()
    snap = snapshot_date or datetime.utcnow().date()

    gold_root = cfg.gold_root
    silver_root = cfg.silver_root
    artifacts_root = cfg.artifacts_root
    artifacts_root.mkdir(parents=True, exist_ok=True)

    logger.info("=== portfolio_artifacts: exporting gold tables ===")

    n_af = export_allele_frequencies(gold_root, artifacts_root)
    n_ph = export_phenotype_distribution(gold_root, artifacts_root)
    n_di = export_drug_impact_summary(gold_root, artifacts_root)
    n_ar = export_actionability_ranking(gold_root, artifacts_root)

    # Unique variants = rows in allele_frequencies ÷ number of populations
    # (approximate — each variant appears once per population)
    export_metadata(gold_root, silver_root, artifacts_root, snap, n_af)

    logger.info(
        "portfolio_artifacts complete — af=%d pheno=%d impact=%d ranking=%d",
        n_af,
        n_ph,
        n_di,
        n_ar,
    )


def main() -> None:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s — %(message)s",
    )
    run()
    print("  ✓ artifacts/allele_frequencies.json")
    print("  ✓ artifacts/phenotype_distribution.json")
    print("  ✓ artifacts/drug_impact_summary.json")
    print("  ✓ artifacts/actionability_ranking.json")
    print("  ✓ artifacts/metadata.json")


if __name__ == "__main__":
    main()
