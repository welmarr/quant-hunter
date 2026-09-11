"""Static safety contracts for the inert-by-default Item 10B host scripts."""

from __future__ import annotations

import re
from pathlib import Path

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
        "item10b_identity_probe.ps1",
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
    assert "NT AUTHORITY\\SYSTEM" in setup
    assert "BUILTIN\\Administrators" in setup
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
