"""Hostile synthetic tests for the Item 10B Windows host authority."""

from __future__ import annotations

import json
import subprocess
from copy import deepcopy
from dataclasses import dataclass, replace
from pathlib import Path
from types import SimpleNamespace
from typing import Any, cast
from uuid import UUID

import pytest
from test_sealed_release import (
    SECOND_EXPERIMENT_ID,
    THIRD_DATASET_ID,
    ReleaseHarness,
    _build_harness,
    _payload_for_footprint,
)

from quant_hunter.config import JsonRecord, JsonValue, canonicalize_json
from quant_hunter.experiments import ExperimentIntegrityError, PostReleaseSearchError
from quant_hunter.identity import RegistryIntegrityError
from quant_hunter.isolation import (
    ExposureAlreadyRecordedError,
    ExposureLedgerEvent,
    ExposureLedgerIntegrityError,
    ExposureLedgerStaleWriterError,
    HostBoundaryEvidenceError,
    HostEnforcedReleaseRequest,
    HostIdentityError,
    SealedBinding,
    UnsupportedHostPlatformError,
    VerifiedHostReleaseEvidence,
    VerifiedWindowsHostBoundaryEvidence,
    WindowsHostBoundaryError,
    WindowsHostBoundaryProfile,
    WindowsHostBoundaryVerifier,
    WindowsHostReleaseService,
    host_boundary_evidence_digest,
    release_event_digest,
    verify_host_boundary_evidence_digest,
    windows_host,
)
from quant_hunter.storage import ImmutableObjectStore, ObjectStoreError

SCHEMA_DIRECTORY = Path(__file__).parents[1] / "schemas" / "v1"


@dataclass(frozen=True, slots=True)
class HostHarness:
    release: ReleaseHarness
    profile: WindowsHostBoundaryProfile
    verifier: WindowsHostBoundaryVerifier
    evidence: VerifiedWindowsHostBoundaryEvidence
    service: WindowsHostReleaseService
    request: HostEnforcedReleaseRequest
    evidence_path: Path


def _live_report(profile: WindowsHostBoundaryProfile) -> JsonRecord:
    return {
        "schema_version": "1.0.0",
        "verified_at": "2026-09-11T06:00:00.000000001Z",
        "platform": "WINDOWS",
        "filesystem": "NTFS",
        "fixed_local_volume": True,
        "encryption": {
            "technology": "BITLOCKER",
            "protection_status": "ON",
            "volume_status": "FULLY_ENCRYPTED",
        },
        "vault_path": str(profile.vault_root),
        "release_path": str(profile.release_root),
        "evidence_path": str(profile.evidence_root),
        "custodian_identity": "qh-oos-custodian",
        "research_identity": "qh-research",
        "vault_dacl_checks": {
            "inheritance_disabled": True,
            "allow_list_verified": True,
            "broad_principals_absent": True,
            "research_data_rights_absent": True,
        },
        "release_dacl_checks": {
            "inheritance_disabled": True,
            "allow_list_verified": True,
            "broad_principals_absent": True,
            "research_read_only": True,
        },
        "audit_checks": {
            "file_system_policy_enabled": True,
            "sacl_verified": True,
            "research_denial_observed": True,
            "custodian_activity_observed": True,
        },
        "research_denial_checks": {
            "directory_list_denied": True,
            "file_read_denied": True,
            "file_create_denied": True,
            "file_write_denied": True,
            "file_delete_denied": True,
            "acl_change_denied": True,
            "owner_change_denied": True,
            "read_attributes_denied": False,
            "read_attributes_observation": (
                "Attributes remained visible under Windows traverse semantics."
            ),
        },
        "custodian_access_checks": {
            "vault_list_succeeded": True,
            "fixture_read_succeeded": True,
            "release_publish_succeeded": True,
        },
        "released_artifact_checks": {
            "research_read_succeeded": True,
            "research_modify_denied": True,
            "research_delete_denied": True,
            "research_acl_change_denied": True,
            "research_owner_change_denied": True,
        },
        "indexing_excluded": True,
        "sync_overlap_detected": False,
        "backup_status": "RESIDUAL_RISK_RETAINED",
        "synthetic_fixture_only": True,
        "identity_authentication_material_persisted": False,
        "identities_disabled_after_verification": True,
        "live_verification_passed": True,
        "limitations": [
            "Administrators and SYSTEM remain outside the Stage 1 threat model.",
            "Only a clearly synthetic fixture was used.",
        ],
    }


def _host_request(
    release: ReleaseHarness,
    evidence: VerifiedWindowsHostBoundaryEvidence,
) -> HostEnforcedReleaseRequest:
    source = release.request
    return HostEnforcedReleaseRequest(
        experiment_id=source.experiment_id,
        frozen_revision_digest=source.frozen_revision_digest,
        frozen_manifest_digest=source.frozen_manifest_digest,
        sealed_binding=source.sealed_binding,
        code_revision=source.code_revision,
        configuration_digest=source.configuration_digest,
        environment_digest=source.environment_digest,
        occurred_at=source.occurred_at,
        actor="qh-oos-custodian",
        reason="Controlled synthetic host-boundary release.",
        released_artifact_digest=source.released_artifact_digest,
        host_boundary_evidence=evidence,
    )


def _build_host_harness(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> HostHarness:
    release = _build_harness(tmp_path)
    vault_root = (tmp_path / "host" / "vault").resolve()
    evidence_root = (tmp_path / "host" / "host-evidence").resolve()
    vault_root.mkdir(parents=True)
    evidence_root.mkdir(parents=True)
    profile = WindowsHostBoundaryProfile(
        vault_root=vault_root,
        release_root=release.lifecycle.object_store.root,
        evidence_root=evidence_root,
    )
    verifier = WindowsHostBoundaryVerifier(profile, SCHEMA_DIRECTORY)
    report_path = evidence_root / "live-report.json"
    evidence_path = evidence_root / "evidence-000001.json"
    report_path.write_text(json.dumps(_live_report(profile)), encoding="utf-8")
    monkeypatch.setattr(windows_host, "_is_windows_host", lambda: True)
    monkeypatch.setattr(windows_host, "_is_elevated_administrator", lambda: True)
    monkeypatch.setattr(
        windows_host,
        "_current_windows_account",
        lambda: "SYNTHETIC-HOST\\qh-oos-custodian",
    )
    evidence = verifier.finalize_live_report(report_path, evidence_path)
    service = WindowsHostReleaseService(
        release.lifecycle, release.ledger, release.lifecycle.object_store
    )
    return HostHarness(
        release,
        profile,
        verifier,
        evidence,
        service,
        _host_request(release, evidence),
        evidence_path,
    )


def test_verified_host_authorities_cannot_be_built_from_raw_mappings() -> None:
    """Public constructors cannot turn caller-provided mappings into authority."""
    evidence_type = cast(Any, VerifiedWindowsHostBoundaryEvidence)
    release_type = cast(Any, VerifiedHostReleaseEvidence)
    with pytest.raises(TypeError):
        evidence_type({})
    with pytest.raises(TypeError):
        release_type({})


def test_non_windows_operations_fail_before_process_or_filesystem_mutation(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Import is portable and explicit live operations fail closed off Windows."""
    profile = WindowsHostBoundaryProfile(
        (tmp_path / "vault").resolve(),
        (tmp_path / "release").resolve(),
        (tmp_path / "evidence").resolve(),
    )
    verifier = WindowsHostBoundaryVerifier(profile, SCHEMA_DIRECTORY)
    monkeypatch.setattr(windows_host, "_is_windows_host", lambda: False)
    monkeypatch.setattr(
        subprocess,
        "run",
        lambda *args, **kwargs: pytest.fail("process execution attempted"),
    )
    with pytest.raises(UnsupportedHostPlatformError):
        verifier.load(profile.evidence_root / "missing.json")


def test_live_report_finalizes_to_canonical_profile_bound_evidence(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Only complete live assertions become deterministic typed evidence."""
    harness = _build_host_harness(tmp_path, monkeypatch)
    record = harness.evidence.verify()
    assert harness.evidence_path.read_bytes() == canonicalize_json(record)
    assert record["host_boundary_evidence_digest"] == harness.evidence.digest
    assert record["vault_location_fingerprint"] == (
        harness.profile.vault_location_fingerprint
    )
    assert "vault_path" not in record
    assert "release_path" not in record
    verify_host_boundary_evidence_digest(record)
    assert host_boundary_evidence_digest(record) == harness.evidence.digest


def test_host_evidence_tamper_and_profile_substitution_are_rejected(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Digest and sanitized location bindings fail closed after publication."""
    harness = _build_host_harness(tmp_path, monkeypatch)
    original = harness.evidence.record
    tampered = harness.evidence.record
    tampered["backup_status"] = "EQUIVALENT_PROTECTION_VERIFIED"
    harness.evidence_path.write_bytes(canonicalize_json(tampered))
    with pytest.raises(HostBoundaryEvidenceError, match="digest mismatch"):
        harness.evidence.verify()
    harness.evidence_path.write_bytes(canonicalize_json(original))

    other_release = (tmp_path / "other-release").resolve()
    other_release.mkdir()
    wrong_profile = WindowsHostBoundaryProfile(
        harness.profile.vault_root,
        other_release,
        harness.profile.evidence_root,
    )
    wrong_verifier = WindowsHostBoundaryVerifier(wrong_profile, SCHEMA_DIRECTORY)
    with pytest.raises(HostBoundaryEvidenceError, match="configured profile"):
        wrong_verifier.load(harness.evidence_path)


@pytest.mark.parametrize(
    ("mutation", "expected"),
    [
        (
            lambda report: report.__setitem__("live_verification_passed", False),
            "validation",
        ),
        (
            lambda report: report.__setitem__("sync_overlap_detected", True),
            "validation",
        ),
        (
            lambda report: cast(JsonRecord, report["encryption"]).__setitem__(
                "protection_status", "OFF"
            ),
            "validation",
        ),
        (lambda report: report.__setitem__("unknown", True), "shape"),
        (
            lambda report: report.__setitem__(
                "limitations",
                [
                    "Administrators and SYSTEM remain outside the Stage 1 threat model.",
                    "Authorization: Bearer synthetic-hidden-value",
                ],
            ),
            "credential",
        ),
    ],
)
def test_incomplete_or_secret_bearing_live_reports_are_rejected(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    mutation: Any,
    expected: str,
) -> None:
    """A report cannot claim HOST_ENFORCED after any material check fails."""
    release = _build_harness(tmp_path)
    evidence_root = (tmp_path / "host-evidence").resolve()
    evidence_root.mkdir()
    vault_root = (tmp_path / "vault").resolve()
    vault_root.mkdir()
    profile = WindowsHostBoundaryProfile(
        vault_root, release.lifecycle.object_store.root, evidence_root
    )
    report = _live_report(profile)
    mutation(report)
    report_path = evidence_root / "report.json"
    report_path.write_text(json.dumps(report), encoding="utf-8")
    verifier = WindowsHostBoundaryVerifier(profile, SCHEMA_DIRECTORY)
    monkeypatch.setattr(windows_host, "_is_windows_host", lambda: True)
    monkeypatch.setattr(windows_host, "_is_elevated_administrator", lambda: True)
    with pytest.raises(HostBoundaryEvidenceError, match=expected) as captured:
        verifier.finalize_live_report(report_path, evidence_root / "evidence.json")
    assert "synthetic-hidden-value" not in str(captured.value)


def test_live_report_requires_admin_exact_paths_and_exclusive_output(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Finalization cannot bypass elevation, path binding, or append-only creation."""
    harness = _build_host_harness(tmp_path, monkeypatch)
    report_path = harness.profile.evidence_root / "second-report.json"
    report = _live_report(harness.profile)
    report_path.write_text(json.dumps(report), encoding="utf-8")
    with pytest.raises(HostBoundaryEvidenceError, match="already exists"):
        harness.verifier.finalize_live_report(report_path, harness.evidence_path)

    report["vault_path"] = str((tmp_path / "wrong-vault").resolve())
    report_path.write_text(json.dumps(report), encoding="utf-8")
    with pytest.raises(HostBoundaryEvidenceError, match="configured profile"):
        harness.verifier.finalize_live_report(
            report_path, harness.profile.evidence_root / "unused.json"
        )

    monkeypatch.setattr(windows_host, "_is_elevated_administrator", lambda: False)
    with pytest.raises(HostIdentityError, match="elevated"):
        harness.verifier.finalize_live_report(
            report_path, harness.profile.evidence_root / "unused.json"
        )


def test_host_release_binds_typed_evidence_and_exact_artifact(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The host service creates a schema-valid, canonical, reverified event."""
    harness = _build_host_harness(tmp_path, monkeypatch)
    released = harness.service.authorize_release(
        harness.request, expected_ledger_head=None
    )
    record = released.verify()
    assert record["enforcement_mode"] == "HOST_ENFORCED"
    assert record["host_boundary_evidence_digest"] == harness.evidence.digest
    assert (
        harness.service.verify_release(
            released.event_digest, host_boundary_evidence=harness.evidence
        ).record
        == record
    )


@pytest.mark.parametrize(
    ("field", "value", "error_type"),
    [
        ("frozen_revision_digest", "sha256:" + "9" * 64, ExperimentIntegrityError),
        ("frozen_manifest_digest", "sha256:" + "8" * 64, ExperimentIntegrityError),
        ("experiment_id", SECOND_EXPERIMENT_ID, RegistryIntegrityError),
        (
            "sealed_binding",
            SealedBinding(
                (THIRD_DATASET_ID,),
                "2022-01-01T00:00:00Z",
                "2022-02-01T00:00:00Z",
            ),
            ExperimentIntegrityError,
        ),
        ("released_artifact_digest", "sha256:" + "7" * 64, ObjectStoreError),
    ],
)
def test_host_release_rejects_wrong_frozen_binding_or_artifact(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    field: str,
    value: object,
    error_type: type[Exception],
) -> None:
    """Typed host evidence cannot substitute for exact scientific authority."""
    harness = _build_host_harness(tmp_path, monkeypatch)
    request = replace(harness.request, **cast(Any, {field: value}))
    with pytest.raises(error_type):
        harness.service.authorize_release(request, expected_ledger_head=None)
    assert harness.release.ledger.verify() == ()


def test_host_release_requires_effective_custodian_and_matching_release_root(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Host mode cannot be authorized by a research identity or another root."""
    harness = _build_host_harness(tmp_path, monkeypatch)
    monkeypatch.setattr(
        windows_host, "_current_windows_account", lambda: "HOST\\qh-research"
    )
    with pytest.raises(HostIdentityError, match="effective custodian"):
        harness.service.authorize_release(harness.request, expected_ledger_head=None)

    monkeypatch.setattr(
        windows_host,
        "_current_windows_account",
        lambda: "HOST\\qh-oos-custodian",
    )
    wrong_actor = replace(harness.request, actor="qh-research")
    with pytest.raises(HostIdentityError, match="actor"):
        harness.service.authorize_release(wrong_actor, expected_ledger_head=None)

    wrong_store = type(harness.release.lifecycle.object_store)(
        (tmp_path / "wrong-release-root").resolve()
    )
    wrong_service = WindowsHostReleaseService(
        harness.release.lifecycle, harness.release.ledger, wrong_store
    )
    with pytest.raises(HostBoundaryEvidenceError, match="object store"):
        wrong_service.authorize_release(harness.request, expected_ledger_head=None)


def test_host_release_preserves_item8_search_termination_and_single_freeze(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A host release flows through the existing Item 8 lifecycle authority."""
    harness = _build_host_harness(tmp_path, monkeypatch)
    released = harness.service.authorize_release(
        harness.request, expected_ledger_head=None
    )
    running = harness.release.lifecycle.start(
        harness.release.experiment_id,
        harness.release.frozen_digest,
        started_at="2026-09-11T06:01:00Z",
        release_evidence=released,
    )
    with pytest.raises(PostReleaseSearchError):
        harness.release.lifecycle.record_attempt(
            harness.release.experiment_id,
            running.digest,
            recorded_at="2026-09-11T06:02:00Z",
            ai_generated=True,
            failed=False,
            exposure_reason="Forbidden post-release synthetic search.",
        )
    history = harness.release.lifecycle.registry.verify_object(
        harness.release.experiment_id
    )
    assert sum(item.record["lifecycle_status"] == "FROZEN" for item in history) == 1


def test_host_release_cannot_reseal_or_fork_global_exposure(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Host mode keeps global overlap, append-only history, and CAS invariants."""
    first = _build_host_harness(tmp_path, monkeypatch)
    evidence = first.service.authorize_release(first.request, expected_ledger_head=None)
    with pytest.raises(ExposureAlreadyRecordedError):
        first.service.authorize_release(
            first.request, expected_ledger_head=evidence.event_digest
        )
    with pytest.raises(ExposureLedgerStaleWriterError):
        first.service.authorize_release(first.request, expected_ledger_head=None)

    second = _build_harness(
        tmp_path,
        payload=_payload_for_footprint(
            first.release.binding.dataset_ids,
            first.release.binding.start,
            first.release.binding.end,
        ),
        experiment_uuid=UUID(SECOND_EXPERIMENT_ID.removeprefix("EXP-")),
        ledger=first.release.ledger,
    )
    second_request = _host_request(second, first.evidence)
    second_service = WindowsHostReleaseService(
        second.lifecycle, first.release.ledger, second.lifecycle.object_store
    )
    with pytest.raises(ExposureAlreadyRecordedError):
        second_service.authorize_release(
            second_request, expected_ledger_head=evidence.event_digest
        )
    assert len(first.release.ledger.verify()) == 1


def test_host_event_missing_or_wrong_evidence_digest_fails_closed(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Structural storage requires the exact host evidence identity."""
    harness = _build_host_harness(tmp_path, monkeypatch)
    released = harness.release.lifecycle.object_store.get(
        harness.request.released_artifact_digest
    )
    body: JsonRecord = {
        "schema_version": "1.0.0",
        "event_type": "AUTHORIZED_RELEASE",
        "experiment_id": harness.request.experiment_id,
        "frozen_revision_digest": harness.request.frozen_revision_digest,
        "frozen_manifest_digest": harness.request.frozen_manifest_digest,
        "sealed_binding": harness.request.sealed_binding.as_record(),
        "code_revision": harness.request.code_revision,
        "configuration_digest": harness.request.configuration_digest,
        "environment_digest": harness.request.environment_digest,
        "occurred_at": harness.request.occurred_at,
        "actor": harness.request.actor,
        "reason": harness.request.reason,
        "released_artifact_digest": released.digest,
        "released_artifact_reference": (
            harness.release.lifecycle.object_store.storage_reference(released.digest)
        ),
        "source_partition_status": "EXPOSED",
        "enforcement_mode": "HOST_ENFORCED",
    }
    with pytest.raises(ExposureLedgerIntegrityError, match="governed validation"):
        harness.release.ledger._append_validated_event(
            body, expected_previous_digest=None
        )
    body["host_boundary_evidence_digest"] = cast(JsonValue, "sha256:" + "f" * 64)
    event = harness.release.ledger._append_validated_event(
        body, expected_previous_digest=None
    )
    with pytest.raises(HostBoundaryEvidenceError, match="digest mismatch"):
        harness.service.verify_release(
            event.digest, host_boundary_evidence=harness.evidence
        )


def test_platform_identity_and_path_guards_fail_closed(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Live identity and path helpers retain explicit failure behavior."""
    module = cast(Any, windows_host)
    assert isinstance(module._is_windows_host(), bool)
    monkeypatch.setattr(module, "_is_windows_host", lambda: True)

    monkeypatch.delenv("SystemRoot", raising=False)
    with pytest.raises(HostIdentityError, match="system root"):
        module._current_windows_account()
    monkeypatch.setenv("SystemRoot", str(tmp_path))
    monkeypatch.setattr(
        subprocess,
        "run",
        lambda *args, **kwargs: SimpleNamespace(stdout="HOST\\qh-oos-custodian\n"),
    )
    assert module._current_windows_account() == "HOST\\qh-oos-custodian"
    monkeypatch.setattr(
        subprocess, "run", lambda *args, **kwargs: SimpleNamespace(stdout="")
    )
    with pytest.raises(HostIdentityError, match="empty"):
        module._current_windows_account()

    def process_failure(*args: object, **kwargs: object) -> object:
        raise OSError("synthetic process failure")

    monkeypatch.setattr(subprocess, "run", process_failure)
    with pytest.raises(HostIdentityError, match="determine"):
        module._current_windows_account()

    assert module._is_link_like(tmp_path / "absent") is False
    monkeypatch.setattr(module, "_is_link_like", lambda path: True)
    with pytest.raises(HostBoundaryEvidenceError, match="Link-like"):
        module._assert_no_link_components(tmp_path)

    monkeypatch.setattr(module, "_is_link_like", lambda path: False)
    with pytest.raises(HostBoundaryEvidenceError, match="absolute"):
        module._resolved_non_root(Path("relative"), "test")
    with pytest.raises(HostBoundaryEvidenceError, match="filesystem root"):
        module._resolved_non_root(Path(tmp_path.anchor), "test")
    with pytest.raises(HostBoundaryEvidenceError, match="below evidence root"):
        module._require_within(
            (tmp_path.parent / "outside.json").resolve(), tmp_path.resolve(), "test"
        )


def test_profile_digest_and_private_constructor_guards(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Profile and digest substitutions cannot manufacture typed authority."""
    with pytest.raises(HostBoundaryEvidenceError, match="distinct"):
        WindowsHostBoundaryProfile(
            tmp_path.resolve(), tmp_path.resolve(), (tmp_path / "evidence").resolve()
        )
    with pytest.raises(HostBoundaryEvidenceError, match="role names"):
        WindowsHostBoundaryProfile(
            (tmp_path / "vault").resolve(),
            (tmp_path / "release").resolve(),
            (tmp_path / "evidence").resolve(),
            custodian_role="other",
        )
    with pytest.raises(HostBoundaryEvidenceError, match="digest is malformed"):
        verify_host_boundary_evidence_digest({})
    with pytest.raises(HostBoundaryEvidenceError, match="digest is malformed"):
        verify_host_boundary_evidence_digest(
            {"host_boundary_evidence_digest": "not-a-digest"}
        )

    harness = _build_host_harness(tmp_path / "valid", monkeypatch)
    evidence_type = cast(Any, VerifiedWindowsHostBoundaryEvidence)
    with pytest.raises(TypeError, match="Windows verifier"):
        evidence_type(
            harness.evidence.record,
            harness.verifier,
            harness.evidence_path,
            _token=object(),
        )
    release_type = cast(Any, VerifiedHostReleaseEvidence)
    with pytest.raises(TypeError, match="Windows release service"):
        release_type(
            harness.release.ledger,
            harness.release.lifecycle.object_store,
            SimpleNamespace(),
            harness.evidence,
            _token=object(),
        )


def test_evidence_loader_rejects_missing_invalid_and_noncanonical_files(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Only a regular canonical schema-valid file can retain typed authority."""
    harness = _build_host_harness(tmp_path, monkeypatch)
    root = harness.profile.evidence_root
    with pytest.raises(HostBoundaryEvidenceError, match="regular file"):
        harness.verifier.load(root / "missing.json")

    directory = root / "directory.json"
    directory.mkdir()
    with pytest.raises(HostBoundaryEvidenceError, match="regular file"):
        harness.verifier.load(directory)

    invalid = root / "invalid.json"
    invalid.write_text("{", encoding="utf-8")
    with pytest.raises(HostBoundaryEvidenceError, match="strict JSON"):
        harness.verifier.load(invalid)

    array = root / "array.json"
    array.write_bytes(canonicalize_json(cast(JsonValue, [])))
    with pytest.raises(HostBoundaryEvidenceError, match="JSON object"):
        harness.verifier.load(array)

    noncanonical = root / "noncanonical.json"
    noncanonical.write_text(
        json.dumps(harness.evidence.record, indent=2), encoding="utf-8"
    )
    with pytest.raises(HostBoundaryEvidenceError, match="not canonical"):
        harness.verifier.load(noncanonical)

    report_directory = root / "report-directory.json"
    report_directory.mkdir()
    with pytest.raises(HostBoundaryEvidenceError, match="regular file"):
        harness.verifier.finalize_live_report(
            report_directory, root / "unused-evidence.json"
        )
    invalid_report = root / "invalid-report.json"
    invalid_report.write_text("{", encoding="utf-8")
    with pytest.raises(HostBoundaryEvidenceError, match="strict JSON"):
        harness.verifier.finalize_live_report(
            invalid_report, root / "unused-evidence.json"
        )
    report = _live_report(harness.profile)
    report["research_identity"] = "other"
    identity_report = root / "identity-report.json"
    identity_report.write_text(json.dumps(report), encoding="utf-8")
    with pytest.raises(HostBoundaryEvidenceError, match="identities"):
        harness.verifier.finalize_live_report(
            identity_report, root / "unused-evidence.json"
        )


def test_verified_host_release_rejects_retained_event_substitutions(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The typed release object independently checks mode, fields, root and reference."""
    harness = _build_host_harness(tmp_path, monkeypatch)
    released = harness.service.authorize_release(
        harness.request, expected_ledger_head=None
    )
    module = cast(Any, windows_host)
    release_type = cast(Any, VerifiedHostReleaseEvidence)
    original_event = cast(Any, released)._event

    changed_record = deepcopy(original_event.record)
    changed_record["reason"] = "Changed after construction."
    changed_event = ExposureLedgerEvent(
        original_event.sequence,
        original_event.path,
        original_event.digest,
        changed_record,
    )
    changed = release_type(
        harness.release.ledger,
        harness.release.lifecycle.object_store,
        changed_event,
        harness.evidence,
        _token=module._RELEASE_TOKEN,
    )
    with pytest.raises(ExposureLedgerIntegrityError, match="changed"):
        changed.verify()

    def evidence_for(record: JsonRecord, store: ImmutableObjectStore) -> Any:
        record["event_digest"] = release_event_digest(record)
        event = ExposureLedgerEvent(
            1, original_event.path, cast(str, record["event_digest"]), record
        )
        ledger = SimpleNamespace(get_verified=lambda digest: event)
        return release_type(
            ledger,
            store,
            event,
            harness.evidence,
            _token=module._RELEASE_TOKEN,
        )

    wrong_mode = deepcopy(original_event.record)
    wrong_mode["enforcement_mode"] = "SYNTHETIC_TEST"
    with pytest.raises(WindowsHostBoundaryError, match="host-enforced"):
        evidence_for(wrong_mode, harness.release.lifecycle.object_store).verify()

    malformed = deepcopy(original_event.record)
    malformed["released_artifact_reference"] = cast(JsonValue, 1)
    with pytest.raises(WindowsHostBoundaryError, match="malformed"):
        evidence_for(malformed, harness.release.lifecycle.object_store).verify()

    wrong_root = ImmutableObjectStore((tmp_path / "other-store").resolve())
    with pytest.raises(HostBoundaryEvidenceError, match="object store"):
        evidence_for(deepcopy(original_event.record), wrong_root).verify()

    wrong_reference = deepcopy(original_event.record)
    wrong_reference["released_artifact_reference"] = "objects/sha256/00/" + "0" * 64
    with pytest.raises(WindowsHostBoundaryError, match="reference mismatch"):
        evidence_for(wrong_reference, harness.release.lifecycle.object_store).verify()

    for invalid_text in ("", "Authorization: Bearer synthetic-hidden"):
        request = replace(harness.request, reason=invalid_text)
        with pytest.raises(WindowsHostBoundaryError) as captured:
            harness.service.authorize_release(
                request, expected_ledger_head=released.event_digest
            )
        assert "synthetic-hidden" not in str(captured.value)
