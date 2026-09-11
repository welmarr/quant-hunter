Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'

function Test-Item10bExactSidSet {
    param([object[]]$Rules, [string[]]$ExpectedSidValues)

    $observed = @($Rules | ForEach-Object {
        if (-not ($_.IdentityReference -is [Security.Principal.SecurityIdentifier])) {
            return '__INVALID_IDENTITY_REFERENCE__'
        }
        return $_.IdentityReference.Value
    })
    return $observed.Count -eq $ExpectedSidValues.Count -and
        @($ExpectedSidValues | Where-Object { $_ -notin $observed }).Count -eq 0
}

function Test-Item10bExactAccessRule {
    param(
        [object[]]$Rules,
        [Security.Principal.SecurityIdentifier]$ExpectedSid,
        [Security.AccessControl.FileSystemRights]$ExpectedRights
    )

    $matches = @($Rules | Where-Object {
        $_.IdentityReference -is [Security.Principal.SecurityIdentifier] -and
        $_.IdentityReference.Value.Equals(
            $ExpectedSid.Value,
            [StringComparison]::OrdinalIgnoreCase
        )
    })
    return $matches.Count -eq 1 -and
        $matches[0].AccessControlType -eq [Security.AccessControl.AccessControlType]::Allow -and
        $matches[0].FileSystemRights -eq $ExpectedRights
}

function Test-Item10bExactAuditRule {
    param(
        [object[]]$Rules,
        [Security.Principal.SecurityIdentifier]$ExpectedSid,
        [Security.AccessControl.FileSystemRights]$ExpectedRights,
        [Security.AccessControl.AuditFlags]$ExpectedFlags
    )

    $matches = @($Rules | Where-Object {
        $_.IdentityReference -is [Security.Principal.SecurityIdentifier] -and
        $_.IdentityReference.Value.Equals(
            $ExpectedSid.Value,
            [StringComparison]::OrdinalIgnoreCase
        )
    })
    return $matches.Count -eq 1 -and
        $matches[0].FileSystemRights -eq $ExpectedRights -and
        $matches[0].AuditFlags -eq $ExpectedFlags
}
