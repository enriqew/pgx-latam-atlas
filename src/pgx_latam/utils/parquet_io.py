"""Shared utilities for reading and writing medallion-layer Parquet files."""

from __future__ import annotations

import logging
from datetime import date
from pathlib import Path

import pandas as pd

logger = logging.getLogger(__name__)


# ── Bronze writes ─────────────────────────────────────────────────────────────

def write_bronze_partition(
    df: pd.DataFrame,
    table_root: Path,
    ingest_date: date,
    extra_partition: tuple[str, str] | None = None,
) -> Path:
    """Write a DataFrame to a date-partitioned Parquet file in bronze.

    Args:
        df: DataFrame whose columns match the bronze DDL schema.
        table_root: Root path for the table.
        ingest_date: Partition date written as ``ingest_date=YYYY-MM-DD``.
        extra_partition: Optional second partition as (column_name, value),
            e.g. ``("chromosome_part", "chr10")``.

    Returns:
        Path to the written ``.parquet`` file.
    """
    partition_dir = table_root / f"ingest_date={ingest_date.isoformat()}"
    if extra_partition is not None:
        col_name, col_val = extra_partition
        partition_dir = partition_dir / f"{col_name}={col_val}"

    partition_dir.mkdir(parents=True, exist_ok=True)
    out_path = partition_dir / "data.parquet"
    df.to_parquet(out_path, engine="pyarrow", compression="snappy", index=False)
    logger.info("Wrote %d rows → %s", len(df), out_path)
    return out_path


# ── Bronze reads ──────────────────────────────────────────────────────────────

def read_latest_bronze_partition(table_root: Path) -> pd.DataFrame:
    """Read all Parquet files from the most recent ingest_date partition.

    Recurses into sub-partitions (e.g. chromosome_part=chrN) automatically.

    Args:
        table_root: Root directory of the bronze table.

    Returns:
        Concatenated DataFrame of all files in the latest partition.

    Raises:
        FileNotFoundError: If no partitions exist — ingestion must be run first.
    """
    if not table_root.exists():
        raise FileNotFoundError(
            f"Bronze table not found: {table_root}\n"
            "Run ingestion first: make ingest-local"
        )

    date_dirs = sorted(
        [d for d in table_root.iterdir() if d.is_dir() and d.name.startswith("ingest_date=")],
        key=lambda d: d.name,
        reverse=True,
    )
    if not date_dirs:
        raise FileNotFoundError(
            f"No ingest_date partitions found in {table_root}. "
            "Run ingestion first: make ingest-local"
        )

    latest = date_dirs[0]
    parquet_files = sorted(latest.rglob("*.parquet"))
    if not parquet_files:
        raise FileNotFoundError(
            f"No Parquet files found in {latest}. "
            "The ingestion run may have produced an empty result."
        )

    frames = [pd.read_parquet(f) for f in parquet_files]
    df = pd.concat(frames, ignore_index=True)
    logger.info(
        "Read %d rows from %s (%d files, partition %s)",
        len(df),
        table_root.name,
        len(parquet_files),
        latest.name,
    )
    return df


# ── Silver writes ─────────────────────────────────────────────────────────────

def write_silver_table(
    df: pd.DataFrame,
    table_root: Path,
) -> Path:
    """Write a non-partitioned silver table as a single Parquet file.

    Args:
        df: DataFrame whose columns match the silver DDL schema.
        table_root: Root directory for the table (one level, no partitions).

    Returns:
        Path to the written ``.parquet`` file.
    """
    table_root.mkdir(parents=True, exist_ok=True)
    out_path = table_root / "data.parquet"
    df.to_parquet(out_path, engine="pyarrow", compression="snappy", index=False)
    logger.info("Wrote %d rows → %s", len(df), out_path)
    return out_path


def write_silver_variants_partition(
    df: pd.DataFrame,
    table_root: Path,
    gene_symbol: str,
    population_code: str,
) -> Path:
    """Write a silver/variants/ partition for one gene x population combination.

    Directory layout: ``table_root/gene_symbol_part=GENE/population_part=POP/data.parquet``

    Args:
        df: Variant DataFrame for this gene + population slice.
        table_root: Root directory of silver/variants/.
        gene_symbol: HGNC gene symbol used as partition value.
        population_code: 1000G population code used as partition value.

    Returns:
        Path to the written ``.parquet`` file.
    """
    out_dir = (
        table_root
        / f"gene_symbol_part={gene_symbol}"
        / f"population_part={population_code}"
    )
    out_dir.mkdir(parents=True, exist_ok=True)
    out_path = out_dir / "data.parquet"
    df.to_parquet(out_path, engine="pyarrow", compression="snappy", index=False)
    logger.debug(
        "Wrote %d rows → %s/%s/%s",
        len(df),
        table_root.name,
        gene_symbol,
        population_code,
    )
    return out_path


def read_silver_table(table_root: Path) -> pd.DataFrame:
    """Read a silver table (non-partitioned or any directory of Parquet files).

    Args:
        table_root: Root directory of the silver table.

    Returns:
        Concatenated DataFrame.

    Raises:
        FileNotFoundError: If the table does not exist.
    """
    if not table_root.exists():
        raise FileNotFoundError(
            f"Silver table not found: {table_root}\n"
            "Run silver transformations first: make transform-local"
        )
    parquet_files = sorted(table_root.rglob("*.parquet"))
    if not parquet_files:
        raise FileNotFoundError(f"No Parquet files found in {table_root}")
    frames = [pd.read_parquet(f) for f in parquet_files]
    df = pd.concat(frames, ignore_index=True)
    logger.info("Read %d rows from silver/%s", len(df), table_root.name)
    return df
