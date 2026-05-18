"""Wilson score confidence interval for binomial proportions.

Used throughout the gold layer to compute allele frequency and phenotype
distribution confidence intervals. The Wilson interval outperforms the Normal
approximation when proportions are near 0 or 1 — common for rare alleles.
"""

import math
from typing import NamedTuple

_Z95 = 1.96  # z-score for 95% confidence interval


class WilsonCI(NamedTuple):
    lower: float
    upper: float
    center: float


def wilson_score_interval(
    successes: int,
    trials: int,
    z: float = _Z95,
) -> WilsonCI:
    """Compute the Wilson score confidence interval for a proportion.

    Args:
        successes: Number of observed successes (e.g., alternate allele count).
        trials: Total number of trials (e.g., total alleles = 2 x sample size).
        z: z-score for the desired confidence level. Default: 1.96 (95% CI).

    Returns:
        WilsonCI with lower bound, upper bound, and Wilson center estimate.

    Raises:
        ValueError: If trials <= 0 or successes < 0 or successes > trials.
    """
    if trials <= 0:
        raise ValueError(f"trials must be > 0, got {trials}")
    if successes < 0:
        raise ValueError(f"successes must be >= 0, got {successes}")
    if successes > trials:
        raise ValueError(
            f"successes ({successes}) cannot exceed trials ({trials})"
        )

    z2 = z * z
    n = trials
    k = successes

    denominator = n + z2
    center = (k + z2 / 2.0) / denominator
    half_width = (z / denominator) * math.sqrt(
        k * (n - k) / n + z2 / 4.0
    )

    return WilsonCI(
        lower=max(0.0, center - half_width),
        upper=min(1.0, center + half_width),
        center=center,
    )
