data "aws_iam_policy_document" "glue_assume_role" {
  statement {
    actions = ["sts:AssumeRole"]
    principals {
      type        = "Service"
      identifiers = ["glue.amazonaws.com"]
    }
  }
}

resource "aws_iam_role" "glue_execution" {
  name               = "${local.name_prefix}-glue-execution"
  assume_role_policy = data.aws_iam_policy_document.glue_assume_role.json
}

resource "aws_iam_role_policy_attachment" "glue_service" {
  role       = aws_iam_role.glue_execution.name
  policy_arn = "arn:aws:iam::aws:policy/service-role/AWSGlueServiceRole"
}

data "aws_iam_policy_document" "glue_lake_access" {
  statement {
    sid     = "LakeBucketReadWrite"
    actions = ["s3:GetObject", "s3:PutObject", "s3:DeleteObject", "s3:ListBucket"]
    resources = [
      aws_s3_bucket.lake.arn,
      "${aws_s3_bucket.lake.arn}/*",
    ]
  }
  statement {
    sid       = "GlueScriptsRead"
    actions   = ["s3:GetObject"]
    resources = ["${aws_s3_bucket.glue_scripts.arn}/*"]
  }
}

resource "aws_iam_role_policy" "glue_lake_access" {
  name   = "lake-access"
  role   = aws_iam_role.glue_execution.id
  policy = data.aws_iam_policy_document.glue_lake_access.json
}

# ── Step Functions ─────────────────────────────────────────────────────────────

data "aws_iam_policy_document" "sfn_assume_role" {
  statement {
    actions = ["sts:AssumeRole"]
    principals {
      type        = "Service"
      identifiers = ["states.amazonaws.com"]
    }
  }
}

resource "aws_iam_role" "step_functions_execution" {
  name               = "${local.name_prefix}-sfn-execution"
  assume_role_policy = data.aws_iam_policy_document.sfn_assume_role.json
}

data "aws_iam_policy_document" "sfn_permissions" {
  statement {
    sid     = "InvokeLambdas"
    actions = ["lambda:InvokeFunction"]
    resources = [
      aws_lambda_function.validate_bronze.arn,
      aws_lambda_function.ingest_pharmgkb.arn,
      aws_lambda_function.ingest_cpic.arn,
      aws_lambda_function.build_silver_clinical.arn,
      aws_lambda_function.build_silver_populations.arn,
      aws_lambda_function.build_gold_frequencies.arn,
      aws_lambda_function.build_gold_phenotype.arn,
      aws_lambda_function.build_gold_drug_impact.arn,
      aws_lambda_function.build_gold_ranking.arn,
      aws_lambda_function.export_artifacts.arn,
    ]
  }
  statement {
    sid       = "StartGlueJobs"
    actions   = ["glue:StartJobRun", "glue:GetJobRun", "glue:BatchStopJobRun"]
    resources = ["*"]
  }
  statement {
    sid       = "PublishSNS"
    actions   = ["sns:Publish"]
    resources = [aws_sns_topic.pipeline_failure.arn]
  }
}

resource "aws_iam_role_policy" "sfn_permissions" {
  name   = "sfn-permissions"
  role   = aws_iam_role.step_functions_execution.id
  policy = data.aws_iam_policy_document.sfn_permissions.json
}

# ── Lambda execution role ──────────────────────────────────────────────────────

data "aws_iam_policy_document" "lambda_assume_role" {
  statement {
    actions = ["sts:AssumeRole"]
    principals {
      type        = "Service"
      identifiers = ["lambda.amazonaws.com"]
    }
  }
}

resource "aws_iam_role" "lambda_execution" {
  name               = "${local.name_prefix}-lambda-execution"
  assume_role_policy = data.aws_iam_policy_document.lambda_assume_role.json
}

resource "aws_iam_role_policy_attachment" "lambda_basic" {
  role       = aws_iam_role.lambda_execution.name
  policy_arn = "arn:aws:iam::aws:policy/service-role/AWSLambdaBasicExecutionRole"
}

data "aws_iam_policy_document" "lambda_pipeline_access" {
  statement {
    sid     = "LakeAccess"
    actions = ["s3:GetObject", "s3:PutObject", "s3:ListBucket"]
    resources = [
      aws_s3_bucket.lake.arn,
      "${aws_s3_bucket.lake.arn}/*",
    ]
  }
  statement {
    sid     = "AthenaQueryExecution"
    actions = ["athena:StartQueryExecution", "athena:GetQueryExecution", "athena:GetQueryResults"]
    resources = ["*"]
  }
  statement {
    sid       = "GlueCatalogRead"
    actions   = ["glue:GetDatabase", "glue:GetTable", "glue:GetPartitions"]
    resources = ["*"]
  }
  statement {
    sid       = "SecretsManagerReadGitHub"
    actions   = ["secretsmanager:GetSecretValue"]
    resources = ["arn:aws:secretsmanager:*:*:secret:pgx-latam/github-pat*"]
  }
}

resource "aws_iam_role_policy" "lambda_pipeline_access" {
  name   = "pipeline-access"
  role   = aws_iam_role.lambda_execution.id
  policy = data.aws_iam_policy_document.lambda_pipeline_access.json
}
