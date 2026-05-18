"""Download PharmGKB TSV releases and write Parquet to data/bronze/pharmgkb_*_raw/.

Source:  https://www.pharmgkb.org/downloads
License: CC BY 4.0  (https://creativecommons.org/licenses/by/4.0/)
Cite:    Whirl-Carrillo et al. Clin Pharmacol Ther 2021. PMID 34216021

Downloads four zip archives from the PharmGKB API. Each zip contains one or more
TSV files that are mapped to bronze schema column names and written as Parquet.
"""

from __future__ import annotations

import io
import logging
import zipfile
from dataclasses import dataclass
from datetime import date, datetime

import pandas as pd
import requests
from tenacity import (
    retry,
    retry_if_exception_type,
    stop_after_attempt,
    wait_exponential,
)

from pgx_latam.config import Settings, get_settings
from pgx_latam.utils.parquet_io import write_bronze_partition

logger = logging.getLogger(__name__)

_PHARMGKB_BASE = "https://api.pharmgkb.org/v1/download/file/data"
_REQUEST_TIMEOUT = 120  # seconds


@dataclass(frozen=True)
class _DownloadSpec:
    url: str
    zip_member: str
    column_map: dict[str, str]
    table_name: str
    required_columns: tuple[str, ...]


def _clinical_annotations_spec() -> _DownloadSpec:
    return _DownloadSpec(
        url=f"{_PHARMGKB_BASE}/clinicalAnnotations.zip",
        zip_member="clinical_annotations.tsv",
        column_map={
            "Clinical Annotation ID": "clinical_annotation_id",
            "Variant/Haplotypes": "variant_or_haplotype",
            "Gene": "gene_symbol",
            "Drug(s)": "drug_names",
            "Phenotype Category": "phenotype_categories",
            # PharmGKB renamed "Evidence Level" → "Level of Evidence" (observed 2026-05)
            "Level of Evidence": "evidence_level",
            "Evidence Level": "evidence_level",       # kept for older downloads
            "Clinical Annotation Types": "clinical_annotation_types",
            "Pediatric": "pediatric",
            "Sentence": "annotation_text",
            "URL": "url",
        },
        table_name="pharmgkb_clinical_annotations_raw",
        required_columns=("Clinical Annotation ID", "Gene"),
    )


def _var_drug_ann_spec() -> _DownloadSpec:
    return _DownloadSpec(
        url=f"{_PHARMGKB_BASE}/variantAnnotations.zip",
        zip_member="var_drug_ann.tsv",
        column_map={
            # PharmGKB renamed "Annotation ID" → "Variant Annotation ID" (observed 2026-05)
            "Variant Annotation ID": "annotation_id",
            "Annotation ID": "annotation_id",             # kept for older downloads
            "Variant/Haplotypes": "variant_rsid",
            "Gene": "gene_symbol",
            "Drug(s)": "drug_name",
            "PMID": "pmid",
            "Phenotype Category": "phenotype_category",
            "Significance": "significance",
            "Notes": "notes",
            "Sentence": "sentence",
            "Alleles": "alleles",
        },
        table_name="pharmgkb_var_drug_ann_raw",
        required_columns=("Gene",),
    )


def _drugs_spec() -> _DownloadSpec:
    return _DownloadSpec(
        url=f"{_PHARMGKB_BASE}/drugs.zip",
        zip_member="drugs.tsv",
        column_map={
            "PharmGKB Accession Id": "pharmgkb_drug_id",
            "Name": "drug_name",
            "Generic Names": "generic_names",
            "Trade Names": "trade_names",
            "Type": "drug_type",
            "Cross-references": "_cross_references",
        },
        table_name="pharmgkb_drugs_raw",
        required_columns=("PharmGKB Accession Id", "Name"),
    )


def _genes_spec() -> _DownloadSpec:
    return _DownloadSpec(
        url=f"{_PHARMGKB_BASE}/genes.zip",
        zip_member="genes.tsv",
        column_map={
            "PharmGKB Accession Id": "pharmgkb_gene_id",
            "Symbol": "gene_symbol",
            "Ensembl Id": "ensembl_id",
            "NCBI Gene ID": "ncbi_gene_id",
            "Chromosome": "chromosome",
            "Chromosomal Start (GRCh37)": "chromosomal_start",
            "Chromosomal End (GRCh37)": "chromosomal_end",
        },
        table_name="pharmgkb_genes_raw",
        required_columns=("PharmGKB Accession Id", "Symbol"),
    )


@retry(
    retry=retry_if_exception_type(requests.RequestException),
    wait=wait_exponential(multiplier=2, min=4, max=60),
    stop=stop_after_attempt(4),
    reraise=True,
)
def _download_zip(url: str) -> bytes:
    logger.info("Downloading %s", url)
    response = requests.get(url, timeout=_REQUEST_TIMEOUT)
    if response.status_code != 200:
        raise RuntimeError(
            f"PharmGKB download failed: GET {url} → HTTP {response.status_code}. "
            "Source may be unavailable. Check https://www.pharmgkb.org/downloads"
        )
    return response.content


def _extract_tsv_from_zip(zip_bytes: bytes, member: str) -> pd.DataFrame:
    with zipfile.ZipFile(io.BytesIO(zip_bytes)) as zf:
        available = zf.namelist()
        matched = [n for n in available if n.endswith(member) or n == member]
        if not matched:
            raise RuntimeError(
                f"Expected '{member}' inside zip archive. "
                f"Found: {available}. PharmGKB may have renamed this file."
            )
        with zf.open(matched[0]) as tsv_file:
            return pd.read_csv(
                tsv_file,
                sep="\t",
                comment="#",
                dtype=str,
                keep_default_na=False,
            )


def _map_columns(df: pd.DataFrame, spec: _DownloadSpec) -> pd.DataFrame:
    actual_cols = set(df.columns)
    missing_required = [c for c in spec.required_columns if c not in actual_cols]
    if missing_required:
        raise RuntimeError(
            f"PharmGKB {spec.zip_member}: required columns not found: {missing_required}. "
            f"Actual columns: {sorted(actual_cols)}. "
            "PharmGKB may have changed their schema — update column_map in pharmgkb.py."
        )

    available_mapped = {
        src: dst for src, dst in spec.column_map.items() if src in actual_cols
    }
    missing_optional = [
        src for src in spec.column_map if src not in actual_cols
    ]
    if missing_optional:
        logger.warning(
            "%s: optional columns not found (will be null): %s",
            spec.zip_member,
            missing_optional,
        )

    result = df[list(available_mapped.keys())].rename(columns=available_mapped)

    for src, dst in spec.column_map.items():
        if src not in available_mapped and dst not in result.columns:
            result[dst] = pd.NA

    return result


def _parse_cross_references(df: pd.DataFrame) -> pd.DataFrame:
    """Extract ATC and RxNorm identifiers from the PharmGKB cross-references column."""
    if "_cross_references" not in df.columns:
        df["atc_identifiers"] = pd.NA
        df["rxnorm_identifiers"] = pd.NA
        return df

    def _extract(ref_str: str, prefix: str) -> str:
        if not ref_str or pd.isna(ref_str):
            return ""
        parts = [p.strip() for p in str(ref_str).split(",")]
        matched = [p.split(":", 1)[1] for p in parts if p.startswith(f"{prefix}:")]
        return ",".join(matched)

    df["atc_identifiers"] = df["_cross_references"].apply(
        lambda x: _extract(x, "ATC")
    )
    df["rxnorm_identifiers"] = df["_cross_references"].apply(
        lambda x: _extract(x, "RxNorm")
    )
    return df.drop(columns=["_cross_references"])


def _process_spec(spec: _DownloadSpec) -> pd.DataFrame:
    zip_bytes = _download_zip(spec.url)
    raw_df = _extract_tsv_from_zip(zip_bytes, spec.zip_member)
    logger.info("%s: %d rows loaded from TSV", spec.zip_member, len(raw_df))
    mapped_df = _map_columns(raw_df, spec)
    if spec.table_name == "pharmgkb_drugs_raw":
        mapped_df = _parse_cross_references(mapped_df)
    return mapped_df


def run(ingest_date: date | None = None, settings: Settings | None = None) -> list[str]:
    """Download all PharmGKB TSV releases and write to bronze Parquet.

    Args:
        ingest_date: Partition date. Defaults to today.
        settings: Application settings. Defaults to ``get_settings()``.

    Returns:
        List of written table names.
    """
    effective_date = ingest_date or datetime.utcnow().date()
    cfg = settings or get_settings()

    specs = [
        _clinical_annotations_spec(),
        _var_drug_ann_spec(),
        _drugs_spec(),
        _genes_spec(),
    ]

    written: list[str] = []
    for spec in specs:
        logger.info("Processing PharmGKB table: %s", spec.table_name)
        df = _process_spec(spec)
        table_root = cfg.bronze_root / spec.table_name
        write_bronze_partition(df, table_root, effective_date)
        written.append(spec.table_name)
        logger.info(
            "Wrote %s: %d rows → %s",
            spec.table_name,
            len(df),
            table_root / f"ingest_date={effective_date.isoformat()}",
        )

    return written


def main() -> None:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s — %(message)s",
    )
    written = run()
    for table in written:
        print(f"  ✓ {table}")


if __name__ == "__main__":
    main()
