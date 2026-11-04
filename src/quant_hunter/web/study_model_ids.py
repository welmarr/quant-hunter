"""Permanent proposed model identities around existing numerical/Lab authorities.

This bridge does not fit during registration, count attempts, or change any
scientific status. Immutable producer/input/model receipts precede Item8 freeze.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import cast

from quant_hunter.config import (
    JsonRecord,
    JsonValue,
    canonicalize_json,
    parse_json_document,
)
from quant_hunter.identity import RegistryKind, new_typed_id
from quant_hunter.lab import LabService
from quant_hunter.lab.records import research_record
from quant_hunter.provenance.hashing import sha256_bytes
from quant_hunter.web.state import AccessError, AppState, Job, User

PROFILE = "qh-preregistered-model-identities-v1"
INPUT_FORMAT = (
    "SOFTWARE_MODEL_INPUT_MANIFEST; ACTUAL_INPUT_IN_REFERENCED_IMMUTABLE_OBJECT"
)
MAX_BYTES = 2_000_000
_OUTPUT_LIMITATION = "Recipe/FIT identities are proposed software objects; null output means no successful fit, never a fabricated parameter set"
_STUDY_FITS: dict[str, tuple[str, ...]] = {
    "CRP-01": (),
    "CRP-02": (),
    "CRP-03": (),
    "CRP-04": (),
    "CRP-05": ("cointegration_regression", "error_correction_regression"),
    "CRP-06": ("training_standardizer", "pca_projection"),
    "CRP-07": ("garch_forecaster",),
    "CRP-08": (),
    "CRP-09": ("surprise_scale",),
    "CRP-10": (),
    "ENS-COV": ("training_covariance", "constrained_allocator"),
    "META-OOF": ("training_standardizer", "ridge_metamodel"),
}
_FAMILY_NAME = "V0 proposed mathematical model definitions"


class ModelIdentityError(ValueError):
    """Stable sanitized binding failure; existing runtime retains actual attempts."""


def _record(value: object) -> JsonRecord:
    if not isinstance(value, dict):
        raise ModelIdentityError("MODEL_OBJECT_REQUIRED")
    return cast(JsonRecord, value)


def _stamp() -> str:
    return datetime.now(UTC).isoformat(timespec="microseconds").replace("+00:00", "Z")


class ModelIdentityBridge:
    """Shared schema adapter; RegistryStore alone allocates canonical identities."""

    def __init__(self, state: AppState, lab: LabService) -> None:
        self.state, self.lab = state, lab
        with state.connection() as db:
            db.execute(
                "CREATE TABLE IF NOT EXISTS model_identity_family (name TEXT PRIMARY KEY, family_id TEXT NOT NULL, record_digest TEXT NOT NULL)"
            )

    def _read(self, digest: str) -> JsonRecord:
        if self.lab.objects.get(digest).byte_size > MAX_BYTES:
            raise ModelIdentityError("MODEL_METADATA_LIMIT")
        return _record(parse_json_document(self.lab.objects.read_bytes(digest)))

    def _environment(self, digest: str) -> None:
        environment = self._read(digest)
        if "source_snapshot_digest" in environment:
            self.lab.objects.get(cast(str, environment["source_snapshot_digest"]))

    def _job(self, user: User, job: Job, *, unbound: bool) -> None:
        actual = self.state.job(user, job.id)
        with self.state.connection() as db:
            actor = db.execute(
                "SELECT role FROM users WHERE id=?", (user.id,)
            ).fetchone()
        if (
            actual != job
            or actual.status != "RUNNING"
            or (unbound and actual.experiment_id is not None)
            or actor is None
            or actor[0] not in {"owner", "researcher"}
        ):
            raise AccessError("Exact owned active research job required")

    def _definition(
        self,
        payload: JsonRecord,
        family_id: str,
        *,
        created: str,
        owner: str,
        family: bool = False,
    ) -> JsonRecord:
        method = _record(payload["method"])
        # Empty data arrays are deliberate for an actual immutable study input
        # that has not yet become Lab's DATASET; no placeholder IDs are published.
        definition = research_record(
            timestamp=created,
            family_id=family_id,
            source_id="",
            dataset_id="",
            code_revision=cast(str, payload["code_revision"]),
            name=_FAMILY_NAME
            if family
            else f"{payload['scope']} {payload['method_id']} {payload['kind']} {payload.get('fit_key', '')}".strip(),
            configuration_digest=cast(str, payload.get("configuration_digest", "")),
            family=family,
            method=method,
        )
        definition.update(
            object_type="RESEARCH_FAMILY" if family else "MODEL",
            owner=owner,
            parameters=canonicalize_json(payload).decode(),
            parent_ids=[]
            if payload["kind"] != "FIT"
            else [_record(payload["recipe"])["model_id"]],
            inputs=[
                "Exact immutable configuration and source payload digests in parameters",
                "Actual code/environment snapshot and training-only availability constraints",
            ],
            outputs=[
                "Registered recipe or one fixed fit's immutable parameters; no promotion authority"
            ],
            distinctiveness="Model identities do not create independent testing families; actual EXP grouping and attempts remain Item8 authority",
            limitations="PROPOSED synthetic software only. Preregistration is not a successful fit, empirical validation, or live execution permission.",
            failure_modes="Unused, failed and inconclusive preregistered IDs remain permanent; computation is never automatically replayed",
            implementation={
                "exists": True,
                "location": f"https://github.com/welmarr/quant-hunter/tree/{payload['code_revision']}/src/quant_hunter",
                "code_revision": payload["code_revision"],
            },
        )
        requirements = _record(definition["data_requirements"])
        requirements.update(
            dataset_ids=payload["dataset_ids"],
            source_ids=payload["source_ids"],
            point_in_time_constraints="Each learned fit uses its frozen eligible training support; later values cannot enter estimation",
            availability="Exact immutable source_digest is registered before evaluation; canonical Lab DATASET is created before actual computation",
        )
        if family:
            definition["parameter_search_accounting"] = {
                "complete_search_space": "Definition catalogue only; no statistical exposure counter here",
                "ai_generated_variants": "Actual exposure is the unchanged shared Item8 experiment family",
                "combination_count": 0,
            }
        return definition

    def _family(self) -> tuple[str, str]:
        with self.state.connection() as db:
            db.execute("BEGIN IMMEDIATE")
            row = db.execute(
                "SELECT family_id,record_digest FROM model_identity_family WHERE name=?",
                (_FAMILY_NAME,),
            ).fetchone()
            if row is not None:
                head = self.lab.registry.verify_object(str(row[0]))[-1]
                payload = _record(
                    parse_json_document(cast(str, head.record["parameters"]))
                )
                expected = self._definition(
                    payload,
                    str(row[0]),
                    created=cast(str, head.record["created_at"]),
                    owner="local-model-definition-catalogue",
                    family=True,
                )
                if (
                    head.digest != row[1]
                    or {
                        k: v
                        for k, v in head.record.items()
                        if k
                        not in {"object_id", "revision", "previous_revision_digest"}
                    }
                    != expected
                ):
                    raise ModelIdentityError("MODEL_FAMILY_BINDING")
                return str(row[0]), str(row[1])
            identity = new_typed_id(RegistryKind.FAMILY)
            payload = {
                "profile": PROFILE,
                "scope": "DEFINITION_LIBRARY",
                "method_id": "ALL_V0",
                "kind": "FAMILY",
                "code_revision": self.lab.code_revision,
                "environment_digest": self.lab.environment_digest,
                "dataset_ids": [],
                "source_ids": [],
                "method": {
                    "implemented_scope": "Permanent mathematical recipe and fit identities; no new exposure accounting or scientific authority",
                    "source_citations": [
                        "https://github.com/welmarr/quant-hunter/blob/main/docs/MODEL_REGISTRY.md"
                    ],
                    "assumptions": ["All actual trials remain governed by Item8"],
                    "cost_model": "No execution, trade or cost model is introduced",
                },
            }
            revision = self.lab.registry.create_initial(
                RegistryKind.FAMILY,
                identity,
                self._definition(
                    payload,
                    identity,
                    created=_stamp(),
                    owner="local-model-definition-catalogue",
                    family=True,
                ),
            )
            db.execute(
                "INSERT INTO model_identity_family VALUES(?,?,?)",
                (_FAMILY_NAME, identity, revision.digest),
            )
            return identity, revision.digest

    def register(
        self,
        user: User,
        job: Job,
        *,
        scope: str,
        method_id: str,
        configuration: JsonRecord,
        source: bytes,
        fit_keys: tuple[str, ...],
        dataset_ids: tuple[str, ...] = (),
        source_ids: tuple[str, ...] = (),
    ) -> JsonRecord:
        self._job(user, job, unbound=True)
        if (
            scope not in {"STUDY", "VALIDATION"}
            or not 0 <= len(fit_keys) <= 10
            or len(set(fit_keys)) != len(fit_keys)
        ):
            raise ModelIdentityError("MODEL_REGISTRATION_SCOPE")
        if not isinstance(source, bytes) or not 1 <= len(source) <= MAX_BYTES:
            raise ModelIdentityError("MODEL_SOURCE_LIMIT")
        config_raw = canonicalize_json(configuration)
        if len(config_raw) > MAX_BYTES:
            raise ModelIdentityError("MODEL_METADATA_LIMIT")
        self._environment(self.lab.environment_digest)
        for identity in (*dataset_ids, *source_ids):
            self.lab.registry.verify_object(identity)
        family_id, family_digest = self._family()
        payload: JsonRecord = {
            "profile": PROFILE,
            "scope": scope,
            "method_id": method_id,
            "job_id": job.id,
            "owner_id": user.id,
            "job_request": cast(JsonRecord, job.config),
            "configuration_digest": self.lab.objects.publish(config_raw).digest,
            "source_digest": self.lab.objects.publish(source).digest,
            "code_revision": self.lab.code_revision,
            "environment_digest": self.lab.environment_digest,
            "dataset_ids": list(dataset_ids),
            "source_ids": list(source_ids),
            "fit_keys": list(fit_keys),
            "method": configuration["software_method"],
        }

        def allocate(details: JsonRecord) -> JsonRecord:
            allocation = self.lab.registry.allocate(
                RegistryKind.MODEL,
                self._definition(
                    details, family_id, created=_stamp(), owner=f"local-user-{user.id}"
                ),
            )
            return {
                "model_id": allocation.object_id,
                "record_digest": allocation.revision.digest,
                "family_id": family_id,
                "family_record_digest": family_digest,
                "kind": details["kind"],
            }

        recipe = allocate({**payload, "kind": "RECIPE"})
        fits: list[JsonValue] = []
        for key in fit_keys:
            fits.append(
                {
                    "fit_key": key,
                    "binding": allocate(
                        {**payload, "kind": "FIT", "fit_key": key, "recipe": recipe}
                    ),
                }
            )
        return {**payload, "recipe": recipe, "fits": fits}

    def verify(
        self, user: User, registration: JsonRecord, *, current: bool = False
    ) -> tuple[JsonRecord, bytes]:
        required = {
            "profile",
            "scope",
            "method_id",
            "job_id",
            "owner_id",
            "job_request",
            "configuration_digest",
            "source_digest",
            "code_revision",
            "environment_digest",
            "dataset_ids",
            "source_ids",
            "fit_keys",
            "method",
            "recipe",
            "fits",
        }
        if (
            set(registration) != required
            or registration["profile"] != PROFILE
            or registration["owner_id"] != user.id
        ):
            raise ModelIdentityError("MODEL_REGISTRATION_BINDING")
        actual = self.state.job(user, cast(str, registration["job_id"]))
        if actual.config != registration["job_request"]:
            raise ModelIdentityError("MODEL_JOB_REQUEST_BINDING")
        if current and (
            registration["code_revision"] != self.lab.code_revision
            or registration["environment_digest"] != self.lab.environment_digest
        ):
            raise ModelIdentityError("MODEL_CURRENT_PRODUCER_MISMATCH")
        self._environment(cast(str, registration["environment_digest"]))
        config = self._read(cast(str, registration["configuration_digest"]))
        source_digest = cast(str, registration["source_digest"])
        if self.lab.objects.get(source_digest).byte_size > MAX_BYTES:
            raise ModelIdentityError("MODEL_SOURCE_LIMIT")
        source = self.lab.objects.read_bytes(source_digest)
        if config.get("software_method") != registration["method"]:
            raise ModelIdentityError("MODEL_METHOD_BINDING")
        base = {k: v for k, v in registration.items() if k not in {"recipe", "fits"}}
        recipe = _record(registration["recipe"])

        def verify_one(binding: JsonRecord, payload: JsonRecord) -> None:
            if (
                set(binding)
                != {
                    "model_id",
                    "record_digest",
                    "family_id",
                    "family_record_digest",
                    "kind",
                }
                or binding["kind"] != payload["kind"]
            ):
                raise ModelIdentityError("MODEL_RECORD_BINDING")
            head = self.lab.registry.verify_object(cast(str, binding["model_id"]))[-1]
            family = self.lab.registry.verify_object(cast(str, binding["family_id"]))[
                -1
            ]
            expected = self._definition(
                payload,
                cast(str, binding["family_id"]),
                created=cast(str, head.record["created_at"]),
                owner=f"local-user-{user.id}",
            )
            if (
                head.digest != binding["record_digest"]
                or family.digest != binding["family_record_digest"]
                or family.record.get("name") != _FAMILY_NAME
                or family.record.get("object_type") != "RESEARCH_FAMILY"
                or {
                    k: v
                    for k, v in head.record.items()
                    if k not in {"object_id", "revision", "previous_revision_digest"}
                }
                != expected
            ):
                raise ModelIdentityError("MODEL_RECORD_BINDING")

        verify_one(recipe, {**base, "kind": "RECIPE"})
        fits = registration["fits"]
        if (
            not isinstance(fits, list)
            or len(fits) > 10
            or [_record(row).get("fit_key") for row in fits] != registration["fit_keys"]
        ):
            raise ModelIdentityError("MODEL_FIT_PLAN_BINDING")
        ids = [recipe["model_id"]]
        for row in fits:
            fit = _record(row)
            if set(fit) != {"fit_key", "binding"}:
                raise ModelIdentityError("MODEL_FIT_PLAN_BINDING")
            binding = _record(fit["binding"])
            if (
                binding["family_id"] != recipe["family_id"]
                or binding["family_record_digest"] != recipe["family_record_digest"]
            ):
                raise ModelIdentityError("MODEL_FIT_PLAN_BINDING")
            ids.append(binding["model_id"])
            verify_one(
                binding,
                {**base, "kind": "FIT", "fit_key": fit["fit_key"], "recipe": recipe},
            )
        if len(set(cast(list[str], ids))) != len(ids):
            raise ModelIdentityError("MODEL_ID_REUSE")
        return config, source

    @staticmethod
    def bound(registration: JsonRecord, config: JsonRecord) -> tuple[JsonRecord, bytes]:
        return (
            {
                **config,
                "model_registration": registration,
                "input_format": INPUT_FORMAT,
            },
            canonicalize_json(
                {
                    "format": INPUT_FORMAT,
                    "actual_input_digest": registration["source_digest"],
                    "model_registration": registration,
                }
            ),
        )

    def artifact(
        self, registration: JsonRecord, experiment_id: str, outputs: JsonRecord
    ) -> JsonRecord:
        if set(outputs) != set(cast(list[str], registration["fit_keys"])):
            raise ModelIdentityError("MODEL_OUTPUT_PLAN_BINDING")
        payload: JsonRecord = {
            "profile": PROFILE,
            "kind": "FIT_OUTPUTS",
            "experiment_id": experiment_id,
            "registration": registration,
            "outputs": outputs,
            "limitations": _OUTPUT_LIMITATION,
        }
        raw = canonicalize_json(payload)
        if len(raw) > MAX_BYTES:
            raise ModelIdentityError("MODEL_OUTPUT_LIMIT")
        return {
            "registration": registration,
            "artifact_digest": self.lab.objects.publish(raw).digest,
        }

    def verify_artifact(
        self, user: User, artifact: JsonRecord, experiment_id: str, outputs: JsonRecord
    ) -> None:
        if set(artifact) != {"registration", "artifact_digest"}:
            raise ModelIdentityError("MODEL_OUTPUT_BINDING")
        registration = _record(artifact["registration"])
        self.verify(user, registration)
        retained = self._read(cast(str, artifact["artifact_digest"]))
        if set(outputs) != set(
            cast(list[str], registration["fit_keys"])
        ) or retained != {
            "profile": PROFILE,
            "kind": "FIT_OUTPUTS",
            "experiment_id": experiment_id,
            "registration": registration,
            "outputs": outputs,
            "limitations": _OUTPUT_LIMITATION,
        }:
            raise ModelIdentityError("MODEL_OUTPUT_BINDING")


class StudyModelIds(ModelIdentityBridge):
    """Runtime keeps Job/Lab failure authority; only actual numerical core runs here."""

    @staticmethod
    def _input(job: Job, config: JsonRecord, source: bytes) -> None:
        from quant_hunter.web.studies import prepare_job

        expected, expected_source, _ = prepare_job(job.config)
        if expected != config or expected_source != source:
            raise ModelIdentityError("STUDY_REQUEST_INPUT_BINDING")

    def register_study(
        self, user: User, job: Job, config: JsonRecord, source: bytes
    ) -> tuple[JsonRecord, bytes]:
        self._input(job, config, source)
        method = cast(str, config["study_id"])
        registration = self.register(
            user,
            job,
            scope="STUDY",
            method_id=method,
            configuration=config,
            source=source,
            fit_keys=_STUDY_FITS[method],
        )
        return self.bound(registration, config)

    @staticmethod
    def _outputs(result: JsonRecord) -> JsonRecord:
        method = cast(str, result["study_id"])
        model = result.get("fitted_model")
        if not _STUDY_FITS[method]:
            if model is not None:
                raise ModelIdentityError("UNREGISTERED_STUDY_FIT")
            return {}
        values = _record(model)
        fields: dict[str, dict[str, tuple[str, ...]]] = {
            "CRP-05": {
                "cointegration_regression": (
                    "train_end",
                    "intercept",
                    "hedge_ratio",
                    "residual_scale",
                    "statistic",
                    "pvalue",
                    "critical_values",
                    "level_adf_pvalues",
                    "difference_adf_pvalues",
                    "eligible",
                ),
                "error_correction_regression": ("train_end", "ecm_coefficients"),
            },
            "CRP-06": {
                "training_standardizer": ("train_end", "means", "scales"),
                "pca_projection": ("train_end", "loadings", "explained_variance"),
            },
            "ENS-COV": {
                "training_covariance": ("train_end", "covariance"),
                "constrained_allocator": ("train_end", "weights"),
            },
            "META-OOF": {
                "training_standardizer": ("train_end", "means", "scales"),
                "ridge_metamodel": ("train_end", "intercept", "coefficients"),
            },
        }
        if method in fields:
            return {
                key: {field: values[field] for field in names}
                for key, names in fields[method].items()
            }
        return {_STUDY_FITS[method][0]: values}

    def execute_study(
        self,
        user: User,
        job: Job,
        experiment_id: str,
        config: JsonRecord,
        payload: bytes,
    ) -> JsonRecord:
        self._job(user, job, unbound=False)
        if job.experiment_id != experiment_id:
            raise ModelIdentityError("STUDY_JOB_EXPERIMENT_BINDING")
        registration = _record(config.get("model_registration"))
        base, source = self.verify(user, registration, current=True)
        self._input(job, base, source)
        if (
            registration["scope"] != "STUDY"
            or registration["job_id"] != job.id
            or registration["method_id"] != base["study_id"]
            or registration["dataset_ids"] != []
            or registration["source_ids"] != []
            or registration["fit_keys"]
            != list(_STUDY_FITS[cast(str, base["study_id"])])
        ):
            raise ModelIdentityError("STUDY_MODEL_PLAN_BINDING")
        if self.bound(registration, base) != (config, payload):
            raise ModelIdentityError("STUDY_INPUT_MANIFEST_BINDING")
        run = self.lab.get_run(experiment_id)
        if (
            run["lifecycle_status"] != "RUNNING"
            or run["configuration"] != config
            or _record(run["bindings"])["dataset_digest"] != sha256_bytes(payload)
        ):
            raise ModelIdentityError("STUDY_ITEM8_BINDING")
        from quant_hunter.research_methods.studies import execute_study

        result = execute_study(source, base)
        if result.get("study_id") != base["study_id"]:
            raise ModelIdentityError("STUDY_RESULT_BINDING")
        result["canonical_models"] = self.artifact(
            registration, experiment_id, self._outputs(result)
        )
        result["actual_input_digest"] = registration["source_digest"]
        result["native_input_format"] = INPUT_FORMAT
        return result

    def inspect(self, user: User, job: Job) -> JsonRecord:
        actual = self.state.job(user, job.id)
        if actual != job or job.experiment_id is None:
            raise AccessError("Owned bound study job required")
        run = self.lab.get_run(job.experiment_id)
        config = _record(run["configuration"])
        registration = _record(config.get("model_registration"))
        base, _ = self.verify(user, registration)
        expected_config, payload = self.bound(registration, base)
        if (
            config != expected_config
            or registration["job_id"] != job.id
            or registration["scope"] != "STUDY"
            or registration["method_id"] != base["study_id"]
            or registration["dataset_ids"] != []
            or registration["source_ids"] != []
            or registration["fit_keys"]
            != list(_STUDY_FITS[cast(str, base["study_id"])])
            or _record(run["bindings"])["dataset_digest"] != sha256_bytes(payload)
        ):
            raise ModelIdentityError("STUDY_ITEM8_BINDING")
        if run["result"] is not None and run["evaluation_outcome"] != "FAILED":
            result = _record(run["result"])
            if (
                result.get("study_id") != base["study_id"]
                or result.get("actual_input_digest") != registration["source_digest"]
                or result.get("native_input_format") != INPUT_FORMAT
            ):
                raise ModelIdentityError("STUDY_RESULT_BINDING")
            artifact = _record(result.get("canonical_models"))
            if artifact.get("registration") != registration:
                raise ModelIdentityError("STUDY_RESULT_BINDING")
            self.verify_artifact(
                user, artifact, job.experiment_id, self._outputs(result)
            )
        return run
