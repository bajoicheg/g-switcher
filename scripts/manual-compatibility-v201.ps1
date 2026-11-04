param(
    [string]$OutputPath = (Join-Path (Get-Location) "compatibility-results-2.0.1.md"),
    [switch]$ScaffoldOnly
)

$ErrorActionPreference = "Stop"
Set-StrictMode -Version Latest

# Keep this script ASCII-only so it parses correctly in Windows PowerShell 5.1
# when the repository/artifact file is UTF-8 without a BOM.
$CoreInteractiveResults = @(
    "PASS",
    "FAIL",
    "UNSUPPORTED/FAIL-OPEN",
    "PENDING"
)

$OptionalInteractiveResults = @(
    "PASS",
    "FAIL",
    "UNSUPPORTED/FAIL-OPEN",
    "N/A",
    "PENDING"
)

$Applications = @(
    [pscustomobject]@{
        Name = "Notepad"
        Commands = @("notepad.exe")
        RegistryPatterns = @("Windows Notepad", "Notepad")
        PackagePatterns = @("Microsoft.WindowsNotepad")
        RegistryFirst = $false
    },
    [pscustomobject]@{
        Name = "Microsoft Word"
        Commands = @("WINWORD.EXE")
        RegistryPatterns = @("Microsoft 365", "Microsoft Office", "Microsoft Word")
        PackagePatterns = @()
        RegistryFirst = $false
    },
    [pscustomobject]@{
        Name = "Microsoft Edge"
        Commands = @("msedge.exe")
        RegistryPatterns = @("Microsoft Edge")
        PackagePatterns = @()
        RegistryFirst = $false
    },
    [pscustomobject]@{
        Name = "Google Chrome"
        Commands = @("chrome.exe")
        RegistryPatterns = @("Google Chrome")
        PackagePatterns = @()
        RegistryFirst = $false
    },
    [pscustomobject]@{
        Name = "Telegram Desktop"
        Commands = @("Telegram.exe")
        RegistryPatterns = @("Telegram Desktop")
        PackagePatterns = @("TelegramMessengerLLP.TelegramDesktop")
        RegistryFirst = $false
    },
    [pscustomobject]@{
        Name = "Visual Studio Code"
        Commands = @("Code.exe", "code.cmd")
        RegistryPatterns = @("Microsoft Visual Studio Code", "Visual Studio Code")
        PackagePatterns = @()
        # A generic Code.exe elsewhere on PATH can belong to another product.
        # Prefer the uninstall registration, whose DisplayVersion identifies
        # the actual Visual Studio Code installation under test.
        RegistryFirst = $true
    },
    [pscustomobject]@{
        Name = "Windows Terminal"
        Commands = @("wt.exe")
        RegistryPatterns = @("Windows Terminal")
        PackagePatterns = @("Microsoft.WindowsTerminal", "Microsoft.WindowsTerminalPreview")
        RegistryFirst = $false
    }
)

function Get-WindowsBuild {
    try {
        $os = Get-CimInstance -ClassName Win32_OperatingSystem
        if ($null -ne $os -and -not [string]::IsNullOrWhiteSpace($os.BuildNumber)) {
            return [string]$os.BuildNumber
        }
    }
    catch {
        # Fall back to the local process view when CIM is unavailable.
    }

    return [string][Environment]::OSVersion.Version.Build
}

function Get-AppxVersion {
    param([string[]]$Patterns)

    if ($Patterns.Count -eq 0) {
        return $null
    }

    try {
        $command = Get-Command Get-AppxPackage -ErrorAction Stop
        if ($null -eq $command) {
            return $null
        }
    }
    catch {
        return $null
    }

    foreach ($pattern in $Patterns) {
        try {
            $package = Get-AppxPackage -Name $pattern -ErrorAction SilentlyContinue |
                Sort-Object -Property Version -Descending |
                Select-Object -First 1
            if ($null -ne $package -and $null -ne $package.Version) {
                $version = [string]$package.Version
                if (-not [string]::IsNullOrWhiteSpace($version)) {
                    return $version.Trim()
                }
            }
        }
        catch {
            continue
        }
    }

    return $null
}

function Get-ExecutableVersion {
    param([string[]]$Commands)

    foreach ($commandName in $Commands) {
        try {
            $command = Get-Command $commandName -ErrorAction Stop | Select-Object -First 1
            if ($null -eq $command -or [string]::IsNullOrWhiteSpace($command.Source)) {
                continue
            }
            if (-not (Test-Path -LiteralPath $command.Source -PathType Leaf)) {
                continue
            }
            $item = Get-Item -LiteralPath $command.Source
            $version = $item.VersionInfo.ProductVersion
            if ([string]::IsNullOrWhiteSpace($version)) {
                $version = $item.VersionInfo.FileVersion
            }
            if (-not [string]::IsNullOrWhiteSpace($version)) {
                return $version.Trim()
            }
        }
        catch {
            continue
        }
    }

    return $null
}

function Get-RegistryVersion {
    param([string[]]$Patterns)

    $roots = @(
        "HKLM:\SOFTWARE\Microsoft\Windows\CurrentVersion\Uninstall\*",
        "HKLM:\SOFTWARE\WOW6432Node\Microsoft\Windows\CurrentVersion\Uninstall\*",
        "HKCU:\SOFTWARE\Microsoft\Windows\CurrentVersion\Uninstall\*"
    )

    foreach ($root in $roots) {
        try {
            $entries = Get-ItemProperty -Path $root -ErrorAction SilentlyContinue
            foreach ($pattern in $Patterns) {
                $match = $entries |
                    Where-Object {
                        -not [string]::IsNullOrWhiteSpace($_.DisplayName) -and
                        $_.DisplayName -like "*$pattern*" -and
                        -not [string]::IsNullOrWhiteSpace($_.DisplayVersion)
                    } |
                    Select-Object -First 1
                if ($null -ne $match) {
                    return ([string]$match.DisplayVersion).Trim()
                }
            }
        }
        catch {
            continue
        }
    }

    return $null
}

function Get-AppVersion {
    param($Application)

    # Prefer the package version for Store/MSIX applications. In particular,
    # modern Notepad and Windows Terminal may expose an execution alias whose
    # file version describes the Windows stub rather than the app under test.
    $version = Get-AppxVersion -Patterns $Application.PackagePatterns
    if (-not [string]::IsNullOrWhiteSpace($version)) {
        return $version
    }

    if ($Application.RegistryFirst) {
        $version = Get-RegistryVersion -Patterns $Application.RegistryPatterns
        if (-not [string]::IsNullOrWhiteSpace($version)) {
            return $version
        }
    }

    $version = Get-ExecutableVersion -Commands $Application.Commands
    if (-not [string]::IsNullOrWhiteSpace($version)) {
        return $version
    }

    if (-not $Application.RegistryFirst) {
        $version = Get-RegistryVersion -Patterns $Application.RegistryPatterns
        if (-not [string]::IsNullOrWhiteSpace($version)) {
            return $version
        }
    }

    return "UNKNOWN"
}

function Read-ExplicitVersion {
    param(
        [string]$ApplicationName,
        [string]$DetectedVersion
    )

    if ($ScaffoldOnly -or $DetectedVersion -ne "UNKNOWN") {
        return $DetectedVersion
    }

    while ($true) {
        $answer = (Read-Host "Could not detect $ApplicationName version. Enter the exact tested application version").Trim()
        if (
            -not [string]::IsNullOrWhiteSpace($answer) -and
            $answer -notmatch '^(?i:PENDING|UNKNOWN|N/A|NOT INSTALLED|UNAVAILABLE)$'
        ) {
            return $answer
        }
        Write-Host "A real tested application version is required; UNKNOWN/N/A/NOT INSTALLED cannot pass the release gate." -ForegroundColor Yellow
    }
}

function Read-ValidatedResult {
    param(
        [string]$Label,
        [string[]]$Allowed,
        [string]$Default = "PENDING"
    )

    if ($ScaffoldOnly) {
        return $Default
    }

    while ($true) {
        $answer = Read-Host "$Label [$Default]"
        if ([string]::IsNullOrWhiteSpace($answer)) {
            return $Default
        }

        $normalized = $answer.Trim().ToUpperInvariant()
        $match = $Allowed | Where-Object { $_ -eq $normalized } | Select-Object -First 1
        if ($null -ne $match) {
            return $match
        }

        Write-Host "Allowed values for this field: $($Allowed -join ', ')" -ForegroundColor Yellow
    }
}

function Read-Notes {
    if ($ScaffoldOnly) {
        return ""
    }

    return (Read-Host "Result / notes (one line)").Trim()
}

function Escape-MarkdownCell {
    param([AllowEmptyString()][string]$Value)

    if ($null -eq $Value) {
        return ""
    }

    return $Value.Replace("|", "\|").Replace("`r", " ").Replace("`n", " ")
}

$windowsBuild = Get-WindowsBuild
$rows = @()

Write-Host "G-switcher 2.0.1 manual compatibility gate" -ForegroundColor Cyan
Write-Host "Windows build: $windowsBuild"
Write-Host ""
Write-Host "Before recording a result for each application, complete the 8 cases in COMPATIBILITY_2.0.1.md." -ForegroundColor Yellow
Write-Host "Do not use real passwords, PINs, OTPs, API keys, or other secrets." -ForegroundColor Yellow
Write-Host "Auto/Manual/Selected do not allow N/A: use PASS, FAIL, or UNSUPPORTED/FAIL-OPEN." -ForegroundColor Yellow
Write-Host "N/A is allowed only for Undo and Password/sensitive fields when the check is genuinely not applicable." -ForegroundColor Yellow
Write-Host ""

foreach ($application in $Applications) {
    $detectedVersion = Get-AppVersion -Application $application
    $version = Read-ExplicitVersion -ApplicationName $application.Name -DetectedVersion $detectedVersion
    Write-Host "=== $($application.Name) ===" -ForegroundColor Cyan
    Write-Host "Version tested: $version"

    $auto = Read-ValidatedResult -Label "Auto" -Allowed $CoreInteractiveResults
    $manual = Read-ValidatedResult -Label "Manual current word" -Allowed $CoreInteractiveResults
    $selected = Read-ValidatedResult -Label "Selected text" -Allowed $CoreInteractiveResults
    $undo = Read-ValidatedResult -Label "Undo" -Allowed $OptionalInteractiveResults
    $sensitive = Read-ValidatedResult -Label "Password/sensitive fields" -Allowed $OptionalInteractiveResults
    $notes = Read-Notes

    $rows += [pscustomobject]@{
        Application = $application.Name
        Version = $version
        WindowsBuild = $windowsBuild
        Auto = $auto
        Manual = $manual
        Selected = $selected
        Undo = $undo
        Sensitive = $sensitive
        Notes = $notes
    }
    Write-Host ""
}

$lines = @(
    "# G-switcher 2.0.1 - manual compatibility results",
    "",
    "Generated locally: $(Get-Date -Format 'yyyy-MM-dd HH:mm:ss zzz')",
    "",
    "## Manual application matrix",
    "",
    "| Application | Version tested | Windows build | Auto | Manual current word | Selected text | Undo | Password/sensitive fields | Result / notes |",
    "|---|---|---|---|---|---|---|---|---|"
)

foreach ($row in $rows) {
    $lines += "| $(Escape-MarkdownCell $row.Application) | $(Escape-MarkdownCell $row.Version) | $(Escape-MarkdownCell $row.WindowsBuild) | $(Escape-MarkdownCell $row.Auto) | $(Escape-MarkdownCell $row.Manual) | $(Escape-MarkdownCell $row.Selected) | $(Escape-MarkdownCell $row.Undo) | $(Escape-MarkdownCell $row.Sensitive) | $(Escape-MarkdownCell $row.Notes) |"
}

$lines += @(
    "",
    "Core columns (Auto, Manual current word, Selected text): PASS, FAIL, UNSUPPORTED/FAIL-OPEN, PENDING.",
    "Undo and Password/sensitive fields: PASS, FAIL, UNSUPPORTED/FAIL-OPEN, N/A, PENDING.",
    "",
    "Release rule: any PENDING or FAIL blocks 2.0.1 publication. N/A is accepted only in the optional columns; unsupported text controls must be explicitly verified as fail-open."
)

$directory = Split-Path -Parent $OutputPath
if (-not [string]::IsNullOrWhiteSpace($directory)) {
    New-Item -ItemType Directory -Path $directory -Force | Out-Null
}

$lines | Set-Content -LiteralPath $OutputPath -Encoding UTF8
Write-Host "Saved: $OutputPath" -ForegroundColor Green

if ($ScaffoldOnly) {
    Write-Host "Scaffold-only mode: all result fields remain PENDING; undetected versions remain UNKNOWN by design." -ForegroundColor Yellow
}
