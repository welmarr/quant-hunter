[CmdletBinding(SupportsShouldProcess = $true, ConfirmImpact = 'High')]
param(
    [Parameter(Mandatory = $true)]
    [string]$RepositoryRoot,
    [Parameter(Mandatory = $true)]
    [string]$CandidateRoot,
    [switch]$Apply
)

Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'
$phase = 'PREFLIGHT'
if (-not $Apply) {
    throw 'Host setup is inert unless -Apply is supplied explicitly.'
}

$preflightScript = Join-Path $PSScriptRoot 'item10b_preflight.ps1'
$verifyScript = Join-Path $PSScriptRoot 'item10b_verify.ps1'
$rollbackScript = Join-Path $PSScriptRoot 'item10b_rollback.ps1'
$root = [IO.Path]::GetFullPath($CandidateRoot).TrimEnd([IO.Path]::DirectorySeparatorChar)
$vault = Join-Path $root 'vault'
$releases = Join-Path $root 'releases'
$evidence = Join-Path $root 'host-evidence'
$statePath = Join-Path $evidence 'item10b-created-state.json'
$fixturePath = Join-Path $vault 'synthetic-sealed-fixture.txt'
$marker = 'QUANT_HUNTER_ITEM10B_SYNTHETIC_BOUNDARY'
$createdUsers = [Collections.Generic.List[string]]::new()
$createdRoot = $false
$systemSid = [Security.Principal.SecurityIdentifier]::new('S-1-5-18')
$administratorsSid = [Security.Principal.SecurityIdentifier]::new('S-1-5-32-544')
$custodianSid = $null
$researchSid = $null

function ConvertTo-SafeSetupDiagnostic {
    param([AllowEmptyString()][string]$Text, [int]$MaximumLength)

    $safe = [regex]::Replace($Text, '\x1B\[[0-?]*[ -/]*[@-~]', '')
    foreach ($pattern in @(
        '(?im)(authorization\s*[:=]\s*)[^\r\n]+',
        '(?im)(cookie\s*[:=]\s*)[^\r\n]+',
        '(?i)((?:bitlocker\s+)?recovery(?:[-_ ]?(?:key|password))\s*(?:=|:|\s)\s*)(\S+)',
        '(?i)((?:--)(?:api[-_]?key|token|password|secret)\s*(?:=|\s)\s*)(\S+)',
        '(?i)((?:api[-_]?key|token|password|secret)\s*(?:=|:)\s*)(\S+)',
        '(?i)(bearer\s+)(\S+)'
    )) {
        $safe = [regex]::Replace($safe, $pattern, '$1[REDACTED]')
    }
    $safe = [regex]::Replace($safe, '[\r\n\t]+', ' ').Trim()
    if ([string]::IsNullOrWhiteSpace($safe)) {
        return 'No safe reason was available.'
    }
    if ($safe.Length -gt $MaximumLength) {
        return $safe.Substring(0, $MaximumLength)
    }
    return $safe
}

function Write-SafeSetupFailure {
    param([string]$FailurePhase, [Management.Automation.ErrorRecord]$ErrorRecord)

    $safePhase = [regex]::Replace($FailurePhase, '[^A-Z_]', '')
    if ([string]::IsNullOrWhiteSpace($safePhase)) { $safePhase = 'UNKNOWN' }
    $exceptionType = [regex]::Replace(
        $ErrorRecord.Exception.GetType().FullName,
        '[^A-Za-z0-9_.+]',
        ''
    )
    if ($exceptionType.Length -gt 120) {
        $exceptionType = $exceptionType.Substring(0, 120)
    }
    $reason = ConvertTo-SafeSetupDiagnostic $ErrorRecord.Exception.Message 240
    [Console]::Error.WriteLine('ITEM10B_SETUP_FAILED')
    [Console]::Error.WriteLine("phase=$safePhase")
    [Console]::Error.WriteLine("exception_type=$exceptionType")
    [Console]::Error.WriteLine("reason=$reason")
}

function Get-GovernedLocalUser {
    param([string]$Name)

    $user = Get-LocalUser -Name $Name -ErrorAction Stop
    if ($null -eq $user -or $user.Name -cne $Name) {
        throw 'The governed local account could not be resolved exactly.'
    }
    if ($null -eq $user.SID -or
        -not ($user.SID -is [Security.Principal.SecurityIdentifier])) {
        throw 'The governed local account has no valid SID authority.'
    }
    if ($null -ne $user.PrincipalSource -and
        [string]$user.PrincipalSource -ne 'Local') {
        throw 'The governed account is not local to this machine.'
    }
    if (-not $user.Enabled) {
        throw 'The governed local account is not enabled for effective verification.'
    }
    return $user
}

function Assert-UnprivilegedLocalUser {
    param([Security.Principal.SecurityIdentifier]$Sid)

    foreach ($groupSidValue in @('S-1-5-32-544', 'S-1-5-32-551', 'S-1-5-32-555')) {
        $groupSid = [Security.Principal.SecurityIdentifier]::new($groupSidValue)
        $group = Get-LocalGroup -SID $groupSid -ErrorAction SilentlyContinue
        if ($null -ne $group) {
            $isMember = @(Get-LocalGroupMember -Group $group -ErrorAction Stop |
                Where-Object { $null -ne $_.SID -and $_.SID.Value -eq $Sid.Value }).Count -gt 0
            if ($isMember) {
                throw 'A governed local account has a forbidden privileged membership.'
            }
        }
    }
}

function New-EphemeralPassword {
    $bytes = [byte[]]::new(48)
    [Security.Cryptography.RandomNumberGenerator]::Fill($bytes)
    try {
        $text = [Convert]::ToBase64String($bytes)
        return ConvertTo-SecureString $text -AsPlainText -Force
    } finally {
        [Array]::Clear($bytes, 0, $bytes.Length)
        $text = $null
    }
}

function New-AllowRule {
    param(
        [Security.Principal.IdentityReference]$Identity,
        [Security.AccessControl.FileSystemRights]$Rights
    )
    return [Security.AccessControl.FileSystemAccessRule]::new(
        $Identity,
        $Rights,
        [Security.AccessControl.InheritanceFlags]'ContainerInherit, ObjectInherit',
        [Security.AccessControl.PropagationFlags]::None,
        [Security.AccessControl.AccessControlType]::Allow
    )
}

function Set-GovernedDacl {
    param(
        [string]$Path,
        [Security.Principal.SecurityIdentifier]$CustodianSid,
        [Security.Principal.SecurityIdentifier]$ResearchSid,
        [bool]$ResearchRead
    )
    $acl = [Security.AccessControl.DirectorySecurity]::new()
    $acl.SetAccessRuleProtection($true, $false)
    $acl.AddAccessRule((New-AllowRule $systemSid 'FullControl'))
    $acl.AddAccessRule((New-AllowRule $administratorsSid 'FullControl'))
    $acl.AddAccessRule((New-AllowRule $CustodianSid 'Modify'))
    if ($ResearchRead) {
        $acl.AddAccessRule((New-AllowRule $ResearchSid 'ReadAndExecute'))
    }
    Set-Acl -LiteralPath $Path -AclObject $acl
}

function Add-GovernedSacl {
    param(
        [string]$Path,
        [Security.Principal.SecurityIdentifier]$CustodianSid,
        [Security.Principal.SecurityIdentifier]$ResearchSid
    )
    $acl = Get-Acl -LiteralPath $Path -Audit
    $acl.SetAuditRuleProtection($true, $false)
    $failureRights = [Security.AccessControl.FileSystemRights]'ListDirectory, ReadData, WriteData, AppendData, Delete, ChangePermissions, TakeOwnership'
    $researchAudit = [Security.AccessControl.FileSystemAuditRule]::new(
        $ResearchSid, $failureRights,
        [Security.AccessControl.InheritanceFlags]'ContainerInherit, ObjectInherit',
        [Security.AccessControl.PropagationFlags]::None,
        [Security.AccessControl.AuditFlags]::Failure
    )
    $custodianAudit = [Security.AccessControl.FileSystemAuditRule]::new(
        $CustodianSid,
        [Security.AccessControl.FileSystemRights]'ReadAndExecute, WriteData, AppendData',
        [Security.AccessControl.InheritanceFlags]'ContainerInherit, ObjectInherit',
        [Security.AccessControl.PropagationFlags]::None,
        [Security.AccessControl.AuditFlags]::Success
    )
    $acl.AddAuditRule($researchAudit)
    $acl.AddAuditRule($custodianAudit)
    Set-Acl -LiteralPath $Path -AclObject $acl
}

if (-not $PSCmdlet.ShouldProcess($root, 'Create the bounded Item 10B synthetic host boundary')) {
    return
}

$custodianPassword = $null
$researchPassword = $null
try {
    $phase = 'PREFLIGHT'
    $preflight = & $preflightScript -RepositoryRoot $RepositoryRoot `
        -CandidateRoot $CandidateRoot -AsObject
    if (-not $preflight.Pass) {
        throw "Read-only preflight failed: $($preflight.Blockers -join '; ')"
    }
    $phase = 'ROOT_CREATE'
    New-Item -ItemType Directory -Path $root | Out-Null
    $createdRoot = $true
    [IO.File]::WriteAllText((Join-Path $root '.item10b-boundary'), $marker, [Text.UTF8Encoding]::new($false))
    New-Item -ItemType Directory -Path $vault | Out-Null
    New-Item -ItemType Directory -Path $releases | Out-Null
    New-Item -ItemType Directory -Path $evidence | Out-Null

    $state = [ordered]@{
        marker = $marker
        candidate_root = $root
        created_root = $createdRoot
        created_users = @()
        audit_success_before = [bool]$preflight.AuditFileSystem.Success
        audit_failure_before = [bool]$preflight.AuditFileSystem.Failure
    }
    [IO.File]::WriteAllText($statePath, ($state | ConvertTo-Json -Depth 5), [Text.UTF8Encoding]::new($false))

    $custodianPassword = New-EphemeralPassword
    $researchPassword = New-EphemeralPassword
    $phase = 'CUSTODIAN_CREATE'
    New-LocalUser -Name 'qh-oos-custodian' -Password $custodianPassword -AccountNeverExpires -PasswordNeverExpires -UserMayNotChangePassword | Out-Null
    $createdUsers.Add('qh-oos-custodian')
    $state.created_users = @($createdUsers)
    [IO.File]::WriteAllText($statePath, ($state | ConvertTo-Json -Depth 5), [Text.UTF8Encoding]::new($false))
    $custodianUser = Get-GovernedLocalUser 'qh-oos-custodian'
    $custodianSid = $custodianUser.SID
    $phase = 'RESEARCH_CREATE'
    New-LocalUser -Name 'qh-research' -Password $researchPassword -AccountNeverExpires -PasswordNeverExpires -UserMayNotChangePassword | Out-Null
    $createdUsers.Add('qh-research')
    $state.created_users = @($createdUsers)
    [IO.File]::WriteAllText($statePath, ($state | ConvertTo-Json -Depth 5), [Text.UTF8Encoding]::new($false))
    $researchUser = Get-GovernedLocalUser 'qh-research'
    $researchSid = $researchUser.SID
    $phase = 'PRIVILEGE_CHECK'
    Assert-UnprivilegedLocalUser $custodianSid
    Assert-UnprivilegedLocalUser $researchSid
    $phase = 'VAULT_DACL'
    Set-GovernedDacl $vault $custodianSid $researchSid $false
    $phase = 'RELEASE_DACL'
    Set-GovernedDacl $releases $custodianSid $researchSid $true
    $phase = 'EVIDENCE_DACL'
    Set-GovernedDacl $evidence $custodianSid $researchSid $false
    $phase = 'INDEX_EXCLUSION'
    (Get-Item -LiteralPath $vault -Force).Attributes = (Get-Item -LiteralPath $vault -Force).Attributes -bor [IO.FileAttributes]::NotContentIndexed

    $phase = 'AUDIT_POLICY'
    & "$env:SystemRoot\System32\auditpol.exe" /set /subcategory:'File System' /success:enable /failure:enable | Out-Null
    if ($LASTEXITCODE -ne 0) { throw 'File System audit policy could not be enabled.' }
    $phase = 'VAULT_SACL'
    Add-GovernedSacl $vault $custodianSid $researchSid
    $phase = 'RELEASE_SACL'
    Add-GovernedSacl $releases $custodianSid $researchSid

    $phase = 'SYNTHETIC_FIXTURE'
    [IO.File]::WriteAllText(
        $fixturePath,
        'QUANT_HUNTER_SYNTHETIC_SEALED_FIXTURE_DO_NOT_USE_FOR_RESEARCH',
        [Text.UTF8Encoding]::new($false)
    )
    $phase = 'EFFECTIVE_VERIFY'
    $result = & $verifyScript -VaultPath $vault -ReleasePath $releases `
        -EvidencePath $evidence -CustodianPassword $custodianPassword `
        -ResearchPassword $researchPassword -CustodianSid $custodianSid `
        -ResearchSid $researchSid -PreflightResult $preflight -AsObject
    if (-not $result.live_verification_passed) {
        throw 'One or more effective Item 10B assertions failed.'
    }
    $phase = 'DISABLE_IDENTITIES'
    Disable-LocalUser -Name 'qh-oos-custodian'
    Disable-LocalUser -Name 'qh-research'
    $result.identities_disabled_after_verification = $true
    [pscustomobject]$result | ConvertTo-Json -Depth 10 -Compress
} catch {
    $failureRecord = $_
    $failurePhase = $phase
    if (Test-Path -LiteralPath $statePath) {
        try {
            & $rollbackScript -StatePath $statePath -Apply
        } catch {
            $failureRecord = $_
            $failurePhase = 'ROLLBACK'
        }
    } elseif ($createdRoot -and
        (Test-Path -LiteralPath (Join-Path $root '.item10b-boundary') -PathType Leaf) -and
        (Get-Content -LiteralPath (Join-Path $root '.item10b-boundary') -Raw) -eq $marker) {
        try {
            Remove-Item -LiteralPath $root -Recurse -Force
        } catch {
            $failureRecord = $_
            $failurePhase = 'ROLLBACK'
        }
    }
    Write-SafeSetupFailure $failurePhase $failureRecord
    exit 2
} finally {
    $custodianPassword = $null
    $researchPassword = $null
    [GC]::Collect()
}
