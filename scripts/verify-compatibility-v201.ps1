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

# Core text-operation columns must be either demonstrated working or explicitly
# unsupported while preserving the user's original input. N/A is not meaningful
# for these capabilities because every required application is being assessed as
# a text-input target.
$CoreResults = @(
    "PASS",
    "UNSUPPORTED/FAIL-OPEN"
)

# Undo can be inapplicable when the corresponding operation is unsupported;
# sensitive-field testing can be inapplicable when an application exposes no
# password/PIN/credential field in the tested surface.
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

    Assert-Result -Application $application -Column "Auto" -Value $cells[3] -Allowed $CoreResults
    Assert-Result -Application $application -Column "Manual current word" -Value $cells[4] -Allowed $CoreResults
    Assert-Result -Application $application -Column "Selected text" -Value $cells[5] -Allowed $CoreResults
    Assert-Result -Application $application -Column "Undo" -Value $cells[6] -Allowed $OptionalResults
    Assert-Result -Application $application -Column "Password/sensitive fields" -Value $cells[7] -Allowed $OptionalResults
}

Write-Host "G-switcher 2.0.1 manual compatibility gate passed for all required applications." -ForegroundColor Green
