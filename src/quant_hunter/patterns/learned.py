"""Train-only classical representations with explicit prediction boundaries."""

from __future__ import annotations

from dataclasses import dataclass
from itertools import pairwise
from math import log2
from typing import Protocol

import numpy as np

from quant_hunter.patterns.contracts import (
    CausalFrame,
    FitContext,
    Floats,
    PatternError,
    PatternWindow,
    TrainingLabel,
    bounded_int,
    freeze,
)
from quant_hunter.patterns.representations import normalize, paa


def _same_shape(windows: tuple[PatternWindow, ...]) -> None:
    first = windows[0]
    if any(
        window.values.shape != first.values.shape
        or window.step_ns != first.step_ns
        or window.provenance.features != first.provenance.features
        for window in windows
    ):
        raise PatternError(
            "Training windows need an explicit common feature schema and shape"
        )


def _entropy(labels: list[int]) -> float:
    if not labels:
        return 0
    probability = sum(labels) / len(labels)
    return -sum(p * log2(p) for p in (probability, 1 - probability) if p)


def _shapelet_distance(values: Floats, shapelet: Floats) -> float:
    return min(
        float(
            np.sqrt(
                np.mean(
                    (
                        normalize(values[start : start + len(shapelet)], "Z_WINDOW")
                        - shapelet
                    )
                    ** 2
                )
            )
        )
        for start in range(len(values) - len(shapelet) + 1)
    )


@dataclass(frozen=True, slots=True, eq=False)
class ShapeletModel:
    context: FitContext
    shapelet: Floats
    threshold: float
    gain: float
    near_label: int
    far_label: int
    candidates_searched: int
    train_fingerprints: tuple[str, ...]
    features: tuple[str, ...]

    def predict(self, window: PatternWindow, *, decision_ns: int) -> tuple[int, float]:
        self.context.prediction(window, decision_ns)
        if window.provenance.features != self.features:
            raise PatternError("Shapelet feature schema differs")
        if window.values.shape[1] != self.shapelet.shape[1] or len(window.values) < len(
            self.shapelet
        ):
            raise PatternError("Query is incompatible with the fitted shapelet")
        distance = _shapelet_distance(window.values, self.shapelet)
        return (
            self.near_label if distance <= self.threshold else self.far_label
        ), distance


def fit_shapelet(
    windows: tuple[PatternWindow, ...],
    labels: tuple[TrainingLabel, ...],
    context: FitContext,
    *,
    length: int,
    candidate_cap: int = 32,
) -> ShapeletModel:
    context.validate(windows, max_count=64)
    _same_shape(windows)
    bounded_int(length, 2, min(64, len(windows[0].values)), "shapelet length")
    bounded_int(candidate_cap, 1, 128, "shapelet candidate cap")
    if len(labels) != len(windows) or len(windows) < 4 or len(windows[0].values) > 128:
        raise PatternError(
            "Shapelet fit requires 4-64 labelled windows of at most 128 bars"
        )
    if (
        candidate_cap
        * len(windows)
        * (len(windows[0].values) - length + 1)
        * length
        * windows[0].values.shape[1]
        > 20_000_000
    ):
        raise PatternError("Shapelet arithmetic budget exceeded")
    for window, label in zip(windows, labels, strict=True):
        label.validate(window, context)
    targets = [label.value for label in labels]
    if len(set(targets)) != 2:
        raise PatternError("Discriminative shapelets need both declared target classes")
    locations = [
        (row, start)
        for row in range(len(windows))
        for start in range(len(windows[row].values) - length + 1)
    ]
    choices = np.linspace(
        0, len(locations) - 1, min(candidate_cap, len(locations)), dtype=int
    )
    best: tuple[float, int, Floats, float, int, int] | None = None
    for serial, choice in enumerate(choices):
        row, start = locations[int(choice)]
        candidate = normalize(windows[row].values[start : start + length], "Z_WINDOW")
        distances = np.array(
            [_shapelet_distance(window.values, candidate) for window in windows]
        )
        unique = np.unique(distances)
        for threshold in (unique[:-1] + unique[1:]) / 2:
            left = [
                targets[i] for i in range(len(targets)) if distances[i] <= threshold
            ]
            right = [
                targets[i] for i in range(len(targets)) if distances[i] > threshold
            ]
            gain = _entropy(targets) - (
                len(left) * _entropy(left) + len(right) * _entropy(right)
            ) / len(targets)
            if best is None or gain > best[0]:
                best = (
                    gain,
                    serial,
                    candidate,
                    float(threshold),
                    int(sum(left) * 2 > len(left)),
                    int(sum(right) * 2 > len(right)),
                )
    if best is None:
        raise PatternError(
            "No discriminative split exists; retain this rejected candidate search"
        )
    return ShapeletModel(
        context,
        best[2],
        best[3],
        best[0],
        best[4],
        best[5],
        len(choices),
        tuple(window.fingerprint for window in windows),
        windows[0].provenance.features,
    )


@dataclass(frozen=True, slots=True, eq=False)
class SAXModel:
    context: FitContext
    segments: int
    breakpoints: Floats
    vocabulary: tuple[str, ...]
    transitions: tuple[tuple[str, str, int], ...]
    train_fingerprints: tuple[str, ...]
    features: tuple[str, ...]

    def _word(self, window: PatternWindow) -> str:
        if window.values.shape[1] != 1 or window.provenance.features != self.features:
            raise PatternError("This SAX profile is univariate")
        reduced = paa(normalize(window.values, "Z_WINDOW"), self.segments).ravel()
        return "".join(
            chr(65 + int(value))
            for value in np.searchsorted(
                self.breakpoints.ravel(), reduced, side="right"
            )
        )

    def transform(self, window: PatternWindow, *, decision_ns: int) -> tuple[str, str]:
        self.context.prediction(window, decision_ns)
        word = self._word(window)
        return word, "KNOWN" if word in self.vocabulary else "UNKNOWN"


def fit_sax(
    windows: tuple[PatternWindow, ...],
    context: FitContext,
    *,
    segments: int = 4,
    alphabet: int = 4,
) -> SAXModel:
    """Empirical-quantile SAX variant; no Gaussian SAX lower-bound claim."""
    context.validate(windows)
    _same_shape(windows)
    bounded_int(alphabet, 2, 16, "SAX alphabet")
    if windows[0].values.shape[1] != 1:
        raise PatternError("This SAX profile is univariate")
    reduced = np.concatenate(
        [
            paa(normalize(window.values, "Z_WINDOW"), segments).ravel()
            for window in windows
        ]
    )
    breaks = freeze(
        np.quantile(reduced, np.arange(1, alphabet) / alphabet).reshape(-1, 1)
    )
    if len(np.unique(breaks)) != alphabet - 1:
        raise PatternError(
            "Training values cannot support the requested symbolic alphabet"
        )
    model = SAXModel(
        context,
        segments,
        breaks,
        (),
        (),
        tuple(window.fingerprint for window in windows),
        windows[0].provenance.features,
    )
    ordered = sorted(windows, key=lambda window: window.start_ns)
    if any(first.end_ns > second.start_ns for first, second in pairwise(ordered)):
        raise PatternError(
            "SAX transition counts require nonoverlapping chronological training events"
        )
    words = [model._word(window) for window in ordered]
    transitions: dict[tuple[str, str], int] = {}
    for pair in pairwise(words):
        transitions[pair] = transitions.get(pair, 0) + 1
    return SAXModel(
        context,
        segments,
        breaks,
        tuple(sorted(set(words))),
        tuple((a, b, count) for (a, b), count in sorted(transitions.items())),
        model.train_fingerprints,
        model.features,
    )


def _emissions(values: Floats, means: Floats, variances: Floats) -> Floats:
    log_probability = -0.5 * (
        np.log(2 * np.pi * variances)[None, :, :]
        + (values[:, None, :] - means[None, :, :]) ** 2 / variances[None, :, :]
    ).sum(axis=2)
    return np.exp(log_probability - log_probability.max(axis=1, keepdims=True)) + 1e-300


def _forward(
    emissions: Floats, transition: Floats, initial: Floats
) -> tuple[Floats, Floats]:
    alpha = np.empty_like(emissions)
    scales = np.empty((len(emissions), 1))
    for index, likelihood in enumerate(emissions):
        predicted = initial.ravel() if index == 0 else alpha[index - 1] @ transition
        joint = predicted * likelihood
        scales[index, 0] = joint.sum()
        alpha[index] = joint / scales[index, 0]
    return alpha, scales


@dataclass(frozen=True, slots=True, eq=False)
class GaussianHMM:
    context: FitContext
    means: Floats
    variances: Floats
    transition: Floats
    initial: Floats
    iterations: int
    training_rows: int
    training_available_ns: int
    features: tuple[str, ...]
    training_fingerprint: str

    def filter(self, window: PatternWindow, *, decision_ns: int) -> Floats:
        self.context.prediction(window, decision_ns)
        if (
            window.values.shape[1] != self.means.shape[1]
            or window.provenance.features != self.features
        ):
            raise PatternError("HMM feature schema differs")
        # No backward pass at inference: prefix probabilities never use suffixes.
        probabilities, _ = _forward(
            _emissions(window.values, self.means, self.variances),
            self.transition,
            self.initial,
        )
        return freeze(probabilities)


def fit_hmm(
    frame: CausalFrame,
    context: FitContext,
    *,
    states: int = 2,
    iterations: int = 12,
    variance_floor: float = 1e-6,
) -> GaussianHMM:
    """Diagonal Gaussian Baum-Welch; backward messages are confined to train."""
    bounded_int(states, 2, 4, "HMM state count")
    bounded_int(iterations, 1, 30, "HMM iterations")
    if not np.isfinite(variance_floor) or not 1e-12 <= variance_floor <= 1:
        raise PatternError("Explicit HMM variance floor is required")
    train = frame.known(context.train_cutoff_ns)
    if not states * 3 <= len(train.values) <= 4096 or train.values.shape[1] > 8:
        raise PatternError("HMM training size exceeds bounded profile")
    if np.any(np.diff(train.close_ns) != train.step_ns):
        raise PatternError(
            "HMM transitions cannot silently span missing bars/session gaps"
        )
    values = train.values
    ordered = values[np.argsort(values[:, 0], kind="stable")]
    means = ordered[np.linspace(0, len(values) - 1, states, dtype=int)].copy()
    variances = np.tile(np.maximum(values.var(axis=0), variance_floor), (states, 1))
    transition = np.full((states, states), 0.1 / (states - 1))
    np.fill_diagonal(transition, 0.9)
    initial = np.full((states, 1), 1 / states)
    for _ in range(iterations):
        emissions = _emissions(values, means, variances)
        alpha, scales = _forward(emissions, transition, initial)
        beta = np.ones_like(alpha)
        for index in range(len(values) - 2, -1, -1):
            beta[index] = (
                transition
                @ (emissions[index + 1] * beta[index + 1])
                / scales[index + 1, 0]
            )
        gamma = alpha * beta
        gamma /= gamma.sum(axis=1, keepdims=True)
        counts = np.full((states, states), 1e-8)
        for index in range(len(values) - 1):
            joint = (
                alpha[index, :, None]
                * transition
                * (emissions[index + 1] * beta[index + 1])[None, :]
            )
            counts += joint / joint.sum()
        transition = counts / counts.sum(axis=1, keepdims=True)
        weight = np.maximum(gamma.sum(axis=0), 1e-12)
        means = (gamma.T @ values) / weight[:, None]
        variances = np.maximum(
            (gamma[:, :, None] * (values[:, None, :] - means[None, :, :]) ** 2).sum(
                axis=0
            )
            / weight[:, None],
            variance_floor,
        )
        initial = gamma[0].reshape(-1, 1)
    order = np.argsort(means[:, 0], kind="stable")
    return GaussianHMM(
        context,
        freeze(means[order]),
        freeze(variances[order]),
        freeze(transition[order][:, order]),
        freeze(initial[order]),
        iterations,
        len(values),
        int(train.available_ns.max()),
        train.provenance.features,
        train.fingerprint,
    )


@dataclass(frozen=True, slots=True, eq=False)
class ClusterModel:
    context: FitContext
    medoids: Floats
    radii: tuple[float, ...]
    segments: int
    train_fingerprints: tuple[str, ...]
    features: tuple[str, ...]

    def assign(
        self, window: PatternWindow, *, decision_ns: int
    ) -> tuple[int | None, float]:
        self.context.prediction(window, decision_ns)
        if window.provenance.features != self.features:
            raise PatternError("Cluster feature schema differs")
        value = paa(normalize(window.values, "Z_WINDOW"), self.segments).ravel()
        if len(value) != self.medoids.shape[1]:
            raise PatternError("Cluster query has incompatible features")
        distances = np.sqrt(np.mean((self.medoids - value) ** 2, axis=1))
        index = int(distances.argmin())
        return (index if distances[index] <= self.radii[index] else None), float(
            distances[index]
        )


def fit_clusters(
    windows: tuple[PatternWindow, ...],
    context: FitContext,
    *,
    clusters: int = 2,
    segments: int = 4,
    radius_factor: float = 1.25,
) -> ClusterModel:
    """Deterministic alternate k-medoids on train PAA; radius is train calibrated."""
    context.validate(windows, max_count=128)
    _same_shape(windows)
    bounded_int(clusters, 1, min(8, len(windows)), "cluster count")
    if not np.isfinite(radius_factor) or not 1 <= radius_factor <= 5:
        raise PatternError("Cluster radius factor must lie in [1,5]")
    values = np.stack(
        [
            paa(normalize(window.values, "Z_WINDOW"), segments).ravel()
            for window in windows
        ]
    )
    distances = np.sqrt(np.mean((values[:, None, :] - values[None, :, :]) ** 2, axis=2))
    medoids = [0]
    while len(medoids) < clusters:
        nearest = distances[:, medoids].min(axis=1)
        nearest[medoids] = -1
        medoids.append(int(nearest.argmax()))
    for _ in range(30):
        assignment = distances[:, medoids].argmin(axis=1)
        updated = list(medoids)
        for index in range(clusters):
            members = np.flatnonzero(assignment == index)
            if len(members):
                updated[index] = int(
                    members[distances[np.ix_(members, members)].sum(axis=1).argmin()]
                )
        if updated == medoids:
            break
        medoids = updated
    assignment = distances[:, medoids].argmin(axis=1)
    radii = tuple(
        max(1e-9, float(distances[assignment == index, medoid].max()) * radius_factor)
        if np.any(assignment == index)
        else 1e-9
        for index, medoid in enumerate(medoids)
    )
    return ClusterModel(
        context,
        freeze(values[medoids]),
        radii,
        segments,
        tuple(window.fingerprint for window in windows),
        windows[0].provenance.features,
    )


class Representation(Protocol):
    """Optional plugin contract. No deep model is supplied or validated here."""

    name: str
    context: FitContext

    def encode(self, window: PatternWindow, *, decision_ns: int) -> Floats: ...


@dataclass(frozen=True, slots=True)
class ClassicalRepresentation:
    context: FitContext
    segments: int = 4
    name: str = "WINDOW_Z_PAA_CLASSICAL_BASELINE"

    def encode(self, window: PatternWindow, *, decision_ns: int) -> Floats:
        self.context.prediction(window, decision_ns)
        return paa(normalize(window.values, "Z_WINDOW"), self.segments)


def representation_comparison(
    window: PatternWindow,
    baseline: ClassicalRepresentation,
    *,
    decision_ns: int,
    optional: Representation | None = None,
) -> dict[str, object]:
    classical = baseline.encode(window, decision_ns=decision_ns)
    result: dict[str, object] = {
        "method_id": "PAT-15",
        "baseline": baseline.name,
        "baseline_values": classical.tolist(),
        "optional_status": "NOT_INSTALLED_UNVALIDATED",
        "window_fingerprint": window.fingerprint,
    }
    if optional is not None:
        if optional.context != baseline.context:
            raise PatternError(
                "Optional representation must bind the same training boundary"
            )
        encoded = freeze(optional.encode(window, decision_ns=decision_ns))
        result.update(
            optional_name=optional.name,
            optional_values=encoded.tolist(),
            optional_status="EXECUTED_UNVALIDATED",
        )
    return result
