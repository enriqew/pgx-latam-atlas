"""Unit tests for the Wilson score confidence interval implementation."""

import math

import pytest

from pgx_latam.utils.wilson_ci import wilson_score_interval


class TestWilsonScoreInterval:
    def test_50_percent_frequency(self) -> None:
        result = wilson_score_interval(successes=50, trials=100)
        assert abs(result.center - 0.5) < 0.01
        assert result.lower < 0.5 < result.upper

    def test_zero_frequency(self) -> None:
        result = wilson_score_interval(successes=0, trials=100)
        assert result.lower == 0.0
        assert result.upper > 0.0
        assert result.center < 0.04

    def test_full_frequency(self) -> None:
        result = wilson_score_interval(successes=100, trials=100)
        assert result.upper == 1.0
        assert result.lower > 0.96

    def test_rare_allele_ci_is_wider_than_common(self) -> None:
        rare = wilson_score_interval(successes=2, trials=100)
        common = wilson_score_interval(successes=50, trials=100)
        rare_width = rare.upper - rare.lower
        common_width = common.upper - common.lower
        assert rare_width < common_width  # rare allele has narrower absolute interval

    def test_bounds_are_in_zero_one(self) -> None:
        for k in range(0, 11):
            result = wilson_score_interval(successes=k, trials=10)
            assert 0.0 <= result.lower <= 1.0
            assert 0.0 <= result.upper <= 1.0
            assert result.lower <= result.upper

    def test_invalid_trials_zero(self) -> None:
        with pytest.raises(ValueError, match="trials must be > 0"):
            wilson_score_interval(successes=0, trials=0)

    def test_invalid_negative_successes(self) -> None:
        with pytest.raises(ValueError, match="successes must be >= 0"):
            wilson_score_interval(successes=-1, trials=10)

    def test_invalid_successes_exceed_trials(self) -> None:
        with pytest.raises(ValueError, match="cannot exceed trials"):
            wilson_score_interval(successes=11, trials=10)

    def test_mxl_sample_size_example(self) -> None:
        # CYP2C19 *2 allele: ~15% in MXL, n=64 samples = 128 alleles
        result = wilson_score_interval(successes=19, trials=128)
        assert 0.09 < result.lower < 0.13
        assert 0.19 < result.upper < 0.25
        assert not math.isnan(result.center)
