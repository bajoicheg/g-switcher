param(
    [string]$OutputPath = (Join-Path (Get-Location) "compatibility-results-2.0.1.md"),
    [switch]$ScaffoldOnly
)

$ErrorActionPreference = "Stop"
Set-StrictMode -Version Latest

$AllowedResults = @(
    "PASS",
    "FAIL",
    "UNSUPPORTED/FAIL-OPEN",
    "N/A",
    "PENDING"
)

$Applications = @(
    [pscustomobject]@{ Name = "Notepad"; Commands = @("notepad.exe"); RegistryPatterns = @("Windows Notepad", "Notepad") },
    [pscustomobject]@{ Name = "Microsoft Word"; Commands = @("WINWORD.EXE"); RegistryPatterns = @("Microsoft 365", "Microsoft Office", "Microsoft Word") },
    [pscustomobject]@{ Name = "Microsoft Edge"; Commands = @("msedge.exe"); RegistryPatterns = @("Microsoft Edge") },
    [pscustomobject]@{ Name = "Google Chrome"; Commands = @("chrome.exe"); RegistryPatterns = @("Google Chrome") },
    [pscustomobject]@{ Name = "Telegram Desktop"; Commands = @("Telegram.exe"); RegistryPatterns = @("Telegram Desktop") },
    [pscustomobject]@{ Name = "Visual Studio Code"; Commands = @("Code.exe", "code.cmd"); RegistryPatterns = @("Microsoft Visual Studio Code", "Visual Studio Code") },
    [pscustomobject]@{ Name = "Windows Terminal"; Commands = @("wt.exe"); RegistryPatterns = @("Windows Terminal") }
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

    $version = Get-ExecutableVersion -Commands $Application.Commands
    if (-not [string]::IsNullOrWhiteSpace($version)) {
        return $version
    }

    $version = Get-RegistryVersion -Patterns $Application.RegistryPatterns
    if (-not [string]::IsNullOrWhiteSpace($version)) {
        return $version
    }

    return "UNKNOWN"
}

function Read-ValidatedResult {
    param(
        [string]$Label,
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
        $match = $AllowedResults | Where-Object { $_ -eq $normalized } | Select-Object -First 1
        if ($null -ne $match) {
            return $match
        }

        Write-Host "Допустимые значения: $($AllowedResults -join ', ')" -ForegroundColor Yellow
    }
}

function Read-Notes {
    if ($ScaffoldOnly) {
        return ""
    }

    return (Read-Host "Result / notes (одна строка)").Trim()
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
Write-Host "Перед фиксацией результата для каждого приложения выполните 8 кейсов из COMPATIBILITY_2.0.1.md." -ForegroundColor Yellow
Write-Host "Не используйте реальные пароли, PIN, OTP или другие секреты." -ForegroundColor Yellow
Write-Host "Для неподдерживаемого контрола фиксируйте UNSUPPORTED/FAIL-OPEN, а не PASS." -ForegroundColor Yellow
Write-Host ""

foreach ($application in $Applications) {
    $version = Get-AppVersion -Application $application
    Write-Host "=== $($application.Name) ===" -ForegroundColor Cyan
    Write-Host "Detected version: $version"

    $auto = Read-ValidatedResult -Label "Auto"
    $manual = Read-ValidatedResult -Label "Manual current word"
    $selected = Read-ValidatedResult -Label "Selected text"
    $undo = Read-ValidatedResult -Label "Undo"
    $sensitive = Read-ValidatedResult -Label "Password/sensitive fields"
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
    "# G-switcher 2.0.1 — manual compatibility results",
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
    "Allowed result values: PASS, FAIL, UNSUPPORTED/FAIL-OPEN, N/A, PENDING.",
    "",
    "Release rule: any PENDING row or any failure that can corrupt text or touch a protected field keeps 2.0.1 blocked."
)

$directory = Split-Path -Parent $OutputPath
if (-not [string]::IsNullOrWhiteSpace($directory)) {
    New-Item -ItemType Directory -Path $directory -Force | Out-Null
}

$lines | Set-Content -LiteralPath $OutputPath -Encoding UTF8
Write-Host "Saved: $OutputPath" -ForegroundColor Green

if ($ScaffoldOnly) {
    Write-Host "Scaffold-only mode: all result fields remain PENDING." -ForegroundColor Yellow
}
