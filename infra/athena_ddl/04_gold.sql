-- Gold layer: analytical Iceberg tables ready for portfolio export and Bedrock KB
-- ${LAKE_BUCKET} is substituted at deploy time
-- All tables include snapshot_date for lineage and Bedrock KB temporal filtering

CREATE TABLE IF NOT EXISTS gold_pgx.allele_frequencies_by_population (
    variant_id                  STRING,
    gene_symbol                 STRING,
    chromosome                  STRING,
    position                    BIGINT,
    population_code             STRING,
    superpopulation             STRING,
    allele_count                INT,
    total_alleles               INT,
    allele_frequency            DOUBLE,
    ci_lower_wilson             DOUBLE,
    ci_upper_wilson             DOUBLE,
    delta_vs_ceu                DOUBLE,
    is_actionable               BOOLEAN,
    snapshot_date               DATE
)
PARTITIONED BY (gene_symbol)
LOCATION 's3://${LAKE_BUCKET}/gold/allele_frequencies_by_population/'
TBLPROPERTIES (
    'table_type'        = 'ICEBERG',
    'format'            = 'PARQUET',
    'write_compression' = 'SNAPPY'
);


CREATE TABLE IF NOT EXISTS gold_pgx.phenotype_distribution_by_population (
    gene_symbol                     STRING,
    population_code                 STRING,
    superpopulation                 STRING,
    phenotype_category              STRING,
    individual_count                INT,
    population_total                INT,
    phenotype_percentage            DOUBLE,
    ci_lower_wilson                 DOUBLE,
    ci_upper_wilson                 DOUBLE,
    snapshot_date                   DATE
)
PARTITIONED BY (gene_symbol)
LOCATION 's3://${LAKE_BUCKET}/gold/phenotype_distribution_by_population/'
TBLPROPERTIES (
    'table_type' = 'ICEBERG',
    'format'     = 'PARQUET'
);


CREATE TABLE IF NOT EXISTS gold_pgx.drug_impact_summary (
    drug_name                       STRING,
    gene_symbol                     STRING,
    population_code                 STRING,
    population_total                INT,
    individuals_requiring_change    INT,
    percentage_requiring_change     DOUBLE,
    baseline_ceu_percentage         DOUBLE,
    delta_vs_baseline               DOUBLE,
    classification_strength         STRING,
    snapshot_date                   DATE
)
PARTITIONED BY (drug_name)
LOCATION 's3://${LAKE_BUCKET}/gold/drug_impact_summary/'
TBLPROPERTIES (
    'table_type' = 'ICEBERG',
    'format'     = 'PARQUET'
);


CREATE TABLE IF NOT EXISTS gold_pgx.actionability_ranking (
    rank_position                   INT,
    drug_name                       STRING,
    gene_symbol                     STRING,
    population_code                 STRING,
    delta_vs_baseline               DOUBLE,
    population_affected_pct         DOUBLE,
    classification_strength         STRING,
    clinical_implication            STRING,
    snapshot_date                   DATE
)
LOCATION 's3://${LAKE_BUCKET}/gold/actionability_ranking/'
TBLPROPERTIES (
    'table_type' = 'ICEBERG',
    'format'     = 'PARQUET'
);
