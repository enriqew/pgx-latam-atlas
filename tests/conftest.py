"""Shared pytest fixtures."""

import pytest


@pytest.fixture(scope="session")
def sample_populations() -> list[dict[str, object]]:
    return [
        {"code": "MXL", "name": "Mexican Ancestry in Los Angeles", "n": 64},
        {"code": "PEL", "name": "Peruvians in Lima", "n": 85},
        {"code": "CLM", "name": "Colombians in Medellín", "n": 94},
        {"code": "PUR", "name": "Puerto Ricans in Puerto Rico", "n": 104},
        {"code": "CEU", "name": "Utah Residents (CEPH)", "n": 99},
    ]
