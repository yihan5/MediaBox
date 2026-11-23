"""读取 config.toml。

所有相对路径都按「项目根目录」解析，而不是按当前工作目录。
这样无论是手动运行还是作为 Windows 服务（工作目录可能是 C:\\Windows\\System32）运行，
找到的都是同一套文件。
"""

from __future__ import annotations

import os
import tomllib
from dataclasses import dataclass, field
from pathlib import Path

# mediabox/config.py -> 项目根目录
PROJECT_ROOT = Path(__file__).resolve().parent.parent


def _resolve(p: str | None) -> Path | None:
    if not p:
        return None
    path = Path(os.path.expandvars(p)).expanduser()
    if not path.is_absolute():
        path = PROJECT_ROOT / path
    return path


@dataclass
class ServerConfig:
    host: str = "127.0.0.1"
    port: int = 8765
    api_key: str = ""


@dataclass
class PathsConfig:
    media_root: Path = Path(r"D:\Share\Media")
    data_dir: Path = PROJECT_ROOT / "data"
    bilibili_cookies: Path | None = None
    youtube_cookies: Path | None = None
    # 作为 Windows 服务运行时看不到「用户 PATH」，ffmpeg / deno 若装在用户目录下会找不到。
    # 把它们所在的文件夹写在这里，程序启动时会加到 PATH 最前面。
    extra_bin_dirs: list[Path] = field(default_factory=list)


@dataclass
class QuotaConfig:
    daily_minutes: int = 90
    daily_count: int = 5
    day_starts_at_hour: int = 2


@dataclass
class DownloadConfig:
    max_height: int = 1080
    prefer_h264: bool = False
    subtitle_langs: list[str] = field(default_factory=lambda: ["zh.*", "en.*"])
    rate_limit: str = ""
    title_max_bytes: int = 120
    bilibili_min_expected_height: int = 720


@dataclass
class TelegramConfig:
    bot_token: str = ""
    chat_id: str = ""

    @property
    def enabled(self) -> bool:
        return bool(self.bot_token and self.chat_id)


@dataclass
class Config:
    server: ServerConfig
    paths: PathsConfig
    quota: QuotaConfig
    download: DownloadConfig
    telegram: TelegramConfig


class ConfigError(Exception):
    pass


def load_config(path: str | os.PathLike | None = None) -> Config:
    if path is None:
        path = os.environ.get("MEDIABOX_CONFIG") or (PROJECT_ROOT / "config.toml")
    path = Path(path)
    if not path.exists():
        raise ConfigError(
            f"找不到配置文件：{path}\n"
            f"请先复制 config.example.toml 为 config.toml 并按说明修改。"
        )
    # 用记事本「UTF-8 带 BOM」保存的文件开头会多一个 BOM，tomllib 不认，这里去掉
    text = path.read_bytes().decode("utf-8-sig")
    try:
        raw = tomllib.loads(text)
    except tomllib.TOMLDecodeError as e:
        raise ConfigError(
            f"config.toml 格式有误：{e}\n"
            f"常见原因：Windows 路径用了双引号，比如 \"D:\\Share\"，请改成单引号 'D:\\Share'。"
        ) from e

    s = raw.get("server", {})
    p = raw.get("paths", {})
    q = raw.get("quota", {})
    d = raw.get("download", {})
    t = raw.get("telegram", {})

    server = ServerConfig(
        host=s.get("host", "127.0.0.1"),
        port=int(s.get("port", 8765)),
        api_key=str(s.get("api_key", "")),
    )
    paths = PathsConfig(
        media_root=_resolve(p.get("media_root")) or PathsConfig.media_root,
        data_dir=_resolve(p.get("data_dir", "data")),
        bilibili_cookies=_resolve(p.get("bilibili_cookies")),
        youtube_cookies=_resolve(p.get("youtube_cookies")),
        extra_bin_dirs=[_resolve(x) for x in p.get("extra_bin_dirs", []) if x],
    )
    quota = QuotaConfig(
        daily_minutes=int(q.get("daily_minutes", 90)),
        daily_count=int(q.get("daily_count", 5)),
        day_starts_at_hour=int(q.get("day_starts_at_hour", 2)),
    )
    download = DownloadConfig(
        max_height=int(d.get("max_height", 1080)),
        prefer_h264=bool(d.get("prefer_h264", False)),
        subtitle_langs=list(d.get("subtitle_langs", ["zh.*", "en.*"])),
        rate_limit=str(d.get("rate_limit", "")),
        title_max_bytes=int(d.get("title_max_bytes", 120)),
        bilibili_min_expected_height=int(d.get("bilibili_min_expected_height", 720)),
    )
    telegram = TelegramConfig(
        bot_token=str(t.get("bot_token", "")),
        chat_id=str(t.get("chat_id", "")),
    )

    # ---- 基本校验：配置错了宁可启动失败，也不要带着错误规则悄悄运行 ----
    if not server.api_key or server.api_key == "change-me":
        raise ConfigError("请在 config.toml 的 [server] 里设置 api_key（不要用默认值 change-me）。")
    if not (0 <= quota.day_starts_at_hour <= 23):
        raise ConfigError("[quota] day_starts_at_hour 必须在 0~23 之间。")
    if quota.daily_minutes <= 0 or quota.daily_count <= 0:
        raise ConfigError("[quota] daily_minutes 和 daily_count 必须大于 0。")

    return Config(server, paths, quota, download, telegram)


def apply_extra_bin_dirs(cfg: Config) -> None:
    """把 extra_bin_dirs 加到 PATH 最前面，让 yt-dlp 能找到 ffmpeg / deno。"""
    dirs = [str(d) for d in cfg.paths.extra_bin_dirs if d]
    if dirs:
        os.environ["PATH"] = os.pathsep.join(dirs + [os.environ.get("PATH", "")])
