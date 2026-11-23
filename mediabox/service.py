"""业务逻辑：提交链接、查询状态。和网页框架无关，接口层（app.py）只是薄薄一层包装。"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import datetime
from typing import Callable

from . import quota
from .config import Config
from .db import Database, row_to_dict, submit_lock
from .downloader import LinkError, VideoInfo, extract_url, platform_of

log = logging.getLogger(__name__)


@dataclass
class SubmitResult:
    result: str            # accepted / rejected / duplicate
    message: str           # 给人看的一句话，dsh 可以直接转述
    item: dict | None = None
    quota: dict = field(default_factory=dict)

    def to_dict(self) -> dict:
        return {
            "result": self.result,
            "message": self.message,
            "item": self.item,
            "quota": self.quota,
        }


def fmt_duration(seconds: int) -> str:
    m, s = divmod(int(seconds), 60)
    h, m = divmod(m, 60)
    if h:
        return f"{h}小时{m}分"
    if m:
        return f"{m}分{s:02d}秒" if s else f"{m}分钟"
    return f"{s}秒"


class MediaService:
    def __init__(
        self,
        cfg: Config,
        db: Database,
        probe: Callable[[str], VideoInfo],
        wake_worker: Callable[[], None] = lambda: None,
        now: Callable[[], datetime] = datetime.now,
    ):
        self.cfg = cfg
        self.db = db
        self.probe = probe
        self.wake_worker = wake_worker
        self.now = now  # 可替换，方便测试「凌晨 1:59」这类情况

    def today(self):
        return quota.media_day(self.now(), self.cfg.quota.day_starts_at_hour)

    def usage(self, day=None) -> quota.QuotaUsage:
        day = day or self.today()
        s, c = self.db.usage_for_day(day)
        return quota.make_usage(s, c, self.cfg.quota)

    # ------------------------------------------------------------------

    def submit(self, text: str) -> SubmitResult:
        # 1) 时间以「收到请求的这一刻」为准，后面解析花了几秒也不影响算哪一天
        submitted_at = self.now()
        day = quota.media_day(submitted_at, self.cfg.quota.day_starts_at_hour)

        # 2) 取链接、查平台（很快，不联网）
        try:
            url = extract_url(text)
            platform_of(url)
        except LinkError as e:
            return SubmitResult("rejected", str(e), quota=self.usage(day).to_dict())

        # 3) 先粗查一次额度：已经用完就不用再花几秒去解析链接了
        pre = self.usage(day)
        pre_decision = quota.decide(pre, 0)
        if not pre_decision.allowed:
            return SubmitResult(
                "rejected", f"{pre_decision.reason}{pre.summary()}。", quota=pre.to_dict()
            )

        # 4) 解析链接（联网，几秒钟）。放在锁外面，免得一个慢请求卡住所有请求
        try:
            info = self.probe(url)
        except LinkError as e:
            return SubmitResult("rejected", str(e), quota=self.usage(day).to_dict())
        except Exception as e:  # noqa: BLE001
            log.exception("解析链接时出现意外错误")
            return SubmitResult(
                "rejected", f"解析链接时出错：{e}", quota=self.usage(day).to_dict()
            )

        # 5) 查重 + 精确查额度 + 写入，必须一起完成
        with submit_lock:
            dup = self.db.find_active_duplicate(info.platform, info.video_id)
            if dup is not None:
                status_text = {
                    "queued": "正在排队",
                    "downloading": "正在下载",
                    "done": f"已经在 {dup['media_day']} 下载过了",
                }.get(dup["status"], dup["status"])
                return SubmitResult(
                    "duplicate",
                    f"《{dup['title']}》{status_text}，不重复下载，也不扣额度。",
                    item=row_to_dict(dup),
                    quota=self.usage(day).to_dict(),
                )

            usage = self.usage(day)
            decision = quota.decide(usage, info.duration)
            if not decision.allowed:
                return SubmitResult(
                    "rejected",
                    f"{decision.reason}《{info.title}》（{fmt_duration(info.duration)}）没有加入。"
                    f"{usage.summary()}。",
                    quota=usage.to_dict(),
                )

            item_id = self.db.insert_item(
                platform=info.platform,
                video_id=info.video_id,
                url=info.url,
                webpage_url=info.webpage_url,
                title=info.title,
                uploader=info.uploader,
                duration=info.duration,
                media_day=day,
                created_at=submitted_at,
            )

        self.wake_worker()

        after = self.usage(day)
        msg = f"已加入：《{info.title}》（{fmt_duration(info.duration)}）。{after.summary()}。"
        if decision.overdraft_seconds > 0:
            msg += (
                f"这个视频比剩余时长多了 {quota.minutes(decision.overdraft_seconds)} 分钟，"
                f"按透支规则放行，今天的时长额度就此用完。"
            )
        return SubmitResult(
            "accepted", msg, item=row_to_dict(self.db.get(item_id)), quota=after.to_dict()
        )

    # ------------------------------------------------------------------

    def status(self) -> dict:
        day = self.today()
        usage = self.usage(day)
        return {
            "media_day": day.isoformat(),
            "day_starts_at_hour": self.cfg.quota.day_starts_at_hour,
            "quota": usage.to_dict(),
            "summary": usage.summary(),
            "today": [row_to_dict(r) for r in self.db.items_for_day(day)],
            "pending": [row_to_dict(r) for r in self.db.pending_items()],
            "recent_failures": [row_to_dict(r) for r in self.db.recent_failures()],
        }
