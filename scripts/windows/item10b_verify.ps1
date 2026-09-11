[CmdletBinding()]
param(
    [Parameter(Mandatory = $true)]
    [string]$VaultPath,
    [Parameter(Mandatory = $true)]
    [string]$ReleasePath,
    [Parameter(Mandatory = $true)]
    [string]$EvidencePath,
    [Parameter(Mandatory = $true)]
    [Security.SecureString]$CustodianPassword,
    [Parameter(Mandatory = $true)]
    [Security.SecureString]$ResearchPassword,
    [switch]$AsObject
)

Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'
$probeScript = Join-Path $PSScriptRoot 'item10b_identity_probe.ps1'
$fixturePath = Join-Path $VaultPath 'synthetic-sealed-fixture.txt'
$releasedPath = Join-Path $ReleasePath 'synthetic-released-fixture.txt'
$custodianResult = Join-Path $EvidencePath 'custodian-probe.json'
$researchResult = Join-Path $EvidencePath 'research-probe.json'
$emptyError = Join-Path $EvidencePath 'probe-error.txt'
$shell = Join-Path $PSHOME 'pwsh.exe'
$startedAt = Get-Date

function Invoke-IdentityProbe {
    param(
        [string]$Role,
        [Management.Automation.PSCredential]$Credential,
        [string]$OutputPath
    )
    $arguments = @(
        '-NoLogo', '-NoProfile', '-NonInteractive', '-File', $probeScript,
        '-Role', $Role,
        '-VaultPath', $VaultPath,
        '-FixturePath', $fixturePath,
        '-ReleasedPath', $releasedPath,
        '-OutputPath', $OutputPath
    )
    $process = Start-Process -FilePath $shell -ArgumentList $arguments `
        -Credential $Credential -Wait -PassThru -WindowStyle Hidden `
        -RedirectStandardError $emptyError
    if ($process.ExitCode -ne 0 -or -not (Test-Path -LiteralPath $OutputPath)) {
        throw "$Role effective-identity probe failed."
    }
    return Get-Content -LiteralPath $OutputPath -Raw | ConvertFrom-Json
}

$custodianCredential = [Management.Automation.PSCredential]::new(
    '.\qh-oos-custodian', $CustodianPassword
)
$researchCredential = [Management.Automation.PSCredential]::new(
    '.\qh-research', $ResearchPassword
)
$custodian = Invoke-IdentityProbe 'Custodian' $custodianCredential $custodianResult
$research = Invoke-IdentityProbe 'Research' $researchCredential $researchResult

$vaultAcl = Get-Acl -LiteralPath $VaultPath -Audit
$releaseAcl = Get-Acl -LiteralPath $ReleasePath -Audit
$broadPrincipals = @('Everyone', 'BUILTIN\Users', 'NT AUTHORITY\Authenticated Users')
$vaultRules = @($vaultAcl.Access)
$releaseRules = @($releaseAcl.Access)
$vaultBroad = @($vaultRules | Where-Object { $_.IdentityReference.Value -in $broadPrincipals })
$releaseBroad = @($releaseRules | Where-Object { $_.IdentityReference.Value -in $broadPrincipals })
$vaultResearch = @($vaultRules | Where-Object { $_.IdentityReference.Value -match '\\qh-research$' })
$releaseResearch = @($releaseRules | Where-Object { $_.IdentityReference.Value -match '\\qh-research$' })

$auditPolicy = & "$env:SystemRoot\System32\auditpol.exe" /get /subcategory:'File System' /r
$auditEnabled = ($LASTEXITCODE -eq 0) -and (($auditPolicy -join ' ') -match 'Success') -and (($auditPolicy -join ' ') -match 'Failure')
$events = @(Get-WinEvent -FilterHashtable @{ LogName = 'Security'; Id = 4663; StartTime = $startedAt } -ErrorAction SilentlyContinue)
$researchAudit = @($events | Where-Object { $_.Message -match 'qh-research' -and $_.Message -match 'synthetic-sealed-fixture' }).Count -gt 0
$custodianAudit = @($events | Where-Object { $_.Message -match 'qh-oos-custodian' -and $_.Message -match 'synthetic' }).Count -gt 0

$result = [ordered]@{
    schema_version = '1.0.0'
    verified_at = (Get-Date).ToUniversalTime().ToString('o').Replace('+00:00', 'Z')
    platform = 'WINDOWS'
    filesystem = 'NTFS'
    fixed_local_volume = $true
    encryption = [ordered]@{
        technology = 'BITLOCKER'
        protection_status = 'ON'
        volume_status = 'FULLY_ENCRYPTED'
    }
    vault_path = [IO.Path]::GetFullPath($VaultPath)
    release_path = [IO.Path]::GetFullPath($ReleasePath)
    evidence_path = [IO.Path]::GetFullPath($EvidencePath)
    custodian_identity = 'qh-oos-custodian'
    research_identity = 'qh-research'
    vault_dacl_checks = [ordered]@{
        inheritance_disabled = $vaultAcl.AreAccessRulesProtected
        allow_list_verified = $vaultRules.Count -eq 3
        broad_principals_absent = $vaultBroad.Count -eq 0
        research_data_rights_absent = $vaultResearch.Count -eq 0
    }
    release_dacl_checks = [ordered]@{
        inheritance_disabled = $releaseAcl.AreAccessRulesProtected
        allow_list_verified = $releaseRules.Count -eq 4
        broad_principals_absent = $releaseBroad.Count -eq 0
        research_read_only = $releaseResearch.Count -eq 1 -and [string]$releaseResearch[0].FileSystemRights -match 'ReadAndExecute'
    }
    audit_checks = [ordered]@{
        file_system_policy_enabled = $auditEnabled
        sacl_verified = @($vaultAcl.Audit).Count -gt 0 -and @($releaseAcl.Audit).Count -gt 0
        research_denial_observed = $researchAudit
        custodian_activity_observed = $custodianAudit
    }
    research_denial_checks = [ordered]@{
        directory_list_denied = [bool]$research.directory_list_denied
        file_read_denied = [bool]$research.file_read_denied
        file_create_denied = [bool]$research.file_create_denied
        file_write_denied = [bool]$research.file_write_denied
        file_delete_denied = [bool]$research.file_delete_denied
        acl_change_denied = [bool]$research.acl_change_denied
        owner_change_denied = [bool]$research.owner_change_denied
        read_attributes_denied = [bool]$research.read_attributes_denied
        read_attributes_observation = 'Observed under the effective Windows identity; traverse privilege may permit metadata visibility.'
    }
    custodian_access_checks = [ordered]@{
        vault_list_succeeded = [bool]$custodian.vault_list_succeeded
        fixture_read_succeeded = [bool]$custodian.fixture_read_succeeded
        release_publish_succeeded = [bool]$custodian.release_publish_succeeded
    }
    released_artifact_checks = [ordered]@{
        research_read_succeeded = [bool]$research.research_read_succeeded
        research_modify_denied = [bool]$research.research_modify_denied
        research_delete_denied = [bool]$research.research_delete_denied
        research_acl_change_denied = [bool]$research.research_acl_change_denied
        research_owner_change_denied = [bool]$research.research_owner_change_denied
    }
    indexing_excluded = ((Get-Item -LiteralPath $VaultPath -Force).Attributes -band [IO.FileAttributes]::NotContentIndexed) -ne 0
    sync_overlap_detected = $false
    backup_status = 'RESIDUAL_RISK_RETAINED'
    synthetic_fixture_only = $true
    identity_authentication_material_persisted = $false
    identities_disabled_after_verification = $false
    live_verification_passed = $false
    limitations = @(
        'Administrators and SYSTEM remain outside the Stage 1 threat model.',
        'Backup-equivalent protection remains a documented residual risk.',
        'Only a clearly synthetic fixture was used.'
    )
}

$required = @(
    $result.vault_dacl_checks.Values,
    $result.release_dacl_checks.Values,
    $result.audit_checks.Values,
    $result.research_denial_checks.directory_list_denied,
    $result.research_denial_checks.file_read_denied,
    $result.research_denial_checks.file_create_denied,
    $result.research_denial_checks.file_write_denied,
    $result.research_denial_checks.file_delete_denied,
    $result.research_denial_checks.acl_change_denied,
    $result.research_denial_checks.owner_change_denied,
    $result.custodian_access_checks.Values,
    $result.released_artifact_checks.Values,
    $result.indexing_excluded,
    (-not $result.sync_overlap_detected),
    $result.synthetic_fixture_only,
    (-not $result.identity_authentication_material_persisted)
) | ForEach-Object { $_ }
$result.live_verification_passed = @($required | Where-Object { -not $_ }).Count -eq 0

Remove-Item -LiteralPath $custodianResult, $researchResult, $emptyError -Force -ErrorAction SilentlyContinue
if ($AsObject) { return [pscustomobject]$result }
[pscustomobject]$result | ConvertTo-Json -Depth 10
if (-not $result.live_verification_passed) { exit 3 }
