"""AWS Glue job: build silver/variants/ + silver/populations/ from bronze on S3.

Invoked by the Step Functions BuildSilverVariants state via:
    aws glue start-job-run --job-name pgx-latam-dev-build-silver-variants

Required job parameters (passed as --key=value Glue arguments):
    --lake_bucket      S3 bucket name, e.g. pgx-latam-lake-123456789012
    --ingest_date      Bronze partition to read, e.g. 2025-05-17
"""

from __future__ import annotations

import sys

from awsglue.context import GlueContext
from awsglue.job import Job
from awsglue.utils import getResolvedOptions
from pyspark.context import SparkContext
from pyspark.sql import DataFrame, SparkSession
from pyspark.sql import functions as F
from pyspark.sql.types import IntegerType, LongType, StringType

# ── Job bootstrap ─────────────────────────────────────────────────────────────

args = getResolvedOptions(sys.argv, ["JOB_NAME", "lake_bucket", "ingest_date"])

sc = SparkContext()
glue_ctx = GlueContext(sc)
spark: SparkSession = glue_ctx.spark_session
job = Job(glue_ctx)
job.init(args["JOB_NAME"], args)

LAKE_BUCKET = args["lake_bucket"]
INGEST_DATE = args["ingest_date"]
BRONZE_BASE = f"s3://{LAKE_BUCKET}/bronze"
SILVER_BASE = f"s3://{LAKE_BUCKET}/silver"

TARGET_POPULATIONS = ("MXL", "PEL", "CLM", "PUR", "CEU")

# GRCh37 gene boundaries — must match thousand_genomes.py
GENE_REGIONS: dict[str, tuple[str, int, int]] = {
    "CYP2C19": ("chr10", 96_522_463, 96_612_671),
    "CYP2C9":  ("chr10", 96_698_415, 96_749_148),
    "SLCO1B1": ("chr12", 21_282_444, 21_394_730),
    "VKORC1":  ("chr16", 31_102_175, 31_106_234),
    "TPMT":    ("chr6",  18_128_556, 18_155_418),
    "NUDT15":  ("chr13", 48_600_074, 48_609_007),
    "DPYD":    ("chr1",  97_543_300, 98_386_615),
    "G6PD":    ("chrX", 153_759_605, 153_798_257),
    "IFNL3":   ("chr19", 39_729_165, 39_756_700),
    "CYP3A5":  ("chr7",  99_245_817, 99_277_621),
}

POPULATION_NAMES: dict[str, tuple[str, str]] = {
    "MXL": ("Mexican Ancestry in Los Angeles, California", "Latin America"),
    "PEL": ("Peruvians in Lima, Peru", "Latin America"),
    "CLM": ("Colombians in Medellín, Colombia", "Latin America"),
    "PUR": ("Puerto Ricans in Puerto Rico", "Latin America"),
    "CEU": (
        "Utah Residents (CEPH) with Northern and Western European Ancestry",
        "Europe",
    ),
}

# ── Gene assignment UDF ───────────────────────────────────────────────────────

gene_regions_bc = spark.sparkContext.broadcast(GENE_REGIONS)


def _assign_gene(chrom: str | None, pos: int | None) -> str | None:
    if chrom is None or pos is None:
        return None
    for gene, (g_chrom, g_start, g_end) in gene_regions_bc.value.items():
        if chrom == g_chrom and g_start <= pos <= g_end:
            return gene
    return None


assign_gene_udf = F.udf(_assign_gene, StringType())

# ── Read bronze ───────────────────────────────────────────────────────────────

variants_path = (
    f"{BRONZE_BASE}/genomes_variants_raw/ingest_date={INGEST_DATE}"
)
samples_path = (
    f"{BRONZE_BASE}/samples_metadata_raw/ingest_date={INGEST_DATE}"
)

variants_df: DataFrame = spark.read.parquet(variants_path)
samples_df: DataFrame = spark.read.parquet(samples_path)

# ── Filter to target populations ──────────────────────────────────────────────

target_samples_df = samples_df.filter(
    F.col("population_code").isin(list(TARGET_POPULATIONS))
)

# ── Assign gene symbols ───────────────────────────────────────────────────────

variants_with_gene = variants_df.withColumn(
    "gene_symbol",
    assign_gene_udf(F.col("chromosome"), F.col("position").cast(LongType())),
).filter(F.col("gene_symbol").isNotNull())

# ── Join with sample metadata ─────────────────────────────────────────────────

joined = variants_with_gene.join(
    target_samples_df.select("sample_id", "population_code", "superpopulation"),
    on="sample_id",
    how="inner",
).drop_duplicates(["sample_id", "variant_id"])

silver_variants = joined.select(
    F.col("sample_id"),
    F.col("variant_id"),
    F.col("gene_symbol"),
    F.col("chromosome"),
    F.col("position").cast(LongType()),
    F.col("reference_allele"),
    F.col("alternate_allele"),
    F.col("genotype"),
    F.col("allele_dosage").cast(IntegerType()),
    F.col("population_code"),
    F.col("superpopulation"),
)

# ── Write silver/variants/ ────────────────────────────────────────────────────

silver_variants.write.mode("overwrite").partitionBy(
    "gene_symbol", "population_code"
).parquet(f"{SILVER_BASE}/variants/")

# ── Build and write silver/populations/ ───────────────────────────────────────

pop_sizes = (
    target_samples_df.groupBy("population_code", "superpopulation")
    .agg(F.count("sample_id").alias("sample_size"))
)

pop_names_bc = spark.sparkContext.broadcast(POPULATION_NAMES)

_get_pop_name = F.udf(
    lambda code: pop_names_bc.value.get(code, (code, "Unknown"))[0],
    StringType(),
)
_get_region = F.udf(
    lambda code: pop_names_bc.value.get(code, (code, "Unknown"))[1],
    StringType(),
)

silver_populations = pop_sizes.withColumn(
    "population_name", _get_pop_name(F.col("population_code"))
).withColumn(
    "region", _get_region(F.col("population_code"))
).select(
    "population_code", "population_name", "superpopulation", "region",
    F.col("sample_size").cast(IntegerType()),
)

silver_populations.write.mode("overwrite").parquet(
    f"{SILVER_BASE}/populations/"
)

# ── Commit ────────────────────────────────────────────────────────────────────

job.commit()
