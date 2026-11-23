# 更新 yt-dlp。B 站 / YouTube 经常改版，yt-dlp 不更新就会下载失败。
# 一般由 register-update-task.ps1 注册的任务计划每周自动运行，也可以手动运行（管理员）。

param(
    [string]$Nssm = "nssm",
    [string]$ServiceName = "MediaBox"
)

$ErrorActionPreference = "Continue"
$Root = Split-Path -Parent $PSScriptRoot
$VenvPy = Join-Path $Root ".venv\Scripts\python.exe"
$Log = Join-Path $Root "data\logs\update-ytdlp.log"
New-Item -ItemType Directory -Force -Path (Split-Path $Log) | Out-Null

function Log($msg) { "$(Get-Date -Format 'yyyy-MM-dd HH:mm:ss') $msg" | Tee-Object -FilePath $Log -Append }

Log "开始更新 yt-dlp"
$before = & $VenvPy -c "import yt_dlp.version as v; print(v.__version__)" 2>$null

# 停掉服务再更新，避免正在下载时替换文件
& $Nssm stop $ServiceName 2>&1 | Out-Null
& $VenvPy -m pip install --upgrade "yt-dlp[default]" 2>&1 | Out-File -FilePath $Log -Append -Encoding utf8
& $Nssm start $ServiceName 2>&1 | Out-Null

$after = & $VenvPy -c "import yt_dlp.version as v; print(v.__version__)" 2>$null
Log "yt-dlp: $before -> $after"
