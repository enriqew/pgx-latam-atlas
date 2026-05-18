"""Unit tests for bronze schema validation — no file I/O, no network calls."""

from __future__ import annotations

import pandas as pd
import pytest

from pgx_latam.utils.bronze_schemas import validate_bronze

# ── Helpers ───────────────────────────────────────────────────────────────────


def _genomes_variants_row(**overrides: object) -> dict[str, object]:
    base: dict[str, object] = {
        "chromosome": "chr10",
        "position": 96521657,
        "variant_id": "chr10:96521657",
        "reference_allele": "G",
        "alternate_allele": "A",
        "sample_id": "NA19648",
        "genotype": "0|1",
        "allele_dosage": 1,
        "quality": 99.0,
        "filter_status": "PASS",
        "info_payload": None,
    }
    base.update(overrides)
    return base


def _samples_metadata_row(**overrides: object) -> dict[str, object]:
    base: dict[str, object] = {
        "sample_id": "NA19648",
        "population_code": "MXL",
        "superpopulation": "AMR",
        "sex": "female",
        "family_id": None,
    }
    base.update(overrides)
    return base


def _cpic_row(**overrides: object) -> dict[str, object]:
    base: dict[str, object] = {
        "guideline_id": "PA166104938:1001",
        "gene_symbol": "CYP2C19",
        "drug_name": "clopidogrel",
        "recommendation_text": "Avoid use.",
        "phenotype": "Poor Metabolizer",
        "activity_score": "0.0",
        "classification_strength": "Strong",
        "cpic_release_version": "v2.0",
    }
    base.update(overrides)
    return base


# ── genomes_variants_raw ──────────────────────────────────────────────────────


class TestGenomesVariantsRaw:
    def test_valid_dataframe_passes(self) -> None:
        df = pd.DataFrame([_genomes_variants_row()])
        validate_bronze(df, "genomes_variants_raw")  # must not raise

    def test_missing_required_column_raises(self) -> None:
        df = pd.DataFrame([_genomes_variants_row()])
        df = df.drop(columns=["chromosome"])
        with pytest.raises(RuntimeError, match="missing required columns"):
            validate_bronze(df, "genomes_variants_raw")

    def test_error_names_missing_column(self) -> None:
        df = pd.DataFrame([_genomes_variants_row()])
        df = df.drop(columns=["sample_id", "genotype"])
        with pytest.raises(RuntimeError, match="sample_id"):
            validate_bronze(df, "genomes_variants_raw")

    def test_null_in_chromosome_raises(self) -> None:
        df = pd.DataFrame([_genomes_variants_row(chromosome=None)])
        with pytest.raises(RuntimeError, match="null value"):
            validate_bronze(df, "genomes_variants_raw")

    def test_null_in_variant_id_raises(self) -> None:
        df = pd.DataFrame([_genomes_variants_row(variant_id=None)])
        with pytest.raises(RuntimeError, match="null value"):
            validate_bronze(df, "genomes_variants_raw")

    def test_null_quality_allowed(self) -> None:
        df = pd.DataFrame([_genomes_variants_row(quality=None)])
        validate_bronze(df, "genomes_variants_raw")  # quality is nullable

    def test_null_info_payload_allowed(self) -> None:
        df = pd.DataFrame([_genomes_variants_row(info_payload=None)])
        validate_bronze(df, "genomes_variants_raw")

    def test_multiple_rows_one_bad_raises(self) -> None:
        rows = [_genomes_variants_row(), _genomes_variants_row(sample_id=None)]
        df = pd.DataFrame(rows)
        with pytest.raises(RuntimeError, match="null value"):
            validate_bronze(df, "genomes_variants_raw")


# ── samples_metadata_raw ──────────────────────────────────────────────────────


class TestSamplesMetadataRaw:
    def test_valid_dataframe_passes(self) -> None:
        df = pd.DataFrame([_samples_metadata_row()])
        validate_bronze(df, "samples_metadata_raw")

    def test_missing_population_code_raises(self) -> None:
        df = pd.DataFrame([_samples_metadata_row()])
        df = df.drop(columns=["population_code"])
        with pytest.raises(RuntimeError, match="missing required columns"):
            validate_bronze(df, "samples_metadata_raw")

    def test_null_sample_id_raises(self) -> None:
        df = pd.DataFrame([_samples_metadata_row(sample_id=None)])
        with pytest.raises(RuntimeError, match="null value"):
            validate_bronze(df, "samples_metadata_raw")

    def test_null_family_id_allowed(self) -> None:
        df = pd.DataFrame([_samples_metadata_row(family_id=None)])
        validate_bronze(df, "samples_metadata_raw")  # family_id is nullable


# ── pharmgkb_clinical_annotations_raw ────────────────────────────────────────


class TestPharmgkbClinicalAnnotationsRaw:
    def _valid_df(self) -> pd.DataFrame:
        return pd.DataFrame(
            [
                {
                    "clinical_annotation_id": "CA001",
                    "gene_symbol": "CYP2C19",
                    "evidence_level": "1A",
                    "variant_or_haplotype": "rs4244285",
                    "drug_names": "clopidogrel",
                    "phenotype_categories": "Metabolism",
                    "clinical_annotation_types": "Dosage",
                    "pediatric": "No",
                    "annotation_text": "Avoid in poor metabolizers.",
                    "url": None,
                }
            ]
        )

    def test_valid_dataframe_passes(self) -> None:
        validate_bronze(self._valid_df(), "pharmgkb_clinical_annotations_raw")

    def test_missing_clinical_annotation_id_raises(self) -> None:
        df = self._valid_df().drop(columns=["clinical_annotation_id"])
        with pytest.raises(RuntimeError, match="missing required columns"):
            validate_bronze(df, "pharmgkb_clinical_annotations_raw")

    def test_null_gene_symbol_raises(self) -> None:
        df = self._valid_df()
        df.loc[0, "gene_symbol"] = None
        with pytest.raises(RuntimeError, match="null value"):
            validate_bronze(df, "pharmgkb_clinical_annotations_raw")

    def test_nullable_columns_allow_nulls(self) -> None:
        df = self._valid_df()
        for col in ("variant_or_haplotype", "drug_names", "annotation_text", "url"):
            df[col] = None
        validate_bronze(df, "pharmgkb_clinical_annotations_raw")


# ── cpic_guidelines_raw ───────────────────────────────────────────────────────


class TestCpicGuidelinesRaw:
    def test_valid_dataframe_passes(self) -> None:
        df = pd.DataFrame([_cpic_row()])
        validate_bronze(df, "cpic_guidelines_raw")

    def test_missing_drug_name_raises(self) -> None:
        df = pd.DataFrame([_cpic_row()])
        df = df.drop(columns=["drug_name"])
        with pytest.raises(RuntimeError, match="missing required columns"):
            validate_bronze(df, "cpic_guidelines_raw")

    def test_null_guideline_id_raises(self) -> None:
        df = pd.DataFrame([_cpic_row(guideline_id=None)])
        with pytest.raises(RuntimeError, match="null value"):
            validate_bronze(df, "cpic_guidelines_raw")

    def test_null_phenotype_allowed(self) -> None:
        df = pd.DataFrame([_cpic_row(phenotype=None)])
        validate_bronze(df, "cpic_guidelines_raw")

    def test_null_classification_strength_allowed(self) -> None:
        df = pd.DataFrame([_cpic_row(classification_strength=None)])
        validate_bronze(df, "cpic_guidelines_raw")


# ── Edge cases ────────────────────────────────────────────────────────────────


class TestEdgeCases:
    def test_unknown_table_skips_silently(self) -> None:
        df = pd.DataFrame({"any_column": [1, 2, 3]})
        validate_bronze(df, "nonexistent_table")  # must not raise

    def test_empty_dataframe_with_correct_columns_passes(self) -> None:
        df = pd.DataFrame(columns=list(_genomes_variants_row().keys()))
        validate_bronze(df, "genomes_variants_raw")

    def test_error_message_lists_all_missing_columns(self) -> None:
        df = pd.DataFrame([{"chromosome": "chr1"}])  # most columns missing
        with pytest.raises(RuntimeError, match="sample_id"):
            validate_bronze(df, "genomes_variants_raw")
