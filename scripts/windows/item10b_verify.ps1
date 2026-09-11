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
    [Parameter(Mandatory = $true)]
    [Security.Principal.SecurityIdentifier]$CustodianSid,
    [Parameter(Mandatory = $true)]
    [Security.Principal.SecurityIdentifier]$ResearchSid,
    [Parameter(Mandatory = $true)]
    [psobject]$PreflightResult,
    [switch]$AsObject
)

Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'
$probeScript = Join-Path $PSScriptRoot 'item10b_identity_probe.ps1'
$auditEvidenceScript = Join-Path $PSScriptRoot 'item10b_audit_evidence.ps1'
$aclEvidenceScript = Join-Path $PSScriptRoot 'item10b_acl_evidence.ps1'
. $auditEvidenceScript
. $aclEvidenceScript
$fixturePath = Join-Path $VaultPath 'synthetic-sealed-fixture.txt'
$releasedPath = Join-Path $ReleasePath 'synthetic-released-fixture.txt'
$custodianResult = Join-Path $EvidencePath 'custodian-probe.json'
$researchResult = Join-Path $EvidencePath 'research-probe.json'
$emptyError = Join-Path $EvidencePath 'probe-error.txt'
$shell = Join-Path $PSHOME 'pwsh.exe'
$startedAt = Get-Date
$candidateRoot = [IO.Path]::GetFullPath((Split-Path -Parent $VaultPath)).TrimEnd([IO.Path]::DirectorySeparatorChar)
if (-not [bool]$PreflightResult.Pass -or
    [IO.Path]::GetFullPath([string]$PreflightResult.CandidateRoot).TrimEnd([IO.Path]::DirectorySeparatorChar) -ne $candidateRoot) {
    throw 'Verification requires the exact successful preflight from this setup execution.'
}

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
        '-ReleasedPath', $releasedPath
    )
    $process = Start-Process -FilePath $shell -ArgumentList $arguments `
        -Credential $Credential -Wait -PassThru -WindowStyle Hidden `
        -RedirectStandardOutput $OutputPath `
        -RedirectStandardError $emptyError
    if ($process.ExitCode -ne 0 -or -not (Test-Path -LiteralPath $OutputPath)) {
        throw "$Role effective-identity probe failed."
    }
    return Get-Content -LiteralPath $OutputPath -Raw | ConvertFrom-Json
}

function Assert-GovernedLocalSid {
    param(
        [string]$Name,
        [Security.Principal.SecurityIdentifier]$ExpectedSid
    )

    $user = Get-LocalUser -Name $Name -ErrorAction Stop
    if ($null -eq $user -or
        $null -eq $user.SID -or
        -not ($user.SID -is [Security.Principal.SecurityIdentifier]) -or
        -not $user.SID.Value.Equals(
            $ExpectedSid.Value,
            [StringComparison]::OrdinalIgnoreCase
        ) -or
        -not $user.Enabled) {
        throw 'The governed local identity does not match its expected SID authority.'
    }
}

$machineName = [Environment]::MachineName
if ([string]::IsNullOrWhiteSpace($machineName)) {
    throw 'The local machine name is unavailable for effective identity probes.'
}
Assert-GovernedLocalSid 'qh-oos-custodian' $CustodianSid
Assert-GovernedLocalSid 'qh-research' $ResearchSid
$custodianCredential = [Management.Automation.PSCredential]::new(
    "$machineName\qh-oos-custodian", $CustodianPassword
)
$researchCredential = [Management.Automation.PSCredential]::new(
    "$machineName\qh-research", $ResearchPassword
)
$custodian = Invoke-IdentityProbe 'Custodian' $custodianCredential $custodianResult
$research = Invoke-IdentityProbe 'Research' $researchCredential $researchResult

$vaultAcl = Get-Acl -LiteralPath $VaultPath -Audit
$releaseAcl = Get-Acl -LiteralPath $ReleasePath -Audit
$systemSid = [Security.Principal.SecurityIdentifier]::new('S-1-5-18')
$administratorsSid = [Security.Principal.SecurityIdentifier]::new('S-1-5-32-544')
$broadSidValues = @('S-1-1-0', 'S-1-5-11', 'S-1-5-32-545')
$vaultRules = @($vaultAcl.GetAccessRules(
    $true, $true, [Security.Principal.SecurityIdentifier]
))
$releaseRules = @($releaseAcl.GetAccessRules(
    $true, $true, [Security.Principal.SecurityIdentifier]
))
$vaultAuditRules = @($vaultAcl.GetAuditRules(
    $true, $true, [Security.Principal.SecurityIdentifier]
))
$releaseAuditRules = @($releaseAcl.GetAuditRules(
    $true, $true, [Security.Principal.SecurityIdentifier]
))
$vaultBroad = @($vaultRules | Where-Object { $_.IdentityReference.Value -in $broadSidValues })
$releaseBroad = @($releaseRules | Where-Object { $_.IdentityReference.Value -in $broadSidValues })
$vaultResearch = @($vaultRules | Where-Object {
    $_.IdentityReference.Value.Equals($ResearchSid.Value, [StringComparison]::OrdinalIgnoreCase)
})
$releaseResearch = @($releaseRules | Where-Object {
    $_.IdentityReference.Value.Equals($ResearchSid.Value, [StringComparison]::OrdinalIgnoreCase)
})
$failureRights = [Security.AccessControl.FileSystemRights]'ListDirectory, ReadData, WriteData, AppendData, Delete, ChangePermissions, TakeOwnership'
$custodianAuditRights = [Security.AccessControl.FileSystemRights]'ReadAndExecute, WriteData, AppendData'
$saclVerified = $vaultAuditRules.Count -eq 2 -and
    $releaseAuditRules.Count -eq 2 -and
    (Test-Item10bExactAuditRule $vaultAuditRules $ResearchSid $failureRights 'Failure') -and
    (Test-Item10bExactAuditRule $vaultAuditRules $CustodianSid $custodianAuditRights 'Success') -and
    (Test-Item10bExactAuditRule $releaseAuditRules $ResearchSid $failureRights 'Failure') -and
    (Test-Item10bExactAuditRule $releaseAuditRules $CustodianSid $custodianAuditRights 'Success')

$auditPolicy = & "$env:SystemRoot\System32\auditpol.exe" /get /subcategory:'File System' /r
$auditEnabled = ($LASTEXITCODE -eq 0) -and (($auditPolicy -join ' ') -match 'Success') -and (($auditPolicy -join ' ') -match 'Failure')
$endedAt = Get-Date
$eventRecords = @(Get-WinEvent -FilterHashtable @{
    LogName = 'Security'
    Id = @(4656, 4663)
    StartTime = $startedAt
    EndTime = $endedAt
} -ErrorAction SilentlyContinue)
$normalizedEvents = @($eventRecords | ConvertTo-Item10bNormalizedAuditEvent)
$auditEvidence = Test-Item10bAuditEvidence -Events $normalizedEvents `
    -WindowStart $startedAt -WindowEnd $endedAt -VaultPath $VaultPath `
    -FixturePath $fixturePath -ReleasedPath $releasedPath
$researchAudit = [bool]$auditEvidence.research_denial_observed
$custodianAudit = [bool]$auditEvidence.custodian_activity_observed

$result = [ordered]@{
    schema_version = '1.0.0'
    verified_at = (Get-Date).ToUniversalTime().ToString('o').Replace('+00:00', 'Z')
    platform = 'WINDOWS'
    preflight_observations = [ordered]@{
        preflight_passed = [bool]$PreflightResult.Pass
        candidate_root = [string]$PreflightResult.CandidateRoot
        filesystem = [string]$PreflightResult.CandidateFilesystem
        fixed_local_volume = [bool]$PreflightResult.FixedLocalVolume
        encryption = [ordered]@{
            technology = 'BITLOCKER'
            protection_status = [string]$PreflightResult.BitLockerProtectionStatus
            volume_status = [string]$PreflightResult.BitLockerVolumeStatus
        }
        repository_worktree_excluded = [bool]$PreflightResult.RepositoryWorktreeExcluded
        profile_cache_temp_excluded = [bool]$PreflightResult.ProfileCacheTempExcluded
        sync_overlap_detected = [bool]$PreflightResult.SyncOverlapDetected
        governed_identities_absent = [bool]$PreflightResult.GovernedIdentitiesAbsent
        candidate_path_absent = [bool]$PreflightResult.CandidatePathAbsent
        original_file_system_audit_policy = [ordered]@{
            success_enabled = [bool]$PreflightResult.AuditFileSystem.Success
            failure_enabled = [bool]$PreflightResult.AuditFileSystem.Failure
        }
        backup_observation = [string]$PreflightResult.BackupObservation
        backup_status = [string]$PreflightResult.BackupStatus
    }
    vault_path = [IO.Path]::GetFullPath($VaultPath)
    release_path = [IO.Path]::GetFullPath($ReleasePath)
    evidence_path = [IO.Path]::GetFullPath($EvidencePath)
    custodian_identity = 'qh-oos-custodian'
    research_identity = 'qh-research'
    vault_dacl_checks = [ordered]@{
        inheritance_disabled = $vaultAcl.AreAccessRulesProtected
        allow_list_verified = (Test-Item10bExactSidSet $vaultRules @(
            $systemSid.Value, $administratorsSid.Value, $CustodianSid.Value
        )) -and
            (Test-Item10bExactAccessRule $vaultRules $systemSid 'FullControl') -and
            (Test-Item10bExactAccessRule $vaultRules $administratorsSid 'FullControl') -and
            (Test-Item10bExactAccessRule $vaultRules $CustodianSid 'Modify')
        broad_principals_absent = $vaultBroad.Count -eq 0
        research_data_rights_absent = $vaultResearch.Count -eq 0
    }
    release_dacl_checks = [ordered]@{
        inheritance_disabled = $releaseAcl.AreAccessRulesProtected
        allow_list_verified = (Test-Item10bExactSidSet $releaseRules @(
            $systemSid.Value, $administratorsSid.Value,
            $CustodianSid.Value, $ResearchSid.Value
        )) -and
            (Test-Item10bExactAccessRule $releaseRules $systemSid 'FullControl') -and
            (Test-Item10bExactAccessRule $releaseRules $administratorsSid 'FullControl') -and
            (Test-Item10bExactAccessRule $releaseRules $CustodianSid 'Modify')
        broad_principals_absent = $releaseBroad.Count -eq 0
        research_read_only = $releaseResearch.Count -eq 1 -and
            (Test-Item10bExactAccessRule $releaseRules $ResearchSid 'ReadAndExecute')
    }
    audit_checks = [ordered]@{
        file_system_policy_enabled = $auditEnabled
        sacl_verified = $saclVerified
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
    $result.preflight_observations.preflight_passed,
    $result.preflight_observations.filesystem -eq 'NTFS',
    $result.preflight_observations.fixed_local_volume,
    $result.preflight_observations.encryption.protection_status -eq 'On',
    $result.preflight_observations.encryption.volume_status -eq 'FullyEncrypted',
    $result.preflight_observations.repository_worktree_excluded,
    $result.preflight_observations.profile_cache_temp_excluded,
    (-not $result.preflight_observations.sync_overlap_detected),
    $result.preflight_observations.governed_identities_absent,
    $result.preflight_observations.candidate_path_absent,
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
    $result.synthetic_fixture_only,
    (-not $result.identity_authentication_material_persisted)
) | ForEach-Object { $_ }
$result.live_verification_passed = @($required | Where-Object { -not $_ }).Count -eq 0

Remove-Item -LiteralPath $custodianResult, $researchResult, $emptyError -Force -ErrorAction SilentlyContinue
if ($AsObject) { return [pscustomobject]$result }
[pscustomobject]$result | ConvertTo-Json -Depth 10
if (-not $result.live_verification_passed) { exit 3 }
