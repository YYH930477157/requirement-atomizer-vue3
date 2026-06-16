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
    $xlsxPath = Join-Path $SmokeRoot "synthetic_standard.xlsx"
    $pdfPath = Join-Path $SmokeRoot "sample_text_tables.pdf"
    $outDir = Join-Path $SmokeRoot "out"
    $xlsxOutDir = Join-Path $SmokeRoot "xlsx-out"
    $pdfOutDir = Join-Path $SmokeRoot "pdf-out"
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
    @'
import sys
from pathlib import Path
from openpyxl import Workbook

path = Path(sys.argv[1])
book = Workbook()
sheet = book.active
sheet.title = "Requirements"
sheet.append(["Req ID", "Requirement", "Priority"])
sheet.append(["REQ-1", "The meter shall support xDLMS GET service.", "High"])
book.save(path)
'@ | & $Python - $xlsxPath
    if ($LASTEXITCODE -ne 0) {
        throw "Synthetic XLSX generation failed"
    }
    Copy-Item -LiteralPath (Join-Path $RepoRoot "tests\fixtures\sample_text_tables.pdf") -Destination $pdfPath

    Push-Location $SmokeRoot
    try {
        $stdout = & $CliExe run $docxPath --out $outDir --export csv --quiet 2>$null
        if ($LASTEXITCODE -ne 0) {
            throw "ratomizer.exe run failed with exit code $LASTEXITCODE"
        }
        $xlsxStdout = & $CliExe run $xlsxPath --out $xlsxOutDir --skip-review --quiet 2>$null
        if ($LASTEXITCODE -ne 0) {
            throw "ratomizer.exe run XLSX failed with exit code $LASTEXITCODE"
        }
        $pdfStdout = & $CliExe run $pdfPath --out $pdfOutDir --skip-review --quiet 2>$null
        if ($LASTEXITCODE -ne 0) {
            throw "ratomizer.exe run PDF failed with exit code $LASTEXITCODE"
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
    $xlsxJson = $xlsxStdout | ConvertFrom-Json
    if (-not $xlsxJson.ok -or $xlsxJson.manifest.input_format -ne "xlsx") {
        throw "ratomizer.exe run XLSX smoke returned invalid envelope"
    }
    $pdfJson = $pdfStdout | ConvertFrom-Json
    if (-not $pdfJson.ok -or $pdfJson.manifest.input_format -ne "pdf") {
        throw "ratomizer.exe run PDF smoke returned invalid envelope"
    }

    $env:QT_QPA_PLATFORM = "offscreen"
    & $GuiExe --smoke
    if ($LASTEXITCODE -ne 0) {
        throw "RequirementAtomizer.exe --smoke failed with exit code $LASTEXITCODE"
    }
    # 装配冒烟：走 assemble→spec_enrich 等生成器导入链（默认 stub，不调 LLM），
    # 防回归——任一生成器模块未被打包收全会在此 ImportError 崩。$outDir 已由上面 run 产出原子文件。
    & $GuiExe --smoke-assemble $outDir
    if ($LASTEXITCODE -ne 0) {
        throw "RequirementAtomizer.exe --smoke-assemble failed with exit code $LASTEXITCODE"
    }
}
finally {
    Remove-Item -LiteralPath $SmokeRoot -Recurse -Force -ErrorAction SilentlyContinue
}

Write-Host "Package smoke passed: $AppDir"
