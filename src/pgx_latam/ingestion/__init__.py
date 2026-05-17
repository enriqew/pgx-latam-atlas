"""Data ingestion modules for 1000 Genomes, PharmGKB, and CPIC sources."""

from __future__ import annotations

import logging
from datetime import date, datetime

from pgx_latam.config import Settings, get_settings
from pgx_latam.ingestion import cpic, pharmgkb, thousand_genomes

logger = logging.getLogger(__name__)


def run_all(ingest_date: date | None = None, settings: Settings | None = None) -> None:
    """Run all three ingestors sequentially.

    Order: PharmGKB and CPIC first (pure HTTP, no pysam), then 1000 Genomes.
    PharmGKB and CPIC are independent and could be parallelized in Phase 4 Step Functions.
    """
    effective_date = ingest_date or datetime.utcnow().date()
    cfg = settings or get_settings()

    logger.info("=== Ingestion start: %s ===", effective_date.isoformat())

    pharmgkb.run(effective_date, cfg)
    cpic.run(effective_date, cfg)
    thousand_genomes.run(effective_date, cfg)

    logger.info("=== Ingestion complete: %s ===", effective_date.isoformat())


def main() -> None:
    import argparse

    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s — %(message)s",
    )

    parser = argparse.ArgumentParser(
        description="Run pgx-latam data ingestion from public sources."
    )
    parser.add_argument(
        "--source",
        choices=["all", "pharmgkb", "cpic", "1000g"],
        default="all",
        help="Which source to ingest (default: all)",
    )
    parser.add_argument(
        "--date",
        type=date.fromisoformat,
        default=None,
        help="Ingest partition date as YYYY-MM-DD (default: today)",
    )
    args = parser.parse_args()

    cfg = get_settings()
    effective_date = args.date or datetime.utcnow().date()

    if args.source == "all":
        run_all(effective_date, cfg)
    elif args.source == "pharmgkb":
        pharmgkb.run(effective_date, cfg)
    elif args.source == "cpic":
        cpic.run(effective_date, cfg)
    elif args.source == "1000g":
        thousand_genomes.run(effective_date, cfg)
