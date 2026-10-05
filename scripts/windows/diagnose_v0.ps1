$ErrorActionPreference = 'Stop'
$repository = (Resolve-Path (Join-Path $PSScriptRoot '../..')).Path
Write-Output ('Repository: ' + $repository)
Get-PSDrive -PSProvider FileSystem | Select-Object Name,@{Name='FreeGiB';Expression={[math]::Round($_.Free/1GB,2)}}
Get-Command uv,python,node,docker -ErrorAction SilentlyContinue | Select-Object Name,Source
Write-Output 'Default runtime: .local/v0 on the repository drive. No host mutation performed.'
Write-Output 'Docker Linux root does not prove Windows VHD location. Large Docker builds remain gated.'
