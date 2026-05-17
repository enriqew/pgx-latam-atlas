# Methodology

## Scope definition

### In-scope pharmacogenes

The following genes are in scope for Phase 1–4. Selection criteria: CPIC Level A or B
guideline exists, PharmGKB evidence level 1A or 1B variant exists, gene region can be
reliably captured from 1000 Genomes short-read WGS data without specialized callers.

| Gene | Key drugs | Rationale |
|------|-----------|-----------|
| CYP2C19 | Clopidogrel, omeprazole, SSRIs | CPIC A-level; star alleles called from SNPs only |
| CYP2C9 | Warfarin, NSAIDs, phenytoin | CPIC A-level; SNP-based calling |
| SLCO1B1 | Statins (simvastatin, atorvastatin) | CPIC A-level; rs4149056 single-variant actionability |
| VKORC1 | Warfarin | CPIC A-level (warfarin dosing algorithm) |
| TPMT | Thiopurines (azathioprine, 6-MP) | CPIC A-level; high-impact in oncology |
| NUDT15 | Thiopurines | CPIC A-level; especially relevant in East/South Asian ancestry |
| DPYD | Fluoropyrimidines (5-FU, capecitabine) | CPIC A-level; HER2+ and GI oncology |
| G6PD | Rasburicase, primaquine | CPIC A-level; high prevalence of deficiency in LATAM |
| IFNL3/4 | Peginterferon | CPIC A-level; HCV treatment (still relevant in LATAM) |
| CYP3A5 | Tacrolimus | CPIC A-level; relevant for solid organ transplant |

### Explicitly out-of-scope genes

| Gene | Reason |
|------|--------|
| CYP2D6 | CNV-driven copy number variation; star-allele calling requires Aldy or PyPGx on WGS BAMs. Short-read VCF is insufficient. Will be addressed in a future phase with a dedicated caller. |
| HLA-B, HLA-A | Imputation-based; not reliably called from standard VCF processing pipeline. |
| RYR1 | Structural variants dominate; not representable as SNP frequencies. |

---

## Allele frequency calculation

### Definition

For a given variant (rsID) in a given population:

```
allele_frequency = allele_count / total_alleles
```

Where:
- `allele_count` = sum of alternate allele dosages across all samples in the population
- `total_alleles` = 2 × number of samples (diploid; X-chromosome adjustments applied for
  hemizygous males in G6PD)

### Wilson score confidence interval

We use the **Wilson score interval** (not the Normal approximation) because it performs
well for proportions near 0 or 1, which is common for rare pharmacogenomic alleles.

```
center = (allele_count + z²/2) / (total_alleles + z²)
half_width = z × sqrt(allele_count × (total_alleles - allele_count) / total_alleles + z²/4)
             / (total_alleles + z²)

ci_lower = center - half_width
ci_upper = center + half_width
```

Where `z = 1.96` for 95% confidence intervals. See `src/pgx_latam/utils/wilson_ci.py`
for the implementation.

### Delta vs CEU baseline

```
delta_vs_ceu = allele_frequency_population - allele_frequency_CEU
```

A positive delta means the alternate (often non-reference) allele is more common in
the Latin American population than in the European reference cohort.

---

## Phenotype inference

For genes where phenotype can be reliably inferred from SNP-based diplotypes
(CYP2C19, CYP2C9, SLCO1B1, VKORC1, TPMT, NUDT15, DPYD), we assign a
phenotype category per individual based on their genotype.

**Phenotype categories used (aligned with CPIC terminology):**

- Poor Metabolizer (PM)
- Intermediate Metabolizer (IM)
- Normal Metabolizer (NM)
- Rapid Metabolizer (RM)
- Ultrarapid Metabolizer (UM)
- Indeterminate

The mapping from diplotype to phenotype follows the CPIC guideline translation tables.
These are sourced from `silver_pgx.drug_recommendations` (CPIC source).

### Diplotype calling limitation

This pipeline **counts allele frequencies** from VCF genotypes. Phased haplotype
information (required for compound heterozygote calling, e.g., CYP2C19 \*2/\*17)
is partially available in 1000G Phase 3 data but is not used in the current
implementation. Phenotype inference here assumes the two most common alleles
per individual; compound heterozygotes may be misclassified at low rates.

---

## Drug impact calculation

For a drug–gene pair, the percentage of individuals requiring a dose change or
alternative therapy is calculated as:

```
percentage_requiring_change = individuals_requiring_change / population_total × 100
```

Where `individuals_requiring_change` = individuals with phenotype categories flagged
as `requires_dose_change = TRUE` or `requires_alternative = TRUE` in
`silver_pgx.drug_recommendations`.

---

## Caveats and limitations

1. **Small sample sizes**: MXL (n=64), PEL (n=85), CLM (n=94), PUR (n=104). Wilson CIs
   are wide for rare alleles. Do not over-interpret point estimates; always report CIs.

2. **"Latino" is not a genetic category**: The four populations have distinct ancestral
   compositions (e.g., MXL has substantial Native American + European + African admixture;
   PEL has high Native American + some African). They are never pooled. Subpopulation
   structure is a real source of heterogeneity.

3. **Reference genome**: 1000G Phase 3 uses GRCh37/hg19. PharmGKB and CPIC guidelines
   typically report variants in dbSNP rsIDs which are genome-build-agnostic, but
   position-based coordinates in DDL files are GRCh37.

4. **No phased haplotypes for compound heterozygotes**: See "Diplotype calling limitation"
   above.

5. **CYP2D6 excluded**: See scope definition above. This is a significant gap for
   antidepressants, antipsychotics, and opioids.

6. **Population as proxy for ancestry**: 1000G population labels represent recruitment
   location and self-reported ancestry, not genetically derived ancestry. Use PCA plots
   in the notebooks for caveat visualization.

7. **Static dataset**: 1000G Phase 3 is a fixed cohort. Results reflect 2012–2013
   recruitment. Newer LATAM sequencing initiatives (e.g., HGDP, TOPMed LATAM components)
   are not included.
