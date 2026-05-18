"""Export modules that write gold layer results to artifacts/ JSON files."""

from __future__ import annotations

import logging

from pgx_latam.config import Settings, get_settings
from pgx_latam.exports import portfolio_artifacts

logger = logging.getLogger(__name__)


def run_exports(settings: Settings | None = None) -> None:
    """Run all artifact exports from gold tables."""
    cfg = settings or get_settings()
    logger.info("=== Export start ===")
    portfolio_artifacts.run(cfg)
    logger.info("=== Export complete ===")


def main() -> None:
    import argparse

    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s — %(message)s",
    )
    parser = argparse.ArgumentParser(description="Export pgx-latam gold artifacts to JSON.")
    parser.add_argument(
        "--artifact",
        choices=[
            "all",
            "allele_frequencies",
            "phenotype_distribution",
            "drug_impact_summary",
            "actionability_ranking",
        ],
        default="all",
        help="Which artifact to export (default: all)",
    )
    args = parser.parse_args()
    cfg = get_settings()

    if args.artifact == "all":
        run_exports(cfg)
    else:
        gold_root = cfg.gold_root
        artifacts_root = cfg.artifacts_root
        artifacts_root.mkdir(parents=True, exist_ok=True)
        fn_map = {
            "allele_frequencies": portfolio_artifacts.export_allele_frequencies,
            "phenotype_distribution": portfolio_artifacts.export_phenotype_distribution,
            "drug_impact_summary": portfolio_artifacts.export_drug_impact_summary,
            "actionability_ranking": portfolio_artifacts.export_actionability_ranking,
        }
        fn_map[args.artifact](gold_root, artifacts_root)
