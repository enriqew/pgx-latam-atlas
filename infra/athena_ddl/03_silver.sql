-- Silver layer: conformed, typed, deduplicated tables
-- ${LAKE_BUCKET} is substituted at deploy time

CREATE EXTERNAL TABLE IF NOT EXISTS silver_pgx.populations (
    population_code     STRING,
    population_name     STRING,
    superpopulation     STRING,
    region              STRING,
    sample_size         INT
)
STORED AS PARQUET
LOCATION 's3://${LAKE_BUCKET}/silver/populations/';


CREATE EXTERNAL TABLE IF NOT EXISTS silver_pgx.pharmacogenes (
    gene_symbol         STRING,
    ensembl_id          STRING,
    ncbi_gene_id        STRING,
    chromosome          STRING,
    chromosomal_start   BIGINT,
    chromosomal_end     BIGINT,
    is_in_scope         BOOLEAN,
    scope_rationale     STRING
)
STORED AS PARQUET
LOCATION 's3://${LAKE_BUCKET}/silver/pharmacogenes/';


CREATE EXTERNAL TABLE IF NOT EXISTS silver_pgx.variants (
    sample_id           STRING,
    variant_id          STRING,
    gene_symbol         STRING,
    chromosome          STRING,
    position            BIGINT,
    reference_allele    STRING,
    alternate_allele    STRING,
    genotype            STRING,
    allele_dosage       INT,
    population_code     STRING,
    superpopulation     STRING
)
PARTITIONED BY (
    gene_symbol_part    STRING,
    population_part     STRING
)
STORED AS PARQUET
LOCATION 's3://${LAKE_BUCKET}/silver/variants/';


CREATE EXTERNAL TABLE IF NOT EXISTS silver_pgx.clinical_variants (
    variant_rsid        STRING,
    gene_symbol         STRING,
    drug_name           STRING,
    phenotype_category  STRING,
    evidence_level      STRING,
    is_actionable       BOOLEAN,
    annotation_summary  STRING
)
STORED AS PARQUET
LOCATION 's3://${LAKE_BUCKET}/silver/clinical_variants/';


CREATE EXTERNAL TABLE IF NOT EXISTS silver_pgx.drug_recommendations (
    gene_symbol             STRING,
    drug_name               STRING,
    phenotype               STRING,
    recommendation_text     STRING,
    classification_strength STRING,
    requires_dose_change    BOOLEAN,
    requires_alternative    BOOLEAN,
    cpic_release_version    STRING
)
STORED AS PARQUET
LOCATION 's3://${LAKE_BUCKET}/silver/drug_recommendations/';
