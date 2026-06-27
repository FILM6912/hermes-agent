# dev.ps1 — Start Hermes backend + frontend dev servers in separate windows
$ErrorActionPreference = 'Stop'

$Port = if ($env:HERMES_WEBUI_PORT) { $env:HERMES_WEBUI_PORT } else { '8789' }
$Home_ = if ($env:HERMES_HOME) { $env:HERMES_HOME } else { "$env:TEMP\hermes-dev-home" }
$State = if ($env:HERMES_WEBUI_STATE_DIR) { $env:HERMES_WEBUI_STATE_DIR } else { "$env:TEMP\hermes-dev-state" }

Write-Host "`n=== Hermes Dev ===" -ForegroundColor Cyan
Write-Host "  HERMES_HOME           = $Home_"
Write-Host "  HERMES_WEBUI_STATE_DIR= $State"
Write-Host "  HERMES_WEBUI_PORT     = $Port"
Write-Host ""

# Ensure isolated dirs exist
New-Item -ItemType Directory -Force -Path $Home_ | Out-Null
New-Item -ItemType Directory -Force -Path $State | Out-Null

$root = $PSScriptRoot

# Backend — new window
Write-Host "[backend]  python bootstrap.py  -> http://127.0.0.1:$Port" -ForegroundColor Green
Start-Process powershell -ArgumentList "-NoExit", "-Command", @"
`$env:HERMES_HOME='$Home_'; `$env:HERMES_WEBUI_STATE_DIR='$State'; `$env:HERMES_WEBUI_PORT='$Port'
Set-Location '$root'
python bootstrap.py
"@

# Frontend — new window
Write-Host "[frontend] npm run dev          -> http://localhost:5173"  -ForegroundColor Yellow
Start-Process powershell -ArgumentList "-NoExit", "-Command", @"
`$env:HERMES_WEBUI_PORT='$Port'
Set-Location '$root\frontend'
npm run dev
"@

Write-Host "`nBoth servers launched in separate windows.`n" -ForegroundColor Cyan
