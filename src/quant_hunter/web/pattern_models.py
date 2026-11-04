"""Canonical proposed learned-model recipes and per-execution fit identities.

Operational aliases locate method families; the governed registry alone owns
research identities. A recipe is never a fitted artifact or scientific pass.
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
from quant_hunter.lab.service import LabService
from quant_hunter.patterns.contracts import PatternError
from quant_hunter.web.state import AccessError, AppState, Job, User

LEARNED = frozenset({"PAT-03", "PAT-04", "PAT-05", "PAT-06", "PAT-09"})
_METHODS = {
    "PAT-03": (
        "Bounded information-gain shapelet",
        "https://doi.org/10.1007/s10618-010-0179-5",
        "Training-only candidate shapelets scored by information gain; exact selected length and candidate cap.",
    ),
    "PAT-04": (
        "Empirical SAX vocabulary",
        "https://www.cs.ucr.edu/~eamonn/SAX.pdf",
        "Training quantile breakpoints, PAA words and transition frequencies; not Gaussian SAX calibration.",
    ),
    "PAT-05": (
        "Two-sided reset CUSUM",
        "https://www.itl.nist.gov/div898/handbook/pmc/section3/pmc323.htm",
        "Training mean/variance baseline; one-sided cumulative residual sums reset on threshold alarm.",
    ),
    "PAT-06": (
        "Diagonal Gaussian HMM",
        "https://www.cs.ubc.ca/~murphyk/Bayes/PreMIT/hmm.html",
        "Bounded training EM for diagonal Gaussian emissions; forward filtering only at inference.",
    ),
    "PAT-09": (
        "Alternate k-medoids with OOD rejection",
        "https://arxiv.org/abs/1810.05691",
        "Bounded alternate medoid assignment and update on training PAA representations; training rejection radii, not FasterPAM.",
    ),
}
_PROFILE = "qh-pattern-learned-model-v1"


def _record(value: JsonValue) -> JsonRecord:
    if not isinstance(value, dict):
        raise PatternError("PATTERN_MODEL_RECORD_REQUIRED")
    return value


class PatternModels:
    def __init__(self, state: AppState, lab: LabService) -> None:
        self.state, self.lab = state, lab
        with state.connection() as db:
            db.execute(
                "CREATE TABLE IF NOT EXISTS pattern_model_families (method TEXT PRIMARY KEY, family_id TEXT NOT NULL, record_digest TEXT NOT NULL)"
            )

    def _read(self, digest: str) -> JsonRecord:
        if self.lab.objects.get(digest).byte_size > 2_000_000:
            raise PatternError("PATTERN_MODEL_METADATA_LIMIT")
        return _record(parse_json_document(self.lab.objects.read_bytes(digest)))

    def _writer(self, user: User) -> None:
        with self.state.connection() as db:
            row = db.execute("SELECT role FROM users WHERE id=?", (user.id,)).fetchone()
        if (
            user.role not in {"owner", "researcher"}
            or row is None
            or row[0] not in {"owner", "researcher"}
        ):
            raise AccessError("Model writer unavailable")

    @staticmethod
    def _bounded(record: JsonRecord) -> JsonRecord:
        if len(canonicalize_json(record)) > 2_000_000:
            raise PatternError("PATTERN_MODEL_METADATA_LIMIT")
        return record

    def _definition(
        self,
        family: str,
        family_id: str,
        *,
        owner: str,
        payload: JsonRecord,
        datasets: list[JsonValue],
        sources: list[JsonValue],
        parents: list[JsonValue],
        is_family: bool = False,
    ) -> JsonRecord:
        name, citation, mathematics = _METHODS[family]
        pending: JsonRecord = {
            "status": "UNKNOWN",
            "reason": "No historical or sealed empirical validation exists; synthetic software only.",
        }
        return {
            "schema_version": "1.0.0",
            "created_at": datetime.now(UTC)
            .isoformat(timespec="microseconds")
            .replace("+00:00", "Z"),
            "object_type": "RESEARCH_FAMILY" if is_family else "MODEL",
            "status": "PROPOSED",
            "name": name + (" method family" if is_family else f" {payload['kind']}"),
            "hypothesis": "This bounded implementation obeys its frozen synthetic numerical and temporal contracts; no market prediction claim.",
            "rationale": "Separate permanent model definition, execution identity and immutable fitted payload.",
            "source_citations": [citation],
            "mathematical_definition": mathematics,
            "inputs": [
                "Closed available synthetic bars",
                "Frozen training cutoffs, feature identity, configuration and seed",
            ],
            "outputs": [
                "Bounded fitted parameters and diagnostic output, or retained failure/inconclusive reason"
            ],
            "horizon": "Exact horizon in immutable recipe configuration; not a profitability claim",
            "sampling_frequency": "Exact step_ns in immutable corpus receipt",
            "universe": "Owned SYNTHETIC software inputs only",
            "assumptions": [
                "Training data and labels available by cutoff",
                "No smoothing at inference",
                "One separately counted EXP per execution",
            ],
            "search_space": "Exact immutable recipe and disclosed inner-method training search; no winner selection across runs",
            "parent_ids": parents,
            "baseline_ids": [],
            "data_requirements": {
                "source_ids": sources,
                "dataset_ids": datasets,
                "point_in_time_constraints": "Training, label, candidate and outcome availability are independently frozen and checked",
                "availability": "Synthetic software timestamps only; no historical availability certification",
                "licensing": "Local declared synthetic input; upstream rights do not follow from this model record",
                "expected_cost": "USD 0 incremental external service cost",
            },
            "owner": owner,
            "academic_institutional_basis": mathematics,
            "evidence_quality": "Synthetic software only; no empirical validation",
            "independent_replication_evidence": pending,
            "fx_applicability": pending,
            "known_failures_or_decay": "Small samples, constant windows, OOD inputs and insufficient training may be rejected or inconclusive",
            "distinctiveness": "Parameter siblings/refits remain the same method family, not independent models or ensemble votes",
            "validation_plan": "Independent numerical and causal software oracles; empirical/holdout validation is missing",
            "transaction_cost_sensitivity": "Frozen basis-point outcome deduction; no execution or capacity inference",
            "capacity_sensitivity": pending,
            "risk_sensitivity": pending,
            "regime_sensitivity": pending,
            "decision": {
                "status": "PENDING",
                "reason": "Proposed software diagnostic; no automatic promotion",
            },
            "limitations": "No empirical validation, sealed holdout, calibrated market probability or trading authority. Recipe identity differs from fitted artifact identity.",
            "failure_modes": "Failed preparation/fit IDs and attempts are retained; no automatic recomputation",
            "parameters": canonicalize_json(payload).decode(),
            "research_family_id": family_id,
            "successor_ids": [],
            "experiment_ids": [],
            "parameter_search_accounting": {
                "complete_search_space": "Exact parameters and internal candidate cap frozen in recipe; observed fit exposure retained in EXP result",
                "ai_generated_variants": "Each execution is one AI-originated EXP variant; refits get new MOD IDs",
                "combination_count": 0 if is_family else 1,
            },
            "implementation": {
                "exists": True,
                "location": f"https://github.com/welmarr/quant-hunter/blob/{self.lab.code_revision}/src/quant_hunter/patterns/product.py",
                "code_revision": self.lab.code_revision,
            },
            "reproduction_outcome": {
                "status": "NOT_APPLICABLE",
                "reason": "Independent bounded implementation and synthetic software tests, not empirical paper reproduction",
            },
        }

    def _family(self, method: str) -> tuple[str, str]:
        # Serialize the operational alias, not a competing canonical registry.
        with self.state.connection() as db:
            db.execute("BEGIN IMMEDIATE")
            row = db.execute(
                "SELECT family_id,record_digest FROM pattern_model_families WHERE method=?",
                (method,),
            ).fetchone()
            if row is not None:
                head = self.lab.registry.verify_object(str(row[0]))[-1]
                if (
                    head.digest != row[1]
                    or head.record["object_type"] != "RESEARCH_FAMILY"
                    or head.record["parameters"]
                    != canonicalize_json(
                        {"profile": _PROFILE, "method": method, "kind": "FAMILY"}
                    ).decode()
                ):
                    raise PatternError("PATTERN_MODEL_FAMILY_BINDING")
                return str(row[0]), str(row[1])
            identity = new_typed_id(RegistryKind.FAMILY)
            definition = self._definition(
                method,
                identity,
                owner="local-pattern-method-catalogue",
                payload={"profile": _PROFILE, "method": method, "kind": "FAMILY"},
                datasets=[],
                sources=[],
                parents=[],
                is_family=True,
            )
            revision = self.lab.registry.create_initial(
                RegistryKind.FAMILY, identity, definition
            )
            db.execute(
                "INSERT INTO pattern_model_families VALUES(?,?,?)",
                (method, identity, revision.digest),
            )
            return identity, revision.digest

    @staticmethod
    def _payload(
        configuration: JsonRecord,
        corpus: JsonRecord,
        secondary: JsonValue,
        method_profile: JsonRecord,
    ) -> JsonRecord:
        return {
            "profile": _PROFILE,
            "kind": "RECIPE",
            "method": configuration["family"],
            "configuration": configuration,
            "corpus": corpus,
            "secondary_corpus": secondary,
            "method_profile": method_profile,
        }

    def recipe(
        self,
        user: User,
        configuration: JsonRecord,
        corpus: JsonRecord,
        secondary: JsonValue,
        *,
        method_profile: JsonRecord,
    ) -> JsonRecord | None:
        method = cast(str, configuration["family"])
        if method not in LEARNED:
            return None
        self._writer(user)
        with self.state.connection() as db:
            if not db.execute(
                "SELECT 1 FROM pattern_corpora WHERE dataset_id=? AND owner_id=?",
                (corpus["dataset_id"], user.id),
            ).fetchone():
                raise AccessError("Model corpus is not owned")
        family_id, family_digest = self._family(method)
        payload = self._payload(configuration, corpus, secondary, method_profile)
        datasets: list[JsonValue] = [corpus["dataset_id"]]
        datasets.extend(
            _record(parent)["dataset_id"]
            for parent in cast(list[JsonValue], corpus["parents"])
        )
        sources = cast(
            list[JsonValue],
            self.lab.registry.verify_object(cast(str, corpus["dataset_id"]))[-1].record[
                "source_ids"
            ],
        )
        record = self._definition(
            method,
            family_id,
            owner=f"local-user-{user.id}",
            payload=payload,
            datasets=datasets,
            sources=sources,
            parents=[],
        )
        allocated = self.lab.registry.allocate(
            RegistryKind.MODEL, self._bounded(record)
        )
        return {
            "model_id": allocated.object_id,
            "record_digest": allocated.revision.digest,
            "family_id": family_id,
            "family_record_digest": family_digest,
            "kind": "RECIPE",
        }

    def _verify(
        self,
        user: User,
        binding: JsonRecord,
        payload: JsonRecord,
        parent_ids: list[JsonValue],
        code_revision: str,
    ) -> JsonRecord:
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
            raise PatternError("PATTERN_MODEL_BINDING")
        head = self.lab.registry.verify_object(cast(str, binding["model_id"]))[-1]
        family = self.lab.registry.verify_object(cast(str, binding["family_id"]))[-1]
        record = head.record
        if record["owner"] != f"local-user-{user.id}":
            raise AccessError("Model is not owned")
        if (
            head.digest != binding["record_digest"]
            or record["object_type"] != "MODEL"
            or record["status"] != "PROPOSED"
            or record["research_family_id"] != binding["family_id"]
            or record["parent_ids"] != parent_ids
            or record["parameters"] != canonicalize_json(payload).decode()
            or _record(record["implementation"])["code_revision"] != code_revision
            or _record(record["implementation"])["location"]
            != f"https://github.com/welmarr/quant-hunter/blob/{code_revision}/src/quant_hunter/patterns/product.py"
            or family.digest != binding["family_record_digest"]
            or family.record["object_type"] != "RESEARCH_FAMILY"
            or family.record["parameters"]
            != canonicalize_json(
                {"profile": _PROFILE, "method": payload["method"], "kind": "FAMILY"}
            ).decode()
        ):
            raise PatternError("PATTERN_MODEL_BINDING")
        return record

    def verify_recipe(
        self,
        user: User,
        binding: JsonValue,
        configuration: JsonRecord,
        corpus: JsonRecord,
        secondary: JsonValue,
        *,
        code_revision: str,
        method_profile: JsonRecord,
    ) -> None:
        if configuration["family"] not in LEARNED:
            if binding is not None:
                raise PatternError("PATTERN_UNEXPECTED_LEARNED_MODEL")
            return
        record = self._verify(
            user,
            _record(binding),
            self._payload(configuration, corpus, secondary, method_profile),
            [],
            code_revision,
        )
        expected_datasets: list[JsonValue] = [
            corpus["dataset_id"],
            *(
                _record(parent)["dataset_id"]
                for parent in cast(list[JsonValue], corpus["parents"])
            ),
        ]
        sources = self.lab.registry.verify_object(cast(str, corpus["dataset_id"]))[
            -1
        ].record["source_ids"]
        requirements = _record(record["data_requirements"])
        if (
            requirements["dataset_ids"] != expected_datasets
            or requirements["source_ids"] != sources
        ):
            raise PatternError("PATTERN_MODEL_DATA_BINDING")

    def fit(self, user: User, prepared: JsonRecord, job: Job) -> JsonRecord | None:
        recipe = prepared["model_recipe"]
        if recipe is None:
            return None
        self._writer(user)
        current = self.state.job(user, job.id)
        if (
            current != job
            or job.status != "RUNNING"
            or job.owner_id != user.id
            or job.config
            != {"kind": "PATTERN_JOB", "prepared_id": prepared["prepared_id"]}
        ):
            raise AccessError("Model fit requires exact claimed job")
        code_revision = cast(
            str, self._read(cast(str, prepared["prepared_digest"]))["code_revision"]
        )
        self.verify_recipe(
            user,
            recipe,
            _record(prepared["configuration"]),
            _record(prepared["corpus"]),
            prepared["secondary_corpus"],
            code_revision=code_revision,
            method_profile={
                "expanded_method_parameters": prepared["expanded_method_parameters"],
                "method_input_schema": prepared["method_input_schema"],
            },
        )
        bound = _record(recipe)
        source = self.lab.registry.verify_object(cast(str, bound["model_id"]))[
            -1
        ].record
        payload: JsonRecord = {
            "profile": _PROFILE,
            "kind": "FIT",
            "method": _record(prepared["configuration"])["family"],
            "recipe": recipe,
            "prepared_id": prepared["prepared_id"],
            "prepared_digest": prepared["prepared_digest"],
            "job_id": job.id,
            "owner_id": user.id,
        }
        record = self._definition(
            cast(str, payload["method"]),
            cast(str, bound["family_id"]),
            owner=f"local-user-{user.id}",
            payload=payload,
            datasets=cast(
                list[JsonValue], _record(source["data_requirements"])["dataset_ids"]
            ),
            sources=cast(
                list[JsonValue], _record(source["data_requirements"])["source_ids"]
            ),
            parents=[bound["model_id"]],
        )
        allocated = self.lab.registry.allocate(
            RegistryKind.MODEL, self._bounded(record)
        )
        return {
            **bound,
            "model_id": allocated.object_id,
            "record_digest": allocated.revision.digest,
            "kind": "FIT",
        }

    def verify_fit(
        self, user: User, binding: JsonValue, prepared: JsonRecord, job_id: str
    ) -> None:
        recipe = prepared["model_recipe"]
        if recipe is None:
            if binding is not None:
                raise PatternError("PATTERN_UNEXPECTED_LEARNED_MODEL")
            return
        payload: JsonRecord = {
            "profile": _PROFILE,
            "kind": "FIT",
            "method": _record(prepared["configuration"])["family"],
            "recipe": recipe,
            "prepared_id": prepared["prepared_id"],
            "prepared_digest": prepared["prepared_digest"],
            "job_id": job_id,
            "owner_id": user.id,
        }
        record = self._verify(
            user,
            _record(binding),
            payload,
            [_record(recipe)["model_id"]],
            cast(
                str, self._read(cast(str, prepared["prepared_digest"]))["code_revision"]
            ),
        )
        source = self.lab.registry.verify_object(
            cast(str, _record(recipe)["model_id"])
        )[-1].record
        if record["data_requirements"] != source["data_requirements"]:
            raise PatternError("PATTERN_MODEL_DATA_BINDING")

    def artifact(self, fit: JsonValue, result: JsonRecord) -> JsonRecord | None:
        if fit is None:
            return None
        method = _record(result["method"])
        payload: JsonRecord = {
            "profile": _PROFILE,
            "kind": "FIT_ARTIFACT",
            "fit": fit,
            "canonical_binding": result["canonical_binding"],
            "status": method["status"],
            "trained_parameters": _record(method["output"])["model"]
            if method["status"] == "EXECUTED"
            else None,
            "method_exposure": _record(result["exposure"])["method_internal"],
        }
        raw = canonicalize_json(payload)
        if len(raw) > 2_000_000:
            raise PatternError("PATTERN_MODEL_METADATA_LIMIT")
        digest = self.lab.objects.publish(raw).digest
        return {
            "model_id": _record(fit)["model_id"],
            "artifact_digest": digest,
            "status": payload["status"],
        }

    def verify_artifact(
        self, fit: JsonValue, artifact: JsonValue, result: JsonRecord
    ) -> None:
        if fit is None:
            if artifact is not None:
                raise PatternError("PATTERN_UNEXPECTED_LEARNED_MODEL")
            return
        bound = _record(artifact)
        method = _record(result["method"])
        expected: JsonRecord = {
            "profile": _PROFILE,
            "kind": "FIT_ARTIFACT",
            "fit": fit,
            "canonical_binding": result["canonical_binding"],
            "status": method["status"],
            "trained_parameters": _record(method["output"])["model"]
            if method["status"] == "EXECUTED"
            else None,
            "method_exposure": _record(result["exposure"])["method_internal"],
        }
        if (
            set(bound) != {"model_id", "artifact_digest", "status"}
            or bound["model_id"] != _record(fit)["model_id"]
            or bound["status"] != expected["status"]
            or self._read(cast(str, bound["artifact_digest"])) != expected
        ):
            raise PatternError("PATTERN_MODEL_ARTIFACT_BINDING")
