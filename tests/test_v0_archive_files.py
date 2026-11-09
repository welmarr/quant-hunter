"""Synthetic archive/quote bytes: independent temporal, Decimal and governed oracles."""

from __future__ import annotations

import csv
import io
from copy import copy
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal, Inexact, localcontext
from hashlib import sha256
from pathlib import Path
from typing import cast

import pytest
from quant_hunter.sources.transport import SourceError
from test_v0_materialize import setup

from quant_hunter.config import JsonRecord, parse_json_document
from quant_hunter.sources import archive_files as f
from quant_hunter.sources.fx_forwards import (
    FORWARD_COLUMNS,
    ForwardFileImporter,
    ForwardQuery,
)
from quant_hunter.sources.macro_ces import CESArchiveImporter, CESArchiveQuery
from quant_hunter.sources.macro_surveys import (
    RTDSMImporter,
    RTDSMQuery,
    SurveyFileImporter,
    SurveyQuery,
)
from quant_hunter.sources.providers import ProviderService

NOW = datetime(2025, 3, 1, tzinfo=UTC)
CES = b"vintage_reference_month,2023-12,2024-01\n2023-12,100,\n2024-01,101,102\n2024-02,99,103\n"
CES_QUERY = CESArchiveQuery(
    "CES0000000001", date(2023, 12, 1), date(2024, 1, 31), date(2025, 2, 1)
)
RTDSM = b"DATE,ROUTPUT24Q1,ROUTPUT24M3\n2023:03,200,201\n2023:04,202,203\n2024:01,,\n"
RTDSM_QUERY = RTDSMQuery(
    "ROUTPUT",
    date(2023, 1, 1),
    date(2024, 3, 31),
    date(2025, 2, 1),
    (
        ("ROUTPUT24Q1", "Billions 2017 real USD SAAR"),
        ("ROUTPUT24M3", "Billions 2017 real USD SAAR"),
    ),
)
PHILLY = b"YEAR,QUARTER,UNEMP1,UNEMP2,UNEMP3,UNEMP4,UNEMP5,UNEMP6\n2024,1,3.7,3.8,3.9,4.0,4.1,4.2\n"
PHILLY_QUERY = SurveyQuery(
    "PHILADELPHIA_SPF_QUARTERLY_CSV_V1",
    "UNEMP",
    "PERCENT_LABOUR_FORCE",
    date(2024, 1, 1),
    date(2024, 12, 31),
    date(2025, 2, 1),
    "MEDIAN",
)
ECB = b"TARGET_PERIOD,FCT_SOURCE,POINT\n2024,17,2.1\n2025Jan,17,2.2\n2025Feb,21,2.3\n"
ECB_QUERY = SurveyQuery(
    "ECB_SPF_POINT_CSV_V1",
    "HICP",
    "PERCENT_YOY",
    date(2024, 1, 1),
    date(2024, 12, 31),
    date(2025, 2, 1),
    "INDIVIDUAL_POINT",
    "2024Q1",
)
FORWARD_QUERY = ForwardQuery(
    "EUR",
    "USD",
    "Synthetic licensed-source fixture",
    date(2024, 1, 1),
    date(2024, 1, 31),
    date(2025, 2, 1),
)


def changed[T](record: T, values: dict[str, object]) -> T:
    """Deliberately inject malformed fields into an independent test value."""
    result = copy(record)
    for key, value in values.items():
        object.__setattr__(result, key, value)
    return result


def forward_row() -> dict[str, str]:
    return dict(
        zip(
            FORWARD_COLUMNS,
            (
                "synthetic-1",
                "2024-01-02T12:00:00Z",
                "EUR",
                "USD",
                "2024-01-04",
                "2024-02-05",
                "1M",
                "POINTS",
                "1.10",
                "1.11",
                "-20",
                "-10",
                "0.0001",
                "",
            ),
            strict=True,
        )
    )


def forward_bytes(*rows: dict[str, str]) -> bytes:
    out = io.StringIO(newline="")
    writer = csv.DictWriter(out, fieldnames=FORWARD_COLUMNS, lineterminator="\n")
    writer.writeheader()
    writer.writerows(rows or (forward_row(),))
    return out.getvalue().encode()


def test_ces_revision_oracle_keeps_all_vintages_without_first_release_invention() -> (
    None
):
    batch = CESArchiveImporter().import_bytes(CES, CES_QUERY, NOW)
    assert len(batch.observations) == 5
    december = [row for row in batch.observations if row.period == "2023-12"]
    assert [row.value for row in december] == [Decimal(100), Decimal(101), Decimal(99)]
    assert len({row.vintage for row in december}) == 3
    assert batch.raw_pages[0].raw == CES
    assert batch.raw_pages[0].digest == "sha256:" + sha256(CES).hexdigest()
    assert all(
        row.publication_time is row.available_at is row.revision_time is None
        for row in batch.observations
    )
    assert not batch.coverage_complete and all(
        not row.point_in_time_eligible for row in batch.observations
    )
    changed = CES.replace(b"99,103", b"555,556")
    later = CESArchiveImporter().import_bytes(changed, CES_QUERY, NOW)
    assert later.observations[:3] == batch.observations[:3]
    assert later.raw_pages[0].digest != batch.raw_pages[0].digest


@pytest.mark.parametrize(
    "raw,code",
    [
        (CES.replace(b"2023-12,100,", b"2023-12,100,9"), "CES_VALUE_AFTER_VINTAGE"),
        (CES.replace(b"100", b"-1"), "CES_EMPLOYMENT_NEGATIVE"),
        (CES.replace(b"2024-02,99", b"2023-12,99"), "CES_VINTAGE_ORDER"),
        (CES.replace(b"2024-02,99", b"2026-02,99"), "CES_VINTAGE_ORDER"),
        (
            CES.replace(b"vintage_reference_month", b"publication_time"),
            "CES_MATRIX_HEADER",
        ),
        (
            CES.replace(b"month,2023-12,2024-01", b"month,2024-01,2023-12"),
            "CES_REFERENCE_ORDER",
        ),
        (CES.replace(b"100", b"=NOW()"), "INVALID_NUMBER"),
        (CES.replace(b"100", b"NaN"), "INVALID_NUMBER"),
    ],
)
def test_ces_hostile_values_do_not_create_temporal_certainty(
    raw: bytes, code: str
) -> None:
    with pytest.raises(SourceError, match=code):
        CESArchiveImporter().import_bytes(raw, CES_QUERY, NOW)


@pytest.mark.parametrize(
    "change,code",
    [
        ({"series_id": "CES0000000002"}, "CES_EMPLOYMENT_SERIES"),
        ({"profile": "AUTO_DETECT"}, "CES_PROFILE"),
        (
            {"start": date(2020, 1, 1), "end": date(2020, 2, 1)},
            "CES_SELECTED_RANGE_EMPTY",
        ),
        ({"export_vintage": date(2026, 1, 1)}, "ARCHIVE_RANGE_OR_VINTAGE"),
    ],
)
def test_ces_closed_configuration(change: dict[str, object], code: str) -> None:
    with pytest.raises(SourceError, match=code):
        CESArchiveImporter().import_bytes(CES, changed(CES_QUERY, change), NOW)


def test_ces_missing_is_not_zero_and_explicit_fixture_mode() -> None:
    batch = CESArchiveImporter().import_bytes(
        CES.replace(b"101", b"."), CES_QUERY, NOW, evidence_mode="RECORDED_FIXTURE"
    )
    missing = batch.observations[1]
    assert missing.value is None and "MISSING_VALUE" in missing.quality_flags
    with pytest.raises(SourceError, match="INVALID_EVIDENCE_MODE"):
        CESArchiveImporter().import_bytes(
            CES, CES_QUERY, NOW, evidence_mode="HISTORICAL_REAL"
        )


def test_rtdsm_independent_orientation_and_month_precision() -> None:
    batch = RTDSMImporter().import_bytes(RTDSM, RTDSM_QUERY, NOW)
    assert [(r.period, r.vintage, r.value) for r in batch.observations] == [
        ("2023Q3", "ROUTPUT24Q1", Decimal(200)),
        ("2023Q3", "ROUTPUT24M3", Decimal(201)),
        ("2023Q4", "ROUTPUT24Q1", Decimal(202)),
        ("2023Q4", "ROUTPUT24M3", Decimal(203)),
    ]
    assert "VINTAGE_MONTH:2024-02" in batch.observations[0].quality_flags
    assert all(r.publication_time is r.available_at is None for r in batch.observations)
    changed = RTDSM.replace(b"200,201", b"200,999")
    assert (
        RTDSMImporter().import_bytes(changed, RTDSM_QUERY, NOW).observations[0]
        == batch.observations[0]
    )


@pytest.mark.parametrize(
    "raw,change,code",
    [
        (RTDSM.replace(b"2024:01,,", b"2024:01,1,"), {}, "RTDSM_VALUE_BEFORE"),
        (RTDSM.replace(b"2023:04", b"2023:03"), {}, "RTDSM_REFERENCE_ORDER"),
        (RTDSM, {"vintage_units": ()}, "RTDSM_EXACT_VINTAGE_UNITS"),
        (RTDSM, {"year_window_start": True}, "RTDSM_PROFILE_OR_YEAR_WINDOW"),
        (RTDSM, {"year_window_start": 1900}, "RTDSM_VALUE_BEFORE"),
        (RTDSM, {"profile": "AUTO"}, "RTDSM_PROFILE"),
        (RTDSM.replace(b"DATE", b"date"), {}, "RTDSM_DATE_HEADER"),
        (
            RTDSM,
            {"start": date(2020, 1, 1), "end": date(2020, 2, 1)},
            "RTDSM_SELECTED_RANGE_EMPTY",
        ),
    ],
)
def test_rtdsm_hostile_metadata_and_releases(
    raw: bytes, change: dict[str, object], code: str
) -> None:
    with pytest.raises(SourceError, match=code):
        RTDSMImporter().import_bytes(raw, changed(RTDSM_QUERY, change), NOW)


def test_philadelphia_target_oracle_prior_value_is_not_forecast() -> None:
    batch = SurveyFileImporter().import_bytes(PHILLY, PHILLY_QUERY, NOW)
    assert [r.target_period for r in batch.records] == [
        "2023Q4",
        "2024Q1",
        "2024Q2",
        "2024Q3",
        "2024Q4",
        "2025Q1",
    ]
    assert batch.records[0].statistic == "HISTORICAL_VALUE_REPORTED"
    assert all(r.statistic == "MEDIAN" for r in batch.records[1:])
    assert all(
        not r.event_consensus_eligible and not r.point_in_time_eligible
        for r in batch.records
    )
    assert batch.records[-1].value == Decimal("4.2")


@pytest.mark.parametrize(
    "raw,change,code",
    [
        (PHILLY, {"statistic": "EVENT_CONSENSUS"}, "PHILADELPHIA_SERIES_OR_STATISTIC"),
        (PHILLY, {"variable": "CPI"}, "PHILADELPHIA_SERIES_OR_STATISTIC"),
        (PHILLY, {"unit": "RATE"}, "PHILADELPHIA_UNIT"),
        (PHILLY.replace(b"2024,1", b"2027,1"), {}, "SURVEY_ROUND_ORDER"),
        (PHILLY.replace(b"3.7", b"101"), {}, "SURVEY_UNEMPLOYMENT_RANGE"),
        (PHILLY.replace(b"UNEMP6", b"ANNUAL"), {}, "PHILADELPHIA_QUARTERLY_HEADER"),
        (PHILLY, {"profile": "UNKNOWN"}, "SURVEY_PROFILE"),
        (
            PHILLY,
            {"start": date(2020, 1, 1), "end": date(2020, 2, 1)},
            "SURVEY_SELECTED_RANGE_EMPTY",
        ),
    ],
)
def test_survey_closed_profiles(
    raw: bytes, change: dict[str, object], code: str
) -> None:
    with pytest.raises(SourceError, match=code):
        SurveyFileImporter().import_bytes(raw, changed(PHILLY_QUERY, change), NOW)


def test_ecb_preserves_actual_point_forecaster_and_future_target_without_availability() -> (
    None
):
    batch = SurveyFileImporter().import_bytes(ECB, ECB_QUERY, NOW)
    assert [r.target_start for r in batch.records] == [
        date(2024, 1, 1),
        date(2025, 1, 1),
        date(2025, 2, 1),
    ]
    assert [r.forecaster_id for r in batch.records] == ["17", "17", "21"]
    assert all(
        r.statistic == "INDIVIDUAL_POINT"
        and r.publication_time is r.available_at is None
        for r in batch.records
    )
    assert batch.records[0].survey_round == "2024Q1"
    assert batch.raw_pages[0].raw == ECB


@pytest.mark.parametrize(
    "raw,change,code",
    [
        (ECB, {"statistic": "MEDIAN"}, "ECB_SPF_VARIABLE_OR_STATISTIC"),
        (ECB, {"survey_round": None}, "ECB_SPF_VARIABLE_OR_STATISTIC"),
        (ECB, {"unit": "FRACTION"}, "ECB_SPF_UNIT_OR_HEADER"),
        (ECB, {"survey_round": "2027Q1"}, "ECB_SPF_ROUND_RANGE"),
        (ECB.replace(b"2025Feb", b"2025FEB"), {}, "ECB_SPF_TARGET"),
        (ECB.replace(b"2025Feb", b"2045Feb"), {}, "ECB_SPF_TARGET_OR_DUPLICATE"),
        (ECB.replace(b"2025Jan,17", b"2024,17"), {}, "ECB_SPF_TARGET_OR_DUPLICATE"),
        (ECB.replace(b"2025Jan", b"2025Q1"), {}, "ECB_SPF_TARGET_GRANULARITY"),
        (ECB, {"variable": "RGDP"}, "ECB_SPF_TARGET_GRANULARITY"),
        (ECB.replace(b"2024,17", b"2024,0"), {}, "ECB_SPF_FORECASTER"),
    ],
)
def test_ecb_target_statistic_and_identity_guards(
    raw: bytes, change: dict[str, object], code: str
) -> None:
    with pytest.raises(SourceError, match=code):
        SurveyFileImporter().import_bytes(raw, changed(ECB_QUERY, change), NOW)


def test_forward_points_oracle_is_oriented_exact_and_independent_of_decimal_context() -> (
    None
):
    raw = forward_bytes()
    baseline = ForwardFileImporter().import_bytes(raw, FORWARD_QUERY, NOW).records[0]
    # Independent handwritten: 1.10 - 20/10000 = 1.098; 1.11 - 10/10000 = 1.109.
    assert baseline.outright_bid == Decimal("1.098")
    assert baseline.outright_ask == Decimal("1.109")
    with localcontext() as ctx:
        ctx.prec = 2
        ctx.traps[Inexact] = True
        assert (
            ForwardFileImporter().import_bytes(raw, FORWARD_QUERY, NOW).records[0]
            == baseline
        )
    assert baseline.instrument_kind == "FX_FORWARD" and baseline.available_at is None
    assert (
        not baseline.point_in_time_eligible and not baseline.executable_quote_verified
    )
    outright = {
        **forward_row(),
        "quote_kind": "OUTRIGHT",
        "forward_bid": "1.098",
        "forward_ask": "1.109",
        "point_scale": "",
    }
    direct = (
        ForwardFileImporter()
        .import_bytes(forward_bytes(outright), FORWARD_QUERY, NOW)
        .records[0]
    )
    assert (direct.outright_bid, direct.outright_ask) == (
        baseline.outright_bid,
        baseline.outright_ask,
    )


@pytest.mark.parametrize(
    "change,code",
    [
        (
            {"base_currency": "USD", "quote_currency": "EUR"},
            "FORWARD_DUPLICATE_OR_PAIR",
        ),
        ({"spot_bid": "1.12"}, "FORWARD_BID_ASK"),
        ({"forward_bid": "0"}, "FORWARD_BID_ASK"),
        ({"forward_bid": "-20000"}, "FORWARD_OUTRIGHT_BID_ASK"),
        ({"settlement_date": "2024-01-04"}, "FORWARD_SETTLEMENT"),
        ({"settlement_date": "2050-01-04"}, "FORWARD_SETTLEMENT"),
        ({"point_scale": "0.03"}, "FORWARD_POINT_SCALE"),
        ({"quote_kind": "SPOT"}, "FORWARD_QUOTE_KIND"),
        ({"quote_kind": "OUTRIGHT"}, "FORWARD_OUTRIGHT_SCALE_FORBIDDEN"),
        ({"quote_at": "2024-01-02T12:00:00"}, "ARCHIVE_UTC_TIMESTAMP"),
        ({"quote_at": "2026-01-02T12:00:00Z"}, "FORWARD_QUOTE_TIME"),
        (
            {"declared_available_at": "2024-01-02T11:59:59Z"},
            "FORWARD_DECLARED_AVAILABILITY",
        ),
        (
            {"declared_available_at": "2026-01-02T12:00:00Z"},
            "FORWARD_DECLARED_AVAILABILITY",
        ),
        ({"tenor": "SPOT"}, "FORWARD_TENOR"),
        ({"quote_id": "../secret"}, "FORWARD_QUOTE_ID"),
    ],
)
def test_forward_hostile_quote_semantics(change: dict[str, str], code: str) -> None:
    with pytest.raises(SourceError, match=code):
        ForwardFileImporter().import_bytes(
            forward_bytes({**forward_row(), **change}), FORWARD_QUERY, NOW
        )


def test_forward_declared_availability_retained_but_not_promoted_and_order_unique() -> (
    None
):
    row = {**forward_row(), "declared_available_at": "2024-01-02T12:00:01Z"}
    record = (
        ForwardFileImporter()
        .import_bytes(forward_bytes(row), FORWARD_QUERY, NOW)
        .records[0]
    )
    assert record.declared_available_at == datetime(2024, 1, 2, 12, 0, 1, tzinfo=UTC)
    assert record.available_at is None
    with pytest.raises(SourceError, match="FORWARD_DUPLICATE"):
        ForwardFileImporter().import_bytes(forward_bytes(row, row), FORWARD_QUERY, NOW)
    earlier = {**row, "quote_id": "second", "quote_at": "2024-01-02T11:00:00Z"}
    with pytest.raises(SourceError, match="FORWARD_QUOTE_TIME"):
        ForwardFileImporter().import_bytes(
            forward_bytes(row, earlier), FORWARD_QUERY, NOW
        )


@pytest.mark.parametrize(
    "raw,code",
    [
        (b"", "ARCHIVE_FILE_SIZE"),
        (b"a" * 2_000_001, "ARCHIVE_FILE_SIZE"),
        (b"\xff\n", "ARCHIVE_UTF8"),
        (b"a,b\n1,\x00\n", "ARCHIVE_CONTROL"),
        (b"a,b\n" + b"x" * 32769, "ARCHIVE_LINE"),
        (b"a,b\n" + b"x" * 129 + b",1", "ARCHIVE_FIELD"),
        (b'a,b\n"hello\nworld",1', "ARCHIVE_FIELD"),
        (b'a,b\n"unterminated', "ARCHIVE_CSV"),
        (b"a,b\n", "ARCHIVE_DATA"),
        (b"a,a\n1,2", "ARCHIVE_HEADER"),
        (b"a,b\n1,2,3", "ARCHIVE_HEADER"),
        (b"a, b\n1,2", "ARCHIVE_HEADER"),
        (b"a,b\n\n", "ARCHIVE_TABLE"),
        (b"a,b\n" + b"1,2\n" * 5001, "ARCHIVE_TABLE"),
        ((b"x," * 128) + b"x\n1,2", "ARCHIVE_TABLE"),
        (b"a,b\n" + (b"1," * 127 + b"1\n") * 790, "ARCHIVE_CELL"),
    ],
    ids=[
        "empty",
        "raw_size",
        "utf8",
        "control",
        "line",
        "field",
        "multiline",
        "quote",
        "no_rows",
        "duplicate",
        "width",
        "header_spaces",
        "empty_row",
        "row_bound",
        "column_bound",
        "cell_bound",
    ],
)
def test_hostile_plaintext_allocation_bounds(raw: bytes, code: str) -> None:
    with pytest.raises(SourceError, match=code):
        f.csv_table(raw)


@pytest.mark.parametrize(
    "value",
    [
        "UNKNOWN",
        "../file",
        "C:/secret",
        "token:abc",
        "https://example.test",
        "\x00",
        " trailing ",
    ],
)
def test_metadata_refuses_ambiguous_or_secret_shaped_text(value: str) -> None:
    with pytest.raises(SourceError, match="ARCHIVE_METADATA"):
        f.metadata_text(value)


def profile_case(name: str) -> tuple[str, bytes, JsonRecord]:
    common: JsonRecord = {
        "declared_license": "Synthetic bytes - no provider rights claimed",
        "license_confirmed": True,
        "start": "2023-01-01",
        "end": "2024-12-31",
        "export_vintage": "2025-02-01",
    }
    if name == "CES":
        return (
            "SRC-04",
            CES,
            {**common, "profile": CES_QUERY.profile, "series_id": CES_QUERY.series_id},
        )
    if name == "RTDSM":
        return (
            "SRC-22",
            RTDSM,
            {
                **common,
                "profile": RTDSM_QUERY.profile,
                "series_id": "ROUTPUT",
                "vintage_units": dict(RTDSM_QUERY.vintage_units),
                "year_window_start": 1965,
            },
        )
    if name in {"PHILLY", "ECB"}:
        query = PHILLY_QUERY if name == "PHILLY" else ECB_QUERY
        return (
            "SRC-22",
            PHILLY if name == "PHILLY" else ECB,
            {
                **common,
                "profile": query.profile,
                "variable": query.variable,
                "unit": query.unit,
                "statistic": query.statistic,
                "survey_round": query.survey_round,
            },
        )
    return (
        "SRC-21",
        forward_bytes(),
        {
            **common,
            "profile": FORWARD_QUERY.profile,
            "base_currency": "EUR",
            "quote_currency": "USD",
            "source_label": "Synthetic fixture",
        },
    )


@pytest.mark.parametrize("name", ["CES", "RTDSM", "PHILLY", "ECB", "FORWARD"])
def test_actual_canonical_capture_has_exact_raw_candidate_and_no_approval(
    tmp_path: Path, name: str
) -> None:
    materializer, lab = setup(tmp_path)
    service = ProviderService(materializer.public)
    source, raw, metadata = profile_case(name)
    result = service.import_file(source, raw, metadata)
    assert result["status"] == "SUCCEEDED", result
    assert result["source_status"] == "CANDIDATE" and result["quality"] == "PENDING"
    assert result["evidence_mode"] == "OWNER_SUPPLIED"
    assert lab.objects.get(str(result["raw_digest"])).path.read_bytes() == raw
    summary = cast(
        JsonRecord,
        parse_json_document(
            lab.objects.get(str(result["diagnostic_summary_digest"])).path.read_bytes()
        ),
    )
    assert summary["normalization_version"] == metadata["profile"]
    preview = cast(list[JsonRecord], result["preview"])
    assert all(
        not r["point_in_time_eligible"] and r["available_at"] is None for r in preview
    )
    registry = lab.registry.verify_all()
    assert len(registry) == 2 and any(k.startswith("DATASET-") for k in registry)
    if name == "FORWARD":
        cost = cast(JsonRecord, registry[str(result["source_id"])][-1].record["cost"])
        assert cost["class"] == "INSTITUTIONAL" and cost["monthly_cost"] == "UNKNOWN"


def test_reimport_creates_new_identity_preserves_exact_old_bytes_and_failure(
    tmp_path: Path,
) -> None:
    materializer, lab = setup(tmp_path)
    service = ProviderService(materializer.public)
    source, raw, metadata = profile_case("CES")
    first = service.import_file(source, raw, metadata)
    second = service.import_file(source, raw.replace(b"99,103", b"999,103"), metadata)
    assert (
        first["source_id"] != second["source_id"]
        and first["raw_digest"] != second["raw_digest"]
    )
    assert lab.objects.get(str(first["raw_digest"])).path.read_bytes() == raw
    failed = service.import_file(source, raw.replace(b"100", b"=secret()"), metadata)
    assert failed["status"] == "FAILED" and failed["quality"] == "QUARANTINED"
    assert failed["raw_retained"] is False and failed["error_code"] == "INVALID_NUMBER"
    retained = lab.objects.get(str(failed["capture_digest"])).path.read_bytes()
    assert b"=secret()" not in retained
    assert (
        lab.registry.verify_object(str(failed["source_id"]))[-1].record["status"]
        == "CANDIDATE"
    )


@pytest.mark.parametrize(
    "case", ["extra", "rights", "supplement", "future", "unknown_profile"]
)
def test_workflow_closed_metadata_refuses_or_retains_sanitized_failure(
    tmp_path: Path, case: str
) -> None:
    materializer, _ = setup(tmp_path)
    source, raw, metadata = profile_case("CES")
    if case == "extra":
        metadata["url"] = "https://example.test"
    elif case == "rights":
        metadata["license_confirmed"] = False
    elif case == "future":
        metadata["export_vintage"] = "2099-01-01"
    elif case == "unknown_profile":
        metadata["profile"] = "GUESS"
    service = ProviderService(materializer.public)
    if case == "unknown_profile":
        assert (
            service.import_file(source, raw, metadata)["error_code"]
            == "CES_PROFILE_UNSUPPORTED"
        )
    else:
        with pytest.raises(SourceError):
            service.import_file(
                source,
                raw,
                metadata,
                series_metadata=b"not allowed" if case == "supplement" else None,
            )


def test_timezone_context_and_basic_date_fail_closed() -> None:
    with pytest.raises(SourceError, match="UTC_RETRIEVAL_REQUIRED"):
        CESArchiveImporter().import_bytes(CES, CES_QUERY, NOW.replace(tzinfo=None))
    for encoded in ("2024-02-30", "0001-01-01", "2024-1-01"):
        with pytest.raises(SourceError, match="ARCHIVE_DATE"):
            f.day(encoded)
    with pytest.raises(SourceError, match="ARCHIVE_UTC_TIMESTAMP"):
        f.timestamp("2024-01-02T99:00:00Z")
    assert f.timestamp("2024-01-02T12:00:00.123Z").microsecond == 123000
    assert NOW.utcoffset() == timedelta(0)


def test_matrix_expansion_and_forecast_output_limits_precede_unbounded_growth(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    periods = [f"{2000 + i // 12:04d}-{i % 12 + 1:02d}" for i in range(100)]
    releases = [f"{2010 + i // 12:04d}-{i % 12 + 1:02d}" for i in range(51)]
    raw = (
        "vintage_reference_month,"
        + ",".join(periods)
        + "\n"
        + "\n".join(release + "," + ",".join(["1"] * 100) for release in releases)
    ).encode()
    query = changed(CES_QUERY, {"start": date(2000, 1, 1), "end": date(2008, 12, 31)})
    with pytest.raises(SourceError, match="CES_NORMALIZED_ROW_BOUND"):
        CESArchiveImporter().import_bytes(raw, query, NOW)
    headers = [f"ROUTPUT{2000 + i // 12:04d}M{i % 12 + 1}" for i in range(100)]
    periods_q = [f"{1970 + i // 4:04d}Q{i % 4 + 1}" for i in range(51)]
    rtdsm = (
        "DATE,"
        + ",".join(headers)
        + "\n"
        + "\n".join(period + "," + ",".join(["1"] * 100) for period in periods_q)
    ).encode()
    rquery = changed(
        RTDSM_QUERY,
        {
            "start": date(1970, 1, 1),
            "end": date(1990, 1, 1),
            "vintage_units": tuple((key, "USD") for key in headers),
        },
    )
    with pytest.raises(SourceError, match="RTDSM_NORMALIZED_ROW_BOUND"):
        RTDSMImporter().import_bytes(rtdsm, rquery, NOW)
    # One real-format survey row expands to six outputs. A lower configured
    # bound demonstrates the expanded-output check separately from CSV rows.
    monkeypatch.setattr(f, "MAX_ROWS", 5)
    with pytest.raises(SourceError, match="SURVEY_NORMALIZED_ROW_BOUND"):
        SurveyFileImporter().import_bytes(PHILLY, PHILLY_QUERY, NOW)


def test_more_forward_unit_profile_and_required_number_guards() -> None:
    with pytest.raises(SourceError, match="FORWARD_CURRENCY_UNSUPPORTED"):
        ForwardFileImporter().import_bytes(
            forward_bytes(), changed(FORWARD_QUERY, {"base_currency": "ZZZ"}), NOW
        )
    with pytest.raises(SourceError, match="FORWARD_PAIR_OR_PROFILE"):
        ForwardFileImporter().import_bytes(
            forward_bytes(), changed(FORWARD_QUERY, {"quote_currency": "EUR"}), NOW
        )
    with pytest.raises(SourceError, match="FORWARD_CLOSED_HEADER"):
        ForwardFileImporter().import_bytes(
            forward_bytes().replace(b"quote_id", b"id"), FORWARD_QUERY, NOW
        )
    with pytest.raises(SourceError, match="ARCHIVE_NUMBER_REQUIRED"):
        ForwardFileImporter().import_bytes(
            forward_bytes({**forward_row(), "spot_bid": "."}), FORWARD_QUERY, NOW
        )


def test_ecb_rgdp_quarter_target_is_accepted_and_unemployment_bound_is_real() -> None:
    raw = b"TARGET_PERIOD,FCT_SOURCE,POINT\n2025Q1,17,-0.5\n"
    batch = SurveyFileImporter().import_bytes(
        raw, changed(ECB_QUERY, {"variable": "RGDP"}), NOW
    )
    assert batch.records[0].target_start == date(2025, 1, 1)
    assert batch.records[0].value == Decimal("-0.5")
    with pytest.raises(SourceError, match="SURVEY_UNEMPLOYMENT_RANGE"):
        SurveyFileImporter().import_bytes(
            ECB.replace(b"2.1", b"101"),
            changed(ECB_QUERY, {"variable": "UNEM", "unit": "PERCENT_LABOUR_FORCE"}),
            NOW,
        )
