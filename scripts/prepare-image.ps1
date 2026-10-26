param([string]$MT5InstallDir = 'C:\Program Files\MetaTrader 5')
$ErrorActionPreference = 'Stop'
$terminalSource = Join-Path $MT5InstallDir 'terminal64.exe'
if (-not (Test-Path -LiteralPath $terminalSource -PathType Leaf)) {
    throw 'MT5 terminal64.exe was not found. Pass -MT5InstallDir with your installation folder.'
}
$projectRoot = Split-Path -Parent $PSScriptRoot
$assetDirectory = Join-Path $projectRoot '.image'
New-Item -ItemType Directory -Force -Path $assetDirectory | Out-Null
Copy-Item -LiteralPath $terminalSource -Destination (Join-Path $assetDirectory 'terminal64.exe') -Force
Write-Host 'MT5 binary prepared for the portable image. No terminal accounts or history were copied.'
