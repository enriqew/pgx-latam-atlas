"""Bronze layer schema definitions and validation.

Each bronze table has a declared schema: the set of required columns and which
of those must never contain nulls. Validation runs before every Parquet write
so upstream schema changes (PharmGKB renames, CPIC API restructuring, 1000G
format changes) are caught immediately with a clear error instead of silently
producing corrupt data downstream.

Usage::

    from pgx_latam.utils.bronze_schemas import validate_bronze

    validate_bronze(df, "genomes_variants_raw")  # raises RuntimeError on failure
"""

from __future__ import annotations

from dataclasses import dataclass

import pandas as pd


@dataclass(frozen=True)
class ColumnSpec:
    name: str
    nullable: bool = False


@dataclass(frozen=True)
class BronzeSchema:
    table_name: str
    columns: tuple[ColumnSpec, ...]

    def required_names(self) -> frozenset[str]:
        return frozenset(c.name for c in self.columns)

    def non_nullable_names(self) -> frozenset[str]:
        return frozenset(c.name for c in self.columns if not c.nullable)


# ── Schema definitions ────────────────────────────────────────────────────────

_SCHEMAS: dict[str, BronzeSchema] = {
    # 1000 Genomes Phase 3 — per-sample genotype calls
    "genomes_variants_raw": BronzeSchema(
        table_name="genomes_variants_raw",
        columns=(
            ColumnSpec("chromosome"),
            ColumnSpec("position"),
            ColumnSpec("variant_id"),
            ColumnSpec("reference_allele"),
            ColumnSpec("alternate_allele"),
            ColumnSpec("sample_id"),
            ColumnSpec("genotype"),
            ColumnSpec("allele_dosage"),
            ColumnSpec("quality", nullable=True),  # VCF QUAL field can be missing
            ColumnSpec("filter_status"),
            ColumnSpec("info_payload", nullable=True),  # reserved, always null for now
        ),
    ),
    # 1000 Genomes Phase 3 — sample → population mapping
    "samples_metadata_raw": BronzeSchema(
        table_name="samples_metadata_raw",
        columns=(
            ColumnSpec("sample_id"),
            ColumnSpec("population_code"),
            ColumnSpec("superpopulation"),
            ColumnSpec("sex"),
            ColumnSpec("family_id", nullable=True),
        ),
    ),
    # PharmGKB — clinical annotation evidence table
    "pharmgkb_clinical_annotations_raw": BronzeSchema(
        table_name="pharmgkb_clinical_annotations_raw",
        columns=(
            ColumnSpec("clinical_annotation_id"),
            ColumnSpec("gene_symbol"),
            ColumnSpec("evidence_level"),
            ColumnSpec("variant_or_haplotype", nullable=True),
            ColumnSpec("drug_names", nullable=True),
            ColumnSpec("phenotype_categories", nullable=True),
            ColumnSpec("clinical_annotation_types", nullable=True),
            ColumnSpec("pediatric", nullable=True),
            ColumnSpec("annotation_text", nullable=True),
            ColumnSpec("url", nullable=True),
        ),
    ),
    # PharmGKB — variant-drug literature associations
    "pharmgkb_var_drug_ann_raw": BronzeSchema(
        table_name="pharmgkb_var_drug_ann_raw",
        columns=(
            ColumnSpec("annotation_id"),
            ColumnSpec("gene_symbol"),
            ColumnSpec("variant_rsid", nullable=True),
            ColumnSpec("drug_name", nullable=True),
            ColumnSpec("pmid", nullable=True),
            ColumnSpec("phenotype_category", nullable=True),
            ColumnSpec("significance", nullable=True),
            ColumnSpec("notes", nullable=True),
            ColumnSpec("sentence", nullable=True),
            ColumnSpec("alleles", nullable=True),
        ),
    ),
    # PharmGKB — drug reference table
    "pharmgkb_drugs_raw": BronzeSchema(
        table_name="pharmgkb_drugs_raw",
        columns=(
            ColumnSpec("pharmgkb_drug_id"),
            ColumnSpec("drug_name"),
            ColumnSpec("generic_names", nullable=True),
            ColumnSpec("trade_names", nullable=True),
            ColumnSpec("drug_type", nullable=True),
            ColumnSpec("atc_identifiers", nullable=True),
            ColumnSpec("rxnorm_identifiers", nullable=True),
        ),
    ),
    # PharmGKB — gene coordinates table
    "pharmgkb_genes_raw": BronzeSchema(
        table_name="pharmgkb_genes_raw",
        columns=(
            ColumnSpec("pharmgkb_gene_id"),
            ColumnSpec("gene_symbol"),
            ColumnSpec("ensembl_id", nullable=True),
            ColumnSpec("ncbi_gene_id", nullable=True),
            ColumnSpec("chromosome", nullable=True),
            ColumnSpec("chromosomal_start", nullable=True),
            ColumnSpec("chromosomal_end", nullable=True),
        ),
    ),
    # CPIC — prescribing recommendations (one row per recommendation x gene x drug)
    "cpic_guidelines_raw": BronzeSchema(
        table_name="cpic_guidelines_raw",
        columns=(
            ColumnSpec("guideline_id"),
            ColumnSpec("gene_symbol"),
            ColumnSpec("drug_name"),
            ColumnSpec("recommendation_text"),
            ColumnSpec("phenotype", nullable=True),
            ColumnSpec("activity_score", nullable=True),
            ColumnSpec("classification_strength", nullable=True),
            ColumnSpec("cpic_release_version", nullable=True),
        ),
    ),
}


# ── Validation ────────────────────────────────────────────────────────────────


def validate_bronze(df: pd.DataFrame, table_name: str) -> None:
    """Validate a DataFrame against the declared bronze schema.

    Checks that all required columns are present and that non-nullable columns
    contain no null values. Silently skips tables with no declared schema.

    Args:
        df: DataFrame about to be written to bronze Parquet.
        table_name: Name of the bronze table (e.g. ``"genomes_variants_raw"``).

    Raises:
        RuntimeError: If required columns are missing or non-nullable columns
            contain nulls. The error message names every offending column.
    """
    schema = _SCHEMAS.get(table_name)
    if schema is None:
        return

    actual_cols = set(df.columns)

    missing = schema.required_names() - actual_cols
    if missing:
        raise RuntimeError(
            f"Bronze table {table_name!r}: missing required columns {sorted(missing)}.\n"
            f"Got columns: {sorted(actual_cols)}.\n"
            "The upstream source may have renamed or removed columns — "
            f"update the schema in bronze_schemas.py or the ingestion module."
        )

    null_violations: list[str] = []
    for col_name in schema.non_nullable_names():
        if col_name in actual_cols and df[col_name].isna().any():
            null_count = int(df[col_name].isna().sum())
            null_violations.append(f"  {col_name!r}: {null_count} null value(s)")

    if null_violations:
        raise RuntimeError(
            f"Bronze table {table_name!r}: non-nullable columns contain nulls:\n"
            + "\n".join(null_violations)
            + "\nCheck the upstream source for incomplete or malformed records."
        )
