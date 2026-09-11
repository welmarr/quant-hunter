[CmdletBinding()]
param(
    [Parameter(Mandatory = $true)]
    [string]$AclScriptPath
)

Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'
. $AclScriptPath

$expectedSid = 'S-1-5-21-1-2-3-1001'
$sameNameWrongSid = 'S-1-5-21-1-2-3-1002'
$otherExpectedSid = 'S-1-5-21-1-2-3-1003'
$readAndExecuteRights = 131241L
$modifyRights = 197055L
$readDataRights = 1L
$expectedAccess = [pscustomobject]@{
    IdentityReference = $expectedSid
    AccountName = 'qh-research'
    AccessControlType = 'Allow'
    FileSystemRights = $readAndExecuteRights
}
$otherExpectedAccess = [pscustomobject]@{
    IdentityReference = $otherExpectedSid
    AccountName = 'synthetic-other'
    AccessControlType = 'Allow'
    FileSystemRights = $readAndExecuteRights
}
$sameNameWrongAccess = [pscustomobject]@{
    IdentityReference = $sameNameWrongSid
    AccountName = 'qh-research'
    AccessControlType = 'Allow'
    FileSystemRights = $readAndExecuteRights
}
$wrongRightsAccess = [pscustomobject]@{
    IdentityReference = $expectedSid
    AccountName = 'qh-research'
    AccessControlType = 'Allow'
    FileSystemRights = $modifyRights
}
$wrongTypeAccess = [pscustomobject]@{
    IdentityReference = $expectedSid
    AccountName = 'qh-research'
    AccessControlType = 'Deny'
    FileSystemRights = $readAndExecuteRights
}
$wrongAuditOutcome = [pscustomobject]@{
    IdentityReference = $expectedSid
    AccountName = 'qh-research'
    FileSystemRights = $readDataRights
    AuditFlags = 'Success'
}

[ordered]@{
    expected_sid_accepted = Test-Item10bExactAccessRule `
        @($expectedAccess) $expectedSid $readAndExecuteRights
    same_name_wrong_sid_rejected = -not (Test-Item10bExactAccessRule `
        @($sameNameWrongAccess) $expectedSid $readAndExecuteRights)
    wrong_rights_rejected = -not (Test-Item10bExactAccessRule `
        @($wrongRightsAccess) $expectedSid $readAndExecuteRights)
    wrong_access_control_type_rejected = -not (Test-Item10bExactAccessRule `
        @($wrongTypeAccess) $expectedSid $readAndExecuteRights)
    wrong_audit_outcome_rejected = -not (Test-Item10bExactAuditRule `
        @($wrongAuditOutcome) $expectedSid $readDataRights 'Failure')
    exact_sid_set_accepted = Test-Item10bExactSidSet `
        @($expectedAccess, $otherExpectedAccess) @($expectedSid, $otherExpectedSid)
    missing_sid_rejected = -not (Test-Item10bExactSidSet `
        @($expectedAccess) @($expectedSid, $otherExpectedSid))
    extra_sid_rejected = -not (Test-Item10bExactSidSet `
        @($expectedAccess, $otherExpectedAccess) @($expectedSid))
    wrong_sid_set_rejected = -not (Test-Item10bExactSidSet `
        @($expectedAccess, $sameNameWrongAccess) @($expectedSid, $otherExpectedSid))
} | ConvertTo-Json -Compress
