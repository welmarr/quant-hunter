[CmdletBinding()]
param(
    [Parameter(Mandatory = $true)]
    [ValidateSet('Research', 'Custodian')]
    [string]$Role,
    [Parameter(Mandatory = $true)]
    [string]$VaultPath,
    [Parameter(Mandatory = $true)]
    [string]$FixturePath,
    [Parameter(Mandatory = $true)]
    [string]$ReleasedPath,
    [Parameter(Mandatory = $true)]
    [string]$OutputPath
)

Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'

function Test-Operation {
    param([scriptblock]$Operation, [bool]$ExpectedSuccess)
    try {
        & $Operation
        return $ExpectedSuccess
    } catch {
        return -not $ExpectedSuccess
    }
}

function Test-AclMutation {
    param([string]$Path, [bool]$Ownership)
    $acl = Get-Acl -LiteralPath $Path
    if ($Ownership) {
        $acl.SetOwner([Security.Principal.WindowsIdentity]::GetCurrent().User)
    }
    Set-Acl -LiteralPath $Path -AclObject $acl
}

if ($Role -eq 'Research') {
    $result = [ordered]@{
        role = 'qh-research'
        directory_list_denied = Test-Operation { Get-ChildItem -LiteralPath $VaultPath -ErrorAction Stop | Out-Null } $false
        file_read_denied = Test-Operation { Get-Content -LiteralPath $FixturePath -Raw -ErrorAction Stop | Out-Null } $false
        file_create_denied = Test-Operation { [IO.File]::WriteAllText((Join-Path $VaultPath 'forbidden-create.txt'), 'synthetic') } $false
        file_write_denied = Test-Operation { Add-Content -LiteralPath $FixturePath -Value 'synthetic' -ErrorAction Stop } $false
        file_delete_denied = Test-Operation { Remove-Item -LiteralPath $FixturePath -ErrorAction Stop } $false
        acl_change_denied = Test-Operation { Test-AclMutation $FixturePath $false } $false
        owner_change_denied = Test-Operation { Test-AclMutation $FixturePath $true } $false
        read_attributes_denied = Test-Operation { Get-Item -LiteralPath $FixturePath -Force -ErrorAction Stop | Out-Null } $false
        research_read_succeeded = Test-Operation { Get-Content -LiteralPath $ReleasedPath -Raw -ErrorAction Stop | Out-Null } $true
        research_modify_denied = Test-Operation { Add-Content -LiteralPath $ReleasedPath -Value 'synthetic' -ErrorAction Stop } $false
        research_delete_denied = Test-Operation { Remove-Item -LiteralPath $ReleasedPath -ErrorAction Stop } $false
        research_acl_change_denied = Test-Operation { Test-AclMutation $ReleasedPath $false } $false
        research_owner_change_denied = Test-Operation { Test-AclMutation $ReleasedPath $true } $false
    }
} else {
    $result = [ordered]@{
        role = 'qh-oos-custodian'
        vault_list_succeeded = Test-Operation { Get-ChildItem -LiteralPath $VaultPath -ErrorAction Stop | Out-Null } $true
        fixture_read_succeeded = Test-Operation { Get-Content -LiteralPath $FixturePath -Raw -ErrorAction Stop | Out-Null } $true
        release_publish_succeeded = Test-Operation { Copy-Item -LiteralPath $FixturePath -Destination $ReleasedPath -ErrorAction Stop } $true
    }
}

[IO.File]::WriteAllText(
    [IO.Path]::GetFullPath($OutputPath),
    ($result | ConvertTo-Json -Depth 6 -Compress),
    [Text.UTF8Encoding]::new($false)
)
