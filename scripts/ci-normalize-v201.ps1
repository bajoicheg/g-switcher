$ErrorActionPreference = 'Stop'

# This gate is intentionally read-only. Formatting and lockfile consistency are
# checked by subsequent cargo --locked/fmt steps; CI must never normalize or
# rewrite the branch it is validating.
$requiredFiles = @(
    'Cargo.toml',
    'Cargo.lock',
    'rust-toolchain.toml',
    'src/windows_runtime_v201.rs',
    'src/windows_runtime/selection.rs',
    'src/windows_runtime/uia_secure.rs',
    'src/windows_runtime/uia_text.rs',
    'src/windows_runtime/uia_modern.rs',
    'src/windows_runtime/cross_process_e2e.rs',
    'src/bin/g-switcher-e2e-helper.rs',
    'src/bin/g-switcher-failure-e2e.rs',
    'src/bin/g-switcher-compatibility.rs',
    'tests/browser_uia_adapter.rs',
    'manual-browser-test-2.0.1.html',
    'COMPATIBILITY_2.0.1.md',
    'MANUAL_TESTING_2.0.1.md'
)
foreach ($path in $requiredFiles) {
    if (-not (Test-Path -LiteralPath $path -PathType Leaf)) {
        throw "Required 2.0.1 source/release file is missing: $path"
    }
}

$toolchain = Get-Content -LiteralPath 'rust-toolchain.toml' -Raw
if ($toolchain -notmatch 'channel\s*=\s*"1\.98\.1"' -or $toolchain -notmatch '"rustfmt"' -or $toolchain -notmatch '"clippy"') {
    throw 'rust-toolchain.toml must pin Rust 1.98.1 with rustfmt and clippy for the 2.0.1 release candidate.'
}

$runtime = Get-Content -LiteralPath 'src/windows_runtime_v201.rs' -Raw
$selection = Get-Content -LiteralPath 'src/windows_runtime/selection.rs' -Raw
$uiaSecure = Get-Content -LiteralPath 'src/windows_runtime/uia_secure.rs' -Raw
$uiaModern = Get-Content -LiteralPath 'src/windows_runtime/uia_modern.rs' -Raw
$browserTest = Get-Content -LiteralPath 'tests/browser_uia_adapter.rs' -Raw
$manualBrowserPage = Get-Content -LiteralPath 'manual-browser-test-2.0.1.html' -Raw
$compatTool = Get-Content -LiteralPath 'src/bin/g-switcher-compatibility.rs' -Raw

$requiredRuntimeMarkers = @(
    'mod runtime_dispatch;',
    'mod uia_secure;',
    'static RUNTIME_WINDOW: AtomicIsize',
    'selection::replace_range_if_matches',
    'static CALLBACK_OVER_10MS: AtomicU64',
    'const SINGLE_INSTANCE_NAME: &str = "Local\\GSwitcher.SingleInstance.v0.8";'
)
foreach ($marker in $requiredRuntimeMarkers) {
    if (-not $runtime.Contains($marker)) {
        throw "Required hardened runtime marker is missing: $marker"
    }
}

$requiredSelectionMarkers = @(
    '#[path = "uia_modern.rs"]',
    'uia_modern::has_adapter(hwnd)',
    'uia_modern::replace_range_if_matches',
    'TextAdapter::ModernUiaValue'
)
foreach ($marker in $requiredSelectionMarkers) {
    if (-not $selection.Contains($marker)) {
        throw "Required modern selection adapter marker is missing: $marker"
    }
}

$requiredSecurityMarkers = @(
    'pub struct UiaElementId',
    'element.CurrentIsPassword()',
    'let element_id = runtime_id(&element)?;'
)
foreach ($marker in $requiredSecurityMarkers) {
    if (-not $uiaSecure.Contains($marker)) {
        throw "Required UIA security marker is missing: $marker"
    }
}

$requiredModernMarkers = @(
    'struct RuntimeId',
    'after.runtime_id != original_id',
    'rollback_if_exact',
    'UIA_TextPatternId',
    'UIA_ValuePatternId'
)
foreach ($marker in $requiredModernMarkers) {
    if (-not $uiaModern.Contains($marker)) {
        throw "Required fresh-context modern UIA marker is missing: $marker"
    }
}

foreach ($marker in @('--force-renderer-accessibility=complete', '--enable-features=UiaProvider', 'textarea', 'password')) {
    if (-not $browserTest.Contains($marker)) {
        throw "Required real-browser E2E marker is missing: $marker"
    }
}

foreach ($marker in @('id="auto"', 'id="manual"', 'id="selected"', 'id="race-a"', 'id="race-b"', 'type="password"')) {
    if (-not $manualBrowserPage.Contains($marker)) {
        throw "Required offline manual-browser test marker is missing: $marker"
    }
}
if ($manualBrowserPage -match '(?i)<script\b' -or $manualBrowserPage -match '(?i)https?://') {
    throw 'Offline manual-browser test page must contain no JavaScript or HTTP(S) dependency.'
}

foreach ($marker in @('"record"', '"resume"', '"verify"', 'CORE_PASS_ONLY', 'Microsoft Edge', 'Google Chrome')) {
    if (-not $compatTool.Contains($marker)) {
        throw "Required compiled compatibility-tool marker is missing: $marker"
    }
}

# No hidden clipboard/network fallback is allowed in production Rust source.
$forbiddenProductionPatterns = @(
    'OpenClipboard',
    'GetClipboardData',
    'SetClipboardData',
    'std::net::',
    'TcpStream',
    'UdpSocket',
    'WinHttp',
    'WinInet',
    'reqwest::'
)
$productionFiles = @(Get-ChildItem -LiteralPath 'src' -Recurse -File -Filter '*.rs')
foreach ($file in $productionFiles) {
    $text = Get-Content -LiteralPath $file.FullName -Raw
    foreach ($pattern in $forbiddenProductionPatterns) {
        if ($text.IndexOf($pattern, [System.StringComparison]::Ordinal) -ge 0) {
            throw "Forbidden clipboard/network API marker '$pattern' found in production source: $($file.FullName)"
        }
    }
}

& git diff --check
if ($LASTEXITCODE -ne 0) {
    throw 'git diff --check failed.'
}

$changes = git status --porcelain
if ($changes) {
    Write-Host 'Read-only source gate detected a dirty checkout:'
    git status --short
    throw 'CI checkout must remain clean before compilation.'
}

Write-Host '2.0.1 read-only source/privacy gate passed.'
