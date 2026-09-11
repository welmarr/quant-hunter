[CmdletBinding(SupportsShouldProcess = $true, ConfirmImpact = 'High')]
param(
    [Parameter(Mandatory = $true)]
    [string]$StatePath,
    [switch]$Apply
)

Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'
if (-not $Apply) { throw 'Rollback is inert unless -Apply is supplied explicitly.' }
if (-not (Test-Path -LiteralPath $StatePath -PathType Leaf)) {
    throw 'The explicit rollback state file does not exist.'
}
$state = Get-Content -LiteralPath $StatePath -Raw | ConvertFrom-Json
if ($state.marker -ne 'QUANT_HUNTER_ITEM10B_SYNTHETIC_BOUNDARY') {
    throw 'Rollback state marker is invalid.'
}
$root = [IO.Path]::GetFullPath([string]$state.candidate_root).TrimEnd([IO.Path]::DirectorySeparatorChar)
$filesystemRoot = [IO.Path]::GetPathRoot($root)
if ([string]::IsNullOrWhiteSpace($filesystemRoot) -or $root -eq $filesystemRoot) {
    throw 'Rollback target is not a safe non-root path.'
}
$markerPath = Join-Path $root '.item10b-boundary'
if (-not (Test-Path -LiteralPath $markerPath -PathType Leaf) -or
    (Get-Content -LiteralPath $markerPath -Raw) -ne $state.marker) {
    throw 'Rollback target lacks the exact batch-created marker.'
}
if (-not $PSCmdlet.ShouldProcess($root, 'Roll back only Item 10B-created resources')) {
    return
}

$success = if ([bool]$state.audit_success_before) { 'enable' } else { 'disable' }
$failure = if ([bool]$state.audit_failure_before) { 'enable' } else { 'disable' }
& "$env:SystemRoot\System32\auditpol.exe" /set /subcategory:'File System' /success:$success /failure:$failure | Out-Null
if ($LASTEXITCODE -ne 0) { throw 'Original File System audit policy could not be restored.' }

foreach ($name in @($state.created_users)) {
    if ($name -notin @('qh-oos-custodian', 'qh-research')) {
        throw 'Rollback state contains an unexpected identity.'
    }
    if (Get-LocalUser -Name $name -ErrorAction SilentlyContinue) {
        Remove-LocalUser -Name $name
    }
}
if ([bool]$state.created_root) {
    $resolvedState = [IO.Path]::GetFullPath($StatePath)
    if (-not $resolvedState.StartsWith($root + [IO.Path]::DirectorySeparatorChar, [StringComparison]::OrdinalIgnoreCase)) {
        throw 'Rollback state is outside its exact target boundary.'
    }
    Remove-Item -LiteralPath $root -Recurse -Force
}
