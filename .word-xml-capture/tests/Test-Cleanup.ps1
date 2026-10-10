$ErrorActionPreference = 'Stop'
$errors = $null; $tokens = $null
$ast = [System.Management.Automation.Language.Parser]::ParseFile((Join-Path $PSScriptRoot '../Run-WordXmlProbe.ps1'),[ref]$tokens,[ref]$errors)
if ($errors.Count) { throw 'Probe syntax failed.' }
$main = @($ast.EndBlock.Statements | Where-Object { $_ -is [System.Management.Automation.Language.TryStatementAst] })[-1]
$cleanup = [scriptblock]::Create($main.Finally.Extent.Text.TrimStart('{').TrimEnd('}'))
function Save-ProbeReport { throw 'Injected report I/O failure' }
function Stage { param($Name) Save-ProbeReport }
function Release-Com { param($Value) $script:Released++ }
function Assert-OwnedWord { param($Count) if ($script:RejectGuard) { throw 'Injected lost ownership' } }
function Reset-Case {
    $script:Closed = $false; $script:Quit = $false; $script:Released = 0; $script:RejectGuard = $false
    $script:Report = [ordered]@{status='MEASURED_CHECKS_PASSED';stage='stored-original-xml-undo';cleanup_complete=$false}
    $script:Owned=$true; $script:RecordOpen=$false; $script:DocumentIdentity=[IntPtr]::Zero; $script:UndoRecord=$null
    $script:Document = [pscustomobject]@{}
    $script:Document | Add-Member ScriptMethod Close { param($Save) $script:Closed=$true }
    $script:Word = [pscustomobject]@{}
    $script:Word | Add-Member ScriptMethod Quit { param($Save) $script:Quit=$true }
}
Reset-Case
try { & $cleanup } catch { }
if (-not $script:Closed -or -not $script:Quit -or $script:Released -ne 3) { throw 'Report I/O failure must not skip native cleanup or RCW releases.' }
if ($script:Report.status -ceq 'MEASURED_CHECKS_PASSED') { throw 'Failed report persistence must not leave a successful result.' }
Reset-Case
$script:RejectGuard = $true
try { & $cleanup } catch { }
if ($script:Closed -or $script:Quit -or $script:Released -ne 3) { throw 'Lost ownership must prevent Close/Quit but still release RCWs.' }
if ($script:Report.status -ceq 'MEASURED_CHECKS_PASSED' -or $script:Report.cleanup_complete) { throw 'Lost ownership cannot pass cleanup.' }
Write-Host 'CLEANUP_TESTS_PASSED=2'
