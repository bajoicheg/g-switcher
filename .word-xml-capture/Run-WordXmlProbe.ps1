param(
    [string]$OutputRoot = (Join-Path $PSScriptRoot 'results'),
    [ValidateRange(20,180)][int]$DeadlineSeconds = 120,
    [switch]$Worker,
    [string]$OutputDirectory,
    [int]$ParentProcessId,
    [long]$ParentStartTicks
)
$ErrorActionPreference = 'Stop'
Set-StrictMode -Version Latest
. (Join-Path $PSScriptRoot 'WordXmlProbe.Core.ps1')
$script:Report = [ordered]@{
    schema = 'g-switcher-word-xml-disposable-probe/v1'
    probe_version = '2026-10-10-1'
    product_commit = '830abfe7ef99a7c6e8ca8291fc7ae802ac5edd78'
    status = 'NOT_RUN'
    stage = 'initializing'
    generated_test_content_only = $true
    product_integration = $false
    complete_effective_format_proof = $false
    product_grammar_acceptance = 'NOT_TESTED'
    native_word_calls = $false
    steps = @()
    word_process_id = $null
    word_start_ticks = $null
    word_version = $null
    cleanup_complete = $false
    source_xml_sha256 = $null
    transformed_xml_sha256 = $null
    source_package_parts = @()
    results = [ordered]@{}
}
function Save-ProbeReport {
    if ([string]::IsNullOrEmpty($OutputDirectory)) { return }
    $temporary = Join-Path $OutputDirectory 'report.tmp'
    [IO.File]::WriteAllText($temporary, ($script:Report | ConvertTo-Json -Depth 20), [Text.UTF8Encoding]::new($false))
    Move-Item -LiteralPath $temporary -Destination (Join-Path $OutputDirectory 'report.json') -Force
}
function Stage { param([string]$Name) $script:Report.stage = $Name; Save-ProbeReport }
function Release-Com { param($Value) if ($null -ne $Value -and [Runtime.InteropServices.Marshal]::IsComObject($Value)) { [void][Runtime.InteropServices.Marshal]::FinalReleaseComObject($Value) } }

if (-not $Worker) {
    if ([Environment]::OSVersion.Platform -ne [PlatformID]::Win32NT) { throw 'Windows with installed desktop Word is required.' }
    $OutputDirectory = Join-Path ([IO.Path]::GetFullPath($OutputRoot)) ((Get-Date -Format 'yyyyMMdd-HHmmss') + '-' + [Guid]::NewGuid().ToString('N'))
    [void][IO.Directory]::CreateDirectory($OutputDirectory)
    Save-ProbeReport
    $self = Get-Process -Id $PID
    $shell = Join-Path $env:SystemRoot 'System32/WindowsPowerShell/v1.0/powershell.exe'
    # Windows paths cannot contain a quote. File arguments remain data, never expressions.
    foreach ($path in @($PSCommandPath,$OutputDirectory)) { if ($path.Contains('"')) { throw 'Invalid path.' } }
    $arguments = '-NoProfile -NonInteractive -STA -ExecutionPolicy Bypass -File "' + $PSCommandPath + '" -Worker -OutputDirectory "' + $OutputDirectory + '" -ParentProcessId ' + $PID + ' -ParentStartTicks ' + $self.StartTime.ToUniversalTime().Ticks
    $outcome = Invoke-ProbeChild $shell $arguments $DeadlineSeconds
    $path = Join-Path $OutputDirectory 'report.json'
    if ($outcome.TimedOut) {
        if (Test-Path -LiteralPath $path) {
            try { $script:Report = Get-Content -LiteralPath $path -Raw | ConvertFrom-Json } catch { }
        }
        $script:Report.status = 'UNKNOWN_TIMEOUT'
        $script:Report.cleanup_complete = $false
        Save-ProbeReport
        Write-Host "Timeout. No automatic retry. The private test Word instance may remain open. Report: $path"
        exit 2
    }
    Write-Host ('Report: ' + $path)
    exit $outcome.ExitCode
}

if ([Environment]::OSVersion.Platform -ne [PlatformID]::Win32NT -or [Threading.Thread]::CurrentThread.ApartmentState -ne [Threading.ApartmentState]::STA) { throw 'Worker requires Windows STA.' }
if ([string]::IsNullOrEmpty($OutputDirectory) -or -not [IO.Directory]::Exists($OutputDirectory)) { throw 'Output directory is required.' }
function Assert-Parent {
    $parent = Get-Process -Id $ParentProcessId -ErrorAction Stop
    if ($ParentProcessId -le 0 -or $ParentStartTicks -le 0 -or $parent.StartTime.ToUniversalTime().Ticks -ne $ParentStartTicks) { throw 'PARENT_IDENTITY_LOST' }
}
Assert-Parent
Add-Type -TypeDefinition @'
using System;
using System.Runtime.InteropServices;
public static class ProbeWordWindow {
    [DllImport("user32.dll")] public static extern uint GetWindowThreadProcessId(IntPtr window, out uint process);
}
'@
$script:Word = $null
$script:Document = $null
$script:UndoRecord = $null
$script:RecordOpen = $false
$script:Owned = $false
$script:DocumentIdentity = [IntPtr]::Zero
$script:WordPid = 0
$script:WordBirth = 0L
$script:Preexisting = @(Get-Process WINWORD -ErrorAction SilentlyContinue | ForEach-Object { $_.Id })
$script:Properties = @('Name','Size','Bold','Italic','Underline','Color','StrikeThrough','Subscript','Superscript','SmallCaps','AllCaps','HighlightColorIndex')
function Assert-OwnedWord {
    param([int]$ExpectedCount)
    Assert-Parent
    [uint32]$observed = 0
    $hwnd = [IntPtr]([long]$script:Word.Hwnd)
    if ([ProbeWordWindow]::GetWindowThreadProcessId($hwnd,[ref]$observed) -eq 0) { throw 'WORD_WINDOW_IDENTITY_LOST' }
    $process = Get-Process -Id ([int]$observed) -ErrorAction Stop
    $documents = $script:Word.Documents
    try { $count = [int]$documents.Count } finally { Release-Com $documents }
    if ($process.ProcessName -cne 'WINWORD' -or -not (Test-ProbeOwnership ([int]$observed) $process.StartTime.ToUniversalTime().Ticks $script:Preexisting $script:WordPid $script:WordBirth $count $ExpectedCount)) { throw 'WORD_OWNERSHIP_LOST' }
    if ($ExpectedCount -eq 1) {
        $documents = $script:Word.Documents; $only = $null; $identity = [IntPtr]::Zero
        try {
            $only = $documents.Item(1)
            $identity = [Runtime.InteropServices.Marshal]::GetIUnknownForObject($only)
            if ($identity -ne $script:DocumentIdentity) { throw 'DOCUMENT_IDENTITY_LOST' }
        } finally {
            if ($identity -ne [IntPtr]::Zero) { [void][Runtime.InteropServices.Marshal]::Release($identity) }
            # Item(1) may share the Document RCW: never FinalReleaseComObject here.
            $only = $null
            Release-Com $documents
        }
    }
}
function Read-Token {
    $range = $script:Document.Range(0,6)
    try { return [string]$range.Text } finally { Release-Com $range }
}
function Test-CompleteGeneratedText {
    param([string]$Token)
    $range = $script:Document.Content
    try { return ([string]$range.Text -ceq ($Token + "`r")) } finally { Release-Com $range }
}
function Read-Format {
    $result = @()
    for ($index = 0; $index -lt 6; $index++) {
        $range = $script:Document.Range($index,($index+1)); $font = $null
        try {
            $font = $range.Font
            $row = [ordered]@{}
            foreach ($name in $script:Properties) { $row[$name] = if ($name -ceq 'HighlightColorIndex') { [int]$range.HighlightColorIndex } else { $font.$name } }
            $row['LanguageID'] = [int]$range.LanguageID
            $result += $row
        } finally { Release-Com $font; Release-Com $range }
    }
    return ,$result
}
function Insert-TestXml {
    param([string]$Xml, [string]$Expected)
    Assert-OwnedWord 1
    if ((Read-Token) -cne $Expected) { throw 'EXPECTED_TEXT_CHANGED' }
    if ($script:Document.ReadOnly -or [int]$script:Document.ProtectionType -ne -1 -or $script:Document.TrackRevisions) { throw 'DOCUMENT_NOT_EDITABLE' }
    $range = $script:Document.Range(0,6)
    $clock = [Diagnostics.Stopwatch]::StartNew()
    try {
        $script:UndoRecord.StartCustomRecord('GSwitcher XML disposable probe')
        $script:RecordOpen = $true
        Assert-OwnedWord 1
        $range.InsertXML($Xml)
        $script:UndoRecord.EndCustomRecord()
        $script:RecordOpen = $false
        return $clock.Elapsed.TotalMilliseconds
    } finally { Release-Com $range }
}
try {
    Stage 'check-existing-word'
    # Explicitly refuse while any existing Word is running. No attachment to user documents.
    if ($script:Preexisting.Count -ne 0) { $script:Report.status = 'REFUSED_EXISTING_WORD'; throw 'CLOSE_WORD_BEFORE_PROBE' }
    Stage 'create-word'
    $script:Word = New-Object -ComObject Word.Application
    [uint32]$newPid = 0
    if ([ProbeWordWindow]::GetWindowThreadProcessId([IntPtr]([long]$script:Word.Hwnd),[ref]$newPid) -eq 0) { throw 'WORD_PROCESS_UNPROVEN' }
    $newProcess = Get-Process -Id ([int]$newPid) -ErrorAction Stop
    $script:WordPid = [int]$newPid
    $script:WordBirth = $newProcess.StartTime.ToUniversalTime().Ticks
    $script:Report.word_process_id = $script:WordPid
    $script:Report.word_start_ticks = $script:WordBirth
    Assert-OwnedWord 0
    $script:Owned = $true
    $script:Word.AutomationSecurity = 3
    $script:Word.DisplayAlerts = 0
    $script:Word.Visible = $false
    $script:Report.word_version = [string]$script:Word.Version
    $script:Report.results['word_executable_version'] = $newProcess.MainModule.FileVersionInfo.FileVersion
    $script:Report.native_word_calls = $true
    Stage 'create-disposable-document'
    $documents = $script:Word.Documents
    try { $script:Document = $documents.Add() } finally { Release-Com $documents }
    $script:DocumentIdentity = [Runtime.InteropServices.Marshal]::GetIUnknownForObject($script:Document)
    Assert-OwnedWord 1
    $original = 'ghbdtn'
    $replacement = -join ([char[]]@(0x043f,0x0440,0x0438,0x0432,0x0435,0x0442))
    $range = $script:Document.Range(0,0)
    try { $range.Text = $original } finally { Release-Com $range }
    Stage 'set-generated-mixed-format'
    for ($index = 0; $index -lt 6; $index++) {
        Assert-OwnedWord 1
        $range = $script:Document.Range($index,($index+1)); $font = $null
        try {
            $font = $range.Font
            $font.Name = if ($index % 2 -eq 0) { 'Calibri' } else { 'Arial' }
            $font.Size = 11 + $index
            $font.Bold = if ($index % 2 -eq 0) { -1 } else { 0 }
            $font.Italic = if ($index % 2 -eq 0) { 0 } else { -1 }
            $font.Color = if ($index % 2 -eq 0) { 255 } else { 16711680 }
        } finally { Release-Com $font; Release-Com $range }
    }
    Stage 'export-word-open-xml'
    Assert-OwnedWord 1
    if ((Read-Token) -cne $original) { throw 'GENERATED_TEXT_MISMATCH' }
    $before = Read-Format
    $range = $script:Document.Range(0,6)
    try { $source = [string]$range.WordOpenXML } finally { Release-Com $range }
    if ([Text.Encoding]::UTF8.GetByteCount($source) -gt 4194304) { throw 'SOURCE_XML_TOO_LARGE' }
    # Retain the real unmodified export even when the diagnostic transform refuses it.
    [IO.File]::WriteAllText((Join-Path $OutputDirectory 'word-source.xml'),$source,[Text.UTF8Encoding]::new($false))
    $script:Report.source_xml_sha256 = (Get-FileHash -LiteralPath (Join-Path $OutputDirectory 'word-source.xml') -Algorithm SHA256).Hash.ToLowerInvariant()
    Save-ProbeReport
    Stage 'prepare-diagnostic-xml'
    $transformed = Convert-ProbeTokenXml $source $original $replacement
    [IO.File]::WriteAllText((Join-Path $OutputDirectory 'word-transformed.xml'),$transformed,[Text.UTF8Encoding]::new($false))
    $script:Report.transformed_xml_sha256 = (Get-FileHash -LiteralPath (Join-Path $OutputDirectory 'word-transformed.xml') -Algorithm SHA256).Hash.ToLowerInvariant()
    [xml]$partTree = $source
    $namespace = [Xml.XmlNamespaceManager]::new($partTree.NameTable)
    $namespace.AddNamespace('pkg','http://schemas.microsoft.com/office/2006/xmlPackage')
    $script:Report.source_package_parts = @($partTree.SelectNodes('/pkg:package/pkg:part',$namespace) | ForEach-Object { $_.GetAttribute('name','http://schemas.microsoft.com/office/2006/xmlPackage') })
    $script:UndoRecord = $script:Word.UndoRecord
    Stage 'single-insert-xml'
    $script:Report.results['insert_elapsed_ms'] = Insert-TestXml $transformed $original
    Assert-OwnedWord 1
    $script:Report.results['replacement_text_matches'] = Test-CompleteGeneratedText $replacement
    $script:Report.results['replacement_measured_format_matches'] = Test-ProbeFormattingEqual $before (Read-Format)
    Stage 'native-undo'
    Assert-OwnedWord 1
    $script:Report.results['native_undo_returned_true'] = [bool]$script:Document.Undo(1)
    $script:Report.results['native_undo_text_matches'] = Test-CompleteGeneratedText $original
    $script:Report.results['native_undo_measured_format_matches'] = Test-ProbeFormattingEqual $before (Read-Format)
    if (-not $script:Report.results['native_undo_text_matches']) { throw 'NATIVE_UNDO_TEXT_FAILED' }
    Stage 'second-single-insert-xml'
    $script:Report.results['second_insert_elapsed_ms'] = Insert-TestXml $transformed $original
    Stage 'stored-original-xml-undo'
    $script:Report.results['stored_original_insert_elapsed_ms'] = Insert-TestXml $source $replacement
    Assert-OwnedWord 1
    $script:Report.results['stored_original_text_matches'] = Test-CompleteGeneratedText $original
    $script:Report.results['stored_original_measured_format_matches'] = Test-ProbeFormattingEqual $before (Read-Format)
    $checks = @('replacement_text_matches','replacement_measured_format_matches','native_undo_returned_true','native_undo_text_matches','native_undo_measured_format_matches','stored_original_text_matches','stored_original_measured_format_matches')
    $failed = @($checks | Where-Object { $script:Report.results[$_] -ne $true })
    $script:Report.status = if ($failed.Count -eq 0) { 'MEASURED_CHECKS_PASSED' } else { 'MEASURED_CHECKS_FAILED' }
} catch {
    if ($script:Report.status -ceq 'NOT_RUN') { $script:Report.status = 'FAILED_OR_UNKNOWN' }
    if ($null -eq $script:Word -and $_.Exception.HResult -eq -2147221164) { $script:Report.status = 'WORD_UNAVAILABLE' }
    # Error text may carry XML/provider data: persist only type and numeric HRESULT.
    $script:Report.results['error_type'] = $_.Exception.GetType().FullName
    $script:Report.results['error_hresult'] = $_.Exception.HResult
} finally {
    $outcomeStage = $script:Report.stage
    # Cleanup cannot depend on reporting I/O: disk/access failures must not bypass it.
    $script:Report.stage = 'cleanup'
    if ($script:Owned) {
        try {
            if ($null -ne $script:Document) {
                Assert-OwnedWord 1
                if ($script:RecordOpen) { $script:UndoRecord.EndCustomRecord(); $script:RecordOpen = $false }
                $script:Document.Close(0)
            }
            Assert-OwnedWord 0
            $script:Word.Quit(0)
            $script:Report.cleanup_complete = $true
        } catch {
            $script:Report.cleanup_complete = $false
            $script:Report.status = 'UNKNOWN_CLEANUP'
        }
    }
    try {
        if ($script:DocumentIdentity -ne [IntPtr]::Zero) { [void][Runtime.InteropServices.Marshal]::Release($script:DocumentIdentity) }
    } catch { $script:Report.cleanup_complete = $false; $script:Report.status = 'UNKNOWN_CLEANUP' }
    foreach ($value in @($script:UndoRecord,$script:Document,$script:Word)) {
        try { Release-Com $value } catch { $script:Report.cleanup_complete = $false; $script:Report.status = 'UNKNOWN_CLEANUP' }
    }
    $script:Report.stage = $outcomeStage
    try { Save-ProbeReport } catch {
        $script:Report.status = 'REPORT_WRITE_FAILED'
        Write-Host 'Report could not be saved. Native cleanup was attempted; no successful result is reported.'
    }
}
if ($script:Report.status -ceq 'MEASURED_CHECKS_PASSED' -and $script:Report.cleanup_complete) { exit 0 }
exit 1
