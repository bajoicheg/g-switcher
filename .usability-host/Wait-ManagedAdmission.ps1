$ErrorActionPreference = 'Stop'
if ($env:GITHUB_RUN_ATTEMPT -ne '1') { throw 'Only the reserved first attempt is admitted' }
$pinned = Get-Content .usability-host/host-launch-intent.json -Raw | ConvertFrom-Json
$headers = @{ Authorization = ('Bearer ' + $env:GH_TOKEN); Accept = 'application/vnd.github+json'; 'X-GitHub-Api-Version' = '2022-11-28'; 'Cache-Control' = 'no-cache' }
function Read-RepoJson([string]$Path, [string]$Ref) {
    $url = 'https://api.github.com/repos/bajoicheg/g-switcher/contents/' + $Path + '?ref=' + [uri]::EscapeDataString($Ref)
    $value = Invoke-RestMethod -Uri $url -Headers $headers -TimeoutSec 20
    return ([Text.Encoding]::UTF8.GetString([Convert]::FromBase64String($value.content)) | ConvertFrom-Json)
}
$deadline = [DateTime]::UtcNow.AddMinutes(4)
do {
    $whole = Read-RepoJson 'document.json' $pinned.admission_ref
    $doc = $whole.usability.host
    if ($doc.host_head -ne $env:GITHUB_SHA) { throw 'Different frozen host' }
    if ($doc.state -eq 'managed-admitted') {
        if ($doc.host_admission.run_id -ne [long]$env:GITHUB_RUN_ID -or $doc.host_admission.run_attempt -ne 1) { throw 'Different managed invocation' }
        $lease = Read-RepoJson 'lease.json' 'cdc/coordination'
        if ($lease.owner_id -ne $doc.managed_lease.owner_id -or $lease.generation -ne $doc.managed_lease.generation -or $lease.invocation.invocation_id -ne $doc.managed_lease.invocation_id) { throw 'Managed ownership changed' }
        if ($lease.source_ref -ne 'refs/heads/release/2.0.1' -or $null -eq $lease.external_guard -or $lease.finalization.state -ne 'active') { throw 'Managed state is not active and clear' }
        $now = [DateTimeOffset]::UtcNow
        $expires = [DateTimeOffset]::Parse($lease.expires_at_utc)
        $heartbeat = [DateTimeOffset]::Parse($lease.heartbeat_at_utc)
        if ($now -ge $expires -or ($now - $heartbeat).TotalSeconds -ge 600 -or $heartbeat -gt $now) { throw 'Managed ownership is stale or expired' }
        $jobs = Invoke-RestMethod -Uri ('https://api.github.com/repos/bajoicheg/g-switcher/actions/runs/' + $env:GITHUB_RUN_ID + '/attempts/1/jobs?per_page=100') -Headers $headers -TimeoutSec 20
        if ($jobs.total_count -gt 100) { throw 'Incomplete managed job lookup' }
        $controllers = @($jobs.jobs | Where-Object { $_.name -eq 'managed' })
        if ($controllers.Count -ne 1 -or $controllers[0].status -ne 'in_progress') { throw 'Managed controller job is not active' }
        if ($lease.external_guard.submission_claim.grant_id -ne $doc.windows_claim.grant_id -or $lease.external_guard.intent.binding.candidate_sha -ne $pinned.candidate_sha) { throw 'Different Windows submission claim' }
        $source = Invoke-RestMethod -Uri 'https://api.github.com/repos/bajoicheg/g-switcher/git/ref/heads/release/2.0.1' -Headers $headers -TimeoutSec 20
        if ($source.object.sha -ne $pinned.base) { throw 'Product source changed' }
        Write-Output ('MANAGED_COMPUTE_ADMITTED generation=' + $lease.generation)
        exit 0
    }
    if ($doc.state -notin @('prepared','claimed','windows-intent-prepared','windows-submitting')) { throw 'Managed controller reached another state' }
    if ([DateTime]::UtcNow -ge $deadline) { throw 'Managed admission deadline' }
    Start-Sleep -Seconds 5
} while ($true)
