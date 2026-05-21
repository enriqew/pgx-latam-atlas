"""Ingest 1000 Genomes Phase 3 VCF data for pharmacogene regions.

Source:   s3://1000genomes/release/20130502/  (AWS Open Data)
Registry: https://registry.opendata.aws/1000-genomes/
Cite:     1000 Genomes Project Consortium. Nature 526, 68-74 (2015). PMID 26432245

Extracts per-sample genotype calls for all in-scope pharmacogene regions,
restricted to the target populations: MXL, PEL, CLM, PUR (Latin America),
YRI, ASW (African ancestry), GIH (South Asia), and CEU (European baseline).

Requires pysam for remote tabix-indexed VCF access. On Windows, run via
WSL2 or Docker (see docs/local_dev.md). On Linux/macOS: pip install ".[vcf]".
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import date, datetime
from pathlib import Path

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
from pgx_latam.utils.star_allele_scope import in_scope_symbols

logger = logging.getLogger(__name__)

# ── Constants ─────────────────────────────────────────────────────────────────

TARGET_POPULATIONS = ("MXL", "PEL", "CLM", "PUR", "CEU", "YRI", "ASW", "GIH")

_1000G_HTTPS_BASE = "https://ftp.1000genomes.ebi.ac.uk/vol1/ftp/release/20130502"

_PANEL_URL = f"{_1000G_HTTPS_BASE}/integrated_call_samples_v3.20130502.ALL.panel"

_REQUEST_TIMEOUT = 60
_WRITE_BATCH_SIZE = 50_000
_REGION_BUFFER_BP = 10_000


@dataclass(frozen=True)
class GeneRegion:
    chromosome: str  # without "chr" prefix, e.g. "10" or "X"
    start: int  # 1-based, inclusive (GRCh37)
    end: int  # 1-based, inclusive (GRCh37)


# GRCh37 coordinates — source: PharmGKB genes.tsv (these are approximate;
# the pipeline uses a ±10kb buffer to ensure all relevant variants are captured)
GENE_REGIONS_GRCH37: dict[str, GeneRegion] = {
    # CYP2C19: extended start to 96_510_000 to include rs4244285 (*2) at 96_521_657,
    # which sits ~800bp upstream of the canonical gene body start.
    "CYP2C19": GeneRegion("10", 96_510_000, 96_612_671),
    "CYP2C9": GeneRegion("10", 96_698_415, 96_749_148),
    "SLCO1B1": GeneRegion("12", 21_282_444, 21_394_730),
    # VKORC1: extended start to 31_090_000 to include rs9923231 (-1639G>A) at 31_093_568,
    # a promoter variant ~8.6kb upstream of the gene body.
    "VKORC1": GeneRegion("16", 31_090_000, 31_106_234),
    "TPMT": GeneRegion("6", 18_128_556, 18_155_418),
    "NUDT15": GeneRegion("13", 48_600_074, 48_609_007),
    "DPYD": GeneRegion("1", 97_543_300, 98_386_615),
    "G6PD": GeneRegion("X", 153_759_605, 153_798_257),
    "IFNL3": GeneRegion("19", 39_729_165, 39_756_700),
    "CYP3A5": GeneRegion("7", 99_245_817, 99_277_621),
    # UGT1A9: extended start to 234_575_000 to include rs17868320 (*3, c.98T>C)
    # at chr2:234_578_428, which is ~2kb upstream of the Ensembl-annotated gene body.
    "UGT1A9": GeneRegion("2", 234_575_000, 234_681_946),
}


def _vcf_url(chromosome: str) -> str:
    """Return the HTTPS URL for the 1000G Phase 3 VCF for a given chromosome.

    ChrX uses filename suffix _v1c_ (updated 2021-03-16); autosomes use _v5b_.
    """
    if chromosome == "X":
        return (
            f"{_1000G_HTTPS_BASE}/"
            "ALL.chrX.phase3_shapeit2_mvncall_integrated_v1c.20130502.genotypes.vcf.gz"
        )
    return (
        f"{_1000G_HTTPS_BASE}/"
        f"ALL.chr{chromosome}.phase3_shapeit2_mvncall_integrated_v5b.20130502.genotypes.vcf.gz"
    )


# ── Panel file ────────────────────────────────────────────────────────────────


@retry(
    retry=retry_if_exception_type(requests.RequestException),
    wait=wait_exponential(multiplier=2, min=4, max=60),
    stop=stop_after_attempt(4),
    reraise=True,
)
def _download_panel() -> pd.DataFrame:
    logger.info("Downloading 1000G panel file: %s", _PANEL_URL)
    response = requests.get(_PANEL_URL, timeout=_REQUEST_TIMEOUT)
    if response.status_code != 200:
        raise RuntimeError(
            f"1000 Genomes panel file download failed: HTTP {response.status_code}. "
            f"URL: {_PANEL_URL}"
        )
    from io import StringIO

    df = pd.read_csv(StringIO(response.text), sep="\t", dtype=str)
    logger.info("Panel file: %d samples", len(df))
    return df


def _build_panel_df(raw_panel: pd.DataFrame) -> pd.DataFrame:
    col_map = {
        "sample": "sample_id",
        "pop": "population_code",
        "super_pop": "superpopulation",
        "gender": "sex",
        "sex": "sex",
    }
    existing = {c: col_map[c] for c in raw_panel.columns if c in col_map}
    missing = [c for c in ("sample", "pop", "super_pop") if c not in raw_panel.columns]
    if missing:
        raise RuntimeError(
            f"1000G panel file missing expected columns: {missing}. "
            f"Actual columns: {list(raw_panel.columns)}"
        )

    df = raw_panel.rename(columns=existing)
    if "family_id" not in df.columns:
        df["family_id"] = pd.NA

    return df[["sample_id", "population_code", "superpopulation", "sex", "family_id"]]


def ingest_panel_file(
    ingest_date: date, settings: Settings
) -> tuple[Path, dict[str, tuple[str, str]]]:
    """Download the 1000G panel file and write to bronze/samples_metadata_raw/.

    Returns:
        Tuple of (parquet_path, sample_to_population_map).
        sample_to_population_map maps sample_id → (population_code, superpopulation).
    """
    raw = _download_panel()
    df = _build_panel_df(raw)

    target_df = df[df["population_code"].isin(TARGET_POPULATIONS)].copy()
    logger.info(
        "Target populations: %s",
        target_df.groupby("population_code").size().to_dict(),
    )

    table_root = settings.bronze_root / "samples_metadata_raw"
    path = write_bronze_partition(df, table_root, ingest_date)

    sample_map: dict[str, tuple[str, str]] = {
        row["sample_id"]: (row["population_code"], row["superpopulation"])
        for _, row in target_df.iterrows()
    }
    return path, sample_map


# ── VCF extraction ─────────────────────────────────────────────────────────────


def _require_pysam() -> None:
    try:
        import pysam as _  # noqa: F401
    except ImportError as exc:
        raise RuntimeError(
            "pysam is required for 1000 Genomes VCF extraction but is not installed.\n"
            "Install: pip install 'pgx-latam[vcf]'\n"
            "On Windows: run via WSL2 or Docker — pysam requires Linux/macOS or conda.\n"
            "See docs/local_dev.md for Docker setup."
        ) from exc


def _extract_gene_variants(
    gene_symbol: str,
    region: GeneRegion,
    sample_map: dict[str, tuple[str, str]],
) -> pd.DataFrame:
    """Fetch variants for one gene region and return a flat DataFrame.

    Args:
        gene_symbol: HGNC symbol, used only for logging.
        region: GRCh37 chromosomal region to fetch.
        sample_map: sample_id → (population_code, superpopulation) for target samples.

    Returns:
        DataFrame with bronze genomes_variants_raw schema.
    """
    import pysam  # imported late — optional dep; pysam requires Linux/macOS

    url = _vcf_url(region.chromosome)
    fetch_start = max(0, region.start - _REGION_BUFFER_BP - 1)  # pysam 0-based
    fetch_end = region.end + _REGION_BUFFER_BP
    chrom_label = (
        f"chr{region.chromosome}" if not region.chromosome.startswith("chr") else region.chromosome
    )

    logger.info(
        "Fetching %s (%s:%d-%d) from %s",
        gene_symbol,
        chrom_label,
        region.start,
        region.end,
        url,
    )

    target_sample_ids = list(sample_map.keys())

    try:
        vcf = pysam.VariantFile(url)
    except Exception as exc:
        raise RuntimeError(
            f"Cannot open remote VCF for chromosome {region.chromosome}. "
            f"URL: {url}\nError: {exc}\n"
            "Check internet connectivity and that the 1000G S3 bucket is accessible."
        ) from exc

    vcf_samples = list(vcf.header.samples)
    missing_samples = [s for s in target_sample_ids if s not in set(vcf_samples)]
    if missing_samples:
        logger.warning(
            "%d target samples not found in VCF header for chr%s: %s...",
            len(missing_samples),
            region.chromosome,
            missing_samples[:5],
        )
        target_sample_ids = [s for s in target_sample_ids if s in set(vcf_samples)]

    if not target_sample_ids:
        raise RuntimeError(
            f"No target samples found in VCF for chromosome {region.chromosome}. "
            "This likely means the panel and VCF sample IDs do not match."
        )

    rows: list[dict[str, object]] = []
    skipped_multiallelic = 0
    skipped_missing_gt = 0

    try:
        for record in vcf.fetch(region.chromosome, fetch_start, fetch_end):
            alts = record.alts
            if alts is None or len(alts) != 1:
                skipped_multiallelic += 1
                continue

            alt = alts[0]
            variant_id = record.id if record.id else f"{chrom_label}:{record.pos}"
            qual = record.qual
            filter_keys = list(record.filter.keys()) if record.filter else []
            filter_status = ";".join(filter_keys) if filter_keys else "PASS"

            for sample_id in target_sample_ids:
                gt_data = record.samples[sample_id]["GT"]
                if gt_data is None or any(g is None for g in gt_data):
                    skipped_missing_gt += 1
                    continue

                allele_dosage = sum(1 for g in gt_data if g is not None and g > 0)
                phased = record.samples[sample_id].phased
                sep = "|" if phased else "/"
                genotype_str = sep.join(str(g) for g in gt_data)

                pop_code, superpop = sample_map[sample_id]
                rows.append(
                    {
                        "chromosome": chrom_label,
                        "position": record.pos,
                        "variant_id": variant_id,
                        "reference_allele": record.ref,
                        "alternate_allele": alt,
                        "sample_id": sample_id,
                        "genotype": genotype_str,
                        "allele_dosage": allele_dosage,
                        "quality": qual,
                        "filter_status": filter_status,
                        "info_payload": None,
                        "_population_code": pop_code,
                        "_superpopulation": superpop,
                    }
                )
    finally:
        vcf.close()

    if skipped_multiallelic:
        logger.info(
            "%s: skipped %d multi-allelic sites (biallelic-only filter)",
            gene_symbol,
            skipped_multiallelic,
        )
    if skipped_missing_gt:
        logger.debug(
            "%s: skipped %d missing genotype calls",
            gene_symbol,
            skipped_missing_gt,
        )

    logger.info(
        "%s: extracted %d (variant, sample) rows from %d target samples",
        gene_symbol,
        len(rows),
        len(target_sample_ids),
    )
    return pd.DataFrame(rows)


def ingest_gene_variants(
    ingest_date: date,
    settings: Settings,
    sample_map: dict[str, tuple[str, str]],
) -> list[Path]:
    """Extract VCF regions for all in-scope genes and write to bronze Parquet.

    Partitions by ``ingest_date`` and ``chromosome_part``.

    Args:
        ingest_date: Partition date.
        settings: Application settings.
        sample_map: sample_id → (population_code, superpopulation).

    Returns:
        List of written Parquet file paths.
    """
    _require_pysam()

    missing_regions = [g for g in in_scope_symbols() if g not in GENE_REGIONS_GRCH37]
    if missing_regions:
        logger.warning(
            "No GRCh37 region defined for in-scope genes: %s. "
            "Add coordinates to GENE_REGIONS_GRCH37 in thousand_genomes.py.",
            missing_regions,
        )

    genes_by_chrom: dict[str, list[str]] = {}
    for gene in in_scope_symbols():
        if gene not in GENE_REGIONS_GRCH37:
            continue
        chrom = GENE_REGIONS_GRCH37[gene].chromosome
        genes_by_chrom.setdefault(chrom, []).append(gene)

    written_paths: list[Path] = []
    table_root = settings.bronze_root / "genomes_variants_raw"

    for chrom, genes in sorted(genes_by_chrom.items()):
        chrom_label = f"chr{chrom}"
        chrom_rows: list[pd.DataFrame] = []

        for gene_symbol in genes:
            region = GENE_REGIONS_GRCH37[gene_symbol]
            gene_df = _extract_gene_variants(gene_symbol, region, sample_map)
            if not gene_df.empty:
                chrom_rows.append(gene_df)

        if not chrom_rows:
            logger.warning("No variants extracted for chromosome %s", chrom_label)
            continue

        chrom_df = pd.concat(chrom_rows, ignore_index=True)
        chrom_df = chrom_df.drop_duplicates(subset=["variant_id", "sample_id"])
        # Drop internal columns before writing
        chrom_df = chrom_df.drop(columns=["_population_code", "_superpopulation"], errors="ignore")

        path = write_bronze_partition(
            chrom_df,
            table_root,
            ingest_date,
            extra_partition=("chromosome_part", chrom_label),
        )
        written_paths.append(path)
        logger.info(
            "Written chromosome %s: %d rows (%s)",
            chrom_label,
            len(chrom_df),
            ", ".join(genes),
        )

    return written_paths


# ── Entrypoint ────────────────────────────────────────────────────────────────


def run(ingest_date: date | None = None, settings: Settings | None = None) -> None:
    """Full 1000 Genomes ingestion: panel file + all pharmacogene VCF regions.

    Args:
        ingest_date: Partition date. Defaults to today.
        settings: Application settings. Defaults to ``get_settings()``.
    """
    effective_date = ingest_date or datetime.utcnow().date()
    cfg = settings or get_settings()

    panel_path, sample_map = ingest_panel_file(effective_date, cfg)
    logger.info("Panel written to %s — %d target samples", panel_path, len(sample_map))

    vcf_paths = ingest_gene_variants(effective_date, cfg, sample_map)
    logger.info("VCF extraction complete: %d chromosome partitions written", len(vcf_paths))


def main() -> None:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s — %(message)s",
    )
    run()
    print("  ✓ samples_metadata_raw")
    print("  ✓ genomes_variants_raw (per chromosome)")


if __name__ == "__main__":
    main()
