"""额度规则。这是整个软件的「规矩」，故意写得很短、很直白，方便你随时核对。

规则：
1. 「一天」从 day_starts_at_hour（默认凌晨 2 点）开始算，不是从零点。
   凌晨 1:30 提交的链接，算在前一天。
2. 每天最多 daily_count 个（默认 5 个），总时长最多 daily_minutes（默认 90 分钟）。
3. 透支：只要提交时「已用时长 < 上限」且「已用个数 < 上限」，就放行，
   哪怕这个视频本身比剩余时长还长。超出的部分不会从第二天扣。
4. 失败的下载不计入额度（统计时排除 status = failed 的记录）。
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from datetime import date, datetime, timedelta

from .config import QuotaConfig


def media_day(ts: datetime, day_starts_at_hour: int) -> date:
    """某个时间点属于「哪一天」。凌晨 2 点前的时间算前一天。"""
    return (ts - timedelta(hours=day_starts_at_hour)).date()


@dataclass
class QuotaUsage:
    used_seconds: int
    used_count: int
    limit_seconds: int
    limit_count: int

    @property
    def remaining_seconds(self) -> int:
        return max(0, self.limit_seconds - self.used_seconds)

    @property
    def remaining_count(self) -> int:
        return max(0, self.limit_count - self.used_count)

    def to_dict(self) -> dict:
        return {
            "used_minutes": minutes(self.used_seconds),
            "limit_minutes": self.limit_seconds // 60,
            "remaining_minutes": minutes(self.remaining_seconds, round_up=False),
            "used_count": self.used_count,
            "limit_count": self.limit_count,
            "remaining_count": self.remaining_count,
        }

    def summary(self) -> str:
        return (
            f"今天已用 {minutes(self.used_seconds)}/{self.limit_seconds // 60} 分钟，"
            f"{self.used_count}/{self.limit_count} 个"
        )


@dataclass
class QuotaDecision:
    allowed: bool
    reason: str = ""       # 被拒绝时的原因
    overdraft_seconds: int = 0  # 放行但超出剩余时长的部分


def minutes(seconds: int, round_up: bool = True) -> int:
    """秒 -> 分钟。已用时长向上取整（不低估），剩余时长向下取整（不高估）。"""
    if round_up:
        return math.ceil(seconds / 60)
    return seconds // 60


def make_usage(used_seconds: int, used_count: int, cfg: QuotaConfig) -> QuotaUsage:
    return QuotaUsage(
        used_seconds=used_seconds,
        used_count=used_count,
        limit_seconds=cfg.daily_minutes * 60,
        limit_count=cfg.daily_count,
    )


def decide(usage: QuotaUsage, duration_seconds: int) -> QuotaDecision:
    if usage.used_count >= usage.limit_count:
        return QuotaDecision(False, f"今天的 {usage.limit_count} 个名额已经用完了。")
    if usage.used_seconds >= usage.limit_seconds:
        return QuotaDecision(
            False,
            f"今天的 {usage.limit_seconds // 60} 分钟已经用完了"
            f"（已用 {minutes(usage.used_seconds)} 分钟）。",
        )
    overdraft = max(0, duration_seconds - usage.remaining_seconds)
    return QuotaDecision(True, overdraft_seconds=overdraft)
