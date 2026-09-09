param(
    [string]$Path = (Join-Path (Get-Location) "COMPATIBILITY_2.0.1.md")
)

$ErrorActionPreference = "Stop"
Set-StrictMode -Version Latest

$RequiredApplications = @(
    "Notepad",
    "Microsoft Word",
    "Microsoft Edge",
    "Google Chrome",
    "Telegram Desktop",
    "Visual Studio Code",
    "Windows Terminal"
)

$AllowedResults = @(
    "PASS",
    "N/A",
    "UNSUPPORTED/FAIL-OPEN"
)

if (-not (Test-Path -LiteralPath $Path -PathType Leaf)) {
    throw "Missing compatibility matrix: $Path"
}

$lines = @(Get-Content -LiteralPath $Path)
$start = [Array]::IndexOf($lines, "## Manual application matrix")
if ($start -lt 0) {
    throw "Manual application matrix section is missing from $Path."
}

$table = @()
for ($i = $start + 1; $i -lt $lines.Count; $i++) {
    if ($lines[$i] -match '^##\s+') {
        break
    }
    if ($lines[$i] -match '^\|') {
        $table += $lines[$i]
    }
}

foreach ($application in $RequiredApplications) {
    $pattern = '^\|\s*' + [regex]::Escape($application) + '\s*\|'
    $matches = @($table | Where-Object { $_ -match $pattern })
    if ($matches.Count -ne 1) {
        throw "Expected exactly one manual compatibility row for $application, found $($matches.Count)."
    }

    # The first eight cells are machine-validated. Result/notes is intentionally
    # free text and may contain escaped pipes, so extra split cells after index 7
    # are ignored by the publication gate.
    $cells = @($matches[0].Trim().Trim('|').Split('|') | ForEach-Object { $_.Trim() })
    if ($cells.Count -lt 9) {
        throw "Malformed compatibility row for $application."
    }

    $version = $cells[1]
    $windowsBuild = $cells[2]
    foreach ($metadata in @($version, $windowsBuild)) {
        if ([string]::IsNullOrWhiteSpace($metadata) -or $metadata -match '^(?i:PENDING|UNKNOWN)$') {
            throw "Compatibility metadata is incomplete for $application."
        }
    }

    foreach ($index in 3..7) {
        $result = $cells[$index].ToUpperInvariant()
        if ($AllowedResults -notcontains $result) {
            throw "Compatibility gate for $application contains blocking result '$($cells[$index])'. Allowed: $($AllowedResults -join ', ')."
        }
    }
}

Write-Host "G-switcher 2.0.1 manual compatibility gate passed for all required applications." -ForegroundColor Green
