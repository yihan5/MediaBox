# MediaBox

在 Windows 上按每日额度下载 B 站和 YouTube 视频。把链接或整段分享文字粘进本机管理页，MediaBox 会逐个下载，按日期存成 MP4。把视频目录通过 SMB 共享后，就能在手机上用 VLC 观看。

默认每天收 **5 个视频**，凌晨 **2 点**换日。**90 分钟是停止接单的门槛，不是把视频截断的上限**：如果已用 80 分钟、还剩名额，再提交一个 30 分钟的视频会完整下载；当天不再收新视频，超出的 20 分钟不扣明天的额度。重复提交不重复计费，下载失败不占额度。

## 下载第一个视频

先在 Windows 本机试，不需要配置 Telegram、SMB 或开机服务。

1. 安装 **Python 3.11+** 和 **ffmpeg**；要下载 YouTube，再装 **Deno**。把项目解压到 `C:\MediaBox`，不要放进共享目录，以免暴露密钥和 cookie。各工具的安装命令见[环境准备](docs/windows.md#tools)。
2. 打开 PowerShell，创建运行环境并打开配置文件：

   ```powershell
   cd C:\MediaBox
   powershell -ExecutionPolicy Bypass -File .\scripts\setup.ps1
   notepad config.toml
   ```

3. 把 `[server]` 下的 `api_key` 换成自己的随机密钥，把 `[paths]` 下的 `media_root` 设为视频目录（例如 `'D:\Share'`）。保存后启动：

   ```powershell
   .\.venv\Scripts\python.exe run.py
   ```

4. 在本机打开 <http://127.0.0.1:8765>，输入密钥并点「保存」，再粘贴一个短视频链接，点「提交」。**「已加入」只表示排队成功**；等状态变为完成，在视频目录的日期子文件夹里打开 MP4，才算跑通。这个视频会计入当天额度。

## 接下来

- **想在手机上用：** [通过 SMB 观看](docs/windows.md#playback)，或[接入 Telegram 和 dsh](docs/windows.md#telegram)，从聊天里提交链接、接收结果。
- **想让它常驻：** [注册 Windows 服务](docs/windows.md#service)。如果手动运行正常、注册后下载失败，先检查服务能否找到 ffmpeg。
- **想改配置或接其他工具：** 查[配置项与 HTTP 接口](docs/reference.md)。管理页默认只监听本机，手机播放不需要对外开放管理页。
- **想维护项目：** 看[队列、去重与额度设计](docs/design.md)，或按症状查[故障排查](docs/windows.md#troubleshooting)。
