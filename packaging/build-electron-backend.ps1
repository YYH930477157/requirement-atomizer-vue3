param(
    [string]$Python = "python"
)

$ErrorActionPreference = "Stop"

# 传入的 Python 路径不存在（如这台机器没有 .venv）→ 回退 PATH 上的 python，跨机器可打包
if ($Python -ne "python" -and -not (Test-Path $Python)) {
    Write-Host "Python '$Python' not found; falling back to 'python' on PATH"
    $Python = "python"
}
if ($Python -eq "python") {
    $Python = (Get-Command python -ErrorAction Stop).Source
} else {
    $Python = (Resolve-Path -LiteralPath $Python).Path
}

$RepoRoot = Resolve-Path (Join-Path $PSScriptRoot "..")
$DistBackend = Join-Path $RepoRoot "dist-backend"
$BuildDir = Join-Path $RepoRoot "build-electron-backend"
$Entry = Join-Path $RepoRoot "desktop_backend.py"
$Exe = Join-Path $DistBackend "ratomizer-desktop.exe"

# Word/Excel 影印的首选路径依赖 pywin32。它已经是 Windows 运行时依赖，
# 打包环境缺失时必须在 PyInstaller 前大声失败，不能产出一个静默丢失 COM 支路的工具。
& $Python -c "import pythoncom, win32com.client"
if (-not $?) {
    throw "Office COM packaging dependencies are missing; install the project Windows dependencies before packaging"
}

Remove-Item -LiteralPath $DistBackend -Recurse -Force -ErrorAction SilentlyContinue
Remove-Item -LiteralPath $BuildDir -Recurse -Force -ErrorAction SilentlyContinue
New-Item -ItemType Directory -Force -Path $DistBackend | Out-Null

# 用 spec 打包（含 hiddenimports：assemble_spec/ai_extract/meter_profile/io_utils 等惰性
# import 模块，否则 onefile 冻结环境点「装配/AI 抽取」会 ModuleNotFoundError）。
$BackendSpec = Join-Path $PSScriptRoot "desktop_backend.spec"
& $Python -m PyInstaller --clean --noconfirm --distpath $DistBackend --workpath $BuildDir $BackendSpec

if (-not (Test-Path $Exe)) {
    throw "Backend executable was not created: $Exe"
}

function Invoke-BackendJson {
    param(
        [Parameter(Mandatory = $true)]
        [string[]]$ArgumentList
    )
    $Output = & $Exe @ArgumentList
    if ($LASTEXITCODE -ne 0) {
        throw "Backend smoke command failed ($LASTEXITCODE): $($ArgumentList -join ' ')"
    }
    $Json = ($Output | Where-Object { $_ -notlike "__RATOMIZER_PROGRESS__*" }) -join "`n"
    $Json | ConvertFrom-Json | Out-Null
}

$SmokeOut = Join-Path $env:TEMP ("ratomizer-backend-smoke-" + [guid]::NewGuid().ToString("N"))
New-Item -ItemType Directory -Force -Path $SmokeOut | Out-Null
try {
    Invoke-BackendJson @("summary", "--out", $SmokeOut)

    $SmokeDocx = Join-Path $SmokeOut "sample.docx"
    $SmokeRunOut = Join-Path $SmokeOut "run"
    python -c "from docx import Document; import sys; doc=Document(); doc.add_heading('Scope', level=1); doc.add_paragraph('The meter shall expose active energy import total through OBIS 1-0:1.8.0.255.'); doc.save(sys.argv[1])" $SmokeDocx
    Push-Location $env:TEMP
    try {
        Invoke-BackendJson @("run", "--input", $SmokeDocx, "--out", $SmokeRunOut)
    } finally {
        Pop-Location
    }
} finally {
    Remove-Item -LiteralPath $SmokeOut -Recurse -Force -ErrorAction SilentlyContinue
}

Write-Host "Built backend executable: $Exe"
