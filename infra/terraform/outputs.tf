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

output "bedrock_knowledge_base_id" {
  description = "ID of the Bedrock Knowledge Base for PGx queries"
  value       = aws_bedrockagent_knowledge_base.pgx.id
}

output "bedrock_knowledge_base_arn" {
  description = "ARN of the Bedrock Knowledge Base"
  value       = aws_bedrockagent_knowledge_base.pgx.arn
}

output "bedrock_data_source_id" {
  description = "ID of the Bedrock KB data source (Gold docs in S3)"
  value       = aws_bedrockagent_data_source.gold_docs.data_source_id
}

output "opensearch_kb_collection_endpoint" {
  description = "OpenSearch Serverless collection endpoint for the KB vector store"
  value       = aws_opensearchserverless_collection.kb.collection_endpoint
}
