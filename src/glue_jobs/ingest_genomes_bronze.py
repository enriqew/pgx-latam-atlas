"""AWS Glue job: ingest 1000 Genomes VCF regions → bronze/genomes_variants_raw/ on S3.

Uploaded to S3 and invoked via GlueClient.start_job_run in Phase 4.
Script parameters are passed as --key=value Glue job arguments.
"""

# TODO (Phase 4): implement Glue job entrypoint


def main() -> None:
    raise NotImplementedError("Phase 4 Glue job not yet implemented")


if __name__ == "__main__":
    main()
