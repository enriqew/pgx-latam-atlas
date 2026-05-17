"""Shared utilities for writing Bronze-layer partitioned Parquet files."""

from __future__ import annotations

import logging
from datetime import date
from pathlib import Path

import pandas as pd

logger = logging.getLogger(__name__)


def write_bronze_partition(
    df: pd.DataFrame,
    table_root: Path,
    ingest_date: date,
    extra_partition: tuple[str, str] | None = None,
) -> Path:
    """Write a DataFrame to a date-partitioned Parquet file in bronze.

    Args:
        df: DataFrame to write. Column names must match the bronze DDL schema.
        table_root: Root path for the table, e.g. ``settings.bronze_root / "genomes_variants_raw"``.
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
