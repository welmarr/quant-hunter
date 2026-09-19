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

function Test-Item10bAuditSid {
    param(
        [Parameter(Mandatory = $true)][string]$Observed,
        [Parameter(Mandatory = $true)][string]$Expected
    )

    return $Observed.Equals($Expected, [StringComparison]::OrdinalIgnoreCase)
}

function ConvertTo-Item10bAuditTarget {
    param([Parameter(Mandatory = $true)][string]$Value)

    $normalized = $Value.Replace('/', '\')
    if ($normalized -eq '\' -or $normalized -match '^[A-Za-z]:\\$') {
        return $normalized
    }
    return $normalized.TrimEnd('\')
}

function Join-Item10bAuditTarget {
    param(
        [Parameter(Mandatory = $true)][string]$Base,
        [Parameter(Mandatory = $true)][string]$Leaf
    )

    $normalizedBase = ConvertTo-Item10bAuditTarget $Base
    $normalizedLeaf = $Leaf.Replace('/', '\').TrimStart('\')
    $separator = if ($normalizedBase.EndsWith('\')) { '' } else { '\' }
    return $normalizedBase + $separator + $normalizedLeaf
}

function Test-Item10bAuditTarget {
    param(
        [Parameter(Mandatory = $true)][string]$Observed,
        [Parameter(Mandatory = $true)][string[]]$Expected
    )

    $normalized = ConvertTo-Item10bAuditTarget $Observed
    foreach ($target in $Expected) {
        if ($normalized.Equals(
            (ConvertTo-Item10bAuditTarget $target),
            [StringComparison]::OrdinalIgnoreCase
        )) {
            return $true
        }
    }
    return $false
}

function Resolve-Item10bAuditTargetKind {
    param(
        [Parameter(Mandatory = $true)][string]$Observed,
        [Parameter(Mandatory = $true)][Collections.IDictionary]$Expected
    )

    foreach ($entry in $Expected.GetEnumerator()) {
        if ((ConvertTo-Item10bAuditTarget $Observed).Equals(
            (ConvertTo-Item10bAuditTarget ([string]$entry.Value)),
            [StringComparison]::OrdinalIgnoreCase
        )) {
            return [string]$entry.Key
        }
    }
    return $null
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
            subject_user_sid = [string]$fields['SubjectUserSid']
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
        [Parameter(Mandatory = $true)][string]$ReleasedPath,
        [Parameter(Mandatory = $true)][string]$ExpectedResearchSid,
        [Parameter(Mandatory = $true)][string]$ExpectedCustodianSid
    )

    if ($WindowStart -gt $WindowEnd) {
        throw 'The governed audit window is invalid.'
    }
    $researchTargets = [ordered]@{
        VAULT_ROOT = $VaultPath
        SEALED_FIXTURE = $FixturePath
        FORBIDDEN_CREATE = (Join-Item10bAuditTarget $VaultPath 'forbidden-create.txt')
    }
    $custodianTargets = [ordered]@{
        SEALED_FIXTURE = $FixturePath
        RELEASED_FIXTURE = $ReleasedPath
    }
    $researchDenial = $false
    $custodianActivity = $false
    $researchEvent = $null
    $custodianEvent = $null

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
        $researchTargetKind = Resolve-Item10bAuditTargetKind `
            ([string]$event.object_name) $researchTargets
        $custodianTargetKind = Resolve-Item10bAuditTargetKind `
            ([string]$event.object_name) $custodianTargets
        if (
            [int]$event.event_id -eq 4656 -and
            $isFailure -and
            -not $isSuccess -and
            (Test-Item10bAuditSid ([string]$event.subject_user_sid) $ExpectedResearchSid) -and
            $null -ne $researchTargetKind
        ) {
            $researchDenial = $true
            if ($null -eq $researchEvent) {
                $researchEvent = [ordered]@{
                    event_id = 4656
                    outcome = 'FAILURE'
                    subject_user_sid = [string]$event.subject_user_sid
                    object_kind = $researchTargetKind
                    occurred_at = $occurredAt.ToUniversalTime().ToString('o').Replace('+00:00', 'Z')
                }
            }
        }
        if (
            [int]$event.event_id -eq 4663 -and
            $isSuccess -and
            -not $isFailure -and
            (Test-Item10bAuditSid ([string]$event.subject_user_sid) $ExpectedCustodianSid) -and
            $null -ne $custodianTargetKind
        ) {
            $custodianActivity = $true
            if ($null -eq $custodianEvent) {
                $custodianEvent = [ordered]@{
                    event_id = 4663
                    outcome = 'SUCCESS'
                    subject_user_sid = [string]$event.subject_user_sid
                    object_kind = $custodianTargetKind
                    occurred_at = $occurredAt.ToUniversalTime().ToString('o').Replace('+00:00', 'Z')
                }
            }
        }
    }

    [pscustomobject]@{
        research_denial_observed = $researchDenial
        custodian_activity_observed = $custodianActivity
        research_denial_event = $researchEvent
        custodian_activity_event = $custodianEvent
    }
}
