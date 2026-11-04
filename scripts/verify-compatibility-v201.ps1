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

# These are product-critical targets for 2.0.1. A safe no-op is not enough:
# Auto, manual current-word conversion, selected-text conversion and Undo must
# actually work in ordinary editable fields. Password/sensitive fields are
# evaluated separately and must remain protected.
$FullSupportApplications = @(
    "Notepad",
    "Microsoft Edge",
    "Google Chrome"
)

# Other required applications may still be explicitly documented as unsupported
# if their ordinary input remains unchanged. N/A is never valid for a core text
# operation because every row represents a text-input target.
$CoreResults = @(
    "PASS",
    "UNSUPPORTED/FAIL-OPEN"
)

$OptionalResults = @(
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

function Assert-Result {
    param(
        [string]$Application,
        [string]$Column,
        [string]$Value,
        [string[]]$Allowed
    )

    $normalized = $Value.ToUpperInvariant()
    if ($Allowed -notcontains $normalized) {
        throw "Compatibility gate for $Application / $Column contains blocking result '$Value'. Allowed: $($Allowed -join ', ')."
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
        if (
            [string]::IsNullOrWhiteSpace($metadata) -or
            $metadata -match '^(?i:PENDING|UNKNOWN|N/A|NOT INSTALLED|UNAVAILABLE)$'
        ) {
            throw "Compatibility metadata is incomplete for $application."
        }
    }

    $coreAllowed = $CoreResults
    $undoAllowed = $OptionalResults
    if ($FullSupportApplications -contains $application) {
        $coreAllowed = @("PASS")
        $undoAllowed = @("PASS")
    }

    Assert-Result -Application $application -Column "Auto" -Value $cells[3] -Allowed $coreAllowed
    Assert-Result -Application $application -Column "Manual current word" -Value $cells[4] -Allowed $coreAllowed
    Assert-Result -Application $application -Column "Selected text" -Value $cells[5] -Allowed $coreAllowed
    Assert-Result -Application $application -Column "Undo" -Value $cells[6] -Allowed $undoAllowed
    Assert-Result -Application $application -Column "Password/sensitive fields" -Value $cells[7] -Allowed $OptionalResults
}

Write-Host "G-switcher 2.0.1 manual compatibility gate passed for all required applications." -ForegroundColor Green
