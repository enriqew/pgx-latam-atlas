"""Unit tests for gold aggregation logic — no file I/O, no network calls."""

from __future__ import annotations

from datetime import date

import pandas as pd

from pgx_latam.transformations.gold_aggregates import (
    GENE_KEY_VARIANTS,
    REFERENCE_IS_NONFUNCTIONAL,
    _infer_phenotype,
    build_actionability_ranking,
    build_allele_frequencies,
    build_combined_warfarin_impact,
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
    """Dosage here is *3 (non-expresser) copies, already inverted from the VCF alternate.

    See TestCYP3A5ReferenceInversion for the inversion itself.
    """

    def test_normal_metabolizer_zero_nonfunc_alleles(self) -> None:
        assert _infer_phenotype("CYP3A5", 0) == "Normal Metabolizer"

    def test_intermediate_metabolizer_one_allele(self) -> None:
        assert _infer_phenotype("CYP3A5", 1) == "Intermediate Metabolizer"

    def test_poor_metabolizer_two_alleles(self) -> None:
        assert _infer_phenotype("CYP3A5", 2) == "Poor Metabolizer"

    def test_dosage_above_2_clamped_to_poor_metabolizer(self) -> None:
        assert _infer_phenotype("CYP3A5", 3) == "Poor Metabolizer"


class TestInferPhenotypeSLCO1B1:
    def test_normal_function_zero_nonfunc_alleles(self) -> None:
        assert _infer_phenotype("SLCO1B1", 0) == "Normal Function"

    def test_decreased_function_one_star5_allele(self) -> None:
        # *1a/*5 heterozygote: reduced OATP1B1 transport → Decreased Function
        assert _infer_phenotype("SLCO1B1", 1) == "Decreased Function"

    def test_poor_function_two_star5_alleles(self) -> None:
        assert _infer_phenotype("SLCO1B1", 2) == "Poor Function"

    def test_dosage_above_2_clamped_to_poor_function(self) -> None:
        assert _infer_phenotype("SLCO1B1", 3) == "Poor Function"

    def test_key_variant_is_corrected_position(self) -> None:
        # chr12:21331546 was monomorphic (AF=0) in all 1000G Phase 3 cohorts.
        # The correct rs4149056 position is chr12:21331549 (T>C, c.521T>C).
        assert GENE_KEY_VARIANTS["SLCO1B1"] == ("chr12:21331549",)


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


class TestCYP3A5ReferenceInversion:
    """CYP3A5 is the one gene whose reference allele is the non-functional star allele.

    At rs776746 (chr7:99270539, GRCh37) REF=C is *3 and ALT=T is *1, so the VCF
    alternate dosage counts functional copies and has to be inverted.  Before this was
    handled the pipeline reported every population, African cohorts included, as 85-99%
    Poor Metabolizer.
    """

    def _variants_df(self) -> pd.DataFrame:
        key = GENE_KEY_VARIANTS["CYP3A5"][0]
        return pd.DataFrame(
            {
                "sample_id": ["S0", "S1", "S2"],
                "variant_id": [key] * 3,
                "gene_symbol": ["CYP3A5"] * 3,
                # ALT dosage = *1 copies: 2 = *1/*1 expresser, 1 = *1/*3, 0 = *3/*3
                "allele_dosage": [2, 1, 0],
                "population_code": ["YRI"] * 3,
                "superpopulation": ["AFR"] * 3,
            }
        )

    def _populations_df(self) -> pd.DataFrame:
        return pd.DataFrame(
            {
                "population_code": ["YRI"],
                "sample_size": [3],
                "population_name": ["Yoruba"],
                "region": ["Africa"],
            }
        )

    def test_key_variant_is_rs776746_not_the_near_fixed_indel(self) -> None:
        assert GENE_KEY_VARIANTS["CYP3A5"] == ("chr7:99270539",)

    def test_cyp3a5_is_flagged_as_reference_nonfunctional(self) -> None:
        assert "CYP3A5" in REFERENCE_IS_NONFUNCTIONAL

    def test_two_alternate_copies_are_a_normal_metabolizer(self) -> None:
        df = build_phenotype_distribution(self._variants_df(), self._populations_df(), _SNAP)
        row = df[df["phenotype_category"] == "Normal Metabolizer"]
        assert row["individual_count"].iloc[0] == 1

    def test_zero_alternate_copies_are_a_poor_metabolizer(self) -> None:
        df = build_phenotype_distribution(self._variants_df(), self._populations_df(), _SNAP)
        row = df[df["phenotype_category"] == "Poor Metabolizer"]
        assert row["individual_count"].iloc[0] == 1

    def test_one_alternate_copy_is_intermediate(self) -> None:
        df = build_phenotype_distribution(self._variants_df(), self._populations_df(), _SNAP)
        row = df[df["phenotype_category"] == "Intermediate Metabolizer"]
        assert row["individual_count"].iloc[0] == 1

    def test_other_genes_are_not_inverted(self) -> None:
        key = GENE_KEY_VARIANTS["CYP2C19"][0]
        variants = pd.DataFrame(
            {
                "sample_id": ["S0"],
                "variant_id": [key],
                "gene_symbol": ["CYP2C19"],
                "allele_dosage": [0],
                "population_code": ["YRI"],
                "superpopulation": ["AFR"],
            }
        )
        df = build_phenotype_distribution(variants, self._populations_df(), _SNAP)
        assert df["phenotype_category"].iloc[0] == "Normal Metabolizer"


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
        # top_n=1 but 2 distinct genes → guaranteed one row per gene → 2 rows total.
        # The per-gene guarantee takes precedence over top_n when n_genes > top_n.
        df = build_actionability_ranking(self._impact_df(), _SNAP, top_n=1)
        n_genes = self._impact_df()[self._impact_df()["population_code"] != "CEU"][
            "gene_symbol"
        ].nunique()
        assert len(df) == n_genes

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


# ── build_combined_warfarin_impact ────────────────────────────────────────────


class TestBuildCombinedWarfarinImpact:
    """Warfarin is the one drug scored on a joint VKORC1 + CYP2C9 phenotype.

    Dose category comes from the CPIC joint table, and anything that is not
    "standard" counts as requiring a dose change.
    """

    _VKORC1_KEY = GENE_KEY_VARIANTS["VKORC1"][0]
    _CYP2C9_KEY = GENE_KEY_VARIANTS["CYP2C9"][0]

    def _variants_df(self) -> pd.DataFrame:
        # CEU_1  VKORC1 0 + CYP2C9 0  -> (Normal Sensitivity, Normal Metabolizer)  standard
        # CEU_2  VKORC1 2 + CYP2C9 0  -> (High Sensitivity, Normal Metabolizer)    low
        # PEL_1  VKORC1 2 + CYP2C9 2  -> (High Sensitivity, Poor Metabolizer)      low
        # PEL_2  VKORC1 1 + CYP2C9 1  -> (Intermediate Sensitivity, Intermediate)  low
        samples = [
            ("CEU_1", "CEU", "EUR", 0, 0),
            ("CEU_2", "CEU", "EUR", 2, 0),
            ("PEL_1", "PEL", "AMR", 2, 2),
            ("PEL_2", "PEL", "AMR", 1, 1),
        ]
        rows = []
        for sample_id, pop, superpop, vk_dosage, cyp_dosage in samples:
            rows.append(
                {
                    "sample_id": sample_id,
                    "population_code": pop,
                    "superpopulation": superpop,
                    "gene_symbol": "VKORC1",
                    "variant_id": self._VKORC1_KEY,
                    "allele_dosage": vk_dosage,
                }
            )
            rows.append(
                {
                    "sample_id": sample_id,
                    "population_code": pop,
                    "superpopulation": superpop,
                    "gene_symbol": "CYP2C9",
                    "variant_id": self._CYP2C9_KEY,
                    "allele_dosage": cyp_dosage,
                }
            )
        return pd.DataFrame(rows)

    def _populations_df(self) -> pd.DataFrame:
        return pd.DataFrame(
            {
                "population_code": ["CEU", "PEL"],
                "sample_size": [2, 2],
            }
        )

    def test_gene_symbol_and_drug_name(self) -> None:
        df = build_combined_warfarin_impact(self._variants_df(), self._populations_df(), _SNAP)
        assert set(df["gene_symbol"]) == {"VKORC1+CYP2C9"}
        assert set(df["drug_name"]) == {"warfarin"}

    def test_standard_dose_individuals_are_not_counted(self) -> None:
        df = build_combined_warfarin_impact(self._variants_df(), self._populations_df(), _SNAP)
        ceu = df[df["population_code"] == "CEU"].iloc[0]
        # CEU_1 is (Normal Sensitivity, Normal Metabolizer): standard dose, not counted.
        assert ceu["individuals_requiring_change"] == 1
        assert ceu["percentage_requiring_change"] == 50.0

    def test_every_non_standard_pair_is_counted(self) -> None:
        df = build_combined_warfarin_impact(self._variants_df(), self._populations_df(), _SNAP)
        pel = df[df["population_code"] == "PEL"].iloc[0]
        assert pel["individuals_requiring_change"] == 2
        assert pel["percentage_requiring_change"] == 100.0

    def test_delta_is_measured_against_the_ceu_baseline(self) -> None:
        df = build_combined_warfarin_impact(self._variants_df(), self._populations_df(), _SNAP)
        assert (df["baseline_ceu_percentage"] == 50.0).all()
        pel = df[df["population_code"] == "PEL"].iloc[0]
        ceu = df[df["population_code"] == "CEU"].iloc[0]
        assert pel["delta_vs_baseline"] == 50.0
        assert ceu["delta_vs_baseline"] == 0.0

    def test_population_total_comes_from_the_populations_table(self) -> None:
        """The denominator is the cohort size, not the number of genotyped samples."""
        populations = pd.DataFrame({"population_code": ["CEU", "PEL"], "sample_size": [10, 10]})
        df = build_combined_warfarin_impact(self._variants_df(), populations, _SNAP)
        pel = df[df["population_code"] == "PEL"].iloc[0]
        assert pel["population_total"] == 10
        assert pel["percentage_requiring_change"] == 20.0

    def test_schema_matches_drug_impact_summary(self) -> None:
        df = build_combined_warfarin_impact(self._variants_df(), self._populations_df(), _SNAP)
        assert list(df.columns) == [
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
        assert (df["snapshot_date"] == _SNAP).all()
        assert set(df["classification_strength"]) == {"Strong"}

    def test_missing_cyp2c9_returns_empty(self) -> None:
        variants = self._variants_df()
        vkorc1_only = variants[variants["gene_symbol"] == "VKORC1"]
        df = build_combined_warfarin_impact(vkorc1_only, self._populations_df(), _SNAP)
        assert df.empty

    def test_missing_vkorc1_returns_empty(self) -> None:
        variants = self._variants_df()
        cyp2c9_only = variants[variants["gene_symbol"] == "CYP2C9"]
        df = build_combined_warfarin_impact(cyp2c9_only, self._populations_df(), _SNAP)
        assert df.empty

    def test_non_key_variants_are_ignored(self) -> None:
        variants = self._variants_df().copy()
        variants.loc[variants["gene_symbol"] == "VKORC1", "variant_id"] = "chr16:99999999"
        df = build_combined_warfarin_impact(variants, self._populations_df(), _SNAP)
        assert df.empty

    def test_no_shared_samples_returns_empty(self) -> None:
        """VKORC1 and CYP2C9 genotyped on disjoint samples cannot be joined."""
        variants = self._variants_df()
        disjoint = pd.concat(
            [
                variants[
                    (variants["gene_symbol"] == "VKORC1")
                    & (variants["sample_id"].isin(["CEU_1", "PEL_1"]))
                ],
                variants[
                    (variants["gene_symbol"] == "CYP2C9")
                    & (variants["sample_id"].isin(["CEU_2", "PEL_2"]))
                ],
            ]
        )
        df = build_combined_warfarin_impact(disjoint, self._populations_df(), _SNAP)
        assert df.empty

    def test_population_with_zero_recorded_size_is_skipped(self) -> None:
        populations = pd.DataFrame({"population_code": ["CEU", "PEL"], "sample_size": [2, 0]})
        df = build_combined_warfarin_impact(self._variants_df(), populations, _SNAP)
        assert "PEL" not in df["population_code"].values
        assert "CEU" in df["population_code"].values
