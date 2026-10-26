param([switch]$SmokeTest)
$ErrorActionPreference = 'Stop'
$projectRoot = Split-Path -Parent $PSScriptRoot
if (-not (Test-Path (Join-Path $projectRoot '.image/terminal64.exe'))) {
    & (Join-Path $PSScriptRoot 'prepare-image.ps1')
}
Push-Location $projectRoot
$oldLimit = $env:SCRAPE_MAX_BARS
$oldDatabase = $env:SCRAPE_DB
try {
    if ($SmokeTest) {
        $env:SCRAPE_MAX_BARS = '100'
        $env:SCRAPE_DB = 'Z:/data/market-smoke.db'
    } else {
        $env:SCRAPE_MAX_BARS = '0'
        $env:SCRAPE_DB = 'Z:/data/market.db'
    }
    docker compose -f compose.yaml -f docker/compose.scrape.yaml up -d --build --force-recreate
    if ($LASTEXITCODE -ne 0) { throw 'Could not start the MT5 scraper stack.' }
    Write-Host 'Stack started. Follow progress with: docker compose logs -f mt5'
} finally {
    $env:SCRAPE_MAX_BARS = $oldLimit
    $env:SCRAPE_DB = $oldDatabase
    Pop-Location
}
