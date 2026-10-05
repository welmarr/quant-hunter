param([int]$Port = 8765, [string]$Runtime = '', [string]$PrivateRoot = '')
$ErrorActionPreference = 'Stop'
$repository = (Resolve-Path (Join-Path $PSScriptRoot '../..')).Path
if (-not $Runtime) { $Runtime = Join-Path $repository '.local/v0' }
$Runtime = [System.IO.Path]::GetFullPath($Runtime)
if ([System.IO.Path]::GetPathRoot($Runtime) -ne [System.IO.Path]::GetPathRoot($repository)) {
    throw 'Runtime must remain on the repository drive. Do not silently use C:.'
}
New-Item -ItemType Directory -Force -Path $Runtime,(Join-Path $repository '.tools/v0-tmp') | Out-Null
$env:UV_CACHE_DIR = Join-Path $repository '.tools/uv-cache'
$env:UV_PYTHON_INSTALL_DIR = Join-Path $repository '.tools/python'
$env:TEMP = Join-Path $repository '.tools/v0-tmp'
$env:TMP = $env:TEMP
Push-Location $repository
try {
    uv sync --locked --group dev
    if ($LASTEXITCODE -ne 0) { throw 'Locked dependency setup failed' }
    $revision = git rev-parse HEAD
    if ($LASTEXITCODE -ne 0) { throw 'Cannot resolve repository revision' }
    Write-Output ('Starting local SYNTHETIC laboratory at http://127.0.0.1:' + $Port)
    Write-Output ('Runtime: ' + $Runtime + '. Press Ctrl+C to stop; interrupted work is retained.')
    $privateArguments = @()
    if ($PrivateRoot) { $privateArguments = @('--private-root', $PrivateRoot) }
    uv run --locked python -m quant_hunter.web.main --repository $repository --runtime $Runtime --code-revision $revision --port $Port @privateArguments
    if ($LASTEXITCODE -ne 0) { throw 'Application exited with an error; inspect the message above' }
} finally { Pop-Location }
