param([string]$Root = (Join-Path $PSScriptRoot '..'))
$ErrorActionPreference = 'Stop'
$files = @(Get-ChildItem -LiteralPath $Root -Filter '*.ps1' -Recurse)
if ($files.Count -lt 4) { throw 'Expected all probe and test scripts.' }
foreach ($file in $files) {
    $errors = $null; $tokens = $null
    [void][System.Management.Automation.Language.Parser]::ParseFile($file.FullName,[ref]$tokens,[ref]$errors)
    if ($errors.Count -ne 0) { throw ('Parse failed: ' + $file.Name + ': ' + ($errors | Out-String)) }
    if (@([IO.File]::ReadAllBytes($file.FullName) | Where-Object { $_ -gt 127 }).Count -ne 0) { throw ('Non-ASCII script would be ambiguous under Windows PowerShell 5.1: ' + $file.Name) }
}
Write-Host ('PARSED_SCRIPTS=' + $files.Count)
