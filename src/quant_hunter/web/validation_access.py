"""Owned queued validation work through the existing AppState and Item8 lifecycle."""

from __future__ import annotations

from dataclasses import asdict
from typing import Literal, cast

from quant_hunter.config import JsonRecord, canonicalize_json, parse_json_document
from quant_hunter.data_quality import SelectedSnapshot
from quant_hunter.lab import LabService
from quant_hunter.provenance.hashing import sha256_bytes
from quant_hunter.research_validation import (
    ResearchValidationError,
    ResearchValidationService,
)
from quant_hunter.validation import ValidationPlan
from quant_hunter.web.quality_access import QualityAccess
from quant_hunter.web.state import AccessError, AppState, Job, User
from quant_hunter.web.study_model_ids import ModelIdentityBridge
from quant_hunter.web.validation_jobs import (
    MAX_MANIFEST,
    MAX_REPORT,
    PROFILE,
    ValidationControls,
    execute,
    fit_outputs,
    fit_plan,
    prepare,
)

KIND = "CHRONOLOGICAL_VALIDATION"


def record(value: object) -> JsonRecord:
    if not isinstance(value, dict):
        raise ResearchValidationError("VALIDATION_OBJECT_REQUIRED")
    return cast(JsonRecord, value)


class ValidationAccess:
    """Private operational projection; no scientific state or attempt counter."""

    def __init__(
        self, state: AppState, lab: LabService, quality: QualityAccess
    ) -> None:
        if (
            quality.state is not state
            or lab.registry is not quality.service.registry
            or lab.objects is not quality.service.objects
        ):
            raise ValueError("Validation requires shared governed stores")
        self.state, self.lab, self.quality = state, lab, quality
        self.service = ResearchValidationService(lab.registry, lab.objects)
        self.models = ModelIdentityBridge(state, lab)

    def submit(
        self,
        user: User,
        dataset_id: str,
        *,
        record_digest: str,
        quality_report_digest: str,
        controls: ValidationControls,
    ) -> Job:
        # Only a private pointer check precedes admission; graph replay and all
        # Parquet decoding are inside the existing shared resource-operation slot.
        self.quality.owns(user, dataset_id)
        operation = self.quality.data._begin(user, "VALIDATION_PREPARE")
        try:
            snapshot, raw = self.quality.selected(
                user,
                dataset_id,
                record_digest=record_digest,
                quality_report_digest=quality_report_digest,
                purpose="RESEARCH_CAUSAL",
                operation_id=operation,
            )
            manifest, _ = prepare(snapshot, raw, controls)
            digest = self.lab.objects.publish(canonicalize_json(manifest)).digest
            job = self.state.enqueue(
                user, {"kind": KIND, "submission_manifest_digest": digest}
            )
            # The existing owned Job is the authoritative operational pointer.
            # A crash after enqueue leaves this exact queued definition visible;
            # the resource journal is interrupted, not automatically resubmitted.
            self.quality.data._finish(
                operation,
                result={"job_id": job.id, "submission_manifest_digest": digest},
            )
            return job
        except Exception:
            self.quality.data._finish(operation, error="VALIDATION_PREPARATION_FAILED")
            raise

    def _resolve(
        self, user: User, job: Job
    ) -> tuple[JsonRecord, SelectedSnapshot, bytes, ValidationControls, ValidationPlan]:
        if (
            set(job.config) != {"kind", "submission_manifest_digest"}
            or job.config["kind"] != KIND
            or not isinstance(job.config["submission_manifest_digest"], str)
        ):
            raise AccessError("Validation job is unavailable")
        digest = job.config["submission_manifest_digest"]
        if self.lab.objects.get(digest).byte_size > MAX_MANIFEST:
            raise ResearchValidationError("VALIDATION_MANIFEST_LIMIT")
        frozen = self.lab.objects.read_bytes(digest)
        manifest = record(parse_json_document(frozen))
        selected = record(manifest.get("selected_snapshot"))
        if any(
            not isinstance(selected.get(key), str)
            for key in ("dataset_id", "record_digest", "quality_report_digest")
        ):
            raise ResearchValidationError("VALIDATION_SELECTION_SHAPE")
        snapshot, raw = self.quality._selected(
            user,
            cast(str, selected["dataset_id"]),
            record_digest=cast(str, selected["record_digest"]),
            quality_report_digest=cast(str, selected["quality_report_digest"]),
            purpose="RESEARCH_CAUSAL",
        )
        controls = ValidationControls.from_record(
            record(record(manifest.get("configuration")).get("controls"))
        )
        expected, plan = prepare(snapshot, raw, controls)
        if canonicalize_json(expected) != frozen:
            raise ResearchValidationError("VALIDATION_MANIFEST_REPLAY_MISMATCH")
        return manifest, snapshot, raw, controls, plan

    def _user(self, owner_id: int) -> User:
        with self.state.connection() as db:
            row = db.execute(
                "SELECT id,username,role FROM users WHERE id=?", (owner_id,)
            ).fetchone()
        if row is None:
            raise AccessError("Validation owner is unavailable")
        return User(
            row["id"],
            row["username"],
            cast(Literal["owner", "researcher", "reader"], row["role"]),
        )

    def execute_job(self, job: Job) -> None:
        user = self._user(job.owner_id)
        actual = self.state.job(user, job.id)
        if (
            actual != job
            or actual.status != "RUNNING"
            or actual.experiment_id is not None
            or actual.config.get("kind") != KIND
        ):
            raise AccessError("Only the exact claimed validation job may execute")
        # Parent/child counts as one active resource. Admission also rejects a
        # competing child before graph replay or scientific registration.
        operation = self.quality.data._begin(
            user, "VALIDATION_EXECUTE", worker_job_id=job.id
        )
        experiment_id: str | None = None
        try:
            if user.role not in {"owner", "researcher"}:
                raise AccessError("Researcher role required")
            manifest, snapshot, raw, controls, plan = self._resolve(user, job)
            config = record(manifest["configuration"])
            source_ids = tuple(
                cast(
                    list[str],
                    self.lab.registry.verify_object(snapshot.dataset_id)[-1].record[
                        "source_ids"
                    ],
                )
            )
            registration = self.models.register(
                user,
                job,
                scope="VALIDATION",
                method_id=controls.model,
                configuration=config,
                source=canonicalize_json(manifest),
                fit_keys=fit_plan(controls),
                dataset_ids=(snapshot.dataset_id,),
                source_ids=source_ids,
            )
            bound_config, bound_input = self.models.bound(registration, config)
            experiment_id = self.lab.begin_run(
                bound_config,
                bound_input,
                name=f"Synthetic chronological {controls.model}",
            )
            self.state.bind(job.id, experiment_id)
            bound = self.state.job(user, job.id)
            if bound.status != "RUNNING" or bound.experiment_id != experiment_id:
                raise AccessError("Validation job was interrupted before binding")
            self.models.verify(user, registration, current=True)
            summary, report = execute(
                self.service, experiment_id, snapshot, raw, controls, plan
            )
            report["model_registration"] = registration
            summary["canonical_models"] = self.models.artifact(
                registration, experiment_id, fit_outputs(report, controls)
            )
            summary["submission_manifest_digest"] = job.config[
                "submission_manifest_digest"
            ]
            summary["report_digest"] = self.lab.objects.publish(
                canonicalize_json(report)
            ).digest
            summary["experiment_id"] = experiment_id
            self.lab.evaluate_run(experiment_id, summary)
            self.quality.data._finish(
                operation, result={"job_id": job.id, "experiment_id": experiment_id}
            )
            self.state.finish(job.id)
        except Exception as error:
            failure = "ValidationComputationFailed"
            if experiment_id is not None:
                current = self.lab.get_run(experiment_id)
                if (
                    current["lifecycle_status"] == "RUNNING"
                    and current["variants_attempted"] == 0
                ):
                    name = (
                        str(error)
                        if isinstance(error, ResearchValidationError)
                        else type(error).__name__
                    )
                    run = self.lab.fail_run(experiment_id, name)
                else:
                    run = self.lab.recover_run(experiment_id)
                if (
                    run["lifecycle_status"] == "EVALUATED"
                    and run["evaluation_outcome"] != "FAILED"
                ):
                    self.quality.data._finish(
                        operation,
                        result={"job_id": job.id, "experiment_id": experiment_id},
                    )
                    self.state.finish(job.id)
                    return
            self.quality.data._finish(operation, error=failure)
            self.state.finish(job.id, error=failure)
        # Process termination/BaseException is retained RUNNING. Existing root
        # Runtime.recover resolves bound and orphan Item8 attempts without replay.

    def get(
        self, user: User, job_id: str, *, include_report: bool = False
    ) -> JsonRecord:
        self.state.job(user, job_id)
        with self.quality.inspection(user):
            return self._get(user, job_id, include_report=include_report)

    def _get(self, user: User, job_id: str, *, include_report: bool) -> JsonRecord:
        job = self.state.job(user, job_id)
        manifest, snapshot, _, controls, _ = self._resolve(user, job)
        run = self.lab.get_run(job.experiment_id) if job.experiment_id else None
        report: JsonRecord | None = None
        if run is not None:
            registration = record(
                record(run["configuration"]).get("model_registration")
            )
            registered_config, registered_input = self.models.verify(user, registration)
            bound_config, bound_input = self.models.bound(
                registration, registered_config
            )
            if (
                registered_config != manifest["configuration"]
                or registered_input != canonicalize_json(manifest)
                or registration["job_id"] != job.id
                or registration["scope"] != "VALIDATION"
                or registration["method_id"] != controls.model
                or registration["fit_keys"] != list(fit_plan(controls))
                or registration["dataset_ids"] != [snapshot.dataset_id]
                or registration["source_ids"]
                != self.lab.registry.verify_object(snapshot.dataset_id)[-1].record[
                    "source_ids"
                ]
                or run["configuration"] != bound_config
                or record(run["bindings"])["dataset_digest"]
                != sha256_bytes(bound_input)
            ):
                raise ResearchValidationError("VALIDATION_RUN_BINDING")
            result = run["result"]
            if result is not None:
                result = record(result)
                if result.get("profile") != PROFILE:
                    # A retained Item8 failure report is projected by its own
                    # canonical failed outcome; it is not a successful study.
                    if run["evaluation_outcome"] != "FAILED":
                        raise ResearchValidationError("VALIDATION_RESULT_PROFILE")
                else:
                    if (
                        result.get("submission_manifest_digest")
                        != job.config["submission_manifest_digest"]
                        or result.get("experiment_id") != job.experiment_id
                        or result.get("selected_snapshot") != snapshot.to_record()
                        or result.get("controls") != controls.to_record()
                    ):
                        raise ResearchValidationError("VALIDATION_RESULT_BINDING")
                    digest = result.get("report_digest")
                    if (
                        not isinstance(digest, str)
                        or self.lab.objects.get(digest).byte_size > MAX_REPORT
                    ):
                        raise ResearchValidationError("VALIDATION_REPORT_LIMIT")
                    report = record(
                        parse_json_document(self.lab.objects.read_bytes(digest))
                    )
                    if (
                        report.get("experiment_id") != job.experiment_id
                        or report.get("selected_snapshot") != snapshot.to_record()
                        or report.get("controls") != controls.to_record()
                        or report.get("temporal_plan_digest") != manifest["plan_digest"]
                        or report.get("model_registration") != registration
                    ):
                        raise ResearchValidationError("VALIDATION_REPORT_BINDING")
                    artifact = record(result.get("canonical_models"))
                    if artifact.get("registration") != registration:
                        raise ResearchValidationError("VALIDATION_RESULT_BINDING")
                    self.models.verify_artifact(
                        user,
                        artifact,
                        cast(str, job.experiment_id),
                        fit_outputs(report, controls),
                    )
        inventory: JsonRecord | None = None
        if run is not None:
            family_id = cast(str, record(run["bindings"])["family_id"])
            actual_inventory = self.service.trial_inventory(family_id)
            inventory = {
                key: actual_inventory[key]
                for key in (
                    "family_id",
                    "authority",
                    "total_attempts",
                    "failed_attempts",
                    "ai_generated_attempts",
                    "empirical_status",
                )
            }
            inventory["scope"] = (
                "Canonical shared research family; counts include every user and failed/inconclusive attempt; private experiment details omitted"
            )
        return {
            "job": cast(JsonRecord, asdict(job)),
            "definition": manifest,
            "run": run,
            "report": report if include_report else None,
            "family_exposure": inventory,
        }

    def list(self, user: User) -> list[JsonRecord]:
        return [
            cast(JsonRecord, asdict(job))
            for job in self.state.jobs(user)
            if job.config.get("kind") == KIND
        ][:100]

    def cancel(self, user: User, job_id: str) -> None:
        job = self.state.job(user, job_id)
        if job.config.get("kind") != KIND:
            raise AccessError("Validation job is unavailable")
        self.state.cancel(user, job_id)
