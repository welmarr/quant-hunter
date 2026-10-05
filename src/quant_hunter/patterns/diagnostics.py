"""Classical diagnostic families, with retrospective summaries labelled explicitly."""

from __future__ import annotations

from dataclasses import dataclass
from hashlib import sha256

import numpy as np

from quant_hunter.patterns.contracts import (
    CausalFrame,
    FitContext,
    Floats,
    PatternError,
    PatternWindow,
    Provenance,
    bounded_int,
)
from quant_hunter.patterns.representations import constrained_dtw, normalize


def compare_dtw(
    left: PatternWindow, right: PatternWindow, *, decision_ns: int, radius: int = 4
) -> dict[str, object]:
    left.require_known(decision_ns)
    right.require_known(decision_ns)
    if left.provenance.features != right.provenance.features:
        raise PatternError("DTW feature names differ")
    return {
        "method_id": "PAT-02",
        "distance": constrained_dtw(
            normalize(left.values, "Z_WINDOW"),
            normalize(right.values, "Z_WINDOW"),
            radius=radius,
        ),
        "radius": radius,
        "normalization": "Z_WINDOW",
        "left": left.fingerprint,
        "right": right.fingerprint,
        "maximum_known_ns": max(left.available_ns, right.available_ns),
        "limitation": "Fixed n+m cost scale; no profit probability",
    }


def motif_profile(
    frame: CausalFrame,
    context: FitContext,
    *,
    length: int,
    stride: int = 1,
    max_windows: int = 256,
) -> dict[str, object]:
    """Exact small-corpus subsequence profile, motifs and discord rankings.

    This is retrospective discovery within train, not a causal profile at each
    original observation. Query-time historical neighbor search is separate.
    """
    train = frame.known(context.train_cutoff_ns)
    bounded_int(length, 2, 512, "motif length")
    bounded_int(stride, 1, 512, "motif stride")
    bounded_int(max_windows, 2, 512, "profile window cap")
    locations = list(range(0, len(train.values) - length + 1, stride))
    if not 2 <= len(locations) <= max_windows:
        raise PatternError("Exact motif profile exceeds the declared window count")
    windows = tuple(
        train.window(start, start + length, decision_ns=context.train_cutoff_ns)
        for start in locations
    )
    context.validate(windows, max_count=max_windows)
    size = length * train.values.shape[1]
    if len(windows) ** 2 * size > 20_000_000:
        raise PatternError("Exact profile arithmetic budget exceeded")
    representations = np.stack(
        [normalize(window.values, "Z_WINDOW").ravel() for window in windows]
    )
    squared_norm = (representations**2).sum(axis=1)
    distance = np.sqrt(
        np.maximum(
            0,
            squared_norm[:, None]
            + squared_norm[None, :]
            - 2 * (representations @ representations.T),
        )
        / size
    )
    for i, left in enumerate(windows):
        for j, right in enumerate(windows):
            if left.start_ns < right.end_ns and right.start_ns < left.end_ns:
                distance[i, j] = np.inf
    nearest = distance.argmin(axis=1)
    profile = distance[np.arange(len(windows)), nearest]
    finite = np.isfinite(profile)
    motifs = sorted(
        {tuple(sorted((i, int(nearest[i])))) for i in np.flatnonzero(finite)},
        key=lambda pair: (float(distance[pair]), pair),
    )
    discord = sorted(
        (int(i) for i in np.flatnonzero(finite)), key=lambda i: (-float(profile[i]), i)
    )
    return {
        "method_id": "PAT-01",
        "mode": "EXACT_SMALL_RETROSPECTIVE_TRAIN",
        "dataset": frame.provenance,
        "cutoff_ns": context.train_cutoff_ns,
        "length": length,
        "stride": stride,
        "candidates_searched": len(windows),
        "start_ns": tuple(window.start_ns for window in windows),
        "profile": tuple(
            float(value) if np.isfinite(value) else None for value in profile
        ),
        "nearest_index": tuple(
            int(nearest[i]) if finite[i] else None for i in range(len(windows))
        ),
        "motif_pairs": tuple(motifs),
        "discord_indices": tuple(discord),
        "limitation": "A discord has few close shape neighbors; this does not establish an economic anomaly.",
    }


@dataclass(frozen=True, slots=True)
class CUSUMModel:
    context: FitContext
    mean: float
    scale: float
    allowance: float
    threshold: float
    training_rows: int
    training_fingerprint: str
    features: tuple[str, ...]
    step_ns: int

    def detect(self, window: PatternWindow, *, decision_ns: int) -> dict[str, object]:
        self.context.prediction(window, decision_ns)
        if window.values.shape[1] != 1:
            raise PatternError("CUSUM profile is univariate")
        if (
            window.provenance.features != self.features
            or window.step_ns != self.step_ns
        ):
            raise PatternError(
                "CUSUM prediction schema/time grid differs from training"
            )
        upward = downward = 0.0
        scores: list[tuple[float, float]] = []
        alarms: list[tuple[int, str]] = []
        for index, value in enumerate(window.values[:, 0]):
            residual = (float(value) - self.mean) / self.scale
            upward = max(0, upward + residual - self.allowance)
            downward = max(0, downward - residual - self.allowance)
            scores.append((upward, downward))
            if max(upward, downward) >= self.threshold:
                alarms.append((index, "UP" if upward >= downward else "DOWN"))
                upward = downward = 0
        return {
            "method_id": "PAT-05",
            "scores": tuple(scores),
            "alarms": tuple(alarms),
            "mode": "CAUSAL_FORWARD_RESET_ON_ALARM",
            "window": window.fingerprint,
            "maximum_known_ns": window.available_ns,
        }


def fit_cusum(
    frame: CausalFrame,
    context: FitContext,
    *,
    allowance: float = 0.5,
    threshold: float = 5,
    scale_floor: float = 1e-6,
) -> CUSUMModel:
    if (
        not all(np.isfinite(value) for value in (allowance, threshold, scale_floor))
        or allowance < 0
        or threshold <= 0
        or not 1e-12 <= scale_floor <= 1
    ):
        raise PatternError(
            "CUSUM parameters must be finite with positive threshold/scale"
        )
    train = frame.known(context.train_cutoff_ns)
    if train.values.shape[1] != 1 or len(train.values) < 4:
        raise PatternError(
            "CUSUM fit needs at least four univariate training observations"
        )
    return CUSUMModel(
        context,
        float(train.values.mean()),
        max(scale_floor, float(train.values.std())),
        allowance,
        threshold,
        len(train.values),
        train.fingerprint,
        train.provenance.features,
        train.step_ns,
    )


def spectra_haar(window: PatternWindow, *, decision_ns: int) -> dict[str, object]:
    window.require_known(decision_ns)
    size = len(window.values)
    if window.values.shape[1] != 1 or size < 4 or size & (size - 1):
        raise PatternError("Hann/Haar profile needs 4-512 univariate power-of-two bars")
    values = window.values[:, 0]
    taper = np.hanning(size)
    transformed = np.fft.rfft((values - values.mean()) * taper)
    power = np.abs(transformed) ** 2 / float((taper**2).sum())
    approximation = values.copy()
    details: list[tuple[float, ...]] = []
    while len(approximation) > 1:
        details.append(
            tuple(
                float(item)
                for item in (approximation[::2] - approximation[1::2]) / np.sqrt(2)
            )
        )
        approximation = (approximation[::2] + approximation[1::2]) / np.sqrt(2)
    return {
        "method_id": "PAT-07",
        "window": window.fingerprint,
        "frequencies_cycles_per_bar": tuple(
            float(value) for value in np.fft.rfftfreq(size)
        ),
        "hann_power": tuple(float(value) for value in power),
        "haar_approximation": float(approximation[0]),
        "haar_details_fine_to_coarse": tuple(details),
        "boundary": "No padding; rectangular finite support for Haar; Hann taper for spectrum",
        "limitation": "Retrospective within the closed query window. Finite-window edges and leakage remain; no periodic-market claim.",
    }


def _runs(values: np.ndarray) -> list[int]:
    padded = np.r_[False, values, False].astype(np.int8)
    boundaries = np.diff(padded)
    return [
        int(value)
        for value in np.flatnonzero(boundaries == -1) - np.flatnonzero(boundaries == 1)
    ]


def recurrence(
    window: PatternWindow,
    *,
    decision_ns: int,
    radius: float = 0.5,
    theiler: int = 1,
    minimum_line: int = 2,
) -> dict[str, object]:
    window.require_known(decision_ns)
    size = len(window.values)
    if size > 256 or not np.isfinite(radius) or radius <= 0:
        raise PatternError("Recurrence radius must be positive and rows at most 256")
    bounded_int(theiler, 0, size - 2, "Theiler exclusion")
    bounded_int(minimum_line, 2, size, "minimum recurrence line")
    values = normalize(window.values, "Z_WINDOW")
    distance = np.sqrt(np.mean((values[:, None, :] - values[None, :, :]) ** 2, axis=2))
    allowed = np.abs(np.arange(size)[:, None] - np.arange(size)[None, :]) > theiler
    matrix = (distance <= radius) & allowed
    count = int(matrix.sum())
    diagonal = [
        length
        for offset in range(-size + 1, size)
        for length in _runs(np.diag(matrix, offset))
        if length >= minimum_line
    ]
    vertical = [
        length
        for column in matrix.T
        for length in _runs(column)
        if length >= minimum_line
    ]
    return {
        "method_id": "PAT-08",
        "window": window.fingerprint,
        "recurrence_rate": count / int(allowed.sum()),
        "determinism": sum(diagonal) / count if count else 0,
        "laminarity": sum(vertical) / count if count else 0,
        "trapping_time": sum(vertical) / len(vertical) if vertical else 0,
        "recurrence_points": count,
        "theiler": theiler,
        "minimum_line": minimum_line,
        "state": "RECURRENCES" if count else "NO_RECURRENCES",
        "limitation": "Window-local descriptive recurrence is not evidence of predictable market outcomes.",
    }


def geometry(
    window: PatternWindow,
    *,
    decision_ns: int,
    breakout_fraction: float = 0.001,
    channel_tolerance: float = 0.01,
) -> dict[str, object]:
    """Prior-close range breakout and least-squares channel, with explicit rules."""
    window.require_known(decision_ns)
    if (
        window.provenance.features[0] != "close"
        or len(window.values) < 5
        or np.any(window.values[:, 0] <= 0)
    ):
        raise PatternError("Geometry requires at least five positive close marks")
    if not 0 <= breakout_fraction <= 0.5 or not 0 < channel_tolerance <= 0.5:
        raise PatternError("Geometric tolerances are outside the supported range")
    prices = window.values[:, 0]
    past, latest = prices[:-1], float(prices[-1])
    x = np.arange(len(past), dtype=np.float64)
    slope = float(
        ((x - x.mean()) * (past - past.mean())).sum() / ((x - x.mean()) ** 2).sum()
    )
    intercept = float(past.mean() - slope * x.mean())
    residual = float(np.max(np.abs(past - (intercept + slope * x))) / past.mean())
    state = (
        "BREAKOUT_UP"
        if latest > float(past.max()) * (1 + breakout_fraction)
        else "BREAKOUT_DOWN"
        if latest < float(past.min()) * (1 - breakout_fraction)
        else "NO_BREAKOUT"
    )
    return {
        "method_id": "PAT-10",
        "window": window.fingerprint,
        "state": state,
        "prior_resistance_close": float(past.max()),
        "prior_support_close": float(past.min()),
        "breakout_fraction": breakout_fraction,
        "channel_slope_per_bar": slope,
        "channel_max_relative_residual": residual,
        "channel_within_tolerance": residual <= channel_tolerance,
        "channel_tolerance": channel_tolerance,
        "limitation": "Close-based mathematical rules only; no subjective chart label or trade recommendation.",
    }


@dataclass(frozen=True, slots=True, eq=False)
class AlignmentResult:
    frame: CausalFrame
    input_provenance: tuple[Provenance, ...]
    maximum_staleness_ns: int
    dropped_anchor_rows: int
    method_id: str = "PAT-11"


def align_asof(
    frames: tuple[CausalFrame, ...], *, decision_ns: int, maximum_staleness_ns: int = 0
) -> AlignmentResult:
    """At each first-series close, use only other values already known then.

    Nonzero staleness explicitly permits backward carry within the given bound;
    zero requires simultaneous observations. No future nearest-neighbor join.
    """
    bounded_int(maximum_staleness_ns, 0, 86_400_000_000_000, "alignment staleness")
    if (
        not isinstance(frames, tuple)
        or not 2 <= len(frames) <= 8
        or sum(frame.values.shape[1] for frame in frames) > 16
        or any(len(frame.values) > 4096 for frame in frames)
    ):
        raise PatternError(
            "Alignment needs 2-8 streams and at most 16 combined features"
        )
    known = tuple(frame.known(decision_ns) for frame in frames)
    rows: list[Floats] = []
    closes: list[int] = []
    available: list[int] = []
    for anchor in known[0].close_ns:
        selected: list[int] = []
        for frame in known:
            eligible = np.flatnonzero(
                (frame.close_ns <= anchor)
                & (frame.available_ns <= anchor)
                & (anchor - frame.close_ns <= maximum_staleness_ns)
            )
            if not len(eligible):
                break
            selected.append(int(eligible[-1]))
        if len(selected) != len(known):
            continue
        rows.append(
            np.concatenate(
                [
                    frame.values[index]
                    for frame, index in zip(known, selected, strict=True)
                ]
            ).reshape(1, -1)
        )
        closes.append(int(anchor))
        # The derived row closes at the anchor, after all selected inputs are known.
        available.append(int(anchor))
    if not rows:
        raise PatternError("No contemporaneously available aligned observations")
    references = tuple(frame.provenance for frame in known)
    digest = sha256(repr((references, maximum_staleness_ns)).encode()).hexdigest()
    provenance = Provenance(
        "EPHEMERAL_ALIGNMENT",
        "sha256:" + digest,
        known[0].provenance.instrument_id,
        known[0].provenance.timeframe,
        tuple(
            f"s{index}:{name}"
            for index, frame in enumerate(known)
            for name in frame.provenance.features
        ),
    )
    result = CausalFrame(
        np.concatenate(rows),
        np.array(closes, dtype=np.int64),
        np.array(available, dtype=np.int64),
        known[0].step_ns,
        provenance,
    )
    return AlignmentResult(
        result, references, maximum_staleness_ns, len(known[0].values) - len(rows)
    )
