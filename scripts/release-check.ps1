param(
    [string]$ExePath = "target/release/g-switcher.exe"
)

$ErrorActionPreference = "Stop"

if (-not (Test-Path -LiteralPath $ExePath)) {
    throw "Release executable not found: $ExePath"
}

$exe = (Resolve-Path -LiteralPath $ExePath).Path

# Build forbidden names dynamically so the gate does not contain the forbidden
# strings it is intended to detect.
$forbiddenBrandTokens = @(
    ([string]::Concat('runto', '-', 'privacy')),
    ([string]::Concat('privacy', '-', 'switcher')),
    ([string]::Concat('R', 'Switcher')),
    ([string]::Concat('vraz', 'raz'))
)
$licenseToken = [string]::Concat('M', 'I', 'T')
$licenseRegex = "(?i)(?<![A-Za-z])$([regex]::Escape($licenseToken))(?![A-Za-z])"
$textExtensions = @('.rs', '.toml', '.md', '.yml', '.yaml', '.ps1', '.txt')

foreach ($path in (& git ls-files)) {
    if ($textExtensions -notcontains [System.IO.Path]::GetExtension($path).ToLowerInvariant()) {
        continue
    }
    $content = Get-Content -LiteralPath $path -Raw
    foreach ($token in $forbiddenBrandTokens) {
        if ($content.IndexOf($token, [System.StringComparison]::OrdinalIgnoreCase) -ge 0) {
            throw "Forbidden legacy brand token found in tracked source: $path"
        }
    }
    if ([regex]::IsMatch($content, $licenseRegex)) {
        throw "Forbidden license token found in tracked source: $path"
    }
}

$item = Get-Item -LiteralPath $exe
$version = $item.VersionInfo
if ($version.FileDescription -ne 'G-switcher') {
    throw "Unexpected FileDescription: $($version.FileDescription)"
}
if ($version.ProductName -ne 'G-switcher') {
    throw "Unexpected ProductName: $($version.ProductName)"
}
if ($version.FileVersion -ne '1.0.9.0') {
    throw "Unexpected FileVersion: $($version.FileVersion)"
}
if ($version.ProductVersion -ne '1.0.9') {
    throw "Unexpected ProductVersion: $($version.ProductVersion)"
}

$bytes = [System.IO.File]::ReadAllBytes($exe)
$ascii = [System.Text.Encoding]::ASCII.GetString($bytes)
$utf16 = [System.Text.Encoding]::Unicode.GetString($bytes)
foreach ($token in $forbiddenBrandTokens) {
    if ($ascii.IndexOf($token, [System.StringComparison]::OrdinalIgnoreCase) -ge 0 -or
        $utf16.IndexOf($token, [System.StringComparison]::OrdinalIgnoreCase) -ge 0) {
        throw "Forbidden legacy brand token found in release executable"
    }
}

$stream = [System.IO.File]::OpenRead($exe)
$reader = [System.IO.BinaryReader]::new($stream)
try {
    $stream.Position = 0x3c
    $peOffset = $reader.ReadInt32()
    $stream.Position = $peOffset
    if ($reader.ReadUInt32() -ne 0x00004550) {
        throw "Invalid PE signature"
    }
    $stream.Position = $peOffset + 4 + 20 + 68
    $subsystem = $reader.ReadUInt16()
    if ($subsystem -ne 2) {
        throw "Release executable is not Windows GUI subsystem; subsystem=$subsystem"
    }
}
finally {
    $reader.Dispose()
    $stream.Dispose()
}

$hash = (Get-FileHash -LiteralPath $exe -Algorithm SHA256).Hash.ToLowerInvariant()
$hashPath = "$exe.sha256"
Set-Content -LiteralPath $hashPath -Value "$hash  g-switcher.exe" -Encoding ascii -NoNewline

Write-Host "Release checks passed"
Write-Host "SHA256: $hash"
