resource "aws_glue_catalog_database" "bronze" {
  name        = "bronze_pgx"
  description = "Raw ingested data, minimal transformations, partitioned by ingest_date"
}

resource "aws_glue_catalog_database" "silver" {
  name        = "silver_pgx"
  description = "Conformed, typed, deduplicated tables with stable business keys"
}

resource "aws_glue_catalog_database" "gold" {
  name        = "gold_pgx"
  description = "Business-logic tables ready for analytical consumption and portfolio export"
}

resource "aws_glue_job" "ingest_genomes_bronze" {
  name         = "${local.name_prefix}-ingest-genomes-bronze"
  role_arn     = aws_iam_role.glue_execution.arn
  glue_version = "4.0"

  command {
    name            = "glueetl"
    script_location = "s3://${aws_s3_bucket.glue_scripts.bucket}/jobs/ingest_genomes_bronze.py"
    python_version  = "3"
  }

  default_arguments = {
    "--job-language"                     = "python"
    "--enable-continuous-cloudwatch-log" = "true"
    "--enable-metrics"                   = "true"
    "--TempDir"                          = "s3://${aws_s3_bucket.lake.bucket}/glue-temp/"
    "--lake_bucket"                      = aws_s3_bucket.lake.bucket
  }

  execution_property {
    max_concurrent_runs = 1
  }

  number_of_workers = 4
  worker_type       = "G.1X"
}

resource "aws_glue_job" "build_silver_variants" {
  name         = "${local.name_prefix}-build-silver-variants"
  role_arn     = aws_iam_role.glue_execution.arn
  glue_version = "4.0"

  command {
    name            = "glueetl"
    script_location = "s3://${aws_s3_bucket.glue_scripts.bucket}/jobs/build_silver_variants.py"
    python_version  = "3"
  }

  default_arguments = {
    "--job-language"                     = "python"
    "--enable-continuous-cloudwatch-log" = "true"
    "--enable-metrics"                   = "true"
    "--TempDir"                          = "s3://${aws_s3_bucket.lake.bucket}/glue-temp/"
    "--lake_bucket"                      = aws_s3_bucket.lake.bucket
  }

  execution_property {
    max_concurrent_runs = 1
  }

  number_of_workers = 8
  worker_type       = "G.2X"
}
