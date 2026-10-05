"""Stable method family keys, explicitly distinct from permanent research IDs."""

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class MethodSpec:
    family: str
    name: str
    entrypoint: str
    scope: str


METHODS = (
    MethodSpec(
        "PAT-01",
        "Exact bounded subsequence motifs and discords",
        "motif_profile",
        "Retrospective TRAIN only",
    ),
    MethodSpec(
        "PAT-02",
        "Constrained multivariate DTW",
        "compare_dtw",
        "Closed available windows; cell bound",
    ),
    MethodSpec(
        "PAT-03",
        "Discriminative information-gain shapelet",
        "fit_shapelet",
        "Train observations and labels only",
    ),
    MethodSpec(
        "PAT-04",
        "Empirical SAX vocabulary and transitions",
        "fit_sax",
        "Train calibration; unknown vocabulary allowed",
    ),
    MethodSpec(
        "PAT-05",
        "Two-sided reset CUSUM",
        "fit_cusum",
        "Train baseline; causal forward detection",
    ),
    MethodSpec(
        "PAT-06",
        "Diagonal Gaussian HMM",
        "fit_hmm",
        "Train EM; forward filtering only at inference",
    ),
    MethodSpec(
        "PAT-07",
        "Hann spectrum and Haar multiresolution",
        "spectra_haar",
        "Closed finite window; edges explicit",
    ),
    MethodSpec(
        "PAT-08",
        "Recurrence quantification",
        "recurrence",
        "Theiler exclusion and line thresholds",
    ),
    MethodSpec(
        "PAT-09",
        "Alternate k-medoids with rejection radius",
        "fit_clusters",
        "Train medoids; UNKNOWN/OOD permitted",
    ),
    MethodSpec(
        "PAT-10",
        "Mathematical range breakout and channel",
        "geometry",
        "Previous-close rules only",
    ),
    MethodSpec(
        "PAT-11",
        "Availability-aware multivariate alignment",
        "align_asof",
        "Bounded backward-only alignment",
    ),
    MethodSpec(
        "PAT-12",
        "Observed horizon distribution and uncertainty",
        "outcome_summary",
        "Deduplicated available events; descriptive only",
    ),
    MethodSpec(
        "PAT-13",
        "Historical state neighbors",
        "search_blocks",
        "Strict past plus observed outcome horizon",
    ),
    MethodSpec(
        "PAT-14",
        "Stability, costs, block nulls and FDR",
        "stability_and_costs",
        "Numerical controls; no scientific gate authority",
    ),
    MethodSpec(
        "PAT-15",
        "Optional representation comparison",
        "representation_comparison",
        "Real PAA baseline; deep model absent/unvalidated",
    ),
)
