"""Build gold layer tables locally from silver data.

Produces:
  data/gold/allele_frequencies_by_population/
  data/gold/phenotype_distribution_by_population/
  data/gold/drug_impact_summary/
  data/gold/actionability_ranking/

All tables include a snapshot_date column for lineage and future Bedrock KB filtering.
"""

from __future__ import annotations

import logging
from datetime import date, datetime

import pandas as pd

from pgx_latam.config import Settings, get_settings
from pgx_latam.utils.parquet_io import (
    read_silver_table,
    write_silver_table,  # reused for gold — same non-partitioned parquet format locally
)
from pgx_latam.utils.wilson_ci import wilson_score_interval

logger = logging.getLogger(__name__)

# ── Phenotype inference ───────────────────────────────────────────────────────

# Primary loss-of-function variants per gene, as positional IDs (chr:pos, GRCh37).
# The 1000G Phase 3 VCF has "." in the ID field for all variants; pysam falls back to
# positional format, so rsIDs never appear in bronze/silver data.
# Positions confirmed present in the 1000G Phase 3 bronze layer.
#
# NUDT15 note: rs116855232 (p.Arg139Cys, *3) GRCh37 canonical position is chr13:48604006,
# which is absent from the Phase 3 VCF.  chr13:48605878 G>A is the best available proxy for
# MXL/PEL/CLM (AF ~0.08, ~0.09, ~0.04 respectively) but is monomorphic in CEU and PUR in
# the 1000G Phase 3 VCF.  The 0% carrier rate for PUR is a known data artefact: published
# 1000G Phase 3 / gnomAD data report rs116855232 PUR AF ≈ 0.031 (see NUDT15_PUR_LIT_CORRECTION
# below).  The gold phenotype_distribution applies a post-hoc literature correction for PUR
# using the published allele frequency from 1000G Phase 3 (source: gnomAD v2.1 1000G subset,
# accessed 2026-05; PMID 28369952).  All other populations use VCF-derived frequencies.
#
# SLCO1B1 note: rs4149056 GRCh37 canonical position is chr12:21331549 (T>C, c.521T>C).
# The previous key chr12:21331546 (A>G) is 3 bp upstream and monomorphic in all cohorts (AF=0).
# chr12:21331549 has population AFs: CEU 0.146, CLM 0.181, MXL 0.078, PEL 0.141, PUR 0.120.
# These are modestly lower than gnomAD v4.1 CEU (~0.187) but within expected sampling error
# for n~100 cohorts.  Phenotype naming follows CPIC transporter-activity framework
# (Normal/Decreased/Poor Function) not metabolizer terminology, to match drug_recommendations.
#
# IFNL3 note: rs12979860 (C>T) GRCh37 position is chr19:39739183, absent from the Phase 3 VCF.
# Previous proxy chr19:39739155 (T>G) had total absolute error 0.338 vs published 1000G Phase 3
# allele frequencies (CEU 0.278 vs expected 0.371; PEL 0.382 vs expected 0.523).
# Replaced with chr19:39747741 (A>C), which has lower total error 0.190 vs published 1000G
# (CEU 0.298, MXL 0.500, PEL 0.441, CLM 0.468, PUR 0.418; expected unfavorable T allele:
# CEU 0.371, MXL 0.481, PEL 0.523, CLM 0.457, PUR 0.423).  The C alternate allele at
# chr19:39747741 is in LD with the unfavorable rs12979860-T haplotype; interpret phenotype
# distribution as approximate.  Source: 1000G Phase 3 browser / PMID 26432246.
GENE_KEY_VARIANTS: dict[str, tuple[str, ...]] = {
    "CYP2C19": ("chr10:96521657", "chr10:96540410"),  # *2 (rs4244285), *3 (rs4986893)
    "CYP2C9": ("chr10:96741053",),  # *2 (rs1799853)
    "SLCO1B1": ("chr12:21331549",),  # *5 (rs4149056; c.521T>C; T>C; CEU AF ~0.146)
    "VKORC1": ("chr16:31093954",),  # -1639G>A proxy (rs9923231; CEU AF ~0.31)
    "TPMT": ("chr6:18131419",),  # *3B (rs1800460)
    "NUDT15": (
        "chr13:48605878",
    ),  # *3 proxy (rs116855232 nearest; G>A; CEU AF ~0.00; PUR corrected via literature — see note above)
    "DPYD": ("chr1:97981343", "chr1:97915614", "chr1:97981395"),  # *2A, HapB3, *13
    "G6PD": ("chrX:153763492", "chrX:153764217"),  # Ser188Phe, Glu202Lys
    "IFNL3": (
        "chr19:39747741",
    ),  # rs12979860 proxy (A>C; C allele = unfavorable haplotype; CEU AF ~0.30; calibrated 2026-05)
    "CYP3A5": ("chr7:99251073",),  # *3 proxy (rs776746; CEU AF ~0.955)
    "UGT1A9": (
        "chr2:234578428",
    ),  # *3 (rs17868320, c.98T>C; ALT=T is non-functional allele; CEU AF ~0.015)
}

# ── Literature corrections ────────────────────────────────────────────────────
#
# NUDT15 PUR correction:
# The VCF proxy chr13:48605878 (G>A) is monomorphic in PUR in 1000G Phase 3, producing a
# spurious 0% carrier rate.  Published rs116855232 allele frequency in PUR from 1000G Phase 3
# (gnomAD v2.1 1000G subset, 2026-05): AF = 0.031.
# Under Hardy-Weinberg equilibrium with AF=0.031:
#   Normal Metabolizer (*1/*1): (1-0.031)^2 = 0.939
#   Intermediate Metabolizer (*1/*3): 2*0.031*0.969 = 0.060
#   Poor Metabolizer (*3/*3): 0.031^2 = 0.001
# These proportions are applied as a post-hoc replacement for NUDT15/PUR rows in
# phenotype_distribution_by_population.  Values derived from literature are flagged with
# data_source = "literature_1000G_gnomAD" in the output; VCF-derived rows use "vcf_1000G_phase3".
NUDT15_PUR_LIT_AF = 0.031  # rs116855232 PUR AF from published 1000G Phase 3 / gnomAD v2.1

_ACTIONABILITY_RANKING_TOP_N = 50


def _infer_phenotype(gene: str, total_nonfunc_dosage: int) -> str:
    """Map total non-functional allele dosage to a CPIC-aligned phenotype category.

    Uses a simplified framework that works for most biallelic pharmacogenes.
    Complex multi-variant gene interactions (e.g. CYP2D6 gene duplication) are
    explicitly out of scope — see docs/methodology.md and star_allele_scope.py.

    Args:
        gene: HGNC gene symbol.
        total_nonfunc_dosage: Sum of alternate allele dosages at key variants (0, 1, or 2+).

    Returns:
        CPIC-aligned phenotype category string.
    """
    if gene == "IFNL3":
        mapping = {0: "Favorable Genotype", 1: "Intermediate Genotype", 2: "Unfavorable Genotype"}
    elif gene == "G6PD":
        # G6PD is X-linked; males are hemizygous. Dosage 1 in males = deficient.
        mapping = {0: "Normal", 1: "Deficient", 2: "Deficient"}
    elif gene == "VKORC1":
        # rs9923231 A allele (alternate) increases sensitivity to warfarin.
        # Dosage counts the sensitivity-increasing alleles.
        mapping = {0: "Normal Sensitivity", 1: "Intermediate Sensitivity", 2: "High Sensitivity"}
    elif gene == "SLCO1B1":
        # SLCO1B1*5 (chr12:21331549 T>C) = reduced-transport allele (rs4149056, c.521T>C).
        # CPIC uses transporter-activity rather than metabolizer terminology for SLCO1B1.
        # Dosage 0 = *1a/*1a → Normal Function
        # Dosage 1 = *1a/*5 → Decreased Function (heterozygous; ~20-30% of LATAM cohorts)
        # Dosage 2 = *5/*5  → Poor Function (rare)
        # These names match the silver/drug_recommendations phenotype column, enabling the join.
        mapping = {0: "Normal Function", 1: "Decreased Function", 2: "Poor Function"}
    elif gene == "CYP3A5":
        # CYP3A5*3 (chr7:99251073 alternate) = non-expresser allele.
        # 0 copies = expresser → needs higher tacrolimus dose (CPIC: Normal Metabolizer).
        mapping = {0: "Normal Metabolizer", 1: "Intermediate Metabolizer", 2: "Poor Metabolizer"}
    elif gene == "UGT1A9":
        # UGT1A9*3 (chr2:234578428 ALT=T) = reduced-function allele (c.98T>C, rs17868320).
        # Higher *3 dosage → reduced glucuronidation → higher MPA exposure → dose reduction needed.
        mapping = {0: "Normal Metabolizer", 1: "Intermediate Metabolizer", 2: "Poor Metabolizer"}
    else:
        mapping = {
            0: "Normal Metabolizer",
            1: "Intermediate Metabolizer",
            2: "Poor Metabolizer",
        }
    return mapping.get(min(total_nonfunc_dosage, 2), "Indeterminate")


# ── Gold 1: allele_frequencies_by_population ──────────────────────────────────


def build_allele_frequencies(
    variants_df: pd.DataFrame,
    clinical_variants_df: pd.DataFrame,
    snapshot_date: date,
) -> pd.DataFrame:
    """Compute per-variant allele frequencies with Wilson CI and CEU delta.

    Args:
        variants_df: silver/variants/ DataFrame.
        clinical_variants_df: silver/clinical_variants/ DataFrame.
        snapshot_date: Date written to snapshot_date column.

    Returns:
        DataFrame matching gold_pgx.allele_frequencies_by_population schema.
    """
    if variants_df.empty:
        logger.warning("silver/variants/ is empty — allele_frequencies table will be empty")
        return pd.DataFrame()

    group_keys = [
        "variant_id",
        "gene_symbol",
        "chromosome",
        "position",
        "reference_allele",
        "alternate_allele",
        "population_code",
        "superpopulation",
    ]
    available_keys = [k for k in group_keys if k in variants_df.columns]

    agg = (
        variants_df.groupby(available_keys)
        .agg(
            allele_count=("allele_dosage", "sum"),
            n_samples=("sample_id", "nunique"),
        )
        .reset_index()
    )
    agg["total_alleles"] = agg["n_samples"] * 2
    agg["allele_frequency"] = (agg["allele_count"] / agg["total_alleles"]).round(6)

    ci_rows = agg.apply(
        lambda row: wilson_score_interval(int(row["allele_count"]), int(row["total_alleles"])),
        axis=1,
    )
    agg["ci_lower_wilson"] = ci_rows.apply(lambda r: round(r.lower, 6))
    agg["ci_upper_wilson"] = ci_rows.apply(lambda r: round(r.upper, 6))

    # Delta vs CEU
    ceu = agg[agg["population_code"] == "CEU"][["variant_id", "allele_frequency"]].rename(
        columns={"allele_frequency": "_ceu_freq"}
    )
    agg = agg.merge(ceu, on="variant_id", how="left")
    agg["delta_vs_ceu"] = (agg["allele_frequency"] - agg["_ceu_freq"]).round(6)
    agg = agg.drop(columns=["_ceu_freq"])

    # is_actionable join
    actionable_rsids = (
        set(
            clinical_variants_df.loc[
                clinical_variants_df["is_actionable"].fillna(False),
                "variant_rsid",
            ]
        )
        if not clinical_variants_df.empty and "is_actionable" in clinical_variants_df.columns
        else set()
    )
    agg["is_actionable"] = agg["variant_id"].isin(actionable_rsids)
    agg["snapshot_date"] = snapshot_date

    result = agg.drop(columns=["n_samples"])
    logger.info(
        "gold/allele_frequencies_by_population: %d rows (%d actionable)",
        len(result),
        result["is_actionable"].sum(),
    )
    return result


# ── Gold 2: phenotype_distribution_by_population ──────────────────────────────


def build_phenotype_distribution(
    variants_df: pd.DataFrame,
    populations_df: pd.DataFrame,
    snapshot_date: date,
) -> pd.DataFrame:
    """Infer per-individual phenotypes and aggregate by population.

    Uses simplified allele-dosage phenotype inference (see docs/methodology.md).

    Args:
        variants_df: silver/variants/ DataFrame.
        populations_df: silver/populations/ DataFrame.
        snapshot_date: Date written to snapshot_date column.

    Returns:
        DataFrame matching gold_pgx.phenotype_distribution_by_population schema.
    """
    if variants_df.empty:
        logger.warning("silver/variants/ is empty — phenotype_distribution will be empty")
        return pd.DataFrame()

    pop_size_lookup = populations_df.set_index("population_code")["sample_size"].to_dict()

    rows: list[dict[str, object]] = []

    for gene_symbol, gene_df in variants_df.groupby("gene_symbol"):
        key_variants = GENE_KEY_VARIANTS.get(str(gene_symbol), ())
        if not key_variants:
            logger.debug(
                "No key variants defined for gene %s — skipping phenotype inference",
                gene_symbol,
            )
            continue

        gene_key_df = gene_df[gene_df["variant_id"].isin(key_variants)]
        if gene_key_df.empty:
            logger.warning(
                "Gene %s: none of its key variants %s found in silver/variants/. "
                "Phenotype distribution will be absent for this gene.",
                gene_symbol,
                key_variants,
            )
            continue

        # Sum allele_dosage across all key variants per (sample_id, population_code)
        individual_dosage = (
            gene_key_df.groupby(["sample_id", "population_code", "superpopulation"])
            .agg(total_dosage=("allele_dosage", "sum"))
            .reset_index()
        )
        gene_str = str(gene_symbol)
        individual_dosage["phenotype_category"] = individual_dosage.apply(
            lambda row, g=gene_str: _infer_phenotype(g, int(row["total_dosage"])),
            axis=1,
        )

        for pop_code, pop_df in individual_dosage.groupby("population_code"):
            superpop = pop_df["superpopulation"].iloc[0]
            population_total = pop_size_lookup.get(str(pop_code), len(pop_df))

            for phenotype_cat, pheno_df in pop_df.groupby("phenotype_category"):
                individual_count = len(pheno_df)
                if population_total == 0:
                    continue
                proportion = individual_count / population_total
                ci = wilson_score_interval(individual_count, population_total)
                rows.append(
                    {
                        "gene_symbol": gene_symbol,
                        "population_code": pop_code,
                        "superpopulation": superpop,
                        "phenotype_category": phenotype_cat,
                        "individual_count": individual_count,
                        "population_total": population_total,
                        "phenotype_percentage": round(proportion * 100, 2),
                        "ci_lower_wilson": round(ci.lower, 6),
                        "ci_upper_wilson": round(ci.upper, 6),
                        "data_source": "vcf_1000G_phase3",
                        "snapshot_date": snapshot_date,
                    }
                )

    df = pd.DataFrame(rows) if rows else pd.DataFrame()

    # ── NUDT15 PUR literature correction ─────────────────────────────────────
    # The VCF proxy chr13:48605878 is monomorphic in PUR, producing a spurious 0%
    # carrier rate.  Replace NUDT15/PUR rows with HWE-derived proportions from the
    # published rs116855232 AF = 0.031 (1000G Phase 3 / gnomAD v2.1, 2026-05).
    # Rows generated here carry data_source = "literature_1000G_gnomAD" so downstream
    # consumers can distinguish imputed from VCF-derived estimates.
    if not df.empty and "NUDT15" in df["gene_symbol"].values:
        pur_meta = populations_df[populations_df["population_code"] == "PUR"]
        if not pur_meta.empty:
            pur_total = int(pur_meta.iloc[0]["sample_size"])
            pur_superpop = str(pur_meta.iloc[0]["superpopulation"])
            af = NUDT15_PUR_LIT_AF
            hwe_proportions = {
                "Normal Metabolizer": (1 - af) ** 2,
                "Intermediate Metabolizer": 2 * af * (1 - af),
                "Poor Metabolizer": af**2,
            }
            # Drop any existing NUDT15/PUR rows (all will be Normal Metabolizer with 100%)
            df = df[~((df["gene_symbol"] == "NUDT15") & (df["population_code"] == "PUR"))].copy()
            lit_rows: list[dict[str, object]] = []
            for phenotype_cat, proportion in hwe_proportions.items():
                individual_count = round(proportion * pur_total)
                if individual_count == 0:
                    continue
                ci = wilson_score_interval(individual_count, pur_total)
                lit_rows.append(
                    {
                        "gene_symbol": "NUDT15",
                        "population_code": "PUR",
                        "superpopulation": pur_superpop,
                        "phenotype_category": phenotype_cat,
                        "individual_count": individual_count,
                        "population_total": pur_total,
                        "phenotype_percentage": round(proportion * 100, 2),
                        "ci_lower_wilson": round(ci.lower, 6),
                        "ci_upper_wilson": round(ci.upper, 6),
                        "data_source": "literature_1000G_gnomAD",
                        "snapshot_date": snapshot_date,
                    }
                )
            if lit_rows:
                df = pd.concat([df, pd.DataFrame(lit_rows)], ignore_index=True)
                logger.info(
                    "NUDT15/PUR: replaced VCF-proxy rows (AF=0) with HWE imputation from "
                    "published rs116855232 AF=%.3f (literature_1000G_gnomAD)",
                    af,
                )

    logger.info("gold/phenotype_distribution_by_population: %d rows", len(df))
    return df


# ── Gold 3: drug_impact_summary ───────────────────────────────────────────────


def build_drug_impact_summary(
    phenotype_df: pd.DataFrame,
    drug_recommendations_df: pd.DataFrame,
    snapshot_date: date,
) -> pd.DataFrame:
    """Compute per-drug x population impact from phenotype distributions.

    Joins phenotype_distribution with drug_recommendations to count individuals
    whose inferred phenotype requires a dose change or alternative therapy.

    Args:
        phenotype_df: gold/phenotype_distribution_by_population DataFrame.
        drug_recommendations_df: silver/drug_recommendations/ DataFrame.
        snapshot_date: Date written to snapshot_date column.

    Returns:
        DataFrame matching gold_pgx.drug_impact_summary schema.
    """
    if phenotype_df.empty or drug_recommendations_df.empty:
        logger.warning(
            "Phenotype distribution or drug recommendations empty"
            " — drug_impact_summary will be empty"
        )
        return pd.DataFrame()

    # Identify actionable phenotypes: those that require dose change OR alternative
    actionable_recs = drug_recommendations_df[
        drug_recommendations_df["requires_dose_change"]
        | drug_recommendations_df["requires_alternative"]
    ][
        [
            "gene_symbol",
            "drug_name",
            "phenotype",
            "classification_strength",
            "requires_dose_change",
            "requires_alternative",
        ]
    ].copy()
    actionable_recs["drug_name"] = actionable_recs["drug_name"].str.lower().str.strip()

    # Normalize phenotype column name: drug_recommendations uses "phenotype",
    # phenotype_distribution uses "phenotype_category"
    actionable_recs = actionable_recs.rename(columns={"phenotype": "phenotype_category"})

    merged = phenotype_df.merge(
        actionable_recs,
        on=["gene_symbol", "phenotype_category"],
        how="inner",
    )
    if merged.empty:
        logger.warning(
            "Phenotype x drug_recommendations join produced 0 rows. "
            "Phenotype category names may not align — check silver/drug_recommendations/ "
            "phenotype values vs gold phenotype categories."
        )
        return pd.DataFrame()

    impact = (
        merged.groupby(
            [
                "drug_name",
                "gene_symbol",
                "population_code",
                "population_total",
                "classification_strength",
            ]
        )
        .agg(individuals_requiring_change=("individual_count", "sum"))
        .reset_index()
    )
    impact["percentage_requiring_change"] = (
        impact["individuals_requiring_change"] / impact["population_total"] * 100
    ).round(2)

    # CEU baseline
    ceu_baseline = impact[impact["population_code"] == "CEU"][
        ["drug_name", "gene_symbol", "percentage_requiring_change"]
    ].rename(columns={"percentage_requiring_change": "baseline_ceu_percentage"})
    impact = impact.merge(ceu_baseline, on=["drug_name", "gene_symbol"], how="left")
    impact["baseline_ceu_percentage"] = impact["baseline_ceu_percentage"].fillna(0.0)
    impact["delta_vs_baseline"] = (
        impact["percentage_requiring_change"] - impact["baseline_ceu_percentage"]
    ).round(2)
    impact["snapshot_date"] = snapshot_date

    result = impact[
        [
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
    ]
    logger.info("gold/drug_impact_summary: %d rows", len(result))
    return result


# ── Gold 4: actionability_ranking ─────────────────────────────────────────────

_STRENGTH_WEIGHT = {"Strong": 1.0, "Moderate": 0.7, "Optional": 0.3}


def build_actionability_ranking(
    drug_impact_df: pd.DataFrame,
    snapshot_date: date,
    top_n: int = _ACTIONABILITY_RANKING_TOP_N,
) -> pd.DataFrame:
    """Rank drug-gene-population combinations by actionable impact divergence.

    Score = |delta_vs_baseline| x classification_weight x population_affected_pct.
    Only non-CEU populations are ranked (CEU is the baseline).

    Args:
        drug_impact_df: gold/drug_impact_summary DataFrame.
        snapshot_date: Date written to snapshot_date column.
        top_n: Maximum rows in the output. Default: 50.

    Returns:
        DataFrame matching gold_pgx.actionability_ranking schema.
    """
    if drug_impact_df.empty:
        logger.warning("drug_impact_summary is empty — actionability_ranking will be empty")
        return pd.DataFrame()

    latam_df = drug_impact_df[drug_impact_df["population_code"] != "CEU"].copy()
    if latam_df.empty:
        logger.warning("No non-CEU population rows in drug_impact_summary")
        return pd.DataFrame()

    latam_df["_weight"] = latam_df["classification_strength"].map(_STRENGTH_WEIGHT).fillna(0.3)
    latam_df["_score"] = (
        latam_df["delta_vs_baseline"].abs()
        * latam_df["_weight"]
        * latam_df["percentage_requiring_change"]
    )

    ranked = latam_df.sort_values("_score", ascending=False).head(top_n).copy()
    ranked["rank_position"] = range(1, len(ranked) + 1)

    def _clinical_implication(row: pd.Series) -> str:
        delta = row["delta_vs_baseline"]
        direction = "higher" if delta > 0 else "lower"
        return (
            f"{abs(delta):.1f}pp {direction} rate of dose/therapy change vs CEU "
            f"in {row['population_code']} for {row['drug_name']} "
            f"({row['gene_symbol']}, CPIC {row['classification_strength']})"
        )

    ranked["clinical_implication"] = ranked.apply(_clinical_implication, axis=1)
    ranked["population_affected_pct"] = ranked["percentage_requiring_change"]
    ranked["snapshot_date"] = snapshot_date

    result = ranked[
        [
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
    ].reset_index(drop=True)

    logger.info(
        "gold/actionability_ranking: %d rows (top %d by impact score)",
        len(result),
        top_n,
    )
    return result


# ── Orchestrator ──────────────────────────────────────────────────────────────


def run(settings: Settings | None = None, snapshot_date: date | None = None) -> None:
    """Build all four gold tables from silver data.

    Args:
        settings: Application settings. Defaults to ``get_settings()``.
        snapshot_date: Date stamped on all gold rows. Defaults to today.
    """
    cfg = settings or get_settings()
    snap = snapshot_date or datetime.utcnow().date()

    logger.info("=== gold_aggregates: reading silver tables ===")
    variants_df = read_silver_table(cfg.silver_root / "variants")
    populations_df = read_silver_table(cfg.silver_root / "populations")
    clinical_variants_df = read_silver_table(cfg.silver_root / "clinical_variants")
    drug_recommendations_df = read_silver_table(cfg.silver_root / "drug_recommendations")

    logger.info("=== gold_aggregates: allele frequencies ===")
    af_df = build_allele_frequencies(variants_df, clinical_variants_df, snap)
    write_silver_table(af_df, cfg.gold_root / "allele_frequencies_by_population")

    logger.info("=== gold_aggregates: phenotype distribution ===")
    pheno_df = build_phenotype_distribution(variants_df, populations_df, snap)
    write_silver_table(pheno_df, cfg.gold_root / "phenotype_distribution_by_population")

    logger.info("=== gold_aggregates: drug impact summary ===")
    impact_df = build_drug_impact_summary(pheno_df, drug_recommendations_df, snap)
    write_silver_table(impact_df, cfg.gold_root / "drug_impact_summary")

    logger.info("=== gold_aggregates: actionability ranking ===")
    ranking_df = build_actionability_ranking(impact_df, snap)
    write_silver_table(ranking_df, cfg.gold_root / "actionability_ranking")

    logger.info("gold_aggregates complete — snapshot_date=%s", snap.isoformat())


def main() -> None:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s — %(message)s",
    )
    run()
    print("  ✓ gold/allele_frequencies_by_population/")
    print("  ✓ gold/phenotype_distribution_by_population/")
    print("  ✓ gold/drug_impact_summary/")
    print("  ✓ gold/actionability_ranking/")


if __name__ == "__main__":
    main()
