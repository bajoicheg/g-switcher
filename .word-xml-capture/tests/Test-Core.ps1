param([string]$CorePath = (Join-Path $PSScriptRoot '../WordXmlProbe.Core.ps1'))
$ErrorActionPreference = 'Stop'
Set-StrictMode -Version Latest
if (Test-Path -LiteralPath $CorePath) { . $CorePath } else {
    function Convert-ProbeTokenXml { param($Xml, $Original, $Replacement) return $null }
    function Test-ProbeOwnership { param($ObservedPid, $ObservedStartTicks, $PreexistingPids, $ExpectedPid, $ExpectedStartTicks, $DocumentCount, $ExpectedDocumentCount) return $false }
    function Test-ProbeFormattingEqual { param($Before, $After) return $false }
}
$script:Passed = 0
function Assert-Case { param([string]$Name, [scriptblock]$Body) & $Body; $script:Passed++; Write-Host "PASS $Name" }
function Assert-True { param($Value) if ($Value -ne $true) { throw 'Expected true.' } }
function Assert-False { param($Value) if ($Value -ne $false) { throw 'Expected false.' } }
function Assert-Throws { param([scriptblock]$Body) $caught = $false; try { & $Body | Out-Null } catch { $caught = $true }; Assert-True $caught }
$pkg = 'http://schemas.microsoft.com/office/2006/xmlPackage'
$w = 'http://schemas.openxmlformats.org/wordprocessingml/2006/main'
$xml = '<pkg:package xmlns:pkg="' + $pkg + '"><pkg:part pkg:name="/word/document.xml" pkg:contentType="application/vnd.openxmlformats-officedocument.wordprocessingml.document.main+xml"><pkg:xmlData><w:document xmlns:w="' + $w + '"><w:body><w:p><w:r><w:rPr><w:b/></w:rPr><w:t>ghb</w:t></w:r><w:r><w:rPr><w:i/></w:rPr><w:t>dtn</w:t></w:r></w:p></w:body></w:document></pkg:xmlData></pkg:part><pkg:part pkg:name="/word/styles.xml" pkg:contentType="application/vnd.openxmlformats-officedocument.wordprocessingml.styles+xml"><pkg:xmlData><w:styles xmlns:w="' + $w + '"><w:style w:type="paragraph" w:styleId="Normal"/></w:styles></pkg:xmlData></pkg:part></pkg:package>'
$target = -join ([char[]]@(0x043f,0x0440,0x0438,0x0432,0x0435,0x0442))
Assert-Case 'mixed runs map exact text and retain dependency parts' {
    $result = Convert-ProbeTokenXml $xml 'ghbdtn' $target
    Assert-True ($null -ne $result)
    [xml]$tree = $result
    $ns = [System.Xml.XmlNamespaceManager]::new($tree.NameTable)
    $ns.AddNamespace('pkg',$pkg); $ns.AddNamespace('w',$w)
    $nodes = @($tree.SelectNodes('//pkg:part[@pkg:name="/word/document.xml"]//w:t',$ns))
    Assert-True (($nodes | ForEach-Object { $_.InnerText }) -join '' -ceq $target)
    Assert-True ($nodes[0].InnerText.Length -eq 3 -and $nodes[1].InnerText.Length -eq 3)
    Assert-True ($tree.SelectNodes('//w:b',$ns).Count -eq 1)
    Assert-True ($tree.SelectNodes('//w:i',$ns).Count -eq 1)
    Assert-True ($tree.SelectNodes('//pkg:part[@pkg:name="/word/styles.xml"]',$ns).Count -eq 1)
}
Assert-Case 'XML declaration and alternate namespace prefixes supported diagnostically' {
    $alternate = '<?xml version="1.0"?>' + $xml.Replace('pkg:','p:').Replace('xmlns:pkg','xmlns:p').Replace('w:','a:').Replace('xmlns:w','xmlns:a')
    Assert-True ($null -ne (Convert-ProbeTokenXml $alternate 'ghbdtn' $target))
}
Assert-Case 'different original refuses before producing replacement' { Assert-Throws { Convert-ProbeTokenXml $xml 'xxxxxx' $target } }
Assert-Case 'unequal length refuses' { Assert-Throws { Convert-ProbeTokenXml $xml 'ghbdtn' 'ab' } }
Assert-Case 'DTD and entities refuse' { Assert-Throws { Convert-ProbeTokenXml ('<!DOCTYPE x [<!ENTITY injected "ghbdtn">]>' + $xml) 'ghbdtn' $target } }
Assert-Case 'oversized XML refuses' { Assert-Throws { Convert-ProbeTokenXml ($xml + (' ' * 4194304)) 'ghbdtn' $target } }
Assert-Case 'duplicate main parts refuse' { Assert-Throws { Convert-ProbeTokenXml $xml.Replace('/word/styles.xml','/word/document.xml') 'ghbdtn' $target } }
Assert-Case 'revision text refuses' { Assert-Throws { Convert-ProbeTokenXml $xml.Replace('<w:r><w:rPr><w:b/>','<w:r><w:delText>x</w:delText><w:rPr><w:b/>') 'ghbdtn' $target } }
Assert-Case 'delimiter conversion refuses' { Assert-Throws { Convert-ProbeTokenXml $xml 'ghbdtn' 'hello ' } }
Assert-Case 'new empty Word process admitted' { Assert-True (Test-ProbeOwnership 101 123 @(100) 101 123 0 0) }
Assert-Case 'existing Word process never admitted' { Assert-False (Test-ProbeOwnership 101 123 @(101) 101 123 0 0) }
Assert-Case 'PID reuse never admitted' { Assert-False (Test-ProbeOwnership 101 124 @() 101 123 1 1) }
Assert-Case 'unexpected document never admitted' { Assert-False (Test-ProbeOwnership 101 123 @() 101 123 2 1) }
Assert-Case 'different process never admitted' { Assert-False (Test-ProbeOwnership 102 123 @() 101 123 1 1) }
Assert-Case 'unproven birth never admitted' { Assert-False (Test-ProbeOwnership 101 0 @() 101 0 0 0) }
$before = @([ordered]@{Name='Calibri';Size=11;Bold=0;Color=0},[ordered]@{Name='Arial';Size=16;Bold=-1;Color=255})
Assert-Case 'all measured formatting matches' { Assert-True (Test-ProbeFormattingEqual $before $before) }
Assert-Case 'one character formatting change detected' { $after = @([ordered]@{Name='Calibri';Size=11;Bold=0;Color=0},[ordered]@{Name='Arial';Size=17;Bold=-1;Color=255}); Assert-False (Test-ProbeFormattingEqual $before $after) }
Assert-Case 'missing character formatting detected' { Assert-False (Test-ProbeFormattingEqual $before @($before[0])) }
Write-Host "CORE_TESTS_PASSED=$script:Passed"
