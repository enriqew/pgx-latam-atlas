"""Build silver/variants/, silver/populations/, and silver/pharmacogenes/ locally.

Reads:
  bronze/genomes_variants_raw/  — per-sample genotype calls per chromosome
  bronze/samples_metadata_raw/  — sample → population mapping
  bronze/pharmgkb_genes_raw/    — gene coordinates from PharmGKB

Produces:
  silver/variants/              — partitioned by gene_symbol_part x population_part
  silver/populations/           — population metadata with sample sizes
  silver/pharmacogenes/         — in-scope gene list with coordinates and rationale
"""

from __future__ import annotations

import logging
from pathlib import Path

import pandas as pd

from pgx_latam.config import Settings, get_settings
from pgx_latam.ingestion.thousand_genomes import GENE_REGIONS_GRCH37, TARGET_POPULATIONS
from pgx_latam.utils.parquet_io import (
    read_latest_bronze_partition,
    write_silver_table,
    write_silver_variants_partition,
)
from pgx_latam.utils.star_allele_scope import IN_SCOPE_GENES

logger = logging.getLogger(__name__)

# ── Population reference data ─────────────────────────────────────────────────

# (population_name, region) — superpopulation comes from the panel file
_POPULATION_NAMES: dict[str, tuple[str, str]] = {
    "MXL": ("Mexican Ancestry in Los Angeles, California", "Latin America"),
    "PEL": ("Peruvians in Lima, Peru", "Latin America"),
    "CLM": ("Colombians in Medellín, Colombia", "Latin America"),
    "PUR": ("Puerto Ricans in Puerto Rico", "Latin America"),
    "CEU": (
        "Utah Residents (CEPH) with Northern and Western European Ancestry",
        "Europe",
    ),
    "YRI": ("Yoruba in Ibadan, Nigeria", "Sub-Saharan Africa"),
    "ASW": ("African Ancestry in Southwest USA", "African American"),
    "GIH": ("Gujarati Indian from Houston, Texas", "South Asia"),
}

# ── Gene assignment ───────────────────────────────────────────────────────────


def assign_gene_symbols(
    chrom_series: pd.Series,
    pos_series: pd.Series,
) -> pd.Series:
    """Vectorised gene assignment: map (chromosome, position) → gene_symbol.

    Uses exact gene boundaries from GENE_REGIONS_GRCH37 (no buffer — the buffer
    was only for VCF extraction; here we assign variants to their canonical gene).

    Args:
        chrom_series: String series of chromosome labels (e.g. "chr10").
        pos_series: Integer series of 1-based positions (GRCh37).

    Returns:
        String series of gene symbols; NA for variants outside any gene boundary.
    """
    result = pd.Series(pd.NA, index=chrom_series.index, dtype="object")
    for gene, region in GENE_REGIONS_GRCH37.items():
        target_chrom = f"chr{region.chromosome}"
        mask = (
            (chrom_series == target_chrom)
            & (pos_series >= region.start)
            & (pos_series <= region.end)
        )
        result[mask] = gene
    return result


# ── silver/populations/ ───────────────────────────────────────────────────────


def build_populations(samples_df: pd.DataFrame) -> pd.DataFrame:
    """Build the silver populations table from the samples metadata.

    Args:
        samples_df: bronze samples_metadata_raw DataFrame.

    Returns:
        DataFrame matching silver_pgx.populations schema.
    """
    target_df = samples_df[samples_df["population_code"].isin(TARGET_POPULATIONS)]
    size_series = (
        target_df.groupby(["population_code", "superpopulation"])
        .size()
        .reset_index(name="sample_size")
    )

    rows = []
    for _, row in size_series.iterrows():
        pop_code: str = row["population_code"]
        pop_name, region = _POPULATION_NAMES.get(pop_code, (pop_code, "Unknown"))
        rows.append(
            {
                "population_code": pop_code,
                "population_name": pop_name,
                "superpopulation": row["superpopulation"],
                "region": region,
                "sample_size": int(row["sample_size"]),
            }
        )

    df = pd.DataFrame(rows)
    logger.info("Built populations table: %d rows", len(df))
    return df


# ── silver/pharmacogenes/ ────────────────────────────────────────────────────


def build_pharmacogenes(pharmgkb_genes_df: pd.DataFrame) -> pd.DataFrame:
    """Build the silver pharmacogenes table.

    Joins PharmGKB gene coordinates with the in-scope scope definition.
    Includes both in-scope and explicitly-excluded genes (e.g. CYP2D6).

    Args:
        pharmgkb_genes_df: bronze pharmgkb_genes_raw DataFrame.

    Returns:
        DataFrame matching silver_pgx.pharmacogenes schema.
    """
    scope_genes = set(IN_SCOPE_GENES.keys())
    pgkb_filtered = pharmgkb_genes_df[pharmgkb_genes_df["gene_symbol"].isin(scope_genes)].copy()

    rows = []
    for _, gene_row in pgkb_filtered.iterrows():
        gene_sym: str = gene_row["gene_symbol"]
        scope = IN_SCOPE_GENES.get(gene_sym)
        if scope is None:
            continue
        rows.append(
            {
                "gene_symbol": gene_sym,
                "ensembl_id": gene_row.get("ensembl_id", pd.NA),
                "ncbi_gene_id": gene_row.get("ncbi_gene_id", pd.NA),
                "chromosome": gene_row.get("chromosome", pd.NA),
                "chromosomal_start": _safe_int(gene_row.get("chromosomal_start")),
                "chromosomal_end": _safe_int(gene_row.get("chromosomal_end")),
                "is_in_scope": scope.in_scope,
                "scope_rationale": scope.rationale,
            }
        )

    # Add any in-scope genes missing from PharmGKB (using fallback coordinates)
    pgkb_symbols = set(pgkb_filtered["gene_symbol"].tolist())
    for gene_sym, scope in IN_SCOPE_GENES.items():
        if gene_sym in pgkb_symbols:
            continue
        region = GENE_REGIONS_GRCH37.get(gene_sym)
        rows.append(
            {
                "gene_symbol": gene_sym,
                "ensembl_id": pd.NA,
                "ncbi_gene_id": pd.NA,
                "chromosome": f"chr{region.chromosome}" if region else pd.NA,
                "chromosomal_start": region.start if region else pd.NA,
                "chromosomal_end": region.end if region else pd.NA,
                "is_in_scope": scope.in_scope,
                "scope_rationale": scope.rationale,
            }
        )

    df = pd.DataFrame(rows)
    logger.info("Built pharmacogenes table: %d rows", len(df))
    return df


def _safe_int(value: object) -> int | None:
    try:
        if pd.isna(value):  # type: ignore[call-overload]
            return None
    except (TypeError, ValueError):
        pass
    try:
        return int(value)  # type: ignore[call-overload, no-any-return]
    except (TypeError, ValueError):
        return None


# ── silver/variants/ ──────────────────────────────────────────────────────────


def build_variants(
    variants_df: pd.DataFrame,
    samples_df: pd.DataFrame,
    silver_root: Path,
) -> int:
    """Join bronze variants with sample metadata, assign genes, write silver partitions.

    Emits one Parquet file per (gene_symbol x population_code) combination.

    Args:
        variants_df: bronze genomes_variants_raw DataFrame.
        samples_df: bronze samples_metadata_raw DataFrame.
        silver_root: Path to the silver layer root directory.

    Returns:
        Total rows written across all partitions.
    """
    sample_lookup = samples_df.set_index("sample_id")[["population_code", "superpopulation"]]
    target_sample_ids = set(
        samples_df[samples_df["population_code"].isin(TARGET_POPULATIONS)]["sample_id"]
    )

    filtered = variants_df[variants_df["sample_id"].isin(target_sample_ids)].copy()
    if filtered.empty:
        raise RuntimeError(
            "No variants match target population samples after filtering. "
            "Check that bronze/genomes_variants_raw/ and bronze/samples_metadata_raw/ "
            "were ingested from the same 1000G release."
        )

    # Assign gene_symbol to each unique (chromosome, position)
    unique_positions = (
        filtered[["chromosome", "position", "variant_id"]]
        .drop_duplicates(subset=["variant_id"])
        .copy()
    )
    unique_positions["gene_symbol"] = assign_gene_symbols(
        unique_positions["chromosome"], unique_positions["position"]
    )
    filtered = filtered.merge(
        unique_positions[["variant_id", "gene_symbol"]],
        on="variant_id",
        how="left",
    )

    # Drop variants that don't map to any gene (buffer variants)
    before = len(filtered)
    filtered = filtered[filtered["gene_symbol"].notna()].copy()
    dropped = before - len(filtered)
    if dropped:
        logger.info("Dropped %d buffer/intergenic variant rows", dropped)

    # Join population info
    filtered = filtered.join(sample_lookup, on="sample_id", how="left")

    # Drop bronze columns not in silver schema
    silver_cols = [
        "sample_id",
        "variant_id",
        "gene_symbol",
        "chromosome",
        "position",
        "reference_allele",
        "alternate_allele",
        "genotype",
        "allele_dosage",
        "population_code",
        "superpopulation",
    ]
    available = [c for c in silver_cols if c in filtered.columns]
    filtered = filtered[available].drop_duplicates(subset=["sample_id", "variant_id"])

    table_root = silver_root / "variants"
    total_rows = 0

    for gene_symbol, gene_df in filtered.groupby("gene_symbol"):
        for population_code, pop_df in gene_df.groupby("population_code"):
            write_silver_variants_partition(
                pop_df.reset_index(drop=True),
                table_root,
                str(gene_symbol),
                str(population_code),
            )
            total_rows += len(pop_df)

    logger.info(
        "silver/variants/: %d rows across %d partitions",
        total_rows,
        len(list(table_root.rglob("data.parquet"))),
    )
    return total_rows


# ── Orchestrator ──────────────────────────────────────────────────────────────


def run(settings: Settings | None = None) -> None:
    """Build all three silver variant-side tables from bronze.

    Args:
        settings: Application settings. Defaults to ``get_settings()``.
    """
    cfg = settings or get_settings()

    logger.info("=== silver_variants: reading bronze tables ===")
    samples_df = read_latest_bronze_partition(cfg.bronze_root / "samples_metadata_raw")
    variants_df = read_latest_bronze_partition(cfg.bronze_root / "genomes_variants_raw")
    pharmgkb_genes_df = read_latest_bronze_partition(cfg.bronze_root / "pharmgkb_genes_raw")

    logger.info("=== silver_variants: building populations ===")
    populations_df = build_populations(samples_df)
    write_silver_table(populations_df, cfg.silver_root / "populations")

    logger.info("=== silver_variants: building pharmacogenes ===")
    pharmacogenes_df = build_pharmacogenes(pharmgkb_genes_df)
    write_silver_table(pharmacogenes_df, cfg.silver_root / "pharmacogenes")

    logger.info("=== silver_variants: building variants ===")
    total = build_variants(variants_df, samples_df, cfg.silver_root)
    logger.info("silver_variants complete — %d total variant rows", total)


def main() -> None:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s — %(message)s",
    )
    run()
    print("  ✓ silver/populations/")
    print("  ✓ silver/pharmacogenes/")
    print("  ✓ silver/variants/")


if __name__ == "__main__":
    main()
