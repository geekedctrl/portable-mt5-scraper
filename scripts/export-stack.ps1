param([string]$Image = 'mt5scraper:local', [string]$DashboardImage = 'mt5scraper-dashboard:local', [string]$OutputDirectory = (Join-Path (Split-Path -Parent $PSScriptRoot) 'release'))
$ErrorActionPreference = 'Stop'
$projectRoot = Split-Path -Parent $PSScriptRoot
New-Item -ItemType Directory -Force -Path $OutputDirectory | Out-Null
docker image inspect $Image --format '{{.Id}}' | Out-Null
if ($LASTEXITCODE -ne 0) { throw 'Build the image before exporting the stack.' }
docker image inspect $DashboardImage --format '{{.Id}}' | Out-Null
if ($LASTEXITCODE -ne 0) { throw 'Build the dashboard image before exporting the stack.' }

docker save --output (Join-Path $OutputDirectory 'mt5scraper-image.tar') $Image $DashboardImage
if ($LASTEXITCODE -ne 0) { throw 'Image export failed.' }
Copy-Item -LiteralPath (Join-Path $projectRoot 'docker/compose.server.yaml') -Destination (Join-Path $OutputDirectory 'compose.yaml') -Force
Copy-Item -LiteralPath (Join-Path $projectRoot 'docker/compose.slate-local.yaml') -Destination (Join-Path $OutputDirectory 'compose.slate-local.yaml') -Force
Copy-Item -LiteralPath (Join-Path $projectRoot '.env.example') -Destination (Join-Path $OutputDirectory '.env.example') -Force
Copy-Item -LiteralPath (Join-Path $projectRoot 'README.md') -Destination (Join-Path $OutputDirectory 'README.md') -Force
Copy-Item -LiteralPath (Join-Path $projectRoot 'docs/knowledge-base/DIETPI_DEPLOYMENT.md') -Destination (Join-Path $OutputDirectory 'DEPLOY_TO_DIETPI.md') -Force
$hash = (Get-FileHash -Algorithm SHA256 (Join-Path $OutputDirectory 'mt5scraper-image.tar')).Hash.ToLowerInvariant()
Set-Content -LiteralPath (Join-Path $OutputDirectory 'mt5scraper-image.tar.sha256') -Value "$hash  mt5scraper-image.tar" -Encoding ascii
Write-Host 'Export complete. Configure .env on the server; credentials and downloaded data were not exported.'
