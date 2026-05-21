resource "aws_sns_topic" "pipeline_failure" {
  name = "${local.name_prefix}-pipeline-failure"
}

resource "aws_sns_topic_subscription" "pipeline_failure_email" {
  topic_arn = aws_sns_topic.pipeline_failure.arn
  protocol  = "email"
  endpoint  = var.pipeline_failure_email
}

resource "aws_sfn_state_machine" "pgx_pipeline" {
  name     = "${local.name_prefix}-pipeline"
  role_arn = aws_iam_role.step_functions_execution.arn

  definition = templatefile(
    "${path.module}/../../step_functions/pgx_pipeline.asl.json",
    {
      ValidateBronzeLambdaArn          = aws_lambda_function.validate_bronze.arn
      IngestPharmGKBLambdaArn          = aws_lambda_function.ingest_pharmgkb.arn
      IngestCPICLambdaArn              = aws_lambda_function.ingest_cpic.arn
      BuildSilverClinicalLambdaArn     = aws_lambda_function.build_silver_clinical.arn
      BuildSilverPopulationsLambdaArn  = aws_lambda_function.build_silver_populations.arn
      BuildGoldFrequenciesLambdaArn    = aws_lambda_function.build_gold_frequencies.arn
      BuildGoldPhenotypeLambdaArn      = aws_lambda_function.build_gold_phenotype.arn
      BuildGoldDrugImpactLambdaArn     = aws_lambda_function.build_gold_drug_impact.arn
      BuildGoldRankingLambdaArn        = aws_lambda_function.build_gold_ranking.arn
      ExportArtifactsLambdaArn         = aws_lambda_function.export_artifacts.arn
      UpdateBedrockKBLambdaArn         = aws_lambda_function.update_bedrock_kb.arn
      PipelineFailureSNSTopicArn       = aws_sns_topic.pipeline_failure.arn
    }
  )
}
