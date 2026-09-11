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
if (-not $Apply) {
    throw 'Host setup is inert unless -Apply is supplied explicitly.'
}

$preflightScript = Join-Path $PSScriptRoot 'item10b_preflight.ps1'
$verifyScript = Join-Path $PSScriptRoot 'item10b_verify.ps1'
$rollbackScript = Join-Path $PSScriptRoot 'item10b_rollback.ps1'
$preflight = & $preflightScript -RepositoryRoot $RepositoryRoot -CandidateRoot $CandidateRoot -AsObject
if (-not $preflight.Pass) {
    throw "Read-only preflight failed: $($preflight.Blockers -join '; ')"
}

$root = [IO.Path]::GetFullPath($CandidateRoot).TrimEnd([IO.Path]::DirectorySeparatorChar)
$vault = Join-Path $root 'vault'
$releases = Join-Path $root 'releases'
$evidence = Join-Path $root 'host-evidence'
$statePath = Join-Path $evidence 'item10b-created-state.json'
$fixturePath = Join-Path $vault 'synthetic-sealed-fixture.txt'
$marker = 'QUANT_HUNTER_ITEM10B_SYNTHETIC_BOUNDARY'
$createdUsers = [Collections.Generic.List[string]]::new()
$createdRoot = $false

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
    param([string]$Identity, [Security.AccessControl.FileSystemRights]$Rights)
    return [Security.AccessControl.FileSystemAccessRule]::new(
        $Identity,
        $Rights,
        [Security.AccessControl.InheritanceFlags]'ContainerInherit, ObjectInherit',
        [Security.AccessControl.PropagationFlags]::None,
        [Security.AccessControl.AccessControlType]::Allow
    )
}

function Set-GovernedDacl {
    param([string]$Path, [bool]$ResearchRead)
    $acl = [Security.AccessControl.DirectorySecurity]::new()
    $acl.SetAccessRuleProtection($true, $false)
    $acl.AddAccessRule((New-AllowRule 'NT AUTHORITY\SYSTEM' 'FullControl'))
    $acl.AddAccessRule((New-AllowRule 'BUILTIN\Administrators' 'FullControl'))
    $acl.AddAccessRule((New-AllowRule '.\qh-oos-custodian' 'Modify'))
    if ($ResearchRead) {
        $acl.AddAccessRule((New-AllowRule '.\qh-research' 'ReadAndExecute'))
    }
    Set-Acl -LiteralPath $Path -AclObject $acl
}

function Add-GovernedSacl {
    param([string]$Path, [bool]$ReleasePath)
    $acl = Get-Acl -LiteralPath $Path -Audit
    $acl.SetAuditRuleProtection($true, $false)
    $failureRights = [Security.AccessControl.FileSystemRights]'ListDirectory, ReadData, WriteData, AppendData, Delete, ChangePermissions, TakeOwnership'
    $researchAudit = [Security.AccessControl.FileSystemAuditRule]::new(
        '.\qh-research', $failureRights,
        [Security.AccessControl.InheritanceFlags]'ContainerInherit, ObjectInherit',
        [Security.AccessControl.PropagationFlags]::None,
        [Security.AccessControl.AuditFlags]::Failure
    )
    $custodianAudit = [Security.AccessControl.FileSystemAuditRule]::new(
        '.\qh-oos-custodian',
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
    New-LocalUser -Name 'qh-oos-custodian' -Password $custodianPassword -AccountNeverExpires -PasswordNeverExpires -UserMayNotChangePassword | Out-Null
    $createdUsers.Add('qh-oos-custodian')
    $state.created_users = @($createdUsers)
    [IO.File]::WriteAllText($statePath, ($state | ConvertTo-Json -Depth 5), [Text.UTF8Encoding]::new($false))
    New-LocalUser -Name 'qh-research' -Password $researchPassword -AccountNeverExpires -PasswordNeverExpires -UserMayNotChangePassword | Out-Null
    $createdUsers.Add('qh-research')
    $state.created_users = @($createdUsers)
    [IO.File]::WriteAllText($statePath, ($state | ConvertTo-Json -Depth 5), [Text.UTF8Encoding]::new($false))
    foreach ($name in $createdUsers) {
        foreach ($group in @('Administrators', 'Backup Operators', 'Remote Desktop Users')) {
            if (Get-LocalGroupMember -Group $group -Member $name -ErrorAction SilentlyContinue) {
                throw "Created identity has a forbidden privileged membership."
            }
        }
    }
    Set-GovernedDacl $vault $false
    Set-GovernedDacl $releases $true
    Set-GovernedDacl $evidence $false
    (Get-Item -LiteralPath $vault -Force).Attributes = (Get-Item -LiteralPath $vault -Force).Attributes -bor [IO.FileAttributes]::NotContentIndexed

    & "$env:SystemRoot\System32\auditpol.exe" /set /subcategory:'File System' /success:enable /failure:enable | Out-Null
    if ($LASTEXITCODE -ne 0) { throw 'File System audit policy could not be enabled.' }
    Add-GovernedSacl $vault $false
    Add-GovernedSacl $releases $true

    [IO.File]::WriteAllText(
        $fixturePath,
        'QUANT_HUNTER_SYNTHETIC_SEALED_FIXTURE_DO_NOT_USE_FOR_RESEARCH',
        [Text.UTF8Encoding]::new($false)
    )
    $result = & $verifyScript -VaultPath $vault -ReleasePath $releases `
        -EvidencePath $evidence -CustodianPassword $custodianPassword `
        -ResearchPassword $researchPassword -PreflightResult $preflight -AsObject
    if (-not $result.live_verification_passed) {
        throw 'One or more effective Item 10B assertions failed.'
    }
    Disable-LocalUser -Name 'qh-oos-custodian'
    Disable-LocalUser -Name 'qh-research'
    $result.identities_disabled_after_verification = $true
    [pscustomobject]$result | ConvertTo-Json -Depth 10 -Compress
} catch {
    if (Test-Path -LiteralPath $statePath) {
        & $rollbackScript -StatePath $statePath -Apply
    } elseif ($createdRoot -and
        (Test-Path -LiteralPath (Join-Path $root '.item10b-boundary') -PathType Leaf) -and
        (Get-Content -LiteralPath (Join-Path $root '.item10b-boundary') -Raw) -eq $marker) {
        Remove-Item -LiteralPath $root -Recurse -Force
    }
    throw
} finally {
    $custodianPassword = $null
    $researchPassword = $null
    [GC]::Collect()
}
