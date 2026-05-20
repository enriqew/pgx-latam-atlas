"""Unit tests for gold aggregation logic — no file I/O, no network calls."""

from __future__ import annotations

from datetime import date

import pandas as pd

from pgx_latam.transformations.gold_aggregates import (
    GENE_KEY_VARIANTS,
    _infer_phenotype,
    build_actionability_ranking,
    build_allele_frequencies,
    build_drug_impact_summary,
    build_phenotype_distribution,
)

_SNAP = date(2025, 1, 1)


# ── _infer_phenotype ──────────────────────────────────────────────────────────


class TestInferPhenotype:
    def test_standard_gene_normal_metabolizer(self) -> None:
        assert _infer_phenotype("CYP2C19", 0) == "Normal Metabolizer"

    def test_standard_gene_intermediate_metabolizer(self) -> None:
        assert _infer_phenotype("CYP2C9", 1) == "Intermediate Metabolizer"

    def test_standard_gene_poor_metabolizer(self) -> None:
        assert _infer_phenotype("TPMT", 2) == "Poor Metabolizer"

    def test_dosage_above_2_clamped_to_poor(self) -> None:
        assert _infer_phenotype("CYP2C19", 5) == "Poor Metabolizer"

    def test_ifnl3_favorable_genotype(self) -> None:
        assert _infer_phenotype("IFNL3", 0) == "Favorable Genotype"

    def test_ifnl3_intermediate_genotype(self) -> None:
        assert _infer_phenotype("IFNL3", 1) == "Intermediate Genotype"

    def test_ifnl3_unfavorable_genotype(self) -> None:
        assert _infer_phenotype("IFNL3", 2) == "Unfavorable Genotype"

    def test_g6pd_normal(self) -> None:
        assert _infer_phenotype("G6PD", 0) == "Normal"

    def test_g6pd_deficient_hemizygous(self) -> None:
        assert _infer_phenotype("G6PD", 1) == "Deficient"

    def test_g6pd_deficient_homozygous(self) -> None:
        assert _infer_phenotype("G6PD", 2) == "Deficient"

    def test_cyp3a5_normal_metabolizer_zero_nonfunc_alleles(self) -> None:
        assert _infer_phenotype("CYP3A5", 0) == "Normal Metabolizer"


class TestInferPhenotypeVKORC1:
    def test_normal_sensitivity_zero_dosage(self) -> None:
        assert _infer_phenotype("VKORC1", 0) == "Normal Sensitivity"

    def test_intermediate_sensitivity_one_dosage(self) -> None:
        assert _infer_phenotype("VKORC1", 1) == "Intermediate Sensitivity"

    def test_high_sensitivity_two_dosage(self) -> None:
        assert _infer_phenotype("VKORC1", 2) == "High Sensitivity"

    def test_dosage_above_2_clamped_to_high_sensitivity(self) -> None:
        assert _infer_phenotype("VKORC1", 3) == "High Sensitivity"


class TestInferPhenotypeCYP3A5:
    def test_normal_metabolizer_zero_nonfunc_alleles(self) -> None:
        assert _infer_phenotype("CYP3A5", 0) == "Normal Metabolizer"

    def test_intermediate_metabolizer_one_allele(self) -> None:
        assert _infer_phenotype("CYP3A5", 1) == "Intermediate Metabolizer"

    def test_poor_metabolizer_two_alleles(self) -> None:
        assert _infer_phenotype("CYP3A5", 2) == "Poor Metabolizer"

    def test_dosage_above_2_clamped_to_poor_metabolizer(self) -> None:
        assert _infer_phenotype("CYP3A5", 3) == "Poor Metabolizer"


class TestInferPhenotypeUGT1A9:
    def test_normal_metabolizer_zero_star3_alleles(self) -> None:
        assert _infer_phenotype("UGT1A9", 0) == "Normal Metabolizer"

    def test_intermediate_metabolizer_one_star3_allele(self) -> None:
        assert _infer_phenotype("UGT1A9", 1) == "Intermediate Metabolizer"

    def test_poor_metabolizer_two_star3_alleles(self) -> None:
        assert _infer_phenotype("UGT1A9", 2) == "Poor Metabolizer"

    def test_dosage_above_2_clamped_to_poor_metabolizer(self) -> None:
        assert _infer_phenotype("UGT1A9", 3) == "Poor Metabolizer"


# ── build_allele_frequencies ──────────────────────────────────────────────────


class TestBuildAlleleFrequencies:
    def _variants_df(self) -> pd.DataFrame:
        return pd.DataFrame(
            {
                "sample_id": ["S1", "S2", "S3", "S4"],
                "variant_id": ["rs4244285"] * 4,
                "gene_symbol": ["CYP2C19"] * 4,
                "chromosome": ["chr10"] * 4,
                "position": [96_570_000] * 4,
                "reference_allele": ["G"] * 4,
                "alternate_allele": ["A"] * 4,
                "allele_dosage": [2, 1, 0, 1],
                "population_code": ["MXL", "MXL", "CEU", "CEU"],
                "superpopulation": ["AMR", "AMR", "EUR", "EUR"],
            }
        )

    def _clinical_df(self) -> pd.DataFrame:
        return pd.DataFrame(
            {
                "variant_rsid": ["rs4244285"],
                "is_actionable": [True],
            }
        )

    def test_allele_frequency_computed_per_population(self) -> None:
        df = build_allele_frequencies(self._variants_df(), self._clinical_df(), _SNAP)
        mxl = df[df["population_code"] == "MXL"]
        # MXL: allele_count=3, total_alleles=4 → 0.75
        assert abs(mxl["allele_frequency"].iloc[0] - 0.75) < 1e-4

    def test_ceu_allele_frequency(self) -> None:
        df = build_allele_frequencies(self._variants_df(), self._clinical_df(), _SNAP)
        ceu = df[df["population_code"] == "CEU"]
        # CEU: allele_count=1, total_alleles=4 → 0.25
        assert abs(ceu["allele_frequency"].iloc[0] - 0.25) < 1e-4

    def test_delta_vs_ceu_mxl(self) -> None:
        df = build_allele_frequencies(self._variants_df(), self._clinical_df(), _SNAP)
        mxl = df[df["population_code"] == "MXL"]
        # MXL freq 0.75 - CEU freq 0.25 = 0.50
        assert abs(mxl["delta_vs_ceu"].iloc[0] - 0.50) < 1e-4

    def test_delta_vs_ceu_is_zero_for_ceu(self) -> None:
        df = build_allele_frequencies(self._variants_df(), self._clinical_df(), _SNAP)
        ceu = df[df["population_code"] == "CEU"]
        assert abs(ceu["delta_vs_ceu"].iloc[0]) < 1e-9

    def test_is_actionable_flag_set(self) -> None:
        df = build_allele_frequencies(self._variants_df(), self._clinical_df(), _SNAP)
        assert df["is_actionable"].all()

    def test_wilson_ci_bounds_present_and_valid(self) -> None:
        df = build_allele_frequencies(self._variants_df(), self._clinical_df(), _SNAP)
        assert (df["ci_lower_wilson"] >= 0).all()
        assert (df["ci_upper_wilson"] <= 1).all()
        assert (df["ci_lower_wilson"] <= df["allele_frequency"]).all()
        assert (df["ci_upper_wilson"] >= df["allele_frequency"]).all()

    def test_snapshot_date_column(self) -> None:
        df = build_allele_frequencies(self._variants_df(), self._clinical_df(), _SNAP)
        assert (df["snapshot_date"] == _SNAP).all()

    def test_empty_variants_returns_empty(self) -> None:
        df = build_allele_frequencies(pd.DataFrame(), pd.DataFrame(), _SNAP)
        assert df.empty


# ── build_phenotype_distribution ──────────────────────────────────────────────


class TestBuildPhenotypeDistribution:
    def _variants_df(self) -> pd.DataFrame:
        key_rsid = GENE_KEY_VARIANTS["CYP2C19"][0]
        return pd.DataFrame(
            {
                "sample_id": [f"S{i}" for i in range(6)],
                "variant_id": [key_rsid] * 6,
                "gene_symbol": ["CYP2C19"] * 6,
                "allele_dosage": [0, 2, 1, 1, 2, 0],  # MXL: NM, PM, IM; CEU: IM, PM, NM
                "population_code": ["MXL"] * 3 + ["CEU"] * 3,
                "superpopulation": ["AMR"] * 3 + ["EUR"] * 3,
            }
        )

    def _populations_df(self) -> pd.DataFrame:
        return pd.DataFrame(
            {
                "population_code": ["MXL", "CEU"],
                "sample_size": [3, 3],
                "population_name": ["Mexican Ancestry", "Utah Residents"],
                "region": ["Latin America", "Europe"],
            }
        )

    def test_phenotype_categories_inferred(self) -> None:
        df = build_phenotype_distribution(self._variants_df(), self._populations_df(), _SNAP)
        categories = set(df["phenotype_category"].unique())
        assert "Normal Metabolizer" in categories
        assert "Intermediate Metabolizer" in categories
        assert "Poor Metabolizer" in categories

    def test_mxl_poor_metabolizer_count(self) -> None:
        df = build_phenotype_distribution(self._variants_df(), self._populations_df(), _SNAP)
        mxl_pm = df[
            (df["population_code"] == "MXL") & (df["phenotype_category"] == "Poor Metabolizer")
        ]
        assert mxl_pm["individual_count"].iloc[0] == 1

    def test_population_total_from_populations_df(self) -> None:
        df = build_phenotype_distribution(self._variants_df(), self._populations_df(), _SNAP)
        # population_total should come from populations_df sample_size (3 for MXL)
        mxl = df[df["population_code"] == "MXL"]
        assert (mxl["population_total"] == 3).all()

    def test_phenotype_percentage_in_range(self) -> None:
        df = build_phenotype_distribution(self._variants_df(), self._populations_df(), _SNAP)
        assert (df["phenotype_percentage"] >= 0).all()
        assert (df["phenotype_percentage"] <= 100).all()

    def test_wilson_ci_present(self) -> None:
        df = build_phenotype_distribution(self._variants_df(), self._populations_df(), _SNAP)
        assert "ci_lower_wilson" in df.columns
        assert "ci_upper_wilson" in df.columns

    def test_empty_variants_returns_empty(self) -> None:
        df = build_phenotype_distribution(pd.DataFrame(), self._populations_df(), _SNAP)
        assert df.empty

    def test_gene_without_key_variants_skipped(self) -> None:
        fake_df = pd.DataFrame(
            {
                "sample_id": ["S1"],
                "variant_id": ["rs9999999"],
                "gene_symbol": ["UNKNOWNGENE"],
                "allele_dosage": [1],
                "population_code": ["MXL"],
                "superpopulation": ["AMR"],
            }
        )
        df = build_phenotype_distribution(fake_df, self._populations_df(), _SNAP)
        assert df.empty or "UNKNOWNGENE" not in df.get("gene_symbol", pd.Series()).values


# ── build_drug_impact_summary ─────────────────────────────────────────────────


class TestBuildDrugImpactSummary:
    def _pheno_df(self) -> pd.DataFrame:
        return pd.DataFrame(
            {
                "gene_symbol": ["CYP2C19", "CYP2C19", "CYP2C19", "CYP2C19"],
                "population_code": ["MXL", "MXL", "CEU", "CEU"],
                "superpopulation": ["AMR", "AMR", "EUR", "EUR"],
                "phenotype_category": [
                    "Poor Metabolizer",
                    "Normal Metabolizer",
                    "Poor Metabolizer",
                    "Normal Metabolizer",
                ],
                "individual_count": [10, 40, 5, 45],
                "population_total": [50, 50, 50, 50],
                "phenotype_percentage": [20.0, 80.0, 10.0, 90.0],
                "ci_lower_wilson": [0.10, 0.67, 0.04, 0.78],
                "ci_upper_wilson": [0.33, 0.90, 0.20, 0.97],
                "snapshot_date": [date(2025, 1, 1)] * 4,
            }
        )

    def _drug_recs_df(self) -> pd.DataFrame:
        return pd.DataFrame(
            {
                "gene_symbol": ["CYP2C19", "CYP2C19"],
                "drug_name": ["clopidogrel", "clopidogrel"],
                "phenotype": ["Poor Metabolizer", "Normal Metabolizer"],
                "classification_strength": ["Strong", "Strong"],
                "requires_dose_change": [False, False],
                "requires_alternative": [True, False],
            }
        )

    def test_mxl_individuals_requiring_change(self) -> None:
        df = build_drug_impact_summary(self._pheno_df(), self._drug_recs_df(), _SNAP)
        mxl = df[df["population_code"] == "MXL"]
        assert mxl["individuals_requiring_change"].iloc[0] == 10

    def test_delta_vs_baseline_mxl_higher_than_ceu(self) -> None:
        df = build_drug_impact_summary(self._pheno_df(), self._drug_recs_df(), _SNAP)
        mxl = df[df["population_code"] == "MXL"]
        assert mxl["delta_vs_baseline"].iloc[0] > 0  # MXL 20% > CEU 10%

    def test_ceu_delta_is_zero(self) -> None:
        df = build_drug_impact_summary(self._pheno_df(), self._drug_recs_df(), _SNAP)
        ceu = df[df["population_code"] == "CEU"]
        assert abs(ceu["delta_vs_baseline"].iloc[0]) < 1e-6

    def test_normal_metabolizer_not_in_output(self) -> None:
        # Only actionable phenotypes (Poor Metabolizer requires_alternative=True) appear
        df = build_drug_impact_summary(self._pheno_df(), self._drug_recs_df(), _SNAP)
        # "Normal Metabolizer" has requires_alternative=False, requires_dose_change=False
        # so it should be filtered out of actionable_recs join
        assert len(df) == 2  # MXL + CEU for Poor Metabolizer only

    def test_snapshot_date_column(self) -> None:
        df = build_drug_impact_summary(self._pheno_df(), self._drug_recs_df(), _SNAP)
        assert (df["snapshot_date"] == _SNAP).all()

    def test_empty_pheno_returns_empty(self) -> None:
        df = build_drug_impact_summary(pd.DataFrame(), self._drug_recs_df(), _SNAP)
        assert df.empty

    def test_empty_recs_returns_empty(self) -> None:
        df = build_drug_impact_summary(self._pheno_df(), pd.DataFrame(), _SNAP)
        assert df.empty


# ── build_actionability_ranking ───────────────────────────────────────────────


class TestBuildActionabilityRanking:
    def _impact_df(self) -> pd.DataFrame:
        return pd.DataFrame(
            {
                "drug_name": ["clopidogrel", "clopidogrel", "warfarin", "warfarin"],
                "gene_symbol": ["CYP2C19", "CYP2C19", "CYP2C9", "CYP2C9"],
                "population_code": ["MXL", "CEU", "PEL", "CEU"],
                "population_total": [50, 50, 40, 50],
                "individuals_requiring_change": [10, 5, 12, 4],
                "percentage_requiring_change": [20.0, 10.0, 30.0, 8.0],
                "baseline_ceu_percentage": [10.0, 10.0, 8.0, 8.0],
                "delta_vs_baseline": [10.0, 0.0, 22.0, 0.0],
                "classification_strength": ["Strong", "Strong", "Strong", "Strong"],
                "snapshot_date": [date(2025, 1, 1)] * 4,
            }
        )

    def test_ceu_excluded_from_ranking(self) -> None:
        df = build_actionability_ranking(self._impact_df(), _SNAP)
        assert "CEU" not in df["population_code"].values

    def test_higher_delta_ranks_first(self) -> None:
        df = build_actionability_ranking(self._impact_df(), _SNAP)
        # PEL delta=22 (warfarin) should score higher than MXL delta=10 (clopidogrel)
        assert df.iloc[0]["population_code"] == "PEL"
        assert df.iloc[0]["drug_name"] == "warfarin"

    def test_rank_positions_are_sequential(self) -> None:
        df = build_actionability_ranking(self._impact_df(), _SNAP)
        expected = list(range(1, len(df) + 1))
        assert list(df["rank_position"]) == expected

    def test_clinical_implication_contains_drug_name(self) -> None:
        df = build_actionability_ranking(self._impact_df(), _SNAP)
        for _, row in df.iterrows():
            assert row["drug_name"] in row["clinical_implication"]

    def test_clinical_implication_contains_population(self) -> None:
        df = build_actionability_ranking(self._impact_df(), _SNAP)
        for _, row in df.iterrows():
            assert row["population_code"] in row["clinical_implication"]

    def test_top_n_respected(self) -> None:
        df = build_actionability_ranking(self._impact_df(), _SNAP, top_n=1)
        assert len(df) == 1

    def test_snapshot_date_column(self) -> None:
        df = build_actionability_ranking(self._impact_df(), _SNAP)
        assert (df["snapshot_date"] == _SNAP).all()

    def test_empty_impact_returns_empty(self) -> None:
        df = build_actionability_ranking(pd.DataFrame(), _SNAP)
        assert df.empty

    def test_all_ceu_returns_empty(self) -> None:
        ceu_only = self._impact_df()[self._impact_df()["population_code"] == "CEU"].copy()
        df = build_actionability_ranking(ceu_only, _SNAP)
        assert df.empty

    def test_output_columns_present(self) -> None:
        df = build_actionability_ranking(self._impact_df(), _SNAP)
        expected_cols = {
            "rank_position",
            "drug_name",
            "gene_symbol",
            "population_code",
            "delta_vs_baseline",
            "population_affected_pct",
            "classification_strength",
            "clinical_implication",
            "snapshot_date",
        }
        assert expected_cols.issubset(set(df.columns))
