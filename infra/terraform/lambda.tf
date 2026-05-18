# Lambda functions — all share the lambda_execution IAM role.
# export_artifacts has a full implementation in src/lambda/export_artifacts/.
# All other functions are placeholder stubs; implement when Glue migration to Lambda is needed.

locals {
  lambda_runtime = "python3.11"
  lambda_timeout = 300
  lambda_env = {
    LAKE_BUCKET      = aws_s3_bucket.lake.bucket
    ATHENA_WORKGROUP = aws_athena_workgroup.pgx.name
    AWS_REGION_NAME  = var.aws_region
  }
}

# Placeholder zip for initial deployment — replaced by CI/CD in Phase 5
data "archive_file" "lambda_placeholder" {
  type        = "zip"
  output_path = "${path.module}/placeholder_lambda.zip"

  source {
    content  = "def handler(event, context): raise NotImplementedError('Lambda not yet implemented')"
    filename = "handler.py"
  }
}

resource "aws_lambda_function" "validate_bronze" {
  function_name    = "${local.name_prefix}-validate-bronze"
  role             = aws_iam_role.lambda_execution.arn
  filename         = data.archive_file.lambda_placeholder.output_path
  source_code_hash = data.archive_file.lambda_placeholder.output_base64sha256
  handler          = "handler.handler"
  runtime          = local.lambda_runtime
  timeout          = local.lambda_timeout
  environment { variables = local.lambda_env }
}

resource "aws_lambda_function" "ingest_pharmgkb" {
  function_name    = "${local.name_prefix}-ingest-pharmgkb"
  role             = aws_iam_role.lambda_execution.arn
  filename         = data.archive_file.lambda_placeholder.output_path
  source_code_hash = data.archive_file.lambda_placeholder.output_base64sha256
  handler          = "handler.handler"
  runtime          = local.lambda_runtime
  timeout          = local.lambda_timeout
  environment { variables = local.lambda_env }
}

resource "aws_lambda_function" "ingest_cpic" {
  function_name    = "${local.name_prefix}-ingest-cpic"
  role             = aws_iam_role.lambda_execution.arn
  filename         = data.archive_file.lambda_placeholder.output_path
  source_code_hash = data.archive_file.lambda_placeholder.output_base64sha256
  handler          = "handler.handler"
  runtime          = local.lambda_runtime
  timeout          = local.lambda_timeout
  environment { variables = local.lambda_env }
}

resource "aws_lambda_function" "build_silver_clinical" {
  function_name    = "${local.name_prefix}-build-silver-clinical"
  role             = aws_iam_role.lambda_execution.arn
  filename         = data.archive_file.lambda_placeholder.output_path
  source_code_hash = data.archive_file.lambda_placeholder.output_base64sha256
  handler          = "handler.handler"
  runtime          = local.lambda_runtime
  timeout          = local.lambda_timeout
  environment { variables = local.lambda_env }
}

resource "aws_lambda_function" "build_silver_populations" {
  function_name    = "${local.name_prefix}-build-silver-populations"
  role             = aws_iam_role.lambda_execution.arn
  filename         = data.archive_file.lambda_placeholder.output_path
  source_code_hash = data.archive_file.lambda_placeholder.output_base64sha256
  handler          = "handler.handler"
  runtime          = local.lambda_runtime
  timeout          = local.lambda_timeout
  environment { variables = local.lambda_env }
}

resource "aws_lambda_function" "build_gold_frequencies" {
  function_name    = "${local.name_prefix}-build-gold-frequencies"
  role             = aws_iam_role.lambda_execution.arn
  filename         = data.archive_file.lambda_placeholder.output_path
  source_code_hash = data.archive_file.lambda_placeholder.output_base64sha256
  handler          = "handler.handler"
  runtime          = local.lambda_runtime
  timeout          = local.lambda_timeout
  environment { variables = local.lambda_env }
}

resource "aws_lambda_function" "build_gold_phenotype" {
  function_name    = "${local.name_prefix}-build-gold-phenotype"
  role             = aws_iam_role.lambda_execution.arn
  filename         = data.archive_file.lambda_placeholder.output_path
  source_code_hash = data.archive_file.lambda_placeholder.output_base64sha256
  handler          = "handler.handler"
  runtime          = local.lambda_runtime
  timeout          = local.lambda_timeout
  environment { variables = local.lambda_env }
}

resource "aws_lambda_function" "build_gold_drug_impact" {
  function_name    = "${local.name_prefix}-build-gold-drug-impact"
  role             = aws_iam_role.lambda_execution.arn
  filename         = data.archive_file.lambda_placeholder.output_path
  source_code_hash = data.archive_file.lambda_placeholder.output_base64sha256
  handler          = "handler.handler"
  runtime          = local.lambda_runtime
  timeout          = local.lambda_timeout
  environment { variables = local.lambda_env }
}

resource "aws_lambda_function" "build_gold_ranking" {
  function_name    = "${local.name_prefix}-build-gold-ranking"
  role             = aws_iam_role.lambda_execution.arn
  filename         = data.archive_file.lambda_placeholder.output_path
  source_code_hash = data.archive_file.lambda_placeholder.output_base64sha256
  handler          = "handler.handler"
  runtime          = local.lambda_runtime
  timeout          = local.lambda_timeout
  environment { variables = local.lambda_env }
}

# export_artifacts is deployed from S3 by the CI pipeline after Terraform apply.
# On initial apply the placeholder zip is used; CI overrides via update-function-code.
resource "aws_lambda_function" "export_artifacts" {
  function_name    = "${local.name_prefix}-export-artifacts"
  role             = aws_iam_role.lambda_execution.arn
  filename         = data.archive_file.lambda_placeholder.output_path
  source_code_hash = data.archive_file.lambda_placeholder.output_base64sha256
  handler          = "handler.handler"
  runtime          = local.lambda_runtime
  timeout          = local.lambda_timeout
  environment {
    variables = merge(local.lambda_env, {
      GITHUB_REPO           = var.github_repo
      ATHENA_RESULTS_PREFIX = "athena-results"
      GOLD_DATABASE         = "gold_pgx"
      SILVER_DATABASE       = "silver_pgx"
    })
  }
}
