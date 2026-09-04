# Portfolio Integration

> **Superseded.** This document describes a build-time fetch and Lambda delivery
> architecture that was never built. The artifacts reach the portfolio by being
> copied into `src/data/pgx/` (and `public/data/pgx/` for the large allele
> frequency file) after a pipeline run, and are served as static files from
> CloudFront. Kept for the design discussion; do not follow it as instructions.

This document describes how `data-dive-design-hub` (the React/Vite portfolio) should consume
artifacts from `pgx-latam-atlas`. **Apply these changes manually in a separate session
targeting the `data-dive-design-hub` repository.**

---

## Artifact delivery model

After each successful pipeline run, the Step Functions workflow invokes a Lambda
(`ExportArtifacts` state) that commits the updated JSON files to `artifacts/` in this
repository via the GitHub API. The portfolio fetches these files at **Vite build time**
using raw GitHub URLs.

This means:
- The portfolio always reflects the last successful pipeline run.
- No runtime API calls; artifacts are static.
- Vite's `fetch` during build reads the JSON and bundles or inlines it as needed.

---

## Changes to apply in `data-dive-design-hub`

### 1. Add artifact fetch utility

Create `src/lib/pgxAtlas.ts` (or `.js`):

```typescript
const ARTIFACTS_BASE =
  "https://raw.githubusercontent.com/enriqew/pgx-latam-atlas/main/artifacts";

export async function fetchPgxArtifact<T>(filename: string): Promise<T> {
  const response = await fetch(`${ARTIFACTS_BASE}/${filename}`);
  if (!response.ok) {
    throw new Error(`Failed to fetch pgx artifact: ${filename} (${response.status})`);
  }
  return response.json() as Promise<T>;
}

// Typed helpers
export const fetchActionabilityRanking = () =>
  fetchPgxArtifact<ActionabilityRankingEntry[]>("actionability_ranking.json");

export const fetchAlleleFrequencies = () =>
  fetchPgxArtifact<AlleleFrequencyEntry[]>("allele_frequencies.json");

export const fetchDrugImpactSummary = () =>
  fetchPgxArtifact<DrugImpactEntry[]>("drug_impact_summary.json");

export const fetchMetadata = () =>
  fetchPgxArtifact<PgxMetadata>("metadata.json");
```

### 2. Add TypeScript types

Create `src/types/pgx.ts`:

```typescript
export interface ActionabilityRankingEntry {
  rank_position: number;
  drug_name: string;
  gene_symbol: string;
  population_code: string;
  delta_vs_baseline: number;
  population_affected_pct: number;
  classification_strength: string;
  clinical_implication: string;
  snapshot_date: string;
}

export interface AlleleFrequencyEntry {
  variant_id: string;
  gene_symbol: string;
  population_code: string;
  allele_frequency: number;
  ci_lower_wilson: number;
  ci_upper_wilson: number;
  delta_vs_ceu: number;
  is_actionable: boolean;
  snapshot_date: string;
}

export interface DrugImpactEntry {
  drug_name: string;
  gene_symbol: string;
  population_code: string;
  population_total: number;
  individuals_requiring_change: number;
  percentage_requiring_change: number;
  baseline_ceu_percentage: number;
  delta_vs_baseline: number;
  classification_strength: string;
  snapshot_date: string;
}

export interface PgxMetadata {
  schema_version: string;
  snapshot_date: string;
  source_versions: {
    thousand_genomes: string;
    pharmgkb: string;
    cpic: string;
  };
  populations: Record<string, number>;
  total_variants_analyzed: number;
  pipeline_run_id: string;
}
```

### 3. Add project card to the portfolio

In the portfolio's project list (wherever other projects are defined), add an entry for
`pgx-latam-atlas`:

```typescript
{
  id: "pgx-latam-atlas",
  title: "pgx-latam-atlas",
  description:
    "Pharmacogenomic variant frequencies and drug response divergence across " +
    "Latin American populations. Identifies which drug–gene pairs carry the " +
    "greatest clinical divergence for MXL, PEL, CLM, and PUR cohorts vs " +
    "European baseline — data absent from most prescribing guidance.",
  tags: ["Pharmacogenomics", "AWS", "PySpark", "Athena", "Iceberg", "Python"],
  repoUrl: "https://github.com/enriqew/pgx-latam-atlas",
  featured: true,
}
```

### 4. Add pgx-latam section to portfolio README

In `data-dive-design-hub/README.md`, add under the projects section:

```markdown
### pgx-latam-atlas

Pharmacogenomic variant frequencies and drug response divergence across Latin American
populations (MXL, PEL, CLM, PUR). Data engineering pipeline using AWS Glue, Athena
(Iceberg), and Step Functions. Outputs actionable frequency deltas for 11 pharmacogenes
across 8+ drugs with CPIC A-level guidelines.

→ [Repository](https://github.com/enriqew/pgx-latam-atlas)
```

---

## Alternative: git submodule approach

If you prefer fully reproducible builds (every `npm run build` uses an exact commit of
the artifacts), add `pgx-latam-atlas` as a git submodule:

```bash
# In data-dive-design-hub root
git submodule add https://github.com/enriqew/pgx-latam-atlas.git public/pgx-latam-atlas
git submodule update --init --recursive
```

Then in `vite.config.ts`, alias the artifacts path:

```typescript
resolve: {
  alias: {
    "@pgx-artifacts": path.resolve(__dirname, "public/pgx-latam-atlas/artifacts"),
  },
},
```

And import directly:

```typescript
import actionabilityRanking from "@pgx-artifacts/actionability_ranking.json";
```

**Trade-off**: raw URL fetch is simpler and always current; submodule gives reproducible
builds but requires `git submodule update` to pick up new pipeline runs.

---

## ExportArtifacts Lambda

Source: `src/lambda/export_artifacts/handler.py`

The Lambda runs as the final step of the Step Functions pipeline:
1. Queries the Athena `gold_pgx.*` tables (no `SELECT *` — columns enumerated explicitly)
2. For `allele_frequencies`, filters to the ~11 key pharmacogenomic variant positions
   (the full 182 k-row table is ~86 MB and exceeds GitHub's recommended file size)
3. Commits each artifact to `artifacts/` in this repo via the GitHub Contents API
4. Dependencies: `requests` only — all else uses the built-in boto3 Lambda runtime

Deployment: the CI pipeline (`deploy.yml` → `sync-glue-scripts` job) packages
`handler.py` + `requests` into a zip, uploads to the Glue scripts S3 bucket, then
calls `aws lambda update-function-code` to push the new code. Terraform manages the
Lambda resource definition (permissions, config) but not the code artifact.

---

## Allele frequencies: full dataset vs. key-variant subset

| Artifact committed to GitHub | ~50 rows × 5 populations — key pharmacogene positions only |
|------------------------------|------------------------------------------------------------|
| Full dataset in S3           | 182,465 rows at `s3://<LAKE_BUCKET>/gold/allele_frequencies_by_population/` |

To display the full allele frequencies dataset in the portfolio, query the gold Athena
table directly or use a presigned S3 URL. For the ranked summary and phenotype charts,
the committed artifacts are sufficient.

---

## GitHub PAT for artifact commits

The `ExportArtifacts` Lambda writes JSON files to this repository via the GitHub API.
The PAT is stored in AWS Secrets Manager (secret name: `pgx-latam/github-pat`) with
minimum required scopes:

- `contents:write` — scoped to the `pgx-latam-atlas` repository only

The portfolio repository is **never written to** by the pipeline. Only `pgx-latam-atlas`
receives commits from the Lambda.
