[CmdletBinding()]
param(
    [Parameter(Mandatory = $true)]
    [string]$RepositoryRoot,
    [Parameter(Mandatory = $true)]
    [string]$CandidateRoot,
    [switch]$AsObject
)

Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'

function Resolve-DirectPath {
    param([string]$Path, [string]$Label)
    $full = [IO.Path]::GetFullPath($Path)
    $root = [IO.Path]::GetPathRoot($full)
    if ([string]::IsNullOrWhiteSpace($root) -or $full -eq $root) {
        throw "$Label must be an absolute non-root path."
    }
    return $full.TrimEnd([IO.Path]::DirectorySeparatorChar)
}

function Test-PathWithin {
    param([string]$Path, [string]$Boundary)
    $pathValue = (Resolve-DirectPath $Path 'Path') + [IO.Path]::DirectorySeparatorChar
    $boundaryValue = (Resolve-DirectPath $Boundary 'Boundary') + [IO.Path]::DirectorySeparatorChar
    return $pathValue.StartsWith($boundaryValue, [StringComparison]::OrdinalIgnoreCase)
}

function Test-ExistingReparseComponent {
    param([string]$Path)
    $current = [IO.Path]::GetPathRoot([IO.Path]::GetFullPath($Path))
    foreach ($part in [IO.Path]::GetFullPath($Path).Substring($current.Length).Split(
        [IO.Path]::DirectorySeparatorChar,
        [StringSplitOptions]::RemoveEmptyEntries
    )) {
        $current = Join-Path $current $part
        if (-not (Test-Path -LiteralPath $current)) { break }
        if (((Get-Item -LiteralPath $current -Force).Attributes -band [IO.FileAttributes]::ReparsePoint) -ne 0) {
            return $true
        }
    }
    return $false
}

function Get-AuditFlags {
    $lines = & "$env:SystemRoot\System32\auditpol.exe" /get /subcategory:'File System' /r 2>$null
    if ($LASTEXITCODE -ne 0 -or -not $lines) {
        throw 'The File System audit policy could not be queried.'
    }
    $row = $lines | ConvertFrom-Csv | Select-Object -First 1
    $setting = [string]$row.'Inclusion Setting'
    if ([string]::IsNullOrWhiteSpace($setting)) {
        throw 'The File System audit policy result could not be interpreted.'
    }
    [pscustomobject]@{
        Raw = $setting
        Success = $setting -match 'Success'
        Failure = $setting -match 'Failure'
    }
}

$blockers = [Collections.Generic.List[string]]::new()
$observations = [Collections.Generic.List[string]]::new()
$repository = Resolve-DirectPath $RepositoryRoot 'RepositoryRoot'
$candidate = Resolve-DirectPath $CandidateRoot 'CandidateRoot'
if (Test-ExistingReparseComponent $candidate) {
    $blockers.Add('CandidateRoot traverses an existing reparse point.')
}

if ([Environment]::OSVersion.Platform -ne [PlatformID]::Win32NT) {
    $blockers.Add('The operating system is not supported Windows.')
}

$identity = [Security.Principal.WindowsIdentity]::GetCurrent()
$principal = [Security.Principal.WindowsPrincipal]::new($identity)
$elevated = $principal.IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)
if (-not $elevated) {
    $blockers.Add('The current process is not an elevated Administrator.')
}

$worktrees = [Collections.Generic.List[string]]::new()
$worktrees.Add($repository)
try {
    $gitLines = & git -C $repository worktree list --porcelain 2>$null
    foreach ($line in $gitLines) {
        if ($line.StartsWith('worktree ')) {
            $worktrees.Add((Resolve-DirectPath $line.Substring(9) 'Git worktree'))
        }
    }
} catch {
    $blockers.Add('Git worktree roots could not be inventoried.')
}

$candidateVolume = $null
$bitLocker = $null
try {
    $volumeRoot = [IO.Path]::GetPathRoot($candidate)
    $candidateVolume = Get-CimInstance Win32_LogicalDisk -Filter 'DriveType = 3' |
        Where-Object { ($_.DeviceID + '\') -eq $volumeRoot } |
        Select-Object -First 1
    if ($null -eq $candidateVolume) {
        $blockers.Add('CandidateRoot is not on a local fixed volume.')
    } elseif ([string]$candidateVolume.FileSystem -ne 'NTFS') {
        $blockers.Add('CandidateRoot is not on NTFS.')
    }
    $bitLocker = Get-BitLockerVolume -MountPoint $volumeRoot
    if ($null -eq $bitLocker -or
        [string]$bitLocker.ProtectionStatus -ne 'On' -or
        [string]$bitLocker.VolumeStatus -ne 'FullyEncrypted') {
        $blockers.Add('CandidateRoot lacks proven complete BitLocker protection.')
    }
} catch {
    $blockers.Add('Fixed-volume or BitLocker protection could not be proven.')
}

$forbiddenRoots = [Collections.Generic.List[string]]::new()
foreach ($rootPath in $worktrees) { $forbiddenRoots.Add($rootPath) }
foreach ($pathValue in @(
    $env:USERPROFILE,
    $env:TEMP,
    $env:TMP,
    $env:LOCALAPPDATA,
    $env:APPDATA,
    $env:OneDrive,
    $env:OneDriveConsumer,
    $env:OneDriveCommercial
)) {
    if (-not [string]::IsNullOrWhiteSpace($pathValue)) {
        $forbiddenRoots.Add((Resolve-DirectPath $pathValue 'Forbidden root'))
    }
}
foreach ($boundary in $forbiddenRoots | Select-Object -Unique) {
    if ((Test-PathWithin $candidate $boundary) -or (Test-PathWithin $boundary $candidate)) {
        $blockers.Add('CandidateRoot overlaps a repository, profile, cache, temp, or sync boundary.')
        break
    }
}

$custodian = Get-LocalUser -Name 'qh-oos-custodian' -ErrorAction SilentlyContinue
$research = Get-LocalUser -Name 'qh-research' -ErrorAction SilentlyContinue
if ($null -ne $custodian -or $null -ne $research) {
    $blockers.Add('A governed qh-* identity already exists and requires owner review.')
}
if (Test-Path -LiteralPath $candidate) {
    $blockers.Add('CandidateRoot already exists and requires owner review.')
}

$audit = $null
try {
    $audit = Get-AuditFlags
} catch {
    $blockers.Add('The File System audit policy cannot be read safely.')
}

$search = Get-Service -Name WSearch -ErrorAction SilentlyContinue
if ($null -ne $search) {
    $observations.Add("Windows Search state: $($search.Status).")
}

$backupStatus = 'RESIDUAL_RISK_RETAINED'
try {
    $null = & "$env:SystemRoot\System32\wbadmin.exe" get status 2>$null
    if ($LASTEXITCODE -eq 0) {
        $observations.Add('Windows backup configuration was readable; equivalent protection still requires review.')
    } else {
        $observations.Add('Windows backup configuration was not readable; residual risk retained.')
    }
} catch {
    $observations.Add('Windows backup configuration was not readable; residual risk retained.')
}

$result = [pscustomobject]@{
    SchemaVersion = '1.0.0'
    Pass = $blockers.Count -eq 0
    ElevatedAdministrator = $elevated
    RepositoryRoot = $repository
    WorktreeRoots = @($worktrees | Select-Object -Unique)
    CandidateRoot = $candidate
    CandidateFilesystem = if ($null -eq $candidateVolume) { $null } else { [string]$candidateVolume.FileSystem }
    FixedLocalVolume = $null -ne $candidateVolume
    BitLockerProtectionStatus = if ($null -eq $bitLocker) { $null } else { [string]$bitLocker.ProtectionStatus }
    BitLockerVolumeStatus = if ($null -eq $bitLocker) { $null } else { [string]$bitLocker.VolumeStatus }
    CustodianExists = $null -ne $custodian
    ResearchExists = $null -ne $research
    CandidateExists = Test-Path -LiteralPath $candidate
    AuditFileSystem = $audit
    BackupStatus = $backupStatus
    Blockers = @($blockers)
    Observations = @($observations)
}

if ($AsObject) {
    return $result
}
$result | ConvertTo-Json -Depth 8
if (-not $result.Pass) { exit 2 }
