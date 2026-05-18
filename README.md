# pgx-latam-atlas

> Pharmacogenomic variant frequencies and drug response divergence across Latin American populations.

[![Build](https://github.com/enriqew/pgx-latam-atlas/actions/workflows/ci.yml/badge.svg)](https://github.com/enriqew/pgx-latam-atlas/actions/workflows/ci.yml)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](LICENSE)
[![Python 3.11+](https://img.shields.io/badge/python-3.11%2B-blue.svg)](https://www.python.org/downloads/)

## TL;DR

This project quantifies how pharmacogenomic allele frequencies differ between Latin American
populations (MXL, PEL, CLM, PUR) and European reference cohorts (CEU) using the 1000 Genomes
Project Phase 3 dataset, cross-referenced with PharmGKB clinical annotations and CPIC prescribing
guidelines. The result is a set of actionability rankings that highlight which drug–gene pairs
carry the greatest clinical divergence for Latin American patients — data currently absent from
most mainstream prescribing guidance.

## Key findings

> _Populated after Phase 3 pipeline run. See [`artifacts/actionability_ranking.json`](artifacts/actionability_ranking.json)._

- TBD: CYP2C19 \*2 frequency in MXL vs CEU and clopidogrel impact.
- TBD: SLCO1B1 \*5 frequency across PEL, CLM, PUR and statin safety implications.
- TBD: Top-5 drug–gene pairs by delta frequency vs European baseline.

## Architecture

```mermaid
flowchart TD
    subgraph Sources
        G[1000 Genomes S3]
        P[PharmGKB TSV]
        C[CPIC JSON]
    end

    subgraph Bronze["Bronze — raw ingestion"]
        B1[genomes_variants_raw]
        B2[samples_metadata_raw]
        B3[pharmgkb_*_raw]
        B4[cpic_guidelines_raw]
    end

    subgraph Silver["Silver — conformed"]
        S1[variants]
        S2[populations]
        S3[clinical_variants]
        S4[drug_recommendations]
        S5[pharmacogenes]
    end

    subgraph Gold["Gold — analytical (Iceberg)"]
        Go1[allele_frequencies_by_population]
        Go2[phenotype_distribution_by_population]
        Go3[drug_impact_summary]
        Go4[actionability_ranking]
    end

    subgraph Export
        J1[artifacts/*.json]
        KB[UpdateBedrockKB\nPASS — future phase]
    end

    G --> B1 & B2
    P --> B3
    C --> B4
    B1 & B2 --> S1 & S2
    B3 --> S3 & S4
    B4 --> S4
    S1 & S2 & S3 & S4 --> Go1 & Go2 & Go3 & Go4
    Go4 --> J1
    Go1 & Go2 & Go3 --> J1
    Go1 --> KB
```

See [`docs/architecture.md`](docs/architecture.md) for the full medallion + Step Functions design.

## Data sources

| Source | URL | License | Refresh cadence |
|--------|-----|---------|-----------------|
| 1000 Genomes Project Phase 3 | `s3://1000genomes/` (AWS Open Data) | [Data Use Policy](https://www.internationalgenome.org/data) | Static (Phase 3 final) |
| PharmGKB | [pharmgkb.org/downloads](https://www.pharmgkb.org/downloads) | [CC BY 4.0](https://creativecommons.org/licenses/by/4.0/) | Quarterly |
| CPIC Guidelines | [cpicpgx.org](https://cpicpgx.org/guidelines/) | [CC BY 4.0](https://creativecommons.org/licenses/by/4.0/) | Per guideline update |

## Running locally

### Prerequisites

- Python 3.11+
- [`uv`](https://github.com/astral-sh/uv) (recommended) or pip
- Java 11+ (for PySpark in Phase 2)
- AWS CLI configured with profile `pgx-latam-dev` (Phase 4+)

### Setup

```bash
# Clone and install
git clone https://github.com/enriqew/pgx-latam-atlas.git
cd pgx-latam-atlas
uv pip install -e ".[dev,spark]"
pre-commit install

# Configure environment
cp .env.example .env
# Edit .env with your values

# Run full local pipeline (Phase 1–3, no AWS required)
make dry-run
```

### Make targets

```
make install        Install runtime dependencies
make install-dev    Install all dependencies + pre-commit hooks
make lint           Run ruff linter
make fmt            Run ruff formatter
make typecheck      Run mypy strict checks
make test           Run unit tests (excludes smoke + integration)
make test-smoke     Run smoke tests (hits real external URLs)
make ingest-local   Ingest raw data into data/bronze/
make transform-local Build silver tables locally
make export-local   Build gold + export artifacts/ JSONs
make dry-run        Full local pipeline end-to-end
make tf-plan        Show Terraform plan (no apply)
```

**Estimated AWS cost for a full pipeline run:** ~$2–5 USD (Glue DPU-hours + Athena scanned bytes).
Athena costs are minimized by Iceberg partition pruning on `gene_symbol` and `population_code`.

## Caveats

- **Sample sizes**: MXL n=64, PEL n=85, CLM n=94, PUR n=104. All confidence intervals use Wilson score.
- **CYP2D6 out of scope**: CNV complexity and star-allele calling require Aldy/PyPGx — excluded explicitly. See [`src/pgx_latam/utils/star_allele_scope.py`](src/pgx_latam/utils/star_allele_scope.py).
- **Common-variant focus**: MAF > 1% filter applied. Rare variants require larger cohorts for reliable frequency estimates.
- **"Latino" is not homogeneous**: MXL (Mexican ancestry in Los Angeles), PEL (Peruvians in Lima), CLM (Colombians in Medellín), PUR (Puerto Ricans in Puerto Rico) are reported separately throughout. They are never pooled into a single "Latino" category.
- **Diplotype inference**: This pipeline counts allele frequencies; it does not call diplotypes or phenotypes for multi-variant genes (e.g., CYP2C19 \*2 + \*17 compound heterozygotes require phased haplotypes).

## License

Code is MIT licensed. Data sources must be cited per their own terms:
- 1000 Genomes: cite the Phase 3 paper (PMID 26432245).
- PharmGKB: cite PharmGKB per [pharmgkb.org/page/citingPharmGKB](https://www.pharmgkb.org/page/citingPharmGKB).
- CPIC: cite per [cpicpgx.org/guidelines/](https://cpicpgx.org/guidelines/).
