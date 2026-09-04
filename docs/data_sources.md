# Data Sources

All data used in this project is publicly available and requires no special access agreements
beyond accepting standard usage terms. No PHI (protected health information) is involved.

## 1000 Genomes Project Phase 3

| Attribute | Value |
|-----------|-------|
| **Canonical URL** | `s3://1000genomes/` (AWS Open Data Registry) |
| **Registry entry** | https://registry.opendata.aws/1000-genomes/ |
| **License** | [1000 Genomes Data Use Policy](https://www.internationalgenome.org/data) — free for academic and commercial use; cite the Phase 3 paper |
| **Citation** | 1000 Genomes Project Consortium. _A global reference for human genetic variation._ Nature 526, 68–74 (2015). PMID: 26432245 |
| **Data version** | Phase 3 final release (GRCh37/hg19) |
| **Access pattern** | S3 public bucket, no credentials needed. VCF files per chromosome at `s3://1000genomes/release/20130502/` |

### Latin American populations used

| Code | Name | Location | n (samples) |
|------|------|----------|-------------|
| MXL | Mexican Ancestry in Los Angeles, California | Los Angeles, CA, USA | 64 |
| PEL | Peruvians in Lima, Peru | Lima, Peru | 85 |
| CLM | Colombians in Medellín, Colombia | Medellín, Colombia | 94 |
| PUR | Puerto Ricans in Puerto Rico | Puerto Rico | 104 |

### European reference population

| Code | Name | n (samples) |
|------|------|-------------|
| CEU | Utah Residents (CEPH) with Northern and Western European Ancestry | 99 |

CEU is used as the baseline for delta calculations, consistent with the majority of published
pharmacogenomic frequency studies.

### Pharmacogene target regions

Only VCF regions overlapping pharmacogene coordinates (from PharmGKB) are extracted.
This keeps data volumes manageable and avoids processing the full genome unnecessarily.
See `src/pgx_latam/utils/star_allele_scope.py` for the in-scope gene list and rationale.

---

## PharmGKB

| Attribute | Value |
|-----------|-------|
| **Canonical URL** | https://www.pharmgkb.org/downloads |
| **License** | [Creative Commons Attribution-ShareAlike 4.0 International (CC BY-SA 4.0)](https://creativecommons.org/licenses/by-sa/4.0/) — verify against the current ClinPGx data-usage policy before redistributing derived data |
| **Citation** | Whirl-Carrillo M, et al. _An Evidence-Based Framework for Evaluating Pharmacogenomics Knowledge for Personalized Medicine._ Clin Pharmacol Ther. 2021. PMID: 34216021 |
| **Refresh cadence** | Quarterly TSV releases |

### Files used

| File | Description |
|------|-------------|
| `clinical_annotations.tsv` | Clinical variant–drug–phenotype annotations with evidence levels |
| `var_drug_ann.tsv` | Literature-curated variant–drug associations |
| `drugs.tsv` | Drug identifiers (ATC, RxNorm) |
| `genes.tsv` | Gene coordinates and identifiers |

### Evidence levels

PharmGKB uses a tiered evidence system for clinical annotations:

| Level | Meaning |
|-------|---------|
| 1A | Variant is in a CPIC guideline or medical society recommendation |
| 1B | Variant is in a labeled drug (FDA, EMA, etc.) |
| 2A | Variant is in a CPIC guideline (supporting) |
| 2B | Moderate evidence, replicated |
| 3 | Limited evidence |
| 4 | Case report only |

Only levels 1A and 1B are considered `is_actionable = TRUE` in the silver layer.

---

## CPIC (Clinical Pharmacogenomics Implementation Consortium)

| Attribute | Value |
|-----------|-------|
| **Canonical URL** | https://cpicpgx.org/guidelines/ |
| **JSON API** | https://api.cpicpgx.org/v1/guideline |
| **License** | [Creative Commons Attribution 4.0 International (CC BY 4.0)](https://creativecommons.org/licenses/by/4.0/) |
| **Citation** | Relling MV, Klein TE. _CPIC: Clinical Pharmacogenomics Implementation Consortium of the Pharmacogenomics Research Network._ Clin Pharmacol Ther. 2011. PMID: 21270786 |
| **Refresh cadence** | Per-guideline updates (check `cpic_release_version` field) |

### Classification of recommendation strength

| Level | Meaning |
|-------|---------|
| Strong | High confidence; actionable for most patients |
| Moderate | Reasonable confidence; consider individual factors |
| Optional | Applicable in specific circumstances |
| No recommendation | Insufficient evidence |

---

## Data lineage summary

```
s3://1000genomes/ (VCF) ──────────────────────────┐
                                                    ▼
pharmgkb.org/downloads (TSV) ──── Bronze ──── Silver ──── Gold ──── artifacts/*.json
                                                    ▲
api.cpicpgx.org/v1/guideline (JSON) ──────────────┘
```

All ingestion timestamps are recorded in `metadata.json` under `source_versions`.
Reprocessing any partition is idempotent — bronze uses `ingest_date` partitioning,
gold uses Iceberg MERGE INTO (upsert on business key).
