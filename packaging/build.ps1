param(
    [string]$Python = "python",
    [switch]$SkipSmoke
)

$ErrorActionPreference = "Stop"

$RepoRoot = Resolve-Path (Join-Path $PSScriptRoot "..")
$DistRoot = Join-Path $RepoRoot "dist"
$BuildRoot = Join-Path $RepoRoot "build"
$AppDir = Join-Path $DistRoot "RequirementAtomizer"
$CliExe = Join-Path $AppDir "ratomizer.exe"
$GuiExe = Join-Path $AppDir "RequirementAtomizer.exe"
$SpecPath = Join-Path $PSScriptRoot "ratomizer.spec"

Remove-Item -LiteralPath $DistRoot -Recurse -Force -ErrorAction SilentlyContinue
Remove-Item -LiteralPath $BuildRoot -Recurse -Force -ErrorAction SilentlyContinue

& $Python -m PyInstaller --clean --noconfirm --distpath $DistRoot --workpath $BuildRoot $SpecPath
if ($LASTEXITCODE -ne 0) {
    throw "PyInstaller failed with exit code $LASTEXITCODE"
}

if ($SkipSmoke) {
    exit 0
}

$version = (& $Python -c "from version import __version__; print(__version__)").Trim()
$exeVersion = (& $CliExe --version).Trim()
if ($LASTEXITCODE -ne 0 -or $exeVersion -ne $version) {
    throw "ratomizer.exe --version returned '$exeVersion', expected '$version'"
}

$SmokeRoot = Join-Path ([System.IO.Path]::GetTempPath()) ("ratomizer-package-smoke-" + [guid]::NewGuid().ToString("N"))
New-Item -ItemType Directory -Path $SmokeRoot | Out-Null
try {
    $docxPath = Join-Path $SmokeRoot "synthetic_standard.docx"
    $outDir = Join-Path $SmokeRoot "out"
    @'
import sys
from pathlib import Path
from docx import Document

path = Path(sys.argv[1])
doc = Document()
doc.add_heading("Scope", level=1)
doc.add_paragraph("The meter shall support xDLMS GET service.")
doc.save(path)
'@ | & $Python - $docxPath
    if ($LASTEXITCODE -ne 0) {
        throw "Synthetic DOCX generation failed"
    }

    Push-Location $SmokeRoot
    try {
        $stdout = & $CliExe run $docxPath --out $outDir --export csv --quiet 2>$null
        if ($LASTEXITCODE -ne 0) {
            throw "ratomizer.exe run failed with exit code $LASTEXITCODE"
        }
    }
    finally {
        Pop-Location
    }

    $json = $stdout | ConvertFrom-Json
    if (-not $json.ok) {
        throw "ratomizer.exe run smoke returned ok=false"
    }
    $csvPath = Join-Path $outDir "requirements_export.csv"
    if (-not (Test-Path -LiteralPath $csvPath)) {
        throw "CSV export was not created: $csvPath"
    }

    $env:QT_QPA_PLATFORM = "offscreen"
    & $GuiExe --smoke
    if ($LASTEXITCODE -ne 0) {
        throw "RequirementAtomizer.exe --smoke failed with exit code $LASTEXITCODE"
    }
}
finally {
    Remove-Item -LiteralPath $SmokeRoot -Recurse -Force -ErrorAction SilentlyContinue
}

Write-Host "Package smoke passed: $AppDir"
