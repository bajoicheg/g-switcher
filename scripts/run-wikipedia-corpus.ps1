param(
    [switch]$Strict
)

$ErrorActionPreference = 'Stop'

$articleTitle = 'Информационная безопасность'
$encodedTitle = [uri]::EscapeDataString($articleTitle)
$api = "https://ru.wikipedia.org/w/api.php?action=query&prop=extracts%7Crevisions&explaintext=1&redirects=1&rvprop=ids%7Ctimestamp&format=json&formatversion=2&titles=$encodedTitle"
$headers = @{ 'User-Agent' = 'G-switcher corpus benchmark/1.0 (+https://github.com/bajoicheg/g-switcher)' }

New-Item -ItemType Directory -Force -Path target | Out-Null
$response = Invoke-RestMethod -Uri $api -Headers $headers -Method Get
$page = $response.query.pages | Select-Object -First 1
if (-not $page -or -not $page.extract) {
    throw 'Wikipedia API returned no article extract'
}

# Benchmark encyclopedic prose, not the citation/bibliography/link tail. The
# source revision is still recorded below so the corpus is reproducible.
$rawArticle = [string]$page.extract
$tailHeading = [regex]::Match(
    $rawArticle,
    '(?m)^==\s*(См\. также|Примечания|Литература|Ссылки)\s*==\s*$'
)
if ($tailHeading.Success) {
    $rawArticle = $rawArticle.Substring(0, $tailHeading.Index)
}

# Keyboard typing does not produce editorial stress accents. Remove only those
# accents. Do NOT decompose all Unicode characters: doing so would turn native
# Russian й/ё into и/е after stripping their combining marks.
$articleText = $rawArticle
    .Replace([string][char]0x0301, '')
    .Replace([string][char]0x0300, '')
    .Replace([char]0x00A0, ' ')
$corpusPath = Join-Path $PWD 'target/wiki-article.txt'
$reportPath = Join-Path $PWD 'target/wiki-corpus-failures.csv'
$summaryPath = Join-Path $PWD 'target/wiki-corpus-summary.txt'
[IO.File]::WriteAllText($corpusPath, $articleText, [Text.UTF8Encoding]::new($false))

$env:G_SWITCHER_CORPUS_PATH = $corpusPath
$env:G_SWITCHER_CORPUS_REPORT = $reportPath
$env:G_SWITCHER_CORPUS_SUMMARY = $summaryPath
$env:G_SWITCHER_CORPUS_STRICT = if ($Strict) { '1' } else { '0' }

cargo test --lib wikipedia_article_layout_corpus_e2e -- --ignored --test-threads=1 --nocapture
if ($LASTEXITCODE -ne 0) {
    exit $LASTEXITCODE
}

$revision = $page.revisions | Select-Object -First 1
Add-Content -LiteralPath $summaryPath -Encoding utf8 -Value "wikipedia_page_id=$($page.pageid)"
Add-Content -LiteralPath $summaryPath -Encoding utf8 -Value "wikipedia_revision_id=$($revision.revid)"
Add-Content -LiteralPath $summaryPath -Encoding utf8 -Value "wikipedia_parent_revision_id=$($revision.parentid)"
Add-Content -LiteralPath $summaryPath -Encoding utf8 -Value "wikipedia_revision_timestamp=$($revision.timestamp)"
Add-Content -LiteralPath $summaryPath -Encoding utf8 -Value "benchmark_scope=article prose before See also/Notes/Literature/Links"

Write-Host 'Wikipedia corpus benchmark complete'
Get-Content -LiteralPath $summaryPath
