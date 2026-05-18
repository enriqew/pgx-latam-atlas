"""Application configuration loaded exclusively from environment variables."""

from functools import lru_cache
from pathlib import Path

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
    )

    aws_region: str = Field(default="us-east-1", alias="AWS_REGION")
    aws_profile: str | None = Field(default=None, alias="AWS_PROFILE")

    pgx_s3_lake_bucket: str = Field(default="", alias="PGX_S3_LAKE_BUCKET")
    pgx_athena_workgroup: str = Field(default="primary", alias="PGX_ATHENA_WORKGROUP")
    pgx_glue_role_arn: str = Field(default="", alias="PGX_GLUE_ROLE_ARN")
    pgx_step_functions_role_arn: str = Field(default="", alias="PGX_STEP_FUNCTIONS_ROLE_ARN")

    local_data_root: Path = Field(default=Path("data"), alias="PGX_LOCAL_DATA_ROOT")
    artifacts_root: Path = Field(default=Path("artifacts"), alias="PGX_ARTIFACTS_ROOT")

    @property
    def bronze_root(self) -> Path:
        return self.local_data_root / "bronze"

    @property
    def silver_root(self) -> Path:
        return self.local_data_root / "silver"

    @property
    def gold_root(self) -> Path:
        return self.local_data_root / "gold"


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    return Settings()
