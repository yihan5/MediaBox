# 把 MediaBox 注册成 Windows 服务：开机自动启动、崩溃后自动重启。
# 需要：已安装 NSSM（https://nssm.cc），并且已经跑过 setup.ps1。
# 用法（以管理员身份打开 PowerShell）：
#   powershell -ExecutionPolicy Bypass -File .\scripts\install-service.ps1
#   如果 nssm.exe 不在 PATH 里： ... -Nssm 'C:\tools\nssm\win64\nssm.exe'

param(
    [string]$Nssm = "nssm",
    [string]$ServiceName = "MediaBox"
)

$ErrorActionPreference = "Stop"

$isAdmin = ([Security.Principal.WindowsPrincipal][Security.Principal.WindowsIdentity]::GetCurrent()
           ).IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)
if (-not $isAdmin) { throw "请以管理员身份运行 PowerShell。" }

$Root = Split-Path -Parent $PSScriptRoot
$VenvPy = Join-Path $Root ".venv\Scripts\python.exe"
$RunPy = Join-Path $Root "run.py"
$LogDir = Join-Path $Root "data\logs"

if (-not (Test-Path $VenvPy)) { throw "找不到 $VenvPy，请先运行 scripts\setup.ps1。" }
if (-not (Test-Path (Join-Path $Root "config.toml"))) { throw "找不到 config.toml，请先配置。" }
New-Item -ItemType Directory -Force -Path $LogDir | Out-Null

$existing = Get-Service -Name $ServiceName -ErrorAction SilentlyContinue
if ($existing) {
    Write-Host "服务 $ServiceName 已存在，先停止并删除旧的……"
    & $Nssm stop $ServiceName | Out-Null
    & $Nssm remove $ServiceName confirm | Out-Null
}

& $Nssm install $ServiceName $VenvPy $RunPy
& $Nssm set $ServiceName AppDirectory $Root
& $Nssm set $ServiceName DisplayName "MediaBox 视频下载"
& $Nssm set $ServiceName Description "接收链接，按每日额度下载 B 站 / YouTube 视频"
& $Nssm set $ServiceName Start SERVICE_AUTO_START
# 让 Python 输出 UTF-8，避免中文日志乱码
& $Nssm set $ServiceName AppEnvironmentExtra "PYTHONUTF8=1" "PYTHONIOENCODING=utf-8"
# 程序退出就自动重启（5 秒后）
& $Nssm set $ServiceName AppExit Default Restart
& $Nssm set $ServiceName AppRestartDelay 5000
# 服务自身的标准输出（程序本身另外写 data\logs\mediabox.log）
& $Nssm set $ServiceName AppStdout (Join-Path $LogDir "service-stdout.log")
& $Nssm set $ServiceName AppStderr (Join-Path $LogDir "service-stderr.log")
& $Nssm set $ServiceName AppRotateFiles 1
& $Nssm set $ServiceName AppRotateBytes 2097152

& $Nssm start $ServiceName
Start-Sleep -Seconds 3
& $Nssm status $ServiceName

Write-Host ""
Write-Host "完成。浏览器打开 http://127.0.0.1:8765 检查（端口以 config.toml 为准）。" -ForegroundColor Green
Write-Host "常用命令： nssm restart $ServiceName   /   nssm stop $ServiceName   /   nssm status $ServiceName"
