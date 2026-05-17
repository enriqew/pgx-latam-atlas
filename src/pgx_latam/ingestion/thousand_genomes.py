"""Ingest 1000 Genomes Phase 3 VCF data for pharmacogene regions.

Data source: s3://1000genomes/release/20130502/
Registry: https://registry.opendata.aws/1000-genomes/

This module extracts per-sample genotype calls for in-scope pharmacogene
regions and writes Parquet files to data/bronze/genomes_variants_raw/.
"""

# TODO (Phase 1): implement VCF region extraction via pysam or cyvcf2


def main() -> None:
    raise NotImplementedError("Phase 1 ingestion not yet implemented")


if __name__ == "__main__":
    main()
