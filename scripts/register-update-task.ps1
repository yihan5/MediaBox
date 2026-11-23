# 注册「每周自动更新 yt-dlp」的任务计划。以管理员身份运行一次即可。
# 默认每周一 04:30 运行（这个时间一般不会正在看视频，也已经过了凌晨 2 点的日期切换）。

param(
    [string]$Nssm = "nssm",
    [string]$At = "04:30",
    [string]$TaskName = "MediaBox 更新 yt-dlp"
)

$ErrorActionPreference = "Stop"
$Root = Split-Path -Parent $PSScriptRoot
$Script = Join-Path $Root "scripts\update-ytdlp.ps1"

# 任务以 SYSTEM 身份运行，看不到你个人的 PATH，所以这里先把 nssm 解析成完整路径
$cmd = Get-Command $Nssm -ErrorAction SilentlyContinue
if (-not $cmd) { throw "找不到 nssm：$Nssm。请用 -Nssm 指定 nssm.exe 的完整路径。" }
$Nssm = $cmd.Source

$action = New-ScheduledTaskAction -Execute "powershell.exe" `
    -Argument "-NoProfile -ExecutionPolicy Bypass -File `"$Script`" -Nssm `"$Nssm`""
$trigger = New-ScheduledTaskTrigger -Weekly -DaysOfWeek Monday -At $At
# 用 SYSTEM 身份运行，不需要登录；错过了（比如当时关机）开机后补跑
$principal = New-ScheduledTaskPrincipal -UserId "SYSTEM" -LogonType ServiceAccount -RunLevel Highest
$settings = New-ScheduledTaskSettingsSet -StartWhenAvailable -ExecutionTimeLimit (New-TimeSpan -Minutes 30)

Register-ScheduledTask -TaskName $TaskName -Action $action -Trigger $trigger `
    -Principal $principal -Settings $settings -Force | Out-Null

Write-Host "已注册任务计划「$TaskName」：每周一 $At 更新 yt-dlp。" -ForegroundColor Green
Write-Host "想立刻试一次：Start-ScheduledTask -TaskName '$TaskName'"
