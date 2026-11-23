# MediaBox 首次安装：创建虚拟环境、安装依赖、生成配置文件
# 用法（在项目文件夹里打开 PowerShell）：
#   powershell -ExecutionPolicy Bypass -File .\scripts\setup.ps1

$ErrorActionPreference = "Stop"
$Root = Split-Path -Parent $PSScriptRoot
Set-Location $Root

Write-Host "== 1/4 检查 Python ==" -ForegroundColor Cyan
# 优先用 Python 官方安装器自带的 py 启动器，没有的话用 python
$PyExe = "python"; $PyArgs = @()
if (Get-Command py -ErrorAction SilentlyContinue) { $PyExe = "py"; $PyArgs = @("-3") }
& $PyExe @PyArgs -c "import sys; assert sys.version_info >= (3, 11), sys.version; print(sys.version)"
if ($LASTEXITCODE -ne 0) { throw "需要 Python 3.11 或更新版本。" }

Write-Host "== 2/4 创建虚拟环境 .venv ==" -ForegroundColor Cyan
if (-not (Test-Path ".venv")) {
    & $PyExe @PyArgs -m venv .venv
}
$VenvPy = Join-Path $Root ".venv\Scripts\python.exe"

Write-Host "== 3/4 安装依赖 ==" -ForegroundColor Cyan
& $VenvPy -m pip install --upgrade pip
& $VenvPy -m pip install -r requirements.txt
if ($LASTEXITCODE -ne 0) { throw "依赖安装失败。" }

Write-Host "== 4/4 配置文件 ==" -ForegroundColor Cyan
if (-not (Test-Path "config.toml")) {
    Copy-Item "config.example.toml" "config.toml"
    Write-Host "已生成 config.toml，请用记事本打开修改（至少要改 api_key 和 media_root）。" -ForegroundColor Yellow
} else {
    Write-Host "config.toml 已存在，不覆盖。"
}
New-Item -ItemType Directory -Force -Path "cookies", "data" | Out-Null

Write-Host ""
Write-Host "检查外部工具：" -ForegroundColor Cyan
foreach ($tool in @("ffmpeg", "deno")) {
    $t = Get-Command $tool -ErrorAction SilentlyContinue
    if ($t) { Write-Host "  [OK] $tool -> $($t.Source)" -ForegroundColor Green }
    else    { Write-Host "  [缺少] $tool（安装方法见 README）" -ForegroundColor Yellow }
}
Write-Host ""
Write-Host "完成。改好 config.toml 后，运行下面的命令试运行：" -ForegroundColor Green
Write-Host "  .\.venv\Scripts\python.exe run.py"
