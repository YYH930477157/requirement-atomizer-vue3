$ErrorActionPreference = "Stop"

$RepoRoot = Resolve-Path (Join-Path $PSScriptRoot "..")
$DistBackend = Join-Path $RepoRoot "dist-backend"
$BuildDir = Join-Path $RepoRoot "build-electron-backend"
$Entry = Join-Path $RepoRoot "desktop_backend.py"
$Exe = Join-Path $DistBackend "ratomizer-desktop.exe"

if (-not (Get-Command pyinstaller -ErrorAction SilentlyContinue)) {
    throw "PyInstaller is required. Install with: pip install pyinstaller"
}

Remove-Item -LiteralPath $DistBackend -Recurse -Force -ErrorAction SilentlyContinue
Remove-Item -LiteralPath $BuildDir -Recurse -Force -ErrorAction SilentlyContinue
New-Item -ItemType Directory -Force -Path $DistBackend | Out-Null

pyinstaller `
    --clean `
    --noconfirm `
    --onefile `
    --name ratomizer-desktop `
    --distpath $DistBackend `
    --workpath $BuildDir `
    --specpath $BuildDir `
    --add-data "$RepoRoot\llm_agents;llm_agents" `
    --add-data "$RepoRoot\domain_packs;domain_packs" `
    --add-data "$RepoRoot\knowledge_bases;knowledge_bases" `
    --add-data "$RepoRoot\schemas;schemas" `
    $Entry

if (-not (Test-Path $Exe)) {
    throw "Backend executable was not created: $Exe"
}

$SmokeOut = Join-Path $env:TEMP ("ratomizer-backend-smoke-" + [guid]::NewGuid().ToString("N"))
New-Item -ItemType Directory -Force -Path $SmokeOut | Out-Null
try {
    & $Exe summary --out $SmokeOut | ConvertFrom-Json | Out-Null

    $SmokeDocx = Join-Path $SmokeOut "sample.docx"
    $SmokeRunOut = Join-Path $SmokeOut "run"
    python -c "from docx import Document; import sys; doc=Document(); doc.add_heading('Scope', level=1); doc.add_paragraph('The meter shall expose active energy import total through OBIS 1-0:1.8.0.255.'); doc.save(sys.argv[1])" $SmokeDocx
    Push-Location $env:TEMP
    try {
        & $Exe run --input $SmokeDocx --out $SmokeRunOut | ConvertFrom-Json | Out-Null
    } finally {
        Pop-Location
    }
} finally {
    Remove-Item -LiteralPath $SmokeOut -Recurse -Force -ErrorAction SilentlyContinue
}

Write-Host "Built backend executable: $Exe"
