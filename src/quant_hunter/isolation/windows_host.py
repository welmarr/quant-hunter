"""Windows host-boundary evidence and HOST_ENFORCED release authority.

The module is import-safe on every supported CI platform. Host inspection and
publication happen only through explicit method calls. The boundary protects
against accidental and research-identity access; administrators, SYSTEM, and a
compromised operating system remain outside the Stage 1 threat model.
"""

from __future__ import annotations

import ctypes
import os
import re
import shutil
import subprocess
from collections.abc import Mapping, Sequence
from copy import deepcopy
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Final, Protocol, cast

from quant_hunter.config import (
    CanonicalJsonError,
    JsonRecord,
    JsonValue,
    canonicalize_json,
    parse_json_document,
)
from quant_hunter.config.schema import RecordSchemaError, VersionedSchemaCatalog
from quant_hunter.provenance.hashing import (
    require_sha256_digest,
    sha256_bytes,
    sha256_canonical_json,
)
from quant_hunter.storage import ImmutableObjectStore
from quant_hunter.storage.security import (
    SensitiveMetadataError,
    reject_secret_text_values,
)

from .ledger import (
    ExposureLedger,
    ExposureLedgerEvent,
    ExposureLedgerIntegrityError,
    verify_release_event_digest,
)
from .release import EnforcementMode, SealedBinding, SealedReleaseError

HOST_EVIDENCE_SCHEMA: Final = "windows-host-boundary-evidence.schema.json"
CUSTODIAN_ROLE: Final = "qh-oos-custodian"
RESEARCH_ROLE: Final = "qh-research"
REPARSE_POINT_ATTRIBUTE: Final = 0x400
_EVIDENCE_TOKEN: Final = object()
_RELEASE_TOKEN: Final = object()
_SETUP_FAILURE_MARKER: Final = "ITEM10B_SETUP_FAILED"
_SETUP_DIAGNOSTIC_MAX_CHARS: Final = 384
_SETUP_REASON_MAX_CHARS: Final = 240
_SETUP_PHASES: Final = frozenset(
    {
        "PREFLIGHT",
        "ROOT_CREATE",
        "CUSTODIAN_CREATE",
        "RESEARCH_CREATE",
        "PRIVILEGE_CHECK",
        "VAULT_DACL",
        "RELEASE_DACL",
        "EVIDENCE_DACL",
        "INDEX_EXCLUSION",
        "AUDIT_POLICY",
        "VAULT_SACL",
        "RELEASE_SACL",
        "SYNTHETIC_FIXTURE",
        "EFFECTIVE_VERIFY",
        "DISABLE_IDENTITIES",
        "ROLLBACK",
    }
)
_ANSI_ESCAPE_RE: Final = re.compile(
    r"(?:\x1b\][^\x07]*(?:\x07|\x1b\\)|\x1b\[[0-?]*[ -/]*[@-~])"
)
_RECOVERY_MATERIAL_RE: Final = re.compile(
    r"((?:bitlocker\s+)?recovery(?:[-_ ]?(?:key|password))"
    r"\s*(?:=|:|\s)\s*)\S+",
    re.IGNORECASE,
)
_SAFE_EXCEPTION_TYPE_RE: Final = re.compile(r"[A-Za-z0-9_.+]{1,120}")
_EXECUTION_RESULT_FIELDS: Final = {
    "schema_version",
    "verified_at",
    "platform",
    "preflight_observations",
    "vault_path",
    "release_path",
    "evidence_path",
    "custodian_identity",
    "research_identity",
    "vault_dacl_checks",
    "release_dacl_checks",
    "audit_checks",
    "research_denial_checks",
    "custodian_access_checks",
    "released_artifact_checks",
    "indexing_excluded",
    "synthetic_fixture_only",
    "identity_authentication_material_persisted",
    "identities_disabled_after_verification",
    "live_verification_passed",
    "limitations",
}
_PREFLIGHT_OBSERVATION_FIELDS: Final = {
    "preflight_passed",
    "candidate_root",
    "filesystem",
    "fixed_local_volume",
    "encryption",
    "repository_worktree_excluded",
    "profile_cache_temp_excluded",
    "sync_overlap_detected",
    "governed_identities_absent",
    "candidate_path_absent",
    "original_file_system_audit_policy",
    "backup_observation",
    "backup_status",
}


class WindowsHostBoundaryError(SealedReleaseError):
    """Windows host evidence or host release authorization is invalid."""


class UnsupportedHostPlatformError(WindowsHostBoundaryError):
    """A live Windows-only operation was requested on another platform."""


class HostBoundaryEvidenceError(WindowsHostBoundaryError):
    """Host evidence is absent, malformed, stale, or inconsistent."""


class HostIdentityError(WindowsHostBoundaryError):
    """The effective operating-system identity lacks release authority."""


class _FrozenAuthority(Protocol):
    def verify_release_authority(
        self,
        *,
        experiment_id: str,
        frozen_revision_digest: str,
        frozen_manifest_digest: str,
        dataset_ids: Sequence[str],
        sealed_partition: Mapping[str, JsonValue],
        code_revision: str,
        configuration_digest: str,
        environment_digest: str,
        occurred_at: str,
    ) -> object: ...

    def verify_historical_release_authority(
        self,
        *,
        experiment_id: str,
        frozen_revision_digest: str,
        frozen_manifest_digest: str,
        dataset_ids: Sequence[str],
        sealed_partition: Mapping[str, JsonValue],
        code_revision: str,
        configuration_digest: str,
        environment_digest: str,
        occurred_at: str,
        release_event_digest: str,
    ) -> object: ...


def _is_windows_host() -> bool:
    return os.name == "nt"


def _governed_repository_root() -> Path:
    """Return the source checkout that supplied this authority implementation."""
    return Path(__file__).resolve().parents[3]


def _require_windows_host() -> None:
    if not _is_windows_host():
        raise UnsupportedHostPlatformError(
            "Live host-boundary operations require Windows"
        )


def _is_elevated_administrator() -> bool:
    _require_windows_host()
    windll = cast(Any, ctypes).windll
    return bool(windll.shell32.IsUserAnAdmin())


def _current_windows_account() -> str:
    _require_windows_host()
    system_root = os.environ.get("SystemRoot")
    if not system_root:
        raise HostIdentityError("Windows system root is unavailable")
    executable = Path(system_root) / "System32" / "whoami.exe"
    try:
        result = subprocess.run(  # noqa: S603 - absolute Windows system binary
            [str(executable)],
            check=True,
            capture_output=True,
            text=True,
            timeout=10,
        )
    except (OSError, subprocess.SubprocessError) as error:
        raise HostIdentityError(
            "Cannot determine the effective Windows identity"
        ) from error
    account = result.stdout.strip()
    if not account:
        raise HostIdentityError("Effective Windows identity is empty")
    return account


def _account_leaf(account: str) -> str:
    return account.rsplit("\\", maxsplit=1)[-1].casefold()


def _governed_setup_failure_message(stderr: object) -> str:
    """Return only the bounded, structured diagnostic emitted by setup."""
    if isinstance(stderr, bytes):
        text = stderr[-8192:].decode("utf-8", errors="replace")
    elif isinstance(stderr, str):
        text = stderr[-8192:]
    else:
        text = ""
    text = _ANSI_ESCAPE_RE.sub("", text)
    lines = text.splitlines()
    try:
        marker_index = max(
            index
            for index, line in enumerate(lines)
            if line.strip() == _SETUP_FAILURE_MARKER
        )
    except ValueError:
        return "Governed Item 10B execution failed without creating authority"

    fields: dict[str, str] = {}
    for line in lines[marker_index + 1 : marker_index + 4]:
        key, separator, value = line.partition("=")
        if separator and key in {"phase", "exception_type", "reason"}:
            fields[key] = value.strip()
    phase = fields.get("phase", "UNKNOWN")
    if phase not in _SETUP_PHASES:
        phase = "UNKNOWN"
    exception_type = fields.get("exception_type", "System.Exception")
    if _SAFE_EXCEPTION_TYPE_RE.fullmatch(exception_type) is None:
        exception_type = "System.Exception"
    reason = " ".join(fields.get("reason", "").split())
    reason = "".join(character for character in reason if character.isprintable())
    if not reason:
        reason = "No safe reason was available."
    reason = _RECOVERY_MATERIAL_RE.sub(r"\1[REDACTED]", reason)
    try:
        reject_secret_text_values(reason, "governed setup diagnostic")
    except SensitiveMetadataError:
        reason = "[REDACTED]"
    reason = reason[:_SETUP_REASON_MAX_CHARS]
    message = (
        f"Governed Item 10B execution failed at {phase} ({exception_type}): {reason}"
    )
    return message[:_SETUP_DIAGNOSTIC_MAX_CHARS]


def _is_link_like(path: Path) -> bool:
    try:
        metadata = path.lstat()
    except FileNotFoundError:
        return False
    attributes = getattr(metadata, "st_file_attributes", 0)
    return path.is_symlink() or bool(attributes & REPARSE_POINT_ATTRIBUTE)


def _existing_components(path: Path) -> tuple[Path, ...]:
    current = Path(path.anchor)
    components = [current]
    for part in path.parts[1:]:
        current /= part
        if not os.path.lexists(current):
            break
        components.append(current)
    return tuple(components)


def _assert_no_link_components(path: Path) -> None:
    if any(_is_link_like(component) for component in _existing_components(path)):
        raise HostBoundaryEvidenceError(
            "Link-like host-evidence path component is forbidden"
        )


def _resolved_non_root(path: Path, field: str) -> Path:
    if not path.is_absolute() or ".." in path.parts:
        raise HostBoundaryEvidenceError(f"{field} must be an absolute direct path")
    if os.name == "nt" and str(path).startswith("\\\\"):
        raise HostBoundaryEvidenceError(f"{field} must be on a local filesystem")
    _assert_no_link_components(path)
    try:
        resolved = path.resolve(strict=False)
    except OSError as error:
        raise HostBoundaryEvidenceError(f"{field} cannot be resolved") from error
    if resolved == Path(resolved.anchor):
        raise HostBoundaryEvidenceError(f"{field} must not be a filesystem root")
    _assert_no_link_components(resolved)
    return resolved


def _require_within(path: Path, root: Path, field: str) -> Path:
    resolved = _resolved_non_root(path, field)
    try:
        resolved.relative_to(root)
    except ValueError as error:
        raise HostBoundaryEvidenceError(
            f"{field} must remain below evidence root"
        ) from error
    return resolved


def _location_fingerprint(path: Path, purpose: str) -> str:
    normalized = str(path.resolve(strict=False)).replace("\\", "/").casefold()
    return sha256_canonical_json({"normalized_path": normalized, "purpose": purpose})


def host_boundary_evidence_digest(record: Mapping[str, JsonValue]) -> str:
    """Hash canonical host evidence excluding only its managed digest field."""
    body = deepcopy(dict(record))
    body.pop("host_boundary_evidence_digest", None)
    return sha256_bytes(canonicalize_json(body))


def verify_host_boundary_evidence_digest(record: Mapping[str, JsonValue]) -> None:
    """Require the retained digest to identify the complete canonical evidence."""
    digest = record.get("host_boundary_evidence_digest")
    if not isinstance(digest, str):
        raise HostBoundaryEvidenceError("Host-boundary evidence digest is malformed")
    try:
        require_sha256_digest(digest)
    except ValueError as error:
        raise HostBoundaryEvidenceError(
            "Host-boundary evidence digest is malformed"
        ) from error
    if host_boundary_evidence_digest(record) != digest:
        raise HostBoundaryEvidenceError("Host-boundary evidence digest mismatch")


@dataclass(frozen=True, slots=True)
class WindowsHostBoundaryProfile:
    """Host-local paths and fixed role names; paths are not scientific identities."""

    vault_root: Path
    release_root: Path
    evidence_root: Path
    custodian_role: str = CUSTODIAN_ROLE
    research_role: str = RESEARCH_ROLE

    def __post_init__(self) -> None:
        vault = _resolved_non_root(self.vault_root, "vault_root")
        release = _resolved_non_root(self.release_root, "release_root")
        evidence = _resolved_non_root(self.evidence_root, "evidence_root")
        if len({vault, release, evidence}) != 3:
            raise HostBoundaryEvidenceError("Host boundary paths must be distinct")
        if self.custodian_role != CUSTODIAN_ROLE or self.research_role != RESEARCH_ROLE:
            raise HostBoundaryEvidenceError("Host boundary role names are governed")
        object.__setattr__(self, "vault_root", vault)
        object.__setattr__(self, "release_root", release)
        object.__setattr__(self, "evidence_root", evidence)

    @property
    def vault_location_fingerprint(self) -> str:
        return _location_fingerprint(self.vault_root, "SEALED_VAULT")

    @property
    def release_location_fingerprint(self) -> str:
        return _location_fingerprint(self.release_root, "RELEASE_ROOT")


class VerifiedWindowsHostBoundaryEvidence:
    """Evidence constructible only by a successful verifier operation."""

    __slots__ = ("_path", "_record", "_verifier")

    def __init__(
        self,
        record: Mapping[str, JsonValue],
        verifier: WindowsHostBoundaryVerifier,
        path: Path,
        *,
        _token: object,
    ) -> None:
        if _token is not _EVIDENCE_TOKEN:
            raise TypeError("Verified host evidence requires the Windows verifier")
        self._record = deepcopy(dict(record))
        self._verifier = verifier
        self._path = path

    @property
    def digest(self) -> str:
        return cast(str, self._record["host_boundary_evidence_digest"])

    @property
    def record(self) -> JsonRecord:
        return deepcopy(self._record)

    @property
    def release_location_fingerprint(self) -> str:
        return cast(str, self._record["release_location_fingerprint"])

    @property
    def custodian_role(self) -> str:
        return cast(str, self._record["custodian_role"])

    def verify(self) -> JsonRecord:
        """Re-read and revalidate the protected canonical evidence file."""
        observed = self._verifier._load_verified_record(self._path)
        if observed != self._record:
            raise HostBoundaryEvidenceError(
                "Verified host-boundary evidence changed after construction"
            )
        return deepcopy(observed)


class WindowsHostBoundaryVerifier:
    """Capture governed live evidence or load retained canonical evidence."""

    def __init__(
        self,
        profile: WindowsHostBoundaryProfile,
        schema_directory: Path,
    ) -> None:
        self.profile = profile
        self._schemas = VersionedSchemaCatalog(schema_directory)

    def capture_live_evidence(
        self,
        repository_root: Path,
        candidate_root: Path,
        evidence_path: Path,
        *,
        authorize_setup: bool,
    ) -> VerifiedWindowsHostBoundaryEvidence:
        """Execute the governed host workflow and publish its immediate result."""
        _require_windows_host()
        if not _is_elevated_administrator():
            raise HostIdentityError(
                "Capturing live host evidence requires an elevated administrator"
            )
        if not authorize_setup:
            raise HostBoundaryEvidenceError(
                "Live host setup requires explicit caller authorization"
            )
        repository = _resolved_non_root(repository_root, "repository root")
        if not repository.is_dir():
            raise HostBoundaryEvidenceError("Repository root is not a directory")
        governed_repository = _resolved_non_root(
            _governed_repository_root(), "governed repository root"
        )
        if repository != governed_repository:
            raise HostBoundaryEvidenceError(
                "Repository root does not match the running governed implementation"
            )
        candidate = _resolved_non_root(candidate_root, "candidate root")
        self._require_candidate_profile(candidate)
        output_file = _require_within(
            evidence_path, self.profile.evidence_root, "canonical evidence path"
        )
        if os.path.lexists(output_file):
            raise HostBoundaryEvidenceError(
                "Canonical host evidence is append-only and already exists"
            )
        result = self._run_governed_setup(repository, candidate)
        self._require_execution_binding(result, candidate)
        record = self._sanitized_record(result, candidate)
        record["host_boundary_evidence_digest"] = host_boundary_evidence_digest(record)
        self._validate_record(record)
        self._exclusive_publish(output_file, canonicalize_json(record))
        return self.load(evidence_path)

    def _run_governed_setup(
        self, repository_root: Path, candidate_root: Path
    ) -> JsonRecord:
        """Run the sole live producer without accepting a substitutable report."""
        setup_script = _require_within(
            repository_root / "scripts" / "windows" / "item10b_setup.ps1",
            repository_root,
            "governed setup script",
        )
        if _is_link_like(setup_script) or not setup_script.is_file():
            raise HostBoundaryEvidenceError(
                "Governed Item 10B setup script is unavailable"
            )
        powershell = shutil.which("pwsh.exe") or shutil.which("pwsh")
        if powershell is None:
            raise HostBoundaryEvidenceError("PowerShell 7 is unavailable")
        try:
            completed = subprocess.run(  # noqa: S603 - governed local script
                [
                    powershell,
                    "-NoLogo",
                    "-NoProfile",
                    "-NonInteractive",
                    "-File",
                    str(setup_script),
                    "-RepositoryRoot",
                    str(repository_root),
                    "-CandidateRoot",
                    str(candidate_root),
                    "-Apply",
                    "-Confirm:$false",
                ],
                cwd=repository_root,
                check=False,
                capture_output=True,
                timeout=900,
            )
        except (OSError, subprocess.SubprocessError) as error:
            raise HostBoundaryEvidenceError(
                "Governed Item 10B execution could not complete"
            ) from error
        if completed.returncode != 0:
            raise HostBoundaryEvidenceError(
                _governed_setup_failure_message(completed.stderr)
            )
        try:
            parsed = parse_json_document(completed.stdout)
        except CanonicalJsonError as error:
            raise HostBoundaryEvidenceError(
                "Governed Item 10B execution did not return strict JSON"
            ) from error
        if not isinstance(parsed, dict):
            raise HostBoundaryEvidenceError(
                "Governed Item 10B execution result is not a JSON object"
            )
        return parsed

    def load(self, evidence_path: Path) -> VerifiedWindowsHostBoundaryEvidence:
        """Load protected canonical evidence into the typed authority boundary."""
        _require_windows_host()
        path = _require_within(
            evidence_path, self.profile.evidence_root, "canonical evidence path"
        )
        record = self._load_verified_record(path)
        return VerifiedWindowsHostBoundaryEvidence(
            record, self, path, _token=_EVIDENCE_TOKEN
        )

    def _load_verified_record(self, path: Path) -> JsonRecord:
        path = _require_within(path, self.profile.evidence_root, "evidence path")
        if _is_link_like(path) or not path.is_file():
            raise HostBoundaryEvidenceError(
                "Canonical host evidence is not a regular file"
            )
        try:
            content = path.read_bytes()
            parsed = parse_json_document(content)
        except (OSError, CanonicalJsonError) as error:
            raise HostBoundaryEvidenceError(
                "Canonical host evidence is not strict JSON"
            ) from error
        if not isinstance(parsed, dict):
            raise HostBoundaryEvidenceError(
                "Canonical host evidence is not a JSON object"
            )
        record = parsed
        self._validate_record(record)
        if content != canonicalize_json(record):
            raise HostBoundaryEvidenceError("Host-boundary evidence is not canonical")
        verify_host_boundary_evidence_digest(record)
        if (
            record.get("vault_location_fingerprint")
            != self.profile.vault_location_fingerprint
            or record.get("release_location_fingerprint")
            != self.profile.release_location_fingerprint
            or record.get("custodian_role") != self.profile.custodian_role
            or record.get("research_role") != self.profile.research_role
        ):
            raise HostBoundaryEvidenceError(
                "Host-boundary evidence does not match the configured profile"
            )
        return record

    def _validate_record(self, record: Mapping[str, JsonValue]) -> None:
        try:
            reject_secret_text_values(record, "Windows host-boundary evidence")
            self._schemas.validate(HOST_EVIDENCE_SCHEMA, record)
        except (RecordSchemaError, SensitiveMetadataError) as error:
            raise HostBoundaryEvidenceError(
                "Host-boundary evidence failed governed validation"
            ) from error

    def _require_candidate_profile(self, candidate_root: Path) -> None:
        expected = {
            self.profile.vault_root: candidate_root / "vault",
            self.profile.release_root: candidate_root / "releases",
            self.profile.evidence_root: candidate_root / "host-evidence",
        }
        if any(actual != expected_path for actual, expected_path in expected.items()):
            raise HostBoundaryEvidenceError(
                "Candidate root does not match the configured host profile"
            )

    def _require_execution_binding(
        self, result: Mapping[str, JsonValue], candidate_root: Path
    ) -> None:
        if set(result) != _EXECUTION_RESULT_FIELDS:
            raise HostBoundaryEvidenceError(
                "Governed Item 10B execution result shape is invalid"
            )
        try:
            reject_secret_text_values(result, "governed Windows host execution")
        except SensitiveMetadataError as error:
            raise HostBoundaryEvidenceError(
                "Governed host execution contains forbidden credential material"
            ) from error
        self._require_result_paths(result)
        preflight = result.get("preflight_observations")
        if not isinstance(preflight, dict) or set(preflight) != (
            _PREFLIGHT_OBSERVATION_FIELDS
        ):
            raise HostBoundaryEvidenceError(
                "Governed Item 10B preflight observations are invalid"
            )
        supplied_root = preflight.get("candidate_root")
        if (
            not isinstance(supplied_root, str)
            or _resolved_non_root(Path(supplied_root), "observed candidate root")
            != candidate_root
        ):
            raise HostBoundaryEvidenceError(
                "Preflight observations belong to a different candidate root"
            )

    def _require_result_paths(self, result: Mapping[str, JsonValue]) -> None:
        expected = {
            "vault_path": self.profile.vault_root,
            "release_path": self.profile.release_root,
            "evidence_path": self.profile.evidence_root,
        }
        for field, expected_path in expected.items():
            supplied = result.get(field)
            if (
                not isinstance(supplied, str)
                or _resolved_non_root(Path(supplied), field) != expected_path
            ):
                raise HostBoundaryEvidenceError(
                    "Governed execution path does not match the configured profile"
                )
        if (
            result.get("custodian_identity") != self.profile.custodian_role
            or result.get("research_identity") != self.profile.research_role
        ):
            raise HostBoundaryEvidenceError(
                "Governed execution identities do not match the governed roles"
            )

    def _sanitized_record(
        self, result: Mapping[str, JsonValue], candidate_root: Path
    ) -> JsonRecord:
        copied_fields = (
            "verified_at",
            "platform",
            "vault_dacl_checks",
            "release_dacl_checks",
            "audit_checks",
            "research_denial_checks",
            "custodian_access_checks",
            "released_artifact_checks",
            "indexing_excluded",
            "synthetic_fixture_only",
            "identity_authentication_material_persisted",
            "identities_disabled_after_verification",
            "live_verification_passed",
            "limitations",
        )
        record: JsonRecord = {
            "schema_version": "1.0.0",
            "evidence_type": "WINDOWS_HOST_BOUNDARY",
            "evidence_mode": EnforcementMode.HOST_ENFORCED.value,
            "preflight_observations": deepcopy(result["preflight_observations"]),
            "candidate_root_fingerprint": _location_fingerprint(
                candidate_root, "HOST_BOUNDARY_ROOT"
            ),
            "vault_location_fingerprint": self.profile.vault_location_fingerprint,
            "release_location_fingerprint": self.profile.release_location_fingerprint,
            "custodian_role": self.profile.custodian_role,
            "research_role": self.profile.research_role,
        }
        preflight = cast(JsonRecord, record["preflight_observations"])
        preflight.pop("candidate_root")
        for field in copied_fields:
            record[field] = deepcopy(result[field])
        return record

    @staticmethod
    def _exclusive_publish(path: Path, content: bytes) -> None:
        try:
            descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        except OSError as error:
            raise HostBoundaryEvidenceError(
                "Canonical host evidence could not be created exclusively"
            ) from error
        try:
            with os.fdopen(descriptor, "wb") as stream:
                stream.write(content)
                stream.flush()
                os.fsync(stream.fileno())
        except OSError as error:
            path.unlink(missing_ok=True)
            raise HostBoundaryEvidenceError(
                "Canonical host evidence publication failed"
            ) from error


@dataclass(frozen=True, slots=True)
class HostEnforcedReleaseRequest:
    """A host release bound to verified evidence and exact Item 8 authority."""

    experiment_id: str
    frozen_revision_digest: str
    frozen_manifest_digest: str
    sealed_binding: SealedBinding
    code_revision: str
    configuration_digest: str
    environment_digest: str
    occurred_at: str
    actor: str
    reason: str
    released_artifact_digest: str
    host_boundary_evidence: VerifiedWindowsHostBoundaryEvidence


class VerifiedHostReleaseEvidence:
    """A HOST_ENFORCED event rechecked with exact host and artifact evidence."""

    __slots__ = ("_event", "_host_evidence", "_ledger", "_object_store")

    def __init__(
        self,
        ledger: ExposureLedger,
        object_store: ImmutableObjectStore,
        event: ExposureLedgerEvent,
        host_evidence: VerifiedWindowsHostBoundaryEvidence,
        *,
        _token: object,
    ) -> None:
        if _token is not _RELEASE_TOKEN:
            raise TypeError(
                "Verified host release requires the Windows release service"
            )
        self._ledger = ledger
        self._object_store = object_store
        self._event = event
        self._host_evidence = host_evidence

    @property
    def event_digest(self) -> str:
        return self._event.digest

    @property
    def record(self) -> JsonRecord:
        return deepcopy(self._event.record)

    def verify(self) -> JsonRecord:
        """Reverify ledger membership, host evidence, and released exact bytes."""
        event = self._ledger.get_verified(self._event.digest)
        if event.record != self._event.record:
            raise ExposureLedgerIntegrityError(
                "Verified host release changed after construction"
            )
        record = event.record
        verify_release_event_digest(record)
        if (
            record.get("event_type") != "AUTHORIZED_RELEASE"
            or record.get("enforcement_mode") != EnforcementMode.HOST_ENFORCED.value
        ):
            raise WindowsHostBoundaryError(
                "Exposure evidence is not a host-enforced authorized release"
            )
        host_record = self._host_evidence.verify()
        if record.get("host_boundary_evidence_digest") != host_record.get(
            "host_boundary_evidence_digest"
        ):
            raise HostBoundaryEvidenceError(
                "Release event host-boundary evidence digest mismatch"
            )
        digest = record.get("released_artifact_digest")
        reference = record.get("released_artifact_reference")
        if not isinstance(digest, str) or not isinstance(reference, str):
            raise WindowsHostBoundaryError("Released artifact evidence is malformed")
        if (
            _location_fingerprint(self._object_store.root, "RELEASE_ROOT")
            != self._host_evidence.release_location_fingerprint
        ):
            raise HostBoundaryEvidenceError(
                "Released object store does not match verified host evidence"
            )
        stored = self._object_store.get(digest)
        if self._object_store.storage_reference(stored.digest) != reference:
            raise WindowsHostBoundaryError("Released artifact reference mismatch")
        return deepcopy(record)


class WindowsHostReleaseService:
    """Authorize HOST_ENFORCED releases without weakening Item 10A authority."""

    def __init__(
        self,
        lifecycle: _FrozenAuthority,
        ledger: ExposureLedger,
        object_store: ImmutableObjectStore,
    ) -> None:
        self.lifecycle = lifecycle
        self.ledger = ledger
        self.object_store = object_store

    def authorize_release(
        self,
        request: HostEnforcedReleaseRequest,
        *,
        expected_ledger_head: str | None,
    ) -> VerifiedHostReleaseEvidence:
        """Recheck host, FROZEN, binding, and artifact evidence before append."""
        _require_windows_host()
        host_record = request.host_boundary_evidence.verify()
        current_account = _current_windows_account()
        if (
            _account_leaf(current_account)
            != request.host_boundary_evidence.custodian_role
        ):
            raise HostIdentityError(
                "HOST_ENFORCED release requires the effective custodian identity"
            )
        if request.actor != request.host_boundary_evidence.custodian_role:
            raise HostIdentityError("Release actor must identify the custodian role")
        self._validate_text(request.actor, "release actor")
        self._validate_text(request.reason, "release reason")
        if (
            _location_fingerprint(self.object_store.root, "RELEASE_ROOT")
            != request.host_boundary_evidence.release_location_fingerprint
        ):
            raise HostBoundaryEvidenceError(
                "Released object store does not match verified host evidence"
            )
        binding = request.sealed_binding.as_record()
        self.lifecycle.verify_release_authority(
            experiment_id=request.experiment_id,
            frozen_revision_digest=request.frozen_revision_digest,
            frozen_manifest_digest=request.frozen_manifest_digest,
            dataset_ids=request.sealed_binding.dataset_ids,
            sealed_partition=cast(JsonRecord, binding["sealed_out_of_sample"]),
            code_revision=request.code_revision,
            configuration_digest=request.configuration_digest,
            environment_digest=request.environment_digest,
            occurred_at=request.occurred_at,
        )
        require_sha256_digest(request.released_artifact_digest)
        released = self.object_store.get(request.released_artifact_digest)
        body: JsonRecord = {
            "schema_version": "1.0.0",
            "event_type": "AUTHORIZED_RELEASE",
            "experiment_id": request.experiment_id,
            "frozen_revision_digest": request.frozen_revision_digest,
            "frozen_manifest_digest": request.frozen_manifest_digest,
            "sealed_binding": binding,
            "code_revision": request.code_revision,
            "configuration_digest": request.configuration_digest,
            "environment_digest": request.environment_digest,
            "occurred_at": request.occurred_at,
            "actor": request.actor,
            "reason": request.reason,
            "released_artifact_digest": released.digest,
            "released_artifact_reference": self.object_store.storage_reference(
                released.digest
            ),
            "source_partition_status": "EXPOSED",
            "enforcement_mode": EnforcementMode.HOST_ENFORCED.value,
            "host_boundary_evidence_digest": cast(
                str, host_record["host_boundary_evidence_digest"]
            ),
        }
        event = self.ledger._append_validated_event(
            body, expected_previous_digest=expected_ledger_head
        )
        return self.verify_release(
            event.digest, host_boundary_evidence=request.host_boundary_evidence
        )

    def verify_release(
        self,
        event_digest: str,
        *,
        host_boundary_evidence: VerifiedWindowsHostBoundaryEvidence,
    ) -> VerifiedHostReleaseEvidence:
        """Verify retained host release against historical Item 8 authority."""
        event = self.ledger.get_verified(event_digest)
        evidence = VerifiedHostReleaseEvidence(
            self.ledger,
            self.object_store,
            event,
            host_boundary_evidence,
            _token=_RELEASE_TOKEN,
        )
        record = evidence.verify()
        binding = SealedBinding.from_record(record.get("sealed_binding"))
        self.lifecycle.verify_historical_release_authority(
            experiment_id=cast(str, record["experiment_id"]),
            frozen_revision_digest=cast(str, record["frozen_revision_digest"]),
            frozen_manifest_digest=cast(str, record["frozen_manifest_digest"]),
            dataset_ids=binding.dataset_ids,
            sealed_partition=cast(
                JsonRecord, binding.as_record()["sealed_out_of_sample"]
            ),
            code_revision=cast(str, record["code_revision"]),
            configuration_digest=cast(str, record["configuration_digest"]),
            environment_digest=cast(str, record["environment_digest"]),
            occurred_at=cast(str, record["occurred_at"]),
            release_event_digest=event.digest,
        )
        return evidence

    @staticmethod
    def _validate_text(value: str, context: str) -> None:
        if not isinstance(value, str) or not value.strip():
            raise WindowsHostBoundaryError(f"{context} must be a nonempty string")
        try:
            reject_secret_text_values(value, context)
        except SensitiveMetadataError as error:
            raise WindowsHostBoundaryError(
                f"{context} contains forbidden labelled credential material"
            ) from error
