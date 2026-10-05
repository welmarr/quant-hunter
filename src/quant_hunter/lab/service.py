"""Application facade; Item 8 is the sole scientific state authority.

The application runs one worker. Multiple instances in that process share a
registration lock. A RUNNING record with no attempt is an interrupted/in-flight
trial and must be recovered as failed, never silently rerun. The attempt outcome
is appended at completion because Item 8's immutable attempt includes its failed
flag. Ordinary exceptions and KeyboardInterrupt are accounted by ``run``; process
termination requires explicit ``recover_run`` after the worker has stopped.
"""

from __future__ import annotations

import re
import threading
from collections.abc import Callable, Mapping
from copy import deepcopy
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import cast
from uuid import uuid7

from quant_hunter.config import JsonRecord, JsonValue
from quant_hunter.config.canonical import canonicalize_json, parse_json_document
from quant_hunter.experiments import (
    EvaluationOutcome,
    ExperimentIntegrityError,
    ExperimentLifecycleService,
    ResultArtifactReference,
)
from quant_hunter.identity import RegistryKind, RegistryStore, Revision
from quant_hunter.lab.records import (
    FAMILY_NAME,
    LIMITATION,
    STUDY_FAMILY_NAME,
    experiment_record,
    require_record,
    research_record,
    source_record,
)
from quant_hunter.provenance import DataManifestReference
from quant_hunter.storage import ImmutableObjectStore
from quant_hunter.storage.security import (
    reject_credential_shaped_fields,
    reject_secret_text,
    reject_secret_text_values,
)

_REGISTRATION_LOCK = threading.RLock()
_MAX_BYTES = 2_000_000
_COMPLETED_PREFIX = "Synthetic completed result "
_FAILED_PREFIX = "Synthetic failed type "
_UTC_TIMESTAMP = re.compile(r"^\d{4}-\d\d-\d\dT\d\d:\d\d:\d\d(?:\.\d{1,6})?Z$")
type Computation = Callable[[bytes, JsonRecord], JsonRecord]


class LabValidationError(ValueError):
    """An application input violates the bounded synthetic demonstration contract."""


def _now() -> str:
    return datetime.now(UTC).isoformat(timespec="microseconds").replace("+00:00", "Z")


def _time(value: object) -> datetime:
    if not isinstance(value, str) or not _UTC_TIMESTAMP.fullmatch(value):
        raise LabValidationError(
            "Dataset bounds require UTC Z timestamps (at most 6 decimals)"
        )
    return datetime.fromisoformat(value)


def _stamp(value: datetime) -> str:
    return value.isoformat(timespec="microseconds").replace("+00:00", "Z")


def _safe_document(value: Mapping[str, JsonValue]) -> bytes:
    document = dict(value)
    reject_credential_shaped_fields(document)
    reject_secret_text_values(document, "synthetic application evidence")
    content = canonicalize_json(document)
    if len(content) > _MAX_BYTES:
        raise LabValidationError("Application JSON evidence exceeds 2 MB")
    return content


def _require_bindings(
    actual: Mapping[str, JsonValue], expected: Mapping[str, JsonValue], context: str
) -> None:
    """Reject semantically inconsistent objects even when each hashes correctly."""
    if any(
        key not in actual or actual[key] != value for key, value in expected.items()
    ):
        raise ExperimentIntegrityError(f"{context} disagrees with registered authority")


def _partitions(
    start: datetime, end: datetime, config: Mapping[str, JsonValue] | None = None
) -> JsonRecord:
    midpoint = start + (end - start) / 2
    explicit = {"training_start", "train_end", "training_end_exclusive"}
    if config is not None and (
        config.get("kind") == "CRP_STUDY" or explicit.intersection(config)
    ):
        if not explicit.issubset(config):
            raise LabValidationError("Explicit training bounds must be complete")
        training_start = _time(config["training_start"])
        train_end = _time(config["train_end"])
        midpoint = _time(config["training_end_exclusive"])
        if (
            training_start != start
            or not start <= train_end < midpoint < end
            or midpoint != train_end + timedelta(microseconds=1)
        ):
            raise LabValidationError(
                "Explicit training bounds disagree with dataset coverage"
            )
        if config.get("kind") == "CRP_STUDY":
            decision, target_start, target_end, available = (
                _time(config.get(key))
                for key in (
                    "decision_at",
                    "target_start",
                    "target_end",
                    "target_available_at",
                )
            )
            if not midpoint <= decision < target_start <= target_end <= available < end:
                raise LabValidationError(
                    "Study evaluation must follow its completed training partition"
                )
    return {
        "training": {"start": _stamp(start), "end": _stamp(midpoint)},
        "validation": {"start": _stamp(midpoint), "end": _stamp(end)},
        "sealed_out_of_sample": {
            "start": _stamp(end),
            "end": _stamp(end + timedelta(days=1)),
        },
    }


class LabService:
    """Persist and execute bounded synthetic runs through reviewed Item 8 APIs.

    ``config`` must contain actual half-open ``dataset_start``/``dataset_end``
    UTC bounds. The caller supplies project-generated fixture bytes only. This
    internal service accepts no paths, URLs, credentials, sealed-data handles,
    live mode, scientific conclusion, or result-dependent search callback.
    """

    def __init__(
        self,
        runtime_root: Path,
        schema_root: Path,
        code_revision: str,
        environment: Mapping[str, JsonValue],
    ) -> None:
        if re.fullmatch(r"[0-9a-f]{40}", code_revision) is None:
            raise LabValidationError(
                "Code revision must be an explicit 40-character Git SHA"
            )
        if not runtime_root.is_absolute():
            raise LabValidationError("Runtime root must be an absolute local path")
        self.code_revision = code_revision
        self.objects = ImmutableObjectStore(runtime_root / "artifacts")
        self.registry = RegistryStore.governed(runtime_root / "registries", schema_root)
        self.lifecycle = ExperimentLifecycleService(self.registry, self.objects)
        self.environment_digest = self.objects.publish(
            _safe_document(environment)
        ).digest

    def begin_run(
        self,
        config: Mapping[str, JsonValue],
        dataset: bytes,
        *,
        name: str = "Synthetic accounting demonstration",
    ) -> str:
        """Register all identities, freeze actual inputs, and enter Item 8 RUNNING.

        The caller must finalize with evaluate_run/fail_run. No computation occurs
        here; a restarted worker must fail abandoned RUNNING runs before retrying.
        """
        if not isinstance(dataset, bytes) or not dataset or len(dataset) > _MAX_BYTES:
            raise LabValidationError(
                "Synthetic fixture must contain 1 to 2,000,000 bytes"
            )
        if not isinstance(name, str) or not name.strip() or len(name) > 160:
            raise LabValidationError("Run name must contain 1 to 160 characters")
        reject_secret_text(name, "run name")
        frozen_config = deepcopy(dict(config))
        if frozen_config.get("evidence_mode", "SYNTHETIC") != "SYNTHETIC":
            raise LabValidationError("Only SYNTHETIC software runs are supported")
        for key in frozen_config:
            if any(
                word in key.lower()
                for word in ("sealed", "path", "url", "host_enforced")
            ):
                raise LabValidationError(
                    "Data access handles are forbidden in run configuration"
                )
        start = _time(frozen_config.get("dataset_start"))
        end = _time(frozen_config.get("dataset_end"))
        if end - start < timedelta(microseconds=2):
            raise LabValidationError(
                "Dataset end must follow start by at least two microseconds"
            )
        partitions = _partitions(start, end, frozen_config)
        method = None
        if "software_method" in frozen_config:
            method = require_record(frozen_config["software_method"], "Software method")
            if (
                set(method)
                != {
                    "implemented_scope",
                    "source_citations",
                    "assumptions",
                    "cost_model",
                }
                or any(
                    not isinstance(method[k], str)
                    or not 1 <= len(cast(str, method[k])) <= 2000
                    for k in ("implemented_scope", "cost_model")
                )
                or any(
                    not isinstance(method[k], list)
                    or not 1 <= len(cast(list[JsonValue], method[k])) <= 20
                    or any(
                        not isinstance(value, str) or not 1 <= len(value) <= 2000
                        for value in cast(list[JsonValue], method[k])
                    )
                    for k in ("source_citations", "assumptions")
                )
            ):
                raise LabValidationError("Invalid software method declaration")
        random_seed = frozen_config.get("random_seed", 0)
        if type(random_seed) is not int or not 0 <= random_seed <= 2**32 - 1:
            raise LabValidationError("Invalid declared random seed")
        family_name = STUDY_FAMILY_NAME if method is not None else FAMILY_NAME
        frozen_config["evidence_mode"] = "SYNTHETIC"
        configuration_bytes = _safe_document(frozen_config)
        with _REGISTRATION_LOCK:
            timestamp = _now()
            configuration = self.objects.publish(configuration_bytes)
            raw = self.objects.publish(dataset)
            source = self.registry.allocate(
                RegistryKind.SOURCE, source_record(timestamp, study=method is not None)
            )
            schema = self.objects.publish(
                canonicalize_json(
                    {
                        "format": "opaque project-generated synthetic fixture bytes",
                        "interpretation": "Frozen implementation and configuration",
                        "evidence_mode": "SYNTHETIC",
                    }
                )
            )
            lineage: JsonRecord = {
                "source_id": source.object_id,
                "source_record_digest": source.revision.digest,
                "physical_object_digest": raw.digest,
                "schema_digest": schema.digest,
                "retrieved_at": timestamp,
                "code_revision": self.code_revision,
                "environment_digest": self.environment_digest,
                "transformation": "None; exact synthetic fixture bytes retained",
                "evidence_mode": "SYNTHETIC",
            }
            lineage_object = self.objects.publish(canonicalize_json(lineage))
            dataset_record: JsonRecord = {
                "schema_version": "1.0.0",
                "created_at": timestamp,
                "layer": "raw_landing",
                "source_ids": [source.object_id],
                "coverage": {"start": _stamp(start), "end": _stamp(end)},
                "time_fields": {
                    "event_time": "NOT_APPLICABLE",
                    "publication_time": "NOT_APPLICABLE",
                    "ingestion_time": "NOT_APPLICABLE",
                    "revision_time": "NOT_APPLICABLE",
                },
                "schema_digest": schema.digest,
                "physical_object_digest": raw.digest,
                "provenance_lineage_digest": lineage_object.digest,
                "provenance": {
                    "parent_dataset_ids": [],
                    "transformation": "Opaque immutable fixture; bounds supplied by generator",
                    "code_revision": self.code_revision,
                    "environment_digest": self.environment_digest,
                },
                "quality_status": "PENDING",
            }
            registered_dataset = self.registry.allocate(
                RegistryKind.DATASET, dataset_record
            )
            family_id = self._family(
                timestamp,
                source.object_id,
                registered_dataset.object_id,
                configuration.digest,
                family_name=family_name,
                method=method,
            )
            strategy = self.registry.allocate(
                RegistryKind.STRATEGY,
                research_record(
                    timestamp=timestamp,
                    family_id=family_id,
                    source_id=source.object_id,
                    dataset_id=registered_dataset.object_id,
                    code_revision=self.code_revision,
                    name=name,
                    configuration_digest=configuration.digest,
                    family=False,
                    method=method,
                ),
            )
            manifest: JsonRecord = {
                "schema_version": "v0-lab-inputs-1",
                "evidence_mode": "SYNTHETIC",
                "dataset_id": registered_dataset.object_id,
                "dataset_record_digest": registered_dataset.revision.digest,
                "source_id": source.object_id,
                "source_record_digest": source.revision.digest,
                "dataset_digest": raw.digest,
                "lineage_digest": lineage_object.digest,
                "schema_digest": schema.digest,
                "configuration_digest": configuration.digest,
                "environment_digest": self.environment_digest,
                "code_revision": self.code_revision,
                "strategy_id": strategy.object_id,
                "strategy_record_digest": strategy.revision.digest,
                "family_id": family_id,
                "partitions": partitions,
                "limitations": LIMITATION,
            }
            manifest_object = self.objects.publish(canonicalize_json(manifest))
            payload = experiment_record(
                family_id=family_id,
                strategy_id=strategy.object_id,
                source_id=source.object_id,
                dataset_id=registered_dataset.object_id,
                dataset_record_digest=registered_dataset.revision.digest,
                manifest_digest=manifest_object.digest,
                configuration_digest=configuration.digest,
                environment_digest=self.environment_digest,
                code_revision=self.code_revision,
                partitions=partitions,
                name=name,
                method=method,
                random_seed=random_seed,
            )
            draft = self.lifecycle.create_draft(payload, created_at=timestamp)
            registered = self.lifecycle.register(
                draft.object_id, draft.revision.digest, registered_at=_now()
            )
            frozen = self.lifecycle.freeze(
                draft.object_id,
                registered.digest,
                frozen_at=_now(),
                data_manifests=[
                    DataManifestReference(
                        f"artifact:{manifest_object.digest}", manifest_object.digest
                    )
                ],
            )
            self.lifecycle.start(
                draft.object_id, frozen.revision.digest, started_at=_now()
            )
            return draft.object_id

    def _family(
        self,
        timestamp: str,
        source_id: str,
        dataset_id: str,
        config_digest: str,
        *,
        family_name: str = FAMILY_NAME,
        method: JsonRecord | None = None,
    ) -> str:
        matching = [
            object_id
            for object_id, revisions in self.registry.verify_all().items()
            if object_id.startswith("FAM-")
            and revisions[-1].record.get("name") == family_name
        ]
        if len(matching) > 1:
            raise ExperimentIntegrityError(
                "Multiple synthetic evidence families require review"
            )
        if matching:
            return matching[0]
        family_uuid = uuid7()
        family_id = f"FAM-{family_uuid}"
        allocation = self.registry.allocate(
            RegistryKind.FAMILY,
            research_record(
                timestamp=timestamp,
                family_id=family_id,
                source_id=source_id,
                dataset_id=dataset_id,
                code_revision=self.code_revision,
                name=family_name,
                configuration_digest=config_digest,
                family=True,
                method=method,
            ),
            uuid_factory=lambda: family_uuid,
        )
        return allocation.object_id

    def _head(self, experiment_id: str) -> Revision:
        if not experiment_id.startswith("EXP-"):
            raise LabValidationError("A permanent experiment ID is required")
        head = self.registry.verify_object(experiment_id)[-1]
        if head.record["lifecycle_status"] not in {"DRAFT", "REGISTERED"}:
            self.lifecycle.resolve_rerun(experiment_id).verify()
        return head

    def _inputs(self, head: Revision) -> tuple[JsonRecord, JsonRecord, bytes]:
        digests = cast(list[str], head.record["provenance_artifact_digests"])
        if len(digests) != 1:
            raise ExperimentIntegrityError(
                "Synthetic run must bind exactly one input manifest"
            )
        manifest = self._read_document(digests[0])
        for key in ("configuration_digest", "environment_digest", "code_revision"):
            if manifest.get(key) != head.record.get(key):
                raise ExperimentIntegrityError(
                    "Input manifest disagrees with frozen authority"
                )
        if manifest.get("evidence_mode") != "SYNTHETIC":
            raise ExperimentIntegrityError("Input manifest is not synthetic")
        if manifest.get("schema_version") != "v0-lab-inputs-1":
            raise ExperimentIntegrityError("Input manifest version is unsupported")
        _require_bindings(
            head.record,
            {
                "dataset_ids": [manifest["dataset_id"]],
                "source_registry_ids": [manifest["source_id"]],
                "referenced_object_ids": [manifest["strategy_id"]],
                "research_family_id": manifest["family_id"],
                "partitions": manifest["partitions"],
                "dataset_vintages": [
                    {
                        "dataset_id": manifest["dataset_id"],
                        "record_digest": manifest["dataset_record_digest"],
                        "vintage": digests[0],
                    }
                ],
            },
            "Input manifest",
        )
        _require_bindings(
            require_record(head.record["multiple_testing"], "Search plan"),
            {"family_id": manifest["family_id"]},
            "Evidence family",
        )
        dataset_id = cast(str, manifest["dataset_id"])
        dataset_revision = self.registry.verify_object(dataset_id)[0]
        if dataset_revision.digest != manifest["dataset_record_digest"]:
            raise ExperimentIntegrityError(
                "Dataset record identity differs from manifest"
            )
        if (
            dataset_revision.record["physical_object_digest"]
            != manifest["dataset_digest"]
        ):
            raise ExperimentIntegrityError(
                "Dataset bytes differ from registered identity"
            )
        config = self._read_document(cast(str, manifest["configuration_digest"]))
        _require_bindings(
            head.record,
            {"random_seed": config.get("random_seed", 0)},
            "Declared random seed",
        )
        start = _time(config.get("dataset_start"))
        end = _time(config.get("dataset_end"))
        if end - start < timedelta(microseconds=2):
            raise ExperimentIntegrityError("Retained dataset interval is malformed")
        _require_bindings(
            manifest, {"partitions": _partitions(start, end, config)}, "Temporal plan"
        )
        _require_bindings(
            dataset_revision.record,
            {
                "layer": "raw_landing",
                "source_ids": [manifest["source_id"]],
                "schema_digest": manifest["schema_digest"],
                "provenance_lineage_digest": manifest["lineage_digest"],
                "coverage": {"start": _stamp(start), "end": _stamp(end)},
            },
            "Dataset provenance",
        )
        _require_bindings(
            require_record(dataset_revision.record["provenance"], "Dataset provenance"),
            {
                "code_revision": manifest["code_revision"],
                "environment_digest": manifest["environment_digest"],
                "parent_dataset_ids": [],
            },
            "Dataset implementation",
        )
        for id_key, digest_key in (
            ("source_id", "source_record_digest"),
            ("strategy_id", "strategy_record_digest"),
        ):
            if (
                self.registry.verify_object(cast(str, manifest[id_key]))[0].digest
                != manifest[digest_key]
            ):
                raise ExperimentIntegrityError(
                    "Input registry identity differs from manifest"
                )
        strategy = self.registry.verify_object(cast(str, manifest["strategy_id"]))[
            0
        ].record
        if "software_method" in config:
            method = require_record(config["software_method"], "Software method")
            _require_bindings(
                strategy,
                {
                    "mathematical_definition": method["implemented_scope"],
                    "source_citations": method["source_citations"],
                    "assumptions": method["assumptions"],
                    "transaction_cost_sensitivity": method["cost_model"],
                },
                "Declared strategy method",
            )
            _require_bindings(
                head.record,
                {
                    "feature_definitions": method["implemented_scope"],
                    "label_definitions": "Typed target with distinct start, end and actual availability in frozen bytes; unused diagnostic targets are explicit",
                    "execution_cost_assumptions": [method["cost_model"]],
                    "evaluation_metrics": [
                        "Actual method signals, fitted parameters and numerical metrics specified by frozen implementation"
                    ],
                    "baselines": [
                        "Declared null and sensitivity scenarios are separate experiments; no empirical superiority claim"
                    ],
                },
                "Declared experiment method",
            )
        _require_bindings(
            strategy,
            {
                "object_type": "STRATEGY",
                "research_family_id": manifest["family_id"],
                "parameters": manifest["configuration_digest"],
            },
            "Strategy",
        )
        _require_bindings(
            require_record(strategy["data_requirements"], "Strategy inputs"),
            {
                "source_ids": [manifest["source_id"]],
                "dataset_ids": [manifest["dataset_id"]],
            },
            "Strategy inputs",
        )
        _require_bindings(
            require_record(strategy["implementation"], "Strategy implementation"),
            {
                "exists": True,
                "code_revision": manifest["code_revision"],
            },
            "Strategy implementation",
        )
        family = self.registry.verify_object(cast(str, manifest["family_id"]))[0].record
        _require_bindings(
            family,
            {
                "object_type": "RESEARCH_FAMILY",
                "research_family_id": manifest["family_id"],
            },
            "Research family",
        )
        lineage = self._read_document(cast(str, manifest["lineage_digest"]))
        _require_bindings(
            lineage,
            {
                "source_id": manifest["source_id"],
                "source_record_digest": manifest["source_record_digest"],
                "physical_object_digest": manifest["dataset_digest"],
                "schema_digest": manifest["schema_digest"],
                "code_revision": manifest["code_revision"],
                "environment_digest": manifest["environment_digest"],
                "evidence_mode": "SYNTHETIC",
            },
            "Lineage",
        )
        self.objects.get(cast(str, manifest["schema_digest"]))
        environment = self._read_document(cast(str, manifest["environment_digest"]))
        if "source_snapshot_digest" in environment:
            snapshot_digest = environment["source_snapshot_digest"]
            if not isinstance(snapshot_digest, str):
                raise ExperimentIntegrityError(
                    "Source snapshot identity must be a digest"
                )
            self.objects.get(snapshot_digest)
        dataset = self.objects.get(
            cast(str, manifest["dataset_digest"])
        ).path.read_bytes()
        return manifest, config, dataset

    def _read_document(self, digest: str) -> JsonRecord:
        return require_record(
            parse_json_document(self.objects.get(digest).path.read_bytes()), "Artifact"
        )

    def evaluate_run(
        self, experiment_id: str, result: Mapping[str, JsonValue]
    ) -> JsonRecord:
        """Retain one simulation artifact; software output is always INCONCLUSIVE."""
        result_bytes = _safe_document(result)
        with _REGISTRATION_LOCK:
            head = self._head(experiment_id)
            self._inputs(head)
            if head.record["lifecycle_status"] != "RUNNING":
                raise LabValidationError(
                    "Only an unfinished RUNNING experiment may be evaluated"
                )
            if head.record["variants_attempted"] != 0:
                raise LabValidationError(
                    "Trial already accounted; interrupted finalization needs review"
                )
            artifact = self.objects.publish(result_bytes)
            self.lifecycle.record_attempt(
                experiment_id,
                head.digest,
                recorded_at=_now(),
                ai_generated=True,
                failed=False,
                exposure_reason=f"{_COMPLETED_PREFIX}{artifact.digest}",
                variant_configuration_digest=cast(
                    str, head.record["configuration_digest"]
                ),
            )
            return self._finish_attempt(experiment_id)

    def fail_run(
        self, experiment_id: str, exception_type: str = "InterruptedComputation"
    ) -> JsonRecord:
        """Permanently account for a failed or abandoned trial, without raw errors.

        Do not call on a live worker. No automatic computation retry occurs.
        Exception messages, paths, and potentially sensitive details are omitted.
        """
        error_name = (
            exception_type
            if re.fullmatch(r"[A-Za-z][A-Za-z0-9_]{0,79}", exception_type)
            else "ComputationFailure"
        )
        with _REGISTRATION_LOCK:
            head = self._head(experiment_id)
            self._inputs(head)
            if head.record["lifecycle_status"] != "RUNNING":
                raise LabValidationError(
                    "Only an unfinished RUNNING experiment may fail"
                )
            if head.record["variants_attempted"] != 0:
                raise LabValidationError(
                    "Trial already accounted; interrupted finalization needs review"
                )
            self.lifecycle.record_attempt(
                experiment_id,
                head.digest,
                recorded_at=_now(),
                ai_generated=True,
                failed=True,
                exposure_reason=f"{_FAILED_PREFIX}{error_name}",
                variant_configuration_digest=cast(
                    str, head.record["configuration_digest"]
                ),
            )
            return self._finish_attempt(experiment_id)

    def _finish_attempt(self, experiment_id: str) -> JsonRecord:
        """Finalize exact already-retained attempt evidence without a second trial."""
        head = self._head(experiment_id)
        self._inputs(head)
        if (
            head.record["lifecycle_status"] != "RUNNING"
            or head.record["variants_attempted"] != 1
        ):
            raise LabValidationError(
                "Finalization requires exactly one retained attempt"
            )
        attempts = cast(list[JsonRecord], head.record["attempt_records"])
        attempt = attempts[0]
        reason = cast(str, attempt["exposure_reason"])
        if attempt["failed"] is True and reason.startswith(_FAILED_PREFIX):
            error_name = reason.removeprefix(_FAILED_PREFIX)
            if re.fullmatch(r"[A-Za-z][A-Za-z0-9_]{0,79}", error_name) is None:
                raise ExperimentIntegrityError("Retained failure type is malformed")
            self.lifecycle.evaluate(
                experiment_id,
                head.digest,
                evaluated_at=_now(),
                outcome=EvaluationOutcome.FAILED,
                result_summary="Synthetic software trial failed; no scientific conclusion.",
                no_result_artifact_reason="No successfully completed simulation result",
                failure_modes=[error_name],
            )
        elif attempt["failed"] is False and reason.startswith(_COMPLETED_PREFIX):
            result_digest = reason.removeprefix(_COMPLETED_PREFIX)
            self._read_document(result_digest)
            self.lifecycle.evaluate(
                experiment_id,
                head.digest,
                evaluated_at=_now(),
                outcome=EvaluationOutcome.INCONCLUSIVE,
                result_summary=LIMITATION,
                result_artifacts=[
                    ResultArtifactReference(
                        digest=result_digest, location=f"artifact:{result_digest}"
                    )
                ],
            )
        else:
            raise ExperimentIntegrityError("Retained attempt requires explicit review")
        return self.get_run(experiment_id)

    def recover_run(self, experiment_id: str) -> JsonRecord:
        """Recover an abandoned run after its worker has stopped, without replay.

        A retained completed/failed attempt is finalized from its own exact
        evidence. A run interrupted before its outcome was retained is failed.
        Already evaluated runs are returned unchanged. Never call on live jobs.
        """
        with _REGISTRATION_LOCK:
            head = self._head(experiment_id)
            if head.record["lifecycle_status"] == "EVALUATED":
                return self.get_run(experiment_id)
            if head.record["lifecycle_status"] != "RUNNING":
                raise LabValidationError("Only abandoned RUNNING runs may be recovered")
            if head.record["variants_attempted"] == 0:
                return self.fail_run(experiment_id)
            return self._finish_attempt(experiment_id)

    def run(
        self,
        config: Mapping[str, JsonValue],
        dataset: bytes,
        compute: Computation,
        *,
        name: str = "Synthetic accounting demonstration",
    ) -> JsonRecord:
        """Execute exactly once after preregistration; preserve ordinary failures."""
        experiment_id = self.begin_run(config, dataset, name=name)
        head = self._head(experiment_id)
        _, frozen_config, frozen_dataset = self._inputs(head)
        try:
            result = compute(frozen_dataset, frozen_config)
            return self.evaluate_run(experiment_id, result)
        except (Exception, KeyboardInterrupt) as error:
            # Persistence/integrity errors are not swallowed or overwritten.
            current = self._head(experiment_id)
            if (
                current.record["lifecycle_status"] == "RUNNING"
                and current.record["variants_attempted"] == 0
            ):
                failure = self.fail_run(experiment_id, type(error).__name__)
                if isinstance(error, KeyboardInterrupt):
                    raise
                return failure
            raise

    def get_run(self, experiment_id: str) -> JsonRecord:
        """Project verified Item 8 authority and immutable result objects."""
        head = self._head(experiment_id)
        manifest, config, _ = self._inputs(head)
        result_digests = cast(list[str], head.record["result_artifact_digests"])
        return {
            "experiment_id": experiment_id,
            "revision_digest": head.digest,
            "name": head.record["hypothesis"],
            "lifecycle_status": head.record["lifecycle_status"],
            "evaluation_outcome": head.record.get("evaluation_outcome"),
            "decision": head.record.get("decision"),
            "evidence_mode": "SYNTHETIC",
            "host_enforced": False,
            "limitations": LIMITATION,
            "created_at": head.record["created_at"],
            "variants_attempted": head.record["variants_attempted"],
            "pending_trial": head.record["lifecycle_status"] == "RUNNING"
            and head.record["variants_attempted"] == 0,
            "variant_accounting": deepcopy(head.record["variant_accounting"]),
            "failure_modes": deepcopy(head.record["failure_modes"]),
            "configuration": config,
            "bindings": manifest,
            "result_digest": result_digests[0] if result_digests else None,
            "result": self._read_document(result_digests[0])
            if result_digests
            else None,
        }

    def list_runs(self) -> list[JsonRecord]:
        """Rebuild a listing directly from verified registry history."""
        runs = [
            self.get_run(object_id)
            for object_id in self.registry.verify_all()
            if object_id.startswith("EXP-")
        ]
        return sorted(runs, key=lambda run: cast(str, run["created_at"]), reverse=True)
