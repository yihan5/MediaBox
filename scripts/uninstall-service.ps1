# 删除 MediaBox 服务（不会删除已下载的视频和数据库）。以管理员身份运行。
param(
    [string]$Nssm = "nssm",
    [string]$ServiceName = "MediaBox"
)
$ErrorActionPreference = "Stop"
& $Nssm stop $ServiceName
& $Nssm remove $ServiceName confirm
Write-Host "已删除服务 $ServiceName。" -ForegroundColor Green
