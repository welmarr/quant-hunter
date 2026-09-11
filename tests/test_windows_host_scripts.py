"""Static safety contracts for the inert-by-default Item 10B host scripts."""

from __future__ import annotations

import json
import re
import shutil
import subprocess
from pathlib import Path
from typing import cast

import pytest

ROOT = Path(__file__).parents[1]
SCRIPT_DIRECTORY = ROOT / "scripts" / "windows"
SCRIPTS = {
    path.name: path.read_text(encoding="utf-8")
    for path in sorted(SCRIPT_DIRECTORY.glob("item10b_*.ps1"))
}


def test_item10b_script_set_is_complete_and_has_no_personal_paths() -> None:
    """The bounded workflow ships every reviewed step without machine paths."""
    assert set(SCRIPTS) == {
        "item10b_acl_evidence.ps1",
        "item10b_identity_probe.ps1",
        "item10b_audit_evidence.ps1",
        "item10b_preflight.ps1",
        "item10b_rollback.ps1",
        "item10b_setup.ps1",
        "item10b_verify.ps1",
    }
    assert (SCRIPT_DIRECTORY / "item10b_finalize.py").is_file()
    for source in SCRIPTS.values():
        assert re.search(r"(?i)[A-Z]:\\Users\\", source) is None
        assert "d:\\quant-hunter" not in source.casefold()


@pytest.mark.parametrize(
    "forbidden",
    [
        "Enable-BitLocker",
        "Disable-BitLocker",
        "Suspend-BitLocker",
        "Resume-BitLocker",
        "Add-BitLockerKeyProtector",
        "Remove-BitLockerKeyProtector",
        "manage-bde -on",
        "manage-bde -off",
        "manage-bde -pause",
    ],
)
def test_scripts_contain_no_encryption_mutation(forbidden: str) -> None:
    """Item 10B can inspect an existing encrypted volume but cannot alter it."""
    assert all(
        forbidden.casefold() not in source.casefold() for source in SCRIPTS.values()
    )


def test_identity_secrets_remain_in_secure_objects_and_off_command_lines() -> None:
    """Generated authentication material is never printed, serialized, or passed."""
    setup = SCRIPTS["item10b_setup.ps1"]
    verify = SCRIPTS["item10b_verify.ps1"]
    combined = "\n".join(SCRIPTS.values())
    assert "RandomNumberGenerator" in setup
    assert "SecureString" in setup
    assert "PSCredential" in verify
    assert "ConvertFrom-SecureString" not in combined
    assert "net user" not in combined.casefold()
    assert "cmdkey" not in combined.casefold()
    assert "Write-Host" not in combined
    assert "-ArgumentList $CustodianPassword" not in verify
    assert "-ArgumentList $ResearchPassword" not in verify


def test_setup_and_rollback_are_explicitly_inert_without_apply() -> None:
    """Host writes require the caller's explicit Apply switch and preflight."""
    setup = SCRIPTS["item10b_setup.ps1"]
    rollback = SCRIPTS["item10b_rollback.ps1"]
    assert "[switch]$Apply" in setup
    assert "if (-not $Apply)" in setup
    assert "item10b_preflight.ps1" in setup
    assert setup.index("item10b_preflight.ps1") < setup.index("New-LocalUser")
    assert "[switch]$Apply" in rollback
    assert "if (-not $Apply)" in rollback
    assert "Remove-Item -LiteralPath $root -Recurse -Force" in rollback
    assert "Remove-Item *" not in rollback


def test_preflight_is_read_only_and_host_mutations_are_not_in_ci() -> None:
    """The preflight cannot create accounts, paths, ACLs, or policy changes."""
    preflight = SCRIPTS["item10b_preflight.ps1"]
    for command in (
        "New-LocalUser",
        "Remove-LocalUser",
        "New-Item",
        "Set-Acl",
        "Remove-Item",
        "auditpol.exe' /set",
        "Enable-BitLocker",
    ):
        assert command not in preflight
    workflows = "\n".join(
        path.read_text(encoding="utf-8")
        for path in (ROOT / ".github" / "workflows").glob("*.yml")
    )
    assert "item10b_setup.ps1" not in workflows
    assert "item10b_rollback.ps1" not in workflows


def test_setup_uses_allow_list_acls_auditing_and_disables_test_logons() -> None:
    """The setup script encodes the required least-privilege evidence flow."""
    setup = SCRIPTS["item10b_setup.ps1"]
    verify = SCRIPTS["item10b_verify.ps1"]
    assert "SetAccessRuleProtection($true, $false)" in setup
    assert "S-1-5-18" in setup
    assert "S-1-5-32-544" in setup
    assert "qh-oos-custodian" in setup
    assert "qh-research" in setup
    assert "ReadAndExecute" in setup
    assert "SetAuditRuleProtection($true, $false)" in setup
    assert "/subcategory:'File System' /success:enable /failure:enable" in setup
    assert "NotContentIndexed" in setup
    assert "Disable-LocalUser -Name 'qh-oos-custodian'" in setup
    assert "Disable-LocalUser -Name 'qh-research'" in setup
    assert "Get-WinEvent" in verify
    assert "research_denial_observed" in verify
    assert "[Security.AccessControl.AuditFlags]::Failure" in setup
    assert "[Security.AccessControl.AuditFlags]::Success" in setup


def test_acl_authority_uses_actual_local_sids_and_exact_sid_verification() -> None:
    """ACL construction and verification never depend on local-name translation."""
    setup = SCRIPTS["item10b_setup.ps1"]
    verify = SCRIPTS["item10b_verify.ps1"]
    assert "$custodianUser = Get-GovernedLocalUser 'qh-oos-custodian'" in setup
    assert "$researchUser = Get-GovernedLocalUser 'qh-research'" in setup
    assert "$custodianSid = $custodianUser.SID" in setup
    assert "$researchSid = $researchUser.SID" in setup
    assert "New-AllowRule $CustodianSid" in setup
    assert "New-AllowRule $ResearchSid" in setup
    assert "$ResearchSid, $failureRights" in setup
    assert "$CustodianSid," in setup
    assert "[Security.Principal.SecurityIdentifier]$CustodianSid" in verify
    assert "[Security.Principal.SecurityIdentifier]$ResearchSid" in verify
    assert "GetAccessRules(" in verify
    assert "GetAuditRules(" in verify
    assert "item10b_acl_evidence.ps1" in verify
    assert ".Value.Equals(" in SCRIPTS["item10b_acl_evidence.ps1"]
    assert "-match '\\\\qh-research$'" not in verify
    assert "'.\\qh-oos-custodian'" not in setup + verify
    assert "'.\\qh-research'" not in setup + verify


def test_local_login_identity_is_machine_qualified_but_not_persisted() -> None:
    """Effective logon uses the runtime machine authority only inside the probe."""
    verify = SCRIPTS["item10b_verify.ps1"]
    assert "$machineName = [Environment]::MachineName" in verify
    assert '"$machineName\\qh-oos-custodian"' in verify
    assert '"$machineName\\qh-research"' in verify
    assert "$machineName" not in verify.split("$result = [ordered]@", maxsplit=1)[1]
    assert all("50UL" not in source for source in SCRIPTS.values())


def test_elevated_verifier_captures_probe_output_without_evidence_write_grant() -> None:
    """The research child reports through stdout, which the verifier redirects."""
    probe = SCRIPTS["item10b_identity_probe.ps1"]
    verify = SCRIPTS["item10b_verify.ps1"]
    setup = SCRIPTS["item10b_setup.ps1"]
    assert "[Console]::Out.WriteLine" in probe
    assert "[string]$OutputPath" not in probe
    assert "-RedirectStandardOutput $OutputPath" in verify
    assert "-OutputPath', $OutputPath" not in verify
    assert "Set-GovernedDacl $evidence $custodianSid $researchSid $false" in setup


def test_setup_failure_phases_are_bounded_and_rollback_remains_exact() -> None:
    """Safe diagnostics do not weaken the proven marker-bound rollback."""
    setup = SCRIPTS["item10b_setup.ps1"]
    rollback = SCRIPTS["item10b_rollback.ps1"]
    for phase in (
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
    ):
        assert f"$phase = '{phase}'" in setup
    assert "ITEM10B_SETUP_FAILED" in setup
    assert "ConvertTo-SafeSetupDiagnostic" in setup
    execution_try = setup.index("$researchPassword = $null\ntry {")
    assert execution_try < setup.index("$preflight = & $preflightScript")
    assert "recovery(?:[-_ ]?(?:key|password))" in setup
    assert "Write-SafeSetupFailure $failurePhase $failureRecord" in setup
    assert setup.index("& $rollbackScript -StatePath $statePath -Apply") < setup.index(
        "Write-SafeSetupFailure $failurePhase $failureRecord"
    )
    assert "QUANT_HUNTER_ITEM10B_SYNTHETIC_BOUNDARY" in rollback
    assert "audit_success_before" in rollback
    assert "audit_failure_before" in rollback
    assert "Remove-LocalUser -Name $name" in rollback
    assert "Remove-Item -LiteralPath $root -Recurse -Force" in rollback
    assert "Enable-BitLocker" not in rollback


def test_verifier_uses_failure_4656_and_success_4663_metadata() -> None:
    """The live query and the configured SACLs use matching audit semantics."""
    verify = SCRIPTS["item10b_verify.ps1"]
    audit_logic = SCRIPTS["item10b_audit_evidence.ps1"]
    assert "Id = @(4656, 4663)" in verify
    assert "StartTime = $startedAt" in verify
    assert "EndTime = $endedAt" in verify
    assert "ConvertTo-Item10bNormalizedAuditEvent" in verify
    assert ".Message" not in verify
    assert "event_id -eq 4656" in audit_logic
    assert "$isFailure" in audit_logic
    assert "event_id -eq 4663" in audit_logic
    assert "$isSuccess" in audit_logic


def test_audit_target_matching_uses_no_filesystem_provider() -> None:
    """Windows ObjectName evidence stays independent of the executing host."""
    audit_logic = SCRIPTS["item10b_audit_evidence.ps1"]
    for provider_command in ("Join-Path", "Resolve-Path", "Test-Path", "Get-Item"):
        assert provider_command not in audit_logic
    assert "Join-Item10bAuditTarget" in audit_logic
    assert r"D:\QuantHunterOOS\vault" == VAULT


def test_cli_cannot_promote_an_arbitrary_json_report() -> None:
    """The only CLI path delegates to the governed live capture operation."""
    finalizer = (SCRIPT_DIRECTORY / "item10b_finalize.py").read_text(encoding="utf-8")
    assert "--live-report" not in finalizer
    assert "finalize_live_report" not in finalizer
    assert "--authorize-setup" in finalizer
    assert ".capture_live_evidence(" in finalizer


def test_preflight_observations_flow_into_the_same_verification_result() -> None:
    """Host facts are observed by preflight instead of asserted by verification."""
    preflight = SCRIPTS["item10b_preflight.ps1"]
    setup = SCRIPTS["item10b_setup.ps1"]
    verify = SCRIPTS["item10b_verify.ps1"]
    for observation in (
        "RepositoryWorktreeExcluded",
        "ProfileCacheTempExcluded",
        "SyncOverlapDetected",
        "GovernedIdentitiesAbsent",
        "CandidatePathAbsent",
        "AuditFileSystem",
        "BackupObservation",
        "BackupStatus",
    ):
        assert observation in preflight
        assert observation in verify
    assert "-PreflightResult $preflight" in setup
    assert "preflight_observations" in verify
    assert "filesystem = 'NTFS'" not in verify
    assert "fixed_local_volume = $true" not in verify
    assert "protection_status = 'ON'" not in verify
    assert "volume_status = 'FULLY_ENCRYPTED'" not in verify
    assert "sync_overlap_detected = $false" not in verify
    assert "backup_status = 'RESIDUAL_RISK_RETAINED'" not in verify
    assert "item10b-live-report.json" not in setup


PWSH = shutil.which("pwsh.exe") or shutil.which("pwsh")
ACL_LOGIC = SCRIPT_DIRECTORY / "item10b_acl_evidence.ps1"
ACL_HARNESS = ROOT / "tests" / "helpers" / "item10b_acl_logic_harness.ps1"
AUDIT_LOGIC = SCRIPT_DIRECTORY / "item10b_audit_evidence.ps1"
AUDIT_HARNESS = ROOT / "tests" / "helpers" / "item10b_audit_logic_harness.ps1"
WINDOW_START = "2026-09-11T06:00:00Z"
WINDOW_END = "2026-09-11T06:01:00Z"
EVENT_TIME = "2026-09-11T06:00:30Z"
VAULT = r"D:\QuantHunterOOS\vault"
SEALED_FIXTURE = VAULT + r"\synthetic-sealed-fixture.txt"
RELEASED_FIXTURE = r"D:\QuantHunterOOS\releases\synthetic-released-fixture.txt"
AUDIT_FAILURE = "0x8010000000000000"
AUDIT_SUCCESS = "0x8020000000000000"


def test_acl_logic_rejects_same_name_with_different_sid(tmp_path: Path) -> None:
    """A display-name collision cannot satisfy exact SID authority."""
    if PWSH is None:
        pytest.skip("PowerShell 7 is unavailable")
    output = tmp_path / "acl-result.json"
    error = tmp_path / "acl-error.txt"
    with (
        output.open("w", encoding="utf-8") as stdout,
        error.open("w", encoding="utf-8") as stderr,
    ):
        completed = subprocess.run(  # noqa: S603 - resolved local PowerShell binary
            [
                PWSH,
                "-NoLogo",
                "-NoProfile",
                "-NonInteractive",
                "-File",
                str(ACL_HARNESS),
                "-AclScriptPath",
                str(ACL_LOGIC),
            ],
            check=False,
            stdout=stdout,
            stderr=stderr,
            text=True,
            timeout=30,
        )
    assert completed.returncode == 0, error.read_text(encoding="utf-8")
    result = json.loads(output.read_text(encoding="utf-8"))
    assert result == {
        "expected_sid_accepted": True,
        "same_name_wrong_sid_rejected": True,
        "wrong_rights_rejected": True,
        "wrong_audit_outcome_rejected": True,
    }


def _audit_event(
    event_id: int,
    keywords: str,
    account_name: str,
    object_name: str,
    *,
    occurred_at: str = EVENT_TIME,
) -> dict[str, object]:
    return {
        "event_id": event_id,
        "occurred_at": occurred_at,
        "account_name": account_name,
        "object_name": object_name,
        "keywords": keywords,
    }


AUDIT_SCENARIOS = {
    "valid": [
        _audit_event(4656, AUDIT_FAILURE, "HOST\\qh-research", SEALED_FIXTURE),
        _audit_event(
            4663,
            AUDIT_SUCCESS,
            "HOST\\qh-oos-custodian",
            RELEASED_FIXTURE,
        ),
    ],
    "research_4663_failure": [
        _audit_event(4663, AUDIT_FAILURE, "qh-research", SEALED_FIXTURE)
    ],
    "research_4656_success": [
        _audit_event(4656, AUDIT_SUCCESS, "qh-research", SEALED_FIXTURE)
    ],
    "research_wrong_identity": [
        _audit_event(4656, AUDIT_FAILURE, "other-identity", SEALED_FIXTURE)
    ],
    "research_wrong_object": [
        _audit_event(
            4656,
            AUDIT_FAILURE,
            "qh-research",
            r"D:\unrelated\object.txt",
        )
    ],
    "custodian_4663_failure": [
        _audit_event(4663, AUDIT_FAILURE, "qh-oos-custodian", RELEASED_FIXTURE)
    ],
    "custodian_4656_success": [
        _audit_event(4656, AUDIT_SUCCESS, "qh-oos-custodian", RELEASED_FIXTURE)
    ],
    "custodian_wrong_object": [
        _audit_event(
            4663,
            AUDIT_SUCCESS,
            "qh-oos-custodian",
            r"D:\unrelated\object.txt",
        )
    ],
    "stale": [
        _audit_event(
            4656,
            AUDIT_FAILURE,
            "qh-research",
            SEALED_FIXTURE,
            occurred_at="2026-09-11T05:59:59Z",
        ),
        _audit_event(
            4663,
            AUDIT_SUCCESS,
            "qh-oos-custodian",
            RELEASED_FIXTURE,
            occurred_at="2026-09-11T06:01:01Z",
        ),
    ],
}


@pytest.fixture(scope="module")
def audit_scenario_results(
    tmp_path_factory: pytest.TempPathFactory,
) -> dict[str, dict[str, bool]]:
    if PWSH is None:
        pytest.skip("PowerShell 7 is unavailable")
    audit_directory = tmp_path_factory.mktemp("item10b-audit")
    fixture = audit_directory / "scenarios.json"
    output = audit_directory / "result.json"
    error = audit_directory / "error.txt"
    fixture.write_text(json.dumps(AUDIT_SCENARIOS), encoding="utf-8")
    with (
        output.open("w", encoding="utf-8") as stdout,
        error.open("w", encoding="utf-8") as stderr,
    ):
        completed = subprocess.run(  # noqa: S603 - resolved local PowerShell binary
            [
                PWSH,
                "-NoLogo",
                "-NoProfile",
                "-NonInteractive",
                "-File",
                str(AUDIT_HARNESS),
                "-AuditScriptPath",
                str(AUDIT_LOGIC),
                "-FixturePath",
                str(fixture),
                "-WindowStart",
                WINDOW_START,
                "-WindowEnd",
                WINDOW_END,
                "-VaultPath",
                VAULT,
                "-SealedFixturePath",
                SEALED_FIXTURE,
                "-ReleasedPath",
                RELEASED_FIXTURE,
            ],
            check=False,
            stdout=stdout,
            stderr=stderr,
            text=True,
            timeout=30,
        )
    assert completed.returncode == 0, error.read_text(encoding="utf-8")
    return cast(
        dict[str, dict[str, bool]], json.loads(output.read_text(encoding="utf-8"))
    )


def test_audit_logic_accepts_bound_denial_and_custodian_success(
    audit_scenario_results: dict[str, dict[str, bool]],
) -> None:
    """The two roles require their distinct, correctly classified audit events."""
    result = audit_scenario_results["valid"]
    assert result == {
        "research_denial_observed": True,
        "custodian_activity_observed": True,
    }


@pytest.mark.parametrize(
    "scenario",
    [
        "research_4663_failure",
        "research_4656_success",
        "research_wrong_identity",
        "research_wrong_object",
    ],
)
def test_research_denial_rejects_wrong_id_outcome_identity_or_object(
    audit_scenario_results: dict[str, dict[str, bool]], scenario: str
) -> None:
    """An event's existence does not establish a denied research access."""
    result = audit_scenario_results[scenario]
    assert result["research_denial_observed"] is False


@pytest.mark.parametrize(
    "scenario",
    [
        "custodian_4663_failure",
        "custodian_4656_success",
        "custodian_wrong_object",
    ],
)
def test_custodian_activity_requires_bound_successful_4663(
    audit_scenario_results: dict[str, dict[str, bool]], scenario: str
) -> None:
    """Custodian authority requires successful performed-object activity."""
    result = audit_scenario_results[scenario]
    assert result["custodian_activity_observed"] is False


def test_audit_evidence_rejects_events_outside_verification_window(
    audit_scenario_results: dict[str, dict[str, bool]],
) -> None:
    """Stale otherwise-matching events cannot satisfy either evidence gate."""
    result = audit_scenario_results["stale"]
    assert result == {
        "research_denial_observed": False,
        "custodian_activity_observed": False,
    }
