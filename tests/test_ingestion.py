"""Unit tests for ingestion module logic — no network calls."""

from __future__ import annotations

import io
import zipfile
from datetime import date

import pandas as pd
import pytest

from pgx_latam.ingestion.pharmgkb import (
    _clinical_annotations_spec,
    _drugs_spec,
    _extract_tsv_from_zip,
    _genes_spec,
    _map_columns,
    _parse_cross_references,
)
from pgx_latam.ingestion.thousand_genomes import (
    TARGET_POPULATIONS,
    _build_panel_df,
    _vcf_url,
)
from pgx_latam.ingestion.cpic import _flatten_recommendations


# ── PharmGKB helpers ──────────────────────────────────────────────────────────

class TestExtractTsvFromZip:
    def _make_zip(self, filename: str, content: str) -> bytes:
        buf = io.BytesIO()
        with zipfile.ZipFile(buf, "w") as zf:
            zf.writestr(filename, content)
        return buf.getvalue()

    def test_extracts_correct_member(self) -> None:
        tsv = "col_a\tcol_b\nval1\tval2\n"
        zip_bytes = self._make_zip("clinical_annotations.tsv", tsv)
        df = _extract_tsv_from_zip(zip_bytes, "clinical_annotations.tsv")
        assert list(df.columns) == ["col_a", "col_b"]
        assert len(df) == 1

    def test_raises_when_member_missing(self) -> None:
        zip_bytes = self._make_zip("other_file.tsv", "a\tb\n1\t2\n")
        with pytest.raises(RuntimeError, match="clinical_annotations.tsv"):
            _extract_tsv_from_zip(zip_bytes, "clinical_annotations.tsv")

    def test_handles_subdirectory_prefix(self) -> None:
        tsv = "id\tname\n1\ttest\n"
        zip_bytes = self._make_zip("subdir/clinical_annotations.tsv", tsv)
        df = _extract_tsv_from_zip(zip_bytes, "clinical_annotations.tsv")
        assert len(df) == 1


class TestMapColumns:
    def test_maps_all_expected_columns(self) -> None:
        spec = _clinical_annotations_spec()
        df = pd.DataFrame(
            {
                "Clinical Annotation ID": ["CA_001"],
                "Variant/Haplotypes": ["rs4244285"],
                "Gene": ["CYP2C19"],
                "Drug(s)": ["clopidogrel"],
                "Phenotype Category": ["Metabolism"],
                "Evidence Level": ["1A"],
                "Clinical Annotation Types": ["Dosage"],
                "Pediatric": ["No"],
                "Sentence": ["This variant affects metabolism."],
            }
        )
        result = _map_columns(df, spec)
        assert "clinical_annotation_id" in result.columns
        assert "gene_symbol" in result.columns
        assert "evidence_level" in result.columns
        assert result["gene_symbol"].iloc[0] == "CYP2C19"

    def test_raises_on_missing_required_column(self) -> None:
        spec = _clinical_annotations_spec()
        df = pd.DataFrame({"Some Unrelated Column": ["value"]})
        with pytest.raises(RuntimeError, match="required columns not found"):
            _map_columns(df, spec)

    def test_optional_missing_columns_become_null(self) -> None:
        spec = _clinical_annotations_spec()
        df = pd.DataFrame(
            {
                "Clinical Annotation ID": ["CA_001"],
                "Gene": ["CYP2C19"],
                "Evidence Level": ["1A"],
            }
        )
        result = _map_columns(df, spec)
        assert "annotation_text" in result.columns


class TestParseCrossReferences:
    def test_extracts_atc_and_rxnorm(self) -> None:
        df = pd.DataFrame(
            {
                "_cross_references": [
                    "ATC:B01AC04,PubChem Compound:60606,RxNorm:32968",
                    "ATC:C10AA01,RxNorm:12345,DrugBank:DB01234",
                    "No cross refs",
                ]
            }
        )
        result = _parse_cross_references(df)
        assert result["atc_identifiers"].iloc[0] == "B01AC04"
        assert result["rxnorm_identifiers"].iloc[0] == "32968"
        assert result["atc_identifiers"].iloc[1] == "C10AA01"
        assert result["rxnorm_identifiers"].iloc[2] == ""

    def test_handles_empty_cross_refs(self) -> None:
        df = pd.DataFrame({"_cross_references": [pd.NA, ""]})
        result = _parse_cross_references(df)
        assert result["atc_identifiers"].iloc[0] == ""
        assert "_cross_references" not in result.columns


# ── 1000 Genomes helpers ──────────────────────────────────────────────────────

class TestBuildPanelDf:
    def _sample_panel(self) -> pd.DataFrame:
        return pd.DataFrame(
            {
                "sample": ["NA19648", "HG01619", "NA18525"],
                "pop": ["MXL", "CLM", "CEU"],
                "super_pop": ["AMR", "AMR", "EUR"],
                "gender": ["female", "male", "female"],
            }
        )

    def test_renames_columns_correctly(self) -> None:
        df = _build_panel_df(self._sample_panel())
        assert "sample_id" in df.columns
        assert "population_code" in df.columns
        assert "superpopulation" in df.columns
        assert "sex" in df.columns
        assert "family_id" in df.columns

    def test_adds_null_family_id(self) -> None:
        df = _build_panel_df(self._sample_panel())
        assert df["family_id"].isna().all()

    def test_raises_on_missing_required_columns(self) -> None:
        bad_df = pd.DataFrame({"sample": ["NA19648"], "gender": ["female"]})
        with pytest.raises(RuntimeError, match="missing expected columns"):
            _build_panel_df(bad_df)


class TestVcfUrl:
    def test_autosome_url_pattern(self) -> None:
        url = _vcf_url("10")
        assert "chr10" in url
        assert "v5b" in url
        assert url.endswith(".vcf.gz")

    def test_chrx_uses_v5a_pattern(self) -> None:
        url = _vcf_url("X")
        assert "chrX" in url
        assert "v5a" in url
        assert "v5b" not in url

    def test_all_gene_chromosomes_have_url(self) -> None:
        from pgx_latam.ingestion.thousand_genomes import GENE_REGIONS_GRCH37
        for gene, region in GENE_REGIONS_GRCH37.items():
            url = _vcf_url(region.chromosome)
            assert url.startswith("https://"), f"{gene}: bad URL {url}"


class TestTargetPopulations:
    def test_latam_populations_present(self) -> None:
        assert "MXL" in TARGET_POPULATIONS
        assert "PEL" in TARGET_POPULATIONS
        assert "CLM" in TARGET_POPULATIONS
        assert "PUR" in TARGET_POPULATIONS

    def test_ceu_reference_present(self) -> None:
        assert "CEU" in TARGET_POPULATIONS

    def test_no_pooled_latino_category(self) -> None:
        assert "LATAM" not in TARGET_POPULATIONS
        assert "Latino" not in TARGET_POPULATIONS
        assert "Hispanic" not in TARGET_POPULATIONS


# ── CPIC helpers ──────────────────────────────────────────────────────────────

class TestFlattenRecommendations:
    def _sample_guidelines(self) -> dict:
        return {
            "PA166104938": {
                "id": "PA166104938",
                "name": "CPIC guideline for clopidogrel and CYP2C19",
                "genes": ["CYP2C19"],
                "drugs": ["clopidogrel"],
                "version": 3,
            }
        }

    def _sample_recs(self) -> list:
        return [
            {
                "id": 1001,
                "guidelineid": "PA166104938",
                "drugrecommendation": "Avoid use for poor metabolizers.",
                "classification": "Strong",
                "phenotypes": {"CYP2C19": "Poor Metabolizer"},
                "activityscore": {"CYP2C19": "0.0"},
                "comments": "",
            }
        ]

    def test_produces_expected_row(self) -> None:
        rows = _flatten_recommendations(
            self._sample_recs(), self._sample_guidelines(), {}
        )
        assert len(rows) == 1
        row = rows[0]
        assert row["gene_symbol"] == "CYP2C19"
        assert row["drug_name"] == "clopidogrel"
        assert row["phenotype"] == "Poor Metabolizer"
        assert row["classification_strength"] == "Strong"
        assert len(row["recommendation_text"]) > 0

    def test_skips_rec_with_unknown_guideline(self) -> None:
        recs = [{"id": 9999, "guidelineid": "UNKNOWN_ID", "drugrecommendation": "X",
                 "classification": "Strong", "phenotypes": {}, "activityscore": {}, "comments": ""}]
        rows = _flatten_recommendations(recs, self._sample_guidelines(), {})
        assert len(rows) == 0

    def test_multi_gene_recommendation_emits_multiple_rows(self) -> None:
        guidelines = {
            "PA166105001": {
                "id": "PA166105001",
                "genes": ["CYP2C19", "CYP2D6"],
                "drugs": ["amitriptyline"],
                "version": 2,
            }
        }
        recs = [
            {
                "id": 2001,
                "guidelineid": "PA166105001",
                "drugrecommendation": "Consider alternative.",
                "classification": "Strong",
                "phenotypes": {
                    "CYP2C19": "Poor Metabolizer",
                    "CYP2D6": "Normal Metabolizer",
                },
                "activityscore": {},
                "comments": "",
            }
        ]
        rows = _flatten_recommendations(recs, guidelines, {})
        assert len(rows) == 2
        genes = {r["gene_symbol"] for r in rows}
        assert genes == {"CYP2C19", "CYP2D6"}
