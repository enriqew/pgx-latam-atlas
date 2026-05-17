output "lake_bucket_name" {
  description = "Name of the S3 data lake bucket"
  value       = aws_s3_bucket.lake.bucket
}

output "lake_bucket_arn" {
  description = "ARN of the S3 data lake bucket"
  value       = aws_s3_bucket.lake.arn
}

output "athena_workgroup_name" {
  description = "Name of the Athena workgroup"
  value       = aws_athena_workgroup.pgx.name
}

output "glue_role_arn" {
  description = "ARN of the Glue execution IAM role"
  value       = aws_iam_role.glue_execution.arn
}

output "step_functions_role_arn" {
  description = "ARN of the Step Functions execution IAM role"
  value       = aws_iam_role.step_functions_execution.arn
}

output "pipeline_state_machine_arn" {
  description = "ARN of the pgx-latam pipeline Step Functions state machine"
  value       = aws_sfn_state_machine.pgx_pipeline.arn
}

output "failure_sns_topic_arn" {
  description = "ARN of the pipeline failure SNS topic"
  value       = aws_sns_topic.pipeline_failure.arn
}
