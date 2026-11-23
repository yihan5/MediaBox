# Windows 部署与使用

[返回首页](../README.md)

以下步骤均在运行 MediaBox 的 Windows 电脑上操作。命令都在 **PowerShell** 里运行。

<a id="tools"></a>

## 准备外部工具

| 工具 | 用途 | 安装方式（任选一种） |
|---|---|---|
| **Python 3.11+**（推荐 3.12 或更新） | 运行程序 | [python.org](https://www.python.org/downloads/windows/) 下载安装包，**安装时勾选 "Add python.exe to PATH"**；或者 `winget install Python.Python.3.12` |
| **ffmpeg** | 合并音视频、嵌入封面和字幕 | `winget install Gyan.FFmpeg` |
| **Deno** | YouTube 需要它来执行网页里的验证脚本 | `winget install DenoLand.Deno` |
| **NSSM** | 把程序注册成 Windows 服务 | `winget install NSSM.NSSM`，或者从 [nssm.cc](https://nssm.cc/download) 下载并解压 |

装完后**关掉 PowerShell 再重新打开**，然后检查：

```powershell
python --version
ffmpeg -version
deno --version
nssm version
```

> 关于 Deno：新版 yt-dlp 下载 YouTube 时，需要一个 JavaScript 运行环境来处理网页里的验证，官方推荐用 Deno。具体要求可能会变，以 [yt-dlp 的说明](https://github.com/yt-dlp/yt-dlp#dependencies) 为准。只下载 B 站的话不需要 Deno。

<a id="location"></a>

## 放置项目文件夹

把整个 `MediaBox` 文件夹放到一个固定的位置，比如 `C:\MediaBox`。

- **不要**放在 `D:\Share` 里面，否则你的配置和密钥也会被共享出去。
- **不要**放在 OneDrive 之类的同步文件夹里，数据库文件被同步时可能会出问题。

<a id="setup"></a>

## 运行安装脚本

```powershell
cd C:\MediaBox
powershell -ExecutionPolicy Bypass -File .\scripts\setup.ps1
```

这个脚本会做四件事：创建虚拟环境 `.venv`、安装依赖、从模板复制出 `config.toml`、创建 `cookies` 和 `data` 文件夹。最后它会检查 ffmpeg 和 deno 有没有装好。

<a id="settings"></a>

## 修改配置

用记事本打开 `config.toml`，至少要改下面两项：

1. **`api_key`**：改成一串随机字符。可以用这条命令生成：
   ```powershell
   -join ((48..57)+(65..90)+(97..122) | Get-Random -Count 32 | % {[char]$_})
   ```
2. **`media_root`**：改成你通过 SMB 共享出去的那个文件夹，比如 `'D:\Share'`。

其他配置项的含义见[配置项参考](reference.md#settings)。B 站 cookie 和 Telegram 通知见下文的 [cookie](#cookies) 和[通知设置](#telegram)，也可以以后再配。

> Windows 路径请用**单引号**，比如 `'D:\Share'`。用双引号的话，反斜杠需要写成 `\\`。

<a id="trial"></a>

## 试运行

```powershell
cd C:\MediaBox
.\.venv\Scripts\python.exe run.py
```

看到 `MediaBox 已启动：http://127.0.0.1:8765` 就说明启动成功了。用浏览器打开 <http://127.0.0.1:8765>，输入 `api_key`，就能看到管理页面。

**另开一个 PowerShell 窗口测试接口：**

```powershell
$key = "你的api_key"
Invoke-RestMethod -Method Post -Uri http://127.0.0.1:8765/api/links `
  -Headers @{ "X-API-Key" = $key } -ContentType "application/json; charset=utf-8" `
  -Body ([Text.Encoding]::UTF8.GetBytes('{"url": "https://www.bilibili.com/video/BV1xx411c7mD"}'))

Invoke-RestMethod -Uri http://127.0.0.1:8765/api/status -Headers @{ "X-API-Key" = $key }
```

把链接换成你想测试的视频。注意测试用的视频也会计入当天的额度。

**运行规则测试**（不联网，也不会下载任何东西）：

```powershell
.\.venv\Scripts\python.exe -m unittest discover -s tests -v
```

测试没问题后，在运行 `run.py` 的那个窗口里按 `Ctrl+C` 停止，接着进入下一步。

<a id="service"></a>

## 注册成 Windows 服务

**以管理员身份**打开 PowerShell：

```powershell
cd C:\MediaBox
powershell -ExecutionPolicy Bypass -File .\scripts\install-service.ps1
# 如果 nssm 不在 PATH 里：
# powershell -ExecutionPolicy Bypass -File .\scripts\install-service.ps1 -Nssm 'C:\tools\nssm\win64\nssm.exe'
```

注册完成后，MediaBox 会开机自动启动，崩溃了 5 秒后自动重启。

> **重要：服务看不到你个人的 PATH。**
> 服务默认以 SYSTEM 账户运行，只能看到系统级的 PATH。winget 装的 ffmpeg 和 Deno 通常在你的用户目录下，服务会找不到它们。解决方法是先查出它们所在的文件夹：
> ```powershell
> Split-Path (Get-Command ffmpeg).Source
> Split-Path (Get-Command deno).Source
> ```
> 然后把查到的路径写进 `config.toml`：
> ```toml
> extra_bin_dirs = ['C:\Users\你\AppData\Local\Microsoft\WinGet\Links', 'C:\Users\你\.deno\bin']
> ```
> 改完后运行 `nssm restart MediaBox`。

<a id="updates"></a>

## 注册每周自动更新 yt-dlp

**以管理员身份**运行：

```powershell
powershell -ExecutionPolicy Bypass -File .\scripts\register-update-task.ps1
```

注册后，每周一 04:30 会自动更新 yt-dlp。如果当时电脑关着，开机后会补上。更新期间服务会停一两分钟。

<a id="sleep"></a>

## 让电脑不休眠

```powershell
powercfg /change standby-timeout-ac 0
```

<a id="playback"></a>

## 在手机上观看

在 iPhone 上装 **VLC**，然后：网络 → 连接到服务器 → SMB → 填 Tailscale IP、用户名和密码，再打开当天的日期文件夹就能看了。在 Mac 上，用 Finder 连接 `smb://100.x.x.x/Share` 后，用 VLC 打开文件即可。

iPhone 自带的播放器不一定能放 VP9 或 AV1，所以建议统一用 VLC。

<a id="cookies"></a>

## B 站 cookie

未登录时可选画质可能受限。cookie 可让下载器使用当前账号能访问的格式，但不会提高片源本身的清晰度。

**导出步骤：**

1. 在 Chrome 或 Edge 里安装一个导出 cookies.txt 的扩展，比如 "Get cookies.txt LOCALLY"。
2. 打开 bilibili.com，确认已经登录。
3. 点扩展图标，导出当前网站的 cookie（格式选 Netscape，也就是 cookies.txt 格式）。
4. 把文件保存为 `C:\MediaBox\cookies\bilibili.txt`。
5. 运行 `nssm restart MediaBox`。

**注意：**

- **cookie 文件相当于你的登录状态**，别人拿到它就能登录你的 B 站账号。不要分享它，也不要把它放进共享文件夹。
- cookie 会过期。过期后可能只能选择较低画质。MediaBox 发现 B 站视频的画质低于 720P 时，会在通知里提醒你。这时重新导出一次就行。如果视频本身的原始画质就很低，也会触发这个提醒，可以忽略。
- yt-dlp 有一个 `--cookies-from-browser` 功能，可以直接读取浏览器的 cookie。但新版 Chrome 和 Edge 在 Windows 上对 cookie 做了加密，这个功能经常读不出来，所以这里用导出文件的方式。

YouTube 一般不需要 cookie。如果遇到「Sign in to confirm you're not a bot」这样的错误，可以用同样的方法导出 youtube.com 的 cookie，填到 `youtube_cookies` 里。

<a id="telegram"></a>

## Telegram 通知

下载完成或失败时，MediaBox 会直接发 Telegram 消息给你。

1. **`bot_token`**：用 dsh 现在用的那个 bot 的 token 就行。MediaBox 只发消息、不收消息，不会和 dsh 抢消息。
2. **`chat_id`**：就是你的 Telegram 用户 ID，是一串数字。获取方法：在 Telegram 里搜索 **@userinfobot**，给它发任意一条消息，它会回复你的 ID。
   - 不建议用 `getUpdates` 接口去查 ID。dsh 正在用同一个 bot 收消息，同时调用 `getUpdates` 会和 dsh 冲突。
3. 你必须**先给自己的 bot 发过至少一条消息**，bot 才能主动给你发消息。你一直在用 dsh 的话，这一条已经满足了。
4. 填好后运行 `nssm restart MediaBox`。

通知的样子：

```
✅ 已下好：《xxxx》（12分30秒）
文件夹：2026-11-22
画质：1080P
```

```
❌ 下载失败：《xxxx》
原因：……
这一个不计入今天的额度。
```

两项都留空的话就不发通知，只写日志。

<a id="dsh"></a>

## 接入 dsh

`dsh\tools.json` 里定义了两个工具，格式是 OpenAI / DeepSeek 通用的 function calling 格式：

| 工具 | 对应接口 | 什么时候用 |
|---|---|---|
| `submit_media_link(url)` | `POST /api/links` | 收到 B 站或 YouTube 链接时 |
| `get_media_status()` | `GET /api/status` | 你问「今天还剩多少」「下好了没」时 |

这里提供的是工具定义和请求示例，不是即装即用的 dsh 插件。每个工具定义里还有一个 `http` 字段，写明了实际要发的请求。dsh 怎么把工具调用变成 HTTP 请求，要看它自己的实现，按它的格式改一下就行。关键是三点：

- 地址是 `http://127.0.0.1:8765`。
- 请求头里要带 `X-API-Key`。
- 提交链接时转述 `message`；查询状态时读取 `summary`，需要明细时再读取 `today` 或 `pending`。

再把 `dsh\system-prompt.md` 里的内容加到 dsh 的系统提示词里。最重要的一条是：**额度由 MediaBox 决定，dsh 不能破例，也不能尝试绕过。**

MediaBox 没有修改额度的 HTTP 接口。

<a id="daily"></a>

## 日常使用

| 想做的事 | 怎么做 |
|---|---|
| 下载视频 | 在 App 里点分享 → Telegram → 发给 dsh |
| 看今天还剩多少 | 问 dsh，或者在电脑上打开 <http://127.0.0.1:8765> |
| 看视频 | VLC → SMB → 日期文件夹 |
| 下载失败了 | 看通知里的原因。如果是临时问题（比如网络中断），重新发一次链接就行，失败的不计入额度 |
| 改额度 | 改 `config.toml` 的 `[quota]`，再运行 `nssm restart MediaBox`。故意设计得麻烦一点 |
| 删掉看完的视频 | 直接在「文件」App 或 Finder 里删就行。下载记录还留在数据库里，所以同一个视频再发一次会被当成重复 |
| 重新下载以前删掉的视频 | 目前要手动处理，见[故障排查](#troubleshooting) |

<a id="files"></a>

## 文件和日志

| 内容 | 位置 |
|---|---|
| 视频 | `D:\Share\YYYY-MM-DD\标题 [视频ID].mp4` |
| 数据库 | `C:\MediaBox\data\mediabox.db` |
| 程序日志 | `C:\MediaBox\data\logs\mediabox.log`（最多保留 5 个 × 2 MB，自动轮换） |
| 服务的输出 | `C:\MediaBox\data\logs\service-stdout.log`、`service-stderr.log` |
| yt-dlp 更新记录 | `C:\MediaBox\data\logs\update-ytdlp.log` |

数据库可以用 [DB Browser for SQLite](https://sqlitebrowser.org/) 打开查看。

<a id="troubleshooting"></a>

## 常见问题与排错

**服务启动不起来，或者一直在重启**
先看 `data\logs\service-stderr.log`。常见的原因有三个：`config.toml` 格式写错（比如路径用了双引号，但反斜杠没写成 `\\`）、没有改 `api_key`，或者端口被别的程序占用了。

**dsh 连不上 MediaBox**
先在浏览器里打开 <http://127.0.0.1:8765/api/health>。打不开，说明服务没在运行，运行 `nssm status MediaBox` 看一下状态。能打开，就检查 dsh 用的密钥和 `config.toml` 里的是否一致。

**所有视频都下载失败，原因里提到 ffmpeg**
服务找不到 ffmpeg。按 [服务设置](#service) 的说明配置 `extra_bin_dirs`。

**YouTube 下载失败**
按顺序试三件事：
1. 手动更新 yt-dlp（管理员 PowerShell）：`powershell -ExecutionPolicy Bypass -File .\scripts\update-ytdlp.ps1`
2. 确认 Deno 装好了，并且服务能找到它（同样要检查 `extra_bin_dirs`）。
3. 如果错误信息里有 "Sign in to confirm you're not a bot"，就配置 YouTube cookie。

**B 站只下到 480P**
先确认片源有更高画质，再检查 cookie 是否配置并有效。见[cookie 设置](#cookies)。

**提示「解析链接失败」**
可能是视频被删除了、需要大会员、有地区限制，或者 yt-dlp 太旧了。先更新 yt-dlp 再试。

**分 P 视频下载的不是我想要的那一 P**
B 站的链接要带上 `?p=3` 这样的参数，才能指定第几 P。从 App 的分 P 列表里分享出来的链接一般会自带这个参数。

**SMB 里看到了文件，但删不掉**
文件是服务（SYSTEM 账户）创建的，会继承 `D:\Share` 的权限。如果删不掉，就在 `D:\Share` 的属性 → 安全里，给你的用户加上「修改」权限，并勾选「应用到子文件夹和文件」。

**想重新下载一个以前删掉的视频**
因为下载记录还在，它会被当成重复。打开数据库，把那条记录的 `status` 改成 `failed` 再重新提交就行。不过要记得，这样重新下载会计入当天的额度。

**中文标题乱码**
程序已经强制使用 UTF-8。如果日志里还是有乱码，确认你看日志用的编辑器是按 UTF-8 打开的。

<a id="maintenance"></a>

## 维护

- **yt-dlp**：每周自动更新。如果中途遇到失败，可以随时手动运行 `scripts\update-ytdlp.ps1`。
- **其他依赖**：偶尔可以手动更新一下：`.\.venv\Scripts\python.exe -m pip install -U -r requirements.txt`，然后运行 `nssm restart MediaBox`。
- **备份**：真正需要备份的只有 `config.toml` 和 `data\mediabox.db`，视频本身是可以重新下载的。
- **删除服务**：`scripts\uninstall-service.ps1`（管理员）。删除服务不会删除视频和数据库。
