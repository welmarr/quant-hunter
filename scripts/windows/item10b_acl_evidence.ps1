Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'

function Get-Item10bSidValue {
    param([object]$Rule)

    try {
        $identityReference = $Rule.IdentityReference
        if ($identityReference -is [string]) {
            return [string]$identityReference
        }
        $valueProperty = $identityReference.PSObject.Properties['Value']
        if ($null -eq $valueProperty -or $valueProperty.Value -isnot [string]) {
            return $null
        }
        return [string]$valueProperty.Value
    }
    catch {
        return $null
    }
}

function Test-Item10bExactSidSet {
    param([object[]]$Rules, [string[]]$ExpectedSidValues)

    if ($Rules.Count -ne $ExpectedSidValues.Count) {
        return $false
    }
    $observed = @()
    foreach ($rule in $Rules) {
        $sidValue = Get-Item10bSidValue $rule
        if ([string]::IsNullOrWhiteSpace($sidValue)) {
            return $false
        }
        $observed += $sidValue
    }
    foreach ($expectedSid in $ExpectedSidValues) {
        if ([string]::IsNullOrWhiteSpace($expectedSid)) {
            return $false
        }
        $matches = @($observed | Where-Object {
            $_.Equals($expectedSid, [StringComparison]::OrdinalIgnoreCase)
        })
        if ($matches.Count -ne 1) {
            return $false
        }
    }
    foreach ($observedSid in $observed) {
        $matches = @($ExpectedSidValues | Where-Object {
            $_.Equals($observedSid, [StringComparison]::OrdinalIgnoreCase)
        })
        if ($matches.Count -ne 1) {
            return $false
        }
    }
    return $true
}

function Test-Item10bExactAccessRule {
    param(
        [object[]]$Rules,
        [string]$ExpectedSidValue,
        [long]$ExpectedRightsValue
    )

    $matches = @($Rules | Where-Object {
        $sidValue = Get-Item10bSidValue $_
        $null -ne $sidValue -and $sidValue.Equals(
            $ExpectedSidValue,
            [StringComparison]::OrdinalIgnoreCase
        )
    })
    if ($matches.Count -ne 1) {
        return $false
    }
    try {
        $accessControlType = [string]$matches[0].AccessControlType
        $rightsValue = [long]$matches[0].FileSystemRights
    }
    catch {
        return $false
    }
    return $accessControlType.Equals('Allow', [StringComparison]::OrdinalIgnoreCase) -and
        $rightsValue -eq $ExpectedRightsValue
}

function Test-Item10bExactAuditRule {
    param(
        [object[]]$Rules,
        [string]$ExpectedSidValue,
        [long]$ExpectedRightsValue,
        [string]$ExpectedFlags
    )

    $matches = @($Rules | Where-Object {
        $sidValue = Get-Item10bSidValue $_
        $null -ne $sidValue -and $sidValue.Equals(
            $ExpectedSidValue,
            [StringComparison]::OrdinalIgnoreCase
        )
    })
    if ($matches.Count -ne 1) {
        return $false
    }
    try {
        $rightsValue = [long]$matches[0].FileSystemRights
        $auditFlags = [string]$matches[0].AuditFlags
    }
    catch {
        return $false
    }
    return $rightsValue -eq $ExpectedRightsValue -and
        $auditFlags.Equals($ExpectedFlags, [StringComparison]::OrdinalIgnoreCase)
}
