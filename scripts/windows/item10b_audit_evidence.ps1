Set-StrictMode -Version Latest

$script:Item10bAuditFailureKeyword = [Convert]::ToUInt64('0010000000000000', 16)
$script:Item10bAuditSuccessKeyword = [Convert]::ToUInt64('0020000000000000', 16)

function ConvertTo-Item10bAuditKeyword {
    param([Parameter(Mandatory = $true)][object]$Value)

    $text = ([string]$Value).Trim()
    if ($text.StartsWith('0x', [StringComparison]::OrdinalIgnoreCase)) {
        return [Convert]::ToUInt64($text.Substring(2), 16)
    }
    return [Convert]::ToUInt64($text, [Globalization.CultureInfo]::InvariantCulture)
}

function Test-Item10bAuditIdentity {
    param(
        [Parameter(Mandatory = $true)][string]$Observed,
        [Parameter(Mandatory = $true)][string]$Expected
    )

    $leaf = $Observed.Split('\')[-1]
    return $leaf.Equals($Expected, [StringComparison]::OrdinalIgnoreCase)
}

function Test-Item10bAuditTarget {
    param(
        [Parameter(Mandatory = $true)][string]$Observed,
        [Parameter(Mandatory = $true)][string[]]$Expected
    )

    $normalized = $Observed.Replace('/', '\').TrimEnd('\')
    foreach ($target in $Expected) {
        if ($normalized.Equals(
            $target.Replace('/', '\').TrimEnd('\'),
            [StringComparison]::OrdinalIgnoreCase
        )) {
            return $true
        }
    }
    return $false
}

function ConvertTo-Item10bNormalizedAuditEvent {
    param([Parameter(Mandatory = $true, ValueFromPipeline = $true)][object]$EventRecord)

    process {
        [xml]$document = $EventRecord.ToXml()
        $fields = @{}
        foreach ($item in @($document.Event.EventData.Data)) {
            $fields[[string]$item.GetAttribute('Name')] = [string]$item.InnerText
        }
        [pscustomobject]@{
            event_id = [int]$EventRecord.Id
            occurred_at = ([datetime]$EventRecord.TimeCreated).ToUniversalTime().ToString('o')
            account_name = [string]$fields['SubjectUserName']
            object_name = [string]$fields['ObjectName']
            keywords = [string]$document.Event.System.Keywords
        }
    }
}

function Test-Item10bAuditEvidence {
    param(
        [Parameter(Mandatory = $true)][object[]]$Events,
        [Parameter(Mandatory = $true)][datetimeoffset]$WindowStart,
        [Parameter(Mandatory = $true)][datetimeoffset]$WindowEnd,
        [Parameter(Mandatory = $true)][string]$VaultPath,
        [Parameter(Mandatory = $true)][string]$FixturePath,
        [Parameter(Mandatory = $true)][string]$ReleasedPath
    )

    if ($WindowStart -gt $WindowEnd) {
        throw 'The governed audit window is invalid.'
    }
    $researchTargets = @(
        $VaultPath,
        $FixturePath,
        (Join-Path $VaultPath 'forbidden-create.txt')
    )
    $custodianTargets = @($FixturePath, $ReleasedPath)
    $researchDenial = $false
    $custodianActivity = $false

    foreach ($event in $Events) {
        try {
            $occurredAt = [datetimeoffset]::Parse(
                [string]$event.occurred_at,
                [Globalization.CultureInfo]::InvariantCulture,
                [Globalization.DateTimeStyles]::AssumeUniversal -bor
                    [Globalization.DateTimeStyles]::AdjustToUniversal
            )
            $keywords = ConvertTo-Item10bAuditKeyword $event.keywords
        } catch {
            continue
        }
        if ($occurredAt -lt $WindowStart -or $occurredAt -gt $WindowEnd) {
            continue
        }
        $isFailure = ($keywords -band $script:Item10bAuditFailureKeyword) -ne 0
        $isSuccess = ($keywords -band $script:Item10bAuditSuccessKeyword) -ne 0
        if (
            [int]$event.event_id -eq 4656 -and
            $isFailure -and
            -not $isSuccess -and
            (Test-Item10bAuditIdentity ([string]$event.account_name) 'qh-research') -and
            (Test-Item10bAuditTarget ([string]$event.object_name) $researchTargets)
        ) {
            $researchDenial = $true
        }
        if (
            [int]$event.event_id -eq 4663 -and
            $isSuccess -and
            -not $isFailure -and
            (Test-Item10bAuditIdentity ([string]$event.account_name) 'qh-oos-custodian') -and
            (Test-Item10bAuditTarget ([string]$event.object_name) $custodianTargets)
        ) {
            $custodianActivity = $true
        }
    }

    [pscustomobject]@{
        research_denial_observed = $researchDenial
        custodian_activity_observed = $custodianActivity
    }
}
