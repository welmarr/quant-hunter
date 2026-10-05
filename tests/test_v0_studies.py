"""Study adapters evaluate real reviewed mathematics after input-only preparation."""

from __future__ import annotations

import hashlib
from copy import deepcopy
from dataclasses import asdict
from datetime import datetime, timedelta
from math import log, sqrt
from statistics import stdev
from typing import cast

import pytest

from quant_hunter.config import JsonRecord, JsonValue
from quant_hunter.config.canonical import canonicalize_json, parse_json_document
from quant_hunter.research_methods import MethodError, studies
from quant_hunter.research_methods.studies import (
    StudyError,
    execute_study,
    list_studies,
    prepare_study,
)

IDS = tuple(definition.study_id for definition in list_studies())


def record(value: JsonValue) -> JsonRecord:
    assert isinstance(value, dict)
    return value


def payload(raw: bytes) -> JsonRecord:
    return record(parse_json_document(raw))


def evaluate(
    study_id: str, scenario: str = "POSITIVE", parameter: float | None = None
) -> JsonRecord:
    config, raw = prepare_study(study_id, scenario, parameter)
    return execute_study(raw, config)


def test_catalog_has_exact_domains_distinct_baselines_and_json_safe_metadata() -> None:
    assert IDS[:10] == tuple(f"CRP-{i:02}" for i in range(1, 11))
    assert IDS[10:] == ("ENS-COV", "META-OOF")
    for definition in list_studies():
        assert (
            definition.parameter_min
            <= definition.parameter_default
            <= definition.parameter_max
        )
        assert (
            definition.implemented_scope
            and definition.null_behavior
            and definition.assumptions
        )
        assert "SYNTHETIC" in str(asdict(definition))


def test_prepare_never_calls_any_fit_signal_or_evaluation_function(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def forbidden(*args: object, **kwargs: object) -> object:
        raise AssertionError("evaluation attempted before Item8")

    for name in (
        "ecm_forecast",
        "fit_cointegration",
        "fit_covariance_ensemble",
        "fit_garch",
        "fit_pca",
        "fit_surprise_scale",
        "fit_temporal_meta",
        "forward_carry",
        "fx_cross_section_momentum",
        "garch_forecast",
        "macro_surprise",
        "meta_prediction",
        "order_flow_imbalance",
        "pca_residual",
        "portfolio_net_return",
        "time_series_momentum",
        "value_momentum",
        "variance_scores",
        "volatility_managed_exposure",
    ):
        monkeypatch.setattr(studies, name, forbidden)
    for study_id in IDS:
        for scenario in studies.SCENARIOS:
            config, raw = prepare_study(study_id, scenario)
            assert config["evidence_mode"] == "SYNTHETIC"
            assert canonicalize_json(payload(raw)) == raw
            assert "fitted_model" not in payload(raw)


@pytest.mark.parametrize("study_id", IDS)
def test_preparation_and_execution_are_deterministic_and_inputs_unchanged(
    study_id: str,
) -> None:
    config, raw = prepare_study(study_id)
    assert prepare_study(study_id) == (config, raw)
    copy = deepcopy(config)
    result = execute_study(raw, config)
    assert execute_study(raw, config) == result and config == copy
    assert result["assessment"] == "EMPIRICALLY_UNVALIDATED"
    assert result["input_digest"] == "sha256:" + hashlib.sha256(raw).hexdigest()
    assert (
        result["config_digest"]
        == "sha256:" + hashlib.sha256(canonicalize_json(config)).hexdigest()
    )
    assert result["metrics"] and result["signals"] is not None
    canonicalize_json(result)


@pytest.mark.parametrize("study_id", IDS)
def test_explicit_sensitivity_parameter_changes_relevant_computation(
    study_id: str,
) -> None:
    base, changed = evaluate(study_id), evaluate(study_id, "SENSITIVITY")
    assert base["signals"] != changed["signals"]
    assert base["metrics"] != changed["metrics"]


@pytest.mark.parametrize("study_id", ["CRP-05", "CRP-07", "CRP-08"])
def test_degenerate_nulls_raise_and_never_fabricate_success(study_id: str) -> None:
    config, raw = prepare_study(study_id, "NULL")
    with pytest.raises(MethodError):
        execute_study(raw, config)


@pytest.mark.parametrize(
    "study_id", ["CRP-01", "CRP-02", "CRP-04", "CRP-06", "CRP-09", "CRP-10", "META-OOF"]
)
def test_nulls_remove_the_mechanism_in_controlled_examples(study_id: str) -> None:
    result = evaluate(study_id, "NULL")
    metrics = record(result["metrics"])
    key = {
        "CRP-01": "exposure",
        "CRP-02": "gross_exposure",
        "CRP-04": "gross_exposure",
        "CRP-06": "residual_sum_squares",
        "CRP-09": "standardized_surprise",
        "CRP-10": "order_flow_imbalance",
        "META-OOF": "forecast",
    }[study_id]
    assert cast(float, metrics[key]) == pytest.approx(0, abs=1e-20)


def test_crp01_scalar_volatility_and_causal_cost_oracle() -> None:
    result = evaluate("CRP-01")
    sigma = stdev([0.1, -0.1, 0.1]) * sqrt(12)
    exposure = 0.1 / sigma
    metrics, accounting = record(result["metrics"]), record(result["accounting"])
    assert metrics["annualized_volatility"] == pytest.approx(sigma)
    assert metrics["exposure"] == pytest.approx(0.25)
    assert accounting["gross_return"] == pytest.approx(exposure * 0.01)
    assert accounting["net_return"] == pytest.approx(0.00225)
    assert accounting["final_wealth_index"] == pytest.approx(1.00225)


@pytest.mark.parametrize("study_id", ["CRP-02", "CRP-04"])
def test_rank_portfolio_independent_oracle(study_id: str) -> None:
    result = evaluate(study_id)
    assert result["signals"] == [0.5, 0, -0.5]
    accounting = record(result["accounting"])
    # .5*.02 +(-.5)*(-.01) = .015; gross traded notional1; cost.001.
    assert accounting["gross_return"] == pytest.approx(0.015)
    assert accounting["net_return"] == pytest.approx(0.014)


def test_forward_carry_differs_from_realized_terminal_spot_payoff() -> None:
    result = evaluate("CRP-03")
    metrics, accounting = record(result["metrics"]), record(result["accounting"])
    assert metrics["horizon_carry"] == pytest.approx((1.25 - 1.2) / 1.25)
    assert metrics["realized_synthetic_forward_return"] == pytest.approx(
        (1.27 - 1.2) / 1.25
    )
    assert accounting["net_return"] == pytest.approx(0.055)
    null = evaluate("CRP-03", "NULL")
    assert record(null["metrics"])["horizon_carry"] == 0
    assert record(null["accounting"])["net_return"] == pytest.approx(-0.001)


def test_ecm_report_contains_actual_fit_and_scalar_forecast_identity() -> None:
    config, raw = prepare_study("CRP-05")
    result = execute_study(raw, config)
    inputs = record(payload(raw)["inputs"])
    known = cast(list[float], record(inputs["query"])["values"])
    previous = cast(list[float], record(inputs["previous"])["values"])
    model = record(result["fitted_model"])
    coefficients = cast(list[float], model["ecm_coefficients"])
    residual = (
        known[0]
        - cast(float, model["intercept"])
        - known[1] * cast(float, model["hedge_ratio"])
    )
    oracle = (
        coefficients[0]
        + coefficients[1] * residual
        + coefficients[2] * (known[0] - previous[0])
        + coefficients[3] * (known[1] - previous[1])
    )
    assert model["eligible"] is True
    assert result["signals"] == pytest.approx(oracle)
    assert record(result["metrics"])["squared_error"] == pytest.approx(
        (oracle - 0.5) ** 2
    )
    assert result["accounting"] is None


def test_pca_residual_projection_is_not_a_fabricated_trade() -> None:
    result = evaluate("CRP-06")
    assert result["signals"] == pytest.approx([1, -2])
    assert record(result["metrics"])["residual_sum_squares"] == pytest.approx(5)
    assert result["accounting"] is None


def test_garch_actual_fit_matches_independent_variance_recursion_and_score() -> None:
    config, raw = prepare_study("CRP-07")
    result = execute_study(raw, config)
    observations = cast(list[JsonRecord], payload(raw)["observations"])
    returns = [cast(list[float], row["values"])[0] for row in observations]
    model = record(result["fitted_model"])
    h = sum(x * x for x in returns) / len(returns)
    for value in returns:
        h = (
            cast(float, model["omega"])
            + cast(float, model["alpha"]) * value * value
            + cast(float, model["beta"]) * h
        )
    assert model["converged"] is True and cast(int, model["iterations"]) > 0
    metrics = record(result["metrics"])
    assert metrics["next_variance"] == pytest.approx(h)
    assert metrics["one_observation_mse"] == pytest.approx((h - 0.0004) ** 2)
    assert metrics["one_observation_qlike"] == pytest.approx(log(h) + 0.0004 / h)


def test_inverse_variance_and_macro_ofi_small_oracles() -> None:
    vol = evaluate("CRP-08")
    assert vol["signals"] == pytest.approx(0.0002 / (0.01**2 + 0.01**2))
    assert record(vol["accounting"])["net_return"] == pytest.approx(0.009)
    surprise = evaluate("CRP-09")
    assert record(surprise["fitted_model"])["standard_deviation"] == 1
    assert surprise["signals"] == 2
    ofi = evaluate("CRP-10")
    assert record(ofi["signals"])["event_contributions"] == [7, 7, -12]
    assert record(ofi["metrics"])["order_flow_imbalance"] == 2


def test_covariance_and_oof_demos_report_later_comparisons_with_oracles() -> None:
    result = evaluate("ENS-COV")
    a, b = 0.0004 / 3 + 0.000001, 0.0016 / 3 + 0.000001
    weights = cast(list[float], result["signals"])
    assert weights == pytest.approx([b / (a + b), a / (a + b)], abs=1e-6)
    assert len(cast(list[JsonValue], result["comparison"])) == 2
    assert record(evaluate("ENS-COV", "NULL")["accounting"])[
        "net_return"
    ] == pytest.approx(-0.001)
    meta = evaluate("META-OOF")
    # Centered x SS5, sample variance5/3: ridge1 shrinks slope2 to1.5.
    assert meta["signals"] == pytest.approx(3 + 1.5 * (4 - 1.5))
    assert record(meta["metrics"])["squared_error"] == pytest.approx(1.5625)
    assert record(meta["comparison"])["base_squared_error"] == 16


@pytest.mark.parametrize(
    "study_id", ["CRP-01", "CRP-02", "CRP-03", "CRP-04", "CRP-08", "ENS-COV"]
)
def test_doubled_cost_degrades_same_positions_by_exact_added_turnover_cost(
    study_id: str,
) -> None:
    config, raw = prepare_study(study_id)
    baseline = execute_study(raw, config)
    changed = execute_study(raw, {**config, "cost_per_unit_turnover": 0.002})
    a, b = record(baseline["accounting"]), record(changed["accounting"])
    assert a["weights"] == b["weights"] and a["gross_return"] == b["gross_return"]
    assert cast(float, a["net_return"]) - cast(float, b["net_return"]) == pytest.approx(
        0.001 * cast(float, a["turnover_l1"])
    )


@pytest.mark.parametrize(
    "study_id",
    ["CRP-01", "CRP-02", "CRP-04", "CRP-05", "CRP-06", "CRP-07", "CRP-08", "ENS-COV"],
)
def test_future_invalid_numeric_row_does_not_enter_earlier_fit_or_signal(
    study_id: str,
) -> None:
    config, raw = prepare_study(study_id)
    original = execute_study(raw, config)
    data = payload(raw)
    rows = cast(list[JsonValue], data["observations"])
    count = len(cast(list[JsonValue], record(rows[0])["values"]))
    rows.append(
        {
            "at": config["target_end"],
            "available_at": config["target_end"],
            "values": ["UNAVAILABLE_NUMBER"] * count,
        }
    )
    changed = execute_study(canonicalize_json(data), config)
    assert changed["signals"] == original["signals"]
    assert changed["fitted_model"] == original["fitted_model"]
    assert changed["accounting"] == original["accounting"]
    assert changed["input_digest"] != original["input_digest"]


def test_oof_delayed_unread_target_and_prediction_do_not_enter_meta_fit() -> None:
    config, raw = prepare_study("META-OOF")
    original = execute_study(raw, config)
    data = payload(raw)
    rows = cast(list[JsonValue], record(data["inputs"])["oof"])
    rows.append(
        {
            "at": config["decision_at"],
            "label_end": config["target_end"],
            "label_available_at": config["target_available_at"],
            "base_training_end": config["train_end"],
            "predictions": ["UNAVAILABLE"],
            "target": "UNAVAILABLE",
        }
    )
    changed = execute_study(canonicalize_json(data), config)
    assert (
        changed["fitted_model"] == original["fitted_model"]
        and changed["signals"] == original["signals"]
    )


def test_delayed_macro_release_changes_usable_information_not_economic_date() -> None:
    config, raw = prepare_study("CRP-09")
    data = payload(raw)
    query = record(record(data["inputs"])["query_release"])
    query["available_at"] = config["target_start"]
    with pytest.raises(MethodError, match="unavailable"):
        execute_study(canonicalize_json(data), config)


def test_later_target_mutation_does_not_change_position_or_fit() -> None:
    config, raw = prepare_study("CRP-01")
    original = execute_study(raw, config)
    data = payload(raw)
    record(data["target"])["values"] = [-0.01]
    changed = execute_study(canonicalize_json(data), config)
    assert changed["signals"] == original["signals"]
    assert record(changed["accounting"])["gross_return"] == pytest.approx(
        -cast(float, record(original["accounting"])["gross_return"])
    )


@pytest.mark.parametrize(
    "change",
    [
        {"kind": "OTHER"},
        {"evidence_mode": "HISTORICAL"},
        {"purpose": "PROFIT"},
        {"variant": "UNREGISTERED"},
        {"parameter": 99},
        {"parameter": True},
        {"scenario": "UNKNOWN"},
        {"cost_per_unit_turnover": -0.01},
        {"train_end": "2020-01-05T00:00:00Z"},
        {"dataset_start": "2020-01-02T00:00:00Z"},
        {"dataset_end": "2021-01-01T00:00:00Z"},
        {"target_start": "2020-01-05T00:00:00Z"},
        {"decision_at": "2020-01-06T00:00:00Z"},
    ],
)
def test_config_binding_and_temporal_contradictions_fail(change: JsonRecord) -> None:
    config, raw = prepare_study("CRP-01")
    with pytest.raises(StudyError):
        execute_study(raw, {**config, **change})


@pytest.mark.parametrize(
    "raw",
    [b"", b"{}", b"[]", b"{", b'{"x":1,"x":2}', b'{"x":NaN}', b"x" * 2_000_001],
    ids=["empty", "missing", "array", "broken", "duplicate", "nonfinite", "oversized"],
)
def test_malformed_or_oversized_dataset_fails(raw: bytes) -> None:
    config, _ = prepare_study("CRP-01")
    with pytest.raises(StudyError):
        execute_study(raw, config)


def test_noncanonical_json_and_wrong_target_units_are_rejected() -> None:
    config, raw = prepare_study("CRP-01")
    with pytest.raises(StudyError, match="canonical"):
        execute_study(raw + b"\n", config)
    data = payload(raw)
    record(data["target"])["kind"] = "USD_PRICE"
    with pytest.raises(StudyError, match="units"):
        execute_study(canonicalize_json(data), config)


@pytest.mark.parametrize(
    "study_id,scenario,parameter",
    [
        ("UNKNOWN", "POSITIVE", None),
        ("CRP-01", "SEARCH_UNTIL_SUCCESS", None),
        ("CRP-01", "POSITIVE", True),
        ("CRP-01", "POSITIVE", float("nan")),
        ("CRP-01", "POSITIVE", 100),
    ],
)
def test_preparation_rejects_unknown_searches_and_unbounded_parameters(
    study_id: str, scenario: str, parameter: float | None
) -> None:
    with pytest.raises(StudyError):
        prepare_study(study_id, scenario, parameter)


@pytest.mark.parametrize("study_id", ["CRP-04", "CRP-09", "CRP-10"])
def test_future_unread_event_values_preserve_current_outputs(study_id: str) -> None:
    config, raw = prepare_study(study_id)
    original = execute_study(raw, config)
    data = payload(raw)
    inputs = record(data["inputs"])
    if study_id == "CRP-04":
        cast(list[JsonValue], inputs["fundamentals"]).append(
            {
                "asset": 0,
                "period_end": config["target_start"],
                "published_at": config["target_end"],
                "available_at": config["target_end"],
                "book_value_per_share": "UNREAD",
            }
        )
    elif study_id == "CRP-09":
        future = dict(record(cast(list[JsonValue], inputs["releases"])[0]))
        future.update(
            {
                "period_end": config["target_start"],
                "published_at": config["target_end"],
                "available_at": config["target_end"],
                "consensus_at": config["decision_at"],
                "actual": "UNREAD",
                "consensus": "UNREAD",
            }
        )
        cast(list[JsonValue], inputs["releases"]).append(future)
    else:
        cast(list[JsonValue], inputs["book"]).append(
            {
                "sequence": 4,
                "at": config["target_end"],
                "available_at": config["target_end"],
                "bid": "UNREAD",
                "ask": "UNREAD",
                "bid_size": "UNREAD",
                "ask_size": "UNREAD",
            }
        )
    changed = execute_study(canonicalize_json(data), config)
    assert (
        changed["signals"] == original["signals"]
        and changed["fitted_model"] == original["fitted_model"]
    )


def test_failed_fit_has_no_hidden_retry_or_success_fallback(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    config, raw = prepare_study("CRP-07")
    calls = 0

    def failure(*args: object, **kwargs: object) -> object:
        nonlocal calls
        calls += 1
        raise MethodError("GARCH_DID_NOT_CONVERGE")

    monkeypatch.setattr(studies, "fit_garch", failure)
    with pytest.raises(MethodError, match="GARCH_DID_NOT_CONVERGE"):
        execute_study(raw, config)
    assert calls == 1


@pytest.mark.parametrize(
    "kind",
    [
        "units",
        "columns",
        "target-columns",
        "row-schema",
        "future-query",
        "previous-query",
        "bad-time",
        "zero-terminal",
    ],
)
def test_row_units_dimensions_and_query_contracts_fail_closed(kind: str) -> None:
    study_id = "CRP-03" if kind == "zero-terminal" else "CRP-05"
    config, raw = prepare_study(study_id)
    data = payload(raw)
    inputs = record(data["inputs"])
    if kind == "units":
        data["observation_kind"] = "UNDECLARED_UNITS"
    elif kind == "columns":
        record(cast(list[JsonValue], data["observations"])[0])["values"] = [1]
    elif kind == "target-columns":
        record(data["target"])["values"] = [1, 2]
    elif kind == "row-schema":
        cast(list[JsonValue], data["observations"])[0] = []
    elif kind == "future-query":
        record(inputs["query"])["available_at"] = config["target_end"]
    elif kind == "previous-query":
        record(inputs["previous"])["at"] = config["decision_at"]
        record(inputs["previous"])["available_at"] = config["decision_at"]
    elif kind == "bad-time":
        record(inputs["query"])["at"] = "INVALIDZ"
    else:
        record(data["target"])["values"] = [0]
    with pytest.raises(StudyError):
        execute_study(canonicalize_json(data), config)


def test_matching_but_out_of_bounds_parameter_is_rejected_before_fit() -> None:
    config, raw = prepare_study("CRP-01")
    data = payload(raw)
    data["parameter"] = config["parameter"] = 0.99
    with pytest.raises(StudyError, match="bounds"):
        execute_study(canonicalize_json(data), config)


@pytest.mark.parametrize("field", ["at", "available_at"])
def test_target_actual_and_receipt_times_cannot_be_moved_before_decision(
    field: str,
) -> None:
    config, raw = prepare_study("CRP-01")
    data = payload(raw)
    record(data["target"])[field] = config["decision_at"]
    with pytest.raises(StudyError, match="target horizon"):
        execute_study(canonicalize_json(data), config)


def test_ecm_previous_observation_is_identical_to_retained_training_endpoint() -> None:
    config, raw = prepare_study("CRP-05")
    data = payload(raw)
    previous = record(record(data["inputs"])["previous"])
    assert previous == cast(list[JsonValue], data["observations"])[-1]
    previous["values"] = [7, 2.5]
    with pytest.raises(StudyError, match="retained last training"):
        execute_study(canonicalize_json(data), config)


@pytest.mark.parametrize("study_id", ["CRP-05", "CRP-07", "META-OOF"])
def test_forecast_horizon_cannot_silently_change_while_coverage_stays_consistent(
    study_id: str,
) -> None:
    config, raw = prepare_study(study_id)
    data = payload(raw)
    target = record(data["target"])
    for key in ("end", "at", "available_at"):
        target[key] = (
            (datetime.fromisoformat(cast(str, target[key])) + timedelta(days=1))
            .isoformat()
            .replace("+00:00", "Z")
        )
    config["target_end"] = target["end"]
    config["target_available_at"] = target["available_at"]
    config["dataset_end"] = (
        (
            datetime.fromisoformat(cast(str, target["available_at"]))
            + timedelta(microseconds=1)
        )
        .isoformat()
        .replace("+00:00", "Z")
    )
    with pytest.raises(StudyError, match="target must"):
        execute_study(canonicalize_json(data), config)


def test_oof_training_horizon_is_explicit_and_consistent_with_query() -> None:
    config, raw = prepare_study("META-OOF")
    data = payload(raw)
    row = record(cast(list[JsonValue], record(data["inputs"])["oof"])[0])
    row["label_end"] = (
        (datetime.fromisoformat(cast(str, row["label_end"])) + timedelta(minutes=1))
        .isoformat()
        .replace("+00:00", "Z")
    )
    with pytest.raises(StudyError, match="training label horizon"):
        execute_study(canonicalize_json(data), config)


@pytest.mark.parametrize("study_id", ["CRP-05", "CRP-07"])
def test_daily_forecast_rejects_irregular_usable_training_cadence(
    study_id: str,
) -> None:
    config, raw = prepare_study(study_id)
    data = payload(raw)
    row = record(cast(list[JsonValue], data["observations"])[1])
    for field in ("at", "available_at"):
        row[field] = (
            (datetime.fromisoformat(cast(str, row[field])) + timedelta(hours=1))
            .isoformat()
            .replace("+00:00", "Z")
        )
    with pytest.raises(StudyError, match="daily cadence"):
        execute_study(canonicalize_json(data), config)


@pytest.mark.parametrize(
    "study_id,scenario,seed",
    [
        ("CRP-05", "NULL", 801),
        ("CRP-05", "POSITIVE", 412),
        ("CRP-07", "POSITIVE", 809),
        ("CRP-01", "POSITIVE", 0),
    ],
)
def test_frozen_random_seed_is_actual_generator_identity(
    study_id: str, scenario: str, seed: int
) -> None:
    config, raw = prepare_study(study_id, scenario)
    assert config["random_seed"] == seed
    config["random_seed"] = seed + 1
    with pytest.raises(StudyError, match="random_seed"):
        execute_study(raw, config)


def test_frozen_cadence_cannot_be_changed_to_match_hostile_training() -> None:
    config, raw = prepare_study("CRP-07")
    config["observation_interval_seconds"] = 3600
    with pytest.raises(StudyError, match="cadence"):
        execute_study(raw, config)


@pytest.mark.parametrize("study_id", ["CRP-05", "CRP-07"])
def test_delayed_final_training_observation_cannot_shift_fixed_forecast_origin(
    study_id: str,
) -> None:
    config, raw = prepare_study(study_id)
    data = payload(raw)
    row = record(cast(list[JsonValue], data["observations"])[-1])
    row["available_at"] = config["decision_at"]
    with pytest.raises(StudyError, match="train_end"):
        execute_study(canonicalize_json(data), config)


def test_ecm_query_cannot_skip_a_daily_observation() -> None:
    config, raw = prepare_study("CRP-05")
    data = payload(raw)
    query = record(record(data["inputs"])["query"])
    shifted = (
        (datetime.fromisoformat(cast(str, query["at"])) + timedelta(hours=1))
        .isoformat()
        .replace("+00:00", "Z")
    )
    query["at"] = query["available_at"] = config["decision_at"] = shifted
    target = record(data["target"])
    for name in ("start", "end", "at", "available_at"):
        target[name] = (
            (datetime.fromisoformat(cast(str, target[name])) + timedelta(hours=1))
            .isoformat()
            .replace("+00:00", "Z")
        )
    for name in ("start", "end", "available_at"):
        config[f"target_{name}"] = target[name]
    config["dataset_end"] = (
        (
            datetime.fromisoformat(cast(str, target["available_at"]))
            + timedelta(microseconds=1)
        )
        .isoformat()
        .replace("+00:00", "Z")
    )
    with pytest.raises(StudyError, match="next observation"):
        execute_study(canonicalize_json(data), config)
