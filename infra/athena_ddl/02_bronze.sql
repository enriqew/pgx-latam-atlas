-- Bronze layer: raw ingestion tables
-- ${LAKE_BUCKET} is substituted at deploy time by Terraform local_file or scripts/deploy.sh

CREATE EXTERNAL TABLE IF NOT EXISTS bronze_pgx.genomes_variants_raw (
    chromosome          STRING,
    position            BIGINT,
    variant_id          STRING,
    reference_allele    STRING,
    alternate_allele    STRING,
    sample_id           STRING,
    genotype            STRING,
    allele_dosage       INT,
    quality             DOUBLE,
    filter_status       STRING,
    info_payload        STRING
)
PARTITIONED BY (
    ingest_date         STRING,
    chromosome_part     STRING
)
STORED AS PARQUET
LOCATION 's3://${LAKE_BUCKET}/bronze/genomes_variants_raw/'
TBLPROPERTIES (
    'parquet.compression' = 'SNAPPY'
);


CREATE EXTERNAL TABLE IF NOT EXISTS bronze_pgx.samples_metadata_raw (
    sample_id           STRING,
    population_code     STRING,
    superpopulation     STRING,
    sex                 STRING,
    family_id           STRING
)
PARTITIONED BY (ingest_date STRING)
STORED AS PARQUET
LOCATION 's3://${LAKE_BUCKET}/bronze/samples_metadata_raw/';


CREATE EXTERNAL TABLE IF NOT EXISTS bronze_pgx.pharmgkb_clinical_annotations_raw (
    clinical_annotation_id      STRING,
    variant_or_haplotype        STRING,
    gene_symbol                 STRING,
    drug_names                  STRING,
    phenotype_categories        STRING,
    evidence_level              STRING,
    clinical_annotation_types   STRING,
    pediatric                   STRING,
    annotation_text             STRING
)
PARTITIONED BY (ingest_date STRING)
STORED AS PARQUET
LOCATION 's3://${LAKE_BUCKET}/bronze/pharmgkb_clinical_annotations_raw/';


CREATE EXTERNAL TABLE IF NOT EXISTS bronze_pgx.pharmgkb_var_drug_ann_raw (
    annotation_id       STRING,
    variant_rsid        STRING,
    gene_symbol         STRING,
    drug_name           STRING,
    pmid                STRING,
    phenotype_category  STRING,
    significance        STRING,
    notes               STRING,
    sentence            STRING,
    alleles             STRING
)
PARTITIONED BY (ingest_date STRING)
STORED AS PARQUET
LOCATION 's3://${LAKE_BUCKET}/bronze/pharmgkb_var_drug_ann_raw/';


CREATE EXTERNAL TABLE IF NOT EXISTS bronze_pgx.pharmgkb_drugs_raw (
    pharmgkb_drug_id    STRING,
    drug_name           STRING,
    generic_names       STRING,
    trade_names         STRING,
    drug_type           STRING,
    atc_identifiers     STRING,
    rxnorm_identifiers  STRING
)
PARTITIONED BY (ingest_date STRING)
STORED AS PARQUET
LOCATION 's3://${LAKE_BUCKET}/bronze/pharmgkb_drugs_raw/';


CREATE EXTERNAL TABLE IF NOT EXISTS bronze_pgx.pharmgkb_genes_raw (
    pharmgkb_gene_id    STRING,
    gene_symbol         STRING,
    ensembl_id          STRING,
    ncbi_gene_id        STRING,
    chromosome          STRING,
    chromosomal_start   BIGINT,
    chromosomal_end     BIGINT
)
PARTITIONED BY (ingest_date STRING)
STORED AS PARQUET
LOCATION 's3://${LAKE_BUCKET}/bronze/pharmgkb_genes_raw/';


CREATE EXTERNAL TABLE IF NOT EXISTS bronze_pgx.cpic_guidelines_raw (
    guideline_id            STRING,
    gene_symbol             STRING,
    drug_name               STRING,
    phenotype               STRING,
    activity_score          STRING,
    recommendation_text     STRING,
    classification_strength STRING,
    cpic_release_version    STRING
)
PARTITIONED BY (ingest_date STRING)
STORED AS PARQUET
LOCATION 's3://${LAKE_BUCKET}/bronze/cpic_guidelines_raw/';
