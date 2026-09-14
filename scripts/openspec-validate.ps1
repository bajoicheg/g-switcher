$ErrorActionPreference = 'Stop'
$env:OPENSPEC_TELEMETRY = '0'

$package = '@fission-ai/openspec@1.13.0'
& npx --yes --package $package openspec validate --all --strict --no-interactive --report findings
$exitCode = $LASTEXITCODE
if ($exitCode -ne 0) {
    exit $exitCode
}
