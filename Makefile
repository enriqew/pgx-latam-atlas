.PHONY: help install install-dev lint fmt typecheck test test-smoke \
        ingest-local transform-local export-local dry-run \
        tf-init tf-plan tf-validate clean

PYTHON := python
UV    := uv

# ── Help ──────────────────────────────────────────────────────────────────────
help:
	@grep -E '^[a-zA-Z_-]+:.*?## .*$$' $(MAKEFILE_LIST) | \
		awk 'BEGIN {FS = ":.*?## "}; {printf "\033[36m%-22s\033[0m %s\n", $$1, $$2}'

# ── Setup ─────────────────────────────────────────────────────────────────────
install: ## Install runtime dependencies via uv
	$(UV) pip install -e .

install-dev: ## Install all dependencies including dev extras
	$(UV) pip install -e ".[dev,spark]"
	pre-commit install

install-vcf: ## Install VCF processing deps — requires Linux/macOS/WSL2 (pysam)
	$(UV) pip install -e ".[vcf]"

# ── Code quality ──────────────────────────────────────────────────────────────
lint: ## Run ruff linter
	ruff check src tests

fmt: ## Run ruff formatter
	ruff format src tests

typecheck: ## Run mypy strict type checking
	mypy src/pgx_latam

# ── Tests ─────────────────────────────────────────────────────────────────────
test: ## Run all tests except smoke and integration
	pytest -m "not smoke and not integration" -v

test-smoke: ## Run smoke tests (hits real external URLs — requires internet)
	pytest -m smoke -v

test-all: ## Run full test suite
	pytest -v

# ── Local pipeline (Phase 1-3, no AWS) ───────────────────────────────────────
ingest-local: ## Ingest raw data from public sources into data/bronze/ (local)
	$(PYTHON) -m pgx_latam.ingestion.thousand_genomes
	$(PYTHON) -m pgx_latam.ingestion.pharmgkb
	$(PYTHON) -m pgx_latam.ingestion.cpic

transform-local: ## Build silver tables locally from data/bronze/
	$(PYTHON) -m pgx_latam.transformations.silver_variants
	$(PYTHON) -m pgx_latam.transformations.silver_clinical

export-local: ## Build gold tables and export artifacts/ JSONs locally
	$(PYTHON) -m pgx_latam.transformations.gold_aggregates
	$(PYTHON) -m pgx_latam.exports.portfolio_artifacts

dry-run: ## Full local pipeline end-to-end (Phase 1-3)
	bash scripts/run_local_dry_run.sh

# ── IaC ───────────────────────────────────────────────────────────────────────
tf-init: ## Initialize Terraform (first time: bootstrap backend first)
	cd infra/terraform && terraform init

tf-validate: ## Validate Terraform configuration
	cd infra/terraform && terraform validate

tf-plan: ## Show Terraform plan (no apply)
	cd infra/terraform && terraform plan

# ── Cleanup ───────────────────────────────────────────────────────────────────
clean: ## Remove local build and cache artifacts
	find . -type d -name __pycache__ -exec rm -rf {} + 2>/dev/null || true
	find . -type d -name .pytest_cache -exec rm -rf {} + 2>/dev/null || true
	find . -type d -name .mypy_cache -exec rm -rf {} + 2>/dev/null || true
	find . -type d -name .ruff_cache -exec rm -rf {} + 2>/dev/null || true
	find . -type d -name "*.egg-info" -exec rm -rf {} + 2>/dev/null || true
	rm -f coverage.xml .coverage
