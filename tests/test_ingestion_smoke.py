"""Smoke tests: verify real public data source URLs are reachable via HEAD requests.

These tests do NOT download data. They confirm the URLs are live.
Run with: pytest -m smoke
"""

import pytest
import requests


@pytest.mark.smoke
class TestDataSourceAvailability:
    def test_1000genomes_panel_file_reachable(self) -> None:
        url = (
            "https://ftp.1000genomes.ebi.ac.uk/vol1/ftp/release/20130502/"
            "integrated_call_samples_v3.20130502.ALL.panel"
        )
        response = requests.head(url, timeout=15, allow_redirects=True)
        assert response.status_code == 200, (
            f"1000 Genomes panel file not reachable: {url} → {response.status_code}"
        )

    def test_pharmgkb_downloads_page_reachable(self) -> None:
        url = "https://www.pharmgkb.org/downloads"
        response = requests.head(url, timeout=15, allow_redirects=True)
        assert response.status_code in (200, 301, 302), (
            f"PharmGKB downloads page not reachable: {url} → {response.status_code}"
        )

    def test_cpic_api_reachable(self) -> None:
        url = "https://api.cpicpgx.org/v1/guideline"
        response = requests.head(url, timeout=15, allow_redirects=True)
        assert response.status_code in (200, 405), (
            f"CPIC API not reachable: {url} → {response.status_code}"
        )

    def test_1000genomes_s3_bucket_index_reachable(self) -> None:
        url = (
            "https://s3.amazonaws.com/1000genomes/release/20130502/"
            "ALL.chr22.phase3_shapeit2_mvncall_integrated_v5b.20130502.genotypes.vcf.gz.tbi"
        )
        response = requests.head(url, timeout=15, allow_redirects=True)
        assert response.status_code == 200, (
            f"1000G S3 VCF index not reachable: {url} → {response.status_code}"
        )
