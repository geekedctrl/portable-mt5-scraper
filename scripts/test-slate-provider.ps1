param(
    [string]$Network = 'slate-local_internal',
    [string]$ProviderHost = 'mt5-market-provider'
)
$ErrorActionPreference = 'Stop'
$testFile = Join-Path $PSScriptRoot 'test-slate-provider.mjs'

docker network inspect $Network *> $null
if ($LASTEXITCODE -ne 0) { throw "Docker network '$Network' was not found. Start Slate first." }
docker image inspect slate-api:latest *> $null
if ($LASTEXITCODE -ne 0) { throw 'Slate local API image slate-api:latest is not available.' }

docker run --rm --network $Network `
    --mount "type=bind,source=$testFile,target=/tmp/test-slate-provider.mjs,readonly" `
    --entrypoint node slate-api:latest /tmp/test-slate-provider.mjs $ProviderHost
if ($LASTEXITCODE -ne 0) { throw 'The Slate-network provider smoke test failed.' }
