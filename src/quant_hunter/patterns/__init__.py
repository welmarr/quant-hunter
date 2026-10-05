"""Pure PatternLab computations. No file, network, registry or execution authority."""

from quant_hunter.patterns.catalog import METHODS, MethodSpec
from quant_hunter.patterns.contracts import (
    CausalFrame,
    FitContext,
    PatternError,
    PatternWindow,
    Provenance,
    SearchCancelledError,
    TrainingLabel,
)
from quant_hunter.patterns.diagnostics import (
    align_asof,
    compare_dtw,
    fit_cusum,
    geometry,
    motif_profile,
    recurrence,
    spectra_haar,
)
from quant_hunter.patterns.learned import (
    ClassicalRepresentation,
    fit_clusters,
    fit_hmm,
    fit_sax,
    fit_shapelet,
    representation_comparison,
)
from quant_hunter.patterns.outcomes import outcome_summary
from quant_hunter.patterns.representations import (
    constrained_dtw,
    normalize,
    paa,
    relative_candles,
)
from quant_hunter.patterns.search import (
    ObservedOutcome,
    SearchConfig,
    SearchEngine,
    SearchHit,
    SearchResult,
    deduplicate,
    search_blocks,
)
from quant_hunter.patterns.validation import (
    block_permutation_test,
    fdr_adjust,
    stability_and_costs,
)

__all__ = [
    "METHODS",
    "CausalFrame",
    "ClassicalRepresentation",
    "FitContext",
    "MethodSpec",
    "ObservedOutcome",
    "PatternError",
    "PatternWindow",
    "Provenance",
    "SearchCancelledError",
    "SearchConfig",
    "SearchEngine",
    "SearchHit",
    "SearchResult",
    "TrainingLabel",
    "align_asof",
    "block_permutation_test",
    "compare_dtw",
    "constrained_dtw",
    "deduplicate",
    "fdr_adjust",
    "fit_clusters",
    "fit_cusum",
    "fit_hmm",
    "fit_sax",
    "fit_shapelet",
    "geometry",
    "motif_profile",
    "normalize",
    "outcome_summary",
    "paa",
    "recurrence",
    "relative_candles",
    "representation_comparison",
    "search_blocks",
    "spectra_haar",
    "stability_and_costs",
]
