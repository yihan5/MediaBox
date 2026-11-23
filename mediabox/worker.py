"""后台下载线程：一次只下一个，按提交顺序依次处理。"""

from __future__ import annotations

import logging
import threading
from datetime import date

from .config import Config
from .db import Database
from .downloader import Downloader, friendly_error
from .notify import Notifier
from .service import fmt_duration

log = logging.getLogger(__name__)


class DownloadWorker(threading.Thread):
    def __init__(self, cfg: Config, db: Database, downloader: Downloader, notifier: Notifier):
        super().__init__(name="download-worker", daemon=True)
        self.cfg = cfg
        self.db = db
        self.downloader = downloader
        self.notifier = notifier
        self._wake_event = threading.Event()
        self._stop_event = threading.Event()

    def wake(self) -> None:
        """有新链接加入时调用，让线程立刻开始干活，而不是等下一次轮询。"""
        self._wake_event.set()

    def stop(self) -> None:
        self._stop_event.set()
        self._wake_event.set()

    def run(self) -> None:
        n = self.db.requeue_interrupted()
        if n:
            log.info("上次有 %d 个下载被中断，已重新排队。", n)
        while not self._stop_event.is_set():
            try:
                worked = self._process_one()
            except Exception:  # noqa: BLE001 —— 线程不能因为任何意外退出
                log.exception("下载线程出现意外错误")
                worked = False
            if not worked:
                # 没活干：最多等 30 秒，或者被 wake() 叫醒
                self._wake_event.wait(timeout=30)
                self._wake_event.clear()

    def _process_one(self) -> bool:
        item = self.db.claim_next()
        if item is None:
            return False

        title = item["title"]
        log.info("开始下载 #%s《%s》", item["id"], title)
        try:
            result = self.downloader.download(
                item["url"], item["platform"], date.fromisoformat(item["media_day"])
            )
        except Exception as e:  # noqa: BLE001
            err = friendly_error(e)
            log.warning("下载失败 #%s《%s》：%s", item["id"], title, err)
            self.db.mark_failed(item["id"], err)
            self.notifier.send(f"❌ 下载失败：《{title}》\n原因：{err}\n这一个不计入今天的额度。")
            return True

        self.db.mark_done(item["id"], result.file_path, result.height)
        log.info("下载完成 #%s → %s", item["id"], result.file_path)

        msg = f"✅ 已下好：《{title}》（{fmt_duration(item['duration'])}）\n文件夹：{item['media_day']}"
        if result.height:
            msg += f"\n画质：{result.height}P"
        # B 站 cookie 过期时不会报错，只会悄悄降到 480P，所以这里主动检查
        min_h = self.cfg.download.bilibili_min_expected_height
        if item["platform"] == "bilibili" and result.height and result.height < min_h:
            msg += (
                f"\n⚠️ 画质只有 {result.height}P，B 站 cookie 可能过期了（或者没配置），"
                f"请重新导出 cookies 文件。"
            )
        self.notifier.send(msg)
        return True
