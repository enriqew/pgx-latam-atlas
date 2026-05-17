# Terraform Infrastructure

## First-time backend bootstrap

The remote state backend (S3 + DynamoDB lock) must be created **before** running
`terraform init` for the first time. It uses a **separate bucket** from the data lake.

### Step 1: Create the state bucket and lock table manually

```bash
# Replace <your-account-id> and <your-region> with real values
aws s3api create-bucket \
  --bucket pgx-latam-tfstate-<your-account-id> \
  --region us-east-1

aws s3api put-bucket-versioning \
  --bucket pgx-latam-tfstate-<your-account-id> \
  --versioning-configuration Status=Enabled

aws s3api put-bucket-encryption \
  --bucket pgx-latam-tfstate-<your-account-id> \
  --server-side-encryption-configuration \
    '{"Rules":[{"ApplyServerSideEncryptionByDefault":{"SSEAlgorithm":"AES256"}}]}'

aws dynamodb create-table \
  --table-name pgx-latam-tfstate-lock \
  --attribute-definitions AttributeName=LockID,AttributeType=S \
  --key-schema AttributeName=LockID,KeyType=HASH \
  --billing-mode PAY_PER_REQUEST \
  --region us-east-1
```

### Step 2: Initialize Terraform

```bash
cd infra/terraform
terraform init \
  -backend-config="bucket=pgx-latam-tfstate-<your-account-id>" \
  -backend-config="key=pgx-latam-atlas/terraform.tfstate" \
  -backend-config="region=us-east-1" \
  -backend-config="dynamodb_table=pgx-latam-tfstate-lock"
```

### Step 3: Create a `terraform.tfvars` file (gitignored)

Copy `terraform.tfvars.example` to `terraform.tfvars` and fill in real values.
**Never commit `terraform.tfvars`.**

```bash
cp terraform.tfvars.example terraform.tfvars
```

## Workflow

```bash
make tf-validate   # Validate configuration
make tf-plan       # Review plan — no changes applied
# Apply only after reviewing plan output:
cd infra/terraform && terraform apply
```

**Never use `terraform apply -auto-approve` in production.**

## GitHub Actions CI

The CI workflow uses OIDC to assume an IAM role — no long-lived access keys in secrets.
The PR workflow runs `terraform plan` and posts output as a PR comment.
The main branch workflow never auto-applies; it only validates and plans.
