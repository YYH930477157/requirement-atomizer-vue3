param(
  [string]$OutputDir = ".\out\abnt_nbr_16968_atomizer_v5",
  [int]$Port = 8770,
  [switch]$RunReview
)

$ErrorActionPreference = "Stop"
$Root = Split-Path -Parent $PSScriptRoot
$UiPath = Join-Path $Root "ui\index.html"

Write-Host "Starting Requirement Atomizer API on http://127.0.0.1:$Port"
Write-Host "Review UI: $UiPath"

if ($RunReview) {
  Write-Host "Running local review pipeline..."
  python .\llm_pipeline.py --out "$OutputDir"
}

Start-Process powershell -WindowStyle Hidden -ArgumentList @(
  "-NoProfile",
  "-ExecutionPolicy", "Bypass",
  "-Command",
  "cd `"$Root`"; python .\api_server.py --out `"$OutputDir`" --port $Port"
)

Start-Process $UiPath
