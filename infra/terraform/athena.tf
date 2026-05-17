resource "aws_athena_workgroup" "pgx" {
  name = var.athena_workgroup_name

  configuration {
    enforce_workgroup_configuration    = true
    publish_cloudwatch_metrics_enabled = true

    result_configuration {
      output_location = "s3://${aws_s3_bucket.lake.bucket}/${var.athena_output_prefix}/"

      encryption_configuration {
        encryption_option = "SSE_S3"
      }
    }

    bytes_scanned_cutoff_per_query = var.athena_data_scanned_limit_gb * 1024 * 1024 * 1024
  }
}
