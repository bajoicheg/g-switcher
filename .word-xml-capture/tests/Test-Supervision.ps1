param([string]$Shell)
$ErrorActionPreference = 'Stop'
if ([string]::IsNullOrEmpty($Shell)) {
    $Shell = if ($PSVersionTable.PSEdition -eq 'Desktop') { Join-Path $PSHOME 'powershell.exe' } elseif ([Environment]::OSVersion.Platform -eq [PlatformID]::Win32NT) { Join-Path $PSHOME 'pwsh.exe' } else { Join-Path $PSHOME 'pwsh' }
}
. (Join-Path $PSScriptRoot '../WordXmlProbe.Core.ps1')
if (-not (Get-Command Invoke-ProbeChild -ErrorAction SilentlyContinue)) {
    function Invoke-ProbeChild { param($FilePath,$Arguments,$DeadlineSeconds) return [pscustomobject]@{TimedOut=$false;ExitCode=0;Reaped=$false} }
}
$short = Invoke-ProbeChild $Shell '-NoProfile -NonInteractive -Command "exit 7"' 10
if ($short.TimedOut -or $short.ExitCode -ne 7 -or -not $short.Reaped) { throw 'Completion must preserve the actual child exit code and reap it.' }
$watch = [Diagnostics.Stopwatch]::StartNew()
$hung = Invoke-ProbeChild $Shell '-NoProfile -NonInteractive -Command "Start-Sleep -Seconds 30"' 1
if (-not $hung.TimedOut -or -not $hung.Reaped -or $watch.Elapsed.TotalSeconds -gt 8) { throw 'Timeout must kill and reap the exact child without waiting for its sleep.' }
Write-Host 'SUPERVISION_TESTS_PASSED=2'
