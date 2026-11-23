"""和 yt-dlp 打交道的部分：识别链接、只取信息（不下载）、真正下载。

yt-dlp 作为 Python 库调用，不另开命令行进程。
"""

from __future__ import annotations

import logging
import re
import urllib.request
from dataclasses import dataclass
from datetime import date
from pathlib import Path
from urllib.parse import urlparse

from .config import Config

log = logging.getLogger(__name__)

# 只放行这两个平台。dsh 提取错了链接、或者发来别的网站，都在这里挡掉。
ALLOWED_HOSTS = {
    "bilibili": ("bilibili.com", "b23.tv"),
    "youtube": ("youtube.com", "youtu.be"),
}

URL_RE = re.compile(r"https?://[^\s<>\"'，。；！？【】（）]+", re.IGNORECASE)


class LinkError(Exception):
    """链接本身的问题（不是 B 站/YouTube、是直播、是合集……）。会原样告诉用户。"""


@dataclass
class VideoInfo:
    platform: str
    video_id: str
    url: str           # 用来下载的链接（短链接已展开）
    webpage_url: str | None
    title: str
    uploader: str | None
    duration: int      # 秒


@dataclass
class DownloadResult:
    file_path: str | None
    height: int | None


# ---------------------------------------------------------------------------
# 链接处理
# ---------------------------------------------------------------------------

def extract_url(text: str) -> str:
    """从一段文字里取出第一个链接。

    B 站 App 分享出来的往往是「【标题】 https://b23.tv/xxxx」这样的一段话，
    页面输入框里直接粘贴整段也能用。
    """
    m = URL_RE.search(text or "")
    if not m:
        raise LinkError("没有在内容里找到链接。")
    return m.group(0).rstrip(".,)")


def platform_of(url: str) -> str:
    host = (urlparse(url).hostname or "").lower()
    for platform, suffixes in ALLOWED_HOSTS.items():
        for suffix in suffixes:
            if host == suffix or host.endswith("." + suffix):
                return platform
    raise LinkError(f"只支持 B 站和 YouTube 的链接，这个链接的网站是：{host or '未知'}。")


def expand_short_link(url: str) -> str:
    """展开 b23.tv 短链接，得到真正的 bilibili.com 地址。"""
    host = (urlparse(url).hostname or "").lower()
    if not (host == "b23.tv" or host.endswith(".b23.tv")):
        return url
    req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
    try:
        with urllib.request.urlopen(req, timeout=15) as resp:
            final = resp.geturl()
    except Exception as e:  # noqa: BLE001
        raise LinkError(f"b23.tv 短链接展开失败：{e}") from e
    # 展开后必须仍然是 B 站，防止短链接跳到别的网站
    if platform_of(final) != "bilibili":
        raise LinkError("这个 b23.tv 短链接跳转到的不是 B 站视频。")
    return final


def _clean_error(e: Exception) -> str:
    msg = re.sub(r"\x1b\[[0-9;]*m", "", str(e))  # 去掉终端颜色码
    msg = msg.replace("ERROR: ", "").strip()
    return msg[:500] or e.__class__.__name__


# ---------------------------------------------------------------------------
# yt-dlp
# ---------------------------------------------------------------------------

class Downloader:
    def __init__(self, cfg: Config):
        self.cfg = cfg

    def _cookie_opts(self, platform: str) -> dict:
        cookie = {
            "bilibili": self.cfg.paths.bilibili_cookies,
            "youtube": self.cfg.paths.youtube_cookies,
        }.get(platform)
        if cookie and Path(cookie).exists():
            return {"cookiefile": str(cookie)}
        if cookie:
            log.warning("配置了 cookie 文件但找不到：%s", cookie)
        return {}

    def _base_opts(self, platform: str) -> dict:
        return {
            "quiet": True,
            "no_warnings": False,
            "noprogress": True,
            "noplaylist": True,          # 分 P / 合集：只取你发的那一个
            "logger": logging.getLogger("yt_dlp"),
            "socket_timeout": 30,
            **self._cookie_opts(platform),
        }

    def probe(self, url: str) -> VideoInfo:
        """只取信息、不下载。拿到 ID、标题、时长，用来查重和查额度。"""
        import yt_dlp  # 延迟导入：方便在没装 yt-dlp 的环境里测试其他逻辑

        url = expand_short_link(url)
        platform = platform_of(url)
        opts = {**self._base_opts(platform), "skip_download": True}
        try:
            with yt_dlp.YoutubeDL(opts) as ydl:
                info = ydl.extract_info(url, download=False, process=False)
        except Exception as e:  # noqa: BLE001
            raise LinkError(f"解析链接失败：{_clean_error(e)}") from e

        if info is None:
            raise LinkError("解析链接失败：yt-dlp 没有返回任何信息。")
        if info.get("_type") in ("url", "url_transparent"):
            # process=False 时偶尔会拿到一层跳转，完整解析一次
            try:
                with yt_dlp.YoutubeDL(opts) as ydl:
                    info = ydl.extract_info(url, download=False)
            except Exception as e:  # noqa: BLE001
                raise LinkError(f"解析链接失败：{_clean_error(e)}") from e
        if info.get("_type") in ("playlist", "multi_video"):
            raise LinkError("这是一个合集或播放列表，请发单个视频的链接。")
        if info.get("is_live") or info.get("live_status") in ("is_live", "is_upcoming"):
            raise LinkError("这是直播（或还没开始的直播），不支持下载。")
        duration = info.get("duration")
        if not duration:
            raise LinkError("拿不到这个视频的时长，没法计算额度，所以不下载。")

        return VideoInfo(
            platform=platform,
            video_id=str(info.get("id")),
            url=url,
            webpage_url=info.get("webpage_url") or url,
            title=info.get("title") or str(info.get("id")),
            uploader=info.get("uploader") or info.get("channel"),
            duration=int(round(float(duration))),
        )

    def _download_opts(self, platform: str, day_dir: Path, with_extras: bool) -> dict:
        d = self.cfg.download
        h = d.max_height
        opts = {
            **self._base_opts(platform),
            "paths": {"home": str(day_dir)},
            # 标题按字节截断（中文一个字 3 字节），后面带上 ID 保证不重名
            "outtmpl": {"default": f"%(title).{d.title_max_bytes}B [%(id)s].%(ext)s"},
            "windowsfilenames": True,
            "format": f"bv*[height<={h}]+ba/b[height<={h}]/bv*+ba/b",
            "merge_output_format": "mp4",
            "retries": 5,
            "fragment_retries": 5,
            "overwrites": False,
        }
        if d.prefer_h264:
            # 优先 H.264 + AAC：所有设备都能硬解，文件会稍大
            opts["format_sort"] = ["vcodec:h264", "acodec:m4a"]
        if d.rate_limit:
            opts["ratelimit"] = _parse_rate(d.rate_limit)

        if with_extras:
            opts.update(
                {
                    "writethumbnail": True,
                    "writesubtitles": True,        # 只要人工字幕
                    "writeautomaticsub": False,    # 不要 YouTube 自动生成的字幕
                    "subtitleslangs": d.subtitle_langs,
                    "postprocessors": [
                        # 顺序和 yt-dlp 命令行 --convert-subs srt --convert-thumbnails jpg
                        # --embed-subs --embed-thumbnail 生成的一致
                        {"key": "FFmpegSubtitlesConvertor", "format": "srt", "when": "before_dl"},
                        {"key": "FFmpegThumbnailsConvertor", "format": "jpg", "when": "before_dl"},
                        {"key": "FFmpegEmbedSubtitle", "already_have_subtitle": False},
                        {"key": "EmbedThumbnail", "already_have_thumbnail": False},
                    ],
                }
            )
        return opts

    def download(self, url: str, platform: str, day: date) -> DownloadResult:
        import yt_dlp

        day_dir = Path(self.cfg.paths.media_root) / day.isoformat()
        day_dir.mkdir(parents=True, exist_ok=True)

        try:
            return self._run(yt_dlp, url, self._download_opts(platform, day_dir, True))
        except Exception as e:  # noqa: BLE001
            msg = _clean_error(e).lower()
            # 字幕或封面出问题时，不应该让整个视频下载失败：去掉这些再试一次
            if any(k in msg for k in ("subtitle", "thumbnail", "postprocess", "embed")):
                log.warning("嵌入字幕/封面失败，改为只下载视频再试一次：%s", msg)
                return self._run(yt_dlp, url, self._download_opts(platform, day_dir, False))
            raise

    @staticmethod
    def _run(yt_dlp, url: str, opts: dict) -> DownloadResult:
        with yt_dlp.YoutubeDL(opts) as ydl:
            info = ydl.extract_info(url, download=True)
        downloads = (info or {}).get("requested_downloads") or [{}]
        return DownloadResult(
            file_path=downloads[0].get("filepath") or downloads[0].get("_filename"),
            height=(info or {}).get("height"),
        )


def _parse_rate(text: str) -> int:
    """'5M' -> 5*1024*1024 字节/秒。"""
    m = re.fullmatch(r"\s*(\d+(?:\.\d+)?)\s*([KMG]?)\s*B?\s*", text, re.IGNORECASE)
    if not m:
        raise ValueError(f"rate_limit 格式不对：{text!r}，应该像 '5M' 或 '800K'")
    n = float(m.group(1))
    unit = m.group(2).upper()
    return int(n * {"": 1, "K": 1024, "M": 1024**2, "G": 1024**3}[unit])


def friendly_error(e: Exception) -> str:
    return _clean_error(e)
