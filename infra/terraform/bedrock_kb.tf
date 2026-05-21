# Bedrock Knowledge Base — PGx LATAM Atlas
# Vector store: OpenSearch Serverless (no-server, pay-per-use)
# Data source: S3 prefix gold/kb-docs/ in the existing lake bucket
# Embedding model: Amazon Titan Embeddings V2 (default dimension 1536)

# ── OpenSearch Serverless collection ─────────────────────────────────────────

resource "aws_opensearchserverless_security_policy" "kb_encryption" {
  name        = "${local.name_prefix}-kb-enc"
  type        = "encryption"
  description = "Encryption policy for Bedrock KB vector store"

  policy = jsonencode({
    Rules = [
      {
        ResourceType = "collection"
        Resource     = ["collection/${local.name_prefix}-kb"]
      }
    ]
    AWSOwnedKey = true
  })
}

resource "aws_opensearchserverless_security_policy" "kb_network" {
  name        = "${local.name_prefix}-kb-net"
  type        = "network"
  description = "Network policy — allow Bedrock service access only"

  policy = jsonencode([
    {
      Rules = [
        {
          ResourceType = "collection"
          Resource     = ["collection/${local.name_prefix}-kb"]
        },
        {
          ResourceType = "dashboard"
          Resource     = ["collection/${local.name_prefix}-kb"]
        }
      ]
      AllowFromPublic = false
      SourceServices  = ["bedrock.amazonaws.com"]
    }
  ])
}

resource "aws_opensearchserverless_access_policy" "kb_data" {
  name        = "${local.name_prefix}-kb-data"
  type        = "data"
  description = "Data access policy for Bedrock KB role"

  policy = jsonencode([
    {
      Rules = [
        {
          ResourceType = "index"
          Resource     = ["index/${local.name_prefix}-kb/*"]
          Permission   = ["aoss:CreateIndex", "aoss:DeleteIndex", "aoss:UpdateIndex", "aoss:DescribeIndex", "aoss:ReadDocument", "aoss:WriteDocument"]
        },
        {
          ResourceType = "collection"
          Resource     = ["collection/${local.name_prefix}-kb"]
          Permission   = ["aoss:CreateCollectionItems", "aoss:DeleteCollectionItems", "aoss:UpdateCollectionItems", "aoss:DescribeCollectionItems"]
        }
      ]
      Principal = [aws_iam_role.bedrock_kb.arn]
    }
  ])
}

resource "aws_opensearchserverless_collection" "kb" {
  name        = "${local.name_prefix}-kb"
  type        = "VECTORSEARCH"
  description = "Vector store for pgx-latam-atlas Bedrock Knowledge Base"

  depends_on = [
    aws_opensearchserverless_security_policy.kb_encryption,
    aws_opensearchserverless_security_policy.kb_network,
  ]
}

# ── IAM role for Bedrock KB ───────────────────────────────────────────────────

data "aws_iam_policy_document" "bedrock_kb_assume_role" {
  statement {
    actions = ["sts:AssumeRole"]
    principals {
      type        = "Service"
      identifiers = ["bedrock.amazonaws.com"]
    }
    condition {
      test     = "StringEquals"
      variable = "aws:SourceAccount"
      values   = [data.aws_caller_identity.current.account_id]
    }
  }
}

data "aws_caller_identity" "current" {}

resource "aws_iam_role" "bedrock_kb" {
  name               = "${local.name_prefix}-bedrock-kb"
  assume_role_policy = data.aws_iam_policy_document.bedrock_kb_assume_role.json
}

data "aws_iam_policy_document" "bedrock_kb_permissions" {
  statement {
    sid       = "BedrockFoundationModelAccess"
    actions   = ["bedrock:InvokeModel"]
    resources = ["arn:aws:bedrock:${var.aws_region}::foundation-model/amazon.titan-embed-text-v2:0"]
  }
  statement {
    sid     = "S3KBDocsRead"
    actions = ["s3:GetObject", "s3:ListBucket"]
    resources = [
      aws_s3_bucket.lake.arn,
      "${aws_s3_bucket.lake.arn}/gold/kb-docs/*",
    ]
  }
  statement {
    sid       = "OpenSearchServerlessAccess"
    actions   = ["aoss:APIAccessAll"]
    resources = [aws_opensearchserverless_collection.kb.arn]
  }
}

resource "aws_iam_role_policy" "bedrock_kb_permissions" {
  name   = "bedrock-kb-permissions"
  role   = aws_iam_role.bedrock_kb.id
  policy = data.aws_iam_policy_document.bedrock_kb_permissions.json
}

# ── Bedrock Knowledge Base ────────────────────────────────────────────────────

resource "aws_bedrockagent_knowledge_base" "pgx" {
  name        = "${local.name_prefix}-pgx-kb"
  description = "Pharmacogenomic knowledge base — Latin American populations PGx atlas"
  role_arn    = aws_iam_role.bedrock_kb.arn

  knowledge_base_configuration {
    type = "VECTOR"
    vector_knowledge_base_configuration {
      embedding_model_arn = "arn:aws:bedrock:${var.aws_region}::foundation-model/amazon.titan-embed-text-v2:0"
    }
  }

  storage_configuration {
    type = "OPENSEARCH_SERVERLESS"
    opensearch_serverless_configuration {
      collection_arn    = aws_opensearchserverless_collection.kb.arn
      vector_index_name = "pgx-latam-index"
      field_mapping {
        vector_field   = "bedrock-knowledge-base-default-vector"
        text_field     = "AMAZON_BEDROCK_TEXT_CHUNK"
        metadata_field = "AMAZON_BEDROCK_METADATA"
      }
    }
  }
}

# ── Bedrock KB Data Source (S3) ───────────────────────────────────────────────

resource "aws_bedrockagent_data_source" "gold_docs" {
  knowledge_base_id = aws_bedrockagent_knowledge_base.pgx.id
  name              = "${local.name_prefix}-gold-docs"
  description       = "Gold-layer PGx text documents generated by the pipeline"

  data_source_configuration {
    type = "S3"
    s3_configuration {
      bucket_arn              = aws_s3_bucket.lake.arn
      inclusion_prefixes      = ["gold/kb-docs/"]
    }
  }

  vector_ingestion_configuration {
    chunking_configuration {
      chunking_strategy = "FIXED_SIZE"
      fixed_size_chunking_configuration {
        max_tokens         = 300
        overlap_percentage = 10
      }
    }
  }
}
