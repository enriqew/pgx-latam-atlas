# Artifacts

Static JSON files exported from the gold layer of the pgx-latam-atlas pipeline.
These files are consumed by the `data-dive-design-hub` portfolio at Vite build time.

Last refresh: see `metadata.json` → `snapshot_date`.

---

## Files

### `schema_version.json`

```json
{ "version": "1.0.0" }
```

Bump the version whenever the schema of any artifact file changes in a breaking way.
The portfolio should check this before parsing other files.

---

### `metadata.json`

Pipeline run metadata. Always read this first to understand the freshness of the data.

| Field | Type | Description |
|-------|------|-------------|
| `schema_version` | string | Schema version (matches `schema_version.json`) |
| `snapshot_date` | ISO 8601 date | Date when the gold tables were last updated |
| `source_versions.thousand_genomes` | string | 1000G Phase 3 release identifier |
| `source_versions.pharmgkb` | string | PharmGKB release date/version used |
| `source_versions.cpic` | string | CPIC release version used |
| `populations` | object | Map of population_code → sample_size |
| `total_variants_analyzed` | integer | Variant-population observations: distinct positions times cohorts, not distinct positions |
| `pipeline_run_id` | string | Step Functions execution ID |

---

### `allele_frequencies.json`

Array of allele frequency records for actionable variants across all in-scope populations.
Filtered to `is_actionable = true` variants only. Sorted by `gene_symbol`, then `population_code`.

| Field | Type | Description |
|-------|------|-------------|
| `variant_id` | string | rsID (e.g., "rs4244285") |
| `gene_symbol` | string | HGNC gene symbol |
| `population_code` | string | 1000G population code (MXL, PEL, CLM, PUR, CEU) |
| `allele_frequency` | float [0,1] | Alternate allele frequency |
| `ci_lower_wilson` | float [0,1] | 95% Wilson CI lower bound |
| `ci_upper_wilson` | float [0,1] | 95% Wilson CI upper bound |
| `delta_vs_ceu` | float | allele_frequency - CEU allele_frequency |
| `is_actionable` | boolean | True if PharmGKB evidence level 1A or 1B |
| `snapshot_date` | ISO 8601 date | Row-level freshness date |

---

### `phenotype_distribution.json`

Array of phenotype distribution records per gene × population.

| Field | Type | Description |
|-------|------|-------------|
| `gene_symbol` | string | HGNC gene symbol |
| `population_code` | string | 1000G population code |
| `phenotype_category` | string | CPIC phenotype (PM, IM, NM, RM, UM, Indeterminate) |
| `individual_count` | integer | Individuals with this phenotype in the population |
| `population_total` | integer | Total individuals in the population |
| `phenotype_percentage` | float [0,100] | percentage = individual_count / population_total × 100 |
| `ci_lower_wilson` | float [0,1] | 95% Wilson CI lower bound (on proportion) |
| `ci_upper_wilson` | float [0,1] | 95% Wilson CI upper bound (on proportion) |
| `snapshot_date` | ISO 8601 date | Row-level freshness date |

---

### `drug_impact_summary.json`

Array of drug impact records: what percentage of a population requires dose change or
alternative therapy for a given drug–gene pair.

| Field | Type | Description |
|-------|------|-------------|
| `drug_name` | string | Drug name (lowercase, generic) |
| `gene_symbol` | string | HGNC gene symbol |
| `population_code` | string | 1000G population code |
| `population_total` | integer | Total individuals in the population |
| `individuals_requiring_change` | integer | Individuals with actionable phenotype |
| `percentage_requiring_change` | float [0,100] | Percentage requiring dose change or alternative |
| `baseline_ceu_percentage` | float [0,100] | Same metric for the CEU reference population |
| `delta_vs_baseline` | float | percentage_requiring_change - baseline_ceu_percentage |
| `classification_strength` | string | CPIC classification (Strong, Moderate, Optional) |
| `snapshot_date` | ISO 8601 date | Row-level freshness date |

---

### `actionability_ranking.json`

Top drug–gene–population combinations ranked by absolute delta vs CEU baseline.
Capped at top 50 entries to keep file size small.

| Field | Type | Description |
|-------|------|-------------|
| `rank_position` | integer | Rank (1 = largest delta) |
| `drug_name` | string | Drug name |
| `gene_symbol` | string | HGNC gene symbol |
| `population_code` | string | 1000G population code |
| `delta_vs_baseline` | float | Absolute delta vs CEU baseline (percentage points) |
| `population_affected_pct` | float [0,100] | Percentage of population requiring change |
| `classification_strength` | string | CPIC classification strength |
| `clinical_implication` | string | Human-readable implication sentence |
| `snapshot_date` | ISO 8601 date | Row-level freshness date |
