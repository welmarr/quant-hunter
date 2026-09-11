[CmdletBinding()]
param(
    [Parameter(Mandatory = $true)]
    [string]$AclScriptPath
)

Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'
. $AclScriptPath

$expectedSid = [Security.Principal.SecurityIdentifier]::new('S-1-5-21-1-2-3-1001')
$sameNameWrongSid = [Security.Principal.SecurityIdentifier]::new('S-1-5-21-1-2-3-1002')
$expectedAccess = [pscustomobject]@{
    IdentityReference = $expectedSid
    AccountName = 'qh-research'
    AccessControlType = [Security.AccessControl.AccessControlType]::Allow
    FileSystemRights = [Security.AccessControl.FileSystemRights]::ReadAndExecute
}
$sameNameWrongAccess = [pscustomobject]@{
    IdentityReference = $sameNameWrongSid
    AccountName = 'qh-research'
    AccessControlType = [Security.AccessControl.AccessControlType]::Allow
    FileSystemRights = [Security.AccessControl.FileSystemRights]::ReadAndExecute
}
$wrongRightsAccess = [pscustomobject]@{
    IdentityReference = $expectedSid
    AccountName = 'qh-research'
    AccessControlType = [Security.AccessControl.AccessControlType]::Allow
    FileSystemRights = [Security.AccessControl.FileSystemRights]::Modify
}
$wrongAuditOutcome = [pscustomobject]@{
    IdentityReference = $expectedSid
    AccountName = 'qh-research'
    FileSystemRights = [Security.AccessControl.FileSystemRights]::ReadData
    AuditFlags = [Security.AccessControl.AuditFlags]::Success
}

[ordered]@{
    expected_sid_accepted = Test-Item10bExactAccessRule `
        @($expectedAccess) $expectedSid 'ReadAndExecute'
    same_name_wrong_sid_rejected = -not (Test-Item10bExactAccessRule `
        @($sameNameWrongAccess) $expectedSid 'ReadAndExecute')
    wrong_rights_rejected = -not (Test-Item10bExactAccessRule `
        @($wrongRightsAccess) $expectedSid 'ReadAndExecute')
    wrong_audit_outcome_rejected = -not (Test-Item10bExactAuditRule `
        @($wrongAuditOutcome) $expectedSid 'ReadData' 'Failure')
} | ConvertTo-Json -Compress
