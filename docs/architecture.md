# Architecture

## Overview

`pgx-latam-atlas` follows a **medallion architecture** (Bronze → Silver → Gold) on AWS,
orchestrated by Step Functions. All tables use S3 as the underlying storage layer, with
Athena (Iceberg) for analytical queries and AWS Glue for heavy ETL.

## Medallion layers

### Bronze: raw ingestion

Raw data lands here with minimal transformation. Partitioned by `ingest_date` so failed
runs can be reprocessed without overwriting prior snapshots. Schema mirrors the source
exactly; no business logic applied.

| Table | Source | Format |
|-------|--------|--------|
| `genomes_variants_raw` | 1000 Genomes VCF (S3 Open Data) | Parquet/SNAPPY |
| `samples_metadata_raw` | 1000 Genomes panel file | Parquet |
| `pharmgkb_clinical_annotations_raw` | PharmGKB TSV release | Parquet |
| `pharmgkb_var_drug_ann_raw` | PharmGKB TSV release | Parquet |
| `pharmgkb_drugs_raw` | PharmGKB TSV release | Parquet |
| `pharmgkb_genes_raw` | PharmGKB TSV release | Parquet |
| `cpic_guidelines_raw` | CPIC JSON API | Parquet |

### Silver: conformed

Typed, deduplicated, business-key–stable tables. Joins between sources happen here.
No aggregations yet.

| Table | Description |
|-------|-------------|
| `populations` | 1000G population codes with names, superpopulations, and sample sizes |
| `pharmacogenes` | In-scope genes with coordinates and scope rationale |
| `variants` | Per-sample genotype calls for pharmacogene regions |
| `clinical_variants` | PharmGKB annotations joined to rsIDs |
| `drug_recommendations` | CPIC prescribing guidance per gene–drug–phenotype |

### Gold: analytical (Apache Iceberg)

Aggregate tables ready for portfolio export and (future) Bedrock Knowledge Base ingestion.
Each row carries a `snapshot_date` column for lineage. Uses Iceberg for schema evolution
and time-travel queries.

| Table | Description |
|-------|-------------|
| `allele_frequencies_by_population` | Allele counts, frequencies, and Wilson CIs per variant × population |
| `phenotype_distribution_by_population` | Inferred phenotype percentages per gene × population |
| `drug_impact_summary` | Percentage of individuals requiring dose change or alternative per drug × population |
| `actionability_ranking` | Top drug–gene pairs ranked by delta vs CEU baseline |

## Step Functions state machine

```
Parallel(IngestGenomes, IngestPharmGKB, IngestCPIC)
  → Each → ValidateRowCounts (Lambda)
  → Sync
  → Parallel(
      BuildSilverVariants (Glue),
      BuildSilverClinical (Athena CTAS)
    )
  → BuildSilverPopulations (Athena CTAS)
  → Parallel(
      BuildGoldAlleleFrequencies (Athena MERGE INTO),
      BuildGoldPhenotypeDistribution (Athena MERGE INTO)
    )
  → BuildGoldDrugImpact (Athena MERGE INTO)
  → BuildGoldActionabilityRanking (Athena MERGE INTO)
  → Parallel(
      ExportArtifacts (Lambda → GitHub API),
      UpdateBedrockKB  ← Pass state (TODO: replace with Bedrock KB sync)
    )
```

Any state failure routes to `NotifyFailure` (SNS). All Lambda tasks have exponential
retry with 3 attempts, backoff rate 2.0.

## Infrastructure

- **S3 lake bucket**: `pgx-latam-lake`: versioning enabled, lifecycle rules for bronze
  partitions older than 90 days (Glacier transition).
- **S3 state bucket**: separate from lake; hosts Terraform remote state + DynamoDB lock table.
- **Glue catalog**: `awsdatacatalog."pgx_latam_catalog"`: three databases (bronze_pgx,
  silver_pgx, gold_pgx).
- **Athena workgroup**: dedicated workgroup with per-query data scanned limit (100 GB default).
- **IAM**: least-privilege roles per component. Glue role, Step Functions role, Lambda
  execution role, all separate.

## CI/CD

- **PR workflow** (read-only): `ruff` + `mypy` + `pytest` (no AWS needed).
- **Main workflow** (write): `terraform plan` output posted as PR comment; no auto-apply.
- AWS authentication uses OIDC, no long-lived access keys in GitHub Secrets.

## Future work: Bedrock agent

When the gold layer is stable, a conversational agent can be layered on top without
changing the data model. The plan:

**Knowledge Base sources** (all Iceberg tables, exposed as S3 data source to Bedrock):
- `allele_frequencies_by_population`: for variant-level frequency questions
- `phenotype_distribution_by_population`: for phenotype distribution questions
- `drug_impact_summary`: for drug-specific impact questions
- `actionability_ranking`: for "what matters most for this population?" queries

**Expected query types**:
- "What is the CYP2C19 \*2 frequency in Mexican ancestry individuals, and how does it
  compare to European populations?"
- "Which drugs in the cardiovascular class have the largest dosing divergence for
  Peruvian patients?"
- "List all CPIC A-level recommendations for genes with >10% frequency difference
  between MXL and CEU."

**Migration path**: The `UpdateBedrockKB` state in Step Functions is currently a `Pass`
state. Changing `"Type": "Pass"` to `"Type": "Task"` with an appropriate Lambda ARN
that calls `bedrock-agent:StartIngestionJob` is the only pipeline change needed.

The Bedrock Knowledge Base, data source, and agent resources will be added to Terraform
in a separate `bedrock.tf` file. The Bedrock agent will use an action group backed by
a Lambda that queries Athena gold tables directly for structured lookups outside the
KB's semantic search scope.
