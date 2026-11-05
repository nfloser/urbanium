$ErrorActionPreference = 'Stop'
Set-Location (Join-Path $PSScriptRoot '..')

if (-not (Get-Command py.exe -ErrorAction SilentlyContinue)) {
    throw 'Install Python 3.12 for Windows with the Python Launcher, then run this command again.'
}

py.exe -3.12 -m venv .venv
if ($LASTEXITCODE -ne 0) { throw 'Could not create the Python 3.12 environment.' }

$python = Join-Path $PWD '.venv/Scripts/python.exe'
& $python -m pip install .
if ($LASTEXITCODE -ne 0) { throw 'Urbanium installation failed.' }

$env:URBANIUM_HOST = '127.0.0.1'
$env:URBANIUM_PORT = '8000'
$env:URBANIUM_CITIES = Join-Path $PWD 'cities'
Write-Host 'Open http://127.0.0.1:8000/ once the server is running. Press Ctrl+C to stop.'
& $python -m urbanium.api
exit $LASTEXITCODE
