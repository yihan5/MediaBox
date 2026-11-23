r"""核心规则的测试：不联网、不需要 yt-dlp 和 FastAPI。

运行：  .\.venv\Scripts\python.exe -m unittest discover -s tests -v
"""

from __future__ import annotations

import tempfile
import unittest
from datetime import date, datetime
from pathlib import Path

from mediabox import quota
from mediabox.config import (
    Config, DownloadConfig, PathsConfig, QuotaConfig, ServerConfig, TelegramConfig,
)
from mediabox.db import Database
from mediabox.downloader import (
    DownloadResult, LinkError, VideoInfo, _parse_rate, extract_url, platform_of,
)
from mediabox.service import MediaService
from mediabox.worker import DownloadWorker


def make_cfg(tmp: Path) -> Config:
    return Config(
        server=ServerConfig(api_key="test"),
        paths=PathsConfig(media_root=tmp / "media", data_dir=tmp / "data"),
        quota=QuotaConfig(daily_minutes=90, daily_count=5, day_starts_at_hour=2),
        download=DownloadConfig(),
        telegram=TelegramConfig(),
    )


class FakeProbe:
    """假装解析链接：链接末尾写什么 ID、多少分钟，就返回什么。
    例：https://www.bilibili.com/video/BV1?min=30 -> ID BV1，30 分钟"""

    def __call__(self, url: str) -> VideoInfo:
        from urllib.parse import parse_qs, urlparse

        u = urlparse(url)
        q = parse_qs(u.query)
        if "fail" in q:
            raise LinkError("这是直播（或还没开始的直播），不支持下载。")
        vid = u.path.rstrip("/").split("/")[-1]
        mins = float(q.get("min", ["10"])[0])
        return VideoInfo(
            platform=platform_of(url), video_id=vid, url=url, webpage_url=url,
            title=f"视频{vid}", uploader=None, duration=int(mins * 60),
        )


class Clock:
    def __init__(self, t: datetime):
        self.t = t

    def __call__(self) -> datetime:
        return self.t


def bili(vid: str, mins: float) -> str:
    return f"https://www.bilibili.com/video/{vid}?min={mins}"


class TestQuotaRules(unittest.TestCase):
    def test_day_boundary_is_2am(self):
        self.assertEqual(quota.media_day(datetime(2026, 11, 23, 1, 59), 2), date(2026, 11, 22))
        self.assertEqual(quota.media_day(datetime(2026, 11, 23, 2, 0), 2), date(2026, 11, 23))
        self.assertEqual(quota.media_day(datetime(2026, 11, 22, 23, 30), 2), date(2026, 11, 22))

    def test_overdraft_allowed_while_quota_left(self):
        u = quota.make_usage(80 * 60, 2, QuotaConfig())
        d = quota.decide(u, 40 * 60)
        self.assertTrue(d.allowed)
        self.assertEqual(d.overdraft_seconds, 30 * 60)

    def test_rejected_when_minutes_used_up(self):
        u = quota.make_usage(90 * 60, 2, QuotaConfig())
        self.assertFalse(quota.decide(u, 60).allowed)

    def test_rejected_when_count_used_up(self):
        u = quota.make_usage(10 * 60, 5, QuotaConfig())
        self.assertFalse(quota.decide(u, 60).allowed)


class TestLinks(unittest.TestCase):
    def test_extract_from_bilibili_share_text(self):
        text = "【这是标题-哔哩哔哩】 https://b23.tv/AbCdEf"
        self.assertEqual(extract_url(text), "https://b23.tv/AbCdEf")

    def test_extract_strips_chinese_punctuation(self):
        self.assertEqual(
            extract_url("看这个：https://youtu.be/abc123，很好看"), "https://youtu.be/abc123"
        )

    def test_platforms(self):
        self.assertEqual(platform_of("https://www.bilibili.com/video/BV1xx"), "bilibili")
        self.assertEqual(platform_of("https://m.bilibili.com/video/BV1xx"), "bilibili")
        self.assertEqual(platform_of("https://b23.tv/xx"), "bilibili")
        self.assertEqual(platform_of("https://www.youtube.com/watch?v=x"), "youtube")
        self.assertEqual(platform_of("https://youtu.be/x"), "youtube")

    def test_other_sites_rejected(self):
        for url in ("https://www.douyin.com/video/1", "https://evilbilibili.com/x",
                    "https://bilibili.com.evil.com/x"):
            with self.assertRaises(LinkError, msg=url):
                platform_of(url)

    def test_no_link(self):
        with self.assertRaises(LinkError):
            extract_url("今天天气不错")

    def test_parse_rate(self):
        self.assertEqual(_parse_rate("5M"), 5 * 1024 * 1024)
        self.assertEqual(_parse_rate("800K"), 800 * 1024)


class TestService(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        tmp = Path(self.tmp.name)
        self.cfg = make_cfg(tmp)
        self.db = Database(tmp / "data" / "t.db")
        self.clock = Clock(datetime(2026, 11, 22, 20, 0))
        self.svc = MediaService(self.cfg, self.db, probe=FakeProbe(), now=self.clock)

    def tearDown(self):
        self.tmp.cleanup()

    def test_accept_and_summary(self):
        r = self.svc.submit(bili("BV1", 12))
        self.assertEqual(r.result, "accepted")
        self.assertIn("12/90 分钟", r.message)
        self.assertIn("1/5 个", r.message)

    def test_duplicate_does_not_count(self):
        self.svc.submit(bili("BV1", 12))
        r = self.svc.submit(bili("BV1", 12) + "&share_source=copy")
        self.assertEqual(r.result, "duplicate")
        self.assertEqual(self.svc.usage().used_count, 1)

    def test_count_limit(self):
        for i in range(5):
            self.assertEqual(self.svc.submit(bili(f"BV{i}", 3)).result, "accepted")
        r = self.svc.submit(bili("BV9", 3))
        self.assertEqual(r.result, "rejected")
        self.assertIn("5 个名额", r.message)

    def test_overdraft_then_reject(self):
        self.assertEqual(self.svc.submit(bili("A", 80)).result, "accepted")
        r = self.svc.submit(bili("B", 40))  # 只剩 10 分钟，但仍放行
        self.assertEqual(r.result, "accepted")
        self.assertIn("透支", r.message)
        r = self.svc.submit(bili("C", 1))
        self.assertEqual(r.result, "rejected")

    def test_long_video_on_fresh_day_allowed(self):
        # 比每天总额度还长的视频（2 小时的课），新的一天第一个仍然能下
        self.assertEqual(self.svc.submit(bili("LONG", 120)).result, "accepted")

    def test_failed_items_refund_quota_and_can_resubmit(self):
        r = self.svc.submit(bili("BV1", 30))
        self.db.mark_failed(r.item["id"], "网络错误")
        self.assertEqual(self.svc.usage().used_seconds, 0)
        self.assertEqual(self.svc.submit(bili("BV1", 30)).result, "accepted")

    def test_day_rollover_at_2am(self):
        for i in range(5):
            self.svc.submit(bili(f"BV{i}", 3))
        self.clock.t = datetime(2026, 11, 23, 1, 59)  # 还是 22 号
        self.assertEqual(self.svc.submit(bili("X", 3)).result, "rejected")
        self.clock.t = datetime(2026, 11, 23, 2, 0)   # 23 号了
        r = self.svc.submit(bili("X", 3))
        self.assertEqual(r.result, "accepted")
        self.assertEqual(r.item["media_day"], "2026-11-23")

    def test_probe_error_is_rejected_cleanly(self):
        r = self.svc.submit(bili("LIVE", 0) + "&fail=1")
        self.assertEqual(r.result, "rejected")
        self.assertIn("直播", r.message)

    def test_non_supported_site(self):
        r = self.svc.submit("https://www.douyin.com/video/123")
        self.assertEqual(r.result, "rejected")

    def test_status_shape(self):
        self.svc.submit(bili("BV1", 5))
        s = self.svc.status()
        self.assertEqual(s["media_day"], "2026-11-22")
        self.assertEqual(len(s["today"]), 1)
        self.assertEqual(len(s["pending"]), 1)


class FakeDownloader:
    def __init__(self, fail_ids=(), height=1080):
        self.fail_ids = set(fail_ids)
        self.height = height
        self.calls = []

    def download(self, url, platform, day):
        self.calls.append((url, platform, day))
        if any(f in url for f in self.fail_ids):
            raise RuntimeError("ERROR: 模拟的下载失败")
        return DownloadResult(file_path=f"/media/{day}/x.mp4", height=self.height)


class FakeNotifier:
    def __init__(self):
        self.messages = []

    def send(self, text):
        self.messages.append(text)


class TestWorker(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        tmp = Path(self.tmp.name)
        self.cfg = make_cfg(tmp)
        self.db = Database(tmp / "data" / "t.db")
        self.svc = MediaService(
            self.cfg, self.db, probe=FakeProbe(), now=Clock(datetime(2026, 11, 22, 20, 0))
        )

    def tearDown(self):
        self.tmp.cleanup()

    def test_success_failure_and_cookie_warning(self):
        self.svc.submit(bili("OK1", 5))
        self.svc.submit(bili("BAD", 5))
        dl = FakeDownloader(fail_ids=["BAD"], height=480)
        n = FakeNotifier()
        w = DownloadWorker(self.cfg, self.db, dl, n)

        while w._process_one():
            pass

        rows = {r["video_id"]: r for r in self.db.items_for_day(date(2026, 11, 22))}
        self.assertEqual(rows["OK1"]["status"], "done")
        self.assertEqual(rows["BAD"]["status"], "failed")
        self.assertNotIn("ERROR:", rows["BAD"]["error"])
        self.assertTrue(any("cookie" in m for m in n.messages))   # 480P 提醒
        self.assertTrue(any("下载失败" in m for m in n.messages))
        # 失败的那个退还额度
        self.assertEqual(self.svc.usage().used_count, 1)
        # 下载顺序 = 提交顺序，日期 = 提交时的日期
        self.assertEqual([c[2] for c in dl.calls], [date(2026, 11, 22)] * 2)

    def test_requeue_after_crash(self):
        self.svc.submit(bili("A", 5))
        self.db.claim_next()  # 模拟下载到一半程序崩了
        self.assertEqual(self.db.requeue_interrupted(), 1)
        self.assertEqual(self.db.pending_items()[0]["status"], "queued")


if __name__ == "__main__":
    unittest.main()
