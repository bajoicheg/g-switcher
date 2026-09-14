$ErrorActionPreference = 'Stop'

$package = '@fission-ai/openspec@1.13.0'
$expectedSkills = @(
    'openspec-apply-change',
    'openspec-archive-change',
    'openspec-explore',
    'openspec-propose',
    'openspec-sync-specs',
    'openspec-update-change',
    'openspec-verify-change'
) | Sort-Object

$hadXdgConfigHome = Test-Path Env:XDG_CONFIG_HOME
$oldXdgConfigHome = $env:XDG_CONFIG_HOME
$hadTelemetry = Test-Path Env:OPENSPEC_TELEMETRY
$oldTelemetry = $env:OPENSPEC_TELEMETRY
$tempRoot = Join-Path ([System.IO.Path]::GetTempPath()) ('g-switcher-openspec-' + [guid]::NewGuid().ToString('N'))

try {
    $configDir = Join-Path $tempRoot 'openspec'
    New-Item -ItemType Directory -Force -Path $configDir | Out-Null

    $profile = @{
        profile = 'custom'
        delivery = 'skills'
        workflows = @('propose', 'explore', 'apply', 'update', 'sync', 'archive', 'verify')
    } | ConvertTo-Json -Depth 4
    Set-Content -LiteralPath (Join-Path $configDir 'config.json') -Value $profile -Encoding UTF8

    $env:XDG_CONFIG_HOME = $tempRoot
    $env:OPENSPEC_TELEMETRY = '0'

    & npx --yes --package $package openspec init --tools codex --profile custom --no-animation
    if ($LASTEXITCODE -ne 0) {
        throw "OpenSpec skill refresh failed with exit code $LASTEXITCODE."
    }

    $skillsRoot = Join-Path (Get-Location) '.agents/skills'
    if (-not (Test-Path -LiteralPath $skillsRoot -PathType Container)) {
        throw "Expected Codex skill directory was not generated: $skillsRoot"
    }

    $actualSkills = @(
        Get-ChildItem -LiteralPath $skillsRoot -Directory |
            Where-Object { $_.Name -like 'openspec-*' } |
            Select-Object -ExpandProperty Name |
            Sort-Object
    )

    if (($actualSkills -join "`n") -ne ($expectedSkills -join "`n")) {
        throw "Unexpected OpenSpec skill inventory. Expected: $($expectedSkills -join ', '). Actual: $($actualSkills -join ', ')."
    }

    foreach ($skill in $expectedSkills) {
        $skillFile = Join-Path $skillsRoot "$skill/SKILL.md"
        if (-not (Test-Path -LiteralPath $skillFile -PathType Leaf)) {
            throw "Missing generated skill file: $skillFile"
        }
    }

    Write-Host "OpenSpec Codex skills refreshed from ${package}: $($expectedSkills.Count) workflows."
}
finally {
    if ($hadXdgConfigHome) {
        $env:XDG_CONFIG_HOME = $oldXdgConfigHome
    }
    else {
        Remove-Item Env:XDG_CONFIG_HOME -ErrorAction SilentlyContinue
    }

    if ($hadTelemetry) {
        $env:OPENSPEC_TELEMETRY = $oldTelemetry
    }
    else {
        Remove-Item Env:OPENSPEC_TELEMETRY -ErrorAction SilentlyContinue
    }

    Remove-Item -LiteralPath $tempRoot -Recurse -Force -ErrorAction SilentlyContinue
}
