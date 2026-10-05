"""Bounded study selection; numerical modules load only on an explicit action."""

from dataclasses import asdict
from decimal import Decimal, InvalidOperation
from typing import cast

from quant_hunter.config import JsonRecord, JsonValue


def catalogue() -> list[JsonRecord]:
    from quant_hunter.research_methods.studies import list_studies

    return [cast(JsonRecord, asdict(item)) for item in list_studies()]


def request_config(
    study_id: str, scenario: str, parameter: str | None = None
) -> dict[str, str | int]:
    definitions = {str(item["study_id"]): item for item in catalogue()}
    if study_id not in definitions or scenario not in (
        "POSITIVE",
        "NULL",
        "SENSITIVITY",
    ):
        raise ValueError("Unknown study or scenario")
    config: dict[str, str | int] = {
        "kind": "CRP_STUDY",
        "study_id": study_id,
        "scenario": scenario,
    }
    if parameter is not None:
        definition = definitions[study_id]
        try:
            number = Decimal(parameter)
        except InvalidOperation:
            raise ValueError("Invalid study parameter") from None
        if not number.is_finite() or not Decimal(
            str(definition["parameter_min"])
        ) <= number <= Decimal(str(definition["parameter_max"])):
            raise ValueError("Parameter outside declared study bounds")
        config["parameter"] = str(number)
    return config


def prepare_job(request: dict[str, str | int]) -> tuple[JsonRecord, bytes, str]:
    from quant_hunter.research_methods.studies import prepare_study

    allowed = {"kind", "study_id", "scenario", "parameter"}
    if set(request) - allowed or request.get("kind") != "CRP_STUDY":
        raise ValueError("Invalid study job")
    selected = request_config(
        str(request["study_id"]),
        str(request["scenario"]),
        str(request["parameter"]) if "parameter" in request else None,
    )
    config, dataset = prepare_study(
        str(selected["study_id"]),
        str(selected["scenario"]),
        float(str(selected["parameter"])) if "parameter" in selected else None,
    )
    definition = next(
        item for item in catalogue() if item["study_id"] == config["study_id"]
    )
    config["software_method"] = {
        "implemented_scope": definition["implemented_scope"],
        "source_citations": [
            definition["paper_url"] or "https://github.com/welmarr/quant-hunter"
        ],
        "assumptions": cast(
            list[JsonValue], list(cast(tuple[str, ...], definition["assumptions"]))
        ),
        "cost_model": definition["cost_model"],
    }
    return (
        config,
        dataset,
        f"Synthetic {config['study_id']} {config['scenario']} mathematical study",
    )
