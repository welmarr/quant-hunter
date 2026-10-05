"""Bounded numeric inputs. These types grant no registry or research authority."""

from __future__ import annotations

from dataclasses import dataclass
from hashlib import sha256

import numpy as np
from numpy.typing import ArrayLike, NDArray

MAX_ROWS = 65_536
MAX_FEATURES = 16
MAX_WINDOW = 512
type Floats = NDArray[np.float64]
type Integers = NDArray[np.int64]


class PatternError(ValueError):
    """An input, temporal or resource contract failed; no result is authorized."""


class SearchCancelledError(PatternError):
    """Cancelled at a completed block boundary; the last snapshot remains valid."""


def bounded_int(value: int, low: int, high: int, name: str) -> int:
    if type(value) is not int or not low <= value <= high:
        raise PatternError(f"{name} must be an integer in [{low}, {high}]")
    return value


def instant(value: int) -> int:
    return bounded_int(value, 1, 2**63 - 1, "UTC nanoseconds")


def freeze(values: ArrayLike, *, dimensions: int = 2) -> Floats:
    array = np.asarray(values, dtype=np.float64)
    if (
        array.ndim != dimensions
        or not 1 <= array.size <= MAX_ROWS * MAX_FEATURES
        or not np.isfinite(array).all()
        or np.any(np.abs(array) > 1e100)
    ):
        raise PatternError("Expected bounded finite numeric observations")
    # Bytes-backed views cannot be made writable with setflags(write=True).
    return np.frombuffer(array.tobytes(), dtype=np.float64).reshape(array.shape)


def freeze_times(values: ArrayLike, count: int) -> Integers:
    array = np.asarray(values)
    if array.dtype.kind not in "iu" or array.shape != (count,):
        raise PatternError("Timestamp arrays require integral UTC nanoseconds")
    if np.any(array <= 0) or np.any(array > 2**63 - 1):
        raise PatternError("Timestamp is outside the supported UTC range")
    return np.frombuffer(array.astype(np.int64).tobytes(), dtype=np.int64)


@dataclass(frozen=True, slots=True)
class Provenance:
    dataset_id: str
    dataset_version: str
    instrument_id: str
    timeframe: str
    features: tuple[str, ...] = ("close",)

    def __post_init__(self) -> None:
        fields = (
            self.dataset_id,
            self.dataset_version,
            self.instrument_id,
            self.timeframe,
        )
        if any(
            not isinstance(item, str) or not 1 <= len(item) <= 200 for item in fields
        ):
            raise PatternError(
                "Explicit bounded dataset/version/instrument/timeframe required"
            )
        if (
            not isinstance(self.features, tuple)
            or not 1 <= len(self.features) <= MAX_FEATURES
            or len(set(self.features)) != len(self.features)
            or any(
                not isinstance(item, str) or not 1 <= len(item) <= 64
                for item in self.features
            )
        ):
            raise PatternError("Feature names must be distinct and bounded")


@dataclass(frozen=True, slots=True, eq=False)
class CausalFrame:
    values: Floats
    close_ns: Integers
    available_ns: Integers
    step_ns: int
    provenance: Provenance

    @property
    def fingerprint(self) -> str:
        digest = sha256(b"qh-pattern-frame-f64le-i64le-v1\0")
        digest.update(self.values.astype("<f8").tobytes())
        digest.update(self.close_ns.astype("<i8").tobytes())
        digest.update(self.available_ns.astype("<i8").tobytes())
        digest.update(repr((self.step_ns, self.provenance)).encode())
        return "sha256:" + digest.hexdigest()

    def __post_init__(self) -> None:
        values = freeze(self.values)
        if not 1 <= len(values) <= MAX_ROWS or values.shape[1] != len(
            self.provenance.features
        ):
            raise PatternError("Frame size or feature schema is invalid")
        close = freeze_times(self.close_ns, len(values))
        available = freeze_times(self.available_ns, len(values))
        bounded_int(self.step_ns, 1, 86_400_000_000_000, "bar duration")
        if close[0] <= self.step_ns or np.any(np.diff(close) <= 0):
            raise PatternError(
                "Closed bars must have distinct increasing positive intervals"
            )
        if np.any(available < close):
            raise PatternError("Availability cannot precede a bar's close")
        object.__setattr__(self, "values", values)
        object.__setattr__(self, "close_ns", close)
        object.__setattr__(self, "available_ns", available)

    def known(self, decision_ns: int) -> CausalFrame:
        instant(decision_ns)
        mask = (self.close_ns <= decision_ns) & (self.available_ns <= decision_ns)
        if not mask.any():
            raise PatternError("No closed available observations")
        return CausalFrame(
            self.values[mask],
            self.close_ns[mask],
            self.available_ns[mask],
            self.step_ns,
            self.provenance,
        )

    def window(
        self, start: int, stop: int, *, decision_ns: int, event_group: str = ""
    ) -> PatternWindow:
        bounded_int(start, 0, len(self.values) - 1, "window start")
        bounded_int(
            stop, start + 1, min(len(self.values), start + MAX_WINDOW), "window stop"
        )
        instant(decision_ns)
        close = self.close_ns[start:stop]
        available = self.available_ns[start:stop]
        if np.any(np.diff(close) != self.step_ns):
            raise PatternError(
                "A pattern window cannot cross missing bars or session gaps"
            )
        if int(close[-1]) > decision_ns or int(available.max()) > decision_ns:
            raise PatternError("Window contains incomplete or unavailable observations")
        return PatternWindow(
            self.values[start:stop],
            int(close[0]) - self.step_ns,
            int(close[-1]),
            int(available.max()),
            self.step_ns,
            self.provenance,
            event_group,
        )


@dataclass(frozen=True, slots=True, eq=False)
class PatternWindow:
    values: Floats
    start_ns: int
    end_ns: int
    available_ns: int
    step_ns: int
    provenance: Provenance
    event_group: str = ""

    def __post_init__(self) -> None:
        values = freeze(self.values)
        if not 2 <= len(values) <= MAX_WINDOW or values.shape[1] != len(
            self.provenance.features
        ):
            raise PatternError("Pattern requires 2-512 rows with its declared features")
        for value in (self.start_ns, self.end_ns, self.available_ns):
            instant(value)
        bounded_int(self.step_ns, 1, 86_400_000_000_000, "bar duration")
        if (
            self.end_ns - self.start_ns != len(values) * self.step_ns
            or self.available_ns < self.end_ns
        ):
            raise PatternError("Window times do not describe closed uniform bars")
        if not isinstance(self.event_group, str) or len(self.event_group) > 200:
            raise PatternError("Event group must be a bounded explicit label")
        object.__setattr__(self, "values", values)

    @property
    def fingerprint(self) -> str:
        digest = sha256(self.values.tobytes())
        digest.update(
            repr(
                (
                    self.start_ns,
                    self.end_ns,
                    self.available_ns,
                    self.step_ns,
                    self.provenance,
                    self.event_group,
                )
            ).encode()
        )
        return "sha256:" + digest.hexdigest()

    def require_known(self, decision_ns: int) -> None:
        if self.available_ns > instant(decision_ns):
            raise PatternError("Pattern was not available at the decision time")


@dataclass(frozen=True, slots=True)
class FitContext:
    train_cutoff_ns: int
    validation_start_ns: int
    purge_ns: int = 0

    def __post_init__(self) -> None:
        instant(self.train_cutoff_ns)
        instant(self.validation_start_ns)
        bounded_int(self.purge_ns, 0, 10**18, "purge duration")
        if self.train_cutoff_ns + self.purge_ns >= self.validation_start_ns:
            raise PatternError("Training plus purge must strictly precede validation")

    def validate(
        self, windows: tuple[PatternWindow, ...], *, max_count: int = 256
    ) -> None:
        if not isinstance(windows, tuple) or not 1 <= len(windows) <= max_count:
            raise PatternError("Training windows must be an explicitly bounded tuple")
        for window in windows:
            window.require_known(self.train_cutoff_ns)
            if window.end_ns + self.purge_ns >= self.validation_start_ns:
                raise PatternError(
                    "Training support overlaps the purged validation boundary"
                )

    def prediction(self, window: PatternWindow, decision_ns: int) -> None:
        window.require_known(decision_ns)
        if window.start_ns < self.validation_start_ns:
            raise PatternError(
                "Prediction window begins before frozen validation boundary"
            )


@dataclass(frozen=True, slots=True)
class TrainingLabel:
    value: int
    horizon_end_ns: int
    available_ns: int

    def validate(self, window: PatternWindow, context: FitContext) -> None:
        bounded_int(self.value, 0, 1, "binary label")
        instant(self.horizon_end_ns)
        instant(self.available_ns)
        if (
            not window.end_ns
            <= self.horizon_end_ns
            <= self.available_ns
            <= context.train_cutoff_ns
        ):
            raise PatternError(
                "Training label horizon/availability exceeds training information"
            )
        if self.horizon_end_ns + context.purge_ns >= context.validation_start_ns:
            raise PatternError("Label support overlaps the purged validation boundary")
