[CmdletBinding()]
param(
    [Parameter(Mandatory = $true)][string]$AuditScriptPath,
    [Parameter(Mandatory = $true)][string]$FixturePath,
    [Parameter(Mandatory = $true)][string]$WindowStart,
    [Parameter(Mandatory = $true)][string]$WindowEnd,
    [Parameter(Mandatory = $true)][string]$VaultPath,
    [Parameter(Mandatory = $true)][string]$SealedFixturePath,
    [Parameter(Mandatory = $true)][string]$ReleasedPath
)

Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'
. $AuditScriptPath
$fixtureScenarios = Get-Content -LiteralPath $FixturePath -Raw | ConvertFrom-Json
$results = [ordered]@{}
foreach ($scenario in $fixtureScenarios.psobject.Properties) {
    $eventRecords = @(@($scenario.Value) | ForEach-Object {
        $accountName = [Security.SecurityElement]::Escape([string]$_.account_name)
        $objectName = [Security.SecurityElement]::Escape([string]$_.object_name)
        $keywords = [Security.SecurityElement]::Escape([string]$_.keywords)
        $eventXml = '<Event><System><Keywords>{0}</Keywords></System>' +
            '<EventData><Data Name="SubjectUserName">{1}</Data>' +
            '<Data Name="ObjectName">{2}</Data></EventData></Event>'
        $eventXml = $eventXml -f $keywords, $accountName, $objectName
        $record = [pscustomobject]@{
            Id = [int]$_.event_id
            TimeCreated = [datetime]$_.occurred_at
            EventXml = $eventXml
        }
        $record | Add-Member -MemberType ScriptMethod -Name ToXml -Value {
            return [string]$this.EventXml
        } -PassThru
    })
    $events = @($eventRecords | ConvertTo-Item10bNormalizedAuditEvent)
    $results[$scenario.Name] = Test-Item10bAuditEvidence -Events $events `
        -WindowStart $WindowStart -WindowEnd $WindowEnd `
        -VaultPath $VaultPath -FixturePath $SealedFixturePath `
        -ReleasedPath $ReleasedPath
}
[pscustomobject]$results | ConvertTo-Json -Depth 5 -Compress
