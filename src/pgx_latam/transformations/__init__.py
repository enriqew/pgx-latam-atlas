"""Transformation modules for bronze → silver → gold medallion layers."""

from __future__ import annotations

import logging

from pgx_latam.config import Settings, get_settings
from pgx_latam.transformations import silver_clinical, silver_variants

logger = logging.getLogger(__name__)


def run_silver(settings: Settings | None = None) -> None:
    """Run all silver transformations.

    silver_variants runs first (it builds populations + pharmacogenes).
    silver_clinical is independent and runs second.
    """
    cfg = settings or get_settings()
    logger.info("=== Silver transformation start ===")
    silver_variants.run(cfg)
    silver_clinical.run(cfg)
    logger.info("=== Silver transformation complete ===")


def main() -> None:
    import argparse

    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s — %(message)s",
    )
    parser = argparse.ArgumentParser(description="Run pgx-latam silver transformations.")
    parser.add_argument(
        "--layer",
        choices=["all", "variants", "clinical"],
        default="all",
        help="Which silver table group to build (default: all)",
    )
    args = parser.parse_args()
    cfg = get_settings()

    if args.layer == "all":
        run_silver(cfg)
    elif args.layer == "variants":
        silver_variants.run(cfg)
    elif args.layer == "clinical":
        silver_clinical.run(cfg)
