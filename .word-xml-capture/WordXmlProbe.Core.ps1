# Diagnostic-only helpers. These functions confer no product/native authority.
Set-StrictMode -Version Latest

function Convert-ProbeTokenXml {
    param([string]$Xml, [string]$Original, [string]$Replacement)
    if ([string]::IsNullOrEmpty($Xml) -or [Text.Encoding]::UTF8.GetByteCount($Xml) -gt 4194304) { throw 'XML_SIZE_REFUSED' }
    if ($Original -cne 'ghbdtn' -or $Replacement.Length -ne 6 -or $Replacement -cnotmatch '^[\u0400-\u04ff]{6}$') { throw 'TEST_TOKEN_REFUSED' }
    $settings = [Xml.XmlReaderSettings]::new()
    $settings.DtdProcessing = [Xml.DtdProcessing]::Prohibit
    $settings.XmlResolver = $null
    $settings.MaxCharactersInDocument = 4194304
    $tree = [Xml.XmlDocument]::new()
    $tree.PreserveWhitespace = $true
    $tree.XmlResolver = $null
    $reader = [Xml.XmlReader]::Create([IO.StringReader]::new($Xml), $settings)
    try { $tree.Load($reader) } finally { $reader.Dispose() }
    $ns = [Xml.XmlNamespaceManager]::new($tree.NameTable)
    $ns.AddNamespace('pkg','http://schemas.microsoft.com/office/2006/xmlPackage')
    $ns.AddNamespace('w','http://schemas.openxmlformats.org/wordprocessingml/2006/main')
    if ($tree.DocumentElement.LocalName -cne 'package' -or $tree.DocumentElement.NamespaceURI -cne 'http://schemas.microsoft.com/office/2006/xmlPackage') { throw 'PACKAGE_REFUSED' }
    $parts = @($tree.SelectNodes('/pkg:package/pkg:part[@pkg:name="/word/document.xml"]', $ns))
    if ($parts.Count -ne 1) { throw 'MAIN_PART_REFUSED' }
    $body = @($parts[0].SelectNodes('pkg:xmlData/w:document/w:body', $ns))
    if ($body.Count -ne 1 -or $body[0].SelectNodes('w:p', $ns).Count -ne 1) { throw 'BODY_REFUSED' }
    $unsafe = './/w:delText|.//w:instrText|.//w:fldChar|.//w:fldSimple|.//w:ins|.//w:del|.//w:sdt|.//w:tbl|.//w:drawing|.//w:object|.//w:hyperlink|.//w:br|.//w:tab|.//w:txbxContent'
    if ($body[0].SelectNodes($unsafe, $ns).Count -ne 0) { throw 'STRUCTURE_REFUSED' }
    $nodes = @($body[0].SelectNodes('w:p/w:r/w:t', $ns))
    if ($nodes.Count -eq 0 -or $nodes.Count -gt 64 -or $parts[0].SelectNodes('.//w:t', $ns).Count -ne $nodes.Count) { throw 'TEXT_SHAPE_REFUSED' }
    $observed = ($nodes | ForEach-Object { $_.InnerText }) -join ''
    if ($observed -cne $Original) { throw 'ORIGINAL_MISMATCH' }
    $offset = 0
    foreach ($node in $nodes) {
        $length = $node.InnerText.Length
        $node.InnerText = $Replacement.Substring($offset,$length)
        $offset += $length
    }
    $output = $tree.OuterXml
    if ([Text.Encoding]::UTF8.GetByteCount($output) -gt 4194304) { throw 'OUTPUT_SIZE_REFUSED' }
    return $output
}

function Test-ProbeOwnership {
    param([int]$ObservedPid, [long]$ObservedStartTicks, [int[]]$PreexistingPids,
        [int]$ExpectedPid, [long]$ExpectedStartTicks, [int]$DocumentCount, [int]$ExpectedDocumentCount)
    return ($ObservedPid -gt 0 -and $ExpectedPid -gt 0 -and $ObservedPid -eq $ExpectedPid -and
        $ObservedStartTicks -gt 0 -and $ObservedStartTicks -eq $ExpectedStartTicks -and
        $PreexistingPids -notcontains $ObservedPid -and $DocumentCount -eq $ExpectedDocumentCount -and
        $ExpectedDocumentCount -ge 0 -and $ExpectedDocumentCount -le 1)
}

function Test-ProbeFormattingEqual {
    param($Before, $After)
    if ($null -eq $Before -or $null -eq $After -or @($Before).Count -ne @($After).Count -or @($Before).Count -eq 0) { return $false }
    return (($Before | ConvertTo-Json -Depth 12 -Compress) -ceq ($After | ConvertTo-Json -Depth 12 -Compress))
}

function Invoke-ProbeChild {
    param([string]$FilePath, [string]$Arguments, [ValidateRange(1,180)][int]$DeadlineSeconds)
    $start = [Diagnostics.ProcessStartInfo]::new()
    $start.FileName = $FilePath
    $start.Arguments = $Arguments
    $start.UseShellExecute = $false
    $start.CreateNoWindow = $true
    $child = [Diagnostics.Process]::Start($start)
    $watch = [Diagnostics.Stopwatch]::StartNew()
    try {
        while (-not $child.WaitForExit(100)) {
            if ($watch.Elapsed.TotalSeconds -ge $DeadlineSeconds) {
                $child.Kill()
                $reaped = $child.WaitForExit(5000)
                return [pscustomobject]@{TimedOut=$true;ExitCode=$null;Reaped=$reaped}
            }
        }
        return [pscustomobject]@{TimedOut=$false;ExitCode=$child.ExitCode;Reaped=$true}
    } catch {
        if (-not $child.HasExited) { $child.Kill(); [void]$child.WaitForExit(5000) }
        throw
    } finally { $child.Dispose() }
}
