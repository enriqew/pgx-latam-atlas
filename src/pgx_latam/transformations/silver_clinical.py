"""Build silver/clinical_variants/ and silver/drug_recommendations/ locally.

Reads:
  bronze/pharmgkb_clinical_annotations_raw/  — clinical annotations with evidence levels
  bronze/pharmgkb_var_drug_ann_raw/           — variant-drug literature associations
  bronze/cpic_guidelines_raw/                 — CPIC prescribing recommendations

Produces:
  silver/clinical_variants/      — actionable variants (PharmGKB evidence 1A / 1B)
  silver/drug_recommendations/   — CPIC recommendations with dose-change flags
"""

from __future__ import annotations

import logging
import re

import pandas as pd

from pgx_latam.config import Settings, get_settings
from pgx_latam.utils.parquet_io import (
    read_latest_bronze_partition,
    write_silver_table,
)
from pgx_latam.utils.star_allele_scope import in_scope_symbols

logger = logging.getLogger(__name__)

# ── Actionability ─────────────────────────────────────────────────────────────

_ACTIONABLE_EVIDENCE_LEVELS = frozenset({"1A", "1B"})

# ── Dose-change / alternative-therapy classifiers ────────────────────────────
# Applied to CPIC recommendation_text (lowercase) to set silver flags.
# These drive the gold-layer "individuals_requiring_change" calculation.

_DOSE_CHANGE_PATTERNS: list[re.Pattern[str]] = [
    re.compile(r"\breduce\b"),
    re.compile(r"\breduction\b"),
    re.compile(r"\blower (the |a |your )?dose\b"),
    re.compile(r"\bdose (reduction|adjustment|decrease)\b"),
    re.compile(r"\badjust(ed)? dose\b"),
    re.compile(r"\bstart (at|with) (a )?lower\b"),
    re.compile(r"\btitrat"),  # matches titrate, titration, titrating
    re.compile(r"\b\d+\s*%\s*(of|reduction)\b"),
    re.compile(r"\bmodified dose\b"),
    re.compile(r"\bdosage adjustment\b"),
    re.compile(r"\bdecrease (the )?dose\b"),
    re.compile(r"\bincrease (starting |the )?dose\b"),
]

_ALTERNATIVE_PATTERNS: list[re.Pattern[str]] = [
    re.compile(r"\bavoid\b"),
    re.compile(r"\balternative\b"),
    re.compile(r"\bcontraindicated\b"),
    re.compile(r"\bdo not use\b"),
    re.compile(r"\bswitch\b"),
    re.compile(r"\bselect an?other\b"),
    re.compile(r"\bconsider an?other\b"),
    re.compile(r"\buse an?other\b"),
    re.compile(r"\bnot recommended\b"),
    re.compile(r"\bsubstitut\b"),
]


# VKORC1 warfarin recommendations are not exposed in the CPIC API response
# (warfarin dosing uses a joint VKORC1+CYP2C9 algorithm). These rows are
# curated from CPIC Table S1 of the warfarin guideline (PMID 28198005).
_CURATED_RECOMMENDATIONS: list[dict[str, object]] = [
    {
        "gene_symbol": "VKORC1",
        "drug_name": "warfarin",
        "phenotype": "Normal Sensitivity",
        "recommendation_text": "Initiate therapy with standard recommended dose.",
        "classification_strength": "Strong",
        "requires_dose_change": False,
        "requires_alternative": False,
        "cpic_release_version": "v1.4-2017",
    },
    {
        "gene_symbol": "VKORC1",
        "drug_name": "warfarin",
        "phenotype": "Intermediate Sensitivity",
        "recommendation_text": "Consider moderate dose reduction based on VKORC1 sensitivity genotype.",
        "classification_strength": "Strong",
        "requires_dose_change": True,
        "requires_alternative": False,
        "cpic_release_version": "v1.4-2017",
    },
    {
        "gene_symbol": "VKORC1",
        "drug_name": "warfarin",
        "phenotype": "High Sensitivity",
        "recommendation_text": "Consider significant dose reduction based on VKORC1 high sensitivity genotype.",
        "classification_strength": "Strong",
        "requires_dose_change": True,
        "requires_alternative": False,
        "cpic_release_version": "v1.4-2017",
    },
    # IFNL3 (IL28B) peginterferon recommendations — not exposed in the CPIC PostgREST API v1.
    # Curated from CPIC IL28B / IFNL3 guideline for peginterferon + ribavirin HCV therapy
    # (Muir et al., 2014, Clin Pharmacol Ther. PMID 24096968).
    # rs12979860 CC genotype = Favorable; CT = Intermediate; TT = Unfavorable.
    # In our pipeline, the proxy variant (chr19:39739155 T>G) codes G as the
    # non-reference / unfavorable allele (dosage ≥ 1 = reduced response).
    {
        "gene_symbol": "IFNL3",
        "drug_name": "peginterferon alfa-2a",
        "phenotype": "Favorable Genotype",
        "recommendation_text": (
            "Initiate peginterferon alfa-2a plus ribavirin at standard doses. "
            "CC genotype (favorable) is associated with approximately 70% sustained virologic "
            "response (SVR) rate in HCV genotype 1 patients."
        ),
        "classification_strength": "Strong",
        "requires_dose_change": False,
        "requires_alternative": False,
        "cpic_release_version": "v1.0-2014",
    },
    {
        "gene_symbol": "IFNL3",
        "drug_name": "peginterferon alfa-2a",
        "phenotype": "Intermediate Genotype",
        "recommendation_text": (
            "Initiate peginterferon alfa-2a plus ribavirin at standard doses. "
            "CT genotype (intermediate) is associated with intermediate SVR rates (~40–50%). "
            "Enhanced monitoring is recommended."
        ),
        "classification_strength": "Strong",
        "requires_dose_change": False,
        "requires_alternative": False,
        "cpic_release_version": "v1.0-2014",
    },
    {
        "gene_symbol": "IFNL3",
        "drug_name": "peginterferon alfa-2a",
        "phenotype": "Unfavorable Genotype",
        "recommendation_text": (
            "Consider alternative therapy. TT genotype (unfavorable) is associated with "
            "approximately 25–30% SVR rate for HCV genotype 1. "
            "Direct-acting antiviral (DAA) regimens are preferred when available, "
            "as they are not impacted by IFNL3 genotype."
        ),
        "classification_strength": "Strong",
        "requires_dose_change": False,
        "requires_alternative": True,
        "cpic_release_version": "v1.0-2014",
    },
    {
        "gene_symbol": "IFNL3",
        "drug_name": "peginterferon alfa-2b",
        "phenotype": "Favorable Genotype",
        "recommendation_text": (
            "Initiate peginterferon alfa-2b plus ribavirin at standard doses. "
            "CC genotype (favorable) is associated with approximately 70% SVR rate "
            "in HCV genotype 1 patients."
        ),
        "classification_strength": "Strong",
        "requires_dose_change": False,
        "requires_alternative": False,
        "cpic_release_version": "v1.0-2014",
    },
    {
        "gene_symbol": "IFNL3",
        "drug_name": "peginterferon alfa-2b",
        "phenotype": "Intermediate Genotype",
        "recommendation_text": (
            "Initiate peginterferon alfa-2b plus ribavirin at standard doses. "
            "CT genotype (intermediate) is associated with intermediate SVR rates. "
            "Enhanced monitoring is recommended."
        ),
        "classification_strength": "Strong",
        "requires_dose_change": False,
        "requires_alternative": False,
        "cpic_release_version": "v1.0-2014",
    },
    {
        "gene_symbol": "IFNL3",
        "drug_name": "peginterferon alfa-2b",
        "phenotype": "Unfavorable Genotype",
        "recommendation_text": (
            "Consider alternative therapy. TT genotype (unfavorable) is associated with "
            "approximately 25–30% SVR rate for HCV genotype 1. "
            "DAA regimens are preferred when available."
        ),
        "classification_strength": "Strong",
        "requires_dose_change": False,
        "requires_alternative": True,
        "cpic_release_version": "v1.0-2014",
    },
    # UGT1A9 mycophenolate recommendations — not in CPIC PostgREST API v1.
    # Curated from CPIC UGT1A8/UGT1A9 guideline for immunosuppressants (Luzum et al., 2021,
    # Clin Pharmacol Ther. PMID 34115020). UGT1A9*3 reduces glucuronidation → higher MPA exposure.
    {
        "gene_symbol": "UGT1A9",
        "drug_name": "mycophenolate mofetil",
        "phenotype": "Normal Metabolizer",
        "recommendation_text": (
            "Initiate therapy with standard recommended dose of mycophenolate mofetil. "
            "No genotype-based dose adjustment required."
        ),
        "classification_strength": "Moderate",
        "requires_dose_change": False,
        "requires_alternative": False,
        "cpic_release_version": "v1.0-2021",
    },
    {
        "gene_symbol": "UGT1A9",
        "drug_name": "mycophenolate mofetil",
        "phenotype": "Intermediate Metabolizer",
        "recommendation_text": (
            "Initiate therapy with standard recommended dose. "
            "Enhanced therapeutic drug monitoring may be warranted due to genotype-predicted "
            "intermediate UGT1A9 activity and potential for altered MPA exposure."
        ),
        "classification_strength": "Moderate",
        "requires_dose_change": False,
        "requires_alternative": False,
        "cpic_release_version": "v1.0-2021",
    },
    {
        "gene_symbol": "UGT1A9",
        "drug_name": "mycophenolate mofetil",
        "phenotype": "Poor Metabolizer",
        "recommendation_text": (
            "Consider dose reduction of mycophenolate mofetil. "
            "UGT1A9*3/*3 genotype predicts substantially reduced glucuronidation and higher "
            "mycophenolic acid (MPA) systemic exposure; dose reduction and enhanced monitoring recommended."
        ),
        "classification_strength": "Moderate",
        "requires_dose_change": True,
        "requires_alternative": False,
        "cpic_release_version": "v1.0-2021",
    },
]


def _classify_recommendation(text: str, classification_strength: str) -> tuple[bool, bool]:
    """Return (requires_dose_change, requires_alternative) for a recommendation.

    No flags are set for "No recommendation" or empty strength regardless of text,
    as those represent insufficient evidence for clinical action.

    Args:
        text: CPIC recommendation text (any case).
        classification_strength: CPIC classification (Strong / Moderate / Optional / ...).

    Returns:
        Tuple of (requires_dose_change, requires_alternative).
    """
    strength = (classification_strength or "").strip().lower()
    if strength in ("no recommendation", ""):
        return False, False

    lower = text.lower()
    requires_dose_change = any(p.search(lower) for p in _DOSE_CHANGE_PATTERNS)
    requires_alternative = any(p.search(lower) for p in _ALTERNATIVE_PATTERNS)
    return requires_dose_change, requires_alternative


# ── silver/clinical_variants/ ─────────────────────────────────────────────────


def build_clinical_variants(
    clinical_ann_df: pd.DataFrame,
    var_drug_ann_df: pd.DataFrame,
) -> pd.DataFrame:
    """Build silver/clinical_variants/ from PharmGKB annotations.

    Filters clinical annotations to in-scope genes and actionable evidence levels.
    The var_drug_ann table supplements with rsID-level variant identifiers.

    Args:
        clinical_ann_df: bronze pharmgkb_clinical_annotations_raw DataFrame.
        var_drug_ann_df: bronze pharmgkb_var_drug_ann_raw DataFrame.

    Returns:
        DataFrame matching silver_pgx.clinical_variants schema.
    """
    scope = set(in_scope_symbols())
    ann = clinical_ann_df[clinical_ann_df["gene_symbol"].isin(scope)].copy()

    if ann.empty:
        logger.warning(
            "No clinical annotations found for in-scope genes. "
            "PharmGKB data may be empty — check bronze/pharmgkb_clinical_annotations_raw/."
        )
        return pd.DataFrame(
            columns=[
                "variant_rsid",
                "gene_symbol",
                "drug_name",
                "phenotype_category",
                "evidence_level",
                "is_actionable",
                "annotation_summary",
            ]
        )

    ann["is_actionable"] = ann["evidence_level"].isin(_ACTIONABLE_EVIDENCE_LEVELS)
    ann["annotation_summary"] = (
        ann.get("annotation_text", pd.Series(dtype=str)).fillna("").str[:500]
    )

    # Explode drug_names (semicolon or comma separated) to one row per drug
    ann["drug_name"] = (
        ann["drug_names"]
        .str.split(r"[,;]")
        .apply(
            lambda parts: [p.strip() for p in (parts or [])] if isinstance(parts, list) else [""]
        )
    )
    ann = ann.explode("drug_name").reset_index(drop=True)
    ann["drug_name"] = ann["drug_name"].str.strip().str.lower()

    # Use variant_or_haplotype as variant_rsid; keep rsID-like values as-is
    ann = ann.rename(columns={"variant_or_haplotype": "variant_rsid"})
    ann["phenotype_category"] = ann.get("phenotype_categories", pd.Series(dtype=str)).fillna("")

    silver_cols = [
        "variant_rsid",
        "gene_symbol",
        "drug_name",
        "phenotype_category",
        "evidence_level",
        "is_actionable",
        "annotation_summary",
    ]
    available = [c for c in silver_cols if c in ann.columns]
    result = ann[available].drop_duplicates(subset=["variant_rsid", "gene_symbol", "drug_name"])

    logger.info(
        "silver/clinical_variants/: %d rows (%d actionable)",
        len(result),
        result["is_actionable"].sum() if "is_actionable" in result.columns else 0,
    )
    return result.reset_index(drop=True)


# ── silver/drug_recommendations/ ──────────────────────────────────────────────


def build_drug_recommendations(cpic_df: pd.DataFrame) -> pd.DataFrame:
    """Build silver/drug_recommendations/ from CPIC guidelines.

    Classifies each recommendation row for dose-change and alternative-therapy
    requirements. These flags drive the gold-layer impact calculation.

    Args:
        cpic_df: bronze cpic_guidelines_raw DataFrame.

    Returns:
        DataFrame matching silver_pgx.drug_recommendations schema.
    """
    scope = set(in_scope_symbols())
    filtered = cpic_df[cpic_df["gene_symbol"].isin(scope)].copy()

    if filtered.empty:
        logger.warning(
            "No CPIC recommendations found for in-scope genes. Check bronze/cpic_guidelines_raw/."
        )
        return pd.DataFrame(
            columns=[
                "gene_symbol",
                "drug_name",
                "phenotype",
                "recommendation_text",
                "classification_strength",
                "requires_dose_change",
                "requires_alternative",
                "cpic_release_version",
            ]
        )

    flags = filtered.apply(
        lambda row: _classify_recommendation(
            row.get("recommendation_text", "") or "",
            row.get("classification_strength", "") or "",
        ),
        axis=1,
        result_type="expand",
    )
    filtered["requires_dose_change"] = flags[0]
    filtered["requires_alternative"] = flags[1]

    filtered["drug_name"] = filtered["drug_name"].str.strip().str.lower()

    silver_cols = [
        "gene_symbol",
        "drug_name",
        "phenotype",
        "recommendation_text",
        "classification_strength",
        "requires_dose_change",
        "requires_alternative",
        "cpic_release_version",
    ]
    available = [c for c in silver_cols if c in filtered.columns]
    result = filtered[available].drop_duplicates(subset=["gene_symbol", "drug_name", "phenotype"])

    n_dose = result["requires_dose_change"].sum()
    n_alt = result["requires_alternative"].sum()
    logger.info(
        "silver/drug_recommendations/: %d rows — %d require dose change, %d require alternative",
        len(result),
        n_dose,
        n_alt,
    )
    curated_df = pd.DataFrame(_CURATED_RECOMMENDATIONS)
    result = pd.concat([result, curated_df], ignore_index=True)
    return result.reset_index(drop=True)


# ── Orchestrator ──────────────────────────────────────────────────────────────


def run(settings: Settings | None = None) -> None:
    """Build silver/clinical_variants/ and silver/drug_recommendations/ from bronze.

    Args:
        settings: Application settings. Defaults to ``get_settings()``.
    """
    cfg = settings or get_settings()

    logger.info("=== silver_clinical: reading bronze tables ===")
    clinical_ann_df = read_latest_bronze_partition(
        cfg.bronze_root / "pharmgkb_clinical_annotations_raw"
    )
    var_drug_ann_df = read_latest_bronze_partition(cfg.bronze_root / "pharmgkb_var_drug_ann_raw")
    cpic_df = read_latest_bronze_partition(cfg.bronze_root / "cpic_guidelines_raw")

    logger.info("=== silver_clinical: building clinical_variants ===")
    clinical_df = build_clinical_variants(clinical_ann_df, var_drug_ann_df)
    write_silver_table(clinical_df, cfg.silver_root / "clinical_variants")

    logger.info("=== silver_clinical: building drug_recommendations ===")
    recs_df = build_drug_recommendations(cpic_df)
    write_silver_table(recs_df, cfg.silver_root / "drug_recommendations")

    logger.info("silver_clinical complete")


def main() -> None:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s — %(message)s",
    )
    run()
    print("  ✓ silver/clinical_variants/")
    print("  ✓ silver/drug_recommendations/")


if __name__ == "__main__":
    main()
