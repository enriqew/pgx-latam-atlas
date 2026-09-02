"""Unit tests for silver transformation logic — no file I/O, no network calls."""

from __future__ import annotations

import pandas as pd

from pgx_latam.transformations.silver_clinical import (
    _classify_recommendation,
    build_clinical_variants,
    build_drug_recommendations,
)
from pgx_latam.transformations.silver_variants import (
    TARGET_POPULATIONS,
    assign_gene_symbols,
    build_pharmacogenes,
    build_populations,
)

# ── assign_gene_symbols ───────────────────────────────────────────────────────


class TestAssignGeneSymbols:
    def test_cyp2c19_assigned_from_chr10_coordinates(self) -> None:
        chrom = pd.Series(["chr10"])
        pos = pd.Series([96_570_000])  # inside CYP2C19
        result = assign_gene_symbols(chrom, pos)
        assert result.iloc[0] == "CYP2C19"

    def test_cyp2c9_assigned_from_chr10_different_region(self) -> None:
        chrom = pd.Series(["chr10"])
        pos = pd.Series([96_720_000])  # inside CYP2C9
        result = assign_gene_symbols(chrom, pos)
        assert result.iloc[0] == "CYP2C9"

    def test_cyp2c19_and_cyp2c9_do_not_overlap(self) -> None:
        # Both on chr10 — must map to different genes
        chrom = pd.Series(["chr10", "chr10"])
        pos = pd.Series([96_570_000, 96_720_000])
        result = assign_gene_symbols(chrom, pos)
        assert result.iloc[0] == "CYP2C19"
        assert result.iloc[1] == "CYP2C9"
        assert result.iloc[0] != result.iloc[1]

    def test_g6pd_on_chrx(self) -> None:
        chrom = pd.Series(["chrX"])
        pos = pd.Series([153_780_000])
        result = assign_gene_symbols(chrom, pos)
        assert result.iloc[0] == "G6PD"

    def test_intergenic_variant_returns_na(self) -> None:
        chrom = pd.Series(["chr1"])
        pos = pd.Series([1_000_000])  # nowhere near any pharmacogene
        result = assign_gene_symbols(chrom, pos)
        assert pd.isna(result.iloc[0])

    def test_wrong_chromosome_returns_na(self) -> None:
        chrom = pd.Series(["chr1"])
        pos = pd.Series([96_570_000])  # CYP2C19 position but wrong chromosome
        result = assign_gene_symbols(chrom, pos)
        assert pd.isna(result.iloc[0])

    def test_vectorised_multiple_rows(self) -> None:
        chrom = pd.Series(["chr10", "chr12", "chr1", "chrX", "chr99"])
        pos = pd.Series([96_570_000, 21_340_000, 97_900_000, 153_780_000, 1])
        result = assign_gene_symbols(chrom, pos)
        assert result.iloc[0] == "CYP2C19"
        assert result.iloc[1] == "SLCO1B1"
        assert result.iloc[2] == "DPYD"
        assert result.iloc[3] == "G6PD"
        assert pd.isna(result.iloc[4])

    def test_all_in_scope_genes_have_region_and_are_assignable(self) -> None:
        from pgx_latam.ingestion.thousand_genomes import GENE_REGIONS_GRCH37
        from pgx_latam.utils.star_allele_scope import in_scope_symbols

        for gene in in_scope_symbols():
            assert gene in GENE_REGIONS_GRCH37, f"{gene} missing from GENE_REGIONS_GRCH37"
            region = GENE_REGIONS_GRCH37[gene]
            mid = (region.start + region.end) // 2
            chrom = pd.Series([f"chr{region.chromosome}"])
            pos = pd.Series([mid])
            result = assign_gene_symbols(chrom, pos)
            assert result.iloc[0] == gene, (
                f"Midpoint of {gene} (chr{region.chromosome}:{mid}) did not assign back to {gene}"
            )


# ── build_populations ─────────────────────────────────────────────────────────


class TestBuildPopulations:
    def _sample_df(self) -> pd.DataFrame:
        return pd.DataFrame(
            {
                "sample_id": [f"S{i}" for i in range(10)],
                "population_code": ["MXL"] * 4 + ["PEL"] * 3 + ["CEU"] * 3,
                "superpopulation": ["AMR"] * 7 + ["EUR"] * 3,
                "sex": ["female"] * 10,
                "family_id": [pd.NA] * 10,
            }
        )

    def test_sample_sizes_are_correct(self) -> None:
        df = build_populations(self._sample_df())
        mxl = df[df["population_code"] == "MXL"]["sample_size"].iloc[0]
        assert mxl == 4

    def test_all_target_populations_present(self) -> None:
        df = build_populations(self._sample_df())
        assert set(df["population_code"]) == {"MXL", "PEL", "CEU"}

    def test_population_names_are_not_empty(self) -> None:
        df = build_populations(self._sample_df())
        assert df["population_name"].notna().all()
        assert (df["population_name"] != "").all()

    def test_region_column_is_populated(self) -> None:
        df = build_populations(self._sample_df())
        latam = df[df["population_code"] == "MXL"]["region"].iloc[0]
        assert "Latin America" in latam

    def test_panel_populations_are_kept(self) -> None:
        """GBR and FIN joined the panel when the atlas went from LATAM to all 26 cohorts."""
        df_extra = pd.DataFrame(
            {
                "sample_id": ["X1", "X2"],
                "population_code": ["GBR", "FIN"],
                "superpopulation": ["EUR", "EUR"],
                "sex": ["male", "female"],
                "family_id": [pd.NA, pd.NA],
            }
        )
        result = build_populations(pd.concat([self._sample_df(), df_extra]))
        assert "GBR" in result["population_code"].values
        assert "FIN" in result["population_code"].values

    def test_codes_outside_the_panel_are_excluded(self) -> None:
        df_extra = pd.DataFrame(
            {
                "sample_id": ["X1", "X2"],
                "population_code": ["ZZZ", "QQQ"],
                "superpopulation": ["EUR", "AFR"],
                "sex": ["male", "female"],
                "family_id": [pd.NA, pd.NA],
            }
        )
        result = build_populations(pd.concat([self._sample_df(), df_extra]))
        assert "ZZZ" not in result["population_code"].values
        assert "QQQ" not in result["population_code"].values

    def test_target_panel_covers_all_26_cohorts(self) -> None:
        assert len(TARGET_POPULATIONS) == 26


# ── build_pharmacogenes ───────────────────────────────────────────────────────


class TestBuildPharmacogenes:
    def _genes_df(self) -> pd.DataFrame:
        return pd.DataFrame(
            {
                "pharmgkb_gene_id": ["PA124", "PA131", "PA162"],
                "gene_symbol": ["CYP2C19", "CYP2D6", "UNKNOWNGENE"],
                "ensembl_id": ["ENSG00000165841", "ENSG00000100197", "ENSG99999"],
                "ncbi_gene_id": ["1557", "1565", "9999"],
                "chromosome": ["chr10", "chr22", "chr1"],
                "chromosomal_start": [96_522_463, 42_522_500, 1_000_000],
                "chromosomal_end": [96_612_671, 42_540_000, 1_100_000],
            }
        )

    def test_in_scope_gene_present(self) -> None:
        df = build_pharmacogenes(self._genes_df())
        assert "CYP2C19" in df["gene_symbol"].values

    def test_cyp2d6_included_as_out_of_scope(self) -> None:
        df = build_pharmacogenes(self._genes_df())
        cyp2d6 = df[df["gene_symbol"] == "CYP2D6"]
        assert len(cyp2d6) == 1
        assert not cyp2d6["is_in_scope"].iloc[0]

    def test_unknown_gene_excluded(self) -> None:
        df = build_pharmacogenes(self._genes_df())
        assert "UNKNOWNGENE" not in df["gene_symbol"].values

    def test_is_in_scope_is_true_for_cyp2c19(self) -> None:
        df = build_pharmacogenes(self._genes_df())
        cyp2c19 = df[df["gene_symbol"] == "CYP2C19"]
        assert cyp2c19["is_in_scope"].iloc[0]

    def test_scope_rationale_is_not_empty(self) -> None:
        df = build_pharmacogenes(self._genes_df())
        assert df["scope_rationale"].notna().all()
        assert (df["scope_rationale"] != "").all()


# ── _classify_recommendation ──────────────────────────────────────────────────


class TestClassifyRecommendation:
    def test_avoid_triggers_alternative_flag(self) -> None:
        _change, alt = _classify_recommendation("Avoid use in poor metabolizers.", "Strong")
        assert alt

    def test_reduce_dose_triggers_dose_change_flag(self) -> None:
        change, _alt = _classify_recommendation(
            "Reduce dose by 50% for intermediate metabolizers.", "Strong"
        )
        assert change

    def test_no_recommendation_returns_both_false(self) -> None:
        change, alt = _classify_recommendation(
            "Reduce dose or use alternative drug.", "No recommendation"
        )
        assert not change
        assert not alt

    def test_empty_strength_returns_both_false(self) -> None:
        change, alt = _classify_recommendation("Reduce dose.", "")
        assert not change
        assert not alt

    def test_normal_metabolizer_no_action_needed(self) -> None:
        change, alt = _classify_recommendation("Standard dosing is appropriate.", "Strong")
        assert not change
        assert not alt

    def test_both_flags_can_be_true(self) -> None:
        change, alt = _classify_recommendation(
            "If poor metabolizer: reduce dose or consider alternative therapy.", "Strong"
        )
        assert change
        assert alt

    def test_case_insensitive_matching(self) -> None:
        _change, alt = _classify_recommendation("AVOID USE IN POOR METABOLIZERS.", "Strong")
        assert alt

    def test_titration_triggers_dose_change(self) -> None:
        change, _alt = _classify_recommendation("Titrate carefully based on response.", "Moderate")
        assert change


# ── build_clinical_variants ───────────────────────────────────────────────────


class TestBuildClinicalVariants:
    def _clinical_df(self) -> pd.DataFrame:
        return pd.DataFrame(
            {
                "clinical_annotation_id": ["CA001", "CA002", "CA003"],
                "variant_or_haplotype": ["rs4244285", "CYP2C19*2", "rs1057910"],
                "gene_symbol": ["CYP2C19", "CYP2C19", "CYP2C9"],
                "drug_names": ["clopidogrel", "omeprazole", "warfarin"],
                "phenotype_categories": ["Metabolism", "Metabolism", "Dosage"],
                "evidence_level": ["1A", "2B", "1B"],
                "clinical_annotation_types": ["Dosage", "Efficacy", "Dosage"],
                "pediatric": ["No", "No", "No"],
                "annotation_text": ["Text 1", "Text 2", "Text 3"],
            }
        )

    def test_produces_rows_for_in_scope_genes(self) -> None:
        df = build_clinical_variants(self._clinical_df(), pd.DataFrame())
        assert len(df) > 0
        assert all(g in {"CYP2C19", "CYP2C9"} for g in df["gene_symbol"])

    def test_is_actionable_for_level_1a_and_1b(self) -> None:
        df = build_clinical_variants(self._clinical_df(), pd.DataFrame())
        rs_1a = df[df["variant_rsid"] == "rs4244285"]
        assert rs_1a["is_actionable"].iloc[0]

    def test_is_not_actionable_for_level_2b(self) -> None:
        df = build_clinical_variants(self._clinical_df(), pd.DataFrame())
        star2 = df[df["variant_rsid"] == "CYP2C19*2"]
        assert not star2["is_actionable"].iloc[0]


# ── build_drug_recommendations ────────────────────────────────────────────────


class TestBuildDrugRecommendations:
    def _cpic_df(self) -> pd.DataFrame:
        return pd.DataFrame(
            {
                "guideline_id": ["PA166104938:1001", "PA166104938:1002"],
                "gene_symbol": ["CYP2C19", "CYP2C19"],
                "drug_name": ["clopidogrel", "clopidogrel"],
                "phenotype": ["Poor Metabolizer", "Normal Metabolizer"],
                "activity_score": ["0.0", "1.0"],
                "recommendation_text": [
                    "Avoid use. Select alternative antiplatelet therapy.",
                    "Standard dosing is appropriate.",
                ],
                "classification_strength": ["Strong", "Strong"],
                "cpic_release_version": ["v2.0", "v2.0"],
            }
        )

    def test_poor_metabolizer_flagged_as_requires_alternative(self) -> None:
        df = build_drug_recommendations(self._cpic_df())
        pm = df[df["phenotype"] == "Poor Metabolizer"]
        assert pm["requires_alternative"].iloc[0]

    def test_normal_metabolizer_no_flags(self) -> None:
        df = build_drug_recommendations(self._cpic_df())
        nm = df[df["phenotype"] == "Normal Metabolizer"]
        assert not nm["requires_dose_change"].iloc[0]
        assert not nm["requires_alternative"].iloc[0]

    def test_out_of_scope_gene_excluded(self) -> None:
        extra = pd.DataFrame(
            {
                "guideline_id": ["PA_X:1"],
                "gene_symbol": ["CYP2D6"],
                "drug_name": ["codeine"],
                "phenotype": ["Poor Metabolizer"],
                "activity_score": ["0.0"],
                "recommendation_text": ["Avoid use."],
                "classification_strength": ["Strong"],
                "cpic_release_version": ["v1.0"],
            }
        )
        df = build_drug_recommendations(pd.concat([self._cpic_df(), extra], ignore_index=True))
        assert "CYP2D6" not in df["gene_symbol"].values
