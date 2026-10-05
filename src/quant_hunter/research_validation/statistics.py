"""Bounded prespecified uncertainty and complete-family Holm calculations."""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Context, Decimal, InvalidOperation, localcontext
from math import ceil, isfinite
from typing import cast

import numpy as np

from quant_hunter.config import JsonRecord, JsonValue

from .temporal import ResearchValidationError


@dataclass(frozen=True, slots=True)
class BootstrapSpec:
    block_length: int
    repetitions: int
    seed: int
    confidence: str = "0.95"
    minimum_observations: int = 20

    def __post_init__(self) -> None:
        if (
            type(self.block_length) is not int
            or not 1 <= self.block_length <= 10_000
            or type(self.repetitions) is not int
            or not 100 <= self.repetitions <= 10_000
            or type(self.seed) is not int
            or not 0 <= self.seed <= 2**32 - 1
            or self.confidence not in {"0.80", "0.90", "0.95", "0.99"}
            or type(self.minimum_observations) is not int
            or not 4 <= self.minimum_observations <= 100_000
        ):
            raise ResearchValidationError("INVALID_BOOTSTRAP_SPECIFICATION")

    def to_record(self) -> JsonRecord:
        return {
            "method": "NONCIRCULAR_MOVING_BLOCK_MEAN_PERCENTILE_V1",
            "block_length": self.block_length,
            "repetitions": self.repetitions,
            "seed": self.seed,
            "confidence": self.confidence,
            "minimum_observations": self.minimum_observations,
            "rng": "NumPy PCG64",
            "quantile": "linear",
        }


def moving_block_mean(
    values: tuple[float, ...], specification: BootstrapSpec
) -> JsonRecord:
    """Fixed length overlapping blocks; no fitted block length or p-value claim."""
    specification.__post_init__()
    if not isinstance(values, tuple) or not 1 <= len(values) <= 100_000:
        raise ResearchValidationError("BOOTSTRAP_INPUT_LIMIT")
    if any(
        type(value) not in (float, int) or not isfinite(value) or abs(value) > 1e50
        for value in values
    ):
        raise ResearchValidationError("INVALID_BOOTSTRAP_VALUE")
    n, length = len(values), specification.block_length
    if n * specification.repetitions > 10_000_000:
        raise ResearchValidationError("BOOTSTRAP_WORK_LIMIT")
    if n < specification.minimum_observations or length > n // 2:
        return {
            "status": "INCONCLUSIVE",
            "reason": "INSUFFICIENT_SAMPLE_OR_BLOCKS",
            "n": n,
            "specification": specification.to_record(),
            "interval": None,
            "p_value": None,
        }
    array = np.asarray(values, dtype=np.float64)
    generator = np.random.Generator(np.random.PCG64(specification.seed))
    means = np.empty(specification.repetitions)
    blocks = ceil(n / length)
    for index in range(specification.repetitions):
        starts = generator.integers(0, n - length + 1, size=blocks)
        sample = np.concatenate([array[start : start + length] for start in starts])[:n]
        means[index] = float(np.mean(sample))
    alpha = (1 - float(specification.confidence)) / 2
    lower, upper = np.quantile(means, [alpha, 1 - alpha], method="linear")
    return {
        "status": "COMPUTED_SOFTWARE_ONLY",
        "n": n,
        "mean": float(np.mean(array)),
        "interval": [float(lower), float(upper)],
        "p_value": None,
        "specification": specification.to_record(),
        "limitations": [
            "Requires adequate weak stationarity/dependence and a scientifically justified prespecified block length.",
            "Block bootstrap does not repair look-ahead, adaptive selection, missing trials or regime shifts.",
            "Percentile interval concerns the mean; it is not a calibrated selected-strategy probability or a hypothesis-test p-value.",
        ],
    }


def probability(value: str) -> Decimal:
    if not isinstance(value, str) or not 1 <= len(value) <= 64:
        raise ResearchValidationError("INVALID_P_VALUE")
    try:
        parsed = Decimal(value)
    except InvalidOperation:
        raise ResearchValidationError("INVALID_P_VALUE") from None
    if (
        not parsed.is_finite()
        or not 0 <= parsed <= 1
        or abs(cast(int, parsed.as_tuple().exponent)) > 30
    ):
        raise ResearchValidationError("INVALID_P_VALUE")
    return parsed


def holm_adjust(
    p_values: tuple[tuple[str, str], ...], *, alpha: str = "0.05"
) -> JsonRecord:
    """Holm 1979 section2 step-down Bonferroni; assumes valid complete-family p-values."""
    if (
        not isinstance(p_values, tuple)
        or not 1 <= len(p_values) <= 10_000
        or any(
            not isinstance(item, tuple)
            or len(item) != 2
            or not isinstance(item[0], str)
            or not 1 <= len(item[0]) <= 128
            or not item[0].isascii()
            for item in p_values
        )
        or len({key for key, _ in p_values}) != len(p_values)
    ):
        raise ResearchValidationError("INVALID_HOLM_FAMILY")
    level = probability(alpha)
    if not 0 < level < 1:
        raise ResearchValidationError("INVALID_HOLM_ALPHA")
    ordered = sorted(
        ((key, probability(value)) for key, value in p_values),
        key=lambda item: (item[1], item[0]),
    )
    previous = Decimal(0)
    result: list[JsonValue] = []
    # <=64 input characters and <=5 multiplier digits need at most69 exact
    # coefficient digits. Never inherit a caller's Decimal rounding context.
    with localcontext(Context(prec=100)):
        for index, (identity, raw) in enumerate(ordered):
            previous = min(Decimal(1), max(previous, raw * (len(ordered) - index)))
            result.append(
                {
                    "trial_id": identity,
                    "raw_p_value": str(raw),
                    "adjusted_p_value": str(previous),
                    "rejected": previous <= level,
                }
            )
    return {
        "method": "HOLM_STEP_DOWN_BONFERRONI_1979",
        "alpha": str(level),
        "family_size": len(ordered),
        "values": result,
        "empirical_status": "INCONCLUSIVE",
        "limitations": cast(
            list[JsonValue],
            [
                "Requires valid individually calibrated p-values and a complete prespecified family; dependence across tests is permitted.",
                "Adjusted significance does not establish economic importance, PIT validity or operational fitness.",
            ],
        ),
    }
